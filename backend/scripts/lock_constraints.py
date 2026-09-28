"""Make the backend image install the dependency set CI tests (#694).

CI and the E2E lane install `requirements.lock` with `--require-hashes`. The
Docker image cannot: the lock deliberately leaves out the OCR stack
(torch / docling / transformers), and `--require-hashes` is all-or-nothing, so
it cannot cover a hashed lock plus an unhashed OCR install. Before #694 the
image therefore installed the unlocked `requirements.txt`, every transitive
dependency floated, and `genai-prices` 0.1.x reached the deployed image while
CI still pinned 0.0.66. pydantic-ai then swallowed a TypeError and every
`llm_usage` row recorded 0 tokens for two months (#689).

The Dockerfile uses this script like this:

    pip install --index-url https://download.pytorch.org/whl/cpu "torch>=2.5,<3"
    python scripts/lock_constraints.py constraints requirements.lock > /tmp/lock-constraints.txt
    python scripts/lock_constraints.py pin torch >> /tmp/lock-constraints.txt
    pip install -c /tmp/lock-constraints.txt -r requirements.txt
    python scripts/lock_constraints.py verify requirements.lock

`constraints` turns the lock into a hash-free pip constraints file. pip
switches to hash-checking mode as soon as any constraint carries a `--hash`,
so the hashes must go. A constraint does not add a package to the install; it
only pins a package if something needs it. So a package missing from the lock
(the OCR stack) installs normally, while every package the lock does pin,
including any the OCR stack depends on, must resolve to the locked version or
the build fails. The OCR stack's OTHER dependencies (numpy, scipy,
huggingface-hub, tokenizers, safetensors, opencv, ...) are not in the lock and
still float.

`pin torch` prints `torch==<installed version>` (e.g. `torch==2.14.0+cpu`).
Appending it to the constraints stops the constrained install from
backtracking onto a PyPI torch, which on Linux is the CUDA build.

`verify` runs after the last install. It fails the build if any installed
package that the lock pins is at a different version, which catches anything
the constrained resolve did not touch. It also fails the build if any
`nvidia-*` or `cuda-*` distribution is installed, i.e. if CUDA got in anyway.

`constraints` and `pin` use only the standard library, because they run before
requirements.txt is installed. `verify` runs after it and needs `packaging`,
which requirements.txt lists for that reason.
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from importlib import metadata
from typing import Callable, Iterable, Optional

# A requirement line in a uv-compiled lock: `name==version [; marker] [\]`.
# Continuation lines (`--hash=...`, `# via ...`) are indented.
_PIN = re.compile(
    r"^(?P<name>[A-Za-z0-9][A-Za-z0-9._-]*)"
    r"(?:\[[^\]]*\])?"
    r"==(?P<version>[^\s;\\]+)"
    r"\s*(?:;\s*(?P<marker>[^\\]+?))?"
    r"\s*\\?\s*$"
)

# Distributions that only arrive with a CUDA build of torch.
_CUDA_PREFIXES = ("nvidia-", "cuda-")


@dataclass(frozen=True)
class LockedPin:
    name: str
    version: str
    marker: Optional[str] = None

    def constraint(self) -> str:
        # Constraints may not carry extras, so none are emitted.
        line = f"{self.name}=={self.version}"
        return f"{line} ; {self.marker}" if self.marker else line


def parse_lock(text: str) -> list[LockedPin]:
    """Return every pinned package in a uv-compiled, hash-pinned lock.

    Raises ValueError on a top-level line it does not recognise, so a format
    change breaks the build loudly instead of silently dropping pins.
    """
    pins: list[LockedPin] = []
    for lineno, raw in enumerate(text.splitlines(), start=1):
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        if raw[0].isspace():
            # `--hash=...` continuation of the previous pin.
            continue
        match = _PIN.match(raw)
        if match is None:
            raise ValueError(f"requirements.lock:{lineno}: unrecognised line: {raw!r}")
        marker = match.group("marker")
        pins.append(
            LockedPin(
                name=match.group("name"),
                version=match.group("version"),
                marker=marker.strip() if marker else None,
            )
        )
    if not pins:
        raise ValueError("requirements.lock: no pinned packages found")
    return pins


def constraints_text(pins: list[LockedPin]) -> str:
    return "".join(pin.constraint() + "\n" for pin in pins)


def installed_pin(name: str, version_of: Callable[[str], Optional[str]]) -> str:
    """`name==<installed version>`, or ValueError if it is not installed."""
    version = version_of(name)
    if version is None:
        raise ValueError(f"{name} is not installed; nothing to pin")
    return f"{name}=={version}"


def find_drift(
    pins: list[LockedPin],
    version_of: Callable[[str], Optional[str]],
    marker_applies: Callable[[str], bool],
) -> tuple[list[str], int]:
    """Compare installed versions against the lock.

    Returns (problems, checked). `version_of(name)` returns the installed
    version or None. A locked package that is not installed is not drift: a
    constraint only applies when something needs the package. A locked package
    installed at another version is.
    """
    from packaging.version import Version

    problems: list[str] = []
    checked = 0
    for pin in pins:
        if pin.marker and not marker_applies(pin.marker):
            continue
        installed = version_of(pin.name)
        if installed is None:
            continue
        checked += 1
        if Version(installed) != Version(pin.version):
            problems.append(f"{pin.name}: installed {installed}, lock pins {pin.version}")
    return problems, checked


def cuda_distributions(names: Iterable[str]) -> list[str]:
    """The installed distributions that mean a CUDA torch got into the image."""
    from packaging.utils import canonicalize_name

    return sorted({n for n in map(canonicalize_name, names) if n.startswith(_CUDA_PREFIXES)})


def _installed_version(name: str) -> Optional[str]:
    try:
        return metadata.version(name)
    except metadata.PackageNotFoundError:
        return None


def _verify(pins: list[LockedPin]) -> int:
    from packaging.markers import Marker

    problems, checked = find_drift(
        pins,
        version_of=_installed_version,
        marker_applies=lambda marker: Marker(marker).evaluate(),
    )
    cuda = cuda_distributions(d.metadata["Name"] for d in metadata.distributions())
    if cuda:
        problems.append(
            "CUDA distributions installed (torch must be the CPU build): " + ", ".join(cuda)
        )
    if problems:
        print(
            "The installed set does not match requirements.lock (#694):\n  "
            + "\n  ".join(problems),
            file=sys.stderr,
        )
        return 1
    if checked == 0:
        print(
            "No package pinned by requirements.lock is installed; refusing to pass.",
            file=sys.stderr,
        )
        return 1
    print(
        f"requirements.lock: {checked} installed packages match their locked versions; no CUDA distributions."
    )
    return 0


_USAGE = "usage: lock_constraints.py constraints <requirements.lock> | verify <requirements.lock> | pin <distribution>"


def main(argv: list[str]) -> int:
    if len(argv) != 3 or argv[1] not in {"constraints", "verify", "pin"}:
        print(_USAGE, file=sys.stderr)
        return 2
    command, arg = argv[1], argv[2]
    if command == "pin":
        try:
            print(installed_pin(arg, _installed_version))
        except ValueError as exc:
            print(exc, file=sys.stderr)
            return 1
        return 0
    with open(arg, encoding="utf-8") as fh:
        pins = parse_lock(fh.read())
    if command == "constraints":
        sys.stdout.write(constraints_text(pins))
        return 0
    return _verify(pins)


if __name__ == "__main__":
    sys.exit(main(sys.argv))

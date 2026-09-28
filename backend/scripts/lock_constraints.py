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

    pip install --index-url https://download.pytorch.org/whl/cpu "torch>=2.5,<3" torchvision
    python scripts/lock_constraints.py constraints requirements.lock > /tmp/lock-constraints.txt
    python scripts/lock_constraints.py pin torch torchvision >> /tmp/lock-constraints.txt
    pip install -c /tmp/lock-constraints.txt -r requirements.txt
    python scripts/lock_constraints.py verify requirements.lock
    python scripts/lock_constraints.py cpu-torch

`constraints` turns the lock into a hash-free pip constraints file. pip
switches to hash-checking mode as soon as any constraint carries a `--hash`,
so the hashes must go. A constraint does not add a package to the install; it
only pins a package if something needs it. So a package missing from the lock
(the OCR stack) installs normally, while every package the lock does pin,
including any the OCR stack depends on, must resolve to the locked version or
the build fails. The OCR stack's OTHER dependencies (numpy, scipy,
huggingface-hub, tokenizers, safetensors, opencv, ...) are not in the lock and
still float.

`pin torch torchvision` prints one `name==<installed version>` line per
distribution (e.g. `torch==2.14.0+cpu`). Appending them to the constraints
stops the constrained install from backtracking onto a PyPI torch or
torchvision, which on Linux are the CUDA builds. torchvision needs the pin as
much as torch does (#700): docling depends on it, so without its own CPU-index
install and pin the constrained step pulled the PyPI (CUDA) torchvision in
next to the CPU torch, and `torchvision::nms` did not exist at runtime.

`verify` runs after the last install. It fails the build if any installed
package that the lock pins is at a different version, which catches anything
the constrained resolve did not touch. It also fails the build if any
`nvidia-*` or `cuda-*` distribution is installed, i.e. if CUDA got in anyway.

`cpu-torch` also runs after the last install (#700). It fails the build unless
torch and torchvision are both `+cpu` builds and `torchvision.ops.nms` runs on
a tiny tensor. The PyPI torchvision next to the CPU torch passes every other
check: it brings no nvidia-* distribution, and its `torch==<version>`
requirement is satisfied by the `+cpu` torch, so `verify` and `pip check` are
both clean. It then raises `operator torchvision::nms does not exist` (at
`import torchvision` for torch 2.14 / torchvision 0.29), so docling's layout
model cannot load and every scanned PDF silently fell back to tesseract.

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


def installed_pins(names: Iterable[str], version_of: Callable[[str], Optional[str]]) -> list[str]:
    """`installed_pin` for each name; ValueError if any is missing."""
    return [installed_pin(name, version_of) for name in names]


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


# The torch distributions the image installs from the CPU wheel index (#700).
CPU_TORCH = ("torch", "torchvision")


def cpu_build_problems(version_of: Callable[[str], Optional[str]]) -> list[str]:
    """Why the installed torch / torchvision are not both CPU wheels, if they are not.

    The CPU index tags its wheels with the `+cpu` local version. The PyPI Linux
    wheels carry no local version and are the CUDA builds.
    """
    from packaging.version import Version

    problems = []
    for name in CPU_TORCH:
        version = version_of(name)
        if version is None:
            problems.append(f"{name} is not installed")
        elif Version(version).local != "cpu":
            problems.append(f"{name} {version} is not a +cpu build")
    return problems


def nms_keeps() -> list[int]:
    """Run torchvision.ops.nms on three boxes; the CPU build keeps [0, 2].

    Box 1 overlaps box 0 (IoU ~0.68) and scores lower, so it is suppressed.
    A torchvision built for another torch raises
    `operator torchvision::nms does not exist` here, either at the import or
    at the call depending on the version pair.
    """
    import torch
    from torchvision.ops import nms

    boxes = torch.tensor([[0.0, 0.0, 10.0, 10.0], [1.0, 1.0, 11.0, 11.0], [20.0, 20.0, 30.0, 30.0]])
    scores = torch.tensor([0.9, 0.8, 0.7])
    return nms(boxes, scores, iou_threshold=0.5).tolist()


def _cpu_torch() -> int:
    problems = cpu_build_problems(_installed_version)
    if not problems:
        try:
            keeps = nms_keeps()
        except Exception as exc:  # the #700 failure is a RuntimeError from the op lookup
            problems.append(f"torchvision.ops.nms failed: {type(exc).__name__}: {exc}")
        else:
            if keeps != [0, 2]:
                problems.append(f"torchvision.ops.nms kept {keeps}, expected [0, 2]")
    if problems:
        print(
            "torch / torchvision are not a working CPU pair (#700):\n  " + "\n  ".join(problems),
            file=sys.stderr,
        )
        return 1
    print(
        "CPU torch pair OK: "
        + ", ".join(f"{name} {_installed_version(name)}" for name in CPU_TORCH)
        + "; torchvision.ops.nms runs."
    )
    return 0


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


_USAGE = (
    "usage: lock_constraints.py constraints <requirements.lock> | verify <requirements.lock>"
    " | pin <distribution>... | cpu-torch"
)


def main(argv: list[str]) -> int:
    command = argv[1] if len(argv) > 1 else None
    if command == "cpu-torch" and len(argv) == 2:
        return _cpu_torch()
    if command == "pin" and len(argv) >= 3:
        try:
            print("\n".join(installed_pins(argv[2:], _installed_version)))
        except ValueError as exc:
            print(exc, file=sys.stderr)
            return 1
        return 0
    if len(argv) != 3 or command not in {"constraints", "verify"}:
        print(_USAGE, file=sys.stderr)
        return 2
    arg = argv[2]
    with open(arg, encoding="utf-8") as fh:
        pins = parse_lock(fh.read())
    if command == "constraints":
        sys.stdout.write(constraints_text(pins))
        return 0
    return _verify(pins)


if __name__ == "__main__":
    sys.exit(main(sys.argv))

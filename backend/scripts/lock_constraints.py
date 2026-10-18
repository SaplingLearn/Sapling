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

    pip install --no-deps --index-url https://download.pytorch.org/whl/cpu \
        --report /tmp/cpu-index-report.json "torch>=2.5,<3" torchvision
    python scripts/lock_constraints.py constraints requirements.lock > /tmp/lock-constraints.txt
    python scripts/lock_constraints.py pin >> /tmp/lock-constraints.txt
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

`pin` prints `name==<version>` for every distribution the CPU-index step
installed, read from the report that step wrote (`pip install --report`,
default path CPU_INDEX_REPORT), e.g. `torch==2.14.0+cpu`. Appending them to
the constraints stops the constrained install from replacing any of them with
a PyPI build, which for torch and torchvision on Linux is the CUDA one. The
list comes from pip, not from this script, so a package added to the CPU-index
step is pinned without touching anything else. torchvision is why this exists
(#700): docling depends on it, so without its own CPU-index install and pin
the constrained step pulled the PyPI build in next to the CPU torch, and
`torchvision::nms` did not exist at runtime.

The CPU-index step runs with `--no-deps`, so it installs only what it names.
Their dependencies (numpy, pillow, sympy, ...) come from the constrained step
at the lock's versions where the lock pins them. Nothing is installed twice,
and no snapshot pin can contradict a lock pin: the lock leaves out the OCR
stack (tests/dependency_manifest.py OCR_STACK). If the two ever did name
different versions of one package, pip's resolver fails the build.

`cpu-torch` also runs after the last install (#700). It fails the build unless
the torch stack is CPU-only and actually works:
  - `torch.version.cuda` is None;
  - no nvidia-*/cuda-* distribution is installed;
  - torch and every installed distribution whose Requires-Dist names torch
    (torchvision, torchaudio, ...) carries no CUDA/ROCm local version and does
    not require an nvidia-*/cuda-* distribution. A missing local version is
    accepted: the CPU index's aarch64 wheels have often shipped without `+cpu`;
  - `torchvision.ops.nms` runs on a tiny tensor.
The last check is the one that catches #700. The PyPI torchvision next to the
CPU torch has no local version and no CUDA dependency, its `torch==2.14.0`
requirement is satisfied by `2.14.0+cpu` (so `pip check` is clean), and it
still raises `operator torchvision::nms does not exist`. docling's layout model
then could not load, and scanned PDFs silently fell back to tesseract.

`constraints` and `pin` use only the standard library, because they run before
requirements.txt is installed. `verify` runs after it and needs `packaging`,
which requirements.txt lists for that reason.
"""

from __future__ import annotations

import json
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


# Where the Dockerfile's CPU-index step writes `pip install --report`; `pin`
# reads it. The Dockerfile has to spell the path out too (this script is not
# in the image yet at that step); tests/test_docker_lock_install.py checks the
# two agree.
CPU_INDEX_REPORT = "/tmp/cpu-index-report.json"


def report_pins(report: dict, version_of: Callable[[str], Optional[str]]) -> list[str]:
    """`name==version` for every distribution a `pip install --report` installed.

    ValueError if the report installed nothing, or if a distribution is no
    longer installed at the version the report recorded (the pin would then
    describe something that is not in the image).
    """
    pins = []
    for item in report.get("install") or []:
        name, version = item["metadata"]["name"], item["metadata"]["version"]
        installed = version_of(name)
        if installed != version:
            raise ValueError(
                f"{name}: the CPU-index step installed {version}, now {installed or 'missing'}"
            )
        pins.append(f"{name}=={version}")
    if not pins:
        raise ValueError("the CPU-index install report lists nothing installed; nothing to pin")
    return pins


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


# Local version labels of GPU builds: `+cu121`, `+cu130`, `+rocm6.2`, ...
_GPU_LOCAL = re.compile(r"^(cu\d|cuda|rocm)")


@dataclass(frozen=True)
class InstalledDist:
    name: str
    version: str
    requires: tuple[str, ...] = ()


def torch_stack(dists: Iterable[InstalledDist]) -> list[InstalledDist]:
    """torch itself plus every distribution whose Requires-Dist names torch."""
    from packaging.requirements import InvalidRequirement, Requirement
    from packaging.utils import canonicalize_name

    def names_torch(line: str) -> bool:
        try:
            return canonicalize_name(Requirement(line).name) == "torch"
        except InvalidRequirement:
            return False

    return [
        d
        for d in dists
        if canonicalize_name(d.name) == "torch" or any(names_torch(r) for r in d.requires)
    ]


def cpu_build_problems(
    dists: Iterable[InstalledDist],
    torch_cuda: Optional[str],
    marker_applies: Callable[[str], bool],
) -> list[str]:
    """Why the installed torch stack is not CPU-only, if it is not.

    `torch_cuda` is `torch.version.cuda` (None on a CPU build). A missing local
    version is fine; a CUDA/ROCm one is not, and neither is a Requires-Dist on
    an nvidia-*/cuda-* distribution whose marker applies here.
    """
    from packaging.requirements import InvalidRequirement, Requirement
    from packaging.utils import canonicalize_name
    from packaging.version import InvalidVersion, Version

    dists = list(dists)
    problems = []
    if not any(canonicalize_name(d.name) == "torch" for d in dists):
        problems.append("torch is not installed")
    if torch_cuda is not None:
        problems.append(f"torch was built for CUDA {torch_cuda} (torch.version.cuda)")
    for d in torch_stack(dists):
        try:
            local = Version(d.version).local
        except InvalidVersion:
            problems.append(f"{d.name}: cannot parse its version {d.version!r}")
            continue
        if local and _GPU_LOCAL.match(local):
            problems.append(f"{d.name} {d.version} is a GPU build (+{local})")
        for line in d.requires:
            try:
                req = Requirement(line)
            except InvalidRequirement:
                continue
            if canonicalize_name(req.name).startswith(_CUDA_PREFIXES) and (
                req.marker is None or marker_applies(str(req.marker))
            ):
                problems.append(f"{d.name} {d.version} requires {line}")
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


def _installed_dists() -> list[InstalledDist]:
    seen: dict[str, InstalledDist] = {}
    for d in metadata.distributions():
        name = d.metadata["Name"]
        if name and name.lower() not in seen:  # first on sys.path wins, as for imports
            seen[name.lower()] = InstalledDist(name, d.version, tuple(d.requires or ()))
    return list(seen.values())


def _marker_applies(marker: str) -> bool:
    from packaging.markers import Marker

    # Requirements behind an extra (`extra == "cuda"`) only count if requested,
    # and nothing here requests extras.
    return Marker(marker).evaluate({"extra": ""})


def _cpu_torch() -> int:
    dists = _installed_dists()
    problems = []
    try:
        import torch

        torch_cuda = torch.version.cuda
    except Exception as exc:
        problems.append(f"import torch failed: {type(exc).__name__}: {exc}")
        torch_cuda = None
    problems += cpu_build_problems(dists, torch_cuda, _marker_applies)
    cuda = cuda_distributions(d.name for d in dists)
    if cuda:
        problems.append("CUDA distributions installed: " + ", ".join(cuda))
    if not problems:
        try:
            keeps = nms_keeps()
        except Exception as exc:  # #700: RuntimeError "operator torchvision::nms does not exist"
            problems.append(f"torchvision.ops.nms failed: {type(exc).__name__}: {exc}")
        else:
            if keeps != [0, 2]:
                problems.append(f"torchvision.ops.nms kept {keeps}, expected [0, 2]")
    if problems:
        print(
            "The torch stack is not a working CPU-only build (#700):\n  " + "\n  ".join(problems),
            file=sys.stderr,
        )
        return 1
    print(
        "CPU torch stack OK: "
        + ", ".join(f"{d.name} {d.version}" for d in torch_stack(dists))
        + "; torch.version.cuda is None; torchvision.ops.nms runs."
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
    " | pin [<pip install --report file>] | cpu-torch"
)


def main(argv: list[str]) -> int:
    command = argv[1] if len(argv) > 1 else None
    if command == "cpu-torch" and len(argv) == 2:
        return _cpu_torch()
    if command == "pin" and len(argv) in (2, 3):
        path = argv[2] if len(argv) == 3 else CPU_INDEX_REPORT
        try:
            with open(path, encoding="utf-8") as fh:
                print("\n".join(report_pins(json.load(fh), _installed_version)))
        except (OSError, ValueError, KeyError) as exc:
            print(f"pin: {path}: {type(exc).__name__}: {exc}", file=sys.stderr)
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

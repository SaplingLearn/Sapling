"""Shared readers for requirements.txt / requirements-worker.txt /
requirements.lock / the Dockerfile.

Used by tests/test_requirements_lock.py (#163) and
tests/test_docker_lock_install.py (#694), so the two guards agree on what the
manifest says and which packages are the OCR stack.
"""

import os

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

from scripts.lock_constraints import LockedPin, parse_lock

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Installed in the image from the CPU wheel index (torch, torchvision) or
# unconstrained, and deliberately left out of requirements.lock. torchvision is
# not a direct requirement (docling pulls it in), but a lock pin on it would
# fight the CPU-index install (#700).
OCR_STACK = frozenset({"torch", "torchvision", "docling", "transformers"})


def read(name: str) -> str:
    with open(os.path.join(BACKEND, name), encoding="utf-8") as fh:
        return fh.read()


def requirement_lines(name: str = "requirements.txt") -> list[str]:
    """`name`'s requirement lines with comments and blanks stripped."""
    out = []
    for raw in read(name).splitlines():
        line = raw.split("#", 1)[0].strip()
        if line:
            out.append(line)
    return out


def requirements() -> list[Requirement]:
    """requirements.txt: the API image's set, which requirements.lock pins."""
    return [Requirement(line) for line in requirement_lines()]


#: The worker-only extras (#116): the OCR stack, installed on top of
#: requirements.txt in the Dockerfile's `heavy` stage, never in the `api` image.
WORKER_REQUIREMENTS = "requirements-worker.txt"


def worker_requirements() -> list[Requirement]:
    return [Requirement(line) for line in requirement_lines(WORKER_REQUIREMENTS)]


def lock_pins() -> dict[str, LockedPin]:
    """requirements.lock pins keyed by canonical name."""
    return {canonicalize_name(p.name): p for p in parse_lock(read("requirements.lock"))}

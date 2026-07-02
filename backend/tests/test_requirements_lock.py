"""
Guards the dependency pinning + lockfile (#163).

- requirements.txt must give every runtime dependency an explicit constraint
  (no bare, floating package lines).
- requirements.lock must pin (==) every non-OCR top-level dependency named in
  requirements.txt, so the lock can't silently fall behind the manifest.
"""
import os
import re

_BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Installed separately from the CPU wheel index / excluded from the fast lock.
_OCR_STACK = {"torch", "docling", "transformers"}

_SPEC = re.compile(r"[<>=!~]")


def _normalize(name: str) -> str:
    return name.strip().lower().replace("_", "-")


def _requirement_lines() -> list[str]:
    path = os.path.join(_BACKEND, "requirements.txt")
    with open(path, encoding="utf-8") as fh:
        out = []
        for raw in fh:
            line = raw.split("#", 1)[0].strip()
            if line:
                out.append(line)
        return out


def _base_name(line: str) -> str:
    # strip extras "[...]" then the version specifier
    name = re.sub(r"\[.*?\]", "", line)
    name = _SPEC.split(name, 1)[0]
    return _normalize(name)


def test_every_requirement_has_an_explicit_constraint():
    bare = [ln for ln in _requirement_lines() if not _SPEC.search(ln)]
    assert bare == [], f"unpinned dependencies: {bare}"


def test_lock_pins_every_non_ocr_requirement():
    with open(os.path.join(_BACKEND, "requirements.lock"), encoding="utf-8") as fh:
        lock = fh.read().lower()
    missing = []
    for line in _requirement_lines():
        name = _base_name(line)
        if name in _OCR_STACK:
            continue
        if not re.search(rf"^{re.escape(name)}==", lock, re.MULTILINE):
            missing.append(name)
    assert missing == [], f"in requirements.txt but not pinned in requirements.lock: {missing}"


def test_lock_is_hash_pinned():
    with open(os.path.join(_BACKEND, "requirements.lock"), encoding="utf-8") as fh:
        lock = fh.read()
    # A real lock carries per-artifact hashes for --require-hashes installs.
    assert "--hash=sha256:" in lock

"""
Guards the dependency pinning + lockfile (#163).

- requirements.txt must give every runtime dependency *some* version specifier
  (no bare package lines). Upper bounds are not enforced — see
  test_no_requirement_is_completely_unconstrained for why.
- requirements.lock must pin (==) every non-OCR top-level dependency named in
  requirements.txt, so the lock can't silently fall behind the manifest. This is
  the check that catches a dep added to the manifest without regenerating the
  lock (e.g. #97's `redis`, added while this branch was forked).
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


def test_no_requirement_is_completely_unconstrained():
    """Every requirement carries *some* version specifier — no bare `foo` lines.

    Deliberately named for what it checks. It does NOT require an upper bound:
    `pydantic-ai-slim[google]>=0.0.20` passes. Four deps (pydantic-ai-slim,
    logfire, sse-starlette, pydantic-evals) intentionally float their major —
    they are fast-moving and pre-1.0, where a `<1` ceiling would be both
    arbitrary (pre-1.0 breaks on minor bumps anyway) and a silent blocker on
    security updates. Reproducibility comes from requirements.lock, which pins
    every one of them to an exact hashed version; requirements.txt is the
    manifest of intent, not the install plan.
    """
    bare = [ln for ln in _requirement_lines() if not _SPEC.search(ln)]
    assert bare == [], f"dependencies with no version specifier at all: {bare}"


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

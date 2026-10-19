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

import re

from packaging.utils import canonicalize_name

from tests.dependency_manifest import OCR_STACK, lock_pins, read, requirement_lines, requirements

_SPEC = re.compile(r"[<>=!~]")


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
    bare = [ln for ln in requirement_lines() if not _SPEC.search(ln)]
    assert bare == [], f"dependencies with no version specifier at all: {bare}"


def test_lock_pins_every_non_ocr_requirement():
    pins = lock_pins()
    missing = []
    for req in requirements():
        name = canonicalize_name(req.name)
        if name not in OCR_STACK and name not in pins:
            missing.append(name)
    assert missing == [], f"in requirements.txt but not pinned in requirements.lock: {missing}"


def test_lock_is_hash_pinned():
    lock = read("requirements.lock")
    # A real lock carries per-artifact hashes for --require-hashes installs.
    assert "--hash=sha256:" in lock

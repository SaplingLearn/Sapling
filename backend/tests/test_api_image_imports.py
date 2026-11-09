"""The API image boots without the worker-only dependencies (#116, phase 2).

The Dockerfile's `api` target installs requirements.txt under the lock's
constraints and nothing else: no torch, no Docling, no transformers, no
Chromium. Only the `worker` (and, until the cut-over, the default `full`)
target carries those (requirements-worker.txt). This test proves the API
process does not need them to import or to start serving.

It runs in a fresh interpreter with a `sys.meta_path` blocker installed before
anything is imported. The blocker refuses:

  * every top-level module that an installed distribution provides when NONE
    of the distributions providing it is pinned in requirements.lock. That is
    the API image's dependency set exactly (the lock is what the `api` target
    installs), so on a developer venv that also carries the OCR stack this
    blocks torch, docling, transformers, numpy, cv2, ... as the image would.
    In CI (which installs only the lock) nothing is installed to block, and
    the explicit list below still is.
  * `playwright` explicitly. The wheel is in the lock, but the API image has
    no Chromium, so the API must not need Playwright to boot: BU SSO is the
    one caller and it imports it lazily (services/gradescope_service.py).

A blocked import raises ImportError, the same as a missing package. Code that
already treats the OCR stack as optional (extraction_backends, gradescope)
keeps degrading exactly as it does in an image without it; anything that
imports one of them at module level fails this test.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]

#: Blocked even when the lock pins them (see the module docstring), and named
#: so CI proves them blocked even where they are not installed at all.
ALWAYS_BLOCKED = (
    "torch", "torchvision", "docling", "transformers", "playwright",
)

_PROBE = r"""
import importlib.abc
import importlib.metadata as md
import json
import sys

from packaging.utils import canonicalize_name

sys.path.insert(0, ".")
from scripts.lock_constraints import parse_lock

ALWAYS = set(json.loads(sys.argv[1]))
locked = {canonicalize_name(p.name) for p in parse_lock(open("requirements.lock").read())}
TOOLING = {"pip", "setuptools", "wheel"}
blocked = set(ALWAYS)
for module, dists in md.packages_distributions().items():
    if module in sys.stdlib_module_names:
        continue
    # Packaging tooling ships with the base image, not with requirements.
    if any(canonicalize_name(d) in TOOLING for d in dists):
        continue
    if not any(canonicalize_name(d) in locked for d in dists):
        blocked.add(module)
# The test's own harness modules are allowed through.
blocked -= {"packaging", "scripts"}
attempts = []


class Blocker(importlib.abc.MetaPathFinder):
    def find_spec(self, name, path=None, target=None):
        top = name.partition(".")[0]
        if top in blocked:
            attempts.append(top)
            raise ImportError(f"{top} is not in the API image (blocked by test_api_image_imports)")
        return None


sys.meta_path.insert(0, Blocker())
# Anything already imported (sitecustomize, .pth hooks) would bypass the finder.
preloaded = sorted(m for m in list(sys.modules) if m.partition(".")[0] in blocked)
assert not preloaded, f"imported before the blocker: {preloaded}"

from unittest.mock import AsyncMock, patch

import main  # noqa: E402  the import under test

from fastapi.testclient import TestClient

# Startup with the network seams stubbed: the bucket bootstrap and the key
# canary talk to Supabase, the sweeper and DBOS are off-by-config anyway.
with patch("main.ensure_bucket_exists", new=AsyncMock()), \
     patch("main.verify_encryption_key"), \
     patch("main.start_sweeper"), \
     patch("main.init_dbos"):
    with TestClient(main.app) as client:
        health = client.get("/api/health")

loaded = sorted({m.partition(".")[0] for m in sys.modules} & blocked)
print(json.dumps({
    "status": health.status_code,
    "body": health.json(),
    "blocked_count": len(blocked),
    "blocked_sample": sorted(blocked & ALWAYS),
    "attempted": sorted(set(attempts)),
    "loaded": loaded,
}))
"""


def _env() -> dict[str, str]:
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(("SAPLING_MODEL_MODE", "SAPLING_FUNCTION_HANDLERS"))}
    env.update({
        "APP_ENV": "test",
        "ENCRYPTION_KEY": "0" * 64,
        "SUPABASE_URL": "http://127.0.0.1:9",
        "SUPABASE_SERVICE_KEY": "test-service-key",
        "GEMINI_API_KEY": "test-gemini-key",
        "ANTHROPIC_API_KEY": "test-anthropic-key",
        "SESSION_SECRET": "s" * 48,
        "POSTHOG_PROJECT_TOKEN": "",
        "LOGFIRE_TOKEN": "",
        "PYTHONDONTWRITEBYTECODE": "1",
    })
    return env


def test_api_imports_and_starts_without_the_worker_only_dependencies():
    out = subprocess.run(
        [sys.executable, "-c", _PROBE, json.dumps(ALWAYS_BLOCKED)],
        cwd=BACKEND, env=_env(), capture_output=True, text=True, timeout=300,
    )
    assert out.returncode == 0, (
        "the API failed to import or start with the worker-only packages blocked:\n"
        + out.stderr[-4000:]
    )
    result = json.loads(out.stdout.strip().splitlines()[-1])
    assert result["status"] == 200 and result["body"]["status"] == "ok"
    assert result["blocked_sample"] == sorted(ALWAYS_BLOCKED)
    # Nothing blocked slipped in through a path the finder does not see.
    assert result["loaded"] == []

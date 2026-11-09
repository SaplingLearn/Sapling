"""`.railway/railway.ts`: the worker service shares every variable its code
paths read (#116 review).

The worker runs the API's code (boot checks, the job handlers, the agents)
from a separate Railway service, so a variable set only on the API is silently
missing in the worker: an OCR engine choice, a Redis cache, a model-slot
rollback, a flag kill switch. This derives the env names those modules read
(the same grep a reviewer would run) and requires each one to be in the
worker's reference list, or in EXCLUDED with the reason it is not on a worker
path. A new `os.getenv` in one of WORKER_PATH_MODULES fails here until it is
shared or excluded.
"""
from __future__ import annotations

import re
from pathlib import Path

from agents._providers import _DEFAULTS
from services.feature_flags import REGISTRY

BACKEND = Path(__file__).resolve().parents[1]
RAILWAY_TS = BACKEND.parent / ".railway" / "railway.ts"

#: Modules a worker imports and runs: boot (worker/__main__.py::boot, config),
#: the database + crypto layer, the job handlers (document.process,
#: document.index, course_context.refresh, jobs.prune) and what they call.
WORKER_PATH_MODULES = (
    "config.py",
    "agents/_providers.py",
    "agents/_run.py",
    "agents/usage.py",
    "db/connection.py",
    "db/scope.py",
    "db/user_jwt.py",
    "services/encryption.py",
    "services/encryption_canary.py",
    "services/extraction_service.py",
    "services/extraction_backends/*.py",
    "services/cache.py",
    "services/document_jobs.py",
    "services/staged_jobs.py",
    "services/document_pipeline.py",
    "services/document_indexing.py",
    "services/course_context_service.py",
    "services/rag_service.py",
    "services/chunk_visibility.py",
    "services/durable.py",
    "services/events_service.py",
    "services/posthog_client.py",
    "services/analytics_consent.py",
    "services/feature_flags.py",
    "services/jobs.py",
    "routes/documents.py",
)

#: Read in those modules but not on a worker's path, or not the API's to share.
EXCLUDED = {
    "ACCOUNT_SYNC_INBOUND_TOKEN": "admin account-copy routes only",
    "ACCOUNT_SYNC_PEER_TOKEN": "admin account-copy routes only",
    "ACCOUNT_SYNC_PEER_URL": "admin account-copy routes only",
    "ALLOWED_EMAIL_DOMAINS": "sign-in only",
    "CANOPY_METRICS_TOKEN": "the internal metrics route only",
    "DB_USER_SCOPE_SHADOW_SAMPLE_RATE": "per-request RLS shadow; a worker runs as service role",
    "EMAIL_ASSET_BASE_URL": "email routes only; no job sends email",
    "EMAIL_FROM": "email routes only; no job sends email",
    "EMAIL_REPLY_TO": "email routes only; no job sends email",
    "RESEND_API_KEY": "email routes only; no job sends email",
    "FRONTEND_URL": "OAuth redirects and cookies (HTTP only)",
    "SECURE_COOKIES": "session cookies (HTTP only)",
    "GOOGLE_AUTH_REDIRECT_URI": "OAuth (HTTP only)",
    "GOOGLE_CLIENT_ID": "OAuth (HTTP only)",
    "GOOGLE_CLIENT_SECRET": "OAuth (HTTP only)",
    "GOOGLE_REDIRECT_URI": "OAuth (HTTP only)",
    "PORT": "the worker serves nothing",
    "JOBS_LEASE_SECONDS": "the worker's own setting, set on the worker service itself (worker/__main__.py); document_jobs reads the same value on both sides",
    "GIT_COMMIT_SHA": "build metadata; Railway sets RAILWAY_GIT_COMMIT_SHA per service",
    "RAILWAY_GIT_COMMIT_SHA": "Railway sets it on every service itself",
    "OCR_ASYNC_ENABLED": "the upload route's request-path choice, read by the API only",
    "UPLOAD_JOB_PICKUP_GRACE_SECONDS": "the API's wait for a worker to pick an upload up",
    "SAPLING_FUNCTION_HANDLERS": "E2E function mode only, never set on Railway",
}

#: Agent tasks a worker runs (document.process, page OCR, course context).
WORKER_AGENT_TASKS = {"classifier", "summary", "concepts", "syllabus", "ocr_vision",
                      "course_summary"}

_READS = (
    re.compile(r'(?:getenv|environ\.get|env\.get)\(\s*"([A-Z][A-Z0-9_]+)"'),
    re.compile(r'environ\[\s*"([A-Z][A-Z0-9_]+)"\s*\]'),
    re.compile(r'^\s*[A-Z0-9_]*_ENV\s*=\s*"([A-Z][A-Z0-9_]+)"', re.MULTILINE),
)


def _env_reads() -> dict[str, set[str]]:
    out: dict[str, set[str]] = {}
    for pattern in WORKER_PATH_MODULES:
        paths = sorted(BACKEND.glob(pattern))
        assert paths, f"{pattern} matches nothing: update WORKER_PATH_MODULES"
        for path in paths:
            text = path.read_text()
            for rx in _READS:
                for name in rx.findall(text):
                    out.setdefault(name, set()).add(str(path.relative_to(BACKEND)))
    return out


def _shared() -> set[str]:
    """The names railway.ts references, evaluated the way the file builds them."""
    ts = RAILWAY_TS.read_text()

    def array(name: str) -> list[str]:
        m = re.search(rf"const {name}(?:: string\[\])? = \[(.*?)\]", ts, re.S)
        assert m, f"{name} is gone from railway.ts"
        body = re.sub(r"//[^\n]*", "", m.group(1))
        return re.findall(r'"([A-Za-z0-9_]+)"', body)

    names = set(array("BOOT_VARIABLES")) | set(array("HANDLER_VARIABLES"))
    names |= {f"SAPLING_FLAG_{k.upper()}" for k in array("FLAG_KILL_SWITCHES")}
    for task in array("WORKER_AGENT_TASKS"):
        names |= {f"SAPLING_MODEL_{task.upper()}", f"SAPLING_MODEL_FALLBACK_{task.upper()}"}
    # The composition the worker's env actually gets.
    assert re.search(r"const SHARED_VARIABLES = \[\s*\.\.\.BOOT_VARIABLES,\s*\.\.\.HANDLER_VARIABLES,"
                     r"\s*\.\.\.FLAG_KILL_SWITCHES,\s*\.\.\.MODEL_SLOT_VARIABLES,\s*\]", ts)
    assert re.search(r"SHARED_VARIABLES\.map\(\(name\) => \[name, ref\(name\)\]\)", ts)
    return names


def test_every_env_read_on_a_worker_path_is_shared_or_excluded():
    shared = _shared()
    missing = {name: sorted(where) for name, where in _env_reads().items()
               if name not in shared and name not in EXCLUDED}
    assert not missing, (
        "read on a worker code path but not shared with the worker in "
        f".railway/railway.ts (or listed in EXCLUDED with a reason): {missing}")


def test_the_boot_requirements_and_the_review_list_are_shared():
    shared = _shared()
    for name in ("APP_ENV", "SUPABASE_URL", "SUPABASE_SERVICE_KEY", "ENCRYPTION_KEY",
                 "SESSION_SECRET", "ANTHROPIC_API_KEY", "GEMINI_API_KEY",
                 "SAPLING_MODEL_MODE", "OCR_ENGINE", "GEMINI_VISION_OCR_ENABLED",
                 "GEMINI_VISION_OCR_MAX_PAGES", "GOT_OCR_ENABLED", "GOT_OCR_MODEL_PATH",
                 "REDIS_URL", "EVENTS_LOGGING_ENABLED", "EVENTS_QUEUE_MAX",
                 "POSTHOG_PERSONAL_API_KEY", "POSTHOG_PROJECT_TOKEN"):
        assert name in shared, name


def test_every_server_flag_kill_switch_is_shared():
    shared = _shared()
    for key in REGISTRY:
        if key.startswith("hide_"):
            continue  # nav flags: the frontend's, never read by a job
        assert f"SAPLING_FLAG_{key.upper()}" in shared, key


def test_the_worker_agent_slots_are_shared_and_real():
    assert WORKER_AGENT_TASKS <= set(_DEFAULTS), WORKER_AGENT_TASKS - set(_DEFAULTS)
    shared = _shared()
    for task in WORKER_AGENT_TASKS:
        assert f"SAPLING_MODEL_{task.upper()}" in shared
        assert f"SAPLING_MODEL_FALLBACK_{task.upper()}" in shared


def test_exclusions_are_not_also_shared():
    assert not (set(EXCLUDED) & _shared())

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

import logfire
from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from config import FRONTEND_URL, MAX_AVATAR_SIZE, PORT, STORAGE_BUCKET, validate_config

# App-wide log format. Per-request log lines (with request_id, duration,
# status) are emitted from RequestIDMiddleware; this just sets the
# baseline so any other module's logger inherits a consistent shape.
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

from routes import graph, learn, quiz, calendar, social, extract, auth, documents, flashcards, study_guide, feedback, careers, onboarding, gradebook, gradescope, notes, academics, gamification
from routes.profile import router as profile_router
from routes.admin import router as admin_router
from routes.admin_analytics import router as admin_analytics_router
from routes.newsletter import router as newsletter_router
from services import quiz_config, quiz_errors
from services.logfire_scrubber import EXTRA_PATTERNS, scrub_value
from services import otel_fastapi_compat
from services.request_context import RequestIDMiddleware, current_request_id
from services.storage_service import (
    ALLOWED_CONTENT_TYPES,
    ICON_CONTENT_TYPES,
    ensure_bucket_exists,
)
from services.durable import init_dbos, shutdown_dbos

try:
    from recost.frameworks.fastapi import RecostMiddleware
except ImportError:
    RecostMiddleware = None  # optional; tests/CI without recost package

load_dotenv(Path(__file__).with_name(".env"))

RECOST_PROJECT_ID = "eaf22d10-840d-494f-8513-2dcef769ace1"
recost_api_key = os.getenv("RECOST_API_KEY")

# Logfire: free local traces during dev; sends to logfire.pydantic.dev only
# if LOGFIRE_TOKEN is set. Safe to leave on in all environments.
#
# Scrubbing: Pydantic AI's instrumentation writes the full prompt text and
# model output to span attributes (gen_ai.prompt, all_messages_events,
# input/output.value, ...). For Sapling those carry user-uploaded document
# text — names, emails, student work — which we never want exfiltrated to
# logfire.pydantic.dev. ``scrub_value`` redacts those paths before egress,
# keeping a sha256 fingerprint of the body for debugging. ``EXTRA_PATTERNS``
# ensures the callback fires for prompt/completion/messages attribute names
# in addition to Logfire's built-in pattern set (password, secret, ...).
logfire.configure(
    send_to_logfire="if-token-present",
    service_name="sapling-backend",
    scrubbing=logfire.ScrubbingOptions(
        callback=scrub_value,
        extra_patterns=list(EXTRA_PATTERNS),
    ),
)
logfire.instrument_pydantic_ai()

# ── App lifespan: self-bootstrap external resources ─────────────────────────
#
# The avatars + cosmetics storage bucket is required by
# routes/profile.py::upload_user_avatar (and the cosmetic admin path).
# Issue #75 / PRs #84-#87 chased the symptom (uploads fail) before the
# real cause (the bucket never existed) surfaced in a Supabase audit.
# Creating it on startup makes new environments self-bootstrap and
# protects against the same class of "code expects a Supabase resource
# that no migration ever made" bugs.
#
# OPERATOR NOTE: ensure_bucket_exists treats a 409 (bucket already exists) as
# success and deliberately DOES NOT overwrite settings, so widening the MIME
# list below only takes effect on buckets this code creates. Environments whose
# bucket predates the change (staging/prod) need a one-off bucket update to add
# image/svg+xml before SVG icon uploads will work there.
@asynccontextmanager
async def _lifespan(_app: FastAPI):
    # #174: fail loudly at startup if required secrets are missing, before
    # serving any request, rather than booting and failing opaquely later.
    validate_config()
    await ensure_bucket_exists(
        STORAGE_BUCKET,
        public=True,  # required for unauthenticated <img src> reads
        file_size_limit=MAX_AVATAR_SIZE,
        # The bucket holds BOTH avatars/cosmetics (ALLOWED_CONTENT_TYPES) and
        # admin-uploaded achievement icons (ICON_CONTENT_TYPES, which adds
        # image/svg+xml). Supabase Storage enforces the bucket's MIME list even
        # for service-role writes, so a bootstrap list missing svg+xml means
        # storage_service.validate_icon passes and the PUT then 400s — the
        # admin sees "502 Icon upload failed (Supabase 400)". Union both.
        allowed_mime_types=sorted(ALLOWED_CONTENT_TYPES | ICON_CONTENT_TYPES),
    )
    # #116/#118: start the fire-and-forget observability drain thread so LLM
    # usage + event rows flush off the request path.
    from services import events_service
    events_service.start_worker()
    # ADR 0011 / #154: construct + launch DBOS when DBOS_ENABLED=true; no-op
    # passthrough otherwise. Fails loudly (raises) if the operator opted in
    # and launch fails — see services/durable.py::init_dbos.
    init_dbos()
    yield
    # Stop the drain thread and flush anything still queued so the last batch
    # of usage rows isn't lost on shutdown.
    events_service.shutdown()
    shutdown_dbos()


def _drop_request_arguments(_request, _attributes):
    """request_attributes_mapper for instrument_fastapi: never log endpoint args.

    FastAPI instrumentation otherwise records the parsed endpoint arguments —
    the request body and query/path params — on the request span under
    ``fastapi.arguments.values``. In Sapling those carry student content: chat
    messages, note bodies, quiz answers, uploaded document text. That path is
    NOT covered by the ``scrub_value`` callback (Logfire routes only a subset of
    attributes through scrubbing, and a body field named e.g. ``body`` matches
    no risky pattern), so the only safe move is to drop the arguments entirely.
    Returning ``None`` tells Logfire to record no argument attributes at all.

    We keep the method, route template, status, and latency — which is what the
    request trace is actually for. (The full URL and rendered span message do
    still carry the raw query string; Sapling query params are ids/enums plus a
    couple of low-sensitivity search terms, never prompts/completions/document
    text — see docs/observability-logging-tracking.md.)
    """
    return None


app = FastAPI(title="Sapling API", version="1.0.0", lifespan=_lifespan)

# Emit a span per HTTP request (method, route, status, latency) so request
# traces and errors show up in Logfire alongside the Pydantic AI agent spans.
# Like configure()/instrument_pydantic_ai() above, this is always on but inert
# without LOGFIRE_TOKEN (send_to_logfire="if-token-present").
#
# Egress safety (layered): request bodies/params are dropped via
# _drop_request_arguments; request/response headers are not captured
# (capture_headers=False); and the separate arguments/endpoint spans are off
# (extra_spans=False). No student content leaves the process on request spans.
# Must run BEFORE instrument_fastapi: on FastAPI >= 0.138 the otel route
# resolver raises AttributeError on any wrong-method request, turning every
# 405 into a 500. See services/otel_fastapi_compat.py for the full analysis.
otel_fastapi_compat.install_route_details_guard()

logfire.instrument_fastapi(
    app,
    capture_headers=False,
    extra_spans=False,
    request_attributes_mapper=_drop_request_arguments,
)

if recost_api_key and RecostMiddleware is not None:
    app.add_middleware(
        RecostMiddleware,
        api_key=recost_api_key,
        project_id=RECOST_PROJECT_ID,
    )

_extra = [o.strip() for o in os.getenv("CORS_ORIGINS", "").split(",") if o.strip()]
_allowed_origins = list({
    FRONTEND_URL.rstrip("/"),
    "http://localhost:3000",
    "https://saplinglearn.com",
    "https://www.saplinglearn.com",
    *_extra,
} - {""})

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Add LAST so it's the outermost middleware (runs first on the way in,
# last on the way out — exactly what we want for stamping every request,
# tagging every response, and emitting one structured log line per
# request, including ones that fail inside CORS.
app.add_middleware(RequestIDMiddleware)


# #540 A3: on /api/quiz/* paths, quiz_errors.error_content wraps errors in
# the coded envelope (QuizAPIError raise sites carry precise codes; plain
# HTTPExceptions fall back to a status-derived one); everywhere else it
# returns the legacy {detail, request_id} shape unchanged.


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    rid = getattr(request.state, "request_id", None) or current_request_id()
    content = quiz_errors.error_content(
        request.url.path,
        exc.status_code,
        exc.detail,
        rid,
        code=getattr(exc, "code", None),
        machine_detail=getattr(exc, "machine_detail", None),
    )
    # Preserve headers the raise site set (e.g. Retry-After on a 429) —
    # dropping them would strip the only machine-readable part of a
    # throttling response.
    headers = dict(getattr(exc, "headers", None) or {})
    if rid:
        headers["X-Request-ID"] = rid
    return JSONResponse(
        status_code=exc.status_code,
        content=content,
        headers=headers,
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    rid = getattr(request.state, "request_id", None) or current_request_id()
    code, message = quiz_errors.validation_error_code(exc.errors())
    if code is quiz_errors.QuizErrorCode.QUIZ_COUNT_OUT_OF_RANGE:
        message = (
            f"Quizzes can have between {quiz_config.QUIZ_MIN_QUESTIONS} "
            f"and {quiz_config.QUIZ_MAX_QUESTIONS} questions."
        )
    content = quiz_errors.error_content(
        request.url.path, 422, exc.errors(), rid,
        code=code, message=message, machine_detail=exc.errors(),
    )
    return JSONResponse(
        status_code=422,
        content=content,
        headers={"X-Request-ID": rid} if rid else {},
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    logging.getLogger("main").exception("Unhandled exception")
    rid = getattr(request.state, "request_id", None) or current_request_id()
    content = quiz_errors.error_content(
        request.url.path, 500, "Internal server error.", rid,
    )
    return JSONResponse(
        status_code=500,
        content=content,
        headers={"X-Request-ID": rid} if rid else {},
    )

app.include_router(graph.router,       prefix="/api/graph")
app.include_router(learn.router,       prefix="/api/learn")
app.include_router(quiz.router,        prefix="/api/quiz")
app.include_router(calendar.router,    prefix="/api/calendar")
app.include_router(social.router,      prefix="/api/social")
app.include_router(extract.router,     prefix="/api/extract")
app.include_router(auth.router,        prefix="/api/auth")
app.include_router(documents.router,   prefix="/api/documents")
app.include_router(flashcards.router,  prefix="/api/flashcards")
app.include_router(study_guide.router, prefix="/api/study-guide")
app.include_router(feedback.router,    prefix="/api")
app.include_router(careers.router,     prefix="/api/careers")
app.include_router(onboarding.router,  prefix="/api/onboarding")
app.include_router(profile_router,     prefix="/api/profile")
app.include_router(admin_router,       prefix="/api/admin")
app.include_router(admin_analytics_router, prefix="/api/admin/analytics")
app.include_router(newsletter_router,  prefix="/api/newsletter")
app.include_router(gradebook.router,   prefix="/api/gradebook")
app.include_router(gradescope.router,  prefix="/api/gradescope")
app.include_router(notes.router,       prefix="/api/notes")
app.include_router(academics.router,   prefix="/api", tags=["academics"])
app.include_router(gamification.router, prefix="/api/gamification")


@app.get("/api/health")
def health():
    # model_mode surfaces the #391 seam state (real | function | cassette) so
    # E2E journeys (#387) can fail fast with a pointed message when the stack
    # was booted in real mode, instead of running agent stages against live
    # Gemini. (The RAG embed path sits below the seam — #439 — so "function"
    # here vouches for the agent stages, not every byte of egress.) Not a
    # secret: it names a mode, not a key.
    from agents._providers import _model_mode
    from config import build_commit

    return {
        "status": "ok",
        "service": "sapling-backend",
        "model_mode": _model_mode(),
        # The deployed commit, so a promotion can verify the code it merged is
        # actually the code answering (#516). "unknown" off Railway.
        "commit": build_commit(),
    }


@app.get("/api/users")
def list_users(request: Request):
    """List users with decrypted display names.

    The display name now lives on `user_profiles` (migration 0024 moved it out of
    `users`); it is 🔒 encrypted there. Resolve it via services.profiles, which
    decrypts. `users.room_id` was likewise renamed to `current_room_id` by 0024 —
    select the new column but keep the legacy `room_id` response key.

    Requires an authenticated session: this returns decrypted legal names,
    so an unauthenticated caller must never reach the roster (401).
    """
    from services.auth_guard import get_session_user_id
    get_session_user_id(request)  # 401 if unauthenticated
    from db.connection import table
    from services.profiles import get_display_names
    rows = table("users").select("id,current_room_id")
    names = get_display_names([r.get("id") for r in rows if r.get("id")])
    users = [
        {
            "id": r.get("id"),
            "name": names.get(r.get("id"), ""),
            "room_id": r.get("current_room_id"),
        }
        for r in rows
    ]
    users.sort(key=lambda u: (u["name"] or "").lower())
    return {"users": users}


@app.get("/api/gemini-test")
def gemini_test(request: Request):
    """Admin-only Gemini connectivity check. Shows a clear error if the API
    key is missing/wrong.

    Gated behind `require_admin` (#198): every hit makes a real, billable
    agent round-trip, so an unauthenticated caller could burn Gemini quota at
    will and use the `{"ok": ...}` response as an oracle for whether the API
    key is configured. Only admins may trigger LLM spend here.
    """
    from services.auth_guard import require_admin
    require_admin(request)  # 403 unless the session belongs to an admin; 401 if unauthenticated
    from agents._run import run_agent_sync
    from agents.health import health_probe_agent
    from agents.usage import record_agent_usage
    try:
        result = record_agent_usage(
            run_agent_sync(
                health_probe_agent.run('Reply with exactly the text: Gemini OK')
            ),
            feature="health",
        )
        return {"ok": True, "reply": result.output.strip()}
    except Exception as e:
        return {"ok": False, "error": str(e)}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=PORT, reload=True)

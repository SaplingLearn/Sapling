import logging
import os
from contextlib import AsyncExitStack, asynccontextmanager
from pathlib import Path

import logfire
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, Request
from fastapi.encoders import jsonable_encoder
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
from routes.admin_flags import router as admin_flags_router
from routes.flags import router as flags_router
from routes.admin import router as admin_router
from routes.admin_analytics import router as admin_analytics_router
from routes.admin_documents import router as admin_documents_router
from routes.admin_jobs import router as admin_jobs_router
from routes.admin_llm import router as admin_llm_router
from routes.admin_email import router as admin_email_router
from routes.admin_accounts import router as admin_accounts_router
from routes.admin_account_sync import router as admin_account_sync_router
from routes.internal_account_sync import router as internal_account_sync_router
from routes.email import router as email_router
from routes.newsletter import router as newsletter_router
from routes.internal_metrics import router as internal_metrics_router
from routes.topic_checklist import router as topic_checklist_router
from services.quiz import config as quiz_config, errors as quiz_errors
from services.feature_flags import nav_feature_gate
from services.llm_budget import LLMBudgetExceeded
from db.scope import (
    ScopeUnavailable,
    ScopedAccessDenied,
    UnscopedQueryError,
    admin_service_route,
    service_route,
)
from services.logfire_scrubber import EXTRA_PATTERNS, scrub_value
from services import otel_fastapi_compat
from services.request_context import (
    RequestIDMiddleware,
    current_request_id,
    privacy_signal_in,
)
from services.encryption_canary import verify_encryption_key
from services.storage_service import (
    ALLOWED_CONTENT_TYPES,
    ICON_CONTENT_TYPES,
    ensure_bucket_exists,
)
from services.durable import init_dbos, shutdown_dbos
from services.index_sweeper import start_sweeper, stop_sweeper
from services.local_seed_watcher import (
    start_watcher as start_local_seed_watcher,
    stop_watcher as stop_local_seed_watcher,
)
from services import typesafe_client
from services import posthog_client

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
#
# Lifecycle shape (#771): every started resource registers its teardown on an
# AsyncExitStack the moment it starts, so a startup failure part-way through
# still tears down what already started, and shutdown unwinds in REVERSE start
# order. Sinks (PostHog, the events worker) start first so they stop LAST —
# after every producer that can still log_event (the seed watcher, the
# sweeper, DBOS workflows, upload post-roll work, tutor-router decisions) has
# stopped or drained. Add a new resource by starting it AND registering its
# teardown on the next line, at the position that keeps that order.
@asynccontextmanager
async def _lifespan(_app: FastAPI):
    # #771: the model mode is fixed for the life of the process from here on,
    # so the import-time agents and every per-call gate agree on it.
    from agents._providers import freeze_model_mode
    freeze_model_mode()
    # #174: fail loudly at startup if required secrets are missing, before
    # serving any request, rather than booting and failing opaquely later.
    validate_config()
    # Refuse to boot with an ENCRYPTION_KEY that isn't this database's: the
    # read helpers fail soft, so a mismatch otherwise surfaces as garbage reads
    # and writes the real environment can never decrypt.
    verify_encryption_key()
    async with AsyncExitStack() as stack:
        await _start(stack)
        yield


async def _start(stack: AsyncExitStack) -> None:
    """Start everything, registering each teardown as it starts (#771)."""
    # ADR 0028: optional; builds nothing (no threads, no network) when the
    # token is unset, under pytest/APP_ENV=test, or in function mode.
    # Drained, then its SDK flushed, LAST: every sink-feeding producer below
    # has stopped by then.
    posthog_client.initialize_posthog()
    stack.callback(posthog_client.shutdown_posthog)
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
    # usage + event rows flush off the request path. Stopped (and the queue
    # flushed) after every producer below, just before PostHog.
    from services import events_service
    events_service.start_worker()
    stack.callback(events_service.shutdown)
    # The decision seam's pooled Jev client (#642) for this loop: closed after
    # the tutor-router drain below, whose decisions still use it.
    stack.push_async_callback(typesafe_client.aclose_clients)
    # #117: the async DB seam's per-loop httpx.AsyncClient (built lazily on
    # first use, flag `async_db_client`); closed after every request-path
    # producer below has drained.
    from db import async_connection
    stack.push_async_callback(async_connection.aclose_clients)
    # Let in-flight tutor-router decisions finish before the client and the
    # events worker close: each one emits a decision.made row (bounded by the
    # router's own backstop).
    from services import tutor_router
    stack.push_async_callback(tutor_router.drain_inflight)
    # ADR 0011 / #154: construct + launch DBOS when DBOS_ENABLED=true; no-op
    # passthrough otherwise. Fails loudly (raises) if the operator opted in
    # and launch fails — see services/durable.py::init_dbos. Destroyed BEFORE
    # the events worker stops: its workflows log events. Registered BEFORE
    # init: a launch that raises part-way still gets destroyed (a no-op when
    # nothing launched).
    stack.callback(shutdown_dbos)
    init_dbos()
    # #759: let in-flight upload post-roll tasks (indexing, course context)
    # finish — bounded by drain_post_roll's own timeout. They log events and
    # may touch DBOS-decorated code, so they drain before DBOS is destroyed
    # (registered after it: the stack unwinds in reverse).
    from routes.documents import drain_post_roll
    stack.push_async_callback(drain_post_roll)
    # #482: drain the document indexing queue. Without this, a document whose
    # upload-time index attempt failed — or died with the process — would stay
    # out of retrieval for good. No-op outside real model mode.
    start_sweeper()
    stack.push_async_callback(stop_sweeper)
    # #715: on a developer's LOCAL stack only, copy the rich sample dataset
    # onto each Google account that signs in. Not started anywhere else.
    start_local_seed_watcher()
    stack.push_async_callback(stop_local_seed_watcher)
    # #672: the decision seam's backends moved from env vars to the
    # decision_router flag; say so if a deployment still sets the old ones.
    from services import decisions
    decisions.warn_removed_env()


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
    # `jsonable_encoder`, exactly as FastAPI's own default handler does it, and
    # for a reason that is invisible until it isn't: a Pydantic field or model
    # validator raising ValueError puts the EXCEPTION OBJECT into the error's
    # `ctx`, which `json.dumps` cannot serialize. Handing the raw list to
    # JSONResponse turns any such 422 into a 500 — the enveloped 4xx contract
    # (#540 A3) failing precisely when a route adds the kind of cross-field
    # rule the envelope exists to report. Encoded ONCE and reused, so the
    # payload and the machine detail can never disagree.
    errors = jsonable_encoder(exc.errors())
    # The quiz code and its student-facing sentence are for quiz routes only;
    # every other route keeps the plain {detail, request_id} 422.
    code, message = None, None
    if quiz_errors.is_quiz_path(request.url.path):
        code, message = quiz_errors.validation_error_code(errors)
    if code is quiz_errors.QuizErrorCode.QUIZ_COUNT_OUT_OF_RANGE:
        message = (
            f"Quizzes can have between {quiz_config.QUIZ_MIN_QUESTIONS} "
            f"and {quiz_config.QUIZ_MAX_QUESTIONS} questions."
        )
    content = quiz_errors.error_content(
        request.url.path, 422, errors, rid,
        code=code, message=message, machine_detail=errors,
    )
    return JSONResponse(
        status_code=422,
        content=content,
        headers={"X-Request-ID": rid} if rid else {},
    )


# #115 (RLS step 2, db/scope.py): the user-scoped client's three refusals. All
# three exist only once the `db_user_scope` flag is past `off`, and none of
# them ever falls back to the service role:
# - a user-scoped write PostgREST refused (RLS WITH CHECK / no grant) reads
#   as "not found", the same answer a row the policy hides already gives;
# - the user-scoped credential could not be built, or PostgREST rejected it
#   (key/kid mismatch after a rotation): 503, the operator's problem;
# - a request with no session subject reached the DB from a path not marked
#   service: 500, an unmarked public route (fail closed).
@app.exception_handler(ScopedAccessDenied)
async def scoped_access_denied_handler(request: Request, exc: ScopedAccessDenied):
    return await http_exception_handler(
        request, StarletteHTTPException(status_code=404, detail="Not found"),
    )


@app.exception_handler(ScopeUnavailable)
async def scope_unavailable_handler(request: Request, exc: ScopeUnavailable):
    return await http_exception_handler(
        request,
        StarletteHTTPException(status_code=503, detail="Service temporarily unavailable."),
    )


@app.exception_handler(UnscopedQueryError)
async def unscoped_query_handler(request: Request, exc: UnscopedQueryError):
    logging.getLogger("main").error("unscoped query refused: %s", exc)
    return await http_exception_handler(
        request, StarletteHTTPException(status_code=500, detail="Internal server error."),
    )


# #119: a student past today's LLM token budget (services/llm_budget.py). The
# exception IS a 429 HTTPException (so routes' `except HTTPException: raise`
# pass it through); this only adds `error.reset_at` for clients that want to
# say when it resets. Quiz routes convert it to their own coded 429 first.
@app.exception_handler(LLMBudgetExceeded)
async def llm_budget_exceeded_handler(request: Request, exc: LLMBudgetExceeded):
    rid = getattr(request.state, "request_id", None) or current_request_id()
    content = quiz_errors.error_content(
        request.url.path, exc.status_code, exc.detail, rid, code=exc.code,
    )
    if isinstance(content.get("error"), dict):
        content["error"]["reset_at"] = exc.reset_at_iso
    headers = dict(exc.headers or {})
    if rid:
        headers["X-Request-ID"] = rid
    return JSONResponse(status_code=exc.status_code, content=content, headers=headers)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    logging.getLogger("main").exception("Unhandled exception")
    rid = getattr(request.state, "request_id", None) or current_request_id()
    # ADR 0028: PostHog error tracking — queued, consent-checked on the
    # PostHog worker like every event. No-op when PostHog is off; message
    # redacted and no frame locals (posthog_client._scrub_event). The user is
    # whatever auth_guard stamped on request.state (#117 1b) — a users.id or
    # None. This handler runs in ServerErrorMiddleware, OUTSIDE
    # RequestIDMiddleware, whose per-request DNT/GPC contextvar is already
    # reset by now — so the signal is read off the request's own headers.
    posthog_client.capture_exception(
        exc,
        user_id=getattr(request.state, "user_id", None),
        request_id=rid,
        privacy_signal=privacy_signal_in(getattr(request, "headers", None) or {}),
    )
    content = quiz_errors.error_content(
        request.url.path, 500, "Internal server error.", rid,
    )
    return JSONResponse(
        status_code=500,
        content=content,
        headers={"X-Request-ID": rid} if rid else {},
    )

# #771: a hidden nav feature (`hide_<feature>` "on") 404s on its API too, not
# just in the nav. Which routers each flag gates — and the paths another
# visible surface still needs — is services/feature_flags.py::NAV_FEATURE_API.
#
# #115 (RLS step 2): routers whose DB calls run as the service role even when
# the `db_user_scope` flag puts every other request under the student's own
# token (docs/security/rls-step2-plan.md §3.2, §4.3). `_SVC` marks the
# request; `_ADMIN_SVC` also re-checks admin first once the flag is past
# `off`. Every router mounted below without one of these is user-scoped.
_SVC = [Depends(service_route)]
_ADMIN_SVC = [Depends(admin_service_route)]
app.include_router(graph.router,       prefix="/api/graph")
app.include_router(topic_checklist_router, prefix="/api/topic-checklist")
app.include_router(learn.router,       prefix="/api/learn")
app.include_router(quiz.router,        prefix="/api/quiz", dependencies=nav_feature_gate("/api/quiz"))
app.include_router(calendar.router,    prefix="/api/calendar", dependencies=nav_feature_gate("/api/calendar"))
# Social stays service role until step 2e: room_messages has no policies or
# grants yet, and invite-code join / owner transfer / room teardown /
# two-sided friendships are cross-user by design (plan §6.3: social last).
app.include_router(social.router,      prefix="/api/social", dependencies=nav_feature_gate("/api/social") + _SVC)
app.include_router(extract.router,     prefix="/api/extract")
# Auth flows run before (or instead of) a session: the OAuth callback's user
# upserts, POST /test-login (every Playwright journey signs in through it),
# /pending/*, /me's account read.
app.include_router(auth.router,        prefix="/api/auth", dependencies=_SVC)
app.include_router(documents.router,   prefix="/api/documents")
app.include_router(flashcards.router,  prefix="/api/flashcards", dependencies=nav_feature_gate("/api/flashcards"))
app.include_router(study_guide.router, prefix="/api/study-guide", dependencies=nav_feature_gate("/api/study-guide"))
app.include_router(feedback.router,    prefix="/api")
app.include_router(careers.router,     prefix="/api/careers", dependencies=_SVC)  # public; job_applications is service-only
app.include_router(onboarding.router,  prefix="/api/onboarding")
app.include_router(profile_router,     prefix="/api/profile")
# Mounted BEFORE admin_router so its specific /flags paths win over any
# generic admin_router route that could otherwise shadow them.
app.include_router(admin_flags_router, prefix="/api/admin/flags", dependencies=_ADMIN_SVC)
app.include_router(flags_router,       prefix="/api/flags")
# Admin account tools (seed by major / wipe / copy between environments).
# Mounted before the generic admin router so its /accounts paths win.
app.include_router(admin_accounts_router, prefix="/api/admin/accounts", dependencies=_ADMIN_SVC)
app.include_router(admin_account_sync_router, prefix="/api/admin/accounts", dependencies=_ADMIN_SVC)
# #116: the job queue's depth and dead letters (`jobs` is service-only).
# Mounted before the generic admin router so /jobs is never shadowed.
app.include_router(admin_jobs_router,  prefix="/api/admin/jobs", dependencies=_ADMIN_SVC)
# #119: per-user LLM budgets + the outage-drill state. Before admin_router.
app.include_router(admin_llm_router,   prefix="/api/admin/llm", dependencies=_ADMIN_SVC)
app.include_router(admin_router,       prefix="/api/admin", dependencies=_ADMIN_SVC)
app.include_router(admin_analytics_router, prefix="/api/admin/analytics", dependencies=_ADMIN_SVC)
app.include_router(admin_documents_router, prefix="/api/admin/documents", dependencies=_ADMIN_SVC)
app.include_router(admin_email_router, prefix="/api/admin/email", dependencies=_ADMIN_SVC)
app.include_router(newsletter_router,  prefix="/api/newsletter", dependencies=_SVC)  # public; newsletter_emails is service-only
# Public, no session: the unsubscribe page linked from every email (and the
# RFC 8058 one-click POST). Token-authenticated; see routes/email.py.
app.include_router(email_router,       prefix="/api/email", dependencies=_SVC)
app.include_router(gradebook.router,   prefix="/api/gradebook", dependencies=nav_feature_gate("/api/gradebook"))
app.include_router(gradescope.router,  prefix="/api/gradescope")
app.include_router(notes.router,       prefix="/api/notes", dependencies=nav_feature_gate("/api/notes"))
app.include_router(academics.router,   prefix="/api", tags=["academics"])
app.include_router(gamification.router, prefix="/api/gamification", dependencies=nav_feature_gate("/api/gamification"))
# Server-to-server (Canopy's hourly poll): bearer-token auth of its own, no user
# session, 404 unless CANOPY_METRICS_TOKEN is set. See routes/internal_metrics.py.
app.include_router(internal_metrics_router, prefix="/api/internal", dependencies=_SVC)
# Server-to-server account copy between staging and prod; own bearer token
# (ACCOUNT_SYNC_INBOUND_TOKEN, unset -> 404), never auth_guard.
app.include_router(internal_account_sync_router, prefix="/api/internal/account-sync", dependencies=_SVC)


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


@app.get("/api/gemini-test", dependencies=_ADMIN_SVC)
def gemini_test(request: Request):
    """Admin-only LLM connectivity check. Shows a clear error if the API
    key is missing/wrong. The path predates the Anthropic swap (ADR 0030); it
    now probes the agents' provider (`HEALTH_PROBE_MODEL`, a Claude model) and
    keeps its name for existing callers.

    Gated behind `require_admin` (#198): every hit makes a real, billable
    agent round-trip, so an unauthenticated caller could burn model quota at
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
                health_probe_agent.run('Reply with exactly the text: LLM OK')
            ),
            feature="health",
        )
        return {"ok": True, "reply": result.output.strip()}
    except Exception as e:
        return {"ok": False, "error": str(e)}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=PORT, reload=True)

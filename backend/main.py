import logging
import os
from pathlib import Path

import logfire
from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from config import FRONTEND_URL, PORT

# App-wide log format. Per-request log lines (with request_id, duration,
# status) are emitted from RequestIDMiddleware; this just sets the
# baseline so any other module's logger inherits a consistent shape.
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

from routes import graph, learn, quiz, calendar, social, extract, auth, documents, flashcards, study_guide, feedback, careers, onboarding, gradebook
from routes.profile import router as profile_router
from routes.admin import router as admin_router
from routes.newsletter import router as newsletter_router
from services.logfire_scrubber import EXTRA_PATTERNS, scrub_value
from services.request_context import RequestIDMiddleware, current_request_id

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

app = FastAPI(title="Sapling API", version="1.0.0")
logfire.instrument_fastapi(app)

if recost_api_key and RecostMiddleware is not None:
    app.add_middleware(
        RecostMiddleware,
        api_key=recost_api_key,
        project_id=RECOST_PROJECT_ID,
    )

app.add_middleware(
    CORSMiddleware,
    allow_origins=[FRONTEND_URL, "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Add LAST so it's the outermost middleware (runs first on the way in,
# last on the way out — exactly what we want for stamping every request,
# tagging every response, and emitting one structured log line per
# request, including ones that fail inside CORS.
app.add_middleware(RequestIDMiddleware)


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    rid = getattr(request.state, "request_id", None) or current_request_id()
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail, "request_id": rid},
        headers={"X-Request-ID": rid} if rid else {},
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    rid = getattr(request.state, "request_id", None) or current_request_id()
    return JSONResponse(
        status_code=422,
        content={"detail": exc.errors(), "request_id": rid},
        headers={"X-Request-ID": rid} if rid else {},
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    logging.getLogger("main").exception("Unhandled exception")
    rid = getattr(request.state, "request_id", None) or current_request_id()
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error.", "request_id": rid},
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
app.include_router(newsletter_router,  prefix="/api/newsletter")
app.include_router(gradebook.router,   prefix="/api/gradebook")


@app.get("/api/health")
def health():
    return {"status": "ok", "service": "sapling-backend"}


@app.get("/api/users")
def list_users():
    """List users with decrypted display names.

    The `users.name` column is encrypted at rest (see
    services.encryption); decrypt before returning so clients render the
    human-readable name, not ciphertext. Sort by the decrypted value.
    """
    from db.connection import table
    from services.encryption import decrypt_if_present
    rows = table("users").select("id,name,room_id")
    users = [
        {
            "id": r.get("id"),
            "name": decrypt_if_present(r.get("name")) or "",
            "room_id": r.get("room_id"),
        }
        for r in rows
    ]
    users.sort(key=lambda u: (u["name"] or "").lower())
    return {"users": users}


@app.get("/api/gemini-test")
def gemini_test():
    """Test Gemini connectivity. Shows clear error if API key is missing/wrong."""
    from services.gemini_service import call_gemini
    try:
        reply = call_gemini('Reply with exactly the text: Gemini OK', retries=0)
        return {"ok": True, "reply": reply.strip()}
    except Exception as e:
        return {"ok": False, "error": str(e)}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=PORT, reload=True)

import logging
import os
import time
import traceback
import uuid
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from config import FRONTEND_URL, PORT

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("sapling")
from routes import graph, learn, quiz, calendar, social, extract, auth, documents, flashcards, study_guide, feedback, careers, onboarding, gradebook
from routes.profile import router as profile_router
from routes.admin import router as admin_router
from routes.newsletter import router as newsletter_router

try:
    from recost.frameworks.fastapi import RecostMiddleware
except ImportError:
    RecostMiddleware = None  # optional; tests/CI without recost package

load_dotenv(Path(__file__).with_name(".env"))

RECOST_PROJECT_ID = "eaf22d10-840d-494f-8513-2dcef769ace1"
recost_api_key = os.getenv("RECOST_API_KEY")

app = FastAPI(title="Sapling API", version="1.0.0")


class RequestLogMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        rid = uuid.uuid4().hex[:8]
        request.state.request_id = rid
        start = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception as exc:
            dur_ms = (time.perf_counter() - start) * 1000
            log.error(
                "[%s] %s %s -> EXCEPTION %s after %.1fms\n%s",
                rid,
                request.method,
                request.url.path,
                exc.__class__.__name__,
                dur_ms,
                traceback.format_exc(),
            )
            return JSONResponse(
                status_code=500,
                content={
                    "detail": "Internal Server Error",
                    "error": exc.__class__.__name__,
                    "message": str(exc),
                    "request_id": rid,
                    "path": request.url.path,
                },
            )
        dur_ms = (time.perf_counter() - start) * 1000
        if response.status_code >= 500:
            log.error(
                "[%s] %s %s -> %d (%.1fms)",
                rid,
                request.method,
                request.url.path,
                response.status_code,
                dur_ms,
            )
        elif response.status_code >= 400:
            log.warning(
                "[%s] %s %s -> %d (%.1fms)",
                rid,
                request.method,
                request.url.path,
                response.status_code,
                dur_ms,
            )
        else:
            log.info(
                "[%s] %s %s -> %d (%.1fms)",
                rid,
                request.method,
                request.url.path,
                response.status_code,
                dur_ms,
            )
        response.headers["x-request-id"] = rid
        return response


app.add_middleware(RequestLogMiddleware)

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

"""A ceiling on request body size (testathon hardening).

Nothing bounded how many bytes a client could send. FastAPI materialises a
JSON body in memory before validation runs, so a field with no `max_length`
— `ChatBody.message`, say — was a direct route to exhausting the worker's
memory:

    POST /api/learn/chat   {"session_id": "...", "message": "<200 MB of x>"}

The Pydantic bound would have rejected it, but only AFTER the allocation that
kills the process. The same shape reaches every JSON endpoint, so the bound
belongs in one place in front of all of them rather than on 193 individual
fields.

Two ceilings, because the two body shapes have genuinely different needs:

* ``multipart/form-data`` sent to a route that takes a file upload — the
  `UPLOAD_PATHS` allowlist, exact paths. Must stay above the largest upload
  any route accepts (`routes/documents.py::MAX_FILE_SIZE`, 100 MB) plus
  multipart framing overhead, or a legitimate document upload would be
  refused here before its own, better-worded check could run. BOTH halves
  are required: Content-Type is the client's to choose, so a multipart label
  alone must not buy a 120 MB allocation on a JSON route (FastAPI parses a
  multipart body sent to any route with a `Form`/`File` parameter, and reads
  it whole for any other), and an upload route sent a non-multipart body gets
  the JSON ceiling. `tests/test_body_size_limit.py` pins the allowlist to the
  app's own multipart routes, so a new upload route that is missing fails CI.
* everything else (JSON, form-encoded, any route) — must stay above the largest honest
  JSON body. That is the flashcard importer, which carries an uploaded deck
  as base64 (`services/flashcards/import_flow.py::MAX_UPLOAD_BYTES`, 5 MB
  decoded, so ~6.7 MB encoded plus the surrounding object).

One route is neither: ``POST /api/internal/account-sync/import``
(`routes/internal_account_sync.py`, fed by `services/account_sync_client.py
::push`) carries a whole account's decrypted bundle as ONE JSON body — every
document's extracted text, every tutor message, every quiz attempt — and no
per-table cap bounds it, so the 12 MB JSON ceiling would 413 the copy of any
big account. It gets its own ceiling, matched on the EXACT path (a prefix
would hand the larger cap to anything mounted beneath it). The ceiling is
generous because the gate for that route is not this backstop: it is the
bearer token, which the route checks BEFORE it reads a single body byte, so
an unauthenticated caller never reaches the allocation at all. The bound only
caps what a holder of the peer token can make this process hold in memory.

These are a backstop, not the real validation: each route keeps its own,
tighter, better-explained limit. This exists so that a body which is absurd
by any measure is refused before it is read, instead of after.

Enforcement is in two places because a client controls which applies:

1. ``Content-Length``, when sent, is checked BEFORE the body is read at all —
   the cheap path, and the one every ordinary client takes.
2. A chunked body sends no ``Content-Length``, so bytes are counted as they
   arrive and the request is failed the moment the running total passes the
   ceiling. Without this, `Transfer-Encoding: chunked` would walk straight
   past step 1.
"""

from __future__ import annotations

import logging

from fastapi import HTTPException
from starlette.datastructures import Headers
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

logger = logging.getLogger("sapling.body_limit")

#: Above documents.py's 100 MB cap, with room for multipart framing.
DEFAULT_MULTIPART_MAX_BYTES = 120 * 1024 * 1024

#: The routes that take a file upload (an `UploadFile`/`File(...)` parameter),
#: the only ones the multipart ceiling applies to. Exact paths; a test pins
#: this set to the app's multipart routes in both directions.
UPLOAD_PATHS = frozenset({
    "/api/calendar/extract",
    "/api/careers/apply",
    "/api/documents/upload",
    "/api/documents/upload/sync",
    "/api/extract/image",
    "/api/extract/pdf",
    "/api/issue-reports/screenshot",
})

#: Above the flashcard importer's ~6.7 MB base64 payload.
DEFAULT_JSON_MAX_BYTES = 12 * 1024 * 1024

#: The server-to-server account-copy import (routes/internal_account_sync.py).
#: Exact path: main.py mounts that router at /api/internal/account-sync.
ACCOUNT_IMPORT_PATH = "/api/internal/account-sync/import"

#: A whole account's plaintext bundle (services/account_bundle.py). A heavy
#: account — dozens of documents’ OCR text plus its tutor history — can run to
#: tens of MB; 256 MB leaves an order of magnitude of headroom while still
#: bounding what one token-holding request can make the worker allocate.
DEFAULT_ACCOUNT_IMPORT_MAX_BYTES = 256 * 1024 * 1024

#: Methods that carry no body worth bounding.
_BODYLESS = frozenset({"GET", "HEAD", "OPTIONS", "TRACE"})


def _detail(limit: int) -> str:
    return f"Request body too large. Maximum size is {limit // (1024 * 1024)} MB."


def _too_large(limit: int) -> HTTPException:
    return HTTPException(status_code=413, detail=_detail(limit))


class BodySizeLimitMiddleware:
    """Refuse a request body above the ceiling for its route and content type.

    Pure ASGI rather than ``BaseHTTPMiddleware``: the latter would read the
    body itself to hand it on, which is the very allocation being prevented.

    The two paths report the overflow differently, and have to:

    * The declared-length check runs BEFORE ``self.app`` is entered, so there
      is no exception handler above it to turn a raise into a response — the
      413 is therefore written directly. This middleware is mounted INSIDE
      ``CORSMiddleware`` (see main.py), so that response still picks up the
      CORS headers a browser needs in order to read it.
    * The streamed check runs inside ``receive``, i.e. inside the app, so a
      raised ``HTTPException`` lands in the app's normal handler and comes
      back as an ordinary 413 envelope.
    """

    def __init__(
        self,
        app: ASGIApp,
        *,
        json_max_bytes: int = DEFAULT_JSON_MAX_BYTES,
        multipart_max_bytes: int = DEFAULT_MULTIPART_MAX_BYTES,
        account_import_max_bytes: int = DEFAULT_ACCOUNT_IMPORT_MAX_BYTES,
        upload_paths: frozenset[str] = UPLOAD_PATHS,
    ) -> None:
        self.app = app
        self.json_max_bytes = json_max_bytes
        self.multipart_max_bytes = multipart_max_bytes
        self.account_import_max_bytes = account_import_max_bytes
        self.upload_paths = upload_paths

    def _limit_for(self, scope: Scope) -> int:
        path = scope.get("path")
        if path == ACCOUNT_IMPORT_PATH:
            return self.account_import_max_bytes
        if path in self.upload_paths:
            content_type = Headers(scope=scope).get("content-type", "")
            if content_type.lower().startswith("multipart/form-data"):
                return self.multipart_max_bytes
        return self.json_max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope.get("method", "").upper() in _BODYLESS:
            await self.app(scope, receive, send)
            return

        limit = self._limit_for(scope)

        # (1) The declared length, refused before a single body byte is read.
        declared = Headers(scope=scope).get("content-length")
        if declared and declared.isdigit() and int(declared) > limit:
            logger.warning(
                "body_limit: refused %s %s declaring %s bytes (limit %s)",
                scope.get("method"), scope.get("path"), declared, limit,
            )
            response = JSONResponse(status_code=413, content={"detail": _detail(limit)})
            await response(scope, receive, send)
            return

        # (2) The actual length, for a chunked body that declared nothing.
        received = 0

        async def counting_receive() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b"") or b"")
                if received > limit:
                    logger.warning(
                        "body_limit: refused %s %s after %s streamed bytes (limit %s)",
                        scope.get("method"), scope.get("path"), received, limit,
                    )
                    raise _too_large(limit)
            return message

        await self.app(scope, counting_receive, send)

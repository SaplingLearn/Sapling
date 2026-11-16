"""``POST /api/auth/handoff/exchange`` (sec2 M2): consume an OAuth handoff for
the session BFF. Server to server; mounted beside ``routes/auth.py`` under
``/api/auth`` (service role: it runs before any session exists).

The BFF (frontend/src/app/api/auth/session) posts the handoff from the
callback URL and the value of the browser's sign-in nonce cookie. 200
``{"user_id"}`` only when the handoff is genuine, unexpired, bound to that
nonce, and was never exchanged before (it is consumed now, on every replica:
services/auth/handoff.py); the BFF then mints the session cookie. One generic
401 for every refusal; 503 when the single-use store cannot answer (fail
closed). The handoff authenticates the call: there is no session and no
cookie, so the CSRF origin check (services/csrf_origin.py) never applies.
"""
import logging

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

import config
from services.auth.handoff import HandoffRefused, HandoffStoreUnavailable, exchange_handoff

logger = logging.getLogger(__name__)

router = APIRouter()


class HandoffExchangeBody(BaseModel):
    token: str = Field(min_length=1, max_length=4096)
    nonce: str | None = Field(default=None, max_length=256)


@router.post("/handoff/exchange", include_in_schema=False)
def handoff_exchange(body: HandoffExchangeBody):
    secret = (getattr(config, "SESSION_SECRET", "") or "").strip()
    try:
        user_id = exchange_handoff(body.token, body.nonce, secret=secret)
    except HandoffRefused as exc:
        logger.info("handoff exchange refused: %s", exc)
        raise HTTPException(status_code=401, detail="Sign-in link is invalid or was already used.")
    except HandoffStoreUnavailable:
        raise HTTPException(status_code=503, detail="Could not complete sign-in. Please try again.")
    return JSONResponse({"user_id": user_id}, headers={"Cache-Control": "no-store"})

import logging

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from pydantic import BaseModel, EmailStr, field_validator
from db.connection import table
from services import abuse_limits, email_service
from services.request_limits import enforce_abuse_limit, public_route_limit

logger = logging.getLogger("newsletter")

router = APIRouter()


class SubscribeRequest(BaseModel):
    email: EmailStr

    @field_validator('email')
    @classmethod
    def require_tld(cls, v: str) -> str:
        domain = v.split('@')[1]
        if '.' not in domain:
            raise ValueError('Email must have a valid domain (e.g. you@example.com)')
        return v


@router.post("/subscribe")
def subscribe(body: SubscribeRequest, background_tasks: BackgroundTasks, request: Request):
    # Public: per client address when it is a public one, else a shared ceiling
    # (request_limits.public_route_limit).
    enforce_abuse_limit(*public_route_limit(
        request, abuse_limits.NEWSLETTER_SUBSCRIBE, abuse_limits.NEWSLETTER_SUBSCRIBE_SHARED,
    ))
    try:
        table("newsletter_emails").upsert(
            {"email": body.email},
            on_conflict="email",
        )
    except Exception:
        # #199: never echo the raw DB/PostgREST exception text to the client —
        # it leaks internal detail (host/table/driver). Log the full error
        # server-side and return a generic message.
        logger.exception("newsletter subscribe failed")
        raise HTTPException(
            status_code=500,
            detail="Could not process subscription. Please try again later.",
        )
    # "You're on the list". Deduped per address in email_sends, so signing up
    # twice (or a re-submit) never sends it twice; runs after the response.
    email_service.queue_waitlist_confirmation(background_tasks, body.email)
    return {"ok": True}

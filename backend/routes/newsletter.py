import logging

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from pydantic import BaseModel, EmailStr, field_validator
from db.connection import table
from services import email_service
from services.client_ip import client_ip
from services.request_limits import check_rate_limit

logger = logging.getLogger("newsletter")

# Public and unauthenticated: one call upserts a `newsletter_emails` row and
# queues a "you're on the list" email. The send is deduped per ADDRESS
# (email_sends), so the same address cannot be mailed twice — but nothing
# bounded how many DISTINCT addresses one caller could submit, so a script
# could stuff the list and make our domain send to addresses that never asked
# for it, which is how a sending reputation gets burned. Key on the caller
# (see services/client_ip.py's caveat); this is abuse dampening, not identity.
_SUBSCRIBE_RATE_LIMIT = 5    # subscriptions...
_SUBSCRIBE_RATE_WINDOW = 3600  # ...per hour, per caller

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
    retry = check_rate_limit(
        f"newsletter-subscribe:{client_ip(request)}",
        limit=_SUBSCRIBE_RATE_LIMIT,
        window_sec=_SUBSCRIBE_RATE_WINDOW,
    )
    if retry is not None:
        raise HTTPException(
            status_code=429,
            detail="Too many subscription attempts. Please try again later.",
            headers={"Retry-After": str(retry)},
        )
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

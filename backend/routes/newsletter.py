import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, EmailStr, field_validator
from db.connection import table

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
def subscribe(body: SubscribeRequest):
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
    return {"ok": True}

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, EmailStr, field_validator
from db.connection import table

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
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    return {"ok": True}

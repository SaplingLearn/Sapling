"""`/api/learn/saved`: what a student saved from a tutor session (the Tutor
session panel's "Saved" tab; Tutor redesign), behind the `saved_items` flag.
Thin handlers over services/saved_items.py, whose `SavedItemError` carries the
HTTP status it answers with."""
from __future__ import annotations

from contextlib import contextmanager

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from models import Id, ShortText
from services.auth_guard import require_self
from services.feature_flags import require_flag
from services.saved_items import (
    CONTENT_MAX,
    SAVED_ITEMS_FLAG,
    SavedItemError,
    create_saved_item,
    delete_saved_item,
    list_saved_items,
)

router = APIRouter(dependencies=[Depends(require_flag(SAVED_ITEMS_FLAG))])


class SavedItemCreateBody(BaseModel):
    user_id: Id
    session_id: Id
    title: ShortText = ""
    content: str = Field(min_length=1, max_length=CONTENT_MAX)


@contextmanager
def _errors():
    try:
        yield
    except SavedItemError as exc:
        raise HTTPException(status_code=exc.status, detail=exc.detail) from exc


@router.get("/{user_id}")
def get_saved_items(user_id: str, request: Request, session_id: str | None = None, course_id: str | None = None):
    require_self(user_id, request)
    return {"items": list_saved_items(user_id, session_id=session_id, course_id=course_id)}


@router.post("")
def save_item(body: SavedItemCreateBody, request: Request):
    require_self(body.user_id, request)
    with _errors():
        return {"item": create_saved_item(body.user_id, session_id=body.session_id, title=body.title, content=body.content)}


@router.delete("/{saved_item_id}")
def remove_saved_item(saved_item_id: str, user_id: str, request: Request):
    require_self(user_id, request)
    with _errors():
        delete_saved_item(user_id, saved_item_id)
    return {"deleted": True}

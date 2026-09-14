"""
social_cache_service.py
-----------------------
Persistent cache for AI-generated room summaries stored in Supabase.

Cache is keyed by room_id. A SHA-256 hash of the member mastery data
is stored alongside the summary so we can detect when data changed.
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone

from db.connection import table
from services.encryption import decrypt_if_present, encrypt_if_present


def _compute_hash(member_summaries: list[str]) -> str:
    joined = "\n".join(sorted(member_summaries))
    return hashlib.sha256(joined.encode()).hexdigest()[:16]


def get_cached_summary(room_id: str, member_summaries: list[str]) -> str | None:
    current_hash = _compute_hash(member_summaries)
    rows = table("room_summaries").select(
        "summary,member_hash",
        filters={"room_id": f"eq.{room_id}"},
    )
    if rows and rows[0]["member_hash"] == current_hash:
        return decrypt_if_present(rows[0]["summary"])
    return None


def save_summary(room_id: str, member_summaries: list[str], summary: str) -> None:
    table("room_summaries").upsert(
        {
            "room_id": room_id,
            "summary": encrypt_if_present(summary),
            "member_hash": _compute_hash(member_summaries),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        },
        on_conflict="room_id",
    )


def invalidate(room_id: str) -> None:
    table("room_summaries").delete({"room_id": f"eq.{room_id}"})

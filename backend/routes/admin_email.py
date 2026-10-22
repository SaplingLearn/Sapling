"""Admin email: provider status, audiences, and broadcasts.

Mounted at /api/admin/email. Every route is admin-only; mutations are audited.
Sending goes through services/email_service.py (the only Resend caller), which
dedupes every send in `email_sends` and honours `email_suppressions`.

Audiences are resolved in Python because `users.email` is AES-GCM encrypted
with a random nonce (it cannot be queried by value) and the waitlist keeps
addresses as typed. Every audience is deduped by normalized address and
excludes suppressed recipients, so the count shown is the count mailed.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Iterable

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request

import config
from db.connection import page_all, table
from models import EmailBroadcastBody, EmailBroadcastTestBody
from services import email_service, email_templates
from services.admin_audit import log_admin_action
from services.auth_guard import get_session_user_id, require_admin
from services.encryption import decrypt_if_present

logger = logging.getLogger(__name__)

router = APIRouter()

#: In display order. Keys are the contract with the frontend's audience picker.
AUDIENCES: list[tuple[str, str]] = [
    ("waitlist_all", "Everyone on the waitlist"),
    ("waitlist_pending", "Waitlist, not yet approved"),
    ("waitlist_approved_not_joined", "Approved, haven't signed in yet"),
    ("users_all", "Everyone in the app"),
]

_BROADCAST_COLUMNS = (
    "id,subject,audience,status,recipient_count,sent_count,skipped_count,"
    "failed_count,created_at,sent_at,created_by"
)
#: How often (in recipients processed) a running broadcast writes its counts.
PROGRESS_EVERY = 25


# ── Audience resolution ─────────────────────────────────────────────────────


def _suppressed_hashes() -> set[str]:
    return {
        r["recipient_hash"]
        for r in page_all(table("email_suppressions"), "recipient_hash", order="recipient_hash")
        if r.get("recipient_hash")
    }


def _waitlist_entries() -> dict[str, dict]:
    """normalized address → {to, approved, joined}. Case twins merge: approved
    or joined if ANY twin is."""
    entries: dict[str, dict] = {}
    for r in page_all(
        table("newsletter_emails"), "email,approved_at,joined_at", order="created_at.asc,id.asc",
    ):
        address = (r.get("email") or "").strip()
        norm = address.lower()
        if "@" not in norm:
            continue
        entry = entries.setdefault(norm, {"to": address, "approved": False, "joined": False})
        entry["approved"] = entry["approved"] or bool(r.get("approved_at"))
        entry["joined"] = entry["joined"] or bool(r.get("joined_at"))
    return entries


def _user_addresses() -> dict[str, str]:
    """normalized address → address, for every approved, non-deleted user."""
    out: dict[str, str] = {}
    for r in page_all(
        table("users"), "id,email",
        filters={"is_approved": "eq.true", "deleted_at": "is.null"}, order="id.asc",
    ):
        address = (decrypt_if_present(r.get("email")) or "").strip()
        # decrypt_if_present hands back the raw value when it cannot decrypt;
        # ciphertext has no "@", so this also drops undecryptable rows.
        if "@" not in address:
            continue
        out.setdefault(address.lower(), address)
    return out


def _by_hash(addresses: Iterable[str], suppressed: set[str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for address in addresses:
        h = email_service.recipient_hash(address)
        if h not in suppressed:
            out.setdefault(h, address)
    return out


def resolve_audiences(keys: Iterable[str]) -> dict[str, dict[str, str]]:
    """audience key → {recipient_hash: address}, reading each source once."""
    keys = list(keys)
    suppressed = _suppressed_hashes()
    out: dict[str, dict[str, str]] = {}
    waitlist = _waitlist_entries() if any(k.startswith("waitlist_") for k in keys) else {}
    for key in keys:
        if key == "waitlist_all":
            picked = (e["to"] for e in waitlist.values())
        elif key == "waitlist_pending":
            picked = (e["to"] for e in waitlist.values() if not e["approved"])
        elif key == "waitlist_approved_not_joined":
            picked = (e["to"] for e in waitlist.values() if e["approved"] and not e["joined"])
        elif key == "users_all":
            picked = _user_addresses().values()
        else:
            raise ValueError(f"unknown audience {key!r}")
        out[key] = _by_hash(picked, suppressed)
    return out


# ── Routes ──────────────────────────────────────────────────────────────────


@router.get("/status")
def email_status(request: Request):
    require_admin(request)
    return {"configured": email_service.is_configured(), "from_address": config.EMAIL_FROM}


@router.get("/audiences")
def email_audiences(request: Request):
    require_admin(request)
    resolved = resolve_audiences(k for k, _ in AUDIENCES)
    return {
        "audiences": [
            {"key": key, "label": label, "count": len(resolved[key])}
            for key, label in AUDIENCES
        ]
    }


def _admin_address(user_id: str) -> str | None:
    rows = table("users").select("email", filters={"id": f"eq.{user_id}"}, limit=1)
    if not rows:
        return None
    address = (decrypt_if_present(rows[0].get("email")) or "").strip()
    return address if "@" in address else None


@router.post("/broadcasts/test")
def send_test_broadcast(body: EmailBroadcastTestBody, request: Request):
    """Send the broadcast as composed to the calling admin only. Synchronous:
    the admin is waiting on the result."""
    require_admin(request)
    actor = get_session_user_id(request)
    to = _admin_address(actor)
    if not to:
        raise HTTPException(status_code=400, detail="Your account has no email address to send a test to.")
    subject, html, text = email_templates.broadcast(
        body.subject, body.body, unsubscribe_url=email_service.unsubscribe_url(to),
    )
    status = email_service.send_email(
        kind="broadcast_test",
        to=to,
        subject=subject,
        html=html,
        text=text,
        dedupe_key=f"broadcast_test:{uuid.uuid4()}",
    )
    log_admin_action(
        actor_id=actor, action="email.broadcast_test",
        target_type="email_broadcast", target_id=None,
        payload={"subject": body.subject, "status": status},
    )
    return {"status": status, "to": to}


def _broadcast_view(row: dict) -> dict:
    return {k: row.get(k) for k in _BROADCAST_COLUMNS.split(",")}


@router.post("/broadcasts", status_code=202)
def create_broadcast(body: EmailBroadcastBody, request: Request, background_tasks: BackgroundTasks):
    """Resolve the audience NOW (the count the admin confirmed is the list that
    gets mailed), record the broadcast, and send it in the background."""
    require_admin(request)
    actor = get_session_user_id(request)
    recipients = list(resolve_audiences([body.audience])[body.audience].values())
    rows = table("email_broadcasts").insert({
        "subject": body.subject,
        "body": body.body,
        "audience": body.audience,
        "status": "sending",
        "recipient_count": len(recipients),
        "created_by": actor,
    })
    if not rows:
        raise HTTPException(status_code=500, detail="Could not record the broadcast.")
    broadcast = rows[0]
    log_admin_action(
        actor_id=actor, action="email.broadcast",
        target_type="email_broadcast", target_id=broadcast.get("id"),
        payload={
            "audience": body.audience,
            "recipient_count": len(recipients),
            "subject": body.subject,
        },
    )
    background_tasks.add_task(
        run_broadcast, broadcast["id"], body.subject, body.body, recipients,
    )
    return {"broadcast": _broadcast_view(broadcast)}


def run_broadcast(broadcast_id: str, subject: str, body: str, recipients: list[str]) -> None:
    """Send one broadcast to `recipients`, writing progress as it goes.

    Never raises (it runs after the response). `duplicate` and `suppressed`
    count as skipped: the address was not mailed by this run."""
    counts = {"sent_count": 0, "skipped_count": 0, "failed_count": 0}

    def _write(extra: dict | None = None) -> None:
        try:
            table("email_broadcasts").update(
                {**counts, **(extra or {})}, filters={"id": f"eq.{broadcast_id}"},
            )
        except Exception:  # noqa: BLE001
            logger.warning("broadcast progress write failed id=%s", broadcast_id, exc_info=True)

    try:
        for i, to in enumerate(recipients, start=1):
            try:
                subj, html, text = email_templates.broadcast(
                    subject, body, unsubscribe_url=email_service.unsubscribe_url(to),
                )
                status = email_service.send_email(
                    kind="broadcast",
                    to=to,
                    subject=subj,
                    html=html,
                    text=text,
                    dedupe_key=f"broadcast:{broadcast_id}:{email_service.recipient_hash(to)}",
                    broadcast_id=broadcast_id,
                )
            except Exception:  # noqa: BLE001 — one bad recipient never stops the rest
                logger.warning("broadcast recipient failed id=%s", broadcast_id, exc_info=True)
                status = "failed"
            if status == "sent":
                counts["sent_count"] += 1
            elif status == "failed":
                counts["failed_count"] += 1
            else:
                counts["skipped_count"] += 1
            if i % PROGRESS_EVERY == 0 and i < len(recipients):
                _write()
        all_failed = bool(recipients) and counts["failed_count"] == len(recipients)
        _write({
            "status": "failed" if all_failed else "sent",
            "sent_at": datetime.now(timezone.utc).isoformat(),
        })
    except Exception:  # noqa: BLE001
        logger.exception("broadcast run crashed id=%s", broadcast_id)
        _write({"status": "failed"})


@router.get("/broadcasts")
def list_broadcasts(request: Request):
    require_admin(request)
    rows = table("email_broadcasts").select(
        _BROADCAST_COLUMNS, order="created_at.desc", limit=50,
    )
    return {"broadcasts": [_broadcast_view(r) for r in rows or []]}

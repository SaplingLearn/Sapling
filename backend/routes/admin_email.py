"""Admin email: provider status, audiences, and broadcasts.

Mounted at /api/admin/email. Every route is admin-only; mutations are audited.
Sending goes through services/email_service.py (the only Resend caller), which
dedupes every send in `email_sends` and honours `email_suppressions`.

Audiences are resolved in Python because `users.email` is AES-GCM encrypted
with a random nonce (it cannot be queried by value) and the waitlist keeps
addresses as typed. Every audience is deduped by normalized address and
excludes suppressed recipients and accounts that turned email notifications
off, so the count shown is the count mailed.

A broadcast's lifecycle (`email_broadcasts.status`): `sending` while its
background run is alive (it bumps `heartbeat_at` as it goes), then `sent`
(everything that went anywhere went out), `partial` (some sent, some failed,
or the run died part-way), `failed` (nothing sent, something failed) or
`skipped` (nothing sent and nothing failed: no API key, everyone suppressed or
opted out, or an empty audience). A `sending` row whose heartbeat is older
than STALE_SENDING_AFTER has no live run (a deploy killed it); it, and a
`failed`/`partial` one, can be resumed: the audience is re-resolved and every
recipient re-runs through `email_sends` dedupe, so whoever already got it is a
no-op and only the rest are mailed.
"""

from __future__ import annotations

import logging
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Iterable

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from pydantic import BaseModel, Field

import config
from db.connection import page_all, pg_quote_value, table
from models import EmailBroadcastBody, EmailBroadcastPreviewBody, EmailBroadcastTestBody
from services import email_service, email_templates, email_variables
from services.admin_audit import log_admin_action
from services.auth_guard import get_session_user_id, require_admin
from services.encryption import decrypt, decrypt_if_present

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
    "failed_count,created_at,sent_at,created_by,heartbeat_at"
)
#: How often (in recipients processed) a running broadcast writes its counts.
PROGRESS_EVERY = 25
#: ...and the longest it goes without one, so a slow run still heartbeats.
HEARTBEAT_EVERY_S = 30.0
#: A `sending` broadcast with no heartbeat for this long has no live run.
STALE_SENDING_AFTER = timedelta(minutes=10)
_RESUMABLE = ("failed", "partial")


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _stale_cutoff() -> datetime:
    return datetime.now(timezone.utc) - STALE_SENDING_AFTER


def _parse_ts(value) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _is_stale(row: dict) -> bool:
    if row.get("status") != "sending":
        return False
    beat = _parse_ts(row.get("heartbeat_at")) or _parse_ts(row.get("created_at"))
    return beat is None or beat < _stale_cutoff()


def _outcome(sent: int, failed: int) -> str:
    """A finished run's honest status."""
    if sent and failed:
        return "partial"
    if failed:
        return "failed"
    return "sent" if sent else "skipped"


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


def _plain(value) -> str:
    """A 🔒 column's plaintext, or "" when it's empty or can't be decrypted.
    Never the ciphertext: that must not end up in someone's greeting."""
    if not isinstance(value, str) or not value:
        return ""
    try:
        return " ".join(decrypt(value).split())
    except Exception:  # noqa: BLE001
        return ""


def _names() -> dict[str, dict[str, str]]:
    """normalized address → {first_name, name}, for the broadcast variables.

    An account's profile names first (first name falls back to the first word
    of the full name), else the first name a waitlist entry carries (set when
    someone joins from /pending). Landing-form signups have neither, so their
    copy uses the variable's fallback."""
    profiles = {
        p["user_id"]: p
        for p in page_all(table("user_profiles"), "user_id,first_name,name", order="user_id.asc")
        if p.get("user_id")
    }
    out: dict[str, dict[str, str]] = {}
    for u in page_all(table("users"), "id,email", filters={"deleted_at": "is.null"}, order="id.asc"):
        address = _plain(u.get("email")).lower()
        if "@" not in address:
            continue
        p = profiles.get(u["id"]) or {}
        name = _plain(p.get("name"))
        first = _plain(p.get("first_name")) or (name.split()[0] if name else "")
        out.setdefault(address, {"first_name": first, "name": name})
    for r in page_all(table("newsletter_emails"), "email,first_name", order="created_at.asc,id.asc"):
        address = (r.get("email") or "").strip().lower()
        first = _plain(r.get("first_name"))
        if "@" not in address or not first:
            continue
        entry = out.setdefault(address, {"first_name": "", "name": ""})
        entry["first_name"] = entry["first_name"] or first
        entry["name"] = entry["name"] or first
    return out


def _values(address: str, names: dict[str, dict[str, str]]) -> dict[str, str]:
    """One recipient's variable values."""
    known = names.get(address.strip().lower()) or {}
    return {
        "first_name": known.get("first_name", ""),
        "name": known.get("name", ""),
        "email": address,
        **email_variables.link_values(),
    }


def _uses_variables(*texts: str) -> bool:
    return any("{{" in (t or "") for t in texts)


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
    excluded = set(_suppressed_hashes())
    try:
        excluded |= email_service.notification_opt_out_hashes(fresh=True)
    except Exception:  # noqa: BLE001 — send_email still enforces it per recipient
        logger.warning("notification opt-out read failed; audience may over-count", exc_info=True)
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
        out[key] = _by_hash(picked, excluded)
    return out


# ── Routes ──────────────────────────────────────────────────────────────────


@router.get("/status")
def email_status(request: Request):
    require_admin(request)
    return {
        "configured": email_service.is_configured(),
        "from_address": config.EMAIL_FROM,
        "variables": email_variables.VARIABLES,
    }


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


@router.post("/broadcasts/preview")
def preview_broadcast(body: EmailBroadcastPreviewBody, request: Request):
    """The broadcast's real HTML, rendered server-side for the compose preview,
    with the variables filled in as the calling admin. Sends nothing and writes
    nothing; the unsubscribe link is a placeholder. Unknown variables are left
    as typed and listed, so the composer can flag them before a send 422s."""
    require_admin(request)
    values: dict[str, str] = {}
    if _uses_variables(body.subject, body.body):
        address = _admin_address(get_session_user_id(request)) or ""
        values = _values(address, _names()) if address else {}
    subject, html, _ = email_templates.broadcast(
        body.subject or "(no subject)", body.body, unsubscribe_url="#unsubscribe", values=values,
    )
    return {
        "subject": subject,
        "html": html,
        "unknown_variables": email_variables.unknown_variables(body.subject, body.body),
    }


@router.post("/broadcasts/test")
def send_test_broadcast(body: EmailBroadcastTestBody, request: Request):
    """Send the broadcast as composed to the calling admin only. Synchronous:
    the admin is waiting on the result."""
    require_admin(request)
    actor = get_session_user_id(request)
    to = _admin_address(actor)
    if not to:
        raise HTTPException(status_code=400, detail="Your account has no email address to send a test to.")
    values = _values(to, _names() if _uses_variables(body.subject, body.body) else {})
    subject, html, text = email_templates.broadcast(
        body.subject, body.body, unsubscribe_url=email_service.unsubscribe_url(to), values=values,
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
    view = {k: row.get(k) for k in _BROADCAST_COLUMNS.split(",")}
    view["stale"] = _is_stale(row)
    view["resumable"] = view["stale"] or row.get("status") in _RESUMABLE
    return view


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
        "heartbeat_at": _iso(datetime.now(timezone.utc)),
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


def _ledger_sent(broadcast_id: str) -> int | None:
    """How many of this broadcast's recipients `email_sends` records as sent
    (across every run of it), or None when it can't be read."""
    try:
        return sum(1 for _ in page_all(
            table("email_sends"), "id",
            filters={"broadcast_id": f"eq.{broadcast_id}", "status": "eq.sent"}, order="id.asc",
        ))
    except Exception:  # noqa: BLE001
        logger.warning("broadcast ledger read failed id=%s", broadcast_id, exc_info=True)
        return None


def run_broadcast(
    broadcast_id: str, subject: str, body: str, recipients: list[str], *, resumed: bool = False,
) -> None:
    """Send one broadcast to `recipients`, writing progress (and a heartbeat)
    as it goes.

    Never raises (it runs after the response). `duplicate`, `suppressed`,
    `opted_out` and `skipped` count as skipped: the address was not mailed by
    this run. A `resumed` run takes its sent count from the ledger, because
    whoever an earlier run already mailed comes back `duplicate` here. If the
    run itself dies, the row says `partial` when anything went out (else
    `failed`), never a bare `failed` over delivered mail."""
    counts = {"sent_count": 0, "skipped_count": 0, "failed_count": 0}
    last_write = [time.monotonic()]

    def _write(extra: dict | None = None) -> None:
        last_write[0] = time.monotonic()
        try:
            table("email_broadcasts").update(
                {**counts, "heartbeat_at": _iso(datetime.now(timezone.utc)), **(extra or {})},
                filters={"id": f"eq.{broadcast_id}"},
            )
        except Exception:  # noqa: BLE001
            logger.warning("broadcast progress write failed id=%s", broadcast_id, exc_info=True)

    def _tally() -> tuple[int, int]:
        sent, failed = counts["sent_count"], counts["failed_count"]
        if resumed:
            ledger = _ledger_sent(broadcast_id)
            if ledger is not None and ledger > sent:
                sent = counts["sent_count"] = ledger
                counts["skipped_count"] = max(0, len(recipients) - sent - failed)
        return sent, failed

    try:
        # Read once per run, and only when the text actually uses variables.
        names = _names() if _uses_variables(subject, body) else {}
        for i, to in enumerate(recipients, start=1):
            try:
                values = _values(to, names)
                subj, html, text = email_templates.broadcast(
                    subject, body, unsubscribe_url=email_service.unsubscribe_url(to), values=values,
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
            if i < len(recipients) and (
                i % PROGRESS_EVERY == 0 or time.monotonic() - last_write[0] >= HEARTBEAT_EVERY_S
            ):
                _write()
        sent, failed = _tally()
        _write({
            "status": _outcome(sent, failed),
            "sent_at": datetime.now(timezone.utc).isoformat(),
        })
    except Exception:  # noqa: BLE001
        logger.exception("broadcast run crashed id=%s", broadcast_id)
        sent, _ = _tally()
        _write({"status": "partial" if sent else "failed"})


@router.get("/broadcasts")
def list_broadcasts(request: Request):
    require_admin(request)
    rows = table("email_broadcasts").select(
        _BROADCAST_COLUMNS, order="created_at.desc", limit=50,
    )
    return {"broadcasts": [_broadcast_view(r) for r in rows or []]}


@router.post("/broadcasts/{broadcast_id}/resume", status_code=202)
def resume_broadcast(broadcast_id: str, request: Request, background_tasks: BackgroundTasks):
    """Re-run a broadcast whose run died (`sending` with a stale heartbeat) or
    ended `failed`/`partial`. The audience is re-resolved now (addresses are
    never stored, so the original list can't be replayed) and every recipient
    goes back through `email_sends` dedupe: whoever already got it is a no-op,
    failed sends are retried, and anyone who joined the audience since gets it.
    The claim is a conditional update, so two clicks start one run."""
    require_admin(request)
    actor = get_session_user_id(request)
    try:
        uuid.UUID(broadcast_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="No such broadcast.")
    rows = table("email_broadcasts").select(
        "id,subject,body,audience,status,heartbeat_at,created_at",
        filters={"id": f"eq.{broadcast_id}"}, limit=1,
    )
    if not rows:
        raise HTTPException(status_code=404, detail="No such broadcast.")
    row = rows[0]
    if not (_is_stale(row) or row.get("status") in _RESUMABLE):
        raise HTTPException(status_code=409, detail="This broadcast isn't stuck or failed, so there's nothing to resume.")
    try:
        recipients = list(resolve_audiences([row["audience"]])[row["audience"]].values())
    except ValueError:
        raise HTTPException(status_code=409, detail="This broadcast's audience no longer exists.")
    cutoff = pg_quote_value(_iso(_stale_cutoff()))
    claimed = table("email_broadcasts").update(
        {
            "status": "sending",
            "heartbeat_at": _iso(datetime.now(timezone.utc)),
            "recipient_count": len(recipients),
            "sent_at": None,
        },
        filters={
            "id": f"eq.{broadcast_id}",
            "or": (
                f"(status.in.({','.join(_RESUMABLE)}),"
                f"and(status.eq.sending,heartbeat_at.lt.{cutoff}),"
                "and(status.eq.sending,heartbeat_at.is.null))"
            ),
        },
    )
    if not claimed:
        raise HTTPException(status_code=409, detail="This broadcast is already being resumed.")
    log_admin_action(
        actor_id=actor, action="email.broadcast_resume",
        target_type="email_broadcast", target_id=broadcast_id,
        payload={"audience": row["audience"], "recipient_count": len(recipients), "was": row.get("status")},
    )
    background_tasks.add_task(
        run_broadcast, broadcast_id, row["subject"], row["body"], recipients, resumed=True,
    )
    return {"broadcast": _broadcast_view(claimed[0])}


class UnsuppressBody(BaseModel):
    email: str = Field(min_length=3, max_length=320)


@router.post("/suppressions/remove")
def unsuppress_address(body: UnsuppressBody, request: Request):
    """Take an address off the suppression list (it unsubscribed by mistake,
    or asked to be mailed again). The address is only hashed, never stored or
    audited; a later send of a key that was recorded `suppressed` re-claims it."""
    require_admin(request)
    address = body.email.strip()
    if "@" not in address:
        raise HTTPException(status_code=422, detail="That isn't an email address.")
    rhash = email_service.recipient_hash(address)
    removed = email_service.unsuppress(rhash)
    log_admin_action(
        actor_id=get_session_user_id(request), action="email.unsuppress",
        target_type="email_suppression", target_id=rhash,
        payload={"removed": removed},
    )
    return {"removed": removed}

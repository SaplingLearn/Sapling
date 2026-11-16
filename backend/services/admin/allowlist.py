"""
backend/services/admin/allowlist.py

The newsletter waitlist / allowlist: list with invite status,
single + bulk approve (letting linked accounts in, #757) and revoke.
Every case twin of one address is read through the auth package
(``services.auth.waitlist_entries``).

Moved verbatim out of ``routes/admin.py`` (#118); the route keeps the
auth checks and maps ``services.admin.errors`` to HTTP statuses.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

import services.auth as auth_service
from db.connection import page_all, pg_quote_value, table
from models import AllowlistBulkBody, AllowlistEmailBody
from services import email_service
from services.admin.errors import Conflict, NotFound
from services.admin_audit import log_admin_action
from services.auth_guard import clear_account_state_cache
from services.encryption import decrypt_if_present

logger = logging.getLogger(__name__)


_ALLOWLIST_COLUMNS = "id,email,created_at,approved_at,joined_at,joined_user_id"


#: dedupe keys are ~82 chars; 50 per `in.(…)` keeps each URL around 4 KB, well
#: under the 8 KB request-line limits common in front of PostgREST.
_IN_CHUNK = 50


def _chunks(items: list, size: int = _IN_CHUNK):
    for i in range(0, len(items), size):
        yield items[i:i + size]


def _send_statuses(dedupe_keys: list[str]) -> dict[str, str]:
    """dedupe_key → email_sends.status for the keys that have a row.

    Degrades to "no statuses" on a read error: the allowlist is still useful
    without them, and a missing column/table must not 500 the admin page."""
    statuses: dict[str, str] = {}
    keys = sorted(set(k for k in dedupe_keys if k))
    try:
        for chunk in _chunks(keys):
            rows = table("email_sends").select(
                "dedupe_key,status",
                filters={"dedupe_key": f"in.({','.join(chunk)})"},
            )
            for r in rows or []:
                statuses[r.get("dedupe_key")] = r.get("status")
    except Exception:  # noqa: BLE001
        logger.warning("email_sends status read failed", exc_info=True)
    return statuses


def _with_invite_status(rows: list[dict]) -> list[dict]:
    """Attach `invite_status`: the status of that address's "you're in" send."""
    keyed = [
        (r, email_service.waitlist_approved_key(r["email"])) if r.get("email") else (r, None)
        for r in rows
    ]
    statuses = _send_statuses([k for _, k in keyed if k])
    return [{**r, "invite_status": statuses.get(k) if k else None} for r, k in keyed]


def _waitlist_rows(columns: str = _ALLOWLIST_COLUMNS) -> list[dict]:
    # Paged: the waitlist can outgrow PostgREST's max_rows (1000), and a
    # capped read answers 206 — a silent truncation.
    return list(page_all(table("newsletter_emails"), columns, order="created_at.desc,id.desc"))


def list_allowlist():
    return {"emails": _with_invite_status(_waitlist_rows())}


#: What an approval reads off each existing row: the stored spelling and 🔒
#: first name for the "you're in" email, and the linked account to let in.
_APPROVE_COLUMNS = "id,email,approved_at,first_name,joined_user_id"


def _in_list(values) -> str:
    return f"in.({','.join(pg_quote_value(v) for v in values)})"


def _grant_linked_accounts(rows: list[dict], now_iso: str) -> None:
    """Let the accounts behind approved waitlist rows in now (#757).

    A row's `joined_user_id` is the account it was matched to at sign-in (or
    the one Admin → Users removed). Sign-in copies an approval onto
    `users.is_approved` only when the student signs in again, so a re-approval
    used to sit unseen until then; flipping the account here makes it take
    effect at once. Rows without a link have no account yet: their first
    sign-in creates it approved. Idempotent, so a retried approve finishes the
    job a failed one started.
    """
    linked = [r for r in rows if r.get("joined_user_id")]
    user_ids = sorted({r["joined_user_id"] for r in linked})
    for chunk in _chunks(user_ids, 100):
        table("users").update({"is_approved": True}, filters={"id": _in_list(chunk)})
        for uid in chunk:
            clear_account_state_cache(uid)  # #756: honoured now, not at the TTL
    for chunk in _chunks([r["id"] for r in linked], 100):
        table("newsletter_emails").update(
            {"joined_at": now_iso},
            filters={"id": f"in.({','.join(chunk)})", "joined_at": "is.null"},
        )


def _approve_waitlist(
    wanted: list[str], by_lower: dict[str, list[dict]], now_iso: str,
) -> tuple[list[tuple[str, str | None]], list[str]]:
    """Approve normalised addresses against their existing rows (`by_lower`).

    Addresses already on the waitlist keep their stored spelling (the waitlist
    keeps emails as typed, so a lowercased insert would create a case twin) and
    an already-approved row keeps its original `approved_at`: only NULLs are
    stamped, via a PATCH filtered on `approved_at=is.null`. New addresses are
    inserted approved with ON CONFLICT DO NOTHING, so a concurrent signup is
    never overwritten. Returns the "you're in" recipients (address, 🔒 first
    name — one per email) and every stored spelling, for the read-back.
    """
    pending_ids: list[str] = []
    missing: list[str] = []
    linked: list[dict] = []
    recipients: list[tuple[str, str | None]] = []
    spellings: list[str] = []
    for email in wanted:
        existing = by_lower.get(email)
        if existing:
            pending_ids.extend(r["id"] for r in existing if not r.get("approved_at"))
            spellings.extend(r["email"] for r in existing)
            linked.extend(existing)
            recipients.append((existing[0]["email"], decrypt_if_present(existing[0].get("first_name"))))
        else:
            missing.append(email)
            spellings.append(email)
            recipients.append((email, None))

    for chunk in _chunks(pending_ids, 100):
        table("newsletter_emails").update(
            {"approved_at": now_iso},
            filters={"id": f"in.({','.join(chunk)})", "approved_at": "is.null"},
        )
    if missing:
        table("newsletter_emails").upsert(
            [{"email": e, "approved_at": now_iso} for e in missing],
            on_conflict="email",
            ignore_duplicates=True,
        )
    _grant_linked_accounts(linked, now_iso)
    return recipients, spellings


def approve_allowlist(
    body: AllowlistEmailBody, actor: str | None, background_tasks,
):
    """Approve one address — the bulk path's rules for a single email (#757):
    normalised, case twins reached, `approved_at` never re-stamped, and an
    existing account let in at once."""
    now_iso = datetime.now(timezone.utc).isoformat()
    email = body.email  # normalized: lowercased, stripped
    recipients, _ = _approve_waitlist(
        [email], {email: auth_service.waitlist_entries(email, _APPROVE_COLUMNS)}, now_iso,
    )
    log_admin_action(
        actor_id=actor, action="allowlist.approve",
        target_type="allowlist", target_id=email,
        payload={"email": email},
    )
    # "You're in". Deduped per address in email_sends, so a revoke followed
    # by a re-approve never sends it twice. The 🔒 first name is there only
    # for someone who joined from /pending; it never leaves this function.
    for address, first_name in recipients:
        email_service.queue_waitlist_approved(background_tasks, address, first_name)
    rows = auth_service.waitlist_entries(email, _ALLOWLIST_COLUMNS)
    row = dict(rows[0]) if rows else None
    if row:
        row.pop("first_name", None)  # 🔒; never in a response
    return {"email": row}


def approve_allowlist_bulk(body: AllowlistBulkBody, actor: str | None, background_tasks):
    """Approve up to 500 addresses at once (rules: `_approve_waitlist`)."""
    now_iso = datetime.now(timezone.utc).isoformat()
    wanted = body.emails  # normalized: lowercased, stripped, deduped

    by_lower: dict[str, list[dict]] = {}
    for r in _waitlist_rows(_APPROVE_COLUMNS):
        key = (r.get("email") or "").strip().lower()
        if key:
            by_lower.setdefault(key, []).append(r)

    recipients, spellings = _approve_waitlist(wanted, by_lower, now_iso)

    log_admin_action(
        actor_id=actor, action="allowlist.approve_bulk",
        target_type="allowlist", target_id=None,
        payload={"count": len(wanted), "emails": wanted},
    )

    for address, first_name in recipients:
        email_service.queue_waitlist_approved(background_tasks, address, first_name)

    rows: list[dict] = []
    seen_ids: set = set()
    for chunk in _chunks(sorted(set(spellings))):
        quoted = ",".join(pg_quote_value(e) for e in chunk)
        for r in table("newsletter_emails").select(
            _ALLOWLIST_COLUMNS, filters={"email": f"in.({quoted})"},
        ) or []:
            if r.get("id") not in seen_ids:
                seen_ids.add(r.get("id"))
                rows.append(r)
    rows.sort(key=lambda r: r.get("created_at") or "", reverse=True)
    return {"approved": len(wanted), "emails": _with_invite_status(rows)}


def revoke_allowlist(body: AllowlistEmailBody, actor: str | None):
    """Take an address's approval back — and the access it granted (#757).

    Reaches every case twin (sign-in reads the approved twin, so revoking only
    the exact spelling could leave it approved), clears the "joined" stamp so
    no row reads "joined but not approved", and sets the linked account's
    `users.is_approved` to false at once instead of leaving it signed in.
    `joined_user_id` is kept: it is the only link back to the account
    (users.email is nonce-encrypted), which a re-approve or a retried revoke
    needs. The waitlist is written first so a failed account write is retried
    by the admin repeating the revoke, never undone by the student's next
    sign-in re-reading an approved row.
    """
    email = body.email  # normalized: lowercased, stripped
    twins = auth_service.waitlist_entries(email, _ALLOWLIST_COLUMNS)
    if not twins:
        raise NotFound("Email not found")
    user_ids = sorted({r["joined_user_id"] for r in twins if r.get("joined_user_id")})
    if actor in user_ids:
        raise Conflict("You cannot remove your own access.")
    rows = table("newsletter_emails").update(
        {"approved_at": None, "joined_at": None},
        filters={"id": f"in.({','.join(r['id'] for r in twins)})"},
    )
    for chunk in _chunks(user_ids, 100):
        table("users").update({"is_approved": False}, filters={"id": _in_list(chunk)})
        for uid in chunk:
            clear_account_state_cache(uid)  # #756: refused now, not at the TTL
    log_admin_action(
        actor_id=actor, action="allowlist.revoke",
        target_type="allowlist", target_id=email,
        payload={"email": email, "user_ids": user_ids},
    )
    return {"email": (rows or twins)[0]}

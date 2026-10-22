"""Transactional + broadcast email over Resend: the ONLY module that talks to it.

Every send goes through `send_email`, which:

1. refuses a recipient on the suppression list (`email_suppressions`) — for
   EVERY kind of email, recorded as `suppressed`;
2. claims the send's `dedupe_key` in `email_sends` with INSERT … ON CONFLICT DO
   NOTHING before anything leaves the process. A key that is already `queued`,
   `sent` or `suppressed` is never sent again: that is the "never twice"
   guarantee (revoke + re-approve does not re-send "you're in"). A key whose
   last attempt was `skipped` (no API key yet) or `failed` can be re-claimed, so
   approvals made before Resend was configured are not lost forever;
3. with no `RESEND_API_KEY` (the kill switch: tests, E2E, local dev) marks the
   row `skipped`; otherwise POSTs to Resend and marks it `sent` or `failed`.

It never raises: an email is a side effect, and a failure must never fail the
request that triggered it. Routes enqueue through `send_in_background` (FastAPI
`BackgroundTasks`) so the response never waits on Resend either.

Recipient ADDRESSES are never written to the database. Rows key on
`recipient_hash` (keyed HMAC of the normalized address), and the error text
stored for a failure is scrubbed of anything address-shaped.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import re
import threading
import time
import uuid
from datetime import datetime, timezone
from typing import Optional

import httpx

import config
from db.connection import table

logger = logging.getLogger(__name__)

RESEND_URL = "https://api.resend.com/emails"

#: One pooled client for every Resend call. Third-party HTTP, not Supabase, so
#: it is sanctioned outside db/connection.py (CLAUDE.md conventions).
_client = httpx.Client(timeout=10.0)

#: Resend's default limit is 2 requests/second per team. One process-wide gap
#: between requests keeps a broadcast under it; a 429 still gets one retry.
MIN_REQUEST_INTERVAL_S = 0.5
#: Ceiling on how long a 429's Retry-After may hold the sending thread.
MAX_RETRY_AFTER_S = 10.0
_sleep = time.sleep  # patched in tests
_throttle_lock = threading.Lock()
_next_slot = 0.0

_HASH_LABEL = b"sapling-email-v1"
_UNSUB_LABEL = b"sapling-email-unsubscribe-v1"
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_EMAILISH = re.compile(r"[^\s@<>\"'(),;:]+@[^\s@<>\"'(),;:]+")
_MAX_ERROR_LEN = 300


# ── Identity ────────────────────────────────────────────────────────────────


def _derived_key(label: bytes) -> bytes:
    # Read at call time (not import time) so a rotation or a test patch is seen.
    secret = (getattr(config, "SESSION_SECRET", "") or "").encode("utf-8")
    return hmac.new(secret, label, hashlib.sha256).digest()


def normalize_email(email: str) -> str:
    return (email or "").strip().lower()


def recipient_hash(email: str) -> str:
    """Stable, keyed identity of an address: what the email tables store
    instead of the address itself. Case- and whitespace-insensitive."""
    return hmac.new(
        _derived_key(_HASH_LABEL), normalize_email(email).encode("utf-8"), hashlib.sha256
    ).hexdigest()


def _token_sig(rhash: str) -> str:
    return hmac.new(_derived_key(_UNSUB_LABEL), rhash.encode("ascii"), hashlib.sha256).hexdigest()


def unsubscribe_token(email: str) -> str:
    """`<recipient_hash>.<sig>` — URL-safe (hex + '.'), no expiry: an
    unsubscribe link in a years-old email must still work."""
    rhash = recipient_hash(email)
    return f"{rhash}.{_token_sig(rhash)}"


def verify_unsubscribe_token(token: str | None) -> Optional[str]:
    """The recipient_hash a token names, or None when it is malformed/forged."""
    if not token or not isinstance(token, str):
        return None
    rhash, sep, sig = token.strip().partition(".")
    if not sep or not _HEX64.match(rhash) or not _HEX64.match(sig):
        return None
    if not hmac.compare_digest(sig, _token_sig(rhash)):
        return None
    return rhash


def unsubscribe_url(email: str) -> str:
    """Public one-click link. Built on FRONTEND_URL because the frontend
    proxies /api/* to this backend (frontend/next.config.ts rewrites)."""
    base = (getattr(config, "FRONTEND_URL", "") or "").rstrip("/")
    return f"{base}/api/email/unsubscribe?t={unsubscribe_token(email)}"


def is_configured() -> bool:
    return bool((getattr(config, "RESEND_API_KEY", "") or "").strip())


# ── Suppressions ────────────────────────────────────────────────────────────


def is_suppressed(rhash: str) -> bool:
    rows = table("email_suppressions").select(
        "recipient_hash", filters={"recipient_hash": f"eq.{rhash}"}, limit=1,
    )
    return bool(rows)


def suppress(rhash: str, reason: str = "unsubscribe") -> None:
    """Add a hash to the suppression list. Idempotent: an existing row keeps
    its original reason and timestamp. Raises on a DB error (the unsubscribe
    page must not claim success it did not get)."""
    table("email_suppressions").upsert(
        {"recipient_hash": rhash, "reason": reason},
        on_conflict="recipient_hash",
        ignore_duplicates=True,
    )


# ── Sending ─────────────────────────────────────────────────────────────────


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _scrub(message: str, to: str) -> str:
    """Short, address-free error text for `email_sends.error`."""
    text = str(message or "")
    for needle in {to, (to or "").strip(), normalize_email(to)}:
        if needle:
            text = re.sub(re.escape(needle), "<recipient>", text, flags=re.IGNORECASE)
    text = _EMAILISH.sub("<address>", text)
    text = " ".join(text.split())
    return text[:_MAX_ERROR_LEN]


def _throttle() -> None:
    global _next_slot
    with _throttle_lock:
        now = time.monotonic()
        wait = _next_slot - now
        if wait > 0:
            _sleep(wait)
            now = time.monotonic()
        _next_slot = now + MIN_REQUEST_INTERVAL_S


def _retry_after(resp: httpx.Response) -> float:
    try:
        value = float(resp.headers.get("retry-after", "1"))
    except (TypeError, ValueError):
        value = 1.0
    return max(MIN_REQUEST_INTERVAL_S, min(value, MAX_RETRY_AFTER_S))


def _post_to_resend(payload: dict, idempotency_key: str) -> httpx.Response:
    headers = {
        "Authorization": f"Bearer {config.RESEND_API_KEY.strip()}",
        "Idempotency-Key": idempotency_key[:256],
    }
    _throttle()
    resp = _client.post(RESEND_URL, json=payload, headers=headers)
    if resp.status_code == 429:
        _sleep(_retry_after(resp))
        _throttle()
        resp = _client.post(RESEND_URL, json=payload, headers=headers)
    return resp


def _error_from_response(resp: httpx.Response) -> str:
    detail = ""
    try:
        body = resp.json()
        if isinstance(body, dict):
            detail = str(body.get("message") or body.get("name") or "")
    except ValueError:
        detail = ""
    return f"HTTP {resp.status_code}" + (f": {detail}" if detail else "")


def _mark(row_id: str, fields: dict) -> None:
    try:
        table("email_sends").update(fields, filters={"id": f"eq.{row_id}"})
    except Exception:  # noqa: BLE001 — the send already happened (or not); never raise
        logger.warning("email_sends status update failed id=%s", row_id, exc_info=True)


def _reclaim(dedupe_key: str) -> list:
    """Re-claim a key whose last attempt was `skipped` or `failed`.

    Conditional on that status, so of two concurrent re-claims only one gets
    the row back. Never raises.
    """
    try:
        return table("email_sends").update(
            {"status": "queued", "error": None},
            filters={"dedupe_key": f"eq.{dedupe_key}", "status": "in.(skipped,failed)"},
        ) or []
    except Exception:  # noqa: BLE001
        logger.warning("email re-claim failed key=%s", dedupe_key, exc_info=True)
        return []


def send_email(
    *,
    kind: str,
    to: str,
    subject: str,
    html: str,
    text: str,
    dedupe_key: str,
    broadcast_id: Optional[str] = None,
) -> str:
    """Send one email at most once per `dedupe_key`.

    Returns the final status: "sent" | "skipped" | "failed" | "suppressed", or
    "duplicate" when the key was already claimed (nothing is sent). Never raises.
    """
    try:
        if not normalize_email(to):
            logger.warning("email send with no recipient kind=%s key=%s", kind, dedupe_key)
            return "failed"
        rhash = recipient_hash(to)
        suppressed = is_suppressed(rhash)
        row = {
            "kind": kind,
            "dedupe_key": dedupe_key,
            "recipient_hash": rhash,
            "status": "suppressed" if suppressed else "queued",
        }
        if broadcast_id:
            row["broadcast_id"] = broadcast_id
        claimed = table("email_sends").upsert(
            row, on_conflict="dedupe_key", ignore_duplicates=True,
        )
    except Exception:  # noqa: BLE001
        # Without a claim there is no "never twice" guarantee, so do not send.
        logger.warning("email claim failed kind=%s key=%s", kind, dedupe_key, exc_info=True)
        return "failed"

    if not claimed and not suppressed:
        claimed = _reclaim(dedupe_key)
    if not claimed:
        logger.info("email already claimed kind=%s key=%s", kind, dedupe_key)
        return "duplicate"
    if suppressed:
        logger.info("email suppressed kind=%s key=%s", kind, dedupe_key)
        return "suppressed"

    row_id = claimed[0].get("id")

    if not is_configured():
        logger.info("RESEND_API_KEY unset; email skipped kind=%s key=%s", kind, dedupe_key)
        _mark(row_id, {"status": "skipped"})
        return "skipped"

    payload: dict = {
        "from": config.EMAIL_FROM,
        "to": [to.strip()],
        "subject": subject,
        "html": html,
        "text": text,
        "headers": {
            "List-Unsubscribe": f"<{unsubscribe_url(to)}>",
            "List-Unsubscribe-Post": "List-Unsubscribe=One-Click",
        },
    }
    reply_to = (getattr(config, "EMAIL_REPLY_TO", "") or "").strip()
    if reply_to:
        payload["reply_to"] = reply_to

    # Per attempt, not per dedupe_key: Resend replays a key's first response for
    # ~24h, so a re-claimed `failed` send under the same key would just get the
    # old failure back. The 429 retry inside one attempt reuses it, which is
    # what makes that retry safe.
    try:
        resp = _post_to_resend(payload, f"{dedupe_key}:{uuid.uuid4().hex[:12]}")
    except Exception as exc:  # noqa: BLE001 — network/transport failure
        error = type(exc).__name__
        logger.warning("email send failed kind=%s key=%s error=%s", kind, dedupe_key, error)
        _mark(row_id, {"status": "failed", "error": error})
        return "failed"

    if 200 <= resp.status_code < 300:
        provider_id = None
        try:
            body = resp.json()
            if isinstance(body, dict):
                provider_id = body.get("id")
        except ValueError:
            provider_id = None
        _mark(row_id, {
            "status": "sent",
            "provider_message_id": provider_id,
            "sent_at": _now_iso(),
        })
        return "sent"

    error = _scrub(_error_from_response(resp), to)
    logger.warning("email send failed kind=%s key=%s error=%s", kind, dedupe_key, error)
    _mark(row_id, {"status": "failed", "error": error})
    return "failed"


def send_in_background(background_tasks, **kwargs) -> None:
    """Enqueue `send_email(**kwargs)` to run after the response is sent."""
    background_tasks.add_task(send_email, **kwargs)


# ── Trigger helpers (render + enqueue) ──────────────────────────────────────
#
# Each one is best-effort: a template or hashing error is logged and swallowed,
# because the request that triggered the email must still succeed.


def queue_waitlist_confirmation(background_tasks, email: str) -> None:
    from services import email_templates

    try:
        subject, html, text = email_templates.waitlist_confirmation(
            unsubscribe_url=unsubscribe_url(email),
        )
        send_in_background(
            background_tasks,
            kind="waitlist_confirmation",
            to=email,
            subject=subject,
            html=html,
            text=text,
            dedupe_key=f"waitlist_confirmation:{recipient_hash(email)}",
        )
    except Exception:  # noqa: BLE001
        logger.warning("could not queue waitlist confirmation", exc_info=True)


def queue_waitlist_approved(background_tasks, email: str) -> None:
    from services import email_templates

    try:
        subject, html, text = email_templates.waitlist_approved(
            signin_url=signin_url(),
            unsubscribe_url=unsubscribe_url(email),
        )
        send_in_background(
            background_tasks,
            kind="waitlist_approved",
            to=email,
            subject=subject,
            html=html,
            text=text,
            dedupe_key=waitlist_approved_key(email),
        )
    except Exception:  # noqa: BLE001
        logger.warning("could not queue waitlist approval email", exc_info=True)


def queue_welcome(background_tasks, *, email: str, user_id: str, first_name: Optional[str]) -> None:
    from services import email_templates

    try:
        subject, html, text = email_templates.welcome(
            first_name or None,
            app_url=app_url(),
            unsubscribe_url=unsubscribe_url(email),
        )
        send_in_background(
            background_tasks,
            kind="welcome",
            to=email,
            subject=subject,
            html=html,
            text=text,
            dedupe_key=f"welcome:{user_id}",
        )
    except Exception:  # noqa: BLE001
        logger.warning("could not queue welcome email", exc_info=True)


def waitlist_approved_key(email: str) -> str:
    return f"waitlist_approved:{recipient_hash(email)}"


def signin_url() -> str:
    """The landing page: its "Sign in" button starts Google OAuth."""
    return (getattr(config, "FRONTEND_URL", "") or "").rstrip("/") or "https://saplinglearn.com"


def app_url() -> str:
    return f"{signin_url()}/dashboard"

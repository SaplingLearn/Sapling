"""Transactional + broadcast email over Resend: the ONLY module that talks to it.

Every send goes through `send_email`, which:

1. drops a NOTIFICATION-category kind (`EMAIL_CATEGORIES`: broadcasts, and any
   future digest) for an account whose `user_settings.notification_email` is
   false — returned as `opted_out`, no row written. Transactional kinds (the
   waitlist/welcome lifecycle mail) ignore that setting;
2. refuses a recipient on the suppression list (`email_suppressions`) — for
   EVERY kind of email, recorded as `suppressed` (an earlier `skipped`/`failed`
   row for the key is flipped to `suppressed` too, so the ledger says why);
3. claims the send's `dedupe_key` in `email_sends` with INSERT … ON CONFLICT DO
   NOTHING before anything leaves the process. A key that is `sent`, or
   `queued` under a live lease, is never sent again: that is the "never twice"
   guarantee (revoke + re-approve does not re-send "you're in"). A key whose
   last attempt was `skipped` (no API key yet), `failed`, `suppressed` (since
   un-suppressed by an admin), or `queued` past `STALE_QUEUED_AFTER` (the
   process died mid-send, or its status write failed) can be re-claimed;
4. with no `RESEND_API_KEY` (the kill switch: tests, E2E, local dev) marks the
   row `skipped`; otherwise POSTs to Resend under the key's current
   Idempotency-Key (`_idempotency_key`), and marks it `sent` or `failed`.

The Idempotency-Key is reused only while the last attempt's outcome is
UNKNOWN: a re-claimed send whose earlier attempt may have reached Resend (a
transport error or timeout, a crash before the status write) sends the same
key, so Resend replays its stored result instead of delivering twice. After a
DEFINITIVE provider failure (a non-2xx response), `email_sends.idempotency_gen`
is bumped and the next attempt sends a new key, so a retry is a real retry and
not a replay of the cached failure. Resend keeps keys for 24 hours: a re-claim
after that window can still double-send an attempt whose outcome we never
learned. That is the residual risk (docs/email.md).

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
from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx

import config
from db.connection import page_all, pg_quote_value, table
from db.scope import runs_as_service

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

#: How long a `queued` claim is trusted before it is presumed dead. One live
#: send holds its row for at most ~35 s (two 10 s HTTP timeouts plus a capped
#: Retry-After), so this is far past any real attempt.
STALE_QUEUED_AFTER = timedelta(minutes=15)

#: The ONE kind → category map. "transactional" mail is about the person's own
#: account or signup and always sends (the suppression list aside);
#: "notification" mail (broadcasts, digests, marketing) also honours
#: `user_settings.notification_email`. A kind missing here is treated as
#: "notification", so a new kind respects the opt-out until classified.
EMAIL_CATEGORIES: dict[str, str] = {
    "waitlist_confirmation": "transactional",
    "waitlist_approved": "transactional",
    "welcome": "transactional",
    "broadcast_test": "transactional",  # the admin mailing themself
    "broadcast": "notification",
}


def email_category(kind: str) -> str:
    return EMAIL_CATEGORIES.get(kind, "notification")


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


@runs_as_service  # #115: email_suppressions is service-only
def is_suppressed(rhash: str) -> bool:
    rows = table("email_suppressions").select(
        "recipient_hash", filters={"recipient_hash": f"eq.{rhash}"}, limit=1,
    )
    return bool(rows)


@runs_as_service  # #115: email_suppressions is service-only
def suppress(rhash: str, reason: str = "unsubscribe") -> None:
    """Add a hash to the suppression list. Idempotent: an existing row keeps
    its original reason and timestamp. Raises on a DB error (the unsubscribe
    page must not claim success it did not get)."""
    table("email_suppressions").upsert(
        {"recipient_hash": rhash, "reason": reason},
        on_conflict="recipient_hash",
        ignore_duplicates=True,
    )


@runs_as_service  # #115: email_suppressions is service-only
def unsuppress(rhash: str) -> bool:
    """Remove a hash from the suppression list (the admin undo). True when a
    row was removed. Raises on a DB error, like `suppress`."""
    return bool(table("email_suppressions").delete(
        filters={"recipient_hash": f"eq.{rhash}"},
    ))


# ── Notification opt-out (user_settings.notification_email) ──────────────────

#: The opt-out set is read at most this often per process, so a broadcast
#: does not re-read it per recipient. Also the bound on how long a Settings
#: toggle can take to reach a running send.
OPT_OUT_TTL_S = 60.0
_opt_out_lock = threading.Lock()
_opt_out_cache: Optional[tuple[float, frozenset]] = None


def clear_opt_out_cache() -> None:
    global _opt_out_cache
    with _opt_out_lock:
        _opt_out_cache = None


@runs_as_service  # #115: reads every user's opt-out
def notification_opt_out_hashes(*, fresh: bool = False) -> frozenset:
    """recipient_hash of every account with `notification_email = false`.

    `users.email` is encrypted with a random nonce, so the match is by hash
    after decrypting. Raises on a DB error: the caller decides whether that
    means "don't send" (send_email) or "can't answer" (an audience count)."""
    global _opt_out_cache
    now = time.monotonic()
    with _opt_out_lock:
        cached = _opt_out_cache
    if not fresh and cached is not None and now - cached[0] < OPT_OUT_TTL_S:
        return cached[1]

    from services.encryption import decrypt_if_present

    ids = [
        r["user_id"]
        for r in page_all(
            table("user_settings"), "user_id",
            filters={"notification_email": "eq.false"}, order="user_id.asc",
        )
        if r.get("user_id")
    ]
    hashes: set[str] = set()
    for i in range(0, len(ids), 100):
        chunk = ",".join(pg_quote_value(u) for u in ids[i:i + 100])
        for r in table("users").select("id,email", filters={"id": f"in.({chunk})"}) or []:
            address = (decrypt_if_present(r.get("email")) or "").strip()
            if "@" in address:  # undecryptable ciphertext has no "@"
                hashes.add(recipient_hash(address))
    result = frozenset(hashes)
    with _opt_out_lock:
        _opt_out_cache = (now, result)
    return result


# ── Sending ─────────────────────────────────────────────────────────────────


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _stale_queued_cutoff() -> str:
    """ISO instant before which a `queued` claim is presumed dead. 'Z', not
    '+00:00', so the value needs no URL-escaping inside a logic tree."""
    return (datetime.now(timezone.utc) - STALE_QUEUED_AFTER).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _reclaimable_filter(statuses: str) -> str:
    """PostgREST `or=` tree: a row in one of `statuses`, or a dead `queued` one."""
    cutoff = pg_quote_value(_stale_queued_cutoff())
    return (
        f"(status.in.({statuses}),"
        f"and(status.eq.queued,claimed_at.lt.{cutoff}),"
        "and(status.eq.queued,claimed_at.is.null))"
    )


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


def _idempotency_key(dedupe_key: str, gen: int) -> str:
    """The Resend Idempotency-Key for generation `gen` of a dedupe key: the key
    itself first, then `<key>#<gen>` after each definitive failure. Kept within
    Resend's 256-character limit without cutting off the generation."""
    if not gen:
        return dedupe_key[:256]
    suffix = f"#{gen}"
    return dedupe_key[: 256 - len(suffix)] + suffix


def _error_name(resp: httpx.Response) -> str:
    try:
        body = resp.json()
    except ValueError:
        return ""
    return str(body.get("name") or "") if isinstance(body, dict) else ""


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


def _mark(row_id: str, fields: dict, *, dedupe_key: str = "") -> bool:
    """Write a send's outcome. One retry; never raises. A write that still
    fails is logged at ERROR, not swallowed: the row stays `queued` until
    STALE_QUEUED_AFTER, then the next send of the key re-claims it (and the
    stable Idempotency-Key makes Resend replay, not re-deliver, within 24 h)."""
    for attempt in (1, 2):
        try:
            table("email_sends").update(fields, filters={"id": f"eq.{row_id}"})
            return True
        except Exception:  # noqa: BLE001 — the send already happened (or not); never raise
            if attempt == 2:
                logger.error(
                    "email_sends status write failed id=%s key=%s status=%s; the row stays "
                    "queued until its lease expires", row_id, dedupe_key, fields.get("status"),
                    exc_info=True,
                )
    return False


def _reclaim(dedupe_key: str) -> list:
    """Re-claim a key whose last attempt was `skipped`, `failed` or
    `suppressed` (the recipient has since been un-suppressed), or whose
    `queued` lease has expired.

    Conditional on that state, so of two concurrent re-claims only one gets
    the row back. Never raises.
    """
    try:
        return table("email_sends").update(
            {"status": "queued", "error": None, "claimed_at": _now_iso()},
            filters={
                "dedupe_key": f"eq.{dedupe_key}",
                "or": _reclaimable_filter("skipped,failed,suppressed"),
            },
        ) or []
    except Exception:  # noqa: BLE001
        logger.warning("email re-claim failed key=%s", dedupe_key, exc_info=True)
        return []


def _record_suppressed(dedupe_key: str) -> None:
    """A suppressed recipient whose key already has a row: flip a
    `skipped`/`failed`/dead-`queued` row to `suppressed`, so the ledger says
    why it will never go out. A `sent` row is history and stays. Never raises."""
    try:
        table("email_sends").update(
            {"status": "suppressed", "error": None},
            filters={"dedupe_key": f"eq.{dedupe_key}", "or": _reclaimable_filter("skipped,failed")},
        )
    except Exception:  # noqa: BLE001
        logger.warning("email suppressed-status write failed key=%s", dedupe_key, exc_info=True)


@runs_as_service  # #115: email_sends/email_suppressions are service-only
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

    Returns the final status: "sent" | "skipped" | "failed" | "suppressed",
    "opted_out" (a notification-category kind to an account that turned email
    notifications off; nothing recorded), or "duplicate" when the key is
    already sent or held by a live attempt (nothing is sent). Never raises.
    """
    try:
        if not normalize_email(to):
            logger.warning("email send with no recipient kind=%s key=%s", kind, dedupe_key)
            return "failed"
        rhash = recipient_hash(to)
    except Exception:  # noqa: BLE001
        logger.warning("email recipient hashing failed kind=%s key=%s", kind, dedupe_key, exc_info=True)
        return "failed"

    if email_category(kind) != "transactional":
        try:
            opted_out = rhash in notification_opt_out_hashes()
        except Exception:  # noqa: BLE001
            # Can't tell whether they opted out, so don't send. No row is
            # written, so a later run (a broadcast resume) tries again.
            logger.warning("email opt-out read failed kind=%s key=%s", kind, dedupe_key, exc_info=True)
            return "failed"
        if opted_out:
            logger.info("email notifications off; not sent kind=%s key=%s", kind, dedupe_key)
            return "opted_out"

    try:
        suppressed = is_suppressed(rhash)
        row = {
            "kind": kind,
            "dedupe_key": dedupe_key,
            "recipient_hash": rhash,
            "status": "suppressed" if suppressed else "queued",
            "claimed_at": _now_iso(),
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

    if suppressed:
        if not claimed:
            _record_suppressed(dedupe_key)
        logger.info("email suppressed kind=%s key=%s", kind, dedupe_key)
        return "suppressed"
    if not claimed:
        claimed = _reclaim(dedupe_key)
    if not claimed:
        logger.info("email already claimed kind=%s key=%s", kind, dedupe_key)
        return "duplicate"

    row_id = claimed[0].get("id")
    try:
        gen = int(claimed[0].get("idempotency_gen") or 0)
    except (TypeError, ValueError):
        gen = 0

    if not is_configured():
        logger.info("RESEND_API_KEY unset; email skipped kind=%s key=%s", kind, dedupe_key)
        _mark(row_id, {"status": "skipped"}, dedupe_key=dedupe_key)
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

    # Same key while the last outcome is unknown (Resend replays instead of
    # mailing again); a new generation after a definitive failure (a replay of
    # the cached failure would make every retry a no-op for 24 h). Resend
    # holds keys for 24 h; a re-claim after that can double-send an attempt
    # whose outcome we never learned (the documented residual risk).
    try:
        resp = _post_to_resend(payload, _idempotency_key(dedupe_key, gen))
    except Exception as exc:  # noqa: BLE001 — network/transport failure: outcome UNKNOWN
        error = type(exc).__name__
        logger.warning("email send failed kind=%s key=%s error=%s", kind, dedupe_key, error)
        _mark(row_id, {"status": "failed", "error": error}, dedupe_key=dedupe_key)
        return "failed"

    if resp.status_code == 409 and _error_name(resp) == "concurrent_idempotent_requests":
        # Another attempt with this key is in flight at Resend (a stale-queued
        # re-claim racing a live send): it owns the outcome and writes it to
        # this same row. Leave the row alone; if that attempt is dead too, the
        # row goes stale again and the next send re-claims it.
        logger.info("email already in flight at Resend kind=%s key=%s", kind, dedupe_key)
        return "duplicate"

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
        }, dedupe_key=dedupe_key)
        return "sent"

    error = _scrub(_error_from_response(resp), to)
    logger.warning("email send failed kind=%s key=%s error=%s", kind, dedupe_key, error)
    fields: dict = {"status": "failed", "error": error}
    if not (resp.status_code == 409 and _error_name(resp) == "invalid_idempotent_request"):
        # Definitive: Resend answered and did not send. The next attempt gets a
        # fresh key. (A 409 for a changed payload means an earlier request with
        # this key reached Resend and its outcome is still unknown: keep it.)
        fields["idempotency_gen"] = gen + 1
    _mark(row_id, fields, dedupe_key=dedupe_key)
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


def queue_waitlist_approved(background_tasks, email: str, first_name: Optional[str] = None) -> None:
    from services import email_templates

    try:
        subject, html, text = email_templates.waitlist_approved(
            first_name,
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


def _already_sent(dedupe_key: str) -> bool:
    """Whether the ledger records this key as `sent`. False on any error."""
    try:
        rows = table("email_sends").select(
            "status", filters={"dedupe_key": f"eq.{dedupe_key}"}, limit=1,
        )
    except Exception:  # noqa: BLE001
        logger.warning("email_sends status read failed key=%s", dedupe_key, exc_info=True)
        return False
    return bool(rows) and rows[0].get("status") == "sent"


def _send_then(on_sent, **kwargs) -> str:
    """`send_email`, then `on_sent()` once the mail has actually gone out:
    on `sent`, and on a `duplicate` whose ledger row is `sent` (an earlier
    delivery whose hook failed; without this the caller would re-run on every
    trigger forever). Never raises."""
    status = send_email(**kwargs)
    if on_sent is None:
        return status
    went_out = status == "sent" or (
        status == "duplicate" and _already_sent(kwargs.get("dedupe_key") or "")
    )
    if went_out:
        try:
            on_sent()
        except Exception:  # noqa: BLE001
            logger.warning("post-send hook failed key=%s", kwargs.get("dedupe_key"), exc_info=True)
    return status


def queue_welcome(
    background_tasks, *, email: str, user_id: str, first_name: Optional[str], on_sent=None,
) -> None:
    """Enqueue the welcome. `on_sent` runs only after a `sent` outcome (auth
    stamps `users.welcomed_at` there), so a `skipped`/`failed` welcome is
    retried on a later sign-in, and the `welcome:<user_id>` dedupe key keeps
    it to one delivery."""
    from services import email_templates

    try:
        subject, html, text = email_templates.welcome(
            first_name or None,
            app_url=app_url(),
            unsubscribe_url=unsubscribe_url(email),
        )
        background_tasks.add_task(
            _send_then,
            on_sent,
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

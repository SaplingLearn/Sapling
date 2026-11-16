"""
backend/services/gradescope/credentials.py

Stored Gradescope credentials (#118, moved from routes/gradescope.py): read and
decrypt them, log in with them, and record connection / sync-outcome state on
the ``gradescope_credentials`` row.

What is stored is a Gradescope SESSION, never a password. Every way of
connecting ends in ``save_cookie_creds`` (``auth_mode='cookies'``):

- email + password: ``POST /credentials`` logs in once
  (``client.login_for_session_cookies``) and stores the resulting cookies;
- BU SSO: the cookies the browser flow harvested;
- pasted cookies: as pasted.

The encrypted blob records how the session was obtained (``via``), so the UI
can tell a password user to enter their password again when the session
expires (409 ``gradescope_reauth_required``) instead of implying it was kept.

Legacy rows. Before 2026-11-16 password mode stored the password itself
(``auth_mode='password'``, ``password_encrypted``). Such a row still works:
its next login (a sync or a course listing) uses the password once, stores
the session it produced and nulls ``password_encrypted`` and
``email_encrypted`` (``_retire_password``); ``scripts/retire_gradescope_
passwords.py --apply`` does the same for every row at once. The column and
the ``password`` branch of ``gradescope_credentials_payload_chk`` stay until
no row holds a password in any environment; a later migration drops both
(docs/security/data-inventory.md).
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Literal

from gradescopeapi.classes.connection import GSConnection
from pydantic import BaseModel, SecretStr

from db.connection import table
from services.gradescope import client as gradescope_service
from services.encryption import decrypt, encrypt
from services.gradescope.errors import GradescopeCredsError

logger = logging.getLogger(__name__)


AuthMode = Literal["password", "cookies"]
#: How a stored session was obtained (kept in the encrypted cookie blob).
ConnectedVia = Literal["password", "bu_sso", "cookies"]
_VIA_VALUES = ("password", "bu_sso", "cookies")


class StoredCreds(BaseModel):
    """Decrypted credentials. The secrets are SecretStr: a repr, str or log of
    this object shows ``**********``; ``reveal`` unwraps one at its use."""

    auth_mode: AuthMode
    email: str | None = None
    password: SecretStr | None = None  # legacy password-mode rows only
    gradescope_session: SecretStr | None = None
    signed_token: SecretStr | None = None
    connected_via: ConnectedVia | None = None
    # Row metadata, not secrets: which saved version these are (the guard for
    # marking them stale) and whether they were already known to be rejected.
    updated_at: str | None = None
    needs_reauth: bool = False


def reveal(secret: SecretStr | None) -> str | None:
    """The plain value of an optional secret, at the point of use."""
    return secret.get_secret_value() if secret is not None else None


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write_connection_state(user_id: str, fields: dict[str, Any], *, only_version: str | None = None) -> None:
    """Persist connection/sync-outcome columns on the credentials row. Never
    raises: the state is bookkeeping, and a failed write must not turn a
    finished sync (or its real error) into a 500.

    ``only_version`` pins the write to the credential version that produced the
    outcome (``updated_at`` as read with the creds): marking credentials stale
    must not land on a newer set the user saved while this request was running.
    """
    filters = {"user_id": f"eq.{user_id}"}
    if only_version:
        filters["updated_at"] = f"eq.{only_version}"
    try:
        table("gradescope_credentials").update(fields, filters=filters)
    except Exception:
        logger.warning("Failed to record Gradescope connection state for user_id=%s", user_id, exc_info=True)


def _via_of(payload: dict) -> ConnectedVia:
    via = payload.get("via")
    return via if via in _VIA_VALUES else "cookies"


def _load_creds(user_id: str) -> StoredCreds | None:
    """Fetch and decrypt stored Gradescope credentials for user_id. Returns None if none saved."""
    rows = table("gradescope_credentials").select(
        "auth_mode,email_encrypted,password_encrypted,cookies_encrypted,updated_at,needs_reauth",
        filters={"user_id": f"eq.{user_id}"},
        limit=1,
    )
    if not rows:
        return None
    row = rows[0]
    mode: AuthMode = row.get("auth_mode") or "password"
    meta = {"updated_at": row.get("updated_at"), "needs_reauth": bool(row.get("needs_reauth"))}
    try:
        if mode == "password":
            return StoredCreds(
                auth_mode="password",
                email=decrypt(row["email_encrypted"]) if row.get("email_encrypted") else None,
                password=decrypt(row["password_encrypted"]) if row.get("password_encrypted") else None,
                connected_via="password",
                **meta,
            )
        else:  # cookies
            raw = decrypt(row["cookies_encrypted"]) if row.get("cookies_encrypted") else None
            payload = json.loads(raw) if raw else {}
            return StoredCreds(
                auth_mode="cookies",
                gradescope_session=payload.get("_gradescope_session"),
                signed_token=payload.get("signed_token"),
                connected_via=_via_of(payload),
                **meta,
            )
    except Exception:
        logger.exception("Failed to decrypt Gradescope creds for user_id=%s", user_id)
        raise GradescopeCredsError("Stored credentials could not be read.")


def _cookie_blob(gradescope_session: str | None, signed_token: str | None, via: ConnectedVia) -> str:
    return json.dumps(
        {
            "_gradescope_session": gradescope_session,
            "signed_token": signed_token or None,
            "via": via,
        }
    )


def _convert_password_row(user_id: str, cookies: dict[str, str], *, only_version: str | None) -> bool:
    """Turn a legacy password-mode row into the session ``cookies`` came from
    and erase the stored password and email. Guarded on the row still being
    that password version, so it never overwrites credentials saved since.
    Returns whether a row was converted."""
    filters = {"user_id": f"eq.{user_id}", "auth_mode": "eq.password"}
    if only_version:
        filters["updated_at"] = f"eq.{only_version}"
    rows = table("gradescope_credentials").update(
        {
            "auth_mode": "cookies",
            "cookies_encrypted": encrypt(_cookie_blob(
                cookies.get("_gradescope_session"), cookies.get("signed_token"), "password",
            )),
            "password_encrypted": None,
            "email_encrypted": None,
            "needs_reauth": False,
        },
        filters=filters,
    )
    return bool(rows)


def _retire_password(user_id: str, creds: StoredCreds, conn: GSConnection) -> None:
    """After a legacy password row logged in: keep the session, drop the
    password. Never raises; a failure leaves the legacy row for next time."""
    try:
        cookies = gradescope_service.session_cookies(conn)
        if _convert_password_row(user_id, cookies, only_version=creds.updated_at):
            logger.info("gradescope: stored password replaced by its session for user_id=%s", user_id)
    except Exception as e:
        logger.warning(
            "gradescope: could not retire the stored password for user_id=%s (%s); "
            "retried on the next login", user_id, type(e).__name__,
        )


def _establish_connection(creds: StoredCreds, *, user_id: str | None = None) -> GSConnection:
    """Re-establish an authenticated Gradescope session from stored creds.

    A legacy password row logs in with the password one last time and, when
    ``user_id`` is given, is converted to that login's session
    (``_retire_password``)."""
    if creds.auth_mode == "password":
        if not creds.email or not creds.password:
            raise GradescopeCredsError("Password-mode creds missing email/password")
        conn = gradescope_service.login(creds.email, reveal(creds.password), remember_me=True)
        if user_id:
            _retire_password(user_id, creds, conn)
        return conn
    return gradescope_service.login_with_cookies(
        signed_token=reveal(creds.signed_token),
        gradescope_session=reveal(creds.gradescope_session),
    )


def reauth_message(creds: StoredCreds, error: Exception) -> str:
    """What the 409 ``gradescope_reauth_required`` tells the student, worded
    for how they connected: a password user enters the password again (it was
    never kept), a BU user signs in with BU again; pasted cookies keep the
    client's own explanation (expired vs. malformed cookie)."""
    if creds.connected_via == "password":
        return ("Your Gradescope session expired. Enter your Gradescope password again "
                "to reconnect; Sapling doesn't keep it.")
    if creds.connected_via == "bu_sso":
        return "Your Gradescope session expired. Sign in with BU again to reconnect."
    return str(error)


RetireOutcome = Literal["converted", "not_password", "rejected", "unreachable", "changed", "unreadable"]


def retire_stored_password(user_id: str) -> RetireOutcome:
    """One-off conversion of a legacy password row (the backfill script):
    log in once, store the session, null the password. Never raises."""
    try:
        creds = _load_creds(user_id)
    except GradescopeCredsError:
        return "unreadable"
    if creds is None or creds.auth_mode != "password":
        return "not_password"
    if not creds.email or not creds.password:
        return "unreadable"
    try:
        cookies = gradescope_service.login_for_session_cookies(creds.email, reveal(creds.password))
    except gradescope_service.GradescopeAuthError:
        return "rejected"
    except gradescope_service.GradescopeFetchError:
        return "unreachable"
    if _convert_password_row(user_id, cookies, only_version=creds.updated_at):
        return "converted"
    return "changed"


def connection_status(user_id: str) -> dict:
    """GET /status's answer: the connection state and the last sync outcome
    (see the route's docstring for the fields). ``connected_via`` says how the
    stored session was obtained (``password`` | ``bu_sso`` | ``cookies``), so a
    client can word the reconnect for it."""
    rows = table("gradescope_credentials").select(
        "auth_mode,cookies_encrypted,last_synced_at,updated_at,needs_reauth,last_attempt_at,last_sync_error",
        filters={"user_id": f"eq.{user_id}"},
        limit=1,
    )
    if not rows:
        return {
            "state": "disconnected",
            "connected": False,
            "has_credentials": False,
            "needs_reauth": False,
            "auth_mode": None,
            "connected_via": None,
            "last_synced_at": None,
            "last_attempt_at": None,
            "last_sync_error": None,
        }
    row = rows[0]
    needs_reauth = bool(row.get("needs_reauth"))
    auth_mode = row.get("auth_mode") or "password"
    return {
        "state": "needs_reauth" if needs_reauth else "connected",
        "connected": not needs_reauth,
        "has_credentials": True,
        "needs_reauth": needs_reauth,
        "auth_mode": auth_mode,
        "connected_via": _status_via(auth_mode, row.get("cookies_encrypted")),
        "last_synced_at": row.get("last_synced_at"),
        "last_attempt_at": row.get("last_attempt_at"),
        "last_sync_error": row.get("last_sync_error"),
        "credentials_updated_at": row.get("updated_at"),
    }


def _status_via(auth_mode: str, cookies_encrypted: str | None) -> ConnectedVia:
    if auth_mode == "password":
        return "password"
    if not cookies_encrypted:
        return "cookies"
    try:
        return _via_of(json.loads(decrypt(cookies_encrypted)))
    except Exception:
        return "cookies"


def _save_creds(payload: dict[str, Any]) -> None:
    """Upsert a verified credentials row (the caller tested the login)."""
    payload["updated_at"] = _now_iso()
    # Fresh, verified credentials: whatever marked the old ones stale is moot.
    payload["needs_reauth"] = False
    payload["last_sync_error"] = None
    table("gradescope_credentials").upsert(payload, on_conflict="user_id")


def save_cookie_creds(
    user_id: str, gradescope_session: str | None, signed_token: str | None,
    *, via: ConnectedVia = "cookies",
) -> None:
    """Encrypt and save a Gradescope session that just logged in (pasted by the
    user, captured by the BU SSO flow, or produced by a one-time password
    login), as auth_mode='cookies'. ``via`` records which. Never a password:
    ``password_encrypted`` and ``email_encrypted`` are written NULL."""
    payload = {
        "user_id": user_id,
        "auth_mode": "cookies",
        "email_encrypted": None,
        "password_encrypted": None,
        "cookies_encrypted": encrypt(_cookie_blob(gradescope_session, signed_token, via)),
    }
    _save_creds(payload)

"""AES-256-GCM column-level encryption for sensitive Supabase columns.

The 32-byte key is loaded once from the ENCRYPTION_KEY env var (64 hex chars)
at import time. Every seal mints a fresh 12-byte nonce.

TWO ENVELOPES (docs/security/encryption-aad-plan.md, finding M13)
────────────────────────────────────────────────────────────────
    v1 (legacy):  base64(nonce || ct || tag)                 AAD None
    v2:           "enc2:" kid ":" base64(nonce || ct || tag) AAD = the binding

A v1 value carries no record of where it belongs, so anyone who can write the
database without the key can move or swap ciphertext between rows, columns and
users and the app decrypts it as genuine in its new place. A v2 value is sealed
with associated data that names its cell:

    aad = b"sapling/enc/v2|" + table + "|" + column + "|" + row_key

so it opens only in the cell it was written for. The AAD is never stored: the
writer and the reader each rebuild it from the row they touch, through
:func:`bind` and the :data:`ENCRYPTED_COLUMNS` registry (one place decides
which columns make up each table's row key, so a writer and a reader cannot
disagree). The base64 alphabet has no ``:``, so ``enc2:`` never begins a v1
value and the reader dispatches on the prefix alone. ``kid`` is a key id; today
the only key is ``ENCRYPTION_KEY`` as kid ``0`` (online rotation, the plan's
``ENCRYPTION_KEYS``, is not built yet: an unknown kid is a hard failure).

READS
─────
* v2, with a binding: open under the binding's AAD. Any failure (a moved or
  swapped value, a wrong kid, tampering) is HARD: :func:`decrypt` raises
  :class:`BindingMismatch`; the soft helpers return ``None``. Never the raw
  value, never plaintext. A content-free ``encryption.binding_mismatch`` event
  is logged (events_service) and counted (:func:`security_counts`).
* v2, without a binding: the same hard failure. A reader that has not been
  threaded through cannot open v2 data by accident.
* v1 or plaintext: today's path (AAD None; plaintext comes back raw with a
  WARNING) while legacy reads are allowed for the binding's table. Once they
  are not (``ENCRYPTION_LEGACY_READS=refuse``, or the table in
  ``ENCRYPTION_STRICT_TABLES``), a bound read of anything without the ``enc2:``
  prefix is refused like a mismatch (``encryption.legacy_refused``): that is
  what closes plaintext injection. Unbound reads (the few legacy-only sites
  `tests/test_encryption_aad_inventory.py` allowlists) always take the v1 path.

WRITES
──────
A write with a binding produces v2 when ``ENCRYPTION_WRITE_V2`` is on, else
v1. The switch exists so the readers ship (and are live in every environment)
BEFORE any v2 value is written: a backend without this module cannot read v2,
so flipping writers first would show ciphertext to a rolling deploy's old
instances and to a rollback. It is a process-wide format switch, not a feature
flag: the format must not vary per student. Writes without a binding are v1
(the inventory test keeps that to the allowlisted sites).

Row keys are listed in :data:`ENCRYPTED_COLUMNS`. Where a table's primary key
is minted by Postgres, its writers mint it in Python first so the key is known
before encryption. Where ciphertext is copied by SQL between rows
(``materialize_tutor_session`` copies the pending greeting into ``messages``),
or a row is upserted on a natural key, the binding uses the key that survives
the copy (``messages.content`` binds to ``session_id``): it still stops
cross-user and cross-session moves, not moves inside one session.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import threading
from collections import Counter
from dataclasses import dataclass
from typing import Any, Mapping

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

logger = logging.getLogger(__name__)

_NONCE_BYTES = 12  # AES-GCM standard nonce length

V2_PREFIX = "enc2:"
ACTIVE_KID = "0"
_AAD_DOMAIN = b"sapling/enc/v2|"


def _load_key() -> bytes:
    raw = os.getenv("ENCRYPTION_KEY", "").strip()
    if not raw:
        raise RuntimeError(
            "ENCRYPTION_KEY env var is not set. Generate one with: "
            "python -c \"import secrets; print(secrets.token_hex(32))\""
        )
    if len(raw) != 64:
        raise RuntimeError(
            f"ENCRYPTION_KEY must be 64 hex chars (32 bytes); got {len(raw)} chars."
        )
    try:
        key = bytes.fromhex(raw)
    except ValueError as e:
        raise RuntimeError("ENCRYPTION_KEY is not valid hex") from e
    if len(key) != 32:
        raise RuntimeError("ENCRYPTION_KEY must decode to exactly 32 bytes")
    return key


_KEY = _load_key()
_AESGCM = AESGCM(_KEY)


def derive_key(purpose: str) -> bytes:
    """A 32-byte server secret for `purpose`, derived from ENCRYPTION_KEY as
    HMAC-SHA256(key, "sapling/" + purpose): deterministic, never the AES key
    itself, and a different key for every purpose. For keyed hashes a client
    must not be able to recompute (e.g. the check items' correct-option slot,
    learning-loop spec §13 A37) — never for encryption."""
    if not purpose:
        raise ValueError("derive_key needs a non-empty purpose")
    return hmac.new(_KEY, f"sapling/{purpose}".encode("utf-8"), hashlib.sha256).digest()


def _cipher_for(kid: str) -> AESGCM | None:
    """The cipher for a key id. Only kid "0" (ENCRYPTION_KEY) exists; v1
    values are always read as kid "0". Looked up per call, so a test that
    swaps `_AESGCM` swaps both envelopes."""
    return _AESGCM if kid == ACTIVE_KID else None


# ── Errors ──────────────────────────────────────────────────────────────────


class EncryptionError(ValueError):
    """A value was refused for a reason that is never legacy data."""


class BindingMismatch(EncryptionError):
    """A v2 value did not open in this cell: moved, swapped, tampered with,
    read without a binding, or under an unknown key id."""


class LegacyRefused(EncryptionError):
    """A v1 or plaintext value read where legacy reads are no longer allowed."""


class UnknownColumn(KeyError):
    """`bind` was asked for a (table, column) the registry does not list."""


class MissingRowKey(ValueError):
    """`bind` could not build the row key: a key column is absent or empty.

    Raised on purpose: a binding built from a partial row would seal a value
    that no reader can open again."""


# ── Bindings and the registry (the plan's phase-0 inventory) ────────────────


@dataclass(frozen=True)
class Binding:
    """Where a value lives. Literal table/column names, never request data."""

    table: str
    column: str
    row_key: str

    def aad(self) -> bytes:
        return _AAD_DOMAIN + f"{self.table}|{self.column}|{self.row_key}".encode("utf-8")


TEXT, JSON, NUMERIC, BYTES = "text", "json", "numeric", "bytes"


@dataclass(frozen=True)
class ColumnSpec:
    """One 🔒 column.

    ``key``: the row-key columns, in AAD order (joined with ``|``).
    ``pk``: the primary key, which the backfill pages and PATCHes on.
    ``aad_table``/``aad_column``: when the value is sealed for ANOTHER cell
    (a staging column SQL later copies into its real home), the cell it is
    sealed for. ``backfill``: False for a column the AAD backfill leaves alone.
    """

    table: str
    column: str
    kind: str = TEXT
    key: tuple[str, ...] = ("id",)
    pk: tuple[str, ...] = ("id",)
    aad_table: str | None = None
    aad_column: str | None = None
    backfill: bool = True
    note: str = ""


def _cols(table: str, columns: dict[str, str], **kw: Any) -> list[ColumnSpec]:
    return [ColumnSpec(table, column, kind, **kw) for column, kind in columns.items()]


#: Every 🔒 column, its kind and its row key. A new 🔒 column is added HERE
#: first; `bind` refuses a pair that is not listed.
ENCRYPTED_COLUMNS: tuple[ColumnSpec, ...] = tuple([
    # Identity.
    ColumnSpec("users", "email"),
    *_cols("user_profiles", {c: TEXT for c in ("name", "first_name", "last_name", "bio", "location")},
           key=("user_id",), pk=("user_id",)),
    *_cols("oauth_tokens", {"access_token": TEXT, "refresh_token": TEXT},
           key=("user_id",), pk=("user_id",)),
    *_cols("gradescope_credentials",
           {"email_encrypted": TEXT, "password_encrypted": TEXT, "cookies_encrypted": TEXT},
           key=("user_id",), pk=("user_id",)),
    # Upserted on the plaintext email (ADR 0026), whose row keeps its id; the
    # email is the stable identity the first name belongs to.
    ColumnSpec("newsletter_emails", "first_name", key=("email",)),
    # Chat. `materialize_tutor_session` (SQL) copies the pending greeting into
    # `messages`, so the row id is not known when it is sealed: bind to the
    # session, the owner key that survives the copy.
    ColumnSpec("messages", "content", key=("session_id",),
               note="owner fallback: SQL copies the pending greeting into messages"),
    ColumnSpec("tutor_pending_sessions", "assistant_reply", key=("session_id",),
               pk=("session_id",), aad_table="messages", aad_column="content",
               note="sealed for messages.content: materialisation copies it as is"),
    ColumnSpec("room_messages", "text"),
    ColumnSpec("sessions", "summary_json", JSON),
    # Documents and notes.
    *_cols("documents", {"summary": TEXT, "concept_notes": JSON, "extracted_text": TEXT}),
    *_cols("notes", {"title": TEXT, "body": TEXT, "last_summary": TEXT}),
    *_cols("document_uploads", {"file_data": BYTES, "result": JSON}),
    # Content-addressed id (a hash of the plaintext), known before encryption
    # and stable across the shared dedupe upsert.
    ColumnSpec("course_chunks", "chunk_text"),
    ColumnSpec("topic_checklists", "content", JSON, key=("enrollment_id",), pk=("enrollment_id",)),
    # Gradebook.
    *_cols("assignments", {"notes": TEXT, "points_possible": NUMERIC, "points_earned": NUMERIC}),
    # Feedback.
    *_cols("feedback", {"comment": TEXT, "topic": TEXT}),
    *_cols("issue_reports", {"topic": TEXT, "description": TEXT}),
    # Quizzes.
    *_cols("quiz_attempts", {"questions_json": JSON, "answers_json": JSON}),
    ColumnSpec("quiz_context", "context_json", JSON, key=("user_id", "concept_node_id"),
               note="upserted on (user_id, concept_node_id); its id is never sent"),
    ColumnSpec("quiz_responses", "answer_text", JSON, key=("attempt_id", "question_index"),
               note="one row per (attempt, question): the natural key"),
    # Study.
    *_cols("flashcards", {"front": TEXT, "back": TEXT}),
    *_cols("study_guides", {"content": JSON, "previous_content": JSON, "answers": JSON}),
    ColumnSpec("room_summaries", "summary", key=("room_id",), pk=("room_id",)),
    # Learning loop. check_items ids are minted in Python (item_id: a hash of
    # course, concept key and question hash); a re-tag that moves an item to a
    # new id re-seals every value for the new row (check_item_service).
    *_cols("check_items", {
        "prompt": TEXT, "reference_answer": TEXT, "final_answer": TEXT,
        "rubric_json": JSON, "common_wrong_json": JSON, "options_json": JSON,
        "correct_option": TEXT, "canonical_answer": TEXT, "surface_context": TEXT,
    }),
    ColumnSpec("sessions", "close_json", JSON),
    ColumnSpec("sessions", "loop_brief"),
    # Upserted by SQL on (user_id, node_id, wrong_key) WHERE resolved_at IS
    # NULL, which keeps an existing row's id: bind to that natural key.
    ColumnSpec("misconceptions", "evidence_text", key=("user_id", "node_id", "wrong_key"),
               note="the upsert keeps an existing row's id: its natural key"),
    # id is a DB default; one row per (user, session, node).
    ColumnSpec("learning_prequestions", "guess_json", JSON,
               key=("user_id", "session_id", "node_id"),
               note="id is a DB default: the row's unique natural key"),
    ColumnSpec("learning_self_explanations", "reply_text"),
    # The key canary: read with legacy always allowed, never backfilled (a v2
    # canary would make a rollback to pre-v2 code refuse to boot).
    ColumnSpec("encryption_key_check", "canary", backfill=False),
])

_SPECS: dict[tuple[str, str], ColumnSpec] = {(s.table, s.column): s for s in ENCRYPTED_COLUMNS}

#: Tokens sealed outside the database (the pending sign-up link's claims,
#: services/auth/pending.py). Not columns: bound with a fixed row key so the
#: email claim cannot be swapped with the name claim.
TOKEN_CLAIMS = "auth_pending_token"


def column_spec(table: str, column: str) -> ColumnSpec:
    try:
        return _SPECS[(table, column)]
    except KeyError:
        raise UnknownColumn(f"{table}.{column} is not in encryption.ENCRYPTED_COLUMNS") from None


def bind(table: str, column: str, row: Any) -> Binding:
    """The binding for ``table.column`` in ``row``.

    ``row`` is the row dict (the key columns are read off it), a tuple of the
    key values in the registry's order, or the single key value itself."""
    spec = column_spec(table, column)
    if isinstance(row, Mapping):
        parts = [row.get(k) for k in spec.key]
    elif isinstance(row, (tuple, list)):
        parts = list(row)
    else:
        parts = [row]
    if len(parts) != len(spec.key) or any(p is None or p == "" for p in parts):
        raise MissingRowKey(
            f"{table}.{column}: row key {spec.key} incomplete; select/mint "
            f"{', '.join(spec.key)} before sealing or opening this column"
        )
    return Binding(spec.aad_table or table, spec.aad_column or column,
                   "|".join(str(p) for p in parts))


def claim_binding(claim: str) -> Binding:
    """Binding for one claim of the pending sign-up token (not a column)."""
    return Binding(TOKEN_CLAIMS, claim, "claims")


#: Ciphertexts stored INSIDE a plaintext jsonb column rather than as a column
#: of their own: (table, column, path). Not in ENCRYPTED_COLUMNS (the backfill
#: and the account bundle walk real columns); bound with `nested_bind`.
#: sessions.loop_state carries the student's goal text (ADR 0033) and a step's
#: or probe's sealed grade checkpoint (ADR 0038), both keyed on the session.
NESTED_CIPHERTEXTS: frozenset[tuple[str, str, str]] = frozenset({
    ("sessions", "loop_state", "goal.text_encrypted"),
    ("sessions", "loop_state", "grade_checkpoint"),
})


def nested_bind(table: str, column: str, path: str, row_key: Any) -> Binding:
    """The binding for a ciphertext at ``path`` inside ``table.column`` of the
    row keyed ``row_key``. Refuses a (table, column, path) not listed in
    NESTED_CIPHERTEXTS, and an empty row key, like `bind`."""
    if (table, column, path) not in NESTED_CIPHERTEXTS:
        raise UnknownColumn(f"{table}.{column}#{path} is not in encryption.NESTED_CIPHERTEXTS")
    if row_key is None or row_key == "":
        raise MissingRowKey(f"{table}.{column}#{path}: empty row key")
    return Binding(table, f"{column}#{path}", str(row_key))


# ── Settings (read per call: cheap, and tests can flip them) ────────────────
#
# These are env vars, NOT services/feature_flags.py flags, deliberately (the
# one sanctioned exception to CLAUDE.md's "never gate with a new env var"):
# every encrypt/decrypt reads them synchronously, including inside async
# handlers, in offline scripts and backfills, in the worker, and in the boot
# key check before anything else runs. A flag read can hit the database on a
# snapshot miss (a sync DB call on the event loop) and can be unreachable; the
# ciphertext format must not depend on the flag store answering. They are
# per-process settings that the API and the worker must share
# (.railway/railway.ts HANDLER_VARIABLES pins that).

_ON = {"1", "true", "on", "yes"}


def write_v2_enabled() -> bool:
    """``ENCRYPTION_WRITE_V2``: bound writes produce v2. Default off."""
    return os.getenv("ENCRYPTION_WRITE_V2", "off").strip().lower() in _ON


def legacy_reads_allowed(table: str) -> bool:
    """May a BOUND read of ``table`` open a v1/plaintext value?

    ``ENCRYPTION_LEGACY_READS``: ``allow`` (default) | ``refuse`` (every
    table). ``ENCRYPTION_STRICT_TABLES``: comma list of tables that refuse
    while the global setting still allows (phase 4, one table at a time).
    Any other value of the global setting is read as ``refuse``: whoever set
    it meant to change the default."""
    mode = os.getenv("ENCRYPTION_LEGACY_READS", "allow").strip().lower()
    if mode not in ("", "allow"):
        if mode != "refuse":
            logger.warning("ENCRYPTION_LEGACY_READS=%r is not allow|refuse; refusing", mode)
        return False
    strict = os.getenv("ENCRYPTION_STRICT_TABLES", "")
    return table not in {t.strip() for t in strict.split(",") if t.strip()}


# ── Security signals (content-free) ─────────────────────────────────────────

_counts: Counter = Counter()
_counts_lock = threading.Lock()


def security_counts() -> dict[tuple[str, str, str], int]:
    """(kind, table, column) -> refusals since boot (or the last reset)."""
    with _counts_lock:
        return dict(_counts)


def reset_security_counts() -> None:
    with _counts_lock:
        _counts.clear()


def _report(kind: str, bind_: Binding | None, reason: str, version: str) -> None:
    """Count and log one refusal. Never the value, never the plaintext."""
    table_, column = (bind_.table, bind_.column) if bind_ else ("<unbound>", "<unbound>")
    with _counts_lock:
        _counts[(kind, table_, column)] += 1
    logger.warning("encryption %s: %s.%s (%s, %s) row_key=%s", kind, table_, column,
                   reason, version, bind_.row_key if bind_ else None)
    try:
        from services import events_service

        events_service.log_event(
            f"encryption.{kind}", category=events_service.SYSTEM_CATEGORY,
            payload={"table": table_, "column": column, "reason": reason, "version": version},
        )
    except Exception:  # pragma: no cover - a signal must never break a read
        logger.debug("encryption event not logged", exc_info=True)


# ── Seal / open ─────────────────────────────────────────────────────────────


def _seal_v1(data: bytes) -> str:
    nonce = os.urandom(_NONCE_BYTES)
    return base64.b64encode(nonce + _AESGCM.encrypt(nonce, data, None)).decode("ascii")


def _seal_v2(data: bytes, bind_: Binding) -> str:
    nonce = os.urandom(_NONCE_BYTES)
    ct = _cipher_for(ACTIVE_KID).encrypt(nonce, data, bind_.aad())
    return f"{V2_PREFIX}{ACTIVE_KID}:" + base64.b64encode(nonce + ct).decode("ascii")


def _seal(data: bytes, bind_: Binding | None, v2: bool | None) -> str:
    if v2 is None:
        # Unbound writes (the allowlisted legacy sites) stay v1.
        want_v2 = bind_ is not None and write_v2_enabled()
    else:
        want_v2 = v2
    if want_v2:
        if bind_ is None:
            raise ValueError("a v2 seal needs a binding")
        return _seal_v2(data, bind_)
    return _seal_v1(data)


def is_v2(value: Any) -> bool:
    return isinstance(value, str) and value.startswith(V2_PREFIX)


def _open(value: str, bind_: Binding | None, allow_legacy: bool | None) -> bytes:
    if value.startswith(V2_PREFIX):
        if bind_ is None:
            _report("binding_mismatch", None, "unbound_read", "v2")
            raise BindingMismatch("v2 ciphertext read without a binding")
        kid, sep, body = value[len(V2_PREFIX):].partition(":")
        cipher = _cipher_for(kid)
        if not sep or cipher is None:
            _report("binding_mismatch", bind_, "unknown_kid" if sep else "malformed", "v2")
            raise BindingMismatch("v2 ciphertext with a malformed envelope or unknown key id")
        try:
            raw = base64.b64decode(body, validate=True)
            return cipher.decrypt(raw[:_NONCE_BYTES], raw[_NONCE_BYTES:], bind_.aad())
        except (InvalidTag, ValueError):
            _report("binding_mismatch", bind_, "auth_failed", "v2")
            raise BindingMismatch(
                f"v2 ciphertext does not open in {bind_.table}.{bind_.column}"
            ) from None
    if bind_ is not None:
        allowed = legacy_reads_allowed(bind_.table) if allow_legacy is None else allow_legacy
        if not allowed:
            _report("legacy_refused", bind_, "legacy_value", "v1")
            raise LegacyRefused(f"legacy value refused in {bind_.table}.{bind_.column}")
    raw = base64.b64decode(value)
    return _AESGCM.decrypt(raw[:_NONCE_BYTES], raw[_NONCE_BYTES:], None)


# ── Public helpers ──────────────────────────────────────────────────────────


def encrypt(value: str, *, bind: Binding | None = None, v2: bool | None = None) -> str:
    """Seal a string: v2 under ``bind`` when v2 writes are on (or ``v2=True``)."""
    return _seal(value.encode("utf-8"), bind, v2)


def decrypt(value: str, *, bind: Binding | None = None, allow_legacy: bool | None = None) -> str:
    """Open a v1 or v2 value; raises on anything else (see module docstring).

    ``allow_legacy`` overrides the legacy-read setting for this one call (the
    key canary, which is a key check rather than data)."""
    return _open(value, bind, allow_legacy).decode("utf-8")


def encrypt_bytes(value: bytes, *, bind: Binding | None = None, v2: bool | None = None) -> str:
    """Raw bytes -> the envelope. For binary payloads (a staged upload's file,
    #116) that `encrypt` would have to base64 twice."""
    return _seal(bytes(value), bind, v2)


def decrypt_bytes(value: str, *, bind: Binding | None = None) -> bytes:
    """Inverse of `encrypt_bytes`. Strict: raises on a wrong key or tampering
    (there is no legacy plaintext to fall back to)."""
    return _open(value, bind, None)


def encrypt_if_present(value: Any, *, bind: Binding | None = None) -> str | None:
    if value is None:
        return None
    return encrypt(str(value), bind=bind)


def _refuse_non_string(value: Any, bind_: Binding | None) -> bool:
    """A non-string where ciphertext belongs is legacy data: refused once a
    bound read no longer accepts legacy values."""
    if bind_ is not None and not legacy_reads_allowed(bind_.table):
        _report("legacy_refused", bind_, "non_string", "v1")
        return True
    return False


def decrypt_if_present(value: Any, *, bind: Binding | None = None) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        return None if _refuse_non_string(value, bind) else value
    try:
        return decrypt(value, bind=bind)
    except EncryptionError:
        return None
    except Exception as e:
        logger.warning("decrypt_if_present fallback to raw value: %s", e)
        return value


def decrypt_numeric(value: Any, *, bind: Binding | None = None) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return None if _refuse_non_string(value, bind) else float(value)
    try:
        return float(decrypt(value, bind=bind))
    except EncryptionError:
        return None
    except Exception as e:
        logger.warning("decrypt_numeric fallback: %s", e)
        try:
            return float(value)
        except (TypeError, ValueError):
            return None


def encrypt_json(value: dict | list, *, bind: Binding | None = None) -> str:
    return encrypt(json.dumps(value, separators=(",", ":")), bind=bind)


def decrypt_json(value: str, *, bind: Binding | None = None) -> dict | list:
    """Open a JSON value. Raises :class:`EncryptionError` on a refused value
    (never falls back to it), and the original error when neither the
    ciphertext nor a legacy plaintext parse works."""
    try:
        return json.loads(decrypt(value, bind=bind))
    except EncryptionError:
        raise
    except Exception as e:
        logger.warning("decrypt_json fallback to plaintext: %s", e)
        try:
            return json.loads(value)
        except Exception:
            raise e


def decrypt_json_column(value: Any, *, bind: Binding | None = None) -> Any:
    """Read-boundary guard for JSON columns that may hold either legacy
    plaintext JSONB (arrives as dict/list) or ciphertext (str). #521/#518.
    A refused value reads as None."""
    if value is None:
        return None
    if isinstance(value, (dict, list)):
        return None if _refuse_non_string(value, bind) else value
    try:
        return decrypt_json(value, bind=bind)
    except EncryptionError:
        return None

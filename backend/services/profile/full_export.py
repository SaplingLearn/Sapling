"""The student's own full data export, streamed (POST /api/profile/{id}/export).

What a student downloads from Settings → "Export your data": everything
Sapling stores about them, decrypted, as ONE JSON document. The legacy keys
(`user`, `settings`, `roles`, `achievements`, `cosmetics`,
`services/profile/account.py`) come first, unchanged, then:

- ``tables``: the account's academic and study rows, one key per table —
  the tables the admin cross-environment bundle moves
  (`services/account_bundle.py::SPECS`: graph + mastery events, documents
  (with their decrypted extracted text, summary and concept notes),
  enrollments, gradebook + calendar assignments, topic checklists, notes,
  flashcards, tutor sessions + messages, study guides, quiz attempts /
  responses / context, XP, achievements) plus the student's OWN room
  messages and memberships, their Gradescope course links (no credentials),
  and the feedback and issue reports they submitted;
- ``courses``: the course/offering names the rows refer to, so the export
  is readable without the catalog;
- ``not_included``: what is deliberately left out, and why.

Scoping. Every table is read by the requesting user's id (a ``user_id``
filter) or, for child tables, by ids of parent rows already read that way
(messages by the student's sessions, assignments by their enrollments, …).
Room messages are filtered to ``user_id = <the student>``: a classmate's
message is never exported, even in a room they share. Rows of shared tables
(`course_chunks`) are not exported at all; the documents carry the text.

Secrets. OAuth tokens (`oauth_tokens`) and Gradescope credentials
(`gradescope_credentials`) are never read, and every row has any column
whose NAME looks like a secret (token, secret, password, credential, cookie,
api key) removed as a second line, so a credential column added to an
exported table later does not ship.

Decryption. Unlike the admin bundle (which must refuse to move an
undecryptable value between environments), the student's own export is
lenient: any string that decrypts under this environment's key is shown
decrypted — AES-GCM authenticates, so a successful decrypt is proof it was
our ciphertext, including in a column nobody added to
`account_bundle.ENCRYPTED` yet — and JSON columns are parsed. A value that
looks like ciphertext but does not decrypt is replaced by ``UNREADABLE``
rather than failing the whole export.

Bounded. The body is generated table by table and page by page (offset
paging over a total order, ``_PAGE`` rows a read; a short page is the only
proof of the end, as in `db.connection.page_all`), so the server holds one
page of rows at a time however large the account is. A failure mid-stream
leaves the JSON unterminated, so the client's parse fails loudly instead of
saving a silently partial export.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterator

from db.connection import table
from services import account_bundle, encryption

logger = logging.getLogger(__name__)

EXPORT_FORMAT = 2
UNREADABLE = "[unreadable: does not decrypt under this server's key]"

_PAGE = 500
_IN_CHUNK = 50

_SECRET_COLUMN = re.compile(
    r"token|secret|passw(or)?d|credential|cookie|api[_-]?key|private[_-]?key", re.IGNORECASE,
)

# Tables never read for the export, and why (served in `not_included` too).
NOT_INCLUDED: dict[str, str] = {
    "oauth_tokens": "Google OAuth tokens are credentials, not your data.",
    "gradescope_credentials": "Gradescope credentials are secrets.",
    "course_chunks": "Search index rows; shared ones mix classmates' material. "
                     "Your documents' text is included under documents.",
    "room_messages (others)": "Only messages you wrote are included.",
    "room_summaries": "AI summaries of a room's conversation include classmates' messages.",
    "friendships / friend_requests": "These name other students.",
    "events / llm_usage": "Operational telemetry (page events, AI token counts). "
                          "Ask the Sapling team if you want a copy.",
    "document_uploads / tutor_pending_sessions": "Short-lived processing state.",
}


@dataclass(frozen=True)
class Section:
    """One exported table: how the student's rows in it are found."""

    name: str
    key: str = "user_id"
    parent: str | None = None
    order: str = "id"


SECTIONS: tuple[Section, ...] = tuple(
    Section(s.name, s.key, s.parent, s.order) for s in account_bundle.SPECS
) + (
    Section("room_messages", order="created_at,id"),
    Section("room_members", order="room_id"),
    Section("gradescope_course_links"),
    Section("feedback"),
    Section("issue_reports"),
)

# Encrypted columns whose plaintext is JSON (encrypt_json), from the bundle's
# map. An unlisted ciphertext is parsed when its plaintext looks like JSON.
_JSON_COLUMNS: dict[str, set[str]] = {
    name: {c for c, kind in cols.items() if kind == account_bundle.JSON}
    for name, cols in account_bundle.ENCRYPTED.items()
}


def _plain_value(table_name: str, column: str, value: Any) -> Any:
    """Decrypt `value` when it is our ciphertext; parse JSON columns."""
    if not isinstance(value, str) or not account_bundle._looks_like_ciphertext(value):  # noqa: SLF001
        return _parse_json(table_name, column, value)
    try:
        text = encryption.decrypt(value)
    except Exception:
        listed = column in account_bundle.ENCRYPTED.get(table_name, {})
        if listed:
            logger.warning("self export: %s.%s does not decrypt", table_name, column)
            return UNREADABLE
        return value  # base64-shaped plaintext in a plaintext column (an id, a hash)
    return _parse_json(table_name, column, text, decrypted=True)


def _parse_json(table_name: str, column: str, value: Any, *, decrypted: bool = False) -> Any:
    if not isinstance(value, str):
        return value
    is_json_col = column in _JSON_COLUMNS.get(table_name, set())
    if is_json_col or (decrypted and value[:1] in ("{", "[")):
        try:
            return json.loads(value)
        except ValueError:
            return value
    return value


def plain_row(table_name: str, row: dict) -> dict:
    """`row` decrypted, with secret-named columns removed."""
    return {
        column: _plain_value(table_name, column, value)
        for column, value in row.items()
        if not _SECRET_COLUMN.search(column)
    }


def _read(name: str, filters: dict, order: str) -> Iterator[dict]:
    """Every row of `name` matching `filters`, one page at a time."""
    offset = 0
    while True:
        rows = table(name).select(
            "*", filters=filters, order=order, limit=_PAGE, offset=offset,
        ) or []
        yield from rows
        if len(rows) < _PAGE:
            return
        offset += _PAGE


def _rows(section: Section, user_id: str, ids: dict[str, list[str]]) -> Iterator[dict]:
    if section.parent is None:
        yield from _read(section.name, {section.key: f"eq.{user_id}"}, section.order)
        return
    parent_ids = ids.get(section.parent, [])
    for i in range(0, len(parent_ids), _IN_CHUNK):
        chunk = parent_ids[i:i + _IN_CHUNK]
        yield from _read(section.name, {section.key: f"in.({','.join(chunk)})"}, section.order)


def _courses(offering_ids: set[str], course_ids: set[str]) -> dict:
    """Readable names for the offerings/courses the rows mention (best effort)."""
    def select_in(name: str, ids: set[str], cols: str) -> list[dict]:
        out: list[dict] = []
        ordered = sorted(i for i in ids if i)
        for i in range(0, len(ordered), _IN_CHUNK):
            chunk = ordered[i:i + _IN_CHUNK]
            out.extend(table(name).select(cols, filters={"id": f"in.({','.join(chunk)})"}) or [])
        return out

    offerings = select_in("course_offerings", offering_ids, "id,course_id,term_id,section")
    course_ids = set(course_ids) | {o.get("course_id") for o in offerings if o.get("course_id")}
    courses = select_in("courses", course_ids, "id,course_code,course_name")
    return {
        "offerings": {
            o["id"]: {"course_id": o.get("course_id"), "term_id": o.get("term_id"),
                      "section": o.get("section")}
            for o in offerings if o.get("id")
        },
        "courses": {
            c["id"]: {"course_code": c.get("course_code"), "course_name": c.get("course_name")}
            for c in courses if c.get("id")
        },
    }


def _dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


def stream_export(user_id: str, head: dict) -> Iterator[str]:
    """The export document, as chunks of JSON text.

    `head` is `export_account_data(user_id)` (the legacy keys), computed by
    the caller BEFORE the response starts, so a missing account is still a
    clean 404 rather than a broken stream.
    """
    yield "{"
    for key, value in head.items():
        yield f"{_dump(key)}:{_dump(value)},"
    yield f'"export_format":{EXPORT_FORMAT},'
    yield f'"exported_at":{_dump(datetime.now(timezone.utc).isoformat())},'
    yield '"tables":{'

    parents = {s.parent for s in SECTIONS if s.parent}
    ids: dict[str, list[str]] = {}
    offering_ids: set[str] = set()
    course_ids: set[str] = set()
    try:
        for n, section in enumerate(SECTIONS):
            yield ("," if n else "") + f"{_dump(section.name)}:["
            first = True
            keep: list[str] = []
            for row in _rows(section, user_id, ids):
                if section.parent is None and row.get(section.key) not in (None, user_id):
                    # Defence in depth: never trust the filter alone.
                    continue
                if section.name in parents and row.get("id"):
                    keep.append(str(row["id"]))
                if row.get("offering_id"):
                    offering_ids.add(row["offering_id"])
                if row.get("course_id"):
                    course_ids.add(row["course_id"])
                yield ("" if first else ",") + _dump(plain_row(section.name, row))
                first = False
            if section.name in parents:
                ids[section.name] = keep
            yield "]"
        yield "},"
        yield f'"courses":{_dump(_courses(offering_ids, course_ids))},'
        yield f'"not_included":{_dump(NOT_INCLUDED)}'
        yield "}"
    except Exception:
        # The response has started; the only honest signal left is an
        # unterminated document. Log without row content.
        logger.exception("self export failed mid-stream for %s", user_id)
        raise

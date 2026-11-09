"""Export one account's data as a plaintext bundle, and import it elsewhere.

The cross-environment copy (admin account tools, spec
docs/superpowers/specs/2026-11-08-admin-account-tools-design.md) moves an
account's academic/study data between staging and prod. The two projects
differ in exactly the ways that make a row-for-row copy wrong:

- **Different ENCRYPTION_KEYs.** Every 🔒 column is decrypted STRICTLY on the
  source and re-encrypted on the target. "Strict" is the point: the read
  helpers in `services/encryption.py` fail SOFT (a wrong-key ciphertext comes
  back unchanged), and a soft failure here would ship ciphertext labelled as
  plaintext, which the target would then encrypt a second time — unreadable
  forever under either key. `_decrypt_text`/`_decrypt_json` raise instead.
- **Different catalog UUIDs.** Rows keep their source `offering_id` /
  `course_id`, and the bundle carries a `catalog` section mapping each of those
  ids to its natural key: offerings by `(course_code, term_id, section)`,
  courses by `course_code` (+ the school slug as a tie-break). Import resolves
  them on the target by the EXACT triple (creating that offering when it is
  missing, never a course or a term). Achievements move by `slug` — and so do
  the `achievement_unlocked` XP rows that name them. Term ids are stable
  strings (`fall-2026`).
- **No chunks.** `course_chunks` never moves: documents import as
  `index_status='pending'` so the target re-indexes them under its own key and
  its own visibility rules (`shareability` travels, so the decision does too).

Rows are exported with `select=*` rather than a column allowlist, so a new
plaintext column travels without a code change. The risk of that is a NEW 🔒
column nobody added to `ENCRYPTED` — it would ship as ciphertext. Every
exported string is therefore swept: one that decrypts under this environment's
key but sits in an unlisted column fails the export (`_assert_no_unlisted_ciphertext`).
The mirror risk on import — a column the source has and the target's schema
does not (staging is usually migrations ahead of prod) — is caught by a
per-table probe BEFORE the wipe, so a schema mismatch never leaves the target
account emptied.

Import is not atomic (PostgREST has no transactions): everything that can be
checked or computed is done before `wipe_account_data`, and a failure after it
converges on re-run, because every import starts with that wipe. Row ids are
preserved — the target's copies of them were just wiped.

Never copied: OAuth tokens, roles, social (rooms/friendships), telemetry
(events/llm_usage), feedback/issue reports, gradescope links (credentials do not
move), cosmetics (`equipped_*`/`featured_*` ids), `avatar_url` (storage buckets
differ), `course_chunks`, in-flight staging (`document_uploads`, `gradescope_syncs`,
`tutor_pending_sessions`: wiped, never bundled), and every privacy/consent/notification choice in
`user_settings` (see `_SETTINGS_COPIED`): consent is the person's, given on
each environment, and is never carried from one to the other. The imported
documents therefore index under the TARGET's stored `share_class_context`.
`users.total_xp`/`level` are not copied either: they are recomputed from the
imported XP ledger, which is what `xp_service` treats them as (a cache of it).
"""

from __future__ import annotations

import base64
import binascii
import json
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable, Iterator

import httpx

import config
from db.connection import page_all, pg_quote_value, table
from services import encryption
from services.analytics_consent import clear_analytics_consent_cache
from services.growth import level_for_xp
from services.xp_service import idempotency_key as xp_idempotency_key

logger = logging.getLogger(__name__)

BUNDLE_VERSION = 1


class BundleError(ValueError):
    """The bundle cannot be produced or applied as asked (routes → 400).

    Messages name tables, columns, row ids and catalog codes — never a value
    from an encrypted column."""


class AccountNotFound(LookupError):
    """No live `users` row for this id in THIS environment (routes → 404)."""

    def __init__(self, user_id: str):
        super().__init__(f"account {user_id} does not exist in {config.APP_ENV}")
        self.user_id = user_id


# ── Encrypted-column map ─────────────────────────────────────────────────────
#
# Kept in step with CLAUDE.md's encrypted-columns list (Gotchas). TEXT columns
# are written with `encrypt_if_present` (assignments' points are numbers kept
# as their string form); JSON columns with `encrypt_json`.

TEXT = "text"
JSON = "json"

ENCRYPTED: dict[str, dict[str, str]] = {
    "user_profiles": {
        "name": TEXT, "first_name": TEXT, "last_name": TEXT, "bio": TEXT, "location": TEXT,
    },
    "assignments": {"notes": TEXT, "points_possible": TEXT, "points_earned": TEXT},
    "topic_checklists": {"content": JSON},
    "documents": {"summary": TEXT, "concept_notes": JSON, "extracted_text": TEXT},
    "notes": {"title": TEXT, "body": TEXT, "last_summary": TEXT},
    "flashcards": {"front": TEXT, "back": TEXT},
    "sessions": {"summary_json": JSON},
    "messages": {"content": TEXT},
    "study_guides": {"content": JSON},
    "quiz_attempts": {"questions_json": JSON, "answers_json": JSON},
    "quiz_responses": {"answer_text": JSON},
    "quiz_context": {"context_json": JSON},
}

# base64(nonce || ciphertext || tag): 12-byte nonce + 16-byte GCM tag at least.
_MIN_CIPHERTEXT_BYTES = 12 + 16


def _looks_like_ciphertext(value: str) -> bool:
    try:
        raw = base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError):
        return False
    return len(raw) >= _MIN_CIPHERTEXT_BYTES


def _strict_decrypt(value: str, where: str) -> str:
    """Decrypt under THIS environment's key, or raise. Never returns its input."""
    try:
        return encryption.decrypt(value)
    except Exception as exc:  # InvalidTag, bad padding, bad utf-8
        raise BundleError(
            f"{where}: ciphertext does not decrypt under this environment's "
            "ENCRYPTION_KEY; refusing to export it"
        ) from exc


def _decrypt_text(value: Any, where: str) -> Any:
    """Strict read of a TEXT 🔒 column.

    A value that has the SHAPE of ciphertext must decrypt, or the export
    fails. A value that cannot be ciphertext (not base64, or too short) is a
    legacy plaintext row the encryption backfill never reached: it travels as
    the plaintext it is, and the target encrypts it. The one consequence of the
    shape test is fail-closed: a legacy plaintext that happens to be valid
    base64 of 28+ bytes is refused rather than guessed at.
    """
    if value is None or not isinstance(value, str):
        return value
    if not _looks_like_ciphertext(value):
        logger.warning("account bundle: legacy plaintext in %s", where)
        return value
    return _strict_decrypt(value, where)


def _decrypt_json(value: Any, where: str) -> Any:
    """Strict read of a JSON 🔒 column (`encrypt_json` on write).

    A dict/list is a legacy plaintext JSONB row (the same case
    `decrypt_json_column` lets through). A string is ciphertext — decrypted
    strictly — or legacy JSON text, which must parse.
    """
    if value is None or not isinstance(value, str):
        return value
    if _looks_like_ciphertext(value):
        text = _strict_decrypt(value, where)
    else:
        logger.warning("account bundle: legacy plaintext JSON in %s", where)
        text = value
    try:
        return json.loads(text)
    except ValueError as exc:
        raise BundleError(f"{where}: encrypted JSON column does not hold JSON") from exc


def _encrypt(kind: str, value: Any) -> Any:
    if value is None:
        return None
    if kind == JSON:
        return encryption.encrypt_json(value)
    return encryption.encrypt_if_present(value)


def _assert_no_unlisted_ciphertext(table_name: str, row: dict, listed: Iterable[str]) -> None:
    """Refuse a string that decrypts under our key in a column not in ENCRYPTED.

    AES-GCM authenticates, so a successful decrypt is proof the value is our
    ciphertext — this has no false positives. It is what keeps `select=*` safe
    when a new 🔒 column lands without an `ENCRYPTED` entry.
    """
    skip = set(listed)
    for column, value in row.items():
        if column in skip or not isinstance(value, str) or not _looks_like_ciphertext(value):
            continue
        try:
            encryption.decrypt(value)
        except Exception:
            continue
        raise BundleError(
            f"{table_name}.{column} holds ciphertext but is not in account_bundle.ENCRYPTED; "
            "add it there before copying accounts"
        )


# ── What moves ───────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class _Spec:
    """One user-scoped table: how to find the account's rows in it.

    `key` is the column filtered on; with `parent` set, its values are the
    ids already exported for that parent table (e.g. messages by session_id).
    Specs are listed in INSERT order (parents first).
    """

    name: str
    key: str = "user_id"
    parent: str | None = None
    order: str = "id"


SPECS: tuple[_Spec, ...] = (
    _Spec("graph_nodes"),
    _Spec("graph_edges"),
    _Spec("node_mastery_events", key="node_id", parent="graph_nodes"),
    # Before enrollments: enrollments.syllabus_doc_id references documents.
    _Spec("documents"),
    _Spec("enrollments"),
    _Spec("gradebook_categories", key="enrollment_id", parent="enrollments"),
    _Spec("assignments", key="enrollment_id", parent="enrollments"),
    _Spec("topic_checklists", key="enrollment_id", parent="enrollments", order="enrollment_id"),
    _Spec("topic_checklist_progress", key="enrollment_id", parent="enrollments",
          order="enrollment_id,topic_key"),
    _Spec("notes"),
    _Spec("note_concepts", key="note_id", parent="notes", order="note_id,concept_node_id"),
    _Spec("flashcards"),
    _Spec("sessions"),
    _Spec("messages", key="session_id", parent="sessions"),
    _Spec("study_guides"),
    _Spec("quiz_attempts"),
    _Spec("quiz_responses", key="attempt_id", parent="quiz_attempts"),
    _Spec("quiz_context"),
    _Spec("xp_events"),
    _Spec("user_achievements", order="achievement_id"),
)

# Tables whose rows carry an `offering_id` to remap.
_OFFERING_TABLES = ("documents", "enrollments", "notes", "flashcards", "sessions", "study_guides")

USER_COUNTERS = (
    "total_xp", "level", "streak_count", "longest_streak", "onboarding_completed",
    # Not in the spec's list, but the streak is meaningless without it: the
    # next activity compares against the last active day to extend or reset.
    "last_active_date", "daily_goal_xp",
)

# Recomputed on import from the imported xp_events ledger, never copied.
_DERIVED_COUNTERS = ("total_xp", "level")

# Never copied off the profile row.
_PROFILE_DROP = {"user_id", "avatar_url", "created_at", "updated_at"}

# The ONLY user_settings columns that move: display preferences. An allowlist,
# not a drop list, so a consent column added later stays put by default.
# Everything else stays the TARGET's own:
#   - consent/privacy: share_class_context (class-pool RAG sharing, #629),
#     analytics_opt_out (PostHog, #677), profile_visibility,
#     activity_status_visible;
#   - notification preferences: notification_email, notification_push,
#     notification_in_app;
#   - cosmetics: equipped_*_id, featured_role_id, featured_achievement_ids
#     (catalog UUIDs differ per environment);
#   - bookkeeping: user_id, created_at, updated_at.
_SETTINGS_COPIED = ("theme", "font_size", "accent_color")

# xp_events rows that pay out an achievement name it by catalog UUID (in
# source_id AND inside idempotency_key), so they are remapped by slug.
_ACH_XP_RULE = "achievement_unlocked"
_ACH_XP_SOURCE = "achievement"

# Documents re-index on the target; none of the source's indexing state applies.
_DOCUMENT_INDEX_RESET = {
    "index_attempts": 0, "index_leased_at": None, "index_chunk_count": None, "index_error": None,
}

_IN_CHUNK = 50  # ids per `in.(…)` filter — keeps the query string bounded
_INSERT_CHUNK = 200


def _chunks(items: list, size: int) -> Iterator[list]:
    for i in range(0, len(items), size):
        yield items[i:i + size]


def _in(ids: Iterable[str]) -> str:
    return f"in.({','.join(ids)})"


def _select_in(name: str, column: str, ids: Iterable[str], columns: str = "*") -> list[dict]:
    """Every row of `name` whose `column` is in `ids` (chunked; small tables)."""
    unique = sorted({i for i in ids if i})
    rows: list[dict] = []
    for chunk in _chunks(unique, _IN_CHUNK):
        rows.extend(table(name).select(columns, filters={column: _in(chunk)}) or [])
    return rows


def _user_row(user_id: str) -> dict:
    rows = table("users").select(
        ",".join(("id", *USER_COUNTERS)),
        filters={"id": f"eq.{user_id}", "deleted_at": "is.null"},
        limit=1,
    ) or []
    if not rows:
        raise AccountNotFound(user_id)
    return rows[0]


def account_exists(user_id: str) -> bool:
    """Whether a live (not soft-deleted) account with this id exists here."""
    try:
        _user_row(user_id)
    except AccountNotFound:
        return False
    return True


# ── Export ───────────────────────────────────────────────────────────────────


def _export_rows(spec: _Spec, user_id: str, exported: dict[str, list[dict]]) -> list[dict]:
    if spec.parent is None:
        handle = table(spec.name)
        return list(page_all(handle, filters={spec.key: f"eq.{user_id}"}, order=spec.order))
    parent_ids = sorted({r["id"] for r in exported.get(spec.parent, []) if r.get("id")})
    rows: list[dict] = []
    for chunk in _chunks(parent_ids, _IN_CHUNK):
        handle = table(spec.name)
        rows.extend(page_all(handle, filters={spec.key: _in(chunk)}, order=spec.order))
    return rows


def _is_achievement_xp(row: Any) -> bool:
    return (isinstance(row, dict) and row.get("rule_key") == _ACH_XP_RULE
            and row.get("source_type") == _ACH_XP_SOURCE)


def _plain(table_name: str, row: dict) -> dict:
    """`row` with every 🔒 column strictly decrypted (and swept for strays)."""
    cols = ENCRYPTED.get(table_name, {})
    _assert_no_unlisted_ciphertext(table_name, row, cols)
    out = dict(row)
    rid = row.get("id") or row.get("enrollment_id") or row.get("user_id") or "?"
    for column, kind in cols.items():
        if column in out:
            where = f"{table_name}.{column} (row {rid})"
            out[column] = (_decrypt_json if kind == JSON else _decrypt_text)(out[column], where)
    return out


def _export_catalog(exported: dict[str, list[dict]]) -> dict:
    offering_ids = {
        r.get("offering_id") for t in _OFFERING_TABLES for r in exported.get(t, [])
    } - {None}
    offerings = _select_in(
        "course_offerings", "id", offering_ids,
        "id,course_id,term_id,section,instructor_name,meeting_times,location",
    )
    missing = offering_ids - {o["id"] for o in offerings}
    if missing:
        raise BundleError(f"offerings referenced but not found: {sorted(missing)}")

    course_ids = {o["course_id"] for o in offerings} | (
        {r.get("course_id") for r in exported.get("graph_nodes", [])} - {None}
    )
    courses = _select_in("courses", "id", course_ids, "id,course_code,course_name,school_id")
    missing = course_ids - {c["id"] for c in courses}
    if missing:
        raise BundleError(f"courses referenced but not found: {sorted(missing)}")
    schools = {
        s["id"]: s.get("slug")
        for s in _select_in("schools", "id", {c.get("school_id") for c in courses}, "id,slug")
    }

    return {
        "courses": {
            c["id"]: {
                "course_code": c["course_code"],
                "course_name": c.get("course_name"),
                "school_slug": schools.get(c.get("school_id")),
            }
            for c in courses
        },
        "offerings": {
            o["id"]: {
                "course": o["course_id"],
                "term_id": o["term_id"],
                "section": o.get("section") or "",
                "instructor_name": o.get("instructor_name"),
                "meeting_times": o.get("meeting_times"),
                "location": o.get("location"),
            }
            for o in offerings
        },
    }


def export_account(user_id: str) -> dict:
    """The account's data as one plaintext, JSON-serialisable bundle.

    Raises `AccountNotFound` when the account does not exist here, and
    `BundleError` when a value cannot be exported honestly (a ciphertext that
    does not decrypt under this environment's key, an unlisted 🔒 column, a
    dangling catalog reference).
    """
    counters = _user_row(user_id)

    exported: dict[str, list[dict]] = {}
    for spec in SPECS:
        exported[spec.name] = _export_rows(spec, user_id, exported)

    catalog = _export_catalog(exported)

    # Achievements travel by slug: the catalog's UUIDs differ per project.
    # The XP rows that paid them out name them too, so their ids join the map.
    ach_ids = ({r["achievement_id"] for r in exported["user_achievements"]} | {
        r.get("source_id") for r in exported["xp_events"] if _is_achievement_xp(r)
    }) - {None}
    slugs = {a["id"]: a["slug"] for a in _select_in("achievements", "id", ach_ids, "id,slug")}
    catalog["achievements"] = dict(sorted(slugs.items()))
    achievements = []
    for r in exported["user_achievements"]:
        slug = slugs.get(r["achievement_id"])
        if slug:
            achievements.append({
                "achievement_slug": slug,
                "earned_at": r.get("earned_at"),
                "is_featured": r.get("is_featured"),
            })
    exported["user_achievements"] = achievements

    tables = {name: [_plain(name, row) for row in rows] for name, rows in exported.items()}

    profile_rows = table("user_profiles").select(
        "*", filters={"user_id": f"eq.{user_id}"}, limit=1,
    ) or []
    profile = (
        {k: v for k, v in _plain("user_profiles", profile_rows[0]).items() if k not in _PROFILE_DROP}
        if profile_rows else None
    )
    settings_rows = table("user_settings").select(
        "*", filters={"user_id": f"eq.{user_id}"}, limit=1,
    ) or []
    settings = (
        {k: v for k, v in _plain("user_settings", settings_rows[0]).items() if k in _SETTINGS_COPIED}
        if settings_rows else None
    )

    return {
        "version": BUNDLE_VERSION,
        "source_env": config.APP_ENV,
        "user_id": user_id,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "user": {k: counters.get(k) for k in USER_COUNTERS},
        "profile": profile,
        "settings": settings,
        "catalog": catalog,
        "tables": tables,
    }


# ── Import ───────────────────────────────────────────────────────────────────


def _validate(user_id: str, bundle: Any) -> None:
    if not isinstance(bundle, dict):
        raise BundleError("bundle is not a JSON object")
    if bundle.get("version") != BUNDLE_VERSION:
        raise BundleError(
            f"bundle version {bundle.get('version')!r:.20} is not {BUNDLE_VERSION}; "
            "deploy the same backend on both environments"
        )
    if bundle.get("user_id") != user_id:
        raise BundleError("bundle belongs to a different account")
    tables = bundle.get("tables")
    if not isinstance(tables, dict) or not all(isinstance(v, list) for v in tables.values()):
        raise BundleError("bundle has no tables object")
    unknown = set(tables) - {s.name for s in SPECS}
    if unknown:
        raise BundleError(f"bundle carries tables this backend does not import: {sorted(unknown)}")
    catalog = bundle.get("catalog")
    if not isinstance(catalog, dict) or not isinstance(catalog.get("courses"), dict) \
            or not isinstance(catalog.get("offerings"), dict):
        raise BundleError("bundle has no catalog object")
    achievements = catalog.get("achievements")
    if achievements is not None and (
        not isinstance(achievements, dict)
        or not all(isinstance(v, str) for v in achievements.values())
    ):
        raise BundleError("bundle catalog achievements is not an id → slug object")
    for key in ("user", "profile", "settings"):
        if bundle.get(key) is not None and not isinstance(bundle[key], dict):
            raise BundleError(f"bundle {key} is not an object")


def _resolve_courses(catalog: dict) -> dict[str, str]:
    """source course id → target course id, by course_code (school slug breaks ties)."""
    refs: dict[str, dict] = catalog["courses"]
    codes = sorted({r["course_code"] for r in refs.values()})
    found: dict[str, list[dict]] = {}
    for chunk in _chunks(codes, _IN_CHUNK):
        # Codes contain spaces ("CAS CS 111"): quote each for the in.() list.
        quoted = ",".join(pg_quote_value(c) for c in chunk)
        for row in table("courses").select(
            "id,course_code,school_id", filters={"course_code": f"in.({quoted})"},
        ) or []:
            found.setdefault(row["course_code"], []).append(row)
    school_ids = {r.get("school_id") for rows in found.values() for r in rows} - {None}
    slug_of = {s["id"]: s.get("slug") for s in _select_in("schools", "id", school_ids, "id,slug")}

    out: dict[str, str] = {}
    missing = []
    for src_id, ref in refs.items():
        candidates = found.get(ref["course_code"], [])
        if not candidates:
            missing.append(ref["course_code"])
            continue
        same_school = [c for c in candidates if slug_of.get(c.get("school_id")) == ref.get("school_slug")]
        out[src_id] = sorted(same_school or candidates, key=lambda c: c["id"])[0]["id"]
    if missing:
        raise BundleError(
            f"courses missing from {config.APP_ENV}'s catalog: {sorted(set(missing))}"
        )
    return out


def _offering_key(ref: dict, course_map: dict[str, str], src_id: str) -> tuple[str, str, str]:
    """The exact target (course_id, term_id, section) a source offering maps to."""
    course_id = course_map.get(ref.get("course"))
    if not course_id:
        raise BundleError(f"offering {src_id} names a course the bundle does not describe")
    # NOT NULL DEFAULT '' (0033): "no section" is the empty string, never NULL.
    return course_id, ref["term_id"], ref.get("section") or ""


def _check_enrollment_collisions(
    catalog: dict, course_map: dict[str, str], enrollments: list,
) -> None:
    """Refuse (before anything is created or wiped) a bundle whose enrollments
    would land on the same target offering.

    Resolution is exact, so the target offering is a function of the
    (course, term, section) triple: two enrollments sharing a triple — two
    source courses with one course_code that the target holds once, say —
    would collapse into one enrollment (and the second insert would fail
    after the wipe)."""
    refs: dict[str, dict] = catalog["offerings"]
    seen: dict[tuple[str, str, str], str] = {}
    for row in enrollments:
        if not isinstance(row, dict) or row.get("offering_id") is None:
            continue
        src = row["offering_id"]
        if src not in refs:
            raise BundleError(f"enrollments: offering {src} is not in the bundle's catalog")
        key = _offering_key(refs[src], course_map, src)
        if key in seen:
            raise BundleError(
                f"enrollments {seen[key]} and {row.get('id')} would map onto one "
                f"{config.APP_ENV} offering ({key[1]}, section {key[2]!r}); refusing the copy"
            )
        seen[key] = row.get("id")


def _exact_offering(key: tuple[str, str, str], ref: dict) -> str | None:
    """The target offering with exactly (course_id, term_id, section), created
    when absent.

    Never `academics.resolve_offering`: it matches (course, term) with ANY
    section, so a sectionless source offering would land on, e.g., section A1
    — and two source enrollments could collapse onto one offering. The insert
    mirrors resolve_offering's (client-side uuid; a lost race against
    `course_offerings_unique` re-selects the winner), with the exact section.
    """
    course_id, term_id, section = key
    filters = {"course_id": f"eq.{course_id}", "term_id": f"eq.{term_id}",
               "section": f"eq.{section}"}

    def _select() -> str | None:
        rows = table("course_offerings").select(
            "id", filters=filters, order="created_at.asc", limit=1,
        ) or []
        return rows[0]["id"] if rows else None

    found = _select()
    if found:
        return found
    new_id = str(uuid.uuid4())
    try:
        table("course_offerings").insert({
            "id": new_id, "course_id": course_id, "term_id": term_id, "section": section,
            "instructor_name": ref.get("instructor_name"),
            "meeting_times": ref.get("meeting_times"),
            "location": ref.get("location"),
        })
    except httpx.HTTPStatusError as exc:
        if exc.response is None or exc.response.status_code != 409:
            raise
        return _select()
    return new_id


def _resolve_offerings(catalog: dict, course_map: dict[str, str]) -> dict[str, str]:
    """source offering id → target offering id, by the exact (course, term, section).

    A missing offering is created (the catalog has the course and the term, the
    section just has never been taught here yet); a missing TERM is an error —
    terms are seeded by migration and their ids are the same everywhere.
    """
    refs: dict[str, dict] = catalog["offerings"]
    term_ids = sorted({r["term_id"] for r in refs.values()})
    have = {t["id"] for t in _select_in("terms", "id", term_ids, "id")}
    if set(term_ids) - have:
        raise BundleError(f"terms missing from {config.APP_ENV}: {sorted(set(term_ids) - have)}")

    out: dict[str, str] = {}
    for src_id, ref in refs.items():
        target = _exact_offering(_offering_key(ref, course_map, src_id), ref)
        if not target:
            raise BundleError(f"could not resolve an offering for {src_id} on {config.APP_ENV}")
        out[src_id] = target
    return out


def _target_row(name: str, row: dict, user_id: str, offering_map: dict, course_map: dict) -> dict:
    """One bundle row → the row to insert here: remapped and re-encrypted."""
    if not isinstance(row, dict):
        raise BundleError(f"{name}: row is not an object")
    out = dict(row)
    if "user_id" in out:
        out["user_id"] = user_id
    if name in _OFFERING_TABLES and out.get("offering_id") is not None:
        src = out["offering_id"]
        if src not in offering_map:
            raise BundleError(f"{name}: offering {src} is not in the bundle's catalog")
        out["offering_id"] = offering_map[src]
    if name == "graph_nodes" and out.get("course_id") is not None:
        src = out["course_id"]
        if src not in course_map:
            raise BundleError(f"graph_nodes: course {src} is not in the bundle's catalog")
        out["course_id"] = course_map[src]
    if name == "documents":
        out.update(_DOCUMENT_INDEX_RESET)
        # A soft-deleted document is never claimed by the sweeper anyway;
        # 'skipped' keeps it out of the admin unindexed list too.
        out["index_status"] = "skipped" if out.get("deleted_at") else "pending"
    for column, kind in ENCRYPTED.get(name, {}).items():
        if column in out:
            out[column] = _encrypt(kind, out[column])
    return out


def _remap_achievement_xp(
    user_id: str, rows: list[dict], slug_of: dict, ach_by_slug: dict[str, str],
) -> tuple[list[dict], int]:
    """(rows with every `achievement_unlocked` row remapped, rows dropped).

    Such a row names the SOURCE achievement UUID in `source_id` and inside
    `idempotency_key`. On the target it must look exactly like the row
    `xp_service.award_xp(user, "achievement_unlocked", source_type="achievement",
    source_id=<target id>)` writes, because `achievement_service._heal_grants`
    finds a badge's payout by (user_id, rule_key, source_type, source_id) and
    re-pays one it cannot find. A row whose achievement the target lacks (or the
    bundle cannot name) is dropped — its badge is dropped too.

    `xp_events.idempotency_key` is UNIQUE across ALL users and the canonical key
    (`achievement_unlocked:achievement:<id>`) has no user in it, so on the
    target it may already belong to another account. Inserting it again would
    fail AFTER the wipe; such a row keeps the canonical shape plus a
    `:<user_id>` suffix instead. `_heal_grants` reads `source_id`, not the
    key, so both shapes satisfy it; checked here, before the wipe.
    """
    out: list[dict] = []
    skipped = 0
    canonical: dict[str, dict] = {}
    for r in rows:
        if not _is_achievement_xp(r):
            out.append(r)
            continue
        src = r.get("source_id")
        aid = ach_by_slug.get(slug_of.get(src)) if isinstance(src, str) else None
        if not aid:
            skipped += 1
            continue
        key = xp_idempotency_key(_ACH_XP_RULE, _ACH_XP_SOURCE, aid)
        if key in canonical:  # two source rows for one badge: keep the first
            skipped += 1
            continue
        row = {**r, "source_id": aid, "idempotency_key": key}
        canonical[key] = row
        out.append(row)

    keys = sorted(canonical)
    for chunk in _chunks(keys, _IN_CHUNK):
        quoted = ",".join(pg_quote_value(k) for k in chunk)
        for held in table("xp_events").select(
            "idempotency_key",
            filters={"idempotency_key": f"in.({quoted})", "user_id": f"neq.{user_id}"},
        ) or []:
            row = canonical.get(held.get("idempotency_key"))
            if row is not None:
                row["idempotency_key"] = f"{row['idempotency_key']}:{user_id}"
    return out, skipped


def _probe_columns(name: str, columns: Iterable[str]) -> None:
    """Fail BEFORE the wipe when this schema lacks a column the bundle carries.

    PostgREST answers 400 for an unknown column in `select=` exactly as it
    would for the insert, so a one-row read proves the insert's shape.
    """
    cols = sorted(set(columns))
    if not cols:
        return
    try:
        table(name).select(",".join(cols), limit=1)
    except httpx.HTTPStatusError as exc:
        detail = (exc.response.text or "")[:300] if exc.response is not None else ""
        raise BundleError(
            f"{config.APP_ENV}'s {name} table cannot take this bundle's columns "
            f"(migrate it first): {detail}"
        ) from exc


def _wipe(user_id: str) -> dict[str, int]:
    # Imported here, not at module level: the wipe pulls in the RAG/visibility
    # stack, which export (and this module's tests) do not need.
    from services.account_wipe import wipe_account_data

    return wipe_account_data(user_id)


def import_account(user_id: str, bundle: dict) -> dict[str, int]:
    """Overwrite this environment's copy of the account with `bundle`.

    Validates, resolves the catalog, re-encrypts every row and probes the
    schema first; only then wipes the account (`wipe_account_data`) and
    inserts in FK order. Returns per-table row counts written.

    Raises `BundleError` (bad/mismatched bundle, catalog this environment
    cannot satisfy, schema mismatch) or `AccountNotFound` (the person never
    signed in here — copy never creates accounts).
    """
    _validate(user_id, bundle)
    _user_row(user_id)

    catalog = bundle["catalog"]
    tables: dict[str, list] = bundle["tables"]
    course_map = _resolve_courses(catalog)
    _check_enrollment_collisions(catalog, course_map, tables.get("enrollments", []))
    offering_map = _resolve_offerings(catalog, course_map)

    # Achievements by slug; one this environment does not have is dropped
    # (counted), not fatal — the rest of the account still moves.
    ach_rows = tables.get("user_achievements", [])
    ach_slug_of: dict = catalog.get("achievements") or {}  # source achievement id → slug
    slugs = sorted(
        ({r.get("achievement_slug") for r in ach_rows if isinstance(r, dict)}
         | {v for v in ach_slug_of.values() if isinstance(v, str)}) - {None}
    )
    ach_by_slug: dict[str, str] = {}
    for chunk in _chunks(slugs, _IN_CHUNK):
        for a in table("achievements").select("id,slug", filters={"slug": _in(chunk)}) or []:
            ach_by_slug[a["slug"]] = a["id"]
    achievements_skipped = 0

    prepared: dict[str, list[dict]] = {}
    for spec in SPECS:
        rows = tables.get(spec.name, [])
        if spec.name == "user_achievements":
            out = []
            for r in rows:
                aid = ach_by_slug.get(r.get("achievement_slug")) if isinstance(r, dict) else None
                if not aid:
                    achievements_skipped += 1
                    continue
                out.append({"user_id": user_id, "achievement_id": aid,
                            "earned_at": r.get("earned_at"), "is_featured": r.get("is_featured")})
            prepared[spec.name] = out
        else:
            prepared[spec.name] = [
                _target_row(spec.name, r, user_id, offering_map, course_map) for r in rows
            ]
    prepared["xp_events"], xp_skipped = _remap_achievement_xp(
        user_id, prepared["xp_events"], ach_slug_of, ach_by_slug,
    )

    user_update = {
        k: v for k, v in (bundle.get("user") or {}).items()
        if k in USER_COUNTERS and k not in _DERIVED_COUNTERS
    }
    # users.total_xp/level are a cache of the ledger (xp_service._ledger_total):
    # derive them from the rows actually imported, so dropped achievement XP
    # is not still counted and the cache agrees with /activity on day one.
    total_xp = sum(int(r.get("amount") or 0) for r in prepared["xp_events"])
    user_update.update(total_xp=total_xp, level=level_for_xp(total_xp))

    profile = None
    if bundle.get("profile"):
        profile = {k: v for k, v in bundle["profile"].items() if k not in _PROFILE_DROP}
        username = profile.get("username")
        if username:
            # UNIQUE(username): keep the target's own username rather than
            # fail the copy over someone else already holding it here.
            taken = table("user_profiles").select(
                "user_id",
                filters={"username": f"eq.{username}", "user_id": f"neq.{user_id}"},
                limit=1,
            ) or []
            if taken:
                profile.pop("username")
        profile = {"user_id": user_id, **_target_row("user_profiles", profile, user_id, {}, {})}
    settings = None
    copied = {k: v for k, v in (bundle.get("settings") or {}).items() if k in _SETTINGS_COPIED}
    if copied:
        # Allowlist on the TARGET side too: whatever the peer sends, the
        # target's consent/privacy/notification columns are never written.
        settings = {"user_id": user_id, **copied}

    # Schema probe: every column about to be written must exist here.
    for name, rows in prepared.items():
        if rows:
            _probe_columns(name, {c for r in rows for c in r})
    if profile:
        _probe_columns("user_profiles", profile)
    if settings:
        _probe_columns("user_settings", settings)
    if user_update:
        _probe_columns("users", user_update)

    # ── Point of no return ──
    _wipe(user_id)

    counts: dict[str, int] = {}
    if user_update:
        table("users").update(user_update, filters={"id": f"eq.{user_id}"})
    counts["users"] = 1
    if profile:
        table("user_profiles").upsert(profile, on_conflict="user_id")
        counts["user_profiles"] = 1
    if settings:
        table("user_settings").upsert(settings, on_conflict="user_id")
        counts["user_settings"] = 1

    for spec in SPECS:
        rows = prepared[spec.name]
        for chunk in _chunks(rows, _INSERT_CHUNK):
            table(spec.name).insert(chunk)
        counts[spec.name] = len(rows)
    if achievements_skipped:
        counts["user_achievements_skipped"] = achievements_skipped
    if xp_skipped:
        counts["xp_events_skipped"] = xp_skipped
    # Not a consent change (consent never moves), but this is a user_settings
    # mutator and CLAUDE.md asks every one of those to drop the cached answer.
    clear_analytics_consent_cache(user_id)
    return counts

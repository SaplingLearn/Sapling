"""services/account_bundle.py — the cross-environment account copy's data half.

Two in-memory "projects" (a source and a target), each with its OWN
ENCRYPTION_KEY and its OWN catalog UUIDs — the two ways staging and prod differ
that make a row-for-row copy wrong. The round trip exports under key A from the
source, imports under key B into the target, and reads the result back under B.
"""
from __future__ import annotations

import base64
import csv
import io
import json
import os
import uuid

import httpx
import pytest
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from services import academics, account_bundle, encryption
from services.account_bundle import AccountNotFound, BundleError

KEY_A = AESGCM(bytes.fromhex("11" * 32))  # source environment
KEY_B = AESGCM(bytes.fromhex("22" * 32))  # target environment
KEY_C = AESGCM(bytes.fromhex("33" * 32))  # some third key (a wrong-key row)

UID = "user_1234567890"


def enc(aes: AESGCM, value) -> str:
    nonce = os.urandom(12)
    return base64.b64encode(nonce + aes.encrypt(nonce, str(value).encode(), None)).decode()


def enc_json(aes: AESGCM, value) -> str:
    return enc(aes, json.dumps(value, separators=(",", ":")))


def dec(aes: AESGCM, value: str) -> str:
    raw = base64.b64decode(value)
    return aes.decrypt(raw[:12], raw[12:], None).decode()


# ── A tiny PostgREST stand-in ───────────────────────────────────────────────


def _parse_in(arg: str) -> set[str]:
    inner = arg[len("in.("):-1]
    return set(next(csv.reader(io.StringIO(inner), quotechar='"', escapechar="\\")))


def _match(row: dict, filters: dict | None) -> bool:
    for col, cond in (filters or {}).items():
        v = row.get(col)
        sv = None if v is None else str(v)
        if cond == "is.null":
            if v is not None:
                return False
        elif cond.startswith("eq."):
            if sv != cond[3:]:
                return False
        elif cond.startswith("neq."):
            if sv == cond[4:]:
                return False
        elif cond.startswith("in.("):
            if sv not in _parse_in(cond):
                return False
        else:
            raise AssertionError(f"fake does not understand filter {col}={cond}")
    return True


class FakeTable:
    def __init__(self, db: "FakeDB", name: str):
        self.db, self.name = db, name

    @property
    def rows(self) -> list[dict]:
        return self.db.data.setdefault(self.name, [])

    def _project(self, row: dict, columns: str) -> dict:
        if columns == "*":
            return dict(row)
        return {c: row.get(c) for c in columns.split(",")}

    def _check_columns(self, columns):
        schema = self.db.schemas.get(self.name)
        if schema is None or columns == "*":
            return
        unknown = set(columns.split(",")) - schema
        if unknown:
            req = httpx.Request("GET", f"http://fake/{self.name}")
            resp = httpx.Response(400, text=f"column {sorted(unknown)} does not exist", request=req)
            raise httpx.HTTPStatusError("400", request=req, response=resp)

    def _sorted(self, rows, order):
        for part in reversed((order or "").split(",")):
            if not part:
                continue
            col, _, direction = part.partition(".")
            rows = sorted(rows, key=lambda r: str(r.get(col) or ""), reverse=direction == "desc")
        return rows

    def select(self, columns="*", filters=None, order=None, limit=None, offset=None, timeout=None):
        self._check_columns(columns)
        rows = self._sorted([r for r in self.rows if _match(r, filters)], order)
        rows = rows[offset or 0:]
        if limit:
            rows = rows[:limit]
        return [self._project(r, columns) for r in rows]

    def select_with_count(self, columns="*", filters=None, order=None, limit=None, offset=None,
                          timeout=None):
        total = len([r for r in self.rows if _match(r, filters)])
        return self.select(columns, filters, order, limit, offset), total

    def insert(self, data):
        self.db.writes.append(("insert", self.name))
        out = []
        for row in data if isinstance(data, list) else [data]:
            row = dict(row)
            if self.name in self.db.id_tables and not row.get("id"):
                row["id"] = str(uuid.uuid4())
            self.rows.append(row)
            out.append(dict(row))
        return out

    def update(self, data, filters, *, prefer_return_minimal=False):
        self.db.writes.append(("update", self.name))
        hit = [r for r in self.rows if _match(r, filters)]
        for r in hit:
            r.update(data)
        return [dict(r) for r in hit]

    def upsert(self, data, on_conflict="id", *, ignore_duplicates=False, columns=None):
        self.db.writes.append(("upsert", self.name))
        keys = on_conflict.split(",")
        out = []
        for row in data if isinstance(data, list) else [data]:
            existing = next((r for r in self.rows if all(r.get(k) == row.get(k) for k in keys)), None)
            if existing is None:
                existing = dict(row)
                self.rows.append(existing)
            else:
                existing.update(row)
            out.append(dict(existing))
        return out

    def delete(self, filters):
        gone = [r for r in self.rows if _match(r, filters)]
        self.db.data[self.name] = [r for r in self.rows if r not in gone]
        return gone


class FakeDB:
    id_tables = {"course_offerings", "courses", "documents", "notes", "achievements"}

    def __init__(self, data: dict[str, list[dict]] | None = None):
        self.data = {k: [dict(r) for r in v] for k, v in (data or {}).items()}
        self.schemas: dict[str, set[str]] = {}
        self.writes: list[tuple[str, str]] = []

    def table(self, name: str) -> FakeTable:
        return FakeTable(self, name)


@pytest.fixture
def use(monkeypatch):
    """Point the module at one environment: its database and its key."""

    def _use(db: FakeDB, key: AESGCM, env: str):
        monkeypatch.setattr(account_bundle, "table", db.table)
        monkeypatch.setattr(academics, "table", db.table)
        monkeypatch.setattr(encryption, "_AESGCM", key)
        monkeypatch.setattr(account_bundle.config, "APP_ENV", env)
        # The level curve lives in growth_stages; a stand-in keeps it pure.
        monkeypatch.setattr(account_bundle, "level_for_xp", level_for)

    return _use


def level_for(xp: int) -> int:
    return 1 + xp // 25


@pytest.fixture
def consent_clears(monkeypatch):
    calls = []
    monkeypatch.setattr(account_bundle, "clear_analytics_consent_cache", calls.append)
    return calls


@pytest.fixture
def wipes(monkeypatch):
    calls = []
    monkeypatch.setattr(account_bundle, "_wipe", lambda uid: calls.append(uid) or {})
    return calls


# ── The two environments ────────────────────────────────────────────────────

# Catalog: same natural keys, different UUIDs per project.
SRC_SCHOOL, DST_SCHOOL = "src-school", "dst-school"
SRC_CS, DST_CS = "src-course-cs", "dst-course-cs"
SRC_BIO, DST_BIO = "src-course-bio", "dst-course-bio"
SRC_OFF_CS, DST_OFF_CS = "src-off-cs-f26", "dst-off-cs-f26"
SRC_OFF_BIO = "src-off-bio-s26"  # absent on the target → created there
SRC_ACH_FIRST, DST_ACH_FIRST = "src-ach-1", "dst-ach-1"
SRC_ACH_GONE = "src-ach-2"  # slug the target does not have

TERMS = [{"id": "fall-2026"}, {"id": "spring-2026"}]


def source_db() -> FakeDB:
    A = KEY_A
    return FakeDB({
        "users": [{
            "id": UID, "deleted_at": None, "total_xp": 420, "level": 3, "streak_count": 5,
            "longest_streak": 9, "onboarding_completed": True,
            "last_active_date": "2026-11-07", "daily_goal_xp": 50,
            "email": enc(A, "student@bu.edu"),
        }],
        "user_profiles": [{
            "user_id": UID, "name": enc(A, "Ada Student"), "first_name": enc(A, "Ada"),
            "last_name": enc(A, "Student"), "bio": enc(A, "I like graphs"), "location": None,
            "username": "ada", "avatar_url": "https://src.example/avatar.png",
            "year": "Junior", "majors": ["Computer Science"], "minors": [],
            "learning_style": "visual", "website": None,
            "created_at": "2026-01-01T00:00:00Z", "updated_at": "2026-01-02T00:00:00Z",
        }],
        "user_settings": [{
            "user_id": UID, "theme": "dark", "font_size": "large", "accent_color": "#123456",
            "share_class_context": False, "analytics_opt_out": True,
            "profile_visibility": "private", "activity_status_visible": True,
            "notification_email": True, "notification_push": False, "notification_in_app": True,
            "equipped_banner_id": "cosmetic-1", "featured_role_id": "role-1",
            "featured_achievement_ids": [SRC_ACH_FIRST],
            "created_at": "2026-01-01T00:00:00Z", "updated_at": "2026-01-01T00:00:00Z",
        }],
        "schools": [{"id": SRC_SCHOOL, "slug": "bu"}],
        "courses": [
            {"id": SRC_CS, "course_code": "CAS CS 111", "course_name": "Intro CS",
             "school_id": SRC_SCHOOL},
            {"id": SRC_BIO, "course_code": "CAS BI 108", "course_name": "Biology",
             "school_id": SRC_SCHOOL},
        ],
        "terms": TERMS,
        "course_offerings": [
            {"id": SRC_OFF_CS, "course_id": SRC_CS, "term_id": "fall-2026", "section": "",
             "instructor_name": "Dr. A", "meeting_times": None, "location": None},
            {"id": SRC_OFF_BIO, "course_id": SRC_BIO, "term_id": "spring-2026", "section": "",
             "instructor_name": None, "meeting_times": None, "location": None},
        ],
        "achievements": [
            {"id": SRC_ACH_FIRST, "slug": "first-quiz"},
            {"id": SRC_ACH_GONE, "slug": "retired-badge"},
        ],
        "graph_nodes": [
            {"id": "node-1", "user_id": UID, "course_id": SRC_CS, "concept_name": "Recursion",
             "mastery_score": 0.6, "mastery_tier": "learning"},
            {"id": "node-2", "user_id": UID, "course_id": SRC_BIO, "concept_name": "Cells",
             "mastery_score": 0.1, "mastery_tier": "struggling"},
        ],
        "graph_edges": [
            {"id": "edge-1", "user_id": UID, "source_node_id": "node-1",
             "target_node_id": "node-2", "relationship_type": "related", "strength": 0.5},
        ],
        "node_mastery_events": [
            {"id": "nme-1", "node_id": "node-1", "delta": 0.2, "reason": "quiz"},
        ],
        "documents": [{
            "id": "doc-1", "user_id": UID, "offering_id": SRC_OFF_CS, "file_name": "syllabus.pdf",
            "category": "syllabus", "summary": enc(A, "Weekly homework."),
            "concept_notes": enc_json(A, [{"name": "Recursion", "description": "self-call"}]),
            "extracted_text": enc(A, "CS 111 syllabus text"), "flashcards": None,
            "deleted_at": None, "shareability": "course_material", "shareability_confidence": 0.9,
            "index_status": "indexed", "index_attempts": 1, "index_chunk_count": 4,
            "index_leased_at": "2026-11-01T00:00:00Z", "index_error": None,
        }],
        "course_chunks": [{"id": "chunk-1", "doc_id": "doc-1", "chunk_text": enc(A, "chunk")}],
        "enrollments": [
            {"id": "enr-1", "user_id": UID, "offering_id": SRC_OFF_CS, "color": "#fff",
             "nickname": "CS", "syllabus_doc_id": "doc-1", "curve_mode": "raw"},
            {"id": "enr-2", "user_id": UID, "offering_id": SRC_OFF_BIO, "color": "#000",
             "nickname": "Bio", "syllabus_doc_id": None, "curve_mode": "raw"},
        ],
        "gradebook_categories": [
            {"id": "cat-1", "enrollment_id": "enr-1", "name": "Homework", "weight": 0.5},
        ],
        "assignments": [{
            "id": "asg-1", "enrollment_id": "enr-1", "category_id": "cat-1", "title": "HW1",
            "notes": enc(A, "remember the base case"), "points_possible": enc(A, "100"),
            "points_earned": enc(A, "88"), "source": "manual",
        }],
        "topic_checklists": [{
            "enrollment_id": "enr-1", "input_hash": "h",
            "content": enc_json(A, {"topics": [{"name": "Recursion"}]}),
        }],
        "topic_checklist_progress": [{"enrollment_id": "enr-1", "topic_key": "recursion"}],
        "notes": [{
            "id": "note-1", "user_id": UID, "offering_id": SRC_OFF_CS,
            "title": enc(A, "Week 1"), "body": enc(A, "Body text"), "last_summary": None,
            "tags": ["w1"], "deleted_at": None,
        }],
        "note_concepts": [{"note_id": "note-1", "concept_node_id": "node-1"}],
        "flashcards": [{
            "id": "fc-1", "user_id": UID, "offering_id": None, "topic": "CS",
            "front": enc(A, "What is recursion?"), "back": enc(A, "A self call"),
        }],
        "sessions": [{
            "id": "sess-1", "user_id": UID, "offering_id": SRC_OFF_BIO, "mode": "socratic",
            "topic": "Cells", "summary_json": enc_json(A, {"bullets": ["mitochondria"]}),
        }],
        "messages": [
            {"id": "msg-1", "session_id": "sess-1", "role": "user", "content": enc(A, "Hi")},
            {"id": "msg-2", "session_id": "sess-1", "role": "assistant", "content": enc(A, "Hello")},
        ],
        "study_guides": [{
            "id": "sg-1", "user_id": UID, "offering_id": SRC_OFF_CS, "exam_id": "asg-1",
            "content": enc_json(A, {"exam": "Midterm"}),
        }],
        "quiz_attempts": [{
            "id": "qa-1", "user_id": UID, "concept_node_id": "node-1", "score": 3, "total": 4,
            "questions_json": enc_json(A, [{"q": "?"}]), "answers_json": None,
        }],
        "quiz_responses": [{
            "id": "qr-1", "attempt_id": "qa-1", "question_index": 0, "is_correct": True,
            "answer_text": enc_json(A, {"text": "a base case"}),
        }],
        "quiz_context": [{
            "id": "qc-1", "user_id": UID, "concept_node_id": "node-1",
            "context_json": enc_json(A, {"misconceptions": []}),
        }],
        "xp_events": [
            {"id": "xp-1", "user_id": UID, "rule_key": "quiz_completed", "amount": 10,
             "source_type": "quiz", "source_id": "qa-1",
             "idempotency_key": "quiz_completed:quiz:qa-1"},
            # Achievement payouts name the SOURCE catalog UUID twice.
            {"id": "xp-2", "user_id": UID, "rule_key": "achievement_unlocked", "amount": 50,
             "source_type": "achievement", "source_id": SRC_ACH_FIRST,
             "idempotency_key": f"achievement_unlocked:achievement:{SRC_ACH_FIRST}"},
            {"id": "xp-3", "user_id": UID, "rule_key": "achievement_unlocked", "amount": 25,
             "source_type": "achievement", "source_id": SRC_ACH_GONE,
             "idempotency_key": f"achievement_unlocked:achievement:{SRC_ACH_GONE}"},
        ],
        "user_achievements": [
            {"user_id": UID, "achievement_id": SRC_ACH_FIRST, "earned_at": "2026-10-01T00:00:00Z",
             "is_featured": True},
            {"user_id": UID, "achievement_id": SRC_ACH_GONE, "earned_at": "2026-10-02T00:00:00Z",
             "is_featured": False},
        ],
    })


def target_db() -> FakeDB:
    return FakeDB({
        "users": [{"id": UID, "deleted_at": None, "total_xp": 0, "level": 1}],
        # The target's own privacy/consent/notification choices: never overwritten.
        "user_settings": [{
            "user_id": UID, "theme": "light", "share_class_context": True,
            "analytics_opt_out": False, "profile_visibility": "school",
            "activity_status_visible": False, "notification_email": False,
            "notification_push": True, "notification_in_app": False,
        }],
        "user_profiles": [
            {"user_id": UID, "username": "ada-target", "avatar_url": "https://dst/avatar.png"},
            {"user_id": "someone-else", "username": "ada"},
        ],
        "schools": [{"id": DST_SCHOOL, "slug": "bu"}],
        "courses": [
            {"id": DST_CS, "course_code": "CAS CS 111", "school_id": DST_SCHOOL},
            {"id": DST_BIO, "course_code": "CAS BI 108", "school_id": DST_SCHOOL},
        ],
        "terms": TERMS,
        "course_offerings": [
            {"id": DST_OFF_CS, "course_id": DST_CS, "term_id": "fall-2026", "section": "",
             "created_at": "2026-01-01"},
        ],
        "achievements": [{"id": DST_ACH_FIRST, "slug": "first-quiz"}],
    })


def export_from_source(use) -> dict:
    use(source_db(), KEY_A, "staging")
    bundle = account_bundle.export_account(UID)
    # It crosses the wire as JSON: anything not serialisable fails here.
    return json.loads(json.dumps(bundle))


# ── Export ───────────────────────────────────────────────────────────────────


def test_export_is_plaintext_with_natural_key_catalog(use):
    bundle = export_from_source(use)

    assert bundle["version"] == account_bundle.BUNDLE_VERSION
    assert bundle["user_id"] == UID and bundle["source_env"] == "staging"
    t = bundle["tables"]
    assert t["documents"][0]["summary"] == "Weekly homework."
    assert t["documents"][0]["concept_notes"] == [{"name": "Recursion", "description": "self-call"}]
    assert t["assignments"][0]["points_earned"] == "88"
    assert t["messages"][1]["content"] == "Hello"
    assert t["quiz_responses"][0]["answer_text"] == {"text": "a base case"}
    assert t["topic_checklists"][0]["content"] == {"topics": [{"name": "Recursion"}]}
    assert bundle["profile"]["name"] == "Ada Student"
    assert "avatar_url" not in bundle["profile"]
    assert "equipped_banner_id" not in bundle["settings"]
    assert "featured_achievement_ids" not in bundle["settings"]
    # Only display preferences travel; consent never leaves the source.
    assert bundle["settings"] == {"theme": "dark", "font_size": "large", "accent_color": "#123456"}
    assert bundle["catalog"]["achievements"] == {
        SRC_ACH_FIRST: "first-quiz", SRC_ACH_GONE: "retired-badge",
    }
    assert bundle["user"]["total_xp"] == 420
    assert "email" not in bundle["user"]
    assert "course_chunks" not in t
    # Catalog refs are natural keys; achievements travel by slug.
    assert bundle["catalog"]["courses"][SRC_CS]["course_code"] == "CAS CS 111"
    assert bundle["catalog"]["offerings"][SRC_OFF_BIO]["term_id"] == "spring-2026"
    assert {a["achievement_slug"] for a in t["user_achievements"]} == {"first-quiz", "retired-badge"}


def test_strict_decrypt_refuses_wrong_key_ciphertext(use):
    db = source_db()
    db.data["notes"][0]["body"] = enc(KEY_C, "written under another key")
    use(db, KEY_A, "staging")

    with pytest.raises(BundleError, match=r"notes\.body.*does not decrypt"):
        account_bundle.export_account(UID)


def test_soft_decrypt_would_have_shipped_the_ciphertext():
    """Why the strict path exists: the app's read helper returns a wrong-key
    value unchanged, which an export would have shipped as 'plaintext'."""
    ct = enc(KEY_C, "secret")
    assert encryption.decrypt_if_present(ct) == ct
    with pytest.raises(BundleError):
        account_bundle._decrypt_text(ct, "t.c")


def test_legacy_plaintext_in_an_encrypted_column_travels_as_is(use):
    db = source_db()
    db.data["notes"][0]["title"] = "Week 1 (legacy, never backfilled)"
    use(db, KEY_A, "staging")

    bundle = account_bundle.export_account(UID)
    assert bundle["tables"]["notes"][0]["title"] == "Week 1 (legacy, never backfilled)"


def test_unlisted_encrypted_column_fails_the_export(use):
    db = source_db()
    db.data["sessions"][0]["close_json"] = enc(KEY_A, "a new 🔒 column nobody listed")
    use(db, KEY_A, "staging")

    with pytest.raises(BundleError, match=r"sessions\.close_json.*not in account_bundle\.ENCRYPTED"):
        account_bundle.export_account(UID)


def test_export_unknown_or_deleted_account(use):
    db = source_db()
    db.data["users"][0]["deleted_at"] = "2026-11-01T00:00:00Z"
    use(db, KEY_A, "staging")
    with pytest.raises(AccountNotFound):
        account_bundle.export_account(UID)
    assert account_bundle.account_exists(UID) is False


# ── Round trip: export under key A, import under key B ──────────────────────


def test_round_trip_reencrypts_under_the_target_key_and_remaps_catalog(use, wipes, consent_clears):
    bundle = export_from_source(use)
    dst = target_db()
    use(dst, KEY_B, "production")

    counts = account_bundle.import_account(UID, bundle)

    assert wipes == [UID]
    d = dst.data
    doc = d["documents"][0]
    # Re-encrypted under B: readable with B, not with A.
    assert dec(KEY_B, doc["summary"]) == "Weekly homework."
    assert json.loads(dec(KEY_B, doc["concept_notes"]))[0]["name"] == "Recursion"
    with pytest.raises(Exception):
        dec(KEY_A, doc["summary"])
    # Documents re-index on the target; shareability travels.
    assert doc["index_status"] == "pending"
    assert doc["index_attempts"] == 0 and doc["index_chunk_count"] is None
    assert doc["shareability"] == "course_material"
    assert "course_chunks" not in d
    # Offerings remapped: existing one reused, the missing one created.
    assert doc["offering_id"] == DST_OFF_CS
    enr = {e["id"]: e for e in d["enrollments"]}
    assert enr["enr-1"]["offering_id"] == DST_OFF_CS
    bio_off = enr["enr-2"]["offering_id"]
    assert bio_off not in (SRC_OFF_BIO, DST_OFF_CS)
    created = next(o for o in d["course_offerings"] if o["id"] == bio_off)
    assert created["course_id"] == DST_BIO and created["term_id"] == "spring-2026"
    assert created["section"] == ""
    assert d["sessions"][0]["offering_id"] == bio_off
    assert d["flashcards"][0]["offering_id"] is None
    # Graph course ids remapped by course_code; row ids preserved.
    nodes = {n["id"]: n["course_id"] for n in d["graph_nodes"]}
    assert nodes == {"node-1": DST_CS, "node-2": DST_BIO}
    assert d["graph_edges"][0]["source_node_id"] == "node-1"
    # Encrypted values everywhere read back under B.
    a = d["assignments"][0]
    assert dec(KEY_B, a["points_earned"]) == "88" and dec(KEY_B, a["notes"]) == "remember the base case"
    assert [dec(KEY_B, m["content"]) for m in d["messages"]] == ["Hi", "Hello"]
    assert json.loads(dec(KEY_B, d["quiz_responses"][0]["answer_text"])) == {"text": "a base case"}
    assert json.loads(dec(KEY_B, d["study_guides"][0]["content"])) == {"exam": "Midterm"}
    assert d["quiz_attempts"][0]["answers_json"] is None
    assert json.loads(dec(KEY_B, d["topic_checklists"][0]["content"]))["topics"][0]["name"] == "Recursion"
    # Achievements by slug; one the target lacks is skipped and counted.
    assert d["user_achievements"] == [{
        "user_id": UID, "achievement_id": DST_ACH_FIRST,
        "earned_at": "2026-10-01T00:00:00Z", "is_featured": True,
    }]
    assert counts["user_achievements"] == 1 and counts["user_achievements_skipped"] == 1
    # Profile: re-encrypted, username kept (someone else holds it here), avatar untouched.
    prof = next(p for p in d["user_profiles"] if p["user_id"] == UID)
    assert dec(KEY_B, prof["name"]) == "Ada Student"
    assert prof["username"] == "ada-target"
    assert prof["avatar_url"] == "https://dst/avatar.png"
    assert prof["majors"] == ["Computer Science"]
    # Settings: display preferences move; consent/privacy/notifications stay the target's.
    [settings] = d["user_settings"]
    assert settings == {
        "user_id": UID, "theme": "dark", "font_size": "large", "accent_color": "#123456",
        "share_class_context": True, "analytics_opt_out": False,
        "profile_visibility": "school", "activity_status_visible": False,
        "notification_email": False, "notification_push": True, "notification_in_app": False,
    }
    assert consent_clears == [UID]
    # Counters: the streak moves; total_xp/level are re-derived from the imported
    # ledger (10 + 50 — the retired badge's 25 XP went with the badge).
    user = d["users"][0]
    assert user["total_xp"] == 60 and user["level"] == level_for(60)
    assert user["streak_count"] == 5 and user["onboarding_completed"]
    assert counts["messages"] == 2 and counts["documents"] == 1 and counts["graph_nodes"] == 2


def test_username_moves_when_free_on_the_target(use, wipes):
    bundle = export_from_source(use)
    dst = target_db()
    dst.data["user_profiles"] = [p for p in dst.data["user_profiles"] if p["user_id"] == UID]
    use(dst, KEY_B, "production")

    account_bundle.import_account(UID, bundle)
    assert dst.data["user_profiles"][0]["username"] == "ada"


def test_soft_deleted_document_imports_skipped_not_pending(use, wipes):
    src = source_db()
    src.data["documents"][0]["deleted_at"] = "2026-10-01T00:00:00Z"
    use(src, KEY_A, "staging")
    bundle = json.loads(json.dumps(account_bundle.export_account(UID)))
    dst = target_db()
    use(dst, KEY_B, "production")

    account_bundle.import_account(UID, bundle)
    assert dst.data["documents"][0]["index_status"] == "skipped"


# ── Import refusals: all BEFORE the wipe ────────────────────────────────────


def test_version_mismatch(use, wipes):
    bundle = export_from_source(use)
    use(target_db(), KEY_B, "production")
    bundle["version"] = 99
    with pytest.raises(BundleError, match="version"):
        account_bundle.import_account(UID, bundle)
    assert wipes == []


def test_user_mismatch(use, wipes):
    bundle = export_from_source(use)
    use(target_db(), KEY_B, "production")
    with pytest.raises(BundleError, match="different account"):
        account_bundle.import_account("user_someone_else", bundle)
    assert wipes == []


def test_target_account_must_exist(use, wipes):
    bundle = export_from_source(use)
    dst = target_db()
    dst.data["users"] = []
    use(dst, KEY_B, "production")
    with pytest.raises(AccountNotFound):
        account_bundle.import_account(UID, bundle)
    assert wipes == []


def test_course_missing_from_target_catalog(use, wipes):
    bundle = export_from_source(use)
    dst = target_db()
    dst.data["courses"] = [c for c in dst.data["courses"] if c["course_code"] != "CAS BI 108"]
    use(dst, KEY_B, "production")
    with pytest.raises(BundleError, match="CAS BI 108"):
        account_bundle.import_account(UID, bundle)
    assert wipes == []


def test_term_missing_from_target(use, wipes):
    bundle = export_from_source(use)
    dst = target_db()
    dst.data["terms"] = [{"id": "fall-2026"}]
    use(dst, KEY_B, "production")
    with pytest.raises(BundleError, match="spring-2026"):
        account_bundle.import_account(UID, bundle)
    assert wipes == []


def test_target_schema_missing_a_column_fails_before_the_wipe(use, wipes):
    bundle = export_from_source(use)
    bundle["tables"]["notes"][0]["brand_new_column"] = 1
    dst = target_db()
    dst.schemas["notes"] = {"id", "user_id", "offering_id", "title", "body", "last_summary",
                            "tags", "deleted_at"}
    use(dst, KEY_B, "production")
    with pytest.raises(BundleError, match="notes table cannot take"):
        account_bundle.import_account(UID, bundle)
    assert wipes == []
    assert not any(op == "insert" and name == "notes" for op, name in dst.writes)


def test_unknown_table_in_bundle_is_refused(use, wipes):
    bundle = export_from_source(use)
    use(target_db(), KEY_B, "production")
    bundle["tables"]["oauth_tokens"] = [{"user_id": UID}]
    with pytest.raises(BundleError, match="oauth_tokens"):
        account_bundle.import_account(UID, bundle)
    assert wipes == []


# ── Consent ─────────────────────────────────────────────────────────────────


def test_consent_in_a_peer_bundle_is_never_written(use, wipes, consent_clears):
    """Even a bundle that carries consent columns (an older/foreign exporter)
    cannot write them: the allowlist is enforced on the target side too."""
    bundle = export_from_source(use)
    bundle["settings"].update(share_class_context=False, analytics_opt_out=True,
                              notification_email=True)
    dst = target_db()
    use(dst, KEY_B, "production")

    account_bundle.import_account(UID, bundle)
    [settings] = dst.data["user_settings"]
    assert settings["share_class_context"] is True
    assert settings["analytics_opt_out"] is False
    assert settings["notification_email"] is False
    assert settings["theme"] == "dark"


def test_target_without_settings_row_gets_only_display_preferences(use, wipes, consent_clears):
    bundle = export_from_source(use)
    dst = target_db()
    dst.data["user_settings"] = []
    use(dst, KEY_B, "production")

    account_bundle.import_account(UID, bundle)
    [settings] = dst.data["user_settings"]
    # Consent columns are absent → the column defaults (opted in to the class
    # pool, not opted out of analytics) apply, as for any fresh account here.
    assert set(settings) == {"user_id", "theme", "font_size", "accent_color"}


# ── XP ledger ───────────────────────────────────────────────────────────────


def test_achievement_xp_is_remapped_to_the_target_achievement(use, wipes, consent_clears):
    from services.xp_service import idempotency_key

    bundle = export_from_source(use)
    dst = target_db()
    use(dst, KEY_B, "production")

    counts = account_bundle.import_account(UID, bundle)
    xp = {r["id"]: r for r in dst.data["xp_events"]}
    # Exactly what award_xp writes for this badge on the target (and what
    # achievement_service._heal_grants looks up by source_id).
    assert xp["xp-2"]["source_id"] == DST_ACH_FIRST
    assert xp["xp-2"]["idempotency_key"] == idempotency_key(
        "achievement_unlocked", "achievement", DST_ACH_FIRST)
    assert xp["xp-2"]["user_id"] == UID and xp["xp-2"]["amount"] == 50
    # The retired badge (unknown here) is dropped with its XP; other rules untouched.
    assert "xp-3" not in xp
    assert xp["xp-1"]["idempotency_key"] == "quiz_completed:quiz:qa-1"
    assert counts["xp_events"] == 2 and counts["xp_events_skipped"] == 1
    assert not any(SRC_ACH_FIRST in str(r) or SRC_ACH_GONE in str(r)
                   for r in dst.data["xp_events"])


def test_achievement_xp_key_held_by_another_account_gets_a_user_suffix(use, wipes, consent_clears):
    """xp_events.idempotency_key is UNIQUE across all users and the canonical
    achievement key has no user in it: re-inserting one another account holds
    would fail after the wipe. Decided before the wipe instead."""
    bundle = export_from_source(use)
    dst = target_db()
    canonical = f"achievement_unlocked:achievement:{DST_ACH_FIRST}"
    dst.data["xp_events"] = [{"id": "other-xp", "user_id": "user_other", "amount": 50,
                              "rule_key": "achievement_unlocked", "source_type": "achievement",
                              "source_id": DST_ACH_FIRST, "idempotency_key": canonical}]
    use(dst, KEY_B, "production")

    account_bundle.import_account(UID, bundle)
    mine = next(r for r in dst.data["xp_events"] if r["id"] == "xp-2")
    assert mine["idempotency_key"] == f"{canonical}:{UID}"
    assert mine["source_id"] == DST_ACH_FIRST  # what _heal_grants reads
    keys = [r["idempotency_key"] for r in dst.data["xp_events"]]
    assert len(keys) == len(set(keys))


def test_bundle_without_achievement_catalog_drops_achievement_xp(use, wipes, consent_clears):
    bundle = export_from_source(use)
    del bundle["catalog"]["achievements"]
    dst = target_db()
    use(dst, KEY_B, "production")

    counts = account_bundle.import_account(UID, bundle)
    assert [r["id"] for r in dst.data["xp_events"]] == ["xp-1"]
    assert counts["xp_events_skipped"] == 2
    assert dst.data["users"][0]["total_xp"] == 10


# ── Offering remap ──────────────────────────────────────────────────────────


def test_sectionless_offering_never_lands_on_another_section(use, wipes, consent_clears):
    """resolve_offering matches (course, term) with ANY section; the import
    must match the exact triple and create the sectionless one."""
    bundle = export_from_source(use)
    dst = target_db()
    dst.data["course_offerings"] = [
        {"id": "dst-off-cs-a1", "course_id": DST_CS, "term_id": "fall-2026", "section": "A1",
         "created_at": "2025-01-01"},
    ]
    use(dst, KEY_B, "production")

    account_bundle.import_account(UID, bundle)
    enr = {e["id"]: e for e in dst.data["enrollments"]}
    cs_off = enr["enr-1"]["offering_id"]
    assert cs_off != "dst-off-cs-a1"
    made = next(o for o in dst.data["course_offerings"] if o["id"] == cs_off)
    assert (made["course_id"], made["term_id"], made["section"]) == (DST_CS, "fall-2026", "")


def test_null_section_resolves_as_the_empty_section(use, wipes, consent_clears):
    bundle = export_from_source(use)
    bundle["catalog"]["offerings"][SRC_OFF_CS]["section"] = None
    dst = target_db()
    use(dst, KEY_B, "production")

    account_bundle.import_account(UID, bundle)
    enr = {e["id"]: e for e in dst.data["enrollments"]}
    assert enr["enr-1"]["offering_id"] == DST_OFF_CS


def test_enrollments_colliding_on_one_target_offering_refuse_before_the_wipe(use, wipes):
    # Two source courses share a course_code (two schools); the target has one.
    src = source_db()
    src.data["schools"].append({"id": "src-school-2", "slug": "met"})
    src.data["courses"].append({"id": "src-course-cs-met", "course_code": "CAS CS 111",
                                "course_name": "Intro CS (MET)", "school_id": "src-school-2"})
    src.data["course_offerings"].append({
        "id": "src-off-cs-met", "course_id": "src-course-cs-met", "term_id": "fall-2026",
        "section": "", "instructor_name": None, "meeting_times": None, "location": None,
    })
    src.data["enrollments"].append({"id": "enr-3", "user_id": UID, "offering_id": "src-off-cs-met",
                                    "color": "#111", "nickname": "CS2", "syllabus_doc_id": None,
                                    "curve_mode": "raw"})
    use(src, KEY_A, "staging")
    bundle = json.loads(json.dumps(account_bundle.export_account(UID)))
    dst = target_db()
    use(dst, KEY_B, "production")

    with pytest.raises(BundleError, match="would map onto one"):
        account_bundle.import_account(UID, bundle)
    assert wipes == []
    assert ("insert", "course_offerings") not in dst.writes


@pytest.mark.parametrize("bad", [["first-quiz"], {SRC_ACH_FIRST: ["first-quiz"]}])
def test_malformed_achievement_catalog_is_refused_before_the_wipe(use, wipes, bad):
    bundle = export_from_source(use)
    bundle["catalog"]["achievements"] = bad
    use(target_db(), KEY_B, "production")
    with pytest.raises(BundleError, match="achievements"):
        account_bundle.import_account(UID, bundle)
    assert wipes == []

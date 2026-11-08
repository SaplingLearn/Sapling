"""Admin account tools: `services/account_wipe.py::wipe_account_data`.

Driven against an in-memory PostgREST that honours the filters the module
sends and models the FK cascades the wipe relies on. The REAL
`chunk_visibility.withdraw_document_chunks` runs against the same fake, so the
chunk rules are exercised end to end rather than mocked away (one test swaps
it for a recorder to pin call order, one for a failure).
"""
import pytest

from services import account_wipe as aw
from services import chunk_visibility as cv

U, OTHER = "user_wipe", "user_keep"

WIPED = (
    "enrollments", "documents", "notes", "flashcards", "sessions", "study_guides",
    "quiz_attempts", "quiz_context", "graph_nodes", "xp_events", "user_achievements",
)
KEPT = (
    "users", "user_profiles", "user_settings", "user_roles", "oauth_tokens",
    "gradescope_credentials", "user_cosmetics", "friendships", "rooms",
    "room_members", "feedback", "issue_reports", "events", "llm_usage",
    "admin_audit_log", "offering_concept_stats",
)

#: child table -> (child column, parent table, parent column): ON DELETE CASCADE.
CASCADES = {
    "gradebook_categories": ("enrollment_id", "enrollments", "id"),
    "assignments": ("enrollment_id", "enrollments", "id"),
    "gradescope_course_links": ("enrollment_id", "enrollments", "id"),
    "topic_checklists": ("enrollment_id", "enrollments", "id"),
    "messages": ("session_id", "sessions", "id"),
    "quiz_responses": ("attempt_id", "quiz_attempts", "id"),
    "graph_edges": ("source_node_id", "graph_nodes", "id"),
    "node_mastery_events": ("node_id", "graph_nodes", "id"),
    "course_chunk_sources": ("chunk_id", "course_chunks", "id"),
    "course_chunk_contributors": ("chunk_id", "course_chunks", "id"),
}


def _unquote(v):
    return v[1:-1] if len(v) >= 2 and v[0] == v[-1] == '"' else v


def _match(row, col, cond):
    op, _, val = cond.partition(".")
    cur = row.get(col)
    if op == "eq":
        return cur is not None and str(cur) == val
    if op == "neq":
        return cur is not None and str(cur) != val
    if op == "is":
        return cur is None if val == "null" else str(cur).lower() == val
    if op == "in":
        return str(cur) in {_unquote(v) for v in val.strip("()").split(",")}
    raise AssertionError(f"filter op {op!r} not modelled")


class FakeDB:
    def __init__(self):
        self.rows: dict[str, list[dict]] = {}
        self.log: list[tuple[str, str, dict]] = []  # (op, table, filters/data)

    def add(self, name, **row):
        self.rows.setdefault(name, []).append(row)

    def of(self, name, **match):
        return [r for r in self.rows.get(name, [])
                if all(r.get(k) == v for k, v in match.items())]

    def ops(self, op):
        return [t for o, t, _ in self.log if o == op]

    def _cascade(self, name, gone):
        for child, (col, parent, pcol) in CASCADES.items():
            if parent != name:
                continue
            keys = {r[pcol] for r in gone}
            dead = [r for r in self.rows.get(child, []) if r.get(col) in keys]
            if dead:
                self.rows[child] = [r for r in self.rows[child] if r not in dead]
                self._cascade(child, dead)

    def table(self, name):
        db = self

        def hits(filters):
            return [r for r in db.rows.get(name, [])
                    if all(_match(r, k, v) for k, v in (filters or {}).items())]

        class _T:
            def select(self, columns="*", filters=None, limit=None, **_):
                db.log.append(("select", name, dict(filters or {})))
                rows = [dict(r) for r in hits(filters)]
                return rows[:limit] if limit else rows

            def select_with_count(self, columns="*", filters=None, order=None,
                                  limit=None, offset=0, **_):
                db.log.append(("select", name, dict(filters or {})))
                rows = [dict(r) for r in hits(filters)]
                if order:
                    key = order.split(",")[0].split(".")[0]
                    rows.sort(key=lambda r: str(r.get(key)))
                return rows[offset or 0:(offset or 0) + limit], len(rows)

            def update(self, data, filters, *, prefer_return_minimal=False):
                db.log.append(("update", name, dict(data)))
                for r in hits(filters):
                    r.update(data)
                return []

            def delete(self, filters):
                db.log.append(("delete", name, dict(filters)))
                gone = hits(filters)
                db.rows[name] = [r for r in db.rows.get(name, []) if r not in gone]
                db._cascade(name, gone)
                return []

        return _T()


@pytest.fixture
def db(monkeypatch):
    fake = FakeDB()
    monkeypatch.setattr(aw, "table", fake.table)
    monkeypatch.setattr(cv, "table", fake.table)
    return fake


def _seed_user(db, uid, *, n=1):
    """One of everything in and out of the wipe scope, ids prefixed by uid."""
    p = uid
    db.add("users", id=uid, total_xp=420, level=7, streak_count=5, longest_streak=9,
           last_active_date="2026-11-08", daily_goal_xp=50)
    db.add("user_settings", user_id=uid, featured_achievement_ids=[f"{p}-ach0"])
    for kept in KEPT:
        if kept not in ("users", "user_settings"):
            db.add(kept, id=f"{p}-{kept}", user_id=uid)
    for i in range(n):
        db.add("enrollments", id=f"{p}-enr{i}", user_id=uid, syllabus_doc_id=f"{p}-doc{i}")
        db.add("gradebook_categories", id=f"{p}-cat{i}", enrollment_id=f"{p}-enr{i}")
        db.add("assignments", id=f"{p}-asg{i}", enrollment_id=f"{p}-enr{i}")
        db.add("topic_checklists", enrollment_id=f"{p}-enr{i}")
        db.add("gradescope_course_links", id=f"{p}-gsl{i}", enrollment_id=f"{p}-enr{i}")
        db.add("documents", id=f"{p}-doc{i}", user_id=uid, deleted_at=None)
        db.add("notes", id=f"{p}-note{i}", user_id=uid)
        db.add("flashcards", id=f"{p}-fc{i}", user_id=uid)
        db.add("sessions", id=f"{p}-ses{i}", user_id=uid)
        db.add("messages", id=f"{p}-msg{i}", session_id=f"{p}-ses{i}")
        db.add("study_guides", id=f"{p}-sg{i}", user_id=uid)
        db.add("quiz_attempts", id=f"{p}-qa{i}", user_id=uid)
        db.add("quiz_responses", id=f"{p}-qr{i}", attempt_id=f"{p}-qa{i}")
        db.add("quiz_context", id=f"{p}-qc{i}", user_id=uid)
        db.add("graph_nodes", id=f"{p}-gn{i}", user_id=uid)
        db.add("graph_edges", id=f"{p}-ge{i}", source_node_id=f"{p}-gn{i}", user_id=uid)
        db.add("node_mastery_events", id=f"{p}-me{i}", node_id=f"{p}-gn{i}")
        db.add("xp_events", id=f"{p}-xp{i}", user_id=uid)
        db.add("user_achievements", achievement_id=f"{p}-ach{i}", user_id=uid)
        # A private chunk of this document, ledgered as its source.
        db.add("course_chunks", id=f"{p}-ck{i}", doc_id=f"{p}-doc{i}", uploader_id=uid,
               visibility="private", category="lecture_notes")
        db.add("course_chunk_sources", chunk_id=f"{p}-ck{i}", doc_id=f"{p}-doc{i}")


# ── guard ───────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("bad", ["", "   ", None])
def test_blank_user_id_is_refused_before_any_db_call(db, bad):
    with pytest.raises(ValueError):
        aw.wipe_account_data(bad)
    assert db.log == []


# ── scope ───────────────────────────────────────────────────────────────────


def test_wipes_the_scope_and_keeps_everything_else(db):
    _seed_user(db, U, n=2)
    _seed_user(db, OTHER, n=2)

    counts = aw.wipe_account_data(U)

    for name in WIPED:
        assert db.of(name, user_id=U) == [], name
        assert len(db.of(name, user_id=OTHER)) == 2, name  # untouched neighbour
    # The cascades the module relies on actually emptied the children.
    for child, (col, _parent, _pc) in CASCADES.items():
        if child.startswith("course_chunk"):
            continue
        assert not any(str(r.get(col, "")).startswith(U) for r in db.rows.get(child, [])), child
        assert any(str(r.get(col, "")).startswith(OTHER) for r in db.rows.get(child, [])), child
    # Kept tables were never the target of a delete, and still hold the row.
    assert not set(db.ops("delete")) & set(KEPT)
    for name in KEPT:
        assert db.of(name, user_id=U) or db.of(name, id=U), name

    assert counts == {
        "enrollments": 2, "documents": 2, "course_chunks": 2,
        "course_chunk_contributors": 0, "notes": 2, "flashcards": 2, "sessions": 2,
        "study_guides": 2, "quiz_attempts": 2, "quiz_context": 2, "graph_nodes": 2,
        "xp_events": 2, "user_achievements": 2,
    }
    assert [r["id"] for r in db.rows["course_chunks"]] == [f"{OTHER}-ck0", f"{OTHER}-ck1"]


def test_counters_reset_and_featured_achievements_cleared(db):
    _seed_user(db, U)
    _seed_user(db, OTHER)

    aw.wipe_account_data(U)

    (me,) = db.of("users", id=U)
    assert (me["total_xp"], me["level"], me["streak_count"], me["longest_streak"]) == (0, 1, 0, 0)
    assert me["last_active_date"] is None
    assert me["daily_goal_xp"] == 50  # a preference, not a counter
    assert db.of("user_settings", user_id=U)[0]["featured_achievement_ids"] == []
    (them,) = db.of("users", id=OTHER)
    assert them["total_xp"] == 420
    assert db.of("user_settings", user_id=OTHER)[0]["featured_achievement_ids"] == [f"{OTHER}-ach0"]


def test_second_wipe_is_all_zeros(db):
    _seed_user(db, U, n=3)
    aw.wipe_account_data(U)

    again = aw.wipe_account_data(U)

    assert again and set(again.values()) == {0}


def test_deletes_are_batched_and_counts_exact(db):
    db.add("users", id=U)
    for i in range(250):
        db.add("notes", id=f"n{i:03}", user_id=U)

    counts = aw.wipe_account_data(U)

    assert counts["notes"] == 250
    note_deletes = [f for op, t, f in db.log if op == "delete" and t == "notes"]
    assert len(note_deletes) == 3
    assert all(f["user_id"] == f"eq.{U}" for f in note_deletes)  # owner-scoped
    assert db.rows["notes"] == []


# ── order ───────────────────────────────────────────────────────────────────


def test_order_enrollments_then_soft_delete_withdraw_per_doc_then_documents(db, monkeypatch):
    _seed_user(db, U, n=2)
    calls = []

    def record(doc_id, user_id):
        (doc,) = db.of("documents", id=doc_id)
        calls.append((doc_id, user_id, doc["deleted_at"] is not None, len(db.log)))
        return {"chunks_deleted": 1, "contributors_removed": 1}

    monkeypatch.setattr(cv, "withdraw_document_chunks", record)

    counts = aw.wipe_account_data(U)

    assert sorted(c[:2] for c in calls) == [(f"{U}-doc0", U), (f"{U}-doc1", U)]
    # Every document was already soft-deleted when its withdrawal ran.
    assert all(c[2] for c in calls)
    deletes = db.ops("delete")
    first = {t: deletes.index(t) for t in dict.fromkeys(deletes)}
    assert first["enrollments"] < first["documents"]
    # Documents are hard-deleted only after the last withdrawal.
    doc_delete_at = next(i for i, (op, t, _) in enumerate(db.log)
                         if op == "delete" and t == "documents")
    assert max(c[3] for c in calls) <= doc_delete_at
    # Quiz rows go before the graph nodes they reference.
    assert first["quiz_attempts"] < first["graph_nodes"]
    assert first["quiz_context"] < first["graph_nodes"]
    assert counts["course_chunk_contributors"] == 2


def test_failed_withdrawal_stops_before_hard_deleting_documents(db, monkeypatch):
    _seed_user(db, U)
    monkeypatch.setattr(cv, "withdraw_document_chunks",
                        lambda doc_id, user_id: {"failed": True})

    with pytest.raises(aw.AccountWipeIncomplete):
        aw.wipe_account_data(U)

    (doc,) = db.of("documents", user_id=U)
    assert doc["deleted_at"] is not None  # soft-deleted, kept for the re-run
    assert "documents" not in db.ops("delete")


# ── chunks ──────────────────────────────────────────────────────────────────


def test_shared_chunk_from_two_of_the_users_own_docs_is_withdrawn(db):
    """Withdrawing doc A while doc B (same text) is still live would keep the
    chunk — the reason every document is soft-deleted before any withdrawal."""
    db.add("users", id=U)
    db.add("user_settings", user_id=U, share_class_context=True)
    for d in ("dA", "dB"):
        db.add("documents", id=d, user_id=U, deleted_at=None)
        db.add("course_chunk_sources", chunk_id="shared1", doc_id=d)
    db.add("course_chunks", id="shared1", doc_id="dB", uploader_id=U,
           visibility="shared", category="lecture_notes")
    db.add("course_chunk_contributors", chunk_id="shared1", user_id=U)

    counts = aw.wipe_account_data(U)

    assert db.rows["course_chunks"] == []
    assert db.rows.get("course_chunk_contributors") == []
    assert counts["course_chunks"] == 1


def test_classmates_shared_chunk_survives_and_orphan_private_rows_go(db):
    db.add("users", id=U)
    db.add("user_settings", user_id=U, share_class_context=True)
    db.add("user_settings", user_id=OTHER, share_class_context=True)
    db.add("documents", id="mine", user_id=U, deleted_at=None)
    db.add("documents", id="theirs", user_id=OTHER, deleted_at=None)
    # Same text uploaded by both: jointly owned, last writer was U.
    db.add("course_chunks", id="joint", doc_id="mine", uploader_id=U,
           visibility="shared", category="lecture_notes")
    for d in ("mine", "theirs"):
        db.add("course_chunk_sources", chunk_id="joint", doc_id=d)
    for u in (U, OTHER):
        db.add("course_chunk_contributors", chunk_id="joint", user_id=u)
    # Private rows naming U that no ledger or doc_id ties to a document.
    db.add("course_chunks", id="orphan1", doc_id="gone", uploader_id=U,
           visibility="private", category="lecture_notes")
    db.add("course_chunks", id="orphan2", doc_id=None, uploader_id=U,
           visibility="private", category=None)
    # Never a student's: the catalog partition.
    db.add("course_chunks", id="cat1", doc_id=None, uploader_id=U,
           visibility="private", category="catalog")

    counts = aw.wipe_account_data(U)

    assert sorted(r["id"] for r in db.rows["course_chunks"]) == ["cat1", "joint"]
    assert db.rows["course_chunk_contributors"] == [{"chunk_id": "joint", "user_id": OTHER}]
    assert counts["course_chunks"] == 2
    assert counts["course_chunk_contributors"] == 1

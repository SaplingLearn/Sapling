"""#115: course-keyed writes refuse a caller who is not enrolled in the course.

Before this, any signed-in student could upload into another class's course
(pushing chunks into its shared RAG pool), file or move a note under it, open
a tutor session on it, or spend model quota scanning it. Every such write now
goes through `services/academics.py::require_course_enrollment` (enrolled in
ANY term's offering of the abstract course, else the same 404 a missing course
gets), which also returns the offering the write lands in — so the check and
the write agree on the term.

These tests opt OUT of the hermetic `_bypass_course_enrollment` fixture with
the `real_course_enrollment` marker, and model enrollment at the gate's one
read (`academics.enrolled_offering_for_course`) or below it (`table()`).
"""
from __future__ import annotations

import io
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from db import seed_local_rich as seed
from main import app
from services import academics

pytestmark = pytest.mark.real_course_enrollment

client = TestClient(app)
#: For probes that let a stubbed agent blow up once the gate has let them by.
lenient_client = TestClient(app, raise_server_exceptions=False)


def _enrolled(offering: str | None):
    """Patch the gate's single enrollment read: an offering id, or None."""
    return patch("services.academics.enrolled_offering_for_course", return_value=offering)


def _assert_not_enrolled_404(r):
    assert r.status_code == 404, r.text
    # The route's 404 detail may carry a request-id suffix.
    assert str(r.json()["detail"]).startswith(academics.COURSE_NOT_ENROLLED_DETAIL)


# ── a fake PostgREST over rows shaped like the rich seed ─────────────────────


class _Db:
    """Just enough of `table()` for the gate and `graph_service.add_course`:
    the enrollments read with its `course_offerings!inner(...)` embed and
    embedded filter resolved the way PostgREST resolves them."""

    def __init__(self, offerings, enrollments, terms):
        self.offerings = {o["id"]: dict(o) for o in offerings}
        self.enrollments = [dict(e) for e in enrollments]
        self.terms = {t["id"]: dict(t) for t in terms}
        self.courses = {o["course_id"] for o in offerings}

    @staticmethod
    def _eq(filters, key):
        v = (filters or {}).get(key)
        return v[3:] if v and v.startswith("eq.") else None

    def table(self, name):
        db = self
        t = MagicMock()

        def select(columns="*", filters=None, order=None, limit=None, **_kw):
            if name == "enrollments":
                uid = db._eq(filters, "user_id")
                course = db._eq(filters, "course_offerings.course_id")
                out = []
                for e in db.enrollments:
                    off = db.offerings.get(e["offering_id"])
                    if e["user_id"] != uid or off is None:
                        continue
                    if course is not None and off["course_id"] != course:
                        continue  # !inner drops the parent on a non-match
                    term = db.terms.get(off["term_id"]) or {}
                    out.append({
                        "offering_id": e["offering_id"],
                        "course_offerings": {
                            "course_id": off["course_id"], "term_id": off["term_id"],
                            "terms": {"sort_key": term.get("sort_key")},
                        },
                    })
                return out[:limit] if limit else out
            if name == "course_offerings":
                cid, tid = db._eq(filters, "course_id"), db._eq(filters, "term_id")
                return [{"id": o["id"]} for o in db.offerings.values()
                        if (cid is None or o["course_id"] == cid)
                        and (tid is None or o["term_id"] == tid)]
            if name == "courses":
                cid = db._eq(filters, "id")
                return [{"id": cid}] if cid in db.courses else []
            return []

        def insert(row, **_kw):
            if name == "enrollments":
                db.enrollments.append(dict(row))
            elif name == "course_offerings":
                db.offerings[row["id"]] = dict(row)
            return [row]

        t.select.side_effect = select
        t.insert.side_effect = insert
        return t


_SEED_TERMS = [
    {"id": seed.TERM_FALL_2025, "sort_key": 20253},
    {"id": seed.TERM_SPRING_2026, "sort_key": 20261},
    {"id": seed.TERM_FALL_2026, "sort_key": 20263},
]


def _seed_db() -> _Db:
    return _Db(
        offerings=[{"id": o[0], "course_id": o[1], "term_id": o[2]} for o in seed._OFFERINGS],
        enrollments=[{"id": e[0], "user_id": e[1], "offering_id": e[2]} for e in seed._ENROLLMENTS],
        terms=_SEED_TERMS,
    )


# ── the CI failure, reproduced with the seed's real ids ──────────────────────


class TestRichSeedDecision:
    """The integration lane's cross-user matrix failed with
    `POST /api/notes course_id expected 404 got 200`. B (rich-user-second) is
    NOT enrolled in A's A-only course (rich-course-bio110) in the seed, and
    the gate says so. But the matrix runs the resource group in path order,
    and `POST /api/graph/{user_id}/courses` — B adding that catalog course to
    their OWN schedule, a legitimate 200 — sorts before `/api/notes` (and
    `/api/learn/...`), so by then B really is enrolled. The gate was right;
    the matrix's case order was wrong."""

    @pytest.fixture
    def db(self):
        db = _seed_db()
        cur = {"id": seed.TERM_FALL_2026}
        with patch("services.academics.table", side_effect=db.table), \
             patch("services.graph_service.table", side_effect=db.table), \
             patch("services.academics.current_term", return_value=cur), \
             patch("services.course_context_service.refresh_course_context"):
            yield db

    def test_b_is_not_enrolled_in_the_a_only_course(self, db):
        assert seed.USER_SECOND == "rich-user-second"
        with pytest.raises(HTTPException) as exc:
            academics.require_course_enrollment(seed.USER_SECOND, seed.COURSE_BIO)
        assert exc.value.status_code == 404

    def test_a_is_enrolled_and_writes_to_their_own_past_term_offering(self, db):
        # A holds bio110 only in fall-2025; the current term is fall-2026.
        assert academics.require_course_enrollment(
            seed.USER_ACTIVE, seed.COURSE_BIO) == seed.OFF_BIO_F25
        # Nothing was minted for the current term.
        assert set(db.offerings) == {o[0] for o in seed._OFFERINGS}

    def test_after_the_add_course_case_b_is_enrolled(self, db):
        from services.graph_service import add_course

        assert add_course(seed.USER_SECOND, seed.COURSE_BIO)["already_existed"] is False
        # The matrix's earlier add-course case made B a real bio110 student,
        # in the current term's (newly created) offering: the gate now passes,
        # and that offering is where B's write lands.
        off = academics.require_course_enrollment(seed.USER_SECOND, seed.COURSE_BIO)
        assert db.offerings[off] == {
            "id": off, "course_id": seed.COURSE_BIO, "term_id": seed.TERM_FALL_2026,
        }


# ── the helper ───────────────────────────────────────────────────────────────


def _rows(*specs):
    """(offering_id, course_id, term_id, sort_key) → embedded enrollment rows."""
    return [{"offering_id": o, "course_offerings": {
        "course_id": c, "term_id": t, "terms": {"sort_key": k}}} for o, c, t, k in specs]


def _table_returning(rows):
    calls: list = []

    def _table(name):
        t = MagicMock()

        def select(columns="*", filters=None, order=None, limit=None, **_kw):
            calls.append({"table": name, "columns": columns, "filters": dict(filters or {}),
                          "order": order, "limit": limit})
            return rows
        t.select.side_effect = select
        return t
    return _table, calls


class TestHelper:
    def test_one_bounded_read_scoped_to_the_caller_and_course(self):
        fake, calls = _table_returning(_rows(("off-1", "c1", "t1", 1)))
        with patch("services.academics.table", side_effect=fake), \
             patch("services.academics.current_term") as cur:
            assert academics.require_course_enrollment("u1", "c1") == "off-1"
        assert len(calls) == 1
        call = calls[0]
        assert call["table"] == "enrollments"
        assert "course_offerings!inner(" in call["columns"]
        assert call["filters"] == {"user_id": "eq.u1", "course_offerings.course_id": "eq.c1"}
        assert call["limit"] == academics._COURSE_ENROLLMENT_SCAN_LIMIT
        cur.assert_not_called()  # one enrollment: no term lookup

    def test_not_enrolled_raises_404(self):
        fake, _ = _table_returning([])
        with patch("services.academics.table", side_effect=fake), \
             pytest.raises(HTTPException) as exc:
            academics.require_course_enrollment("u1", "c-foreign")
        assert exc.value.status_code == 404
        assert exc.value.detail == academics.COURSE_NOT_ENROLLED_DETAIL

    def test_a_row_whose_embed_is_another_course_does_not_count(self):
        """A non-`!inner` embed returns every enrollment with a null (or other)
        offering instead of filtering; that must not read as enrolled."""
        rows = [{"offering_id": "off-z", "course_offerings": None},
                *_rows(("off-y", "c-other", "t1", 1))]
        fake, _ = _table_returning(rows)
        with patch("services.academics.table", side_effect=fake):
            assert academics.is_enrolled_in_course("u1", "c1") is False

    def test_prefers_the_current_term_offering(self):
        fake, _ = _table_returning(_rows(("off-new", "c1", "t-next", 3),
                                         ("off-cur", "c1", "t-cur", 2)))
        with patch("services.academics.table", side_effect=fake), \
             patch("services.academics.current_term", return_value={"id": "t-cur"}):
            assert academics.enrolled_offering_for_course("u1", "c1") == "off-cur"

    def test_else_the_latest_term_offering(self):
        fake, _ = _table_returning(_rows(("off-f25", "c1", "t-f25", 20253),
                                         ("off-s26", "c1", "t-s26", 20261)))
        with patch("services.academics.table", side_effect=fake), \
             patch("services.academics.current_term", return_value={"id": "t-f26"}):
            assert academics.enrolled_offering_for_course("u1", "c1") == "off-s26"

    @pytest.mark.parametrize("uid,cid", [("", "c1"), ("u1", ""), (None, None)])
    def test_blank_ids_are_not_enrolled_and_read_nothing(self, uid, cid):
        with patch("services.academics.table") as t:
            assert academics.is_enrolled_in_course(uid, cid) is False
        t.assert_not_called()

    def test_a_failed_read_raises_not_a_silent_no(self):
        t = MagicMock()
        t.select.side_effect = RuntimeError("postgrest down")
        with patch("services.academics.table", return_value=t), pytest.raises(RuntimeError):
            academics.require_course_enrollment("u1", "c1")


# ── the routes ───────────────────────────────────────────────────────────────


def _upload(path: str, *, filename="notes.txt", content_type="text/plain", headers=None):
    # An unsupported file type: a caller who passes the enrollment gate gets
    # the NEXT check's 400, which proves the gate ran first and let them by
    # without needing the OCR/agent pipeline.
    return client.post(
        path,
        files={"file": (filename, io.BytesIO(b"hello"), content_type)},
        data={"course_id": "c-target", "user_id": "u1"},
        headers=headers or {},
    )


@pytest.mark.parametrize("path", ["/api/documents/upload/sync", "/api/documents/upload"])
class TestUploadGate:
    def test_not_enrolled_is_404_before_any_work(self, path):
        with _enrolled(None), \
             patch("routes.documents._validate_user", return_value=None), \
             patch("routes.documents._existing_doc_by_request_id", return_value=None), \
             patch("services.academics.resolve_offering") as ro, \
             patch("routes.documents.extract_text_from_file") as ocr:
            r = _upload(path, filename="notes.pdf", content_type="application/pdf")
        _assert_not_enrolled_404(r)
        ro.assert_not_called()  # no offering minted for a course that is not theirs
        ocr.assert_not_called()

    def test_enrolled_reaches_the_next_check(self, path):
        with _enrolled("off-1"), \
             patch("routes.documents._existing_doc_by_request_id", return_value=None), \
             patch("routes.documents._validate_user", return_value=None):
            r = _upload(path)
        assert r.status_code == 400
        assert "Unsupported file type" in r.json()["detail"]

    def test_a_retry_of_a_completed_upload_replays_before_the_gate(self, path):
        """#115 review: the X-Request-ID replay runs BEFORE the gate, so a
        retry of an upload that completed still gets its stored document —
        even after the student dropped the course."""
        stored = {"id": "doc-stored", "user_id": "u1", "offering_id": "off-1",
                  "file_name": "notes.pdf", "category": "other", "summary": None,
                  "concept_notes": [], "created_at": "", "processed_at": ""}
        with _enrolled(None) as gate, \
             patch("routes.documents._validate_user", return_value=None), \
             patch("routes.documents._existing_doc_by_request_id", return_value=stored), \
             patch("routes.documents.extract_text_from_file") as ocr:
            r = _upload(path, filename="notes.pdf", content_type="application/pdf",
                        headers={"X-Request-ID": "retry-1"})
        assert r.status_code == 200, r.text
        assert "doc-stored" in r.text
        gate.assert_not_called()
        ocr.assert_not_called()


class TestCourseScanGate:
    def test_not_enrolled_is_404_and_no_scan(self):
        with _enrolled(None), \
             patch("routes.documents._validate_user_sync", return_value=None), \
             patch("routes.documents._scan_concepts_for_course") as scan:
            r = client.post("/api/documents/course/c-foreign/scan-concepts",
                            json={"user_id": "u1"})
        _assert_not_enrolled_404(r)
        scan.assert_not_called()

    def test_enrolled_scans(self):
        shape = {"concepts": ["X"], "added": 1, "existing": 0}
        with _enrolled("off-1"), \
             patch("routes.documents._validate_user_sync", return_value=None), \
             patch("routes.documents._scan_concepts_for_course", return_value=shape) as scan:
            r = client.post("/api/documents/course/c1/scan-concepts",
                            json={"user_id": "u1"})
        assert r.status_code == 200
        assert r.json() == shape
        scan.assert_called_once_with("u1", "c1")


class TestDocumentScanGate:
    """`/doc/{id}/scan-concepts` scans the course of the document's offering:
    the caller owns the document, but must still be enrolled in that course."""

    def _doc_table(self):
        t = MagicMock()
        t.select.return_value = [{"id": "d1", "user_id": "u1", "offering_id": "off-old",
                                  "file_name": "a.pdf", "summary": None, "concept_notes": []}]
        return t

    def test_dropped_course_is_404_and_no_scan(self):
        with _enrolled(None) as gate, \
             patch("routes.documents._validate_user_sync", return_value=None), \
             patch("routes.documents.table", return_value=self._doc_table()), \
             patch("routes.documents.offering_course_id", return_value="c-dropped"), \
             patch("routes.documents._scan_concepts_for_course") as scan:
            r = client.post("/api/documents/doc/d1/scan-concepts", json={"user_id": "u1"})
        _assert_not_enrolled_404(r)
        gate.assert_called_once_with("u1", "c-dropped")
        scan.assert_not_called()

    def test_enrolled_scans(self):
        shape = {"concepts": [], "added": 0, "existing": 0}
        with _enrolled("off-old"), \
             patch("routes.documents._validate_user_sync", return_value=None), \
             patch("routes.documents.table", return_value=self._doc_table()), \
             patch("routes.documents.offering_course_id", return_value="c1"), \
             patch("routes.documents._scan_concepts_for_course", return_value=shape) as scan:
            r = client.post("/api/documents/doc/d1/scan-concepts", json={"user_id": "u1"})
        assert r.status_code == 200
        assert scan.call_args.args[:2] == ("u1", "c1")


async def _fake_create(user_id, offering_id, title, body, tags):
    return {"id": "n1", "user_id": user_id, "offering_id": offering_id,
            "title": title, "body": body, "tags": tags,
            "last_summary": None, "last_summary_at": None,
            "created_at": "", "updated_at": ""}


class TestNoteCreateGate:
    def test_not_enrolled_is_404_and_nothing_written(self):
        with _enrolled(None), \
             patch("services.academics.resolve_offering") as ro, \
             patch("routes.notes.create_note") as create:
            r = client.post("/api/notes", json={"user_id": "u1", "course_id": "c-foreign",
                                                "title": "T", "body": "B"})
        _assert_not_enrolled_404(r)
        ro.assert_not_called()
        create.assert_not_called()

    def test_enrolled_creates_on_the_offering_the_gate_returns(self):
        with _enrolled("off-mine"), \
             patch("routes.notes.create_note", side_effect=_fake_create) as create, \
             patch("routes.notes.award_xp_safe"):
            r = client.post("/api/notes", json={"user_id": "u1", "course_id": "c1",
                                                "title": "T", "body": "B"})
        assert r.status_code == 200
        assert r.json()["id"] == "n1"
        assert create.call_args.kwargs["offering_id"] == "off-mine"


class TestNoteMoveGate:
    """PATCH /api/notes/{id} with a course_id re-homes the note: the same gate
    as create, before any offering is resolved or the row is touched."""

    def test_moving_into_a_foreign_course_is_404_and_nothing_written(self):
        with _enrolled(None), \
             patch("services.academics.resolve_offering") as ro, \
             patch("routes.notes.update_note") as update:
            r = client.patch("/api/notes/n1", json={"user_id": "u1", "course_id": "c-foreign"})
        _assert_not_enrolled_404(r)
        ro.assert_not_called()
        update.assert_not_called()

    def test_moving_into_an_enrolled_course_uses_its_offering(self):
        with _enrolled("off-mine") as gate, \
             patch("routes.notes.update_note", new=AsyncMock(return_value={"id": "n1"})) as update:
            r = client.patch("/api/notes/n1", json={"user_id": "u1", "course_id": "c1"})
        assert r.status_code == 200
        gate.assert_called_once_with("u1", "c1")
        assert update.call_args.kwargs["patch"] == {"offering_id": "off-mine"}

    def test_an_edit_without_course_id_does_not_consult_the_gate(self):
        with _enrolled(None) as gate, \
             patch("routes.notes.update_note", new=AsyncMock(return_value={"id": "n1"})):
            r = client.patch("/api/notes/n1", json={"user_id": "u1", "title": "New"})
        assert r.status_code == 200
        gate.assert_not_called()


@pytest.mark.parametrize("path", ["/api/learn/start-session", "/api/learn/start-session/stream"])
class TestStartSessionGate:
    def test_a_foreign_course_id_is_404_before_any_agent_setup(self, path):
        with _enrolled(None), \
             patch("routes.learn.resolve_offering") as ro, \
             patch("routes.learn._prepare_chat_run") as prep:
            r = client.post(path, json={"user_id": "u1", "topic": "Cells",
                                        "course_id": "c-foreign"})
        _assert_not_enrolled_404(r)
        ro.assert_not_called()
        prep.assert_not_called()

    def test_an_enrolled_course_id_reaches_the_agent(self, path):
        with _enrolled("off-mine") as gate, \
             patch("routes.learn._prepare_chat_run",
                   side_effect=RuntimeError("reached the agent")) as prep:
            lenient_client.post(path, json={"user_id": "u1", "topic": "Cells",
                                            "course_id": "c1"})
        gate.assert_called_with("u1", "c1")
        assert prep.called

    def test_a_topic_only_session_is_not_gated(self, path):
        with _enrolled(None) as gate, \
             patch("routes.learn._get_course_id_for_topic", return_value="c-topic"), \
             patch("routes.learn.resolve_offering", return_value="off-cur") as ro, \
             patch("routes.learn._prepare_chat_run",
                   side_effect=RuntimeError("reached the agent")) as prep:
            lenient_client.post(path, json={"user_id": "u1", "topic": "Cells"})
        gate.assert_not_called()
        ro.assert_called_with("c-topic", create=True)
        assert prep.called

"""Route tests for /api/gradebook/* on the enrollment-keyed (academics-split)
schema.

The gradebook resolves the abstract ``course_id`` + an optional ``semester``
(term label) to the user's **enrollment** via ``services.academics``, then keys
``gradebook_categories`` / ``assignments`` on ``enrollment_id``.

Both ``routes.gradebook.table`` and ``services.academics.table`` are patched with
one shared, **filter-aware** fake so the resolver's multi-table queries (terms,
course_offerings, enrollments) and the route's gradebook queries all resolve
against the same canned dataset. Mocks live only at the ``table()`` boundary;
the real Pydantic + service + resolver code runs.
"""
import copy
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from main import app


client = TestClient(app)


# ── Filter-aware fake table() ────────────────────────────────────────────────

class _FakeTable:
    """A `table(name)` stand-in that filters canned rows by the PostgREST
    `eq.`/`in.()` filters the resolver + routes pass, so the same table can be
    queried with different filters within one request and return the right rows.
    Records insert/update/delete for assertions; echoes payloads back like the
    real REST representation.
    """

    def __init__(self, name, rows, recorder):
        self.name = name
        self.rows = rows
        self.recorder = recorder

    def _match(self, row, filters):
        for col, expr in (filters or {}).items():
            if col in ("or",):  # unsupported here; treat as no-op pass
                continue
            if expr.startswith("eq."):
                if str(row.get(col)) != expr[3:]:
                    return False
            elif expr.startswith("in."):
                inner = expr[len("in.("):-1]
                wanted = set(inner.split(",")) if inner else set()
                if str(row.get(col)) not in wanted:
                    return False
        return True

    def select(self, _cols="*", filters=None, order=None, limit=None):
        out = [dict(r) for r in self.rows if self._match(r, filters)]
        if limit is not None:
            out = out[:limit]
        return out

    def insert(self, data):
        # Snapshot the payload at write time — the route may mutate the returned
        # row in place (e.g. decrypt points back for the client response), and we
        # want the recorder to reflect what was actually stored (ciphertext).
        self.recorder.append((self.name, "insert", copy.deepcopy(data)))
        return [data] if isinstance(data, dict) else data

    def update(self, data, filters=None):
        self.recorder.append((self.name, "update", data))
        return [data]

    def delete(self, filters=None):
        self.recorder.append((self.name, "delete", filters))
        return []


def _factory(rows_by_table, recorder):
    def make(name):
        return _FakeTable(name, rows_by_table.get(name, []), recorder)
    return make


def _patched(rows_by_table, recorder=None):
    """Patch the table() boundary in both the route and the resolver."""
    recorder = recorder if recorder is not None else []
    f = _factory(rows_by_table, recorder)
    return (
        patch("routes.gradebook.require_self", return_value=None),
        patch("routes.gradebook.table", side_effect=f),
        patch("services.academics.table", side_effect=f),
        recorder,
    )


# A canonical current-term dataset: user u1 enrolled in CS161 (offering off1,
# term spring-2026 which contains today's seed date). Today (2026-06-24) sits in
# summer-2026, but the resolver falls back to the single offering when no
# semester is given, so off1 still resolves.
def _base_rows():
    return {
        "terms": [
            {"id": "spring-2026", "label": "Spring 2026", "start_date": "2026-01-05",
             "end_date": "2026-05-17", "sort_key": 20261},
            {"id": "fall-2026", "label": "Fall 2026", "start_date": "2026-08-24",
             "end_date": "2027-01-03", "sort_key": 20263},
        ],
        "courses": [
            {"id": "cs161", "course_code": "CS 161", "course_name": "Intro CS", "credits": 3},
        ],
        "course_offerings": [
            {"id": "off1", "course_id": "cs161", "term_id": "spring-2026"},
        ],
        "enrollments": [
            {"id": "enr1", "user_id": "u1", "offering_id": "off1", "letter_scale": None,
             "curve_mode": "raw", "curve_avg_target": None, "curve_sd_delta": None,
             "syllabus_doc_id": None},
        ],
    }


# ── GET /summary ─────────────────────────────────────────────────────────────

class TestSummary:
    def test_returns_courses_with_computed_grades_and_gpa(self):
        rows = _base_rows()
        rows["gradebook_categories"] = [
            {"id": "exams", "enrollment_id": "enr1", "name": "Exams", "weight": 100,
             "sort_order": 0, "drop_lowest": 0},
        ]
        rows["assignments"] = [
            {"id": "a1", "enrollment_id": "enr1", "title": "Midterm", "category_id": "exams",
             "points_possible": 90.0, "points_earned": None, "due_date": None,
             "assignment_type": "exam", "notes": None, "source": "manual",
             "curve_class_mean": None, "curve_class_sd": None},
            {"id": "a2", "enrollment_id": "enr1", "title": "Final", "category_id": "exams",
             "points_possible": 100.0, "points_earned": 90.0, "due_date": None,
             "assignment_type": "exam", "notes": None, "source": "manual",
             "curve_class_mean": None, "curve_class_sd": None},
        ]
        rs, t1, t2, _ = _patched(rows)
        with rs, t1, t2:
            r = client.get("/api/gradebook/summary",
                           params={"user_id": "u1", "semester": "Spring 2026"})
        assert r.status_code == 200
        body = r.json()
        assert len(body["courses"]) == 1
        c = body["courses"][0]
        assert c["course_code"] == "CS 161"
        # decrypt_numeric passes plain floats through; 90/100 graded = 90%.
        assert c["percent"] == pytest.approx(90.0)
        assert c["letter"] == "A-"
        assert c["graded_count"] == 1
        assert c["total_count"] == 2
        # term GPA: A- (3.7), single 3-credit course → 3.7
        assert body["gpa"] == pytest.approx(3.7)

    def test_unknown_semester_returns_empty(self):
        rs, t1, t2, _ = _patched(_base_rows())
        with rs, t1, t2:
            r = client.get("/api/gradebook/summary",
                           params={"user_id": "u1", "semester": "Winter 1999"})
        assert r.status_code == 200
        assert r.json()["courses"] == []


# ── GET /courses/{course_id} ─────────────────────────────────────────────────

class TestCourseDetail:
    def test_returns_categories_assignments_and_overall(self):
        rows = _base_rows()
        rows["gradebook_categories"] = [
            {"id": "exams", "enrollment_id": "enr1", "name": "Exams", "weight": 60,
             "sort_order": 0, "drop_lowest": 0},
            {"id": "psets", "enrollment_id": "enr1", "name": "P-Sets", "weight": 40,
             "sort_order": 1, "drop_lowest": 0},
        ]
        rows["assignments"] = [
            {"id": "a1", "enrollment_id": "enr1", "title": "Midterm", "category_id": "exams",
             "points_possible": 100.0, "points_earned": 80.0, "due_date": "2026-03-10",
             "assignment_type": "exam", "notes": None, "source": "manual",
             "curve_class_mean": None, "curve_class_sd": None},
            {"id": "a2", "enrollment_id": "enr1", "title": "P-Set 1", "category_id": "psets",
             "points_possible": 100.0, "points_earned": 100.0, "due_date": "2026-02-01",
             "assignment_type": "homework", "notes": None, "source": "manual",
             "curve_class_mean": None, "curve_class_sd": None},
        ]
        rs, t1, t2, _ = _patched(rows)
        with rs, t1, t2:
            r = client.get("/api/gradebook/courses/cs161", params={"user_id": "u1"})
        assert r.status_code == 200
        body = r.json()
        assert body["course_code"] == "CS 161"
        # 0.8*60 + 1.0*40 = 88
        assert body["percent"] == pytest.approx(88.0)
        assert body["letter"] == "B+"
        assert {c["name"] for c in body["categories"]} == {"Exams", "P-Sets"}
        assert len(body["assignments"]) == 2
        assert body["curve_mode"] == "raw"

    def test_curved_course_applies_bell_curve(self):
        rows = _base_rows()
        rows["enrollments"] = [
            {"id": "enr1", "user_id": "u1", "offering_id": "off1", "letter_scale": None,
             "curve_mode": "curved", "curve_avg_target": 80.0, "curve_sd_delta": 0.0,
             "syllabus_doc_id": None},
        ]
        rows["gradebook_categories"] = [
            {"id": "exams", "enrollment_id": "enr1", "name": "Exams", "weight": 100,
             "sort_order": 0, "drop_lowest": 0},
        ]
        rows["assignments"] = [
            {"id": "a1", "enrollment_id": "enr1", "title": "Exam", "category_id": "exams",
             "points_possible": 100.0, "points_earned": 70.0, "due_date": None,
             "assignment_type": "exam", "notes": None, "source": "manual",
             "curve_class_mean": 60.0, "curve_class_sd": 10.0},
        ]
        rs, t1, t2, _ = _patched(rows)
        with rs, t1, t2:
            r = client.get("/api/gradebook/courses/cs161", params={"user_id": "u1"})
        assert r.status_code == 200
        # raw 70 → curved 80 + (70-60)*(10/10) = 90
        assert r.json()["percent"] == pytest.approx(90.0)

    def test_404_when_user_not_enrolled(self):
        rows = _base_rows()
        rows["enrollments"] = []
        rs, t1, t2, _ = _patched(rows)
        with rs, t1, t2:
            r = client.get("/api/gradebook/courses/nope", params={"user_id": "u1"})
        assert r.status_code == 404


# ── Categories CRUD ──────────────────────────────────────────────────────────

class TestCategories:
    def test_create_one_category(self):
        rs, t1, t2, rec = _patched(_base_rows())
        with rs, t1, t2:
            r = client.post(
                "/api/gradebook/courses/cs161/categories",
                json={"user_id": "u1", "name": "Exams", "weight": 40, "drop_lowest": 1},
            )
        assert r.status_code == 200
        cat = r.json()["category"]
        assert cat["name"] == "Exams"
        assert cat["enrollment_id"] == "enr1"
        assert cat["drop_lowest"] == 1

    def test_create_rejects_unknown_course(self):
        rows = _base_rows()
        rows["enrollments"] = []
        rs, t1, t2, _ = _patched(rows)
        with rs, t1, t2:
            r = client.post(
                "/api/gradebook/courses/cs999/categories",
                json={"user_id": "u1", "name": "Exams", "weight": 40},
            )
        assert r.status_code == 404

    def test_bulk_update_validates_weight_total(self):
        body = {
            "user_id": "u1",
            "categories": [
                {"id": "exams", "name": "Exams", "weight": 60, "sort_order": 0},
                {"id": "psets", "name": "P-Sets", "weight": 30, "sort_order": 1},
            ],
        }
        rs, t1, t2, _ = _patched(_base_rows())
        with rs, t1, t2:
            r = client.patch("/api/gradebook/courses/cs161/categories", json=body)
        assert r.status_code == 400
        assert "100" in r.json()["detail"].lower() or "weight" in r.json()["detail"].lower()

    def test_bulk_update_accepts_total_100(self):
        body = {
            "user_id": "u1",
            "categories": [
                {"id": "exams", "name": "Exams", "weight": 60, "sort_order": 0, "drop_lowest": 2},
                {"id": "psets", "name": "P-Sets", "weight": 40, "sort_order": 1},
            ],
        }
        rs, t1, t2, rec = _patched(_base_rows())
        with rs, t1, t2:
            r = client.patch("/api/gradebook/courses/cs161/categories", json=body)
        assert r.status_code == 200
        assert len(r.json()["categories"]) == 2
        # drop_lowest carried through the update payload
        updates = [d for (n, op, d) in rec if n == "gradebook_categories" and op == "update"]
        assert any(u.get("drop_lowest") == 2 for u in updates)

    def test_delete_category(self):
        rows = _base_rows()
        rows["gradebook_categories"] = [
            {"id": "exams", "enrollment_id": "enr1", "name": "Exams", "weight": 100,
             "sort_order": 0, "drop_lowest": 0},
        ]
        rs, t1, t2, _ = _patched(rows)
        with rs, t1, t2:
            r = client.delete("/api/gradebook/categories/exams", params={"user_id": "u1"})
        assert r.status_code == 200

    def test_delete_404_when_not_owner(self):
        rows = _base_rows()
        rows["gradebook_categories"] = [
            {"id": "exams", "enrollment_id": "other-enr", "name": "Exams", "weight": 100,
             "sort_order": 0, "drop_lowest": 0},
        ]
        rs, t1, t2, _ = _patched(rows)
        with rs, t1, t2:
            r = client.delete("/api/gradebook/categories/exams", params={"user_id": "u1"})
        assert r.status_code == 404


# ── Assignments CRUD ─────────────────────────────────────────────────────────

class TestAssignments:
    def test_create_assignment_minimal(self):
        rs, t1, t2, rec = _patched(_base_rows())
        with rs, t1, t2:
            r = client.post("/api/gradebook/assignments",
                            json={"user_id": "u1", "course_id": "cs161", "title": "Midterm 1"})
        assert r.status_code == 200
        a = r.json()["assignment"]
        assert a["title"] == "Midterm 1"
        assert a["source"] == "manual"
        assert a["enrollment_id"] == "enr1"

    def test_create_encrypts_points_and_returns_plaintext(self):
        rs, t1, t2, rec = _patched(_base_rows())
        with rs, t1, t2:
            r = client.post("/api/gradebook/assignments",
                            json={"user_id": "u1", "course_id": "cs161", "title": "Q",
                                  "points_possible": 100, "points_earned": 88})
        assert r.status_code == 200
        a = r.json()["assignment"]
        # Returned plaintext to the client...
        assert a["points_earned"] == pytest.approx(88.0)
        # ...but the stored insert payload was ciphertext (not the raw float).
        inserts = [d for (n, op, d) in rec if n == "assignments" and op == "insert"]
        assert inserts and inserts[0]["points_earned"] != 88
        assert isinstance(inserts[0]["points_earned"], str)

    def test_create_rejects_unknown_course(self):
        rows = _base_rows()
        rows["enrollments"] = []
        rs, t1, t2, _ = _patched(rows)
        with rs, t1, t2:
            r = client.post("/api/gradebook/assignments",
                            json={"user_id": "u1", "course_id": "cs999", "title": "X"})
        assert r.status_code == 404

    def test_create_rejects_zero_points_possible(self):
        rs, t1, t2, _ = _patched(_base_rows())
        with rs, t1, t2:
            r = client.post("/api/gradebook/assignments",
                            json={"user_id": "u1", "course_id": "cs161", "title": "X",
                                  "points_possible": 0})
        assert r.status_code == 422  # Pydantic gt=0

    def test_create_rejects_bad_assignment_type(self):
        rs, t1, t2, _ = _patched(_base_rows())
        with rs, t1, t2:
            r = client.post("/api/gradebook/assignments",
                            json={"user_id": "u1", "course_id": "cs161", "title": "X",
                                  "assignment_type": "midterm"})  # not in enum
        assert r.status_code == 422

    def test_update_grade_inline(self):
        rows = _base_rows()
        rows["assignments"] = [
            {"id": "a1", "enrollment_id": "enr1", "category_id": None},
        ]
        rs, t1, t2, _ = _patched(rows)
        with rs, t1, t2:
            r = client.patch("/api/gradebook/assignments/a1",
                             json={"user_id": "u1", "points_earned": 87})
        assert r.status_code == 200

    def test_update_404_when_not_owner(self):
        rows = _base_rows()
        rows["assignments"] = [
            {"id": "a1", "enrollment_id": "other-enr", "category_id": None},
        ]
        rs, t1, t2, _ = _patched(rows)
        with rs, t1, t2:
            r = client.patch("/api/gradebook/assignments/a1",
                             json={"user_id": "u1", "points_earned": 87})
        assert r.status_code == 404

    def test_delete_assignment(self):
        rows = _base_rows()
        rows["assignments"] = [{"id": "a1", "enrollment_id": "enr1", "category_id": None}]
        rs, t1, t2, _ = _patched(rows)
        with rs, t1, t2:
            r = client.delete("/api/gradebook/assignments/a1", params={"user_id": "u1"})
        assert r.status_code == 200


# ── PATCH /courses/{course_id}/scale ─────────────────────────────────────────

class TestLetterScale:
    def test_set_custom_scale(self):
        body = {"user_id": "u1", "scale": [
            {"min": 90, "letter": "A"}, {"min": 80, "letter": "B"}, {"min": 0, "letter": "F"},
        ]}
        rs, t1, t2, rec = _patched(_base_rows())
        with rs, t1, t2:
            r = client.patch("/api/gradebook/courses/cs161/scale", json=body)
        assert r.status_code == 200
        updates = [d for (n, op, d) in rec if n == "enrollments" and op == "update"]
        assert updates and updates[0]["letter_scale"][0]["letter"] == "A"

    def test_clear_scale_with_null(self):
        rs, t1, t2, _ = _patched(_base_rows())
        with rs, t1, t2:
            r = client.patch("/api/gradebook/courses/cs161/scale",
                             json={"user_id": "u1", "scale": None})
        assert r.status_code == 200

    def test_rejects_non_monotonic_scale(self):
        body = {"user_id": "u1", "scale": [
            {"min": 80, "letter": "A"}, {"min": 90, "letter": "B"},
        ]}
        rs, t1, t2, _ = _patched(_base_rows())
        with rs, t1, t2:
            r = client.patch("/api/gradebook/courses/cs161/scale", json=body)
        assert r.status_code == 400


# ── PATCH /courses/{course_id}/curve ─────────────────────────────────────────

class TestCurve:
    def test_set_curve_writes_enrollment_fields(self):
        body = {"user_id": "u1", "curve_mode": "curved",
                "curve_avg_target": 82.5, "curve_sd_delta": -3.0}
        rs, t1, t2, rec = _patched(_base_rows())
        with rs, t1, t2:
            r = client.patch("/api/gradebook/courses/cs161/curve", json=body)
        assert r.status_code == 200
        updates = [d for (n, op, d) in rec if n == "enrollments" and op == "update"]
        assert updates and updates[0]["curve_mode"] == "curved"
        assert updates[0]["curve_avg_target"] == 82.5
        assert updates[0]["curve_sd_delta"] == -3.0

    def test_set_curve_404_when_not_enrolled(self):
        rows = _base_rows()
        rows["enrollments"] = []
        rs, t1, t2, _ = _patched(rows)
        with rs, t1, t2:
            r = client.patch("/api/gradebook/courses/cs161/curve",
                             json={"user_id": "u1", "curve_mode": "raw"})
        assert r.status_code == 404

    def test_rejects_bad_curve_mode(self):
        rs, t1, t2, _ = _patched(_base_rows())
        with rs, t1, t2:
            r = client.patch("/api/gradebook/courses/cs161/curve",
                             json={"user_id": "u1", "curve_mode": "wild"})
        assert r.status_code == 422


# ── GET /gpa (cumulative, credit-weighted) ───────────────────────────────────

class TestGpa:
    def _two_course_rows(self):
        """u1 in CS161 (3cr, 90% → A- → 3.7) and MATH200 (4cr, 80% → B- → 2.7)."""
        rows = {
            "terms": [
                {"id": "spring-2026", "label": "Spring 2026", "start_date": "2026-01-05",
                 "end_date": "2026-05-17", "sort_key": 20261},
            ],
            "courses": [
                {"id": "cs161", "course_code": "CS 161", "course_name": "Intro CS", "credits": 3},
                {"id": "math200", "course_code": "MATH 200", "course_name": "Calc", "credits": 4},
            ],
            "course_offerings": [
                {"id": "off1", "course_id": "cs161", "term_id": "spring-2026"},
                {"id": "off2", "course_id": "math200", "term_id": "spring-2026"},
            ],
            "enrollments": [
                {"id": "enr1", "user_id": "u1", "offering_id": "off1", "letter_scale": None,
                 "curve_mode": "raw", "curve_avg_target": None, "curve_sd_delta": None,
                 "syllabus_doc_id": None},
                {"id": "enr2", "user_id": "u1", "offering_id": "off2", "letter_scale": None,
                 "curve_mode": "raw", "curve_avg_target": None, "curve_sd_delta": None,
                 "syllabus_doc_id": None},
            ],
            "gradebook_categories": [
                {"id": "c1", "enrollment_id": "enr1", "name": "All", "weight": 100,
                 "sort_order": 0, "drop_lowest": 0},
                {"id": "c2", "enrollment_id": "enr2", "name": "All", "weight": 100,
                 "sort_order": 0, "drop_lowest": 0},
            ],
            "assignments": [
                {"id": "a1", "enrollment_id": "enr1", "title": "X", "category_id": "c1",
                 "points_possible": 100.0, "points_earned": 90.0, "due_date": None,
                 "assignment_type": "exam", "notes": None, "source": "manual",
                 "curve_class_mean": None, "curve_class_sd": None},
                {"id": "a2", "enrollment_id": "enr2", "title": "Y", "category_id": "c2",
                 "points_possible": 100.0, "points_earned": 80.0, "due_date": None,
                 "assignment_type": "exam", "notes": None, "source": "manual",
                 "curve_class_mean": None, "curve_class_sd": None},
            ],
        }
        return rows

    def test_cumulative_gpa_is_credit_weighted(self):
        rs, t1, t2, _ = _patched(self._two_course_rows())
        with rs, t1, t2:
            r = client.get("/api/gradebook/gpa", params={"user_id": "u1"})
        assert r.status_code == 200
        body = r.json()
        assert body["scope"] == "cumulative"
        # (3.7*3 + 2.7*4) / 7 = 3.1285714...
        assert body["gpa"] == pytest.approx(3.1285714, rel=1e-4)
        assert len(body["courses"]) == 2

    def test_semester_gpa_scopes_to_term(self):
        rs, t1, t2, _ = _patched(self._two_course_rows())
        with rs, t1, t2:
            r = client.get("/api/gradebook/gpa",
                           params={"user_id": "u1", "semester": "Spring 2026"})
        assert r.status_code == 200
        body = r.json()
        assert body["scope"] == "semester"
        assert body["gpa"] == pytest.approx(3.1285714, rel=1e-4)


# ── POST /syllabus/apply ─────────────────────────────────────────────────────

class TestSyllabusApply:
    def test_replaces_categories_and_inserts_assignments(self):
        rows = _base_rows()
        rows["documents"] = [{"id": "doc1", "user_id": "u1"}]
        rows["gradebook_categories"] = []
        rows["assignments"] = []
        body = {
            "user_id": "u1", "course_id": "cs161", "doc_id": "doc1",
            "categories": [
                {"name": "Exams", "weight": 60, "sort_order": 0},
                {"name": "P-Sets", "weight": 40, "sort_order": 1},
            ],
            "assignments": [
                {"title": "Midterm 1", "due_date": "2026-03-10",
                 "assignment_type": "exam", "notes": None},
                {"title": "P-Set 1", "due_date": "2026-02-01",
                 "assignment_type": "homework", "notes": None},
            ],
        }
        rs, t1, t2, rec = _patched(rows)
        with rs, t1, t2:
            r = client.post("/api/gradebook/syllabus/apply", json=body)
        assert r.status_code == 200
        assert "course" in r.json()
        # categories wiped + reinserted keyed on enrollment_id
        cat_inserts = [d for (n, op, d) in rec if n == "gradebook_categories" and op == "insert"]
        assert cat_inserts and all(c["enrollment_id"] == "enr1" for c in cat_inserts[0])
        # syllabus_doc_id stamped on the enrollment
        enr_updates = [d for (n, op, d) in rec if n == "enrollments" and op == "update"]
        assert any(u.get("syllabus_doc_id") == "doc1" for u in enr_updates)

    def test_rejects_when_weights_dont_sum_to_100(self):
        rows = _base_rows()
        rows["documents"] = [{"id": "doc1", "user_id": "u1"}]
        body = {
            "user_id": "u1", "course_id": "cs161", "doc_id": "doc1",
            "categories": [
                {"name": "Exams", "weight": 60, "sort_order": 0},
                {"name": "P-Sets", "weight": 30, "sort_order": 1},
            ],
            "assignments": [],
        }
        rs, t1, t2, _ = _patched(rows)
        with rs, t1, t2:
            r = client.post("/api/gradebook/syllabus/apply", json=body)
        assert r.status_code == 400

    def test_rejects_unknown_course(self):
        rows = _base_rows()
        rows["enrollments"] = []
        rows["documents"] = [{"id": "doc1", "user_id": "u1"}]
        body = {
            "user_id": "u1", "course_id": "cs999", "doc_id": "doc1",
            "categories": [{"name": "X", "weight": 100, "sort_order": 0}],
            "assignments": [],
        }
        rs, t1, t2, _ = _patched(rows)
        with rs, t1, t2:
            r = client.post("/api/gradebook/syllabus/apply", json=body)
        assert r.status_code == 404

    def test_rejects_doc_owned_by_other_user(self):
        rows = _base_rows()
        rows["documents"] = [{"id": "doc1", "user_id": "other"}]
        body = {
            "user_id": "u1", "course_id": "cs161", "doc_id": "doc1",
            "categories": [{"name": "X", "weight": 100, "sort_order": 0}],
            "assignments": [],
        }
        rs, t1, t2, _ = _patched(rows)
        with rs, t1, t2:
            r = client.post("/api/gradebook/syllabus/apply", json=body)
        assert r.status_code == 403

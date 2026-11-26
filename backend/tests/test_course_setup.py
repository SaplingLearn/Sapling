"""The Tutor's course setup (`/api/learn/setup`, services/course_setup.py;
Tutor redesign, owner decision 2026-11-26), behind the `course_setup` flag.

Unticked concepts the student has not started are recorded in
`course_concept_exclusions` and their nodes deleted; `apply_graph_update`
then never re-creates them (`graph_service._without_excluded`). Driven
against an in-memory PostgREST stand-in that honours `eq.` and `in.` filters,
so "another student's node" and "another course's node" are decided by the
same filters production sends.
"""
from unittest.mock import patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from main import app
from services import course_setup as svc
from services import graph_service
from services.graph_update_model import NewNode

client = TestClient(app, raise_server_exceptions=False)
ME, OTHER = "user_setup_me", "user_setup_other"


def _matches(row: dict, filters: dict | None) -> bool:
    for col, cond in (filters or {}).items():
        value = None if row.get(col) is None else str(row.get(col))
        if cond.startswith("eq."):
            if value != cond[3:]:
                return False
        elif cond.startswith("in.(") and cond.endswith(")"):
            if value not in cond[4:-1].split(","):
                return False
        else:
            raise AssertionError(f"filter {col}={cond} not modelled")
    return True


class FakeDB:
    def __init__(self):
        self.upserts: list = []
        self.rows: dict[str, list[dict]] = {
            "course_concept_exclusions": [],
            "graph_nodes": [
                {"id": "n-arrays", "user_id": ME, "course_id": "cs112", "concept_name": "Arrays"},
                {"id": "n-tries", "user_id": ME, "course_id": "cs112", "concept_name": "  Tries "},
                {"id": "n-heaps", "user_id": ME, "course_id": "cs112", "concept_name": "Heaps"},
                {"id": "n-other-course", "user_id": ME, "course_id": "ma123", "concept_name": "Limits"},
                {"id": "n-theirs", "user_id": OTHER, "course_id": "cs112", "concept_name": "Graphs"},
            ],
            # Heaps has evidence: the student started it.
            "node_mastery_events": [{"id": "e1", "node_id": "n-heaps"}],
        }

    def table(self, name):
        db = self

        class _T:
            def select(self, columns="*", filters=None, **_):
                return [dict(r) for r in db.rows[name] if _matches(r, filters)]

            def upsert(self, data, on_conflict="id", *, ignore_duplicates=False, **_):
                db.upserts.append((name, on_conflict, ignore_duplicates))
                rows = data if isinstance(data, list) else [data]
                keys = on_conflict.split(",")
                for row in rows:
                    if not any(all(r.get(k) == row.get(k) for k in keys) for r in db.rows[name]):
                        db.rows[name].append(dict(row))
                return []

        return _T()


@pytest.fixture
def db(monkeypatch):
    fake = FakeDB()
    monkeypatch.setattr(svc, "table", fake.table)
    deleted: list = []
    monkeypatch.setattr(graph_service, "delete_node", lambda uid, nid: deleted.append((uid, nid)) or {"deleted": True})
    fake.deleted = deleted
    return fake


def test_unticked_unstarted_concepts_are_recorded_then_deleted(db):
    out = svc.exclude_concepts(ME, "cs112", ["n-arrays", "n-tries", "n-heaps", "n-other-course", "n-theirs", "n-arrays"])
    assert out == {"removed": ["n-arrays", "n-tries"], "kept": ["n-heaps"]}
    # The record keys on the graph's normalized name, so a later upload of
    # "arrays" or "Tries" is the same concept.
    assert sorted(r["concept_key"] for r in db.rows["course_concept_exclusions"]) == ["arrays", "tries"]
    assert {(r["user_id"], r["course_id"]) for r in db.rows["course_concept_exclusions"]} == {(ME, "cs112")}
    assert db.upserts == [("course_concept_exclusions", "user_id,course_id,concept_key", True)]
    # Another course's node and another student's node are not touched.
    assert db.deleted == [(ME, "n-arrays"), (ME, "n-tries")]


def test_nothing_removable_writes_nothing(db):
    assert svc.exclude_concepts(ME, "cs112", ["n-heaps", "n-theirs"]) == {"removed": [], "kept": ["n-heaps"]}
    assert db.upserts == [] and db.deleted == []
    assert svc.exclude_concepts(ME, "cs112", []) == {"removed": [], "kept": []}


def test_excluded_keys_reads_only_this_students_courses(db):
    db.rows["course_concept_exclusions"] += [
        {"user_id": ME, "course_id": "cs112", "concept_key": "arrays"},
        {"user_id": ME, "course_id": "ma123", "concept_key": "limits"},
        {"user_id": OTHER, "course_id": "cs112", "concept_key": "graphs"},
    ]
    assert svc.excluded_keys(ME, ["cs112", None, 7]) == {("cs112", "arrays")}
    assert svc.excluded_keys(ME, []) == set()


def _nodes(*names, course=None):
    return [NewNode(concept_name=n, course_id=course) for n in names]


def test_apply_graph_update_drops_an_excluded_concept(monkeypatch):
    monkeypatch.setattr(svc, "course_setup_on", lambda uid: True)
    seen: list = []

    def keys(uid, courses):
        seen.append((uid, sorted(set(courses))))
        return {("cs112", "arrays")}

    monkeypatch.setattr(svc, "excluded_keys", keys)
    kept = graph_service._without_excluded(ME, "cs112", _nodes("ARRAYS ", "Linked lists"))
    assert [n.concept_name for n in kept] == ["Linked lists"]
    assert seen == [(ME, ["cs112"])]
    # No call course: each node's own course decides.
    kept = graph_service._without_excluded(ME, None, _nodes("Arrays", course="ma123") + _nodes("Arrays", course="cs112"))
    assert [n.course_id for n in kept] == ["ma123"]


def test_flag_off_the_batch_is_unchanged_and_nothing_is_read(monkeypatch):
    monkeypatch.setattr(svc, "course_setup_on", lambda uid: False)
    monkeypatch.setattr(svc, "excluded_keys", lambda *a: pytest.fail("read while off"))
    batch = _nodes("Arrays")
    assert graph_service._without_excluded(ME, "cs112", batch) is batch
    assert graph_service._without_excluded(ME, "cs112", []) == []


def test_the_flag_is_the_students_own_and_not_a_loop_flag(monkeypatch):
    from learning.gate import LOOP_FLAGS

    monkeypatch.setenv("SAPLING_FLAG_COURSE_SETUP", "on")
    assert svc.course_setup_on(ME) is True
    assert svc.course_setup_on(None) is False
    # A removed concept stays out whatever the loop's gate says.
    monkeypatch.setenv("SAPLING_FLAG_LEARNING_LOOP", "off")
    assert svc.course_setup_on(ME) is True
    assert svc.COURSE_SETUP_FLAG not in LOOP_FLAGS
    monkeypatch.setenv("SAPLING_FLAG_COURSE_SETUP", "off")
    assert svc.course_setup_on(ME) is False


def _post(**over):
    return client.post("/api/learn/setup/exclude-concepts",
                       json={"user_id": ME, "course_id": "cs112", "node_ids": ["n-arrays"], **over})


def test_the_route_404s_while_off(monkeypatch):
    monkeypatch.setenv("SAPLING_FLAG_COURSE_SETUP", "off")
    with patch("routes.course_setup.exclude_concepts", side_effect=AssertionError("ran while off")):
        assert _post().status_code == 404


def test_the_route_removes_and_answers_what_it_did(monkeypatch):
    monkeypatch.setenv("SAPLING_FLAG_COURSE_SETUP", "on")
    with patch("routes.course_setup.exclude_concepts", return_value={"removed": ["n-arrays"], "kept": []}) as ex:
        r = _post()
    assert r.status_code == 200 and r.json() == {"removed": ["n-arrays"], "kept": []}
    ex.assert_called_once_with(ME, "cs112", ["n-arrays"])
    assert _post(node_ids=[]).status_code == 422
    assert _post(node_ids=["x"] * (svc.MAX_PER_REQUEST + 1)).status_code == 422


def test_the_route_is_the_students_own(monkeypatch):
    monkeypatch.setenv("SAPLING_FLAG_COURSE_SETUP", "on")
    with patch("routes.course_setup.require_self", side_effect=HTTPException(403, "Forbidden")), \
            patch("routes.course_setup.exclude_concepts", side_effect=AssertionError("ran for another student")):
        assert _post().status_code == 403

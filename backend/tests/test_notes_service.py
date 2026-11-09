"""Unit tests for services/notes_service.py.

Pins the encryption boundary (title/body are ciphertext at rest,
plaintext in the return shape) and the CRUD contract used by
routes/notes.py.
"""
from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch

from services.notes_service import (
    create_note,
    delete_note,
    get_note,
    list_notes,
    update_note,
)


def _run(coro):
    return asyncio.run(coro)


class FakeTable:
    """Minimal stand-in for db.connection.table() returning recorded calls."""
    def __init__(self, rows=None):
        self.rows = rows or []
        self.inserted = []
        self.updated = []
        self.deleted = []
        self.select_calls = []
        self.upserts = []  # (rows, kwargs) per upsert() call
        self.delete_returns = []

    def select(self, *args, **kwargs):
        self.select_calls.append((args, kwargs))
        return list(self.rows)

    def insert(self, data):
        self.inserted.append(data)
        return [data]

    def update(self, data, filters):
        self.updated.append((data, filters))
        return [{**self.rows[0], **data} if self.rows else data]

    def upsert(self, data, on_conflict="id", **kwargs):
        self.upserts.append((data, {"on_conflict": on_conflict, **kwargs}))
        return list(data) if isinstance(data, list) else [data]

    def delete(self, filters):
        self.deleted.append(filters)
        return list(self.delete_returns)


def test_create_note_encrypts_title_and_body():
    fake = FakeTable()
    with patch("services.notes_service.table", return_value=fake):
        out = _run(create_note(
            user_id="u1",
            offering_id="off1",
            title="Photosynthesis",
            body="Light reactions happen in the thylakoid",
            tags=["lecture"],
        ))

    assert fake.inserted, "insert was not called"
    row = fake.inserted[0]
    # Title and body must NOT be plaintext in the row written to Supabase.
    assert row["title"] != "Photosynthesis"
    assert row["body"] != "Light reactions happen in the thylakoid"
    # The note keys on the OFFERING, not the abstract course (0025).
    assert row["offering_id"] == "off1"
    assert "course_id" not in row
    # Return shape must hand back plaintext for the caller to render.
    assert out["title"] == "Photosynthesis"
    assert out["body"] == "Light reactions happen in the thylakoid"
    assert out["tags"] == ["lecture"]
    assert out["user_id"] == "u1"
    assert out["offering_id"] == "off1"
    assert isinstance(out["id"], str) and len(out["id"]) > 0


def test_get_note_decrypts_and_enforces_ownership():
    from services.encryption import encrypt
    fake = FakeTable(rows=[{
        "id": "n1",
        "user_id": "u1",
        "offering_id": "off1",
        "title": encrypt("My title"),
        "body": encrypt("My body"),
        "tags": ["a"],
        "last_summary": None,
        "last_summary_at": None,
        "created_at": "2026-05-11T00:00:00Z",
        "updated_at": "2026-05-11T00:00:00Z",
    }])
    with patch("services.notes_service.table", return_value=fake):
        out = _run(get_note(note_id="n1", user_id="u1"))

    assert out["title"] == "My title"
    assert out["body"] == "My body"
    # Caller must filter on both id AND user_id — verifies ownership in the query.
    call_args, call_kwargs = fake.select_calls[0]
    filters = call_kwargs.get("filters", {})
    assert filters.get("id") == "eq.n1"
    assert filters.get("user_id") == "eq.u1"
    # Soft-deleted notes are excluded from reads (0025 deleted_at).
    assert filters.get("deleted_at") == "is.null"


def test_get_note_returns_none_when_missing():
    fake = FakeTable(rows=[])
    with patch("services.notes_service.table", return_value=fake):
        out = _run(get_note(note_id="missing", user_id="u1"))
    assert out is None


def test_update_note_only_encrypts_present_fields():
    from services.encryption import encrypt
    fake = FakeTable(rows=[{
        "id": "n1", "user_id": "u1", "offering_id": "off1",
        "title": encrypt("Old"), "body": encrypt("Old body"),
        "tags": [], "last_summary": None, "last_summary_at": None,
        "created_at": "2026-05-11T00:00:00Z",
        "updated_at": "2026-05-11T00:00:00Z",
    }])
    with patch("services.notes_service.table", return_value=fake):
        out = _run(update_note(
            note_id="n1", user_id="u1",
            patch={"title": "New title"},
        ))
    assert fake.updated, "update was not called"
    data, _filters = fake.updated[0]
    # Body must NOT be in the update payload (we only patched title).
    assert "body" not in data
    # Title must be ciphertext in the update payload.
    assert data["title"] != "New title"
    # updated_at must be stamped.
    assert "updated_at" in data
    # Return shape: plaintext title comes back.
    assert out["title"] == "New title"


def test_list_notes_filters_by_user_and_optional_offering():
    fake = FakeTable(rows=[])
    with patch("services.notes_service.table", return_value=fake):
        _run(list_notes(user_id="u1", offering_id="off1"))
    args, kwargs = fake.select_calls[0]
    filters = kwargs.get("filters", {})
    assert filters.get("user_id") == "eq.u1"
    assert filters.get("offering_id") == "eq.off1"
    # Soft-deleted notes are excluded from list reads.
    assert filters.get("deleted_at") == "is.null"


def test_delete_note_soft_deletes_and_scopes_by_user():
    """0025: delete is a soft delete — sets deleted_at instead of removing
    the row, and stays scoped to (id, user_id)."""
    fake = FakeTable(rows=[{"id": "n1", "user_id": "u1"}])
    with patch("services.notes_service.table", return_value=fake):
        _run(delete_note(note_id="n1", user_id="u1"))
    # No hard delete fired.
    assert fake.deleted == []
    # A soft-delete update stamped deleted_at, scoped to the owner.
    assert fake.updated, "soft-delete update was not called"
    data, filters = fake.updated[0]
    assert data.get("deleted_at") is not None
    assert filters == {"id": "eq.n1", "user_id": "eq.u1"}


from services.notes_service import (
    link_concept,
    list_linked_concepts,
    unlink_concept,
)


class TestLinkedConcepts:
    def test_link_concept_inserts_junction_row(self):
        notes_fake = FakeTable(rows=[{"id": "n1", "user_id": "u1"}])
        nodes_fake = FakeTable(rows=[{"id": "g1"}])
        nc_fake = FakeTable()
        def picker(name):
            return {"notes": notes_fake, "graph_nodes": nodes_fake,
                    "note_concepts": nc_fake}[name]
        with patch("services.notes_service.table", side_effect=picker):
            ok = _run(link_concept(note_id="n1", user_id="u1", concept_node_id="g1"))
        assert ok is True
        # An idempotent write: re-linking an existing link is DO NOTHING,
        # not a PK-conflict 500.
        assert nc_fake.upserts == [(
            [{"note_id": "n1", "concept_node_id": "g1"}],
            {"on_conflict": "note_id,concept_node_id", "ignore_duplicates": True},
        )]
        # The node lookup is scoped to the caller (#115).
        _, kwargs = nodes_fake.select_calls[0]
        assert kwargs["filters"] == {"id": "eq.g1", "user_id": "eq.u1"}

    def test_link_concept_rejects_foreign_or_missing_node(self):
        """#115: a node id the caller does not own (another student's node,
        or one that does not exist) is refused the same way: both are zero
        rows under the user_id filter, and nothing is written."""
        notes_fake = FakeTable(rows=[{"id": "n1", "user_id": "u1"}])
        nodes_fake = FakeTable(rows=[])  # filtered by user_id = u1: no row
        nc_fake = FakeTable()
        def picker(name):
            return {"notes": notes_fake, "graph_nodes": nodes_fake,
                    "note_concepts": nc_fake}[name]
        with patch("services.notes_service.table", side_effect=picker):
            ok = _run(link_concept(note_id="n1", user_id="u1", concept_node_id="g-other"))
        assert ok is False
        assert nc_fake.upserts == []
        _, kwargs = nodes_fake.select_calls[0]
        assert kwargs["filters"] == {"id": "eq.g-other", "user_id": "eq.u1"}

    def test_link_concept_rejects_unowned_note(self):
        notes_fake = FakeTable(rows=[])  # no such note for this user
        nc_fake = FakeTable()
        def picker(name):
            return {"notes": notes_fake, "note_concepts": nc_fake}[name]
        with patch("services.notes_service.table", side_effect=picker):
            ok = _run(link_concept(note_id="n1", user_id="u1", concept_node_id="g1"))
        assert ok is False
        assert nc_fake.upserts == []

    def test_list_linked_concepts_joins_against_graph_nodes(self):
        nc_fake = FakeTable(rows=[
            {"note_id": "n1", "concept_node_id": "g1"},
            {"note_id": "n1", "concept_node_id": "g2"},
        ])
        nodes_fake = FakeTable(rows=[
            {"id": "g1", "concept_name": "Photosynthesis",
             "mastery_tier": "learning", "mastery_score": 0.5,
             "course_id": "c1"},
            {"id": "g2", "concept_name": "Calvin Cycle",
             "mastery_tier": "struggling", "mastery_score": 0.2,
             "course_id": "c1"},
        ])
        def picker(name):
            return {"note_concepts": nc_fake, "graph_nodes": nodes_fake}[name]
        with patch("services.notes_service.table", side_effect=picker):
            out = _run(list_linked_concepts(note_id="n1", user_id="u1"))
        names = {c["concept_name"] for c in out}
        assert names == {"Photosynthesis", "Calvin Cycle"}
        assert all("mastery_tier" in c for c in out)

    def test_unlink_concept_scopes_by_note(self):
        nc_fake = FakeTable()
        nc_fake.delete_returns = [{"note_id": "n1", "concept_node_id": "g1"}]
        notes_fake = FakeTable(rows=[{"id": "n1", "user_id": "u1"}])
        nodes_fake = FakeTable(rows=[{"id": "g1"}])
        def picker(name):
            return {"notes": notes_fake, "graph_nodes": nodes_fake,
                    "note_concepts": nc_fake}[name]
        with patch("services.notes_service.table", side_effect=picker):
            ok = _run(unlink_concept(note_id="n1", user_id="u1", concept_node_id="g1"))
        assert ok is True
        assert nc_fake.deleted == [
            {"note_id": "eq.n1", "concept_node_id": "eq.g1"}
        ]
        # The node is checked against the caller too (symmetry with link).
        _, kwargs = nodes_fake.select_calls[0]
        assert kwargs["filters"] == {"id": "eq.g1", "user_id": "eq.u1"}

    def test_unlink_concept_refuses_foreign_node(self):
        nc_fake = FakeTable()
        notes_fake = FakeTable(rows=[{"id": "n1", "user_id": "u1"}])
        nodes_fake = FakeTable(rows=[])
        def picker(name):
            return {"notes": notes_fake, "graph_nodes": nodes_fake,
                    "note_concepts": nc_fake}[name]
        with patch("services.notes_service.table", side_effect=picker):
            ok = _run(unlink_concept(note_id="n1", user_id="u1", concept_node_id="g-x"))
        assert ok is False
        assert nc_fake.deleted == []

    def test_unlink_concept_false_when_nothing_removed(self):
        nc_fake = FakeTable()  # delete returns no rows: there was no link
        notes_fake = FakeTable(rows=[{"id": "n1", "user_id": "u1"}])
        nodes_fake = FakeTable(rows=[{"id": "g1"}])
        def picker(name):
            return {"notes": notes_fake, "graph_nodes": nodes_fake,
                    "note_concepts": nc_fake}[name]
        with patch("services.notes_service.table", side_effect=picker):
            ok = _run(unlink_concept(note_id="n1", user_id="u1", concept_node_id="g1"))
        assert ok is False


def _http_error(status: int, body: dict):
    import httpx
    req = httpx.Request("POST", "https://x.supabase.co/rest/v1/note_concepts")
    return httpx.HTTPStatusError(
        "err", request=req, response=httpx.Response(status, json=body, request=req)
    )


class _RaisingUpsert(FakeTable):
    """note_concepts whose upsert raises `errors[i]` on call i (None = ok)."""
    def __init__(self, errors):
        super().__init__()
        self.errors = list(errors)

    def upsert(self, data, on_conflict="id", **kwargs):
        err = self.errors.pop(0) if self.errors else None
        if err is not None:
            raise err
        return super().upsert(data, on_conflict, **kwargs)


class TestLinkWriteFailures:
    def _picker(self, nc_fake):
        notes_fake = FakeTable(rows=[{"id": "n1", "user_id": "u1"}])
        nodes_fake = FakeTable(rows=[{"id": "g1"}])
        return lambda name: {"notes": notes_fake, "graph_nodes": nodes_fake,
                             "note_concepts": nc_fake}[name]

    def test_fk_violation_is_the_same_false_as_a_foreign_node(self):
        """The node vanished between the ownership check and the write:
        the FK refusal maps to False (the route's 404), not a 500."""
        nc_fake = _RaisingUpsert([_http_error(409, {"code": "23503"})])
        with patch("services.notes_service.table", side_effect=self._picker(nc_fake)):
            ok = _run(link_concept(note_id="n1", user_id="u1", concept_node_id="g1"))
        assert ok is False

    def test_other_write_errors_propagate(self):
        import httpx
        import pytest
        nc_fake = _RaisingUpsert([_http_error(500, {"code": "XX000"})])
        with patch("services.notes_service.table", side_effect=self._picker(nc_fake)), \
             pytest.raises(httpx.HTTPStatusError):
            _run(link_concept(note_id="n1", user_id="u1", concept_node_id="g1"))


class TestLinkPrecheckedConcepts:
    def test_one_bulk_idempotent_write_and_no_probes(self):
        from services.notes_service import link_prechecked_concepts
        nc_fake = FakeTable()
        seen: list[str] = []
        def picker(name):
            seen.append(name)
            return nc_fake
        with patch("services.notes_service.table", side_effect=picker):
            n = _run(link_prechecked_concepts("n1", ["g1", "g2", "g1", ""]))
        assert n == 2
        assert seen == ["note_concepts"]  # no notes/graph_nodes round trips
        assert nc_fake.upserts == [(
            [{"note_id": "n1", "concept_node_id": "g1"},
             {"note_id": "n1", "concept_node_id": "g2"}],
            {"on_conflict": "note_id,concept_node_id", "ignore_duplicates": True},
        )]

    def test_fk_violation_falls_back_to_row_by_row(self):
        from services.notes_service import link_prechecked_concepts
        fk = _http_error(409, {"code": "23503"})
        # batch fails, then g1 ok, g2 (vanished) fails, g3 ok
        nc_fake = _RaisingUpsert([fk, None, fk, None])
        with patch("services.notes_service.table", return_value=nc_fake):
            n = _run(link_prechecked_concepts("n1", ["g1", "g2", "g3"]))
        assert n == 2
        assert [rows for rows, _ in nc_fake.upserts] == [
            [{"note_id": "n1", "concept_node_id": "g1"}],
            [{"note_id": "n1", "concept_node_id": "g3"}],
        ]

    def test_empty_is_a_no_op(self):
        from services.notes_service import link_prechecked_concepts
        with patch("services.notes_service.table", side_effect=AssertionError):
            assert _run(link_prechecked_concepts("n1", [])) == 0

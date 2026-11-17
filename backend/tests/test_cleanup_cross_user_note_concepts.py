"""scripts/cleanup_cross_user_note_concepts.py — removes pre-#115 links of a
note to another student's graph node. Dry-run by default, idempotent."""
import importlib
import sys

import pytest

NAME = "scripts.cleanup_cross_user_note_concepts"


@pytest.fixture
def mod(monkeypatch):
    monkeypatch.setattr("dotenv.load_dotenv", lambda *a, **k: False)
    sys.modules.pop(NAME, None)
    module = importlib.import_module(NAME)
    yield module
    sys.modules.pop(NAME, None)


class _DB:
    """note_concepts / notes / graph_nodes in memory; delete really removes."""

    def __init__(self):
        self.links = [
            {"note_id": "nA", "concept_node_id": "gA"},  # A's note, A's node
            {"note_id": "nB", "concept_node_id": "gA"},  # B's note, A's node: stale
            {"note_id": "nB", "concept_node_id": "gB"},  # B's note, B's node
        ]
        self.owners = {
            "notes": {"nA": "uA", "nB": "uB"},
            "graph_nodes": {"gA": "uA", "gB": "uB"},
        }
        self.deletes: list[dict] = []
        self.lookups: list[tuple[str, str]] = []

    def table(self, name):
        db = self

        class _T:
            def select(self, cols, filters=None, **kw):
                db.lookups.append((name, filters["id"]))
                wanted = filters["id"].removeprefix("in.(").removesuffix(")").split(",")
                wanted = {w.strip('"') for w in wanted}
                return [{"id": i, "user_id": u}
                        for i, u in db.owners[name].items() if i in wanted]

            def delete(self, filters):
                assert name == "note_concepts"
                db.deletes.append(filters)
                note = filters["note_id"].removeprefix("eq.")
                node = filters["concept_node_id"].removeprefix("eq.")
                hit = [r for r in db.links
                       if r["note_id"] == note and r["concept_node_id"] == node]
                db.links = [r for r in db.links if r not in hit]
                return hit

        return _T()


def _wire(mod, monkeypatch, db):
    monkeypatch.setattr(mod, "table", db.table)
    monkeypatch.setattr(mod, "page_all", lambda *a, **k: iter([dict(r) for r in db.links]))


def test_plan_flags_only_rows_whose_owners_differ(mod):
    stale, counts = mod.plan(
        [{"note_id": "n1", "concept_node_id": "g1"},
         {"note_id": "n1", "concept_node_id": "g2"},
         {"note_id": "n9", "concept_node_id": "g1"}],
        {"n1": "u1"},
        {"g1": "u1", "g2": "u2"},
    )
    assert stale == [{"note_id": "n1", "concept_node_id": "g2"}]
    assert counts == {"same_owner": 1, "cross_user": 1, "unreadable_owner": 1}


def test_dry_run_is_the_default_and_deletes_nothing(mod, monkeypatch, capsys):
    db = _DB()
    _wire(mod, monkeypatch, db)
    counts = mod.main([])
    assert counts["cross_user"] == 1
    assert counts["deleted"] == 0
    assert db.deletes == []
    assert "DRY RUN" in capsys.readouterr().out


def test_apply_deletes_exactly_the_cross_user_pair_and_is_idempotent(mod, monkeypatch):
    db = _DB()
    _wire(mod, monkeypatch, db)
    counts = mod.main(["--apply"])
    assert counts["deleted"] == 1
    assert db.deletes == [{"note_id": "eq.nB", "concept_node_id": "eq.gA"}]
    assert db.links == [
        {"note_id": "nA", "concept_node_id": "gA"},
        {"note_id": "nB", "concept_node_id": "gB"},
    ]
    # A second run finds nothing left to do.
    again = mod.main(["--apply"])
    assert again["cross_user"] == 0
    assert again["deleted"] == 0


def test_owner_lookups_are_batched_and_quoted(mod, monkeypatch):
    db = _DB()
    db.links = [{"note_id": f"n{i}", "concept_node_id": "gA"} for i in range(5)]
    db.owners["notes"] = {f"n{i}": "uA" for i in range(5)}
    monkeypatch.setattr(mod, "LOOKUP_BATCH", 2)
    _wire(mod, monkeypatch, db)
    mod.main([])
    note_lookups = [f for name, f in db.lookups if name == "notes"]
    assert len(note_lookups) == 3  # 5 ids in batches of 2
    assert note_lookups[0] == 'in.("n0","n1")'

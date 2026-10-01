import pytest

import db.seed_local_rich as rich


def test_guard_refuses_non_local(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://prod.supabase.co")
    with pytest.raises(SystemExit):
        rich._guard_local()


def test_guard_allows_local(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "http://127.0.0.1:54321")
    rich._guard_local()  # no raise


# ── PKG-14 final fix round: seeded tiers follow the launch cuts (A95) ────────


def _seeded_graph_nodes(monkeypatch) -> list[dict]:
    """Every graph_nodes row the rich seed writes (seed_graph + the loop users),
    captured at the helper seam — no database."""
    from unittest.mock import MagicMock

    rows: list[dict] = []

    def upsert(name, row, **kw):
        if name == "graph_nodes":
            rows.append(dict(row))

    monkeypatch.setattr(rich.h, "upsert", upsert)
    monkeypatch.setattr(rich.h, "insert_if_absent", lambda *a, **k: None)
    monkeypatch.setattr(rich, "table", lambda name: MagicMock(select=MagicMock(return_value=[])))
    rich.seed_graph()
    try:
        rich.seed_learning_loop()
    except Exception:  # noqa: BLE001 — only its graph_nodes upserts matter here
        pass
    return rows


def test_every_seeded_tier_is_tier_for_its_score(monkeypatch):
    from learning.bkt import tier_for

    rows = _seeded_graph_nodes(monkeypatch)
    assert rows, "the seed writes no graph_nodes rows"
    for row in rows:
        assert row["mastery_tier"] == tier_for(row["mastery_score"]), row["id"]


def test_the_seeded_student_covers_every_tier(monkeypatch):
    """frontend/e2e/graph.spec.ts's journey guard: the rich seed has a node in
    EVERY tier for rich-user-active — after the launch cuts (mastered ≥ 0.95)."""
    from learning.bkt import tier_for

    tiers = {
        tier_for(score)
        for nodes in rich._GRAPH_NODES.values()
        for _id, _name, score in nodes
    }
    assert tiers == {"mastered", "learning", "struggling", "unexplored"}
    active = [r for r in _seeded_graph_nodes(monkeypatch) if r["user_id"] == rich.USER_ACTIVE]
    assert {r["mastery_tier"] for r in active} == tiers

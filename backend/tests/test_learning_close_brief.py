"""PKG-09 close-brief: session close (model-written, encrypted at rest,
deterministic fallback, no LLM call without evidence or at the hard budget
level) and the bounded learner brief, stored once per session and served as
the first history message. Spec §3.4, §3.5, §4, §6, §9, §13 A19/A25."""

from __future__ import annotations

import pathlib
import re


MIG_DIR = pathlib.Path(__file__).resolve().parents[1] / "db" / "migrations"


def _migration() -> str:
    hits = sorted(MIG_DIR.glob("*_learning_session_close.sql"))
    assert len(hits) == 1, f"expected exactly one learning_session_close migration, got {hits}"
    return hits[0].read_text()


# ── migration ────────────────────────────────────────────────────────────────


def test_migration_close_json_is_text_not_jsonb():
    sql = _migration()
    assert re.search(r"close_json\s+text", sql), "close_json must be text (encrypted JSON string)"
    assert not re.search(r"close_json\s+jsonb", sql, re.IGNORECASE)


def test_migration_close_phase_check_enum_matches_spec():
    sql = _migration()
    m = re.search(r"close_phase\s+text\s+CHECK\s*\(close_phase IN \(([^)]*)\)\)", sql)
    assert m, "close_phase must carry the CHECK enum from spec §4"
    values = tuple(v.strip().strip("'") for v in m.group(1).split(","))
    from learning.params import CLOSE_PHASES

    assert values == CLOSE_PHASES


def test_migration_is_idempotent_and_named():
    sql = _migration()
    assert sql.count("ADD COLUMN IF NOT EXISTS") == 3
    name = sorted(MIG_DIR.glob("*_learning_session_close.sql"))[0].name
    assert re.fullmatch(r"\d{14}_learning_session_close\.sql", name), name


def test_migration_loop_brief_is_encrypted_text():
    sql = _migration()
    assert re.search(r"loop_brief\s+text", sql), "loop_brief must be text (encrypted string, A19)"
    assert not re.search(r"loop_brief\s+jsonb", sql, re.IGNORECASE)
    assert "loop_brief is encrypted (A19)" in sql


# ── constants ────────────────────────────────────────────────────────────────


def test_close_constants_exist_and_are_bounded():
    from learning import params as p

    assert p.CLOSE_PHASES == ("probe", "plan", "teach", "check", "feedback", "close")
    for name in (
        "CLOSE_SUMMARY_MAX_CHARS",
        "CLOSE_SELF_EVAL_MAX_CHARS",
        "CLOSE_IF_THEN_MAX_CHARS",
        "CLOSE_TRANSCRIPT_TURN_MAX_CHARS",
        "LOOP_HISTORY_TRIM_BLOCK",
    ):
        assert isinstance(getattr(p, name), int) and getattr(p, name) > 0, name
    # One close line (summary + plan) must fit in half a brief, so the newest
    # close always renders; older closes are cut by the brief's hard bound.
    assert p.CLOSE_SUMMARY_MAX_CHARS + p.CLOSE_IF_THEN_MAX_CHARS < p.LEARNER_BRIEF_MAX_CHARS // 2
    # The brief message plus the largest block-trimmed window (2 × block − 1)
    # stays inside the §3.4 history bound (A19).
    assert 1 + (2 * p.LOOP_HISTORY_TRIM_BLOCK - 1) <= p.LOOP_HISTORY_MAX_MESSAGES


def test_close_limits_are_tool_less():
    from agents import CLOSE_LIMITS, GRADER_LIMITS

    assert CLOSE_LIMITS.tool_calls_limit == 0
    assert CLOSE_LIMITS.request_limit == GRADER_LIMITS.request_limit
    assert CLOSE_LIMITS.total_tokens_limit == GRADER_LIMITS.total_tokens_limit


# ── learning/session_close ───────────────────────────────────────────────────


import pytest  # noqa: E402


def _msgs(n: int, prefix: str = "turn") -> list[dict]:
    out = []
    for i in range(n):
        role = "user" if i % 2 == 0 else "assistant"
        out.append({"role": role, "content": f"{prefix}-{i} " + ("x" * 1000)})
    return out


def _evidence(node: str, before: float, after: float, correct: bool = True) -> dict:
    return {
        "node_id": node,
        "p_before": before,
        "p_after": after,
        "correct": correct,
        "channel": "free_response",
    }


def test_build_close_bounds_turns_and_truncates_each():
    from learning.params import CLOSE_TRANSCRIPT_TURN_MAX_CHARS, LOOP_HISTORY_MAX_MESSAGES
    from learning.session_close import build_close

    draft = build_close(_msgs(3 * LOOP_HISTORY_MAX_MESSAGES), [], [], {})
    assert len(draft.turns) == LOOP_HISTORY_MAX_MESSAGES
    assert draft.turns[-1].content.startswith(f"turn-{3 * LOOP_HISTORY_MAX_MESSAGES - 1} ")
    assert all(len(t.content) <= CLOSE_TRANSCRIPT_TURN_MAX_CHARS for t in draft.turns)
    assert all(t.role in ("user", "assistant") for t in draft.turns)


def test_build_close_drops_system_rows_and_empty_content():
    from learning.session_close import build_close

    draft = build_close(
        [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": ""},
            {"role": "user", "content": None},
            {"role": "user", "content": "hi"},
        ],
        [],
        [],
        {},
    )
    assert [t.content for t in draft.turns] == ["hi"]


def test_build_close_derives_concept_deltas_from_evidence():
    from learning.session_close import build_close

    rows = [
        _evidence("n1", 0.35, 0.50),
        _evidence("n1", 0.50, 0.62),
        _evidence("n2", 0.35, 0.28, correct=False),
        {"node_id": "n3", "p_before": None, "p_after": 0.4},  # incomplete: skipped
    ]
    draft = build_close([], rows, ["sign_error", "sign_error", "off_by_one"], {})
    by_id = {c.node_id: c for c in draft.concepts}
    assert set(by_id) == {"n1", "n2"}
    assert by_id["n1"].p_before == 0.35 and by_id["n1"].p_after == 0.62
    assert by_id["n2"].p_before == 0.35 and by_id["n2"].p_after == 0.28
    assert draft.misconception_keys == ["sign_error", "off_by_one"]


def test_build_close_prefers_given_learner_deltas():
    from learning.session_close import build_close

    draft = build_close([], [_evidence("n1", 0.35, 0.62)], [], {"n9": (0.1, 0.2)})
    assert [(c.node_id, c.p_before, c.p_after) for c in draft.concepts] == [("n9", 0.1, 0.2)]


def test_fallback_close_is_deterministic_and_flagged():
    from learning.session_close import build_close, fallback_close

    draft = build_close([], [_evidence("n1", 0.35, 0.62)], ["sign_error"], {})
    a, b = fallback_close(draft), fallback_close(draft)
    assert a == b
    assert a.model_written is False
    assert "n1" in a.summary and "0.35" in a.summary and "0.62" in a.summary
    assert a.if_then == ""
    assert a.self_eval.endswith("?")
    assert a.misconceptions == ["sign_error"]


def test_fallback_close_names_concepts_when_the_draft_knows_them():
    """Deviation (PKG-09): the draft carries concept names (one graph_nodes read in the
    route), so the student-facing fallback says "Base Case", not a node id."""
    from learning.session_close import build_close, fallback_close

    draft = build_close(
        [], [_evidence("n1", 0.35, 0.62)], [], {}, concept_names={"n1": "Base Case"}
    )
    rec = fallback_close(draft)
    assert rec.summary == "Base Case: p 0.35 → 0.62"
    assert [c.node_id for c in rec.concepts] == ["n1"]  # the stored record keeps the id


def test_fallback_close_without_evidence_says_so():
    from learning.session_close import build_close, fallback_close

    rec = fallback_close(build_close([], [], [], {}))
    assert rec.summary == "No graded checks this session."
    assert rec.concepts == []


def test_normalise_close_truncates_and_never_invents_keys():
    from types import SimpleNamespace

    from learning.params import (
        CLOSE_IF_THEN_MAX_CHARS,
        CLOSE_SELF_EVAL_MAX_CHARS,
        CLOSE_SUMMARY_MAX_CHARS,
    )
    from learning.session_close import build_close, normalise_close

    draft = build_close([], [_evidence("n1", 0.35, 0.62)], ["sign_error"], {})
    out = SimpleNamespace(
        summary="s" * (CLOSE_SUMMARY_MAX_CHARS * 3),
        self_eval_prompt="e" * (CLOSE_SELF_EVAL_MAX_CHARS * 3),
        if_then_plan="If x, then y. " * CLOSE_IF_THEN_MAX_CHARS,
        open_misconception_keys=["sign_error", "invented_key", "sign_error"],
    )
    rec = normalise_close(out, draft)
    assert len(rec.summary) == CLOSE_SUMMARY_MAX_CHARS
    assert len(rec.self_eval) == CLOSE_SELF_EVAL_MAX_CHARS
    assert len(rec.if_then) == CLOSE_IF_THEN_MAX_CHARS
    assert rec.misconceptions == ["sign_error"]
    assert rec.model_written is True
    assert [c.node_id for c in rec.concepts] == ["n1"]


class _SessionsTable:
    def __init__(self, existing: list[dict]):
        self.existing, self.inserts, self.updates, self.upserts = existing, [], [], []

    def select(self, cols, filters=None, **kw):
        assert "close_json" not in (filters or {}), "never filter on an encrypted column"
        return self.existing

    def insert(self, row):
        self.inserts.append(row)
        return [row]

    def update(self, row, filters=None):
        self.updates.append((row, filters))
        return [row]

    def upsert(self, *a, **k):
        self.upserts.append((a, k))
        return []


def _record():
    from learning.session_close import CloseRecord

    return CloseRecord(
        summary="S",
        self_eval="Q?",
        if_then="If a, then b.",
        concepts=[],
        misconceptions=[],
        model_written=True,
    )


def test_store_close_creates_missing_lazy_row_then_updates(monkeypatch):
    import learning.session_close as sc

    t = _SessionsTable(existing=[])
    monkeypatch.setattr(sc, "table", lambda name: t)
    monkeypatch.setattr(sc, "encrypt_json", lambda v: "CIPHER")

    sc.store_close(
        "sess-1",
        "user_andres",
        _record(),
        "teach",
        row_defaults={"mode": "socratic", "topic": "Recursion", "offering_id": "off-1"},
    )

    assert t.inserts == [
        {
            "id": "sess-1",
            "user_id": "user_andres",
            "mode": "socratic",
            "topic": "Recursion",
            "offering_id": "off-1",
        }
    ]
    assert t.updates == [({"close_json": "CIPHER", "close_phase": "teach"}, {"id": "eq.sess-1"})]
    assert t.upserts == []


def test_store_close_existing_row_updates_only(monkeypatch):
    import learning.session_close as sc

    t = _SessionsTable(existing=[{"id": "sess-1"}])
    monkeypatch.setattr(sc, "table", lambda name: t)
    monkeypatch.setattr(sc, "encrypt_json", lambda v: "CIPHER")
    sc.store_close(
        "sess-1", "user_andres", _record(), "close", row_defaults={"mode": "socratic", "topic": "T"}
    )
    assert t.inserts == []
    assert t.updates[0][0]["close_phase"] == "close"


def test_store_close_without_offering_omits_it(monkeypatch):
    import learning.session_close as sc

    t = _SessionsTable(existing=[])
    monkeypatch.setattr(sc, "table", lambda name: t)
    monkeypatch.setattr(sc, "encrypt_json", lambda v: "CIPHER")
    sc.store_close(
        "s",
        "u",
        _record(),
        "close",
        row_defaults={"mode": "socratic", "topic": "T", "offering_id": None},
    )
    assert t.inserts == [{"id": "s", "user_id": "u", "mode": "socratic", "topic": "T"}]


def test_store_close_encrypts_the_full_record(monkeypatch):
    import learning.session_close as sc

    t = _SessionsTable(existing=[{"id": "sess-1"}])
    seen = {}
    monkeypatch.setattr(sc, "table", lambda name: t)
    monkeypatch.setattr(sc, "encrypt_json", lambda v: seen.setdefault("v", v) and "CIPHER")
    sc.store_close(
        "sess-1", "u", _record(), "close", row_defaults={"mode": "socratic", "topic": "T"}
    )
    assert set(seen["v"]) == {
        "summary",
        "self_eval",
        "if_then",
        "concepts",
        "misconceptions",
        "model_written",
    }
    assert t.updates[0][0]["close_json"] == "CIPHER"


def test_store_close_rejects_unknown_phase(monkeypatch):
    import learning.session_close as sc

    t = _SessionsTable([])
    monkeypatch.setattr(sc, "table", lambda name: t)
    with pytest.raises(ValueError):
        sc.store_close(
            "s", "u", _record(), "warmup", row_defaults={"mode": "socratic", "topic": "T"}
        )
    assert t.inserts == [] and t.updates == []


def test_store_close_missing_row_without_defaults_raises(monkeypatch):
    """A close with nowhere to go is an error the route maps to 502, never a silent drop."""
    import learning.session_close as sc

    t = _SessionsTable([])
    monkeypatch.setattr(sc, "table", lambda name: t)
    with pytest.raises(LookupError):
        sc.store_close("s", "u", _record(), "close", row_defaults=None)
    assert t.updates == []


def test_ensure_session_row_without_defaults_never_inserts(monkeypatch):
    import learning.session_close as sc

    missing, present = _SessionsTable(existing=[]), _SessionsTable(existing=[{"id": "sess-1"}])
    monkeypatch.setattr(sc, "table", lambda name: missing)
    assert sc.ensure_session_row("sess-1", "u", None) is False
    assert missing.inserts == [] and missing.upserts == []
    monkeypatch.setattr(sc, "table", lambda name: present)
    assert sc.ensure_session_row("sess-1", "u", None) is True
    assert present.inserts == []


def test_session_close_module_is_llm_free():
    src = (
        pathlib.Path(__file__).resolve().parents[1] / "learning" / "session_close.py"
    ).read_text()
    assert "pydantic_ai" not in src and "from agents" not in src and "import agents" not in src

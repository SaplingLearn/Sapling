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

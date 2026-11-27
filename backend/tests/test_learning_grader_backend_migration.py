"""node_mastery_events.grader_backend (spec §4, §13 A22, A116): the code's
GraderBackend Literal is the CHECK list in force, so every label the app
writes is one the database accepts.

Read from the SQL files; the CHECK itself rejecting a bad label against real
Postgres is tests/integration/test_learning_evidence_transaction_db.py."""

from db.migration_units import MIGRATION_UNITS
import re
from typing import get_args

MIG_DIR = MIGRATION_UNITS
#: The list in force since A116: the CHECK the last migration applies, and the Literal.
GRADER_BACKENDS = ("deterministic", "gemini", "gemini_second", "claude", "claude_second", "jev")
_CHECK = re.compile(
    r"CHECK\s*\(\s*grader_backend IS NULL OR grader_backend IN\s*\(([^)]*)\)\s*\)", re.I
)


def _ddl(sql: str) -> str:
    """The SQL without its comment lines (a header may quote an older CHECK)."""
    return "\n".join(line for line in sql.splitlines() if not line.lstrip().startswith("--"))


def _values(group: str) -> tuple[str, ...]:
    return tuple(v.strip().strip("'") for v in group.split(","))


def _check_lists() -> list[tuple[str, tuple[str, ...]]]:
    """Every grader_backend CHECK list the migrations define, in apply order."""
    return [
        (path.name, _values(m.group(1)))
        for path in sorted(MIG_DIR.glob("*.sql"))
        for m in _CHECK.finditer(_ddl(path.read_text()))
    ]


def test_evidence_literal_matches_the_check_list():
    """The model and the CHECK in force (the last one the migrations apply) name the
    same backends, in order."""
    from learning.evidence import GraderBackend

    assert get_args(GraderBackend) == GRADER_BACKENDS
    assert _check_lists()[-1][1] == GRADER_BACKENDS


def test_zpd_step_and_grader_runs_use_that_list():
    """zpd.step's grader_backend is the same Literal (one list, never two to drift),
    and every label the grader writes is in it."""
    from agents.grader import _RUN_BACKENDS, GraderRunBackend
    from learning import evidence, zpd_events

    assert zpd_events.GraderBackend is evidence.GraderBackend
    assert set(_RUN_BACKENDS.values()) == set(get_args(GraderRunBackend))
    assert set(get_args(GraderRunBackend)) <= set(GRADER_BACKENDS)

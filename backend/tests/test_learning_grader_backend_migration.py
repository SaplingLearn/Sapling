"""PKG-05's reopen of PKG-03 (spec §4, §13 A22): node_mastery_events.grader_backend,
and its A116 widening (the grader names the provider that graded).

Read from the SQL files only: this guards the DDL graph_service depends on and
does NOT prove the live schema. The E2E lane's fresh-DB replay (`make e2e-up`
with E2E_FRESH_DB=1) is what applies it."""

import pathlib
import re
from typing import get_args

MIG_DIR = pathlib.Path(__file__).resolve().parents[1] / "db" / "migrations"
#: PKG-05's CHECK list as applied; its migration is immutable, so this is history.
PKG05_BACKENDS = ("deterministic", "gemini", "gemini_second", "jev")
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


def _one(pattern: str) -> tuple[str, str]:
    hits = sorted(MIG_DIR.glob(pattern))
    assert len(hits) == 1, f"expected exactly one {pattern} migration, got {hits}"
    return hits[0].name, hits[0].read_text()


def _migration() -> tuple[str, str]:
    return _one("*_learning_grader_backend.sql")


def _widening() -> tuple[str, str]:
    return _one("*_learning_grader_backend_claude.sql")


def _check_lists() -> list[tuple[str, tuple[str, ...]]]:
    """Every grader_backend CHECK list the migrations define, in apply order."""
    return [
        (path.name, _values(m.group(1)))
        for path in sorted(MIG_DIR.glob("*.sql"))
        for m in _CHECK.finditer(_ddl(path.read_text()))
    ]


def test_grader_backend_column_is_nullable_and_checked():
    _, sql = _migration()
    assert "ALTER TABLE node_mastery_events ADD COLUMN IF NOT EXISTS grader_backend text" in sql
    assert "NOT NULL" not in sql, "legacy journal writers never set it"
    m = _CHECK.search(sql)
    assert m, sql
    assert _values(m.group(1)) == PKG05_BACKENDS


def test_migration_prefix_is_a_utc_timestamp_after_pkg03():
    name, _ = _migration()
    assert re.fullmatch(r"\d{14}_learning_grader_backend\.sql", name), name
    prior = sorted(MIG_DIR.glob("*_learning_learner_state.sql"))[0].name
    assert name > prior, "must sort after PKG-03's migration"


def test_a116_widening_replaces_the_narrow_check_by_its_body():
    """A116: one migration, after PKG-05's, swaps the CHECK for the widened list. It
    finds the narrow constraint by its definition (a DROP by an assumed name no-ops on
    a suffixed variant and leaves the narrow CHECK enforced: 20260828172725), adds
    the wide one only when none is present (re-runnable), and changes no row."""
    name, sql = _widening()
    ddl = _ddl(sql)
    assert re.fullmatch(r"\d{14}_learning_grader_backend_claude\.sql", name), name
    assert name > _migration()[0], "must sort after PKG-05's migration"
    assert "'public.node_mastery_events'::regclass" in ddl
    assert "NOT ILIKE '%claude_second%'" in ddl and "DROP CONSTRAINT %I" in ddl
    assert "DROP CONSTRAINT IF EXISTS" not in ddl, "never by an assumed name alone"
    assert "IF NOT EXISTS" in ddl and "ADD CONSTRAINT node_mastery_events_grader_backend_check" in ddl
    assert ddl.count("NOT VALID") == 1, "a strict superset: no full-table validation scan"
    assert not re.search(r"\b(UPDATE|DELETE|INSERT)\b", ddl, re.I), "historical rows keep their labels"
    assert len(_CHECK.findall(ddl)) == 1


def test_every_check_keeps_the_values_before_it():
    """No widening drops a value an earlier CHECK allowed, so no row already written
    is relabelled or left violating the constraint in force."""
    lists = _check_lists()
    assert [values for _, values in lists] == [PKG05_BACKENDS, GRADER_BACKENDS]
    for (_, earlier), (_, later) in zip(lists, lists[1:]):
        assert set(earlier) <= set(later)


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

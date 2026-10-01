"""PKG-14b review fix round (regression M2, spec §13 A95): stored
graph_nodes.mastery_tier rows written under the retired 0.1/0.45/0.75 cuts are
re-derived ONCE from mastery_score with learning.bkt.tier_for's cuts, by an
idempotent data migration whose SQL CASE mirrors tier_for. Pinned here: the
SQL thresholds ARE learning.params', and the CASE agrees with tier_for."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from learning.bkt import tier_for
from learning.params import BAND_NOVICE_MAX, BKT_PROFICIENT, TIER_UNEXPLORED_MAX

MIG_DIR = Path(__file__).resolve().parents[1] / "db" / "migrations"


def _sql() -> str:
    (path,) = sorted(MIG_DIR.glob("*_learning_rederive_mastery_tier.sql"))
    assert re.fullmatch(r"\d{14}_learning_rederive_mastery_tier\.sql", path.name)
    return "\n".join(l for l in path.read_text().splitlines() if not l.lstrip().startswith("--"))


def _case(sql: str) -> list[tuple[float, str]]:
    """(threshold, tier) in CASE order, plus the ELSE tier as (0, tier)."""
    whens = re.findall(r"WHEN\s+\w+\s*>=\s*([0-9.]+)\s+THEN\s+'(\w+)'", sql)
    (els,) = set(re.findall(r"ELSE\s+'(\w+)'", sql))
    return [(float(v), t) for v, t in whens] + [(0.0, els)]


def test_the_sql_cuts_are_tier_fors_constants():
    case = _case(_sql())
    assert case == [
        (BKT_PROFICIENT, "mastered"),
        (BAND_NOVICE_MAX, "learning"),
        (TIER_UNEXPLORED_MAX, "struggling"),
        (0.0, "unexplored"),
    ]


@pytest.mark.parametrize("p", [0.0, 0.05, 0.0999, 0.1, 0.25, 0.29, 0.3, 0.5, 0.75, 0.8, 0.94, 0.95, 1.0])
def test_the_case_agrees_with_tier_for(p):
    case = _case(_sql())
    sql_tier = next(t for v, t in case if p >= v)
    assert sql_tier == tier_for(p)


def test_the_migration_is_an_idempotent_update_of_mastery_tier_only():
    sql = _sql().upper()
    assert "UPDATE GRAPH_NODES" in sql and "SET MASTERY_TIER" in sql
    assert "IS DISTINCT FROM" in sql  # a second run changes nothing
    for forbidden in ("DROP ", "DELETE ", "ALTER ", "MASTERY_SCORE =", "INSERT "):
        assert forbidden not in sql, forbidden

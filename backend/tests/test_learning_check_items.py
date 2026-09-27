"""PKG-04 check items: params, migration invariants, models, service, agent
plumbing, route hook, backfill. Spec §3.4, §3.5, §4, §8.6/8.9/8.12, §13 A2/A22/A23."""

from __future__ import annotations

import pathlib
import re

MIG_DIR = pathlib.Path(__file__).resolve().parents[1] / "db" / "migrations"


def _migration() -> str:
    hits = sorted(MIG_DIR.glob("*_learning_check_items.sql"))
    assert len(hits) == 1, f"expected exactly one learning_check_items migration, got {hits}"
    return hits[0].read_text()


class TestParams:
    def test_constants_match_spec(self):
        from learning import params

        assert params.CHECK_ITEM_FORMATS == ("free", "teachback", "mc_reason")
        assert params.CHECK_ITEM_DIFFICULTIES == (1, 2, 3)
        assert params.CHECK_ITEM_MIN_RUBRIC == 2
        assert params.CHECK_ITEM_MIN_WRONG == 1
        assert params.CHECK_ITEM_MAX_CHUNKS == 8
        assert params.CHECK_ITEM_MAX_CONCEPTS_PER_DOC == 10
        assert params.CHECK_ITEM_OUTPUT_RETRIES == 2
        assert isinstance(params.CHECK_HASH_VERSION, str) and params.CHECK_HASH_VERSION
        assert params.CHECK_ITEM_CONCEPTS_PER_CALL == 3
        assert params.FLEX_TIMEOUT_S == 900
        assert params.CHECK_ITEM_ANSWER_KINDS == ("free", "numeric")
        assert params.CHECK_ITEM_STEPWISE_MIN_STEPS >= 2
        assert params.CHECK_ITEM_FLEX_RETRIES >= 0
        assert params.CHECK_ITEM_BACKFILL_MIN_CHUNK_SCORE == 1

    def test_initial_set_is_every_pair_and_covers_its_consumers(self):
        from learning import params

        pairs = len(params.CHECK_ITEM_FORMATS) * len(params.CHECK_ITEM_DIFFICULTIES)
        assert params.CHECK_ITEM_INITIAL_PER_CONCEPT == pairs == 9
        # §3.5: >= PROBE_ITEMS_PER_SKILL_MAX + 2 isomorphs + 1 post-test reserve
        assert params.CHECK_ITEM_INITIAL_PER_CONCEPT >= params.PROBE_ITEMS_PER_SKILL_MAX + 2 + 1


class TestMigration:
    def test_prefix_is_a_utc_timestamp_and_header_names_the_package(self):
        hits = sorted(MIG_DIR.glob("*_learning_check_items.sql"))
        assert hits, "no learning_check_items migration"
        name = hits[0].name
        assert re.fullmatch(r"\d{14}_learning_check_items\.sql", name), name
        assert "PKG-04" in _migration()

    def test_unique_is_on_course_concept_and_question_hash_only(self):
        sql = _migration()
        uniques = [ln for ln in sql.splitlines() if "UNIQUE" in ln.upper()]
        assert uniques == ["  UNIQUE (course_id, concept_key, question_hash)"], uniques

    def test_items_are_course_assets_with_no_graph_nodes_fk(self):
        sql = _migration()
        assert "REFERENCES" not in sql.upper()
        assert not re.search(r"^\s*node_id\s", sql, re.M), "A2: no node_id column"

    def test_format_difficulty_and_answer_kind_are_check_constrained(self):
        from learning.params import (
            CHECK_ITEM_ANSWER_KINDS,
            CHECK_ITEM_DIFFICULTIES,
            CHECK_ITEM_FORMATS,
        )

        sql = _migration()
        enum = ",".join(f"'{f}'" for f in CHECK_ITEM_FORMATS)
        assert f"CHECK (format IN ({enum}))" in sql
        lo, hi = min(CHECK_ITEM_DIFFICULTIES), max(CHECK_ITEM_DIFFICULTIES)
        assert f"CHECK (difficulty BETWEEN {lo} AND {hi})" in sql
        kinds = ",".join(f"'{k}'" for k in CHECK_ITEM_ANSWER_KINDS)
        assert f"CHECK (answer_kind IN ({kinds}))" in sql

    def test_a22_and_a17_columns_have_safe_defaults(self):
        sql = _migration()
        for col in ("options_json", "correct_option", "canonical_answer", "tolerance"):
            assert re.search(rf"^\s*{col}\s", sql, re.M), col
        assert re.search(r"answer_kind\s+text NOT NULL DEFAULT 'free'", sql)
        assert re.search(r"canonical_verified\s+boolean NOT NULL DEFAULT false", sql)
        assert re.search(r"stepwise\s+boolean NOT NULL DEFAULT false", sql)

    def test_a23_and_a32_columns(self):
        sql = _migration()
        assert re.search(r"source_document_ids\s+text\[\] NOT NULL DEFAULT '\{\}'", sql)
        assert re.search(r"graded\s+boolean NOT NULL DEFAULT false", sql)
        assert (
            "CREATE INDEX IF NOT EXISTS check_items_source_docs_idx "
            "ON check_items USING gin (source_document_ids)"
        ) in sql

    def test_idempotent_and_indexed(self):
        sql = _migration()
        assert "CREATE TABLE IF NOT EXISTS check_items" in sql
        assert (
            "CREATE INDEX IF NOT EXISTS check_items_concept_idx "
            "ON check_items (course_id, concept_key, format, difficulty)"
        ) in sql

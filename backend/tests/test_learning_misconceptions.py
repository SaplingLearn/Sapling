"""PKG-10: misconception store, the slip/misconception/novice rule, the class
rollup, the grade_answer hook. Pure-rule tests need no fixtures; store tests
patch `learning.misconceptions.table`; the rollup test patches `.rpc`."""

from __future__ import annotations

import pathlib
import re

from learning import params

BACKEND = pathlib.Path(__file__).resolve().parents[1]
MIG_DIR = BACKEND / "db" / "migrations"


def _migration() -> str:
    hits = sorted(MIG_DIR.glob("*_learning_misconceptions.sql"))
    assert len(hits) == 1, f"expected exactly one learning_misconceptions migration, got {hits}"
    return hits[0].read_text()


def _function_body(sql: str) -> str:
    start = sql.index("CREATE OR REPLACE FUNCTION misconception_rollup")
    return sql[start : sql.index("$$;", start)]


class TestMigration:
    def test_rollup_floor_literal_matches_params(self):
        sql = _migration()
        assert f"HAVING count(DISTINCT m.user_id) >= {params.MISCONCEPTION_ROLLUP_MIN_USERS}" in sql

    def test_rollup_is_backend_only(self):
        """Executable by service_role only (ADR 0023 §5: a backend function, not a
        tutor tool). Functions grant EXECUTE to PUBLIC by default, so PUBLIC is
        revoked unguarded; the Supabase roles are revoked/granted inside the
        role-existence guard (a plain Postgres has none of them, and an
        unguarded REVOKE naming one aborts the migration — the house idiom of
        20260929050404_learning_ai_tutor_daily_calls.sql)."""
        sql = _migration()
        assert "REVOKE ALL ON FUNCTION misconception_rollup(text) FROM PUBLIC;" in sql
        assert re.search(
            r"FOREACH r IN ARRAY ARRAY\['anon', 'authenticated'\] LOOP\s+"
            r"IF EXISTS \(SELECT 1 FROM pg_roles WHERE rolname = r\) THEN\s+"
            r"EXECUTE format\('REVOKE ALL ON TABLE misconceptions FROM %I', r\);\s+"
            r"EXECUTE format\('REVOKE ALL ON FUNCTION misconception_rollup\(text\) FROM %I', r\);",
            sql,
        )
        assert re.search(
            r"IF EXISTS \(SELECT 1 FROM pg_roles WHERE rolname = 'service_role'\) THEN\s+"
            r"GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE misconceptions TO service_role;\s+"
            r"GRANT EXECUTE ON FUNCTION misconception_rollup\(text\) TO service_role;",
            sql,
        )

    def test_table_is_rls_locked(self):
        """The anon key the frontend ships reaches every public table through
        PostgREST: RLS with no policy denies every non-bypass role."""
        sql = _migration()
        assert "ALTER TABLE misconceptions ENABLE ROW LEVEL SECURITY;" in sql
        assert "REVOKE ALL ON TABLE misconceptions FROM PUBLIC;" in sql
        assert "CREATE POLICY" not in sql

    def test_security_definer_pins_its_search_path(self):
        fn = _function_body(_migration())
        assert "SECURITY DEFINER" in fn
        assert "SET search_path = public, pg_temp" in fn

    def test_rollup_excludes_resolved_rows(self):
        assert "m.resolved_at IS NULL" in _migration()

    def test_rollup_groups_by_course_concept_not_node(self):
        """Spec §13 A29: graph_nodes rows are per user, so a node_id group holds
        one student and never reaches the distinct-user floor. The rollup keys on
        the course concept (the A2 concept_key) and returns it, never a node id."""
        sql = _migration()
        fn = _function_body(sql)
        key = r"lower(btrim(regexp_replace(g.concept_name, '\s+', ' ', 'g')))"
        assert "RETURNS TABLE (concept_key text, wrong_key text, users int)" in fn
        assert f"GROUP BY g.course_id, {key}, m.wrong_key" in fn
        assert "m.node_id," not in fn.split("FROM", 1)[1].split("FROM", 1)[0]
        assert "GROUP BY m.node_id" not in fn

    def test_rollup_concept_key_mirrors_normalize_concept(self):
        """The SQL key must equal the A2 key check_items use. Mirror the SQL
        expression (whitespace runs → one space, trim, lower) in Python. SQL
        lower() stands in for casefold(): they agree on ASCII names and can
        differ on some non-ASCII characters (e.g. ß) — spec §13 A29's known gap."""
        from services.graph_service import _normalize_concept

        for name in [
            "Derivative",
            "  chain   Rule ",
            "Chain\tRule\n",
            "L'Hôpital's Rule",
            "big-O  Notation",
        ]:
            assert re.sub(r"\s+", " ", name).strip(" ").lower() == _normalize_concept(name)

    def test_evidence_text_has_no_unique(self):
        """Spec §4 encryption rule / inv 9: an encrypted column is never a key."""
        sql = _migration()
        col = re.search(r"^\s*evidence_text\s+text,.*$", sql, re.M)
        assert col, "evidence_text column missing"
        assert "UNIQUE" not in col.group(0).upper()
        assert "UNIQUE INDEX" not in sql.upper()
        assert not re.search(r"UNIQUE\s*\([^)]*evidence_text", sql)

    def test_table_and_index_are_idempotent(self):
        sql = _migration()
        assert "CREATE TABLE IF NOT EXISTS misconceptions" in sql
        assert (
            "CREATE INDEX IF NOT EXISTS misconceptions_user_node_idx "
            "ON misconceptions (user_id, node_id, wrong_key)" in sql
        )
        assert "CREATE OR REPLACE FUNCTION misconception_rollup(p_course_id text)" in sql
        assert "node_id        text NOT NULL REFERENCES graph_nodes(id) ON DELETE CASCADE" in sql

    def test_evidence_text_is_in_the_ciphertext_manifest(self):
        """The E2E `ciphertext` oracle samples the encrypted column (the PKG-04 /
        PKG-09 precedent)."""
        from e2e_oracles.gather import _CIPHERTEXT_MANIFEST

        assert ("misconceptions", "id", "evidence_text") in _CIPHERTEXT_MANIFEST

"""IO gatherers for the #400 E2E Chapter 2 oracle CLI.

Wires the pure judges (`judges.py`) to the live LOCAL stack: one shared
psycopg connection (opened lazily, on the first check that needs it) and
plain `httpx` calls authenticated via a minted `sapling_session` cookie
(`services.session_tokens.mint_session`) — never a hand-rolled token.

Hermetic-safety contract: this module must be importable with no DB, no
network, and no service imports at module scope. `psycopg`, `httpx`, and
every `services.*` import are function-local, mirroring
`tests/integration/conftest.py`'s deferred-import pattern (so the
`load_dotenv()` call in `__main__.main()` always wins the ordering race
against `config`/`services` freezing env vars at import time). `gather`
itself carries no top-level side effects, so importing it eagerly from
`__main__.py` (to build the `CHECKS` registry) never trips this contract.

Both DB and HTTP entry points refuse anything but the local stack
(`require_local`, copied semantics from
`tests/integration/conftest.py:48-84`'s `_db_url_is_local`/
`_require_local_db_url`): exact-hostname loopback matching so a URL that
merely *contains* "127.0.0.1" (e.g. `127.0.0.1.evil.com`) is rejected, not
waved through by a substring check. This CLI runs against a developer's own
local Supabase stack ONLY — never staging or production.

Decisions baked into the checks below (Task 3, #400):

- `counts` covers BOTH `documents` (`GET /api/documents/user/{id}`) and
  `notes` (`GET /api/notes/user/{id}`) — `routes/notes.py::list_user_notes`
  DOES expose a plain per-user list (`{"notes": [...]}`, soft-deleted via
  `deleted_at`), a shape directly comparable to the documents list, so the
  brief's documents-only fallback wasn't needed.
- `orphans` ships all six FK-shaped checks the brief specifies verbatim; every
  table/column name was verified against `db/migrations/0001_baseline_schema.sql`,
  `0021_gradebook.sql`, `0023_graph_integrity.sql`, `0025_study_integrity.sql`
  and `db/seed_local_rich.py` — no renames or drops were needed. Every one of
  these FKs is DB-enforced today, so a live run should always find zero rows;
  the checks exist as a defense-in-depth oracle against pre-FK data, partial
  migrations, or a future schema drift that removes the constraint.
"""

from __future__ import annotations

import argparse
from urllib.parse import urlparse

from e2e_oracles import judges
from e2e_oracles.findings import Finding
from e2e_oracles.logscan import scan_file

_LOCAL_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})

# One shared psycopg connection per CLI run (module-global; a fresh process
# per invocation, so this never leaks across runs). Opened lazily by the
# first DB-backed check; closed by `close_conn()` in `__main__.main()`'s
# `finally`.
_conn = None


def require_local(url: str, label: str) -> None:
    """Raise `RuntimeError` unless `url`'s hostname is an EXACT loopback match.

    Guards both `SUPABASE_DB_URL` (before any psycopg connect) and
    `--base-url` (before any HTTP call) — this CLI only ever talks to a
    developer's own local stack. `label` names the offending setting in the
    error so a misconfigured env var or flag is easy to trace.
    """
    try:
        host = (urlparse(url).hostname or "").strip().lower()
    except ValueError:
        host = ""
    if host not in _LOCAL_HOSTS:
        raise RuntimeError(
            f"REFUSING to use non-local {label} ({url!r}): host {host!r} is not "
            "one of 127.0.0.1 / localhost / ::1. This CLI only targets a local "
            "stack, never staging or production."
        )


def _db_conn():
    """Return the shared psycopg connection, opening it on first use."""
    global _conn
    if _conn is None:
        import os

        import psycopg
        from psycopg.rows import dict_row

        url = (os.environ.get("SUPABASE_DB_URL") or "").strip()
        require_local(url, "SUPABASE_DB_URL")
        _conn = psycopg.connect(url, autocommit=True, row_factory=dict_row)
    return _conn


def close_conn() -> None:
    """Close the shared connection if one was opened. Safe to call unconditionally."""
    global _conn
    if _conn is not None:
        _conn.close()
        _conn = None


def _authed_get(args: argparse.Namespace, path: str) -> dict:
    """GET `path` off `args.base_url`, authenticated as `args.user`."""
    import httpx

    from services.session_tokens import SESSION_COOKIE_NAME, mint_session

    require_local(args.base_url, "--base-url")
    resp = httpx.get(
        f"{args.base_url}{path}",
        cookies={SESSION_COOKIE_NAME: mint_session(args.user)},
        timeout=15.0,
    )
    resp.raise_for_status()
    return resp.json()


def run_graph(args: argparse.Namespace) -> tuple[list[Finding], int]:
    """`graph`: `GET /api/graph/{user}` payload vs the DB (#355 oracle)."""
    payload = _authed_get(args, f"/api/graph/{args.user}")
    conn = _db_conn()

    db_nodes = conn.execute(
        "SELECT id, course_id FROM graph_nodes WHERE user_id = %s", (args.user,)
    ).fetchall()
    db_edges = conn.execute(
        "SELECT id, source_node_id, target_node_id, relationship_type "
        "FROM graph_edges WHERE user_id = %s",
        (args.user,),
    ).fetchall()
    enrolled_rows = conn.execute(
        "SELECT DISTINCT co.course_id FROM enrollments e "
        "JOIN course_offerings co ON co.id = e.offering_id "
        "WHERE e.user_id = %s",
        (args.user,),
    ).fetchall()
    enrolled_course_ids = {r["course_id"] for r in enrolled_rows}

    findings = judges.graph_findings(payload, db_nodes, db_edges, enrolled_course_ids)
    return findings, 0


def run_counts(args: argparse.Namespace) -> tuple[list[Finding], int]:
    """`counts`: API-reported list lengths vs the DB's own counts.

    Covers `documents` (`routes/documents.py:370` filters `deleted_at IS
    NULL`) and `notes` (`routes/notes.py::list_user_notes`, same soft-delete
    shape) — see the module docstring for why notes wasn't dropped.
    """
    conn = _db_conn()
    findings: list[Finding] = []

    docs_payload = _authed_get(args, f"/api/documents/user/{args.user}")
    api_doc_count = len(docs_payload.get("documents", []))
    db_doc_count = conn.execute(
        "SELECT count(*) AS n FROM documents WHERE user_id = %s AND deleted_at IS NULL",
        (args.user,),
    ).fetchone()["n"]
    findings.extend(judges.count_findings("documents", api_doc_count, db_doc_count))

    notes_payload = _authed_get(args, f"/api/notes/user/{args.user}")
    api_notes_count = len(notes_payload.get("notes", []))
    db_notes_count = conn.execute(
        "SELECT count(*) AS n FROM notes WHERE user_id = %s AND deleted_at IS NULL",
        (args.user,),
    ).fetchone()["n"]
    findings.extend(judges.count_findings("notes", api_notes_count, db_notes_count))

    return findings, 0


# (table, pk_col, column) manifest — hardcoded, so identifiers never come from
# user input; every value is read via a parameterized `%s`, never interpolated.
_CIPHERTEXT_MANIFEST: tuple[tuple[str, str, str], ...] = (
    ("users", "id", "email"),
    ("user_profiles", "user_id", "name"),
    ("user_profiles", "user_id", "first_name"),
    ("user_profiles", "user_id", "last_name"),
    ("messages", "id", "content"),
    ("room_messages", "id", "text"),
    ("sessions", "id", "summary_json"),
    ("documents", "id", "summary"),
    ("documents", "id", "concept_notes"),
    ("documents", "id", "extracted_text"),
    ("notes", "id", "title"),
    ("notes", "id", "body"),
    ("notes", "id", "last_summary"),
    ("assignments", "id", "notes"),
    ("assignments", "id", "points_possible"),
    ("assignments", "id", "points_earned"),
    ("feedback", "id", "comment"),
    ("feedback", "id", "topic"),
    ("issue_reports", "id", "topic"),
    ("issue_reports", "id", "description"),
)


def run_ciphertext(args: argparse.Namespace) -> tuple[list[Finding], int]:
    """`ciphertext`: sample rows off `_CIPHERTEXT_MANIFEST`, decrypt-and-compare."""
    from services.encryption import decrypt

    conn = _db_conn()
    findings: list[Finding] = []
    for table, pk_col, column in _CIPHERTEXT_MANIFEST:
        # Identifiers come only from the hardcoded manifest above, never from
        # user input — safe to interpolate directly into SQL text.
        rows = conn.execute(
            f'SELECT "{pk_col}", "{column}" FROM "{table}" '
            f'WHERE "{column}" IS NOT NULL LIMIT 50'
        ).fetchall()
        pairs = [(r[pk_col], r[column]) for r in rows]
        findings.extend(judges.ciphertext_findings(table, column, pairs, decrypt))
    return findings, 0


# (check_name, SQL) — each a LEFT JOIN selecting up to 20 orphaned parent-row
# ids whose referenced row is missing. Verified against
# db/migrations/{0001_baseline_schema,0021_gradebook,0023_graph_integrity,
# 0025_study_integrity}.sql and db/seed_local_rich.py's _SUMMARY_ORDER.
_ORPHAN_CHECKS: tuple[tuple[str, str], ...] = (
    (
        "graph_edges->graph_nodes",
        "SELECT ge.id AS id FROM graph_edges ge "
        "LEFT JOIN graph_nodes gs ON gs.id = ge.source_node_id "
        "LEFT JOIN graph_nodes gt ON gt.id = ge.target_node_id "
        "WHERE gs.id IS NULL OR gt.id IS NULL LIMIT 20",
    ),
    (
        "node_mastery_events->graph_nodes",
        "SELECT nme.id AS id FROM node_mastery_events nme "
        "LEFT JOIN graph_nodes n ON n.id = nme.node_id "
        "WHERE n.id IS NULL LIMIT 20",
    ),
    (
        "messages->sessions",
        "SELECT m.id AS id FROM messages m "
        "LEFT JOIN sessions s ON s.id = m.session_id "
        "WHERE s.id IS NULL LIMIT 20",
    ),
    (
        "enrollments->course_offerings",
        "SELECT e.id AS id FROM enrollments e "
        "LEFT JOIN course_offerings co ON co.id = e.offering_id "
        "WHERE co.id IS NULL LIMIT 20",
    ),
    (
        "documents->users",
        "SELECT d.id AS id FROM documents d "
        "LEFT JOIN users u ON u.id = d.user_id "
        "WHERE u.id IS NULL LIMIT 20",
    ),
    (
        "room_messages->rooms",
        "SELECT rm.id AS id FROM room_messages rm "
        "LEFT JOIN rooms r ON r.id = rm.room_id "
        "WHERE r.id IS NULL LIMIT 20",
    ),
)


def run_orphans(args: argparse.Namespace) -> tuple[list[Finding], int]:
    """`orphans`: dangling-FK sweeps over `_ORPHAN_CHECKS`."""
    conn = _db_conn()
    findings: list[Finding] = []
    for check_name, sql in _ORPHAN_CHECKS:
        rows = conn.execute(sql).fetchall()
        orphan_ids = [r["id"] for r in rows]
        findings.extend(judges.orphan_findings(check_name, orphan_ids))
    return findings, 0


def run_logscan(args: argparse.Namespace) -> tuple[list[Finding], int]:
    """`logscan`: scan `args.log` for 5xx responses and tracebacks.

    A missing log file is itself an `oracle-error` finding — most likely
    the local stack isn't up rather than a real logscan result.
    """
    from pathlib import Path

    log_path = Path(args.log)
    if not log_path.exists():
        return [
            Finding(
                oracle="oracle-error",
                summary=f"logscan: log file not found at {log_path} (is the stack up?)",
                evidence={"path": str(log_path)},
            )
        ], 0
    return scan_file(log_path)


def run_ragstore(args: argparse.Namespace) -> tuple[list[Finding], int]:
    """`ragstore`: the RAG vector store exists and is queryable (#481).

    The failure this exists to catch is SILENT. `course_chunks`, the
    `match_course_chunks` RPC and the `vector` extension lived only as
    dashboard DDL, in no migration — so a database replayed purely from
    `python -m db.migrate` had RAG dead end to end while every suite stayed
    green: `retrieve_chunks` swallows the RPC failure into `[]`,
    `_get_catalog_chunk` degrades to `""`, and indexing failures vanish into
    a fire-and-forget log line. The tutor just answers ungrounded.

    So this asserts the store's EXISTENCE, not its contents — an empty
    course_chunks is normal on a fresh stack; a missing one is the bug.
    """
    conn = _db_conn()
    findings: list[Finding] = []

    ext = conn.execute("SELECT 1 FROM pg_extension WHERE extname = 'vector'").fetchone()
    if not ext:
        findings.append(
            Finding(
                oracle="ragstore",
                summary="pgvector extension is not installed — RAG cannot store or query embeddings",
                evidence={"expected": "CREATE EXTENSION vector (migration 0039)"},
            )
        )

    tbl = conn.execute(
        "SELECT 1 FROM information_schema.tables "
        "WHERE table_schema = 'public' AND table_name = 'course_chunks'"
    ).fetchone()
    if not tbl:
        findings.append(
            Finding(
                oracle="ragstore",
                summary="course_chunks table is missing — retrieval degrades to [] with no error",
                evidence={"expected": "migration 0039 creates it"},
            )
        )

    fn = conn.execute(
        "SELECT 1 FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace "
        "WHERE p.proname = 'match_course_chunks'"
    ).fetchone()
    if not fn:
        findings.append(
            Finding(
                oracle="ragstore",
                summary="match_course_chunks RPC is missing — every retrieval silently returns []",
                evidence={"expected": "migration 0039 creates it"},
            )
        )

    # Rows whose embedding never landed are retrievable by nothing: the RPC
    # orders by distance and skips NULLs, so they are dead weight that still
    # counts as "indexed" to the caller (#482).
    if tbl:
        dead = conn.execute(
            "SELECT count(*) AS n FROM course_chunks WHERE embedding IS NULL"
        ).fetchone()
        if dead and dead["n"]:
            findings.append(
                Finding(
                    oracle="ragstore",
                    summary=f"{dead['n']} course_chunks row(s) have a NULL embedding — indexed but unretrievable",
                    evidence={"null_embedding_rows": dead["n"]},
                )
            )

    return findings, 0

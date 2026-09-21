"""#482 — the indexing queue's claims, through the real PostgREST.

The hermetic suite drives `services.document_indexing` against an in-memory
table that honours the filters the module sends — a model of PostgREST someone
typed. These assertions put the same calls through the real one, where it
matters most: the compare-and-swap claim, the forced claim's `or=(...)` lease
filter (a timestamp with colons, inside a logic-tree parameter), and the SQL
claim function's exposure to each role.

Setup rows go in over raw psycopg so the write does not share the layer under
test.
"""
import pytest

from tests.integration.conftest import USER_ACTIVE

pytestmark = pytest.mark.integration

DOC = "itest-482-doc"


def _offering(db_conn) -> str:
    row = db_conn.execute(
        "SELECT id FROM course_offerings WHERE course_id = 'rich-course-cs101' LIMIT 1"
    ).fetchone()
    assert row, "the rich seed should provide an offering for rich-course-cs101"
    return row["id"]


def _insert(db_conn, doc_id=DOC, *, status="pending", attempts=0,
            leased="NULL", age="10 minutes"):
    db_conn.execute(
        f"""
        INSERT INTO documents
            (id, user_id, offering_id, file_name, category, created_at,
             index_status, index_attempts, index_leased_at)
        VALUES (%s, %s, %s, 'itest.pdf', 'lecture_notes',
                now() - interval '{age}', %s, %s, {leased})
        """,
        (doc_id, USER_ACTIVE, _offering(db_conn), status, attempts),
    )


def _row(db_conn, doc_id=DOC) -> dict:
    return db_conn.execute(
        "SELECT index_status, index_attempts, index_leased_at, index_chunk_count, "
        "index_error FROM documents WHERE id = %s", (doc_id,),
    ).fetchone()


# ── the SQL claim ───────────────────────────────────────────────────────────


def test_the_sweeper_claim_works_through_postgrest(db_conn):
    from db.connection import rpc

    _insert(db_conn)

    claimed = rpc("claim_documents_for_indexing",
                  {"max_attempts": 3, "lease_seconds": 600, "batch_size": 10})

    assert {"id": DOC} in claimed
    row = _row(db_conn)
    assert row["index_status"] == "indexing"
    assert row["index_attempts"] == 1
    assert row["index_leased_at"] is not None


def test_a_fresh_upload_is_left_to_its_own_inline_attempt(db_conn):
    from db.connection import rpc

    _insert(db_conn, age="5 seconds")

    claimed = rpc("claim_documents_for_indexing",
                  {"max_attempts": 3, "lease_seconds": 600, "batch_size": 10})

    assert {"id": DOC} not in claimed
    assert _row(db_conn)["index_status"] == "pending"


def test_only_the_backend_role_may_drive_the_queue(db_conn):
    """The frontend ships the anon key; without the REVOKE anyone holding it
    could drive the indexing queue."""
    row = db_conn.execute(
        """
        SELECT has_function_privilege('service_role',
                   'claim_documents_for_indexing(int,int,int)', 'EXECUTE') AS service,
               has_function_privilege('anon',
                   'claim_documents_for_indexing(int,int,int)', 'EXECUTE') AS anon,
               has_function_privilege('authenticated',
                   'claim_documents_for_indexing(int,int,int)', 'EXECUTE') AS authed
        """
    ).fetchone()
    assert row == {"service": True, "anon": False, "authed": False}


# ── the per-row claim ───────────────────────────────────────────────────────


def test_the_own_claim_is_a_compare_and_swap(db_conn):
    """Two callers that both read attempts=0: exactly one wins."""
    from services.document_indexing import _claim_one

    _insert(db_conn)
    stale_read = {"id": DOC, "index_attempts": 0}

    assert _claim_one(stale_read, force=False) is True
    assert _claim_one(stale_read, force=False) is False
    assert _row(db_conn)["index_attempts"] == 1


def test_a_live_lease_is_never_forced(db_conn):
    """The forced claim's `or=(index_status.neq.indexing,index_leased_at.lt.<ts>)`
    carries a timestamp through PostgREST's logic-tree syntax. If that were
    parsed wrongly, force would either steal every live lease or none."""
    from services.document_indexing import _claim_one

    _insert(db_conn, status="indexing", attempts=1, leased="now()")

    assert _claim_one({"id": DOC, "index_attempts": 1}, force=True) is False
    assert _row(db_conn)["index_status"] == "indexing"


def test_an_expired_lease_can_be_forced(db_conn):
    from services.document_indexing import _claim_one

    _insert(db_conn, status="indexing", attempts=1,
            leased="now() - interval '1 hour'")

    assert _claim_one({"id": DOC, "index_attempts": 1}, force=True) is True
    row = _row(db_conn)
    assert row["index_attempts"] == 1   # force reset the budget, then spent one


def test_force_takes_an_exhausted_failed_row(db_conn):
    from services.document_indexing import _claim_one

    _insert(db_conn, status="failed", attempts=3)

    assert _claim_one({"id": DOC, "index_attempts": 3}, force=True) is True
    assert _row(db_conn)["index_status"] == "indexing"


# ── recording the outcome ───────────────────────────────────────────────────


def test_the_outcome_is_recorded_and_the_attempt_time_kept(db_conn):
    from services.document_indexing import IndexOutcome, _finish, _load

    _insert(db_conn, status="indexing", attempts=1, leased="now()")
    lease = _load(DOC)["index_leased_at"]

    _finish(DOC, IndexOutcome("partial", 3, "ServerError"), lease=lease)

    row = _row(db_conn)
    assert row["index_status"] == "partial"
    assert row["index_chunk_count"] == 3
    assert row["index_error"] == "ServerError"
    assert row["index_leased_at"] is not None   # the retry backoff reads it


def test_a_just_failed_document_waits_before_its_retry(db_conn):
    from db.connection import rpc

    _insert(db_conn, status="failed", attempts=1, leased="now() - interval '5 seconds'")

    claimed = rpc("claim_documents_for_indexing",
                  {"max_attempts": 3, "lease_seconds": 600, "batch_size": 10})

    assert {"id": DOC} not in claimed
    assert _row(db_conn)["index_attempts"] == 1


def test_one_sweep_cannot_spend_a_documents_whole_budget(db_conn, monkeypatch):
    """Review round 2, the reviewer's scenario end to end against the real
    claim: a document failing on every attempt during an outage. Before the
    backoff, one pass claimed it, failed it, and was handed it again — three
    attempts inside a few seconds, then exhausted for good."""
    from services import index_sweeper
    from services.document_indexing import IndexOutcome, _finish, _load

    _insert(db_conn, status="failed", attempts=0, leased="NULL")
    driven = []

    def always_fails(doc_id, **kw):
        driven.append(doc_id)
        lease = _load(doc_id)["index_leased_at"]
        _finish(doc_id, IndexOutcome("failed", 0, "ServerError"), lease=lease)

    monkeypatch.setenv("SAPLING_MODEL_MODE", "real")   # the sweeper runs only in real mode
    monkeypatch.setattr(index_sweeper, "index_document", always_fails)

    index_sweeper.sweep_once()

    assert driven.count(DOC) == 1
    assert _row(db_conn)["index_attempts"] == 1


def test_a_terminal_failure_spends_the_budget(db_conn):
    from services.document_indexing import (
        INDEX_MAX_ATTEMPTS, IndexOutcome, _finish, _load,
    )

    _insert(db_conn, status="indexing", attempts=1, leased="now()")
    lease = _load(DOC)["index_leased_at"]

    _finish(DOC, IndexOutcome("failed", 0, "no_extracted_text"), lease=lease)

    assert _row(db_conn)["index_attempts"] == INDEX_MAX_ATTEMPTS


def test_the_check_constraint_rejects_an_unknown_status(db_conn):
    import psycopg

    _insert(db_conn)
    with pytest.raises(psycopg.errors.CheckViolation):
        db_conn.execute("UPDATE documents SET index_status = 'done' WHERE id = %s", (DOC,))


# ── review round 3: only the lease holder records an outcome ────────────────


def test_a_lease_read_back_through_postgrest_matches_itself(db_conn):
    """The SQL claim's lease is a microsecond `now()`; PostgREST hands it back
    as a string, and the finishing write filters on `index_leased_at=eq.<that
    string>`. If the round trip lost precision or mangled the offset, EVERY
    sweeper-driven outcome would silently fail to record."""
    from db.connection import rpc
    from services.document_indexing import IndexOutcome, _finish, _load

    _insert(db_conn)
    rpc("claim_documents_for_indexing",
        {"max_attempts": 3, "lease_seconds": 600, "batch_size": 1})
    lease = _load(DOC)["index_leased_at"]

    _finish(DOC, IndexOutcome("indexed", 4), lease=lease)

    row = _row(db_conn)
    assert row["index_status"] == "indexed"
    assert row["index_chunk_count"] == 4


def test_an_own_claims_lease_matches_too(db_conn):
    from services.document_indexing import IndexOutcome, _claim_one, _finish

    _insert(db_conn)
    lease = _claim_one({"id": DOC, "index_attempts": 0}, force=False)
    assert lease is not None

    _finish(DOC, IndexOutcome("indexed", 2), lease=lease)

    assert _row(db_conn)["index_status"] == "indexed"


def test_an_attempt_that_lost_its_lease_writes_nothing(db_conn):
    from services.document_indexing import IndexOutcome, _finish

    _insert(db_conn, status="indexed", attempts=2, leased="now()")

    _finish(DOC, IndexOutcome("failed", 0, "ServerError"),
            lease="2000-01-01T00:00:00Z")

    row = _row(db_conn)
    assert row["index_status"] == "indexed"
    assert row["index_error"] is None

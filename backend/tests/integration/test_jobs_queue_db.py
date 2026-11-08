"""#116: the job queue's SQL (20261108095241_jobs_queue.sql) against real Postgres.

The hermetic suite (tests/test_jobs.py, tests/test_worker.py) only pins what
services/jobs.py sends and how the worker loop reacts. Everything that makes a
queue a queue is here, against the real functions: SKIP LOCKED between two
claimers, lease expiry re-offering a job, attempts counting, max_attempts
dead-lettering, run_after (and the retry backoff it carries), the dedupe key,
the (worker, attempt) fence on complete/fail, and the service-only privileges.
A queue fake modelled as POP once hid a re-offer bug past a green hermetic
suite (#482); that is why these exist.

Most tests call the functions in SQL over `db_conn` (the migration role). One
round-trips services/jobs.py through the real PostgREST, which is where JSON
arrays become text[], uuids become strings and scalar returns are unwrapped.
"""
import os
import threading
from pathlib import Path

import psycopg
import pytest
from psycopg.rows import dict_row

pytestmark = pytest.mark.integration

LEASE = 300
_MIGRATION = (Path(__file__).resolve().parents[2] / "db" / "migrations"
              / "20261108095241_jobs_queue.sql")
FUNCTIONS = (
    "public.enqueue_job(text, jsonb, text, timestamptz, integer)",
    "public.claim_jobs(text, text[], integer, integer)",
    "public.complete_job(uuid, text, integer)",
    "public.fail_job(uuid, text, integer, text, integer, boolean)",
)


@pytest.fixture
def other_conn(db_conn):
    """A second, independent session on the same database. Depends on db_conn,
    whose fixture has already refused a non-local SUPABASE_DB_URL."""
    conn = psycopg.connect(os.environ["SUPABASE_DB_URL"], autocommit=True,
                           row_factory=dict_row)
    try:
        yield conn
    finally:
        conn.close()


def _enqueue(conn, type_="t.test", payload='{}', *, key=None, run_after=None,
             max_attempts=5) -> dict:
    return conn.execute(
        "SELECT * FROM public.enqueue_job(%s, %s::jsonb, %s, %s, %s)",
        (type_, payload, key, run_after, max_attempts),
    ).fetchone()


def _claim(conn, worker="w1", types=None, limit=10, lease=LEASE) -> list[dict]:
    return conn.execute(
        "SELECT * FROM public.claim_jobs(%s, %s, %s, %s)", (worker, types, limit, lease),
    ).fetchall()


def _complete(conn, job_id, worker, attempt) -> bool:
    return conn.execute("SELECT public.complete_job(%s, %s, %s) AS ok",
                        (job_id, worker, attempt)).fetchone()["ok"]


def _fail(conn, job_id, worker, attempt, *, backoff=0, permanent=False, error="boom"):
    return conn.execute(
        "SELECT public.fail_job(%s, %s, %s, %s, %s, %s) AS status",
        (job_id, worker, attempt, error, backoff, permanent),
    ).fetchone()["status"]


def _row(conn, job_id) -> dict:
    return conn.execute("SELECT * FROM public.jobs WHERE id = %s", (job_id,)).fetchone()


def _expire_lease(conn, job_id) -> None:
    conn.execute(
        "UPDATE public.jobs SET locked_at = now() - make_interval(secs => %s) WHERE id = %s",
        (LEASE + 60, job_id),
    )


# ── claim basics ────────────────────────────────────────────────────────────


def test_a_claim_takes_the_job_counts_the_attempt_and_locks_it(db_conn):
    job = _enqueue(db_conn, payload='{"offering_id": "o1"}')
    assert job["inserted"] is True

    (got,) = _claim(db_conn, "w1")

    assert got["id"] == job["id"]
    assert got["status"] == "running"
    assert got["attempts"] == 1
    assert got["locked_by"] == "w1" and got["locked_at"] is not None
    assert got["payload"] == {"offering_id": "o1"}
    assert _claim(db_conn, "w2") == []  # held by its lease


def test_run_after_in_the_future_is_not_claimed(db_conn):
    job = _enqueue(db_conn, run_after="2999-01-01T00:00:00Z")
    assert _claim(db_conn) == []
    db_conn.execute("UPDATE public.jobs SET run_after = now() - interval '1 second' "
                    "WHERE id = %s", (job["id"],))
    assert [r["id"] for r in _claim(db_conn)] == [job["id"]]


def test_types_limit_what_a_worker_claims(db_conn):
    a = _enqueue(db_conn, "t.a")
    _enqueue(db_conn, "t.b")
    assert [r["id"] for r in _claim(db_conn, types=["t.a"])] == [a["id"]]
    assert [r["type"] for r in _claim(db_conn, types=None)] == ["t.b"]


def test_limit_and_order(db_conn):
    first = _enqueue(db_conn, run_after="2000-01-01T00:00:00Z")
    _enqueue(db_conn)
    _enqueue(db_conn)
    got = _claim(db_conn, limit=1)
    assert [r["id"] for r in got] == [first["id"]]  # oldest run_after first
    assert len(_claim(db_conn, limit=0)) == 0
    assert len(_claim(db_conn, limit=5)) == 2


# ── SKIP LOCKED ─────────────────────────────────────────────────────────────


def test_two_concurrent_claimers_never_get_the_same_job(db_conn, other_conn):
    one = _enqueue(db_conn)
    two = _enqueue(db_conn)
    # B must skip A's locked row, not wait for it: fail fast instead of hanging.
    other_conn.execute("SET lock_timeout = '2s'")
    with db_conn.transaction():
        held = _claim(db_conn, "A", limit=1)  # A's claim is not committed yet
        taken = _claim(other_conn, "B", limit=10)
    assert len(held) == 1 and len(taken) == 1
    assert {held[0]["id"], taken[0]["id"]} == {one["id"], two["id"]}
    rows = {r["id"]: r["locked_by"] for r in db_conn.execute(
        "SELECT id, locked_by FROM public.jobs").fetchall()}
    assert rows == {held[0]["id"]: "A", taken[0]["id"]: "B"}


def test_many_concurrent_claimers_take_every_job_exactly_once(db_conn):
    ids = {_enqueue(db_conn)["id"] for _ in range(60)}
    claimed: list = []
    lock = threading.Lock()
    errors: list = []

    def drain(name):
        try:
            with psycopg.connect(os.environ["SUPABASE_DB_URL"], autocommit=True,
                                 row_factory=dict_row) as conn:
                while True:
                    got = _claim(conn, name, limit=3)
                    if not got:
                        return
                    with lock:
                        claimed.extend(r["id"] for r in got)
        except Exception as exc:  # surfaced below
            errors.append(exc)

    threads = [threading.Thread(target=drain, args=(f"w{i}",)) for i in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    assert not errors
    assert len(claimed) == len(set(claimed)) == 60
    assert set(claimed) == ids


# ── leases ──────────────────────────────────────────────────────────────────


def test_an_expired_lease_is_reoffered_and_the_old_claim_is_fenced_out(db_conn):
    job = _enqueue(db_conn)
    (first,) = _claim(db_conn, "w1")
    _expire_lease(db_conn, job["id"])  # w1 crashed, or is still running long

    (again,) = _claim(db_conn, "w2")

    assert again["id"] == job["id"]
    assert again["attempts"] == 2 and again["locked_by"] == "w2"
    # w1 finishing late cannot overwrite w2's claim, either way.
    assert _complete(db_conn, job["id"], "w1", first["attempts"]) is False
    assert _fail(db_conn, job["id"], "w1", first["attempts"]) is None
    assert _row(db_conn, job["id"])["status"] == "running"
    assert _complete(db_conn, job["id"], "w2", 2) is True
    assert _row(db_conn, job["id"])["status"] == "succeeded"


def test_a_live_lease_is_not_reoffered(db_conn):
    _enqueue(db_conn)
    _claim(db_conn, "w1", lease=3600)
    assert _claim(db_conn, "w2", lease=3600) == []


def test_a_succeeded_job_is_never_offered_again(db_conn):
    job = _enqueue(db_conn)
    (got,) = _claim(db_conn, "w1")
    assert _complete(db_conn, job["id"], "w1", got["attempts"]) is True
    _expire_lease(db_conn, job["id"])
    assert _claim(db_conn, "w2") == []


# ── failure, backoff, dead letter ───────────────────────────────────────────


def test_a_failed_job_waits_out_its_backoff_before_it_is_retried(db_conn):
    job = _enqueue(db_conn)
    (got,) = _claim(db_conn, "w1")

    assert _fail(db_conn, job["id"], "w1", got["attempts"], backoff=3600) == "failed"
    row = _row(db_conn, job["id"])
    assert row["last_error"] == "boom"
    assert _claim(db_conn, "w2") == []  # not re-offered straight back (#482's bug)

    db_conn.execute("UPDATE public.jobs SET run_after = now() - interval '1 second' "
                    "WHERE id = %s", (job["id"],))
    (retry,) = _claim(db_conn, "w2")
    assert retry["id"] == job["id"] and retry["attempts"] == 2


def test_max_attempts_moves_the_job_to_the_dead_letter(db_conn):
    job = _enqueue(db_conn, max_attempts=2)
    (a1,) = _claim(db_conn, "w1")
    assert _fail(db_conn, job["id"], "w1", a1["attempts"]) == "failed"
    (a2,) = _claim(db_conn, "w1")
    assert a2["attempts"] == 2
    assert _fail(db_conn, job["id"], "w1", a2["attempts"], error="still broken") == "dead"
    assert _claim(db_conn, "w1") == []
    row = _row(db_conn, job["id"])
    assert row["status"] == "dead" and row["last_error"] == "still broken"


def test_a_lease_that_runs_out_on_the_last_attempt_is_reaped_dead(db_conn):
    job = _enqueue(db_conn, max_attempts=1)
    (got,) = _claim(db_conn, "w1")
    _expire_lease(db_conn, job["id"])

    assert _claim(db_conn, "w2") == []

    row = _row(db_conn, job["id"])
    assert row["status"] == "dead" and row["last_error"] == "lease_expired"
    # The attempt that merely outlived its lease still records how it ended.
    assert _complete(db_conn, job["id"], "w1", got["attempts"]) is True
    assert _row(db_conn, job["id"])["status"] == "succeeded"


def test_a_permanent_failure_is_dead_at_once(db_conn):
    job = _enqueue(db_conn, max_attempts=5)
    (got,) = _claim(db_conn, "w1")
    assert _fail(db_conn, job["id"], "w1", got["attempts"], permanent=True) == "dead"
    assert _claim(db_conn, "w1") == []


def test_the_error_is_truncated(db_conn):
    job = _enqueue(db_conn)
    (got,) = _claim(db_conn, "w1")
    _fail(db_conn, job["id"], "w1", got["attempts"], error="x" * 5000)
    assert len(_row(db_conn, job["id"])["last_error"]) == 2000


# ── dedupe ──────────────────────────────────────────────────────────────────


def test_the_dedupe_key_collapses_waiting_jobs_but_not_a_running_one(db_conn):
    first = _enqueue(db_conn, key="course_context.refresh:o1",
                     run_after="2999-01-01T00:00:00Z")
    again = _enqueue(db_conn, key="course_context.refresh:o1")
    assert first["inserted"] is True and again["inserted"] is False
    assert again["id"] == first["id"]
    # The second enqueue asked for "now", so the waiting job moved up.
    (got,) = _claim(db_conn, "w1")
    assert got["id"] == first["id"]

    # Running now: a trigger after the run started must not be lost.
    later = _enqueue(db_conn, key="course_context.refresh:o1")
    assert later["inserted"] is True and later["id"] != first["id"]
    other = _enqueue(db_conn, key="course_context.refresh:o2")
    assert other["inserted"] is True
    count = db_conn.execute("SELECT count(*) AS n FROM public.jobs").fetchone()["n"]
    assert count == 3


def test_a_retry_does_not_collide_with_a_newer_waiting_job(db_conn):
    job = _enqueue(db_conn, key="k")
    (got,) = _claim(db_conn, "w1")
    newer = _enqueue(db_conn, key="k")  # queued while the first runs
    # The first fails: it becomes `failed`, outside the unique index.
    assert _fail(db_conn, job["id"], "w1", got["attempts"], backoff=0) == "failed"
    assert newer["id"] != job["id"]


def test_jobs_without_a_dedupe_key_never_collapse(db_conn):
    assert _enqueue(db_conn)["id"] != _enqueue(db_conn)["id"]


# ── schema, privileges, idempotency ─────────────────────────────────────────


def test_status_is_constrained(db_conn):
    with pytest.raises(psycopg.errors.CheckViolation):
        db_conn.execute("INSERT INTO public.jobs (type, status) VALUES ('t.x', 'paused')")


def test_jobs_is_service_only(db_conn):
    assert db_conn.execute(
        "SELECT relrowsecurity FROM pg_class WHERE oid = 'public.jobs'::regclass"
    ).fetchone()["relrowsecurity"]
    assert db_conn.execute(
        "SELECT count(*) AS n FROM pg_policy WHERE polrelid = 'public.jobs'::regclass"
    ).fetchone()["n"] == 0
    roles = [r["rolname"] for r in db_conn.execute(
        "SELECT rolname FROM pg_roles WHERE rolname IN ('anon', 'authenticated', 'service_role')"
    ).fetchall()]
    if set(roles) != {"anon", "authenticated", "service_role"}:
        pytest.skip("needs the Supabase roles")
    for role in ("anon", "authenticated"):
        for priv in ("SELECT", "INSERT", "UPDATE", "DELETE"):
            assert not db_conn.execute(
                "SELECT has_table_privilege(%s, 'public.jobs', %s) AS ok", (role, priv)
            ).fetchone()["ok"], f"{role} holds {priv} on jobs"
        for fn in FUNCTIONS:
            assert not db_conn.execute(
                "SELECT has_function_privilege(%s, %s, 'EXECUTE') AS ok", (role, fn)
            ).fetchone()["ok"], f"{role} can execute {fn}"
    for fn in FUNCTIONS:
        assert db_conn.execute(
            "SELECT has_function_privilege('service_role', %s, 'EXECUTE') AS ok", (fn,)
        ).fetchone()["ok"], f"service_role cannot execute {fn}"
    assert db_conn.execute(
        "SELECT has_table_privilege('service_role', 'public.jobs', 'UPDATE') AS ok"
    ).fetchone()["ok"]


def test_the_migration_is_safe_to_apply_again(db_conn):
    job = _enqueue(db_conn)
    with db_conn.transaction() as tx:
        db_conn.execute(_MIGRATION.read_text())
        assert _row(db_conn, job["id"]) is not None  # nothing dropped or rewritten
        raise psycopg.Rollback(tx)


def test_updated_at_is_maintained(db_conn):
    job = _enqueue(db_conn)
    before = _row(db_conn, job["id"])["updated_at"]
    _claim(db_conn, "w1")
    assert _row(db_conn, job["id"])["updated_at"] > before


# ── through PostgREST, the way the app calls it ─────────────────────────────


def test_services_jobs_round_trip_through_postgrest(db_conn):
    from services import jobs

    out = jobs.enqueue("t.rest", {"offering_id": "o1"}, dedupe_key="rest:o1")
    assert out["inserted"] is True and out["id"]
    assert jobs.enqueue("t.rest", {"offering_id": "o1"}, dedupe_key="rest:o1") == {
        "id": out["id"], "inserted": False}

    (job,) = jobs.claim("w-rest", types=["t.rest"], limit=5, lease_seconds=LEASE)
    assert job.id == out["id"] and job.payload == {"offering_id": "o1"}
    assert job.attempt == 1 and job.locked_by == "w-rest"
    assert jobs.claim("w-other", types=["t.rest"]) == []

    assert jobs.fail(job, "transient") == "failed"
    db_conn.execute("UPDATE public.jobs SET run_after = now() - interval '1 second' "
                    "WHERE id = %s", (job.id,))
    (retry,) = jobs.claim("w-rest", types=["t.rest"])
    assert retry.attempt == 2
    assert jobs.complete(job) is False  # the first claim's fence is stale
    assert jobs.complete(retry) is True
    assert _row(db_conn, job.id)["status"] == "succeeded"

"""#116: the queue upkeep SQL (20261108213623_jobs_upkeep.sql) against real Postgres.

heartbeat_job keeps a long job's lease alive and is fenced like
complete_job/fail_job; prune_jobs deletes only old `succeeded` rows, in bounded
batches; canopy_metrics() reports the queue depth and the dead letters. SQL
only, over `db_conn` (the migration role): the worker's use of these is pinned
hermetically in tests/test_worker.py and tests/test_jobs.py.
"""
from pathlib import Path

import psycopg
import pytest

pytestmark = pytest.mark.integration

LEASE = 300
_MIGRATION = (Path(__file__).resolve().parents[2] / "db" / "migrations"
              / "20261108213623_jobs_upkeep.sql")
FUNCTIONS = (
    "public.heartbeat_job(uuid, text, integer)",
    "public.prune_jobs(integer, integer)",
)


def _enqueue(conn, type_="t.upkeep", *, max_attempts=5) -> str:
    return conn.execute(
        "SELECT id FROM public.enqueue_job(%s, '{}'::jsonb, NULL, NULL, %s)",
        (type_, max_attempts),
    ).fetchone()["id"]


def _claim(conn, worker="w1", lease=LEASE) -> list[dict]:
    return conn.execute(
        "SELECT * FROM public.claim_jobs(%s, NULL, 10, %s)", (worker, lease),
    ).fetchall()


def _beat(conn, job_id, worker, attempt) -> bool:
    return conn.execute("SELECT public.heartbeat_job(%s, %s, %s) AS ok",
                        (job_id, worker, attempt)).fetchone()["ok"]


def _prune(conn, days=14, limit=1000) -> int:
    return conn.execute("SELECT public.prune_jobs(%s, %s) AS n", (days, limit)).fetchone()["n"]


def _row(conn, job_id) -> dict:
    return conn.execute("SELECT * FROM public.jobs WHERE id = %s", (job_id,)).fetchone()


def _age_lease(conn, job_id, seconds) -> None:
    conn.execute(
        "UPDATE public.jobs SET locked_at = now() - make_interval(secs => %s) WHERE id = %s",
        (seconds, job_id),
    )


def _insert(conn, status, *, age="0 seconds", attempts=0) -> str:
    """A row in `status` whose updated_at is `age` (an interval literal) ago.
    updated_at is maintained by a trigger, disabled for the insert."""
    conn.execute("ALTER TABLE public.jobs DISABLE TRIGGER trg_jobs_updated_at")
    try:
        return conn.execute(
            "INSERT INTO public.jobs (type, status, attempts, updated_at)"
            " VALUES ('t.upkeep', %s, %s, now() - %s::interval) RETURNING id",
            (status, attempts, age),
        ).fetchone()["id"]
    finally:
        conn.execute("ALTER TABLE public.jobs ENABLE TRIGGER trg_jobs_updated_at")


def _succeeded(conn, n, *, age_days) -> list[str]:
    return [_insert(conn, "succeeded", age=f"{age_days} days", attempts=1) for _ in range(n)]


# ── heartbeat_job ───────────────────────────────────────────────────────────


def test_a_heartbeat_keeps_a_long_job_from_being_reoffered(db_conn):
    job_id = _enqueue(db_conn)
    (job,) = _claim(db_conn, "w1")
    _age_lease(db_conn, job_id, LEASE - 5)  # nearly out
    assert _beat(db_conn, job_id, "w1", job["attempts"]) is True
    # 300 s have now passed since the claim, plus the 10 s below: without the
    # beat this would be re-offered; with it the lease restarted at the beat.
    db_conn.execute("UPDATE public.jobs SET locked_at = locked_at - interval '10 seconds'"
                    " WHERE id = %s", (job_id,))
    assert _claim(db_conn, "w2") == []
    row = _row(db_conn, job_id)
    assert (row["status"], row["locked_by"], row["attempts"]) == ("running", "w1", 1)


def test_without_a_heartbeat_the_expired_lease_is_reoffered(db_conn):
    """The control for the test above: same setup, no beat."""
    job_id = _enqueue(db_conn)
    _claim(db_conn, "w1")
    _age_lease(db_conn, job_id, LEASE + 5)
    (again,) = _claim(db_conn, "w2")
    assert again["id"] == job_id and again["locked_by"] == "w2"


def test_a_heartbeat_is_fenced_on_worker_and_attempt(db_conn):
    job_id = _enqueue(db_conn)
    (job,) = _claim(db_conn, "w1")
    _age_lease(db_conn, job_id, 100)
    before = _row(db_conn, job_id)["locked_at"]
    assert _beat(db_conn, job_id, "w2", job["attempts"]) is False
    assert _beat(db_conn, job_id, "w1", job["attempts"] + 1) is False
    assert _row(db_conn, job_id)["locked_at"] == before


def test_a_heartbeat_from_a_lost_claim_cannot_take_the_job_back(db_conn):
    job_id = _enqueue(db_conn)
    (first,) = _claim(db_conn, "w1")
    _age_lease(db_conn, job_id, LEASE + 5)
    (second,) = _claim(db_conn, "w2")
    assert _beat(db_conn, job_id, "w1", first["attempts"]) is False
    row = _row(db_conn, job_id)
    assert (row["locked_by"], row["attempts"]) == ("w2", second["attempts"])
    assert _beat(db_conn, job_id, "w2", second["attempts"]) is True


@pytest.mark.parametrize("finish", ["complete", "dead"])
def test_a_heartbeat_does_nothing_to_a_finished_job(db_conn, finish):
    job_id = _enqueue(db_conn, max_attempts=1)
    (job,) = _claim(db_conn, "w1")
    if finish == "complete":
        assert db_conn.execute("SELECT public.complete_job(%s, 'w1', %s) AS ok",
                               (job_id, job["attempts"])).fetchone()["ok"]
    else:  # the lease runs out on the last attempt and the reap kills it
        _age_lease(db_conn, job_id, LEASE + 5)
        assert _claim(db_conn, "w2") == []
        assert _row(db_conn, job_id)["status"] == "dead"
    status = _row(db_conn, job_id)["status"]
    assert _beat(db_conn, job_id, "w1", job["attempts"]) is False
    assert _row(db_conn, job_id)["status"] == status


# ── prune_jobs ──────────────────────────────────────────────────────────────


def test_prune_deletes_only_old_succeeded_rows(db_conn):
    old = _succeeded(db_conn, 3, age_days=20)
    recent = _succeeded(db_conn, 2, age_days=3)
    # Every other status, far older than the cutoff: never pruned.
    others = {st: _insert(db_conn, st, age="60 days", attempts=1)
              for st in ("queued", "failed", "running", "dead")}

    assert _prune(db_conn, days=14) == 3
    left = {r["id"] for r in db_conn.execute("SELECT id FROM public.jobs").fetchall()}
    assert not set(old) & left
    assert set(recent) <= left
    assert set(others.values()) <= left
    # Idempotent: nothing older is left.
    assert _prune(db_conn, days=14) == 0


def test_prune_is_batched(db_conn):
    _succeeded(db_conn, 7, age_days=40)
    assert _prune(db_conn, days=30, limit=3) == 3
    assert _prune(db_conn, days=30, limit=3) == 3
    assert _prune(db_conn, days=30, limit=3) == 1
    assert _prune(db_conn, days=30, limit=3) == 0


@pytest.mark.parametrize("days", [0, -5, None])
def test_prune_never_reaches_inside_a_day(db_conn, days):
    recent = _succeeded(db_conn, 2, age_days=0)
    older = _succeeded(db_conn, 1, age_days=2)
    assert _prune(db_conn, days=days) == (1 if days is not None and days <= 1 else 0)
    left = {r["id"] for r in db_conn.execute("SELECT id FROM public.jobs").fetchall()}
    assert set(recent) <= left
    if days is None:  # NULL means the 30-day default
        assert set(older) <= left


def test_prune_with_a_zero_or_negative_limit_deletes_nothing(db_conn):
    _succeeded(db_conn, 2, age_days=40)
    assert _prune(db_conn, days=30, limit=0) == 0
    assert _prune(db_conn, days=30, limit=-1) == 0


# ── canopy_metrics ──────────────────────────────────────────────────────────


def _metrics(conn) -> dict:
    return conn.execute("SELECT public.canopy_metrics() AS d").fetchone()["d"]


def test_canopy_metrics_reports_queue_depth_and_dead_letters(db_conn):
    before = _metrics(db_conn)
    assert before["counts"]["jobs_dead_lettered"] == {"24h": 0, "7d": 0, "30d": 0}
    assert before["totals"]["jobs_queue_depth"] == 0

    for status in ("queued", "failed", "running"):   # unfinished: the depth
        _insert(db_conn, status, attempts=1)
    _succeeded(db_conn, 2, age_days=1)                # finished: not depth
    for age in ("1 hour", "3 days", "20 days", "45 days"):
        _insert(db_conn, "dead", age=age, attempts=5)

    after = _metrics(db_conn)
    assert after["totals"]["jobs_queue_depth"] == 3
    assert after["counts"]["jobs_dead_lettered"] == {"24h": 1, "7d": 2, "30d": 3}


# ── privileges, re-apply ────────────────────────────────────────────────────


def test_the_upkeep_functions_are_service_only(db_conn):
    roles = [r["rolname"] for r in db_conn.execute(
        "SELECT rolname FROM pg_roles WHERE rolname IN ('anon', 'authenticated', 'service_role')"
    ).fetchall()]
    if set(roles) != {"anon", "authenticated", "service_role"}:
        pytest.skip("needs the Supabase roles")
    for fn in FUNCTIONS:
        for role in ("anon", "authenticated"):
            assert not db_conn.execute(
                "SELECT has_function_privilege(%s, %s, 'EXECUTE') AS ok", (role, fn)
            ).fetchone()["ok"], f"{role} can execute {fn}"
        assert db_conn.execute(
            "SELECT has_function_privilege('service_role', %s, 'EXECUTE') AS ok", (fn,)
        ).fetchone()["ok"], f"service_role cannot execute {fn}"


def test_the_migration_is_safe_to_apply_again(db_conn):
    job_id = _enqueue(db_conn)
    with db_conn.transaction() as tx:
        db_conn.execute(_MIGRATION.read_text())
        assert _row(db_conn, job_id) is not None
        assert "jobs_queue_depth" in _metrics(db_conn)["totals"]
        raise psycopg.Rollback(tx)

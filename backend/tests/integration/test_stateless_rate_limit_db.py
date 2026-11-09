"""#117: the stateless rate limiter + flag version stamp
(20261108220438_stateless_rate_limit_and_flag_version.sql) against real Postgres.

SQL only (no app imports): the hermetic suite (tests/test_stateless_rate_limit.py,
tests/test_feature_flags.py) pins what the app does with the answers; this pins
the SQL itself — the sliding-window claim, the bounded opportunistic prune, and
that the flag version trigger re-creates its one row when it has gone missing.
"""
from pathlib import Path

import psycopg
import pytest

pytestmark = pytest.mark.integration

_MIGRATION = (Path(__file__).resolve().parents[2] / "db" / "migrations"
              / "20261108220438_stateless_rate_limit_and_flag_version.sql")


def _claim(conn, key, limit=2, window=60) -> dict:
    return conn.execute(
        "SELECT hit_id, retry_after FROM public.claim_rate_limit(%s, %s, %s)",
        (key, limit, window),
    ).fetchone()


def _version(conn):
    row = conn.execute("SELECT version FROM public.feature_flags_version").fetchone()
    return None if row is None else row["version"]


# ── claim_rate_limit ────────────────────────────────────────────────────────


def test_a_claim_admits_up_to_the_limit_then_says_when_to_retry(db_conn):
    db_conn.execute("DELETE FROM public.rate_limit_hits WHERE key LIKE 'w8t:%'")
    a, b, c = (_claim(db_conn, "w8t:a") for _ in range(3))
    assert a["hit_id"] and b["hit_id"] and a["retry_after"] is None
    assert c["hit_id"] is None and 1 <= c["retry_after"] <= 60
    assert _claim(db_conn, "w8t:b")["hit_id"]  # keys are independent


@pytest.mark.parametrize("args", [("", 1, 60), ("k", 0, 60), ("k", 1, 0), ("k", 1, 86401)])
def test_bad_arguments_are_refused(db_conn, args):
    with pytest.raises(psycopg.errors.InvalidParameterValue):
        db_conn.execute("SELECT * FROM public.claim_rate_limit(%s, %s, %s)", args)


def test_the_opportunistic_prune_is_bounded(db_conn):
    # 600 day-old hits of a key nobody claims again. The ~1-in-100 prune
    # deletes at most 500 per claim, never all of them in one go, and never a
    # hit younger than a day.
    db_conn.execute("DELETE FROM public.rate_limit_hits")
    db_conn.execute(
        "INSERT INTO public.rate_limit_hits (key, hit_at) "
        "SELECT 'w8t:stale', now() - interval '2 days' - make_interval(secs => g) "
        "FROM generate_series(1, 600) g"
    )
    db_conn.execute("INSERT INTO public.rate_limit_hits (key, hit_at) "
                    "VALUES ('w8t:fresh', now() - interval '23 hours')")

    def stale() -> int:
        return db_conn.execute("SELECT count(*) AS n FROM public.rate_limit_hits "
                               "WHERE key = 'w8t:stale'").fetchone()["n"]

    for i in range(3000):  # P(no prune in 3000 claims) = 0.99^3000 ~ 1e-13
        _claim(db_conn, f"w8t:k{i}", limit=1000, window=60)
        if stale() < 600:
            break
    assert stale() == 100, "one prune removes exactly its 500-row batch"
    assert db_conn.execute("SELECT count(*) AS n FROM public.rate_limit_hits "
                           "WHERE key = 'w8t:fresh'").fetchone()["n"] == 1
    db_conn.execute("DELETE FROM public.rate_limit_hits")


# ── feature_flags_version ───────────────────────────────────────────────────


def _flag_write(conn, key="w8t_flag"):
    conn.execute(
        "INSERT INTO public.feature_flags (key, default_variant) VALUES (%s, 'off') "
        "ON CONFLICT (key) DO UPDATE SET default_variant = EXCLUDED.default_variant",
        (key,),
    )


def test_every_flag_write_bumps_the_version(db_conn):
    # Readers only compare for change. (An upsert fires both the INSERT and
    # the UPDATE statement triggers, so one statement can bump twice.)
    _flag_write(db_conn)
    v1 = _version(db_conn)
    assert v1 is not None
    _flag_write(db_conn)
    v2 = _version(db_conn)
    assert v2 > v1
    db_conn.execute("UPDATE public.feature_flags SET rollout_percent = 5 WHERE key = 'w8t_flag'")
    v3 = _version(db_conn)
    assert v3 == v2 + 1
    db_conn.execute("INSERT INTO public.feature_flag_targets (flag_key, target_type, target_id, "
                    "variant) VALUES ('w8t_flag', 'user', 'w8t-user', 'on')")
    v4 = _version(db_conn)
    assert v4 == v3 + 1
    db_conn.execute("DELETE FROM public.feature_flags WHERE key = 'w8t_flag'")  # + CASCADE
    assert _version(db_conn) > v4


def test_the_version_row_heals_itself_after_a_delete(db_conn):
    _flag_write(db_conn)
    held = _version(db_conn)  # what a replica last saw
    db_conn.execute("DELETE FROM public.feature_flags_version")
    assert _version(db_conn) is None
    _flag_write(db_conn)
    healed = _version(db_conn)
    assert healed is not None and healed != held
    db_conn.execute("UPDATE public.feature_flags SET rollout_percent = 1 WHERE key = 'w8t_flag'")
    assert _version(db_conn) == healed + 1
    assert db_conn.execute("SELECT count(*) AS n FROM public.feature_flags_version"
                           ).fetchone()["n"] == 1


def test_the_migration_is_safe_to_apply_again(db_conn):
    _flag_write(db_conn)
    v = _version(db_conn)
    with db_conn.transaction() as tx:
        db_conn.execute(_MIGRATION.read_text())
        assert _version(db_conn) == v  # the seed never resets a live counter
        assert _claim(db_conn, "w8t:again")["hit_id"]
        raise psycopg.Rollback(tx)

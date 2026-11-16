"""#117 wave 3: the cross-replica lease primitive (20261109022852_app_leases.sql)
against real Postgres.

SQL only (no app imports): tests/test_pg_lease.py pins what the app does with
the answers; this pins the SQL itself — first-claim wins, a renewal by the same
holder extends, an expired lease is taken over, release is holder-fenced,
renew_lease extends only a row its holder still holds (never recreates one),
bad arguments are refused, and the opportunistic prune is bounded.
"""
import psycopg
import pytest

pytestmark = pytest.mark.integration


def _claim(conn, key, holder, ttl=60) -> bool:
    return conn.execute("SELECT public.claim_lease(%s, %s, %s) AS ok",
                        (key, holder, ttl)).fetchone()["ok"]


def _release(conn, key, holder) -> bool:
    return conn.execute("SELECT public.release_lease(%s, %s) AS ok",
                        (key, holder)).fetchone()["ok"]


def _renew(conn, key, holder, ttl=60) -> bool:
    return conn.execute("SELECT public.renew_lease(%s, %s, %s) AS ok",
                        (key, holder, ttl)).fetchone()["ok"]


def _row(conn, key):
    return conn.execute("SELECT holder, acquired_at, expires_at FROM public.app_leases "
                        "WHERE key = %s", (key,)).fetchone()


@pytest.fixture(autouse=True)
def _clean(db_conn):
    db_conn.execute("DELETE FROM public.app_leases WHERE key LIKE 'w3t:%'")
    yield
    db_conn.execute("DELETE FROM public.app_leases WHERE key LIKE 'w3t:%'")


def test_first_claim_wins_and_a_second_holder_is_refused(db_conn):
    assert _claim(db_conn, "w3t:a", "h1") is True
    assert _claim(db_conn, "w3t:a", "h2") is False
    assert _row(db_conn, "w3t:a")["holder"] == "h1"
    assert _claim(db_conn, "w3t:b", "h2") is True  # keys are independent


def test_the_same_holder_renews_and_keeps_acquired_at(db_conn):
    assert _claim(db_conn, "w3t:a", "h1", ttl=5)
    before = _row(db_conn, "w3t:a")
    assert _claim(db_conn, "w3t:a", "h1", ttl=600) is True
    after = _row(db_conn, "w3t:a")
    assert after["acquired_at"] == before["acquired_at"]
    assert after["expires_at"] > before["expires_at"]


def test_an_expired_lease_is_taken_over(db_conn):
    assert _claim(db_conn, "w3t:a", "h1")
    db_conn.execute("UPDATE public.app_leases SET expires_at = now() - interval '1 second' "
                    "WHERE key = 'w3t:a'")
    assert _claim(db_conn, "w3t:a", "h2") is True
    assert _row(db_conn, "w3t:a")["holder"] == "h2"


def test_release_is_fenced_on_the_holder(db_conn):
    assert _claim(db_conn, "w3t:a", "h1")
    assert _release(db_conn, "w3t:a", "h2") is False
    assert _row(db_conn, "w3t:a") is not None
    assert _release(db_conn, "w3t:a", "h1") is True
    assert _row(db_conn, "w3t:a") is None
    assert _release(db_conn, "w3t:a", "h1") is False


def test_renew_extends_only_the_holders_live_row_and_never_recreates_one(db_conn):
    assert _claim(db_conn, "w3t:a", "h1", ttl=5)
    before = _row(db_conn, "w3t:a")
    assert _renew(db_conn, "w3t:a", "h1", ttl=600) is True
    after = _row(db_conn, "w3t:a")
    assert after["expires_at"] > before["expires_at"]
    assert after["acquired_at"] == before["acquired_at"]
    assert _renew(db_conn, "w3t:a", "h2") is False
    assert _row(db_conn, "w3t:a")["holder"] == "h1"
    # A renewal that lands after its own release brings nothing back.
    assert _release(db_conn, "w3t:a", "h1") is True
    assert _renew(db_conn, "w3t:a", "h1") is False
    assert _row(db_conn, "w3t:a") is None


@pytest.mark.parametrize("args", [
    ("", "h", 60), ("k", "", 60), ("k", "h", 0), ("k", "h", 86401), ("k" * 301, "h", 60),
])
def test_bad_arguments_are_refused(db_conn, args):
    with pytest.raises(psycopg.errors.InvalidParameterValue):
        db_conn.execute("SELECT public.claim_lease(%s, %s, %s)", args)


def test_the_opportunistic_prune_is_bounded(db_conn):
    # 600 leases that expired two hours ago. The ~1-in-100 prune deletes at
    # most 500 per claim, and never a lease that expired under an hour ago.
    db_conn.execute("DELETE FROM public.app_leases WHERE expires_at < now()")
    db_conn.execute(
        "INSERT INTO public.app_leases (key, holder, acquired_at, expires_at) "
        "SELECT 'w3t:stale' || g, 'h', now() - interval '3 hours', "
        "now() - interval '2 hours' - make_interval(secs => g) "
        "FROM generate_series(1, 600) g"
    )
    db_conn.execute("INSERT INTO public.app_leases (key, holder, acquired_at, expires_at) "
                    "VALUES ('w3t:recent', 'h', now() - interval '1 hour', "
                    "now() - interval '50 minutes')")

    def stale() -> int:
        return db_conn.execute("SELECT count(*) AS n FROM public.app_leases "
                               "WHERE key LIKE 'w3t:stale%'").fetchone()["n"]

    for i in range(3000):  # P(no prune in 3000 claims) = 0.99^3000 ~ 1e-13
        _claim(db_conn, f"w3t:k{i}", "h")
        if stale() < 600:
            break
    assert stale() == 100, "one prune removes exactly its 500-row batch"
    assert _row(db_conn, "w3t:recent") is not None

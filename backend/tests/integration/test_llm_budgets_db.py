"""#119: the LLM budget + cost-signal SQL (20261108213311_llm_budgets_and_cost_signal.sql)
against real Postgres.

The hermetic suite (tests/test_llm_budget.py) pins what services/llm_budget.py
does with the status the function returns; this pins the function itself:
override resolution (user -> most generous role -> default -> none), the UTC
day window over llm_usage, the weekly cost-per-active-user arithmetic and its
"2x jump", and the service-only privileges. Raw SQL over `db_conn` only.
"""
from pathlib import Path

import psycopg
import pytest

pytestmark = pytest.mark.integration

_MIGRATION = (Path(__file__).resolve().parents[2] / "db" / "migrations"
              / "20261108213311_llm_budgets_and_cost_signal.sql")
FUNCTIONS = (
    "public.llm_budget_status(text)",
    "public.llm_cost_per_active_user_weekly()",
)
U = "llmb-user-a"


@pytest.fixture
def world(db_conn):
    db_conn.execute(
        "INSERT INTO users (id, email) VALUES (%s, 'llmb-a@example.com') ON CONFLICT DO NOTHING",
        (U,),
    )
    db_conn.execute("DELETE FROM public.llm_budgets")
    yield db_conn
    db_conn.execute("DELETE FROM public.llm_budgets")
    db_conn.execute("DELETE FROM public.llm_usage WHERE user_id LIKE 'llmb-%'")
    db_conn.execute("DELETE FROM public.user_roles WHERE user_id LIKE 'llmb-%'")
    db_conn.execute("DELETE FROM public.roles WHERE slug LIKE 'llmb-%'")


def _status(conn, user=U) -> dict:
    return conn.execute("SELECT public.llm_budget_status(%s) AS s", (user,)).fetchone()["s"]


def _budget(conn, scope, subject, limit):
    conn.execute(
        "INSERT INTO public.llm_budgets (scope, subject, daily_token_limit) VALUES (%s, %s, %s)",
        (scope, subject, limit),
    )


def _role(conn, slug, user=U):
    rid = conn.execute(
        "INSERT INTO public.roles (name, slug, color) VALUES (%s, %s, '#000') RETURNING id",
        (slug, slug),
    ).fetchone()["id"]
    conn.execute("INSERT INTO public.user_roles (user_id, role_id) VALUES (%s, %s)", (user, rid))


def _usage(conn, tokens, *, ago="0 seconds", user=U, cost=None):
    conn.execute(
        "INSERT INTO public.llm_usage (user_id, feature, model, total_tokens, cost_usd, created_at) "
        "VALUES (%s, 'test', 'claude-haiku-5-5', %s, %s, now() - %s::interval)",
        (user, tokens, cost, ago),
    )


# ── llm_budget_status ───────────────────────────────────────────────────────


def test_no_rows_means_unlimited(world):
    s = _status(world)
    assert s["limit"] is None and s["source"] == "none" and s["used"] == 0


def test_resolution_order_user_then_most_generous_role_then_default(world):
    _budget(world, "default", "", 1000)
    assert (_status(world)["limit"], _status(world)["source"]) == (1000, "default")

    _role(world, "llmb-small")
    _role(world, "llmb-big")
    _budget(world, "role", "llmb-small", 5000)
    _budget(world, "role", "llmb-big", 9000)
    assert (_status(world)["limit"], _status(world)["source"]) == (9000, "role:llmb-big")

    _role(world, "llmb-unlimited")
    _budget(world, "role", "llmb-unlimited", None)
    assert (_status(world)["limit"], _status(world)["source"]) == (None, "role:llmb-unlimited")

    _budget(world, "user", U, 10)
    assert (_status(world)["limit"], _status(world)["source"]) == (10, "user")


def test_a_role_override_for_a_role_the_user_lacks_does_not_apply(world):
    _budget(world, "default", "", 1000)
    world.execute("INSERT INTO public.roles (name, slug, color) VALUES ('x', 'llmb-other', '#000')")
    _budget(world, "role", "llmb-other", 99)
    assert _status(world)["source"] == "default"


def test_used_counts_this_utc_day_for_this_user_only(world):
    _budget(world, "default", "", 1000)
    _usage(world, 300)
    _usage(world, 200)
    _usage(world, 5000, ago="2 days")  # yesterday's spend never counts
    _usage(world, 7000, user="llmb-someone-else")
    s = _status(world)
    assert s["used"] == 500
    window = world.execute(
        "SELECT date_trunc('day', now() AT TIME ZONE 'UTC') AT TIME ZONE 'UTC' AS d"
    ).fetchone()["d"]
    got = world.execute(
        "SELECT %s::timestamptz AS ws, %s::timestamptz AS ra",
        (s["window_start"], s["reset_at"]),
    ).fetchone()
    assert got["ws"] == window
    assert (got["ra"] - got["ws"]).total_seconds() == 86400


def test_limits_are_constrained(world):
    with pytest.raises(psycopg.errors.CheckViolation):
        _budget(world, "default", "someone", 1)
    with pytest.raises(psycopg.errors.CheckViolation):
        _budget(world, "user", "", 1)
    with pytest.raises(psycopg.errors.CheckViolation):
        _budget(world, "user", U, -1)
    with pytest.raises(psycopg.errors.CheckViolation):
        _budget(world, "team", "x", 1)


# ── llm_cost_per_active_user_weekly ─────────────────────────────────────────


def _active(conn, user, ago, category="usage"):
    conn.execute(
        "INSERT INTO public.events (event_type, category, user_id, created_at) "
        "VALUES ('test.active', %s, %s, now() - %s::interval)",
        (category, user, ago),
    )


def test_cost_per_active_user_and_the_2x_jump(world):
    world.execute("DELETE FROM public.llm_usage")
    world.execute("DELETE FROM public.events")
    # Trailing four weeks: $1 per active user each week (2 users, $2).
    for week in range(1, 5):
        ago = f"{7 * week + 3} days"
        _active(world, "llmb-u1", ago)
        _active(world, "llmb-u2", ago)
        _usage(world, 10, ago=ago, user="llmb-u1", cost=2.0)
    # This week: one active user, $3 -> 3x the baseline.
    _active(world, "llmb-u1", "1 day")
    _active(world, "llmb-u2", "1 day", category="system")  # never counts as active
    _usage(world, 10, ago="1 day", user="llmb-u1", cost=3.0)
    _usage(world, 10, ago="1 day", user="llmb-u1", cost=None)  # unpriced row

    s = world.execute("SELECT public.llm_cost_per_active_user_weekly() AS s").fetchone()["s"]
    assert float(s["usd_per_active_user_7d"]) == pytest.approx(3.0)
    assert float(s["baseline_usd_per_active_user"]) == pytest.approx(1.0)
    assert s["baseline_weeks"] == 4
    assert float(s["ratio"]) == pytest.approx(3.0)
    assert s["jump"] is True
    assert [w["week"] for w in s["weeks"]] == [0, 1, 2, 3, 4]
    assert s["weeks"][0]["active_users"] == 1


def test_no_active_users_gives_no_answer_rather_than_zero(world):
    world.execute("DELETE FROM public.llm_usage")
    world.execute("DELETE FROM public.events")
    s = world.execute("SELECT public.llm_cost_per_active_user_weekly() AS s").fetchone()["s"]
    assert s["usd_per_active_user_7d"] is None
    assert s["ratio"] is None and s["jump"] is None
    assert s["baseline_weeks"] == 0


# ── schema, privileges, idempotency ─────────────────────────────────────────


def test_llm_budgets_is_service_only(db_conn):
    assert db_conn.execute(
        "SELECT relrowsecurity FROM pg_class WHERE oid = 'public.llm_budgets'::regclass"
    ).fetchone()["relrowsecurity"]
    roles = [r["rolname"] for r in db_conn.execute(
        "SELECT rolname FROM pg_roles WHERE rolname IN ('anon', 'authenticated', 'service_role')"
    ).fetchall()]
    if set(roles) != {"anon", "authenticated", "service_role"}:
        pytest.skip("needs the Supabase roles")
    for role in ("anon", "authenticated"):
        for priv in ("SELECT", "INSERT", "UPDATE", "DELETE"):
            assert not db_conn.execute(
                "SELECT has_table_privilege(%s, 'public.llm_budgets', %s) AS ok", (role, priv)
            ).fetchone()["ok"], f"{role} holds {priv} on llm_budgets"
        for fn in FUNCTIONS:
            assert not db_conn.execute(
                "SELECT has_function_privilege(%s, %s, 'EXECUTE') AS ok", (role, fn)
            ).fetchone()["ok"], f"{role} can execute {fn}"
    for fn in FUNCTIONS:
        assert db_conn.execute(
            "SELECT has_function_privilege('service_role', %s, 'EXECUTE') AS ok", (fn,)
        ).fetchone()["ok"], f"service_role cannot execute {fn}"


def test_the_migration_is_safe_to_apply_again_and_keeps_an_edited_default(world):
    _budget(world, "default", "", 123)
    with world.transaction() as tx:
        world.execute(_MIGRATION.read_text())
        assert _status(world)["limit"] == 123  # the seed never overwrites an admin's value
        raise psycopg.Rollback(tx)

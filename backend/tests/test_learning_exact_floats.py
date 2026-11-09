"""Exact floats on every PostgREST read (spec §13 A136), the hermetic half.

The Supabase image sets extra_float_digits = 0, so float8 output is rounded to
15 significant digits and real output to 6. 20261108162223 sets the role
PostgREST runs the backend's requests as (service_role) to 3, which PostgREST
applies per request, and adds learning_float_probe() for the release fence.
The real-Postgres half (PostgREST applies it; the values round-trip):
tests/integration/test_exact_floats_db.py.
"""

from __future__ import annotations

import pathlib
import re

BACKEND = pathlib.Path(__file__).resolve().parents[1]
MIGRATIONS = BACKEND / "db" / "migrations"


def _sql() -> str:
    (path,) = sorted(MIGRATIONS.glob("*_learning_exact_floats.sql"))
    return "\n".join(
        line for line in path.read_text().splitlines() if not line.lstrip().startswith("--")
    )


def test_the_service_role_reads_floats_exactly_and_the_statement_is_guarded():
    sql = _sql()
    guard = "IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'service_role') THEN"
    setting = "ALTER ROLE service_role SET extra_float_digits = 3;"
    assert sql.index(guard) < sql.index(setting)
    # only the role the backend's key runs as; never the server or a database default
    assert re.findall(r"ALTER\s+(ROLE|DATABASE|SYSTEM)\s+(\w+)", sql, re.I) == [("ROLE", "service_role")]


def test_postgrest_is_told_to_reload_its_config_and_schema():
    sql = _sql()
    assert "NOTIFY pgrst, 'reload config';" in sql
    assert "NOTIFY pgrst, 'reload schema';" in sql


def test_the_probe_measures_the_sessions_setting_and_only_service_role_may_call_it():
    sql = _sql()
    head = re.search(
        r"CREATE OR REPLACE FUNCTION public\.learning_float_probe\(\)(.*?)AS \$\$", sql, re.S
    ).group(1)
    assert "STABLE" in head  # PostgREST runs a GET of it in a read-only transaction
    assert "extra_float_digits" not in head  # a SET of its own would measure nothing
    assert "REVOKE ALL ON FUNCTION public.learning_float_probe() FROM PUBLIC;" in sql
    assert "ARRAY['anon', 'authenticated']" in sql
    assert "GRANT EXECUTE ON FUNCTION public.learning_float_probe() TO service_role;" in sql
    body = re.search(r"AS \$\$(.*?)\$\$;", sql, re.S).group(1)
    assert "FROM" not in body.upper().replace("PG_CATALOG", "")  # constants only, no table


def test_the_probe_values_round_to_something_else_at_the_image_default():
    """The probe discriminates: at 15 / 6 significant digits each value parses
    back to a different number."""
    import struct

    float8 = 0.30000000000000004
    assert float8 == 0.1 + 0.2 and float(f"{float8:.15g}") != float8
    single = struct.unpack("<f", struct.pack("<f", 0.12345679))[0]
    rounded = struct.unpack("<f", struct.pack("<f", float(f"{single:.6g}")))[0]
    assert rounded != single


#: Spec §13 A148: the one other way the backend reaches PostgREST. Under the
#: `db_user_scope` flag (RLS step 2, #115) db/user_jwt.py sends the anon key as
#: `apikey` with a backend-minted JWT whose role is `authenticated`, and
#: 20261109032302_learning_loop_rls.sql gives `authenticated` the same setting.
USER_SCOPED_SEAM = "db/user_jwt.py"


def test_the_backend_reaches_postgrest_with_the_service_key_or_the_user_scope_only():
    """The role setting covers every PostgREST read because the backend sends
    the service key, or (db_user_scope) a minted `authenticated` JWT whose
    role carries the setting too; any other anon-key client would bypass it."""
    from db import connection

    assert connection._HEADERS["Authorization"] == f"Bearer {connection.SUPABASE_KEY}"
    source = (BACKEND / "db" / "connection.py").read_text()
    assert 'os.getenv("SUPABASE_SERVICE_KEY"' in source
    offenders = [
        str(path.relative_to(BACKEND))
        for top in ("routes", "services", "learning", "agents", "db", "scripts", "main.py")
        for path in ([BACKEND / top] if top.endswith(".py") else (BACKEND / top).rglob("*.py"))
        if "SUPABASE_ANON_KEY" in path.read_text()
    ]
    assert offenders == [USER_SCOPED_SEAM]
    from db import user_jwt

    assert user_jwt.ROLE == "authenticated"
    rls = (BACKEND / "db" / "migrations" / "20261109032302_learning_loop_rls.sql").read_text()
    assert "ALTER ROLE authenticated SET extra_float_digits = 3;" in rls

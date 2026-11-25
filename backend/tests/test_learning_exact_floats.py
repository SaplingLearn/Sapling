"""Exact floats on every PostgREST read (spec §13 A136), the hermetic half.

The Supabase image sets extra_float_digits = 0, so float8 output is rounded to
15 significant digits and real output to 6. 20261108162223 sets the role
PostgREST runs the backend's requests as (service_role) to 3, which PostgREST
applies per request. That only covers every read if the backend reaches
PostgREST as that role (or the user scope's role, which carries it too): the
check below. The setting itself, the probe and the round trip are proven on
real Postgres in tests/integration/test_exact_floats_db.py.
"""

from __future__ import annotations

from db.migration_units import MIGRATION_UNITS
import pathlib

BACKEND = pathlib.Path(__file__).resolve().parents[1]


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
    rls = (MIGRATION_UNITS / "20261109032302_learning_loop_rls.sql").read_text()
    assert "ALTER ROLE authenticated SET extra_float_digits = 3;" in rls

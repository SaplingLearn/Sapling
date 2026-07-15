"""Opt-in HTTP end-to-end test against the REAL staging database.

This is NOT a normal unit test: it drives the live FastAPI routes against staging
and writes a throwaway fixture (cleaned up afterward). It is skipped by default so
the regular suite / CI never touches staging. To run it:

    RUN_STAGING_E2E=1 dotenv -f .env.staging run -- python -m pytest tests/test_e2e_staging.py -v

The `e2e_staging` marker tells conftest to leave the live Supabase client + the real
auth guard in place (the hermetic mock + auth bypass are skipped for this test only).
The actual journeys live in db/e2e_staging_http.py and db/e2e_checks/.
"""
import os

import pytest


@pytest.mark.e2e_staging
@pytest.mark.skipif(
    os.getenv("RUN_STAGING_E2E") != "1",
    reason="staging HTTP E2E: set RUN_STAGING_E2E=1 (with .env.staging) to run; it writes to staging",
)
def test_staging_http_e2e():
    from db.e2e_staging_http import main

    rc = main()
    assert rc == 0, "staging HTTP E2E reported failing checks (see the printed PASS/FAIL lines)"

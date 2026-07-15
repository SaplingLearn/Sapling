"""Per-domain HTTP E2E journeys for db/e2e_staging_http.py. Each module exposes
`run()`, which imports the shared harness primitives from db.e2e_staging_http and
calls `check(name, ok, detail)` for every assertion. STAGING ONLY."""

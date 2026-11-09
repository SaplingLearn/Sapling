"""Background job worker (#116): `python -m worker`, run from `backend/`.

Drains the Postgres `jobs` queue (services/jobs.py). Same image and code as the
API; a separate process. See worker/__main__.py for the boot checks and flags.
"""

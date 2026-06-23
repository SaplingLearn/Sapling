"""One-off ops script: approve a user and grant them the `admin` role in staging.

Bootstraps the first staging admin, which the in-app `assign_role` endpoint can't do
(it requires an *existing* admin). The user must have signed into staging at least
once (so their row exists).

Matches by decrypted email (see db/_staging_ops.user_email_index). The `admin`
role_id is a per-project UUID, so it's looked up by slug='admin', not hardcoded.
Idempotent. Targets STAGING only.

Usage (from backend/):
    venv/bin/python -m db.grant_staging_admin aflopez@bu.edu          # preview
    venv/bin/python -m db.grant_staging_admin aflopez@bu.edu --yes    # apply
"""

from __future__ import annotations

import argparse
import sys

from db._staging_ops import confirm_write, dotenv_value, set_encryption_key, user_email_index


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("email")
    ap.add_argument("--staging-env", default=".env.staging")
    ap.add_argument("--yes", action="store_true", help="apply the grant (default: preview)")
    args = ap.parse_args()

    set_encryption_key(args.staging_env)  # before importing services.encryption
    db_url = dotenv_value(args.staging_env, "SUPABASE_DB_URL")

    import psycopg

    target = args.email.strip().lower()

    with psycopg.connect(db_url, connect_timeout=15) as conn, conn.cursor() as cur:
        match = user_email_index(cur).get(target)
        if match is None:
            print(
                f"ERROR: no staging user with email {target!r}. "
                f"Have them sign into staging once, then re-run."
            )
            return 1
        uid, approved = match

        cur.execute("SELECT id FROM roles WHERE slug = 'admin'")
        role_row = cur.fetchone()
        if not role_row:
            print("ERROR: no role with slug='admin' in staging.")
            return 1
        admin_role_id = role_row[0]

        print(f"{target} -> id={uid} (currently approved={approved})")
        if not confirm_write(db_url, args.yes, "approve + grant admin"):
            return 0

        cur.execute("UPDATE users SET is_approved = true WHERE id = %s", (uid,))
        cur.execute(
            "INSERT INTO user_roles (user_id, role_id, granted_by) "
            "VALUES (%s, %s, %s) ON CONFLICT (user_id, role_id) DO NOTHING",
            (uid, admin_role_id, "bootstrap:grant_staging_admin"),
        )
        conn.commit()

        cur.execute(
            "SELECT u.is_approved, "
            "coalesce(string_agg(r.slug, ',' ORDER BY r.slug), '') "
            "FROM users u "
            "LEFT JOIN user_roles ur ON ur.user_id = u.id "
            "LEFT JOIN roles r ON r.id = ur.role_id "
            "WHERE u.id = %s GROUP BY u.is_approved",
            (uid,),
        )
        is_approved, roles = cur.fetchone()
    print(f"OK: {target} (id={uid}) -> approved={is_approved}, roles=[{roles}]")
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""One-off ops script: approve staging user accounts by email (is_approved=true).

This is the access gate the sign-in flow checks: a brand-new sign-in always lands
`is_approved=false` and there's no auto-approve path, so accounts must be approved
out of band. Mirrors the admin portal's `user.approve`, but works directly against
the DB (handy for bootstrapping before anyone is an admin).

Matches by decrypted email (see db/_staging_ops.user_email_index). Emails with no
user row yet (haven't signed into staging) are reported PENDING and skipped — they
can't be pre-approved because sign-in matches on google_id, not email. Idempotent.
Targets STAGING only.

Usage (from backend/):
    venv/bin/python -m db.approve_staging_users a@bu.edu b@bu.edu        # preview
    venv/bin/python -m db.approve_staging_users a@bu.edu b@bu.edu --yes  # apply
"""

from __future__ import annotations

import argparse
import sys

from db._staging_ops import confirm_write, dotenv_value, set_encryption_key, user_email_index


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("emails", nargs="+")
    ap.add_argument("--staging-env", default=".env.staging")
    ap.add_argument("--yes", action="store_true", help="apply approvals (default: preview)")
    args = ap.parse_args()

    set_encryption_key(args.staging_env)  # before importing services.encryption
    db_url = dotenv_value(args.staging_env, "SUPABASE_DB_URL")

    import psycopg

    targets = {e.strip().lower() for e in args.emails}

    with psycopg.connect(db_url, connect_timeout=15) as conn, conn.cursor() as cur:
        index = user_email_index(cur)
        to_approve = []  # (email, uid, was_approved)
        pending = []  # email with no row yet
        for email in sorted(targets):
            if email in index:
                uid, was = index[email]
                to_approve.append((email, uid, was))
            else:
                pending.append(email)

        applying = confirm_write(db_url, args.yes, f"approve {len(to_approve)} account(s)")
        if applying:
            for email, uid, was in to_approve:
                if not was:
                    cur.execute("UPDATE users SET is_approved = true WHERE id = %s", (uid,))
            conn.commit()

    verb = "approved" if args.yes else "would approve"
    for email, uid, was in to_approve:
        state = "already approved" if was else verb
        print(f"  ✓ {email}  ({uid})  -> {state}")
    for email in pending:
        print(f"  … {email}  -> PENDING: no staging account yet (must sign in once)")
    print(f"\n{len(to_approve)} matched, {len(pending)} pending.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

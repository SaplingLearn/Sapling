"""
Replace every stored Gradescope password with the session it logs in to, once.

Before 2026-11-16, connecting Gradescope with an email and password stored the
password (encrypted, but reversible) and logged in with it on every sync. Now
the password is used for one login and only the resulting session cookies are
stored (services/gradescope/credentials.py). A legacy row converts itself on
its next sync or course listing; this script converts the rest:

  each auth_mode='password' row -> log in once (Remember me), store the
                                   session as auth_mode='cookies' (via
                                   'password'), null password_encrypted and
                                   email_encrypted
  ...that Gradescope rejects    -> left as it is and reported; its next sync
                                   marks it needs_reauth and the student
                                   reconnects. --drop-rejected deletes those
                                   rows instead (course links are kept; the
                                   student sees "not connected")
  ...Gradescope unreachable     -> left as it is; re-run later

Dry-run by default (counts only, no logins). Run from backend/:
    python scripts/retire_gradescope_passwords.py            # preview
    python scripts/retire_gradescope_passwords.py --apply

Reads .env; for staging/prod run under `dotenv -f .env.<env> run -- ...` and
check the project it prints first. --apply needs that environment's
ENCRYPTION_KEY and aborts unless the key canary opens. A second run is a
no-op. When every environment reports 0 password rows, a migration can drop
`password_encrypted` and the password branch of the payload check
(docs/security/data-inventory.md).
"""
import argparse
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv

BASE = Path(__file__).parent.parent
load_dotenv(BASE / ".env")
sys.path.insert(0, str(BASE))

from db.connection import REST_URL, page_all, table  # noqa: E402
from services.encryption_canary import abort_unless_key_verified  # noqa: E402
from services.gradescope.credentials import retire_stored_password  # noqa: E402

#: Seconds between live logins, so a batch never looks like an attack.
PAUSE_S = 2.0


def _password_rows() -> list[dict]:
    return list(page_all(
        table("gradescope_credentials"), "user_id",
        filters={"auth_mode": "eq.password"}, order="user_id",
    ))


def main(argv: list[str] | None = None) -> dict:
    parser = argparse.ArgumentParser(description="Replace stored Gradescope passwords with sessions.")
    parser.add_argument("--dry-run", action="store_true", default=True)
    parser.add_argument("--apply", dest="dry_run", action="store_false")
    parser.add_argument("--drop-rejected", action="store_true",
                        help="Delete rows whose stored password Gradescope rejects.")
    parser.add_argument("--pause", type=float, default=PAUSE_S, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)

    print(f"Project: {urlparse(REST_URL).hostname}")
    if not args.dry_run:
        # It decrypts the stored passwords and writes encrypted sessions.
        abort_unless_key_verified("scripts.retire_gradescope_passwords")

    rows = _password_rows()
    print(f"{len(rows)} credential row(s) still hold a password.")
    summary = {"converted": 0, "rejected": 0, "dropped": 0, "unreachable": 0,
               "changed": 0, "unreadable": 0, "not_password": 0}
    if args.dry_run:
        print("\nDRY RUN — nothing logged in to or written. Re-run with --apply.")
        return {"password_rows": len(rows), **summary}

    for i, row in enumerate(rows):
        uid = row["user_id"]
        if i:
            time.sleep(args.pause)
        outcome = retire_stored_password(uid)
        summary[outcome] += 1
        print(f"  {uid}: {outcome}")
        if outcome == "rejected" and args.drop_rejected:
            # Conditional on still holding a password: never a row re-saved since.
            table("gradescope_credentials").delete(
                {"user_id": f"eq.{uid}", "auth_mode": "eq.password"},
            )
            summary["dropped"] += 1

    print("\napplied: " + ", ".join(f"{v} {k.replace('_', ' ')}" for k, v in summary.items()))
    left = len(_password_rows())
    print(f"{left} row(s) still hold a password.")
    return {"password_rows": left, **summary}


if __name__ == "__main__":
    main()

"""
Move unapproved accounts onto the waitlist, once.

Unapproved Google sign-ins used to create a `users` row that sat in Admin →
Users as "pending". They no longer do: the waitlist (Admin → Allowlist) holds
everyone waiting for approval, and Admin → Users lists only people with access.
This script brings the rows created before that change into line:

  every unapproved, non-deleted account  -> its email is put on the waitlist
                                            (unapproved), unless already there
  ...that never got in (onboarding not   -> the account is deleted, with the
     completed)                             profile and OAuth tokens it holds
  ...that did get in (onboarded, so its  -> kept, unapproved: its access was
     access was later removed)              removed and its data is real

Approving the email on the Allowlist lets the person in at their next sign-in
either way (a kept account is promoted; a deleted one is recreated).

Dry-run by default. Run from backend/:
    python scripts/move_unapproved_users_to_waitlist.py            # preview
    python scripts/move_unapproved_users_to_waitlist.py --apply

Reads .env; for staging/prod run under `dotenv -f .env.<env> run -- ...` and
check the project it prints first. Needs that environment's ENCRYPTION_KEY to
read the emails. A second run is a no-op.
"""
import argparse
import sys
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv

BASE = Path(__file__).parent.parent
load_dotenv(BASE / ".env")
sys.path.insert(0, str(BASE))

from db.connection import REST_URL, table  # noqa: E402
from routes.auth import _waitlist_entry  # noqa: E402
from services.encryption import decrypt_if_present  # noqa: E402

#: Rows a never-approved account can hold. Deleted before the account itself;
#: anything else referencing it makes the delete fail, and the account is kept.
_OWNED = ("oauth_tokens", "user_profiles", "user_settings", "user_roles")


def _unapproved() -> list[dict]:
    return table("users").select(
        "id,email,onboarding_completed",
        filters={"is_approved": "eq.false", "deleted_at": "is.null"},
    ) or []


def main(argv: list[str] | None = None) -> dict:
    parser = argparse.ArgumentParser(description="Move unapproved accounts onto the waitlist.")
    parser.add_argument("--dry-run", action="store_true", default=True)
    parser.add_argument("--apply", dest="dry_run", action="store_false")
    args = parser.parse_args(argv)

    print(f"Project: {urlparse(REST_URL).hostname}")
    summary = {"listed": 0, "already_listed": 0, "deleted": 0, "kept": 0, "no_email": 0, "failed": 0}
    for row in _unapproved():
        uid = row["id"]
        email = (decrypt_if_present(row.get("email")) or "").strip()
        if "@" not in email:
            summary["no_email"] += 1
            print(f"  {uid}: no readable email, left alone")
            continue
        listed = _waitlist_entry(email) is not None
        drop = not row.get("onboarding_completed")
        summary["already_listed" if listed else "listed"] += 1
        print(f"  {uid}: {'already on' if listed else 'add to'} waitlist, "
              f"{'delete account' if drop else 'keep account (it had access)'}")
        if args.dry_run:
            summary["deleted" if drop else "kept"] += 1
            continue
        try:
            if not listed:
                table("newsletter_emails").upsert({"email": email}, on_conflict="email")
            if drop:
                for name in _OWNED:
                    table(name).delete({"user_id": f"eq.{uid}"})
                # Conditional, so an account approved since the read is never touched.
                table("users").delete({"id": f"eq.{uid}", "is_approved": "eq.false"})
                summary["deleted"] += 1
            else:
                summary["kept"] += 1
        except Exception as exc:  # noqa: BLE001 — report and carry on
            summary["failed"] += 1
            print(f"    failed: {type(exc).__name__}: {str(exc)[:200]}")

    mode = "DRY RUN — nothing written" if args.dry_run else "applied"
    print(f"\n{mode}: " + ", ".join(f"{v} {k.replace('_', ' ')}" for k, v in summary.items()))
    return summary


if __name__ == "__main__":
    main()

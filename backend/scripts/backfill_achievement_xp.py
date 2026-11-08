"""
Repay achievement XP that the global xp_events key silently denied.

Until 20261108063442_xp_events_per_user_idempotency, `xp_events.idempotency_key`
was UNIQUE across every student, and an achievement's key
(`achievement_unlocked:achievement:<achievement_id>`) does not contain the user.
So only the first student to earn a badge was paid; every later earner's award
hit the conflict and was recorded as "already paid". Their user_achievements
row exists; their xp_events row does not.

The grant path's self-heal (achievement_service._heal_grants) does not reach
them: it re-pays only badges earned in the last HEAL_WINDOW, and only when that
badge's trigger type fires again.

Who is owed
-----------
A holder is owed a badge's CURRENT xp_reward (what the heal path pays too: the
grant-time reward is not recorded) when all of these hold:

  * their account is not soft-deleted (`users.deleted_at` is null);
  * the badge is live and pays more than 0 now;
  * they have no achievement_unlocked ledger row of their own for it;
  * the badge was PAYING when they earned it. A holder who earned it while it
    paid nothing was legitimately unpaid, and paying them now would be a
    retroactive payout of a later reward change, which the heal path refuses.

The last point is the evidence question, and it must not depend on the
original payee's ledger row surviving (xp_events cascades on user delete).
It is satisfied by EITHER of:

  1. Unchanged since: XP existed when they earned it (earned_at is at or after
     the earliest xp_events row in this environment) AND no admin
     `achievement.update` in admin_audit_log changed the badge's xp_reward
     after earned_at. Then its reward at earned_at was the current, positive
     one: they should have been paid and were not. Rewards change only
     through that logged admin PATCH (plus the one-time catalog seed, which
     predates the first XP row). A reward change that predates the audit log,
     or a hand edit in the dashboard, is invisible here.
  2. Paid nearby: some OTHER student's payout of the badge is dated no later
     than earned_at + HEAL_WINDOW, so the badge was paying then. This covers
     badges whose reward has since changed. It only adds holders; losing that
     row to an account deletion never removes a holder evidence 1 covers.

Holders of a DRAFT badge are not paid (an unpublished badge pays nothing,
the same contract the grant and heal paths keep). They are listed per badge
in the output instead: re-run this script after republishing the badge.

How they are paid
-----------------
Each repayment is written to the ledger dated at the holder's earned_at,
which is when award_xp would have written it, not today. A student owed
several badges therefore does not get all that XP "today". Today's xp_in_day
(golden-hour), daily goal, goal streak and activity feed are unaffected, and
each past day's total becomes what it would have been without the bug. Then
each student's users.total_xp / level cache is refreshed ONCE from the ledger,
and the XP-driven achievement checks (level, xp_in_day) run once. Those checks
only see each past day as it should have been, so a golden-hour they grant is
one the student had in fact earned on that day, not a sum of today's
repayments.

Safe to re-run: a repaid holder has their own ledger row afterwards. A
conflict (409) on a write means that student's row already exists (a
concurrent run or a heal won the race): it counts as already paid. If the
conflict came from ANOTHER student's row, the migration has not been applied
and the run stops. Any other failure is recorded per student and the run goes
on. The summary always prints, and the exit status is non-zero if anything
failed or the run stopped.

Run it AFTER the migration. Dry-run unless --apply. Run from backend/:
    python scripts/backfill_achievement_xp.py            # preview
    python scripts/backfill_achievement_xp.py --apply

Reads .env; for staging/prod run under `dotenv -f .env.<env> run -- ...` and
check the project it prints first.
"""
import argparse
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv

BASE = Path(__file__).parent.parent
load_dotenv(BASE / ".env")
sys.path.insert(0, str(BASE))

from db.connection import REST_URL, page_all, table  # noqa: E402
from services.achievement_service import HEAL_WINDOW, parse_utc  # noqa: E402
from services.xp_service import record_ledger_row, settle_ledger_writes  # noqa: E402

RULE_KEY = "achievement_unlocked"
SOURCE_TYPE = "achievement"


def reward_changes(audit_rows) -> dict[str, list[datetime]]:
    """badge id → the times an admin changed its xp_reward."""
    out: dict[str, list[datetime]] = defaultdict(list)
    for r in audit_rows:
        at = parse_utc(r.get("created_at"))
        if at is not None and "xp_reward" in (r.get("payload") or {}):
            out[r.get("target_id")].append(at)
    return out


def plan(holdings, payouts, badges, *, audit_rows=(), xp_live_since=None,
         deleted_users=frozenset()):
    """Decide who is owed what.

    holdings:      user_achievements rows (user_id, achievement_id, earned_at).
    payouts:       achievement_unlocked xp_events rows (user_id, source_id, created_at).
    badges:        achievements rows (id, xp_reward, status).
    audit_rows:    admin_audit_log achievement.update rows (target_id, payload, created_at).
    xp_live_since: the earliest xp_events row in the environment (None: no XP yet).
    deleted_users: ids of soft-deleted accounts.

    Returns (owed, skipped, draft_held):
      owed       [(user_id, achievement_id, amount, earned_at iso)]
      skipped    Counter of reasons a holder is not owed
      draft_held Counter: draft badge id → unpaid holders waiting on republish
    """
    paid = {(p["user_id"], p["source_id"]) for p in payouts}
    paid_at: dict[str, list[tuple[datetime, str]]] = defaultdict(list)
    for p in payouts:
        at = parse_utc(p.get("created_at"))
        if at is not None:
            paid_at[p["source_id"]].append((at, p["user_id"]))
    changes = reward_changes(audit_rows)
    status = {b["id"]: b.get("status") for b in badges}
    reward = {b["id"]: int(b.get("xp_reward") or 0) for b in badges}

    owed = []
    skipped: Counter = Counter()
    draft_held: Counter = Counter()
    for h in holdings:
        user_id, achievement_id = h["user_id"], h["achievement_id"]
        if user_id in deleted_users:
            skipped["account_deleted"] += 1
            continue
        if (user_id, achievement_id) in paid:
            skipped["already_paid"] += 1
            continue
        if achievement_id not in status:
            skipped["badge_missing"] += 1
            continue
        if not reward[achievement_id]:
            skipped["badge_pays_nothing"] += 1
            continue
        if status[achievement_id] != "live":
            skipped["badge_not_live"] += 1
            draft_held[achievement_id] += 1
            continue
        earned_at = parse_utc(h.get("earned_at"))
        if earned_at is None:
            skipped["unknown_earned_at"] += 1
            continue
        unchanged_since = (
            xp_live_since is not None and earned_at >= xp_live_since
            and not any(at > earned_at for at in changes.get(achievement_id, ()))
        )
        paid_nearby = any(
            other != user_id and at <= earned_at + HEAL_WINDOW
            for at, other in paid_at.get(achievement_id, ())
        )
        if not (unchanged_since or paid_nearby):
            skipped["not_paying_when_earned"] += 1
            continue
        owed.append((user_id, achievement_id, reward[achievement_id], earned_at.isoformat()))
    return owed, skipped, draft_held


def _own_row_exists(user_id: str, achievement_id: str) -> bool:
    return bool(table("xp_events").select(
        "id",
        filters={
            "user_id": f"eq.{user_id}",
            "rule_key": f"eq.{RULE_KEY}",
            "source_type": f"eq.{SOURCE_TYPE}",
            "source_id": f"eq.{achievement_id}",
        },
        limit=1,
    ))


class MigrationMissing(Exception):
    """A repayment conflicted with ANOTHER student's row: the key is still
    unique across students in this environment."""


def repay_user(user_id: str, items, summary: Counter) -> None:
    """Write one student's repayments back-dated, then settle the cache once."""
    written = 0
    try:
        for _uid, achievement_id, amount, earned_at in items:
            if record_ledger_row(
                user_id, RULE_KEY, source_type=SOURCE_TYPE, source_id=achievement_id,
                amount=amount, created_at=earned_at,
            ):
                written += 1
                summary["repaid"] += 1
                summary["repaid_xp"] += amount
            elif _own_row_exists(user_id, achievement_id):
                summary["already_paid_concurrently"] += 1
            else:
                raise MigrationMissing(achievement_id)
    finally:
        if written:
            settle_ledger_writes(user_id)


def main(argv: list[str] | None = None) -> Counter:
    parser = argparse.ArgumentParser(
        description="Repay achievement XP denied by the global xp_events key."
    )
    parser.add_argument("--apply", action="store_true",
                        help="write the repayments (default: dry run)")
    args = parser.parse_args(argv)

    print(f"Project: {urlparse(REST_URL).hostname}")
    holdings = list(page_all(
        table("user_achievements"), "user_id,achievement_id,earned_at",
        order="user_id.asc,achievement_id.asc",
    ))
    payouts = list(page_all(
        table("xp_events"), "user_id,source_id,created_at",
        filters={"rule_key": f"eq.{RULE_KEY}", "source_type": f"eq.{SOURCE_TYPE}"},
        order="created_at.asc,id.asc",
    ))
    badges = table("achievements").select("id,xp_reward,status") or []
    audit_rows = list(page_all(
        table("admin_audit_log"), "target_id,payload,created_at",
        filters={"action": "eq.achievement.update"},
        order="created_at.asc,id.asc",
    ))
    first = table("xp_events").select("created_at", order="created_at.asc", limit=1)
    xp_live_since = parse_utc(first[0].get("created_at")) if first else None
    deleted_users = {
        r["id"] for r in page_all(
            table("users"), "id", filters={"deleted_at": "not.is.null"}, order="id.asc",
        )
    }

    owed, summary, draft_held = plan(
        holdings, payouts, badges, audit_rows=audit_rows,
        xp_live_since=xp_live_since, deleted_users=deleted_users,
    )
    summary["owed"] = len(owed)
    summary["owed_xp"] = sum(item[2] for item in owed)
    summary["owed_students"] = len({item[0] for item in owed})

    failures: list[str] = []
    if args.apply:
        by_user: dict[str, list] = defaultdict(list)
        for item in owed:
            by_user[item[0]].append(item)
        for user_id, items in by_user.items():
            try:
                repay_user(user_id, items, summary)
            except MigrationMissing:
                summary["stopped"] += 1
                print(
                    "\nSTOPPED: a repayment conflicted with another student's "
                    "payout, so xp_events.idempotency_key is still unique across "
                    "students here. Apply 20261108063442_xp_events_per_user_"
                    "idempotency first, then re-run.",
                    file=sys.stderr,
                )
                break
            except Exception as exc:  # noqa: BLE001 — one student must not end the run
                summary["failed_students"] += 1
                failures.append(f"{user_id}: {type(exc).__name__}: {exc}")

    mode = "applied" if args.apply else "DRY RUN — nothing written (--apply to write)"
    print(f"\n{mode}")
    for key, n in sorted(summary.items()):
        print(f"  {key}: {n}")
    if draft_held:
        print("\nUnpaid holders of DRAFT badges (re-run after republishing):")
        for achievement_id, n in sorted(draft_held.items()):
            print(f"  {achievement_id}: {n}")
    if failures:
        print("\nFailed (re-run to retry; repaid rows are skipped):", file=sys.stderr)
        for line in failures:
            print(f"  {line}", file=sys.stderr)
    return summary


def exit_code(summary: Counter) -> int:
    return 1 if summary["stopped"] or summary["failed_students"] else 0


if __name__ == "__main__":
    sys.exit(exit_code(main()))

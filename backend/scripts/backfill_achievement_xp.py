"""
Repay achievement XP that the global xp_events key silently denied.

Until 20261108063442_xp_events_per_user_idempotency, `xp_events.idempotency_key`
was UNIQUE across every student, and an achievement's key
(`achievement_unlocked:achievement:<achievement_id>`) does not contain the user.
So only the first student to earn a badge was paid; every later earner's award
hit the conflict and was recorded as "already paid". Their user_achievements
row exists; their xp_events row does not.

The grant path's own self-heal (achievement_service._heal_grants) does not
reach them: it re-pays only badges earned in the last HEAL_WINDOW, and only
when that badge's trigger type fires again. So this script finds the holders
the bug denied and pays them through award_xp (which also refreshes the
users.total_xp / level cache).

"Denied by the bug" is decided from the ledger, not assumed: a holder with no
payout is repaid only when ANOTHER student already held that badge's key by
the time this holder's award (or a heal of it) was attempted — the earliest
other payout is no later than earned_at + HEAL_WINDOW. A holder with no payout
and no such earlier payee was not blocked by the key (most likely the badge
paid nothing when they earned it), and is left alone: paying them would be a
retroactive payout of a later xp_reward change, which the heal path refuses to
do too. As the heal path does, only LIVE badges are paid, at their CURRENT
xp_reward (the grant-time reward is not recorded anywhere).

Idempotent: a repaid holder has an xp_events row afterwards, so a re-run skips
them; award_xp's per-student key makes even a concurrent double run pay once.

Run it AFTER the migration. Before it, every repayment hits the same global
key; the script detects that on the first one and stops.

Dry-run by default. Run from backend/:
    python scripts/backfill_achievement_xp.py            # preview
    python scripts/backfill_achievement_xp.py --apply

Reads .env; for staging/prod run under `dotenv -f .env.<env> run -- ...` and
check the project it prints first.
"""
import argparse
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv

BASE = Path(__file__).parent.parent
load_dotenv(BASE / ".env")
sys.path.insert(0, str(BASE))

from db.connection import REST_URL, page_all, table  # noqa: E402
from services.achievement_service import HEAL_WINDOW  # noqa: E402
from services.xp_service import award_xp  # noqa: E402

RULE_KEY = "achievement_unlocked"
SOURCE_TYPE = "achievement"


def _ts(raw) -> datetime | None:
    if not raw:
        return None
    try:
        ts = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return None
    return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)


def plan(holdings, payouts, badges) -> tuple[list[tuple[str, str, int]], Counter]:
    """Decide who is owed what.

    holdings: user_achievements rows (user_id, achievement_id, earned_at).
    payouts:  achievement_unlocked xp_events rows (user_id, source_id, created_at).
    badges:   achievements rows (id, xp_reward, status).

    Returns ([(user_id, achievement_id, amount)], reasons-skipped Counter).
    """
    paid = {(p["user_id"], p["source_id"]) for p in payouts}
    # Each badge's payouts as (paid_at, user_id): who held its key, and since when.
    by_badge: dict[str, list[tuple[datetime, str]]] = {}
    for p in payouts:
        at = _ts(p.get("created_at"))
        if at is not None:
            by_badge.setdefault(p["source_id"], []).append((at, p["user_id"]))
    reward = {b["id"]: int(b.get("xp_reward") or 0)
              for b in badges if b.get("status") == "live"}

    owed: list[tuple[str, str, int]] = []
    skipped: Counter = Counter()
    for h in holdings:
        user_id, achievement_id = h["user_id"], h["achievement_id"]
        if (user_id, achievement_id) in paid:
            skipped["already_paid"] += 1
            continue
        if achievement_id not in reward:
            skipped["badge_not_live"] += 1
            continue
        if not reward[achievement_id]:
            skipped["badge_pays_nothing"] += 1
            continue
        earned_at = _ts(h.get("earned_at"))
        if earned_at is None:
            skipped["unknown_earned_at"] += 1
            continue
        blocked = any(
            other != user_id and at <= earned_at + HEAL_WINDOW
            for at, other in by_badge.get(achievement_id, ())
        )
        if not blocked:
            skipped["not_blocked_by_key"] += 1
            continue
        owed.append((user_id, achievement_id, reward[achievement_id]))
    return owed, skipped


def main(argv: list[str] | None = None) -> Counter:
    parser = argparse.ArgumentParser(
        description="Repay achievement XP denied by the global xp_events key."
    )
    parser.add_argument("--dry-run", action="store_true", default=True)
    parser.add_argument("--apply", dest="dry_run", action="store_false")
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

    owed, summary = plan(holdings, payouts, badges)
    summary["owed"] = len(owed)
    summary["owed_xp"] = sum(amount for _, _, amount in owed)

    if not args.dry_run:
        for user_id, achievement_id, amount in owed:
            result = award_xp(
                user_id, RULE_KEY,
                source_type=SOURCE_TYPE, source_id=achievement_id, amount=amount,
            )
            if result.duplicate:
                # The only way a holder with no payout of their own conflicts:
                # the key is still unique across students.
                summary["blocked"] += 1
                print(
                    "\nSTOPPED: the repayment conflicted with another student's "
                    "payout, so xp_events.idempotency_key is still globally "
                    "unique here. Apply 20261108063442_xp_events_per_user_"
                    "idempotency first, then re-run.",
                    file=sys.stderr,
                )
                break
            summary["repaid"] += 1
            summary["repaid_xp"] += result.awarded

    mode = "DRY RUN — nothing written" if args.dry_run else "applied"
    print(f"\n{mode}")
    for key, n in sorted(summary.items()):
        print(f"  {key}: {n}")
    return summary


if __name__ == "__main__":
    sys.exit(1 if main()["blocked"] else 0)

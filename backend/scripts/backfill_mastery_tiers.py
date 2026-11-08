"""
Recompute every stale graph_nodes.mastery_tier from its mastery_score (#766).

The tier is stored next to the score, so a change to the thresholds in
config.py (MASTERY_*_MIN) — or any writer that ever stored a tier the current
rule would not produce, including a 'subject_root' reset to 'unexplored' by
migration 20261106055333_state_machines_audit — leaves rows whose tier disagrees with their score.
The atomic `apply_mastery_delta` function heals a node on its next write; this
heals the rest, using `config.get_mastery_tier` so the thresholds keep their
one home.

Each write is conditional on the score it was computed from, so a mastery
update landing between this read and this write is never clobbered (that
write recomputed the tier itself).

Dry-run by default. Run from backend/:
    python scripts/backfill_mastery_tiers.py            # preview
    python scripts/backfill_mastery_tiers.py --apply

Reads .env; for staging/prod run under `dotenv -f .env.<env> run -- ...` and
check the project it prints first. Run it AFTER the migration, and again after
any threshold change.
"""
import argparse
import sys
from collections import Counter
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv

BASE = Path(__file__).parent.parent
load_dotenv(BASE / ".env")
sys.path.insert(0, str(BASE))

from config import get_mastery_tier  # noqa: E402
from db.connection import REST_URL, page_all, table  # noqa: E402


def stale_rows(rows) -> list[tuple[dict, str]]:
    """(row, the tier it should have) for every row whose stored tier is wrong."""
    out = []
    for r in rows:
        want = get_mastery_tier(float(r.get("mastery_score") or 0.0))
        if r.get("mastery_tier") != want:
            out.append((r, want))
    return out


def main(argv: list[str] | None = None) -> Counter:
    parser = argparse.ArgumentParser(
        description="Recompute graph_nodes.mastery_tier from mastery_score."
    )
    parser.add_argument("--dry-run", action="store_true", default=True)
    parser.add_argument("--apply", dest="dry_run", action="store_false")
    args = parser.parse_args(argv)

    print(f"Project: {urlparse(REST_URL).hostname}")
    rows = page_all(
        table("graph_nodes"), "id,mastery_score,mastery_tier", order="id",
    )
    summary: Counter = Counter()
    for row, want in stale_rows(rows):
        summary[f"{row.get('mastery_tier')}->{want}"] += 1
        if not args.dry_run:
            table("graph_nodes").update(
                {"mastery_tier": want},
                filters={
                    "id": f"eq.{row['id']}",
                    "mastery_score": f"eq.{row.get('mastery_score')}",
                },
                prefer_return_minimal=True,
            )

    mode = "DRY RUN — nothing written" if args.dry_run else "applied"
    total = sum(summary.values())
    print(f"\n{mode}: {total} stale tier(s)")
    for transition, n in sorted(summary.items()):
        print(f"  {transition}: {n}")
    return summary


if __name__ == "__main__":
    main()

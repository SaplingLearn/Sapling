"""
Delete note_concepts rows that link a note to ANOTHER student's graph node (#115).

Before #115, `notes_service.link_concept` checked only the note's owner, so
POST /api/notes/{id}/concepts could attach any graph node id to the caller's
own note. The service now refuses that, but rows written before the fix stay.
They are invisible to their note's owner (`list_linked_concepts` joins
graph_nodes filtered by the reader's user_id) and they are not the node
owner's either: a stray cross-user link the account wipe/copy tools and any
future reader would otherwise have to reason about. This removes them.

A row is cross-user when the owner of its note (notes.user_id) differs from
the owner of its node (graph_nodes.user_id). Rows whose note or node owner
cannot be read are left alone and counted (the FKs cascade, so there should
be none). Soft-deleted notes are still compared: their rows are just as
cross-user.

Idempotent: a second run finds nothing left. Each delete names its exact
(note_id, concept_node_id) pair, so a link re-created legitimately between
this read and the write cannot be swept up by a broader filter.

Dry-run by default. Run from backend/:
    python scripts/cleanup_cross_user_note_concepts.py            # preview counts
    python scripts/cleanup_cross_user_note_concepts.py --apply    # delete them

Reads .env; for staging/prod run under `dotenv -f .env.<env> run -- ...` and
check the project it prints first.
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

from db.connection import REST_URL, page_all, pg_quote_value, table  # noqa: E402

#: ids per `id=in.(...)` owner lookup; keeps each URL well under proxy limits.
LOOKUP_BATCH = 100


def _owners(table_name: str, ids: set[str]) -> dict[str, str]:
    """{id: user_id} for every id in `ids` that exists in `table_name`."""
    out: dict[str, str] = {}
    ordered = sorted(ids)
    for i in range(0, len(ordered), LOOKUP_BATCH):
        batch = ordered[i : i + LOOKUP_BATCH]
        in_clause = "in.(" + ",".join(pg_quote_value(x) for x in batch) + ")"
        rows = table(table_name).select("id,user_id", filters={"id": in_clause}) or []
        for r in rows:
            out[r["id"]] = r.get("user_id")
    return out


def plan(
    links: list[dict], note_owner: dict[str, str], node_owner: dict[str, str]
) -> tuple[list[dict], Counter]:
    """(cross-user rows to delete, counts by outcome) — pure, for tests."""
    stale: list[dict] = []
    counts: Counter = Counter()
    for link in links:
        n_owner = note_owner.get(link.get("note_id"))
        g_owner = node_owner.get(link.get("concept_node_id"))
        if n_owner is None or g_owner is None:
            counts["unreadable_owner"] += 1
        elif n_owner != g_owner:
            counts["cross_user"] += 1
            stale.append(link)
        else:
            counts["same_owner"] += 1
    return stale, counts


def main(argv: list[str] | None = None) -> Counter:
    parser = argparse.ArgumentParser(
        description="Delete note_concepts rows whose node owner is not the note owner."
    )
    parser.add_argument("--dry-run", action="store_true", default=True)
    parser.add_argument("--apply", dest="dry_run", action="store_false")
    args = parser.parse_args(argv)

    print(f"Project: {urlparse(REST_URL).hostname}")
    links = list(page_all(
        table("note_concepts"), "note_id,concept_node_id",
        order="note_id,concept_node_id",
    ))
    note_owner = _owners("notes", {link["note_id"] for link in links})
    node_owner = _owners("graph_nodes", {link["concept_node_id"] for link in links})
    stale, counts = plan(links, note_owner, node_owner)

    deleted = 0
    if not args.dry_run:
        for link in stale:
            removed = table("note_concepts").delete(filters={
                "note_id": f"eq.{link['note_id']}",
                "concept_node_id": f"eq.{link['concept_node_id']}",
            }) or []
            deleted += len(removed)
    counts["deleted"] = deleted

    mode = "DRY RUN — nothing written" if args.dry_run else "applied"
    print(f"\n{mode}: {len(links)} note_concepts row(s) scanned")
    print(f"  same owner (kept):           {counts['same_owner']}")
    print(f"  cross-user (to delete):      {counts['cross_user']}")
    print(f"  owner unreadable (skipped):  {counts['unreadable_owner']}")
    if not args.dry_run:
        print(f"  deleted:                     {deleted}")
    else:
        print("Re-run with --apply to delete the cross-user rows.")
    return counts


if __name__ == "__main__":
    main()

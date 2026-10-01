"""Draft check items for existing course concepts (learning loop PKG-04; spec §13 A23).

Uploads draft items at ingest (routes/documents.py); this covers concepts that
predate the package, and it is the launch runbook's staging and production step (spec
§11.1 item 3; §11.7 steps 3, 7, 9, and the nightly job of step 11). Items are course assets keyed on (course_id,
concept_key). Per course: the concept keys are the normalized concept names of
every student's graph_nodes, the sources are the course's shared
course_material documents, and a key that already has
CHECK_ITEM_INITIAL_PER_CONCEPT items is skipped before any agent call — each
concept is drafted once however many students share it. Idempotent: concepts
already covered per `(course_id, concept_key)` are skipped (A2/A23). A re-run
costs nothing.

Run from backend/:
    env LEARNING_LOOP_ENABLED=true python scripts/backfill_check_items.py (--course <id> | --all-courses) --project <ref> [--dry-run] [--function-mode] [--regenerate-missing-final-answer]

--regenerate-missing-final-answer (spec §13 A34, explicit): items drafted
before check_items.final_answer existed have none, so selection never serves
them. This mode retires them by id, per course, before the normal drafting
pass, which then redrafts their concepts as under-covered. A final answer is
never derived from reference text. With --dry-run it only reports.

Prints `Project: <ref>` first and `coverage <course_id> <with_items>/<concepts>`
per course. Exit 2 when --project is not the project SUPABASE_URL points at
(a variable missing from the production env file silently falls back to
.env.staging / backend/.env — this stops the run before any write), when
LEARNING_LOOP_ENABLED is not true, or when the model mode is not 'real'
without --function-mode; exit 1 only when concepts needed items and zero
landed (a fully covered re-run exits 0). A concept that no shared
course-material passage mentions (CHECK_ITEM_BACKFILL_MIN_CHUNK_SCORE) is
never drafted; it stays uncovered.

Loads .env.staging without overriding what is already set, like
scripts/backfill_document_chunks.py, so run it under
`dotenv -f .env.<env> run -- ...` for any other environment and check the
`Project:` line it prints first. Usage is recorded against the system actor
(NULL user_id), so it never counts toward a student's budget.
"""

import argparse
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv

BASE = Path(__file__).parent.parent
load_dotenv(BASE / ".env.staging")

sys.path.insert(0, str(BASE))

import config  # noqa: E402
from agents._providers import model_mode  # noqa: E402
from db.connection import SUPABASE_URL, page_all, pg_quote_value, table  # noqa: E402
from learning.checks import rank_chunks_for_concept  # noqa: E402
from learning.params import (  # noqa: E402
    CHECK_ITEM_BACKFILL_MIN_CHUNK_SCORE,
    CHECK_ITEM_INITIAL_PER_CONCEPT,
    CHECK_ITEM_MAX_CHUNKS,
)
from services.academics import course_offering_ids  # noqa: E402
from services.chunk_visibility import COURSE_MATERIAL  # noqa: E402
from services.check_item_service import (  # noqa: E402
    concept_key,
    count_items,
    coverage,
    generate_for_concepts,
    items_missing_final_answer,
    retire_items_by_id,
    source_chunks,
)

_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", "0.0.0.0", "host.docker.internal"}
_SUPABASE_SUFFIX = ".supabase.co"


def _project_ref() -> str:
    """The project SUPABASE_URL points at: `<ref>` of `<ref>.supabase.co`,
    `local` for a loopback URL, else the bare host."""
    host = (urlparse(SUPABASE_URL).hostname or "").lower()
    if not host or host in _LOCAL_HOSTS:
        return "local"
    if host.endswith(_SUPABASE_SUFFIX):
        return host[: -len(_SUPABASE_SUFFIX)].split(".")[0]
    return host


class _GraphNodesRead:
    """A read-only `page_all` handle over graph_nodes: invariant 1 allows
    `table("graph_nodes")` only as a direct read, never a handle passed on."""

    def select_with_count(self, *args, **kwargs):
        return table("graph_nodes").select_with_count(*args, **kwargs)


def _courses(args) -> list[str]:
    if args.course:
        return [args.course]
    ids = {r.get("course_id") for r in page_all(_GraphNodesRead(), "course_id", order="id")}
    ids.discard(None)
    return sorted(ids)


def _concept_names(course: str) -> list[str]:
    """First name per concept_key over every student's nodes in the course."""
    names: dict[str, str] = {}
    for row in page_all(
        _GraphNodesRead(), "concept_name", filters={"course_id": f"eq.{course}"}, order="id"
    ):
        name = row.get("concept_name") or ""
        key = concept_key(name)
        if key and key not in names:
            names[key] = name
    return list(names.values())


def _source_documents(offerings: list[str]) -> list[dict]:
    if not offerings:
        return []
    return list(
        page_all(
            table("documents"),
            "id,user_id,shareability,shareability_confidence,extracted_text",
            filters={
                "offering_id": f"in.({','.join(pg_quote_value(o) for o in offerings)})",
                "shareability": f"eq.{COURSE_MATERIAL}",
                "deleted_at": "is.null",
            },
            order="id",
        )
    )


def _would_draft(
    course: str, names: list[str], chunks: list[dict], retiring: dict[str, list[str]]
) -> list[str]:
    """Dry run: the keys a real run would send to the agent (reads only).
    `retiring` = the rows the A34 mode would retire first (not counted)."""
    keys = []
    for name in names:
        key = concept_key(name)
        kept = count_items(course, key) - len(retiring.get(key, ()))
        if kept >= CHECK_ITEM_INITIAL_PER_CONCEPT:
            continue
        if rank_chunks_for_concept(
            name, chunks, limit=CHECK_ITEM_MAX_CHUNKS, min_score=CHECK_ITEM_BACKFILL_MIN_CHUNK_SCORE
        ):
            keys.append(key)
    return keys


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Draft check items for existing course concepts (PKG-04, A23).",
    )
    which = parser.add_mutually_exclusive_group(required=True)
    which.add_argument("--course", help="Backfill this one (abstract) course id.")
    which.add_argument(
        "--all-courses", action="store_true", help="Backfill every course with graph_nodes."
    )
    parser.add_argument(
        "--project", required=True, help="The Supabase project ref this run must write to."
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Plan and coverage only; no agent call, no write."
    )
    parser.add_argument(
        "--function-mode",
        action="store_true",
        help="Allow SAPLING_MODEL_MODE other than 'real' (deterministic local runs).",
    )
    parser.add_argument(
        "--regenerate-missing-final-answer",
        action="store_true",
        help="Retire items with no final_answer (A34), then redraft their concepts.",
    )
    args = parser.parse_args(argv)

    connected = _project_ref()
    print(f"Project: {connected}")
    if args.project != connected:
        print(
            f"Refusing: --project {args.project} is not the connected project {connected}. "
            "Check the env file this run loaded (a missing variable falls back to "
            ".env.staging / backend/.env)."
        )
        sys.exit(2)
    if not config.LEARNING_LOOP_ENABLED:
        print(
            "Refusing: LEARNING_LOOP_ENABLED is not true. Run it the runbook way: "
            "env LEARNING_LOOP_ENABLED=true python scripts/backfill_check_items.py ..."
        )
        sys.exit(2)
    mode = model_mode()
    if mode != "real" and not args.function_mode:
        print(
            f"Refusing: SAPLING_MODEL_MODE is {mode!r}, not 'real'. Unset it (is it "
            "still exported from an E2E cycle?) or pass --function-mode deliberately."
        )
        sys.exit(2)

    items = attempted = skipped = unmatched = unavailable = 0
    for n, course in enumerate(_courses(args)):
        if n and not args.dry_run:
            time.sleep(1.0)  # stay under the generation quota between courses
        names = _concept_names(course)
        offerings = course_offering_ids(course)
        if offerings is None:
            print(f"  {course}: offerings unknown — skipped")
            continue
        docs = _source_documents(offerings)
        chunks = [c for d in docs for c in source_chunks(d)]
        print(
            f"  {course} — {len(names)} concept(s), {len(docs)} course_material "
            f"document(s), {len(chunks)} source chunk(s)"
        )
        retiring: dict[str, list[str]] = {}
        if args.regenerate_missing_final_answer:
            retiring = items_missing_final_answer(course)
            stale = [i for ids in retiring.values() for i in ids]
            print(
                f"    {len(stale)} item(s) in {len(retiring)} concept(s) lack a final_answer (A34)"
            )
            if stale and args.dry_run:
                print(f"    would retire {len(stale)} item(s)")
            elif stale:
                print(f"    retired {retire_items_by_id(stale)} item(s) without a final_answer")
        if not chunks:
            print("    no shared course_material — no items (A23)")
        elif args.dry_run:
            keys = _would_draft(course, names, chunks, retiring)
            print(f"    would draft {len(keys)} concept(s): {', '.join(keys) or '-'}")
        else:
            out = generate_for_concepts(
                user_id=None,
                course_id=course,
                concept_names=names,
                chunks=chunks,
                flex=True,
                min_chunk_score=CHECK_ITEM_BACKFILL_MIN_CHUNK_SCORE,
            )
            print(
                f"    items {out.items_created} attempted {out.concepts_attempted} "
                f"skipped {out.concepts_skipped} unmatched {out.concepts_unmatched} "
                f"unavailable {out.unavailable}"
            )
            items += out.items_created
            attempted += out.concepts_attempted
            skipped += out.concepts_skipped
            unmatched += out.concepts_unmatched
            unavailable += out.unavailable
        with_items, concepts = coverage(course)
        print(f"coverage {course} {with_items}/{concepts}")

    print(
        f"\nDone: {items} items, {attempted} concepts attempted, {skipped} already covered, "
        f"{unmatched} with no shared passage, {unavailable} unavailable"
        + (" (dry run)" if args.dry_run else "")
    )
    if not args.dry_run and attempted > 0 and items == 0:
        sys.exit(1)


if __name__ == "__main__":
    main()

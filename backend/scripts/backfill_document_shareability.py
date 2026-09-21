#!/usr/bin/env python3
"""
One-time backfill: fill `documents.shareability` for rows classified before #630,
and withdraw the chunks of anything that is not course material.

Shareability has no cheaper source than the classifier. `documents.category`
cannot substitute for it — a blank problem-set handout and the same student's
worked solutions are both `category='assignment'`, and the whole point of the
field is that those two must not share a corpus. So this re-runs the classifier
over `documents.extracted_text` through the sanctioned agent seam and stores the
answer, which makes every later re-index deterministic instead of needing
another model pass.

Documents with no `extracted_text` (it is persisted inside the indexer, not in
`_persist_document` — see #482) get `personal_notes`: nothing can be read, so
nothing can be judged shareable.

**Withdrawal is a DELETE, not a visibility flip, and that is the whole design.**
A flip looked sufficient and is not, for two reasons that both bite:

* `visibility='private'` on a SHARED-namespace id leaves the row reachable
  through `match_course_chunks`' contributor clause, so every former contributor
  keeps retrieving it — immediately, with no toggle involved.
* The #629 resync recomputes visibility purely from contributor consent; it
  knows nothing about shareability. The first time any contributor touches the
  Class Intel toggle it would compute "an opted-in contributor remains" and flip
  the row back to `shared`, re-publishing the student's answers permanently.

Deleting the row takes its `course_chunk_contributors` entries with it (ON DELETE
CASCADE), which is what makes the withdrawal stick. Re-indexing afterwards
re-creates the content under the PRIVATE id namespace, where it belongs and
where the resync cannot reach it. So:

    python scripts/backfill_document_shareability.py --apply    # this script
    python scripts/backfill_document_chunks.py --apply          # then re-index

Chunks are located by re-deriving their content-addressed ids from the
document's own text, NOT by `doc_id`. `doc_id` is last-writer-wins on a deduped
row, so a filter on it misses exactly the leaking case: student A's
`completed_work` created the row and student B's later upload overwrote
`doc_id`, leaving A's answers shared and invisible to a `doc_id` query.

A row that OTHER students also contributed is left alone and reported. The text
is their upload too, their classification stands, and deleting it would withdraw
material they legitimately shared.

Dry-run by default. Run from backend/:
    python scripts/backfill_document_shareability.py            # preview
    python scripts/backfill_document_shareability.py --apply

Reads .env; for staging/prod run under `dotenv -f .env.staging run -- ...`.
Needs a REAL GEMINI_API_KEY and SAPLING_MODEL_MODE unset/real — the classifier
is a live model call. Note that backend/.env.production's key is a placeholder.

Needs the #482 migration too: it stores `shareability_confidence` beside each
answer, the pair the live upload stores, so a later re-index reproduces the
decision instead of reading a missing confidence as private.
"""
import argparse
import sys
from pathlib import Path

from dotenv import load_dotenv

BASE = Path(__file__).parent.parent
load_dotenv(BASE / ".env")
sys.path.insert(0, str(BASE))

from agents import WORKER_LIMITS  # noqa: E402
from agents._run import run_agent_sync  # noqa: E402
from agents.classifier import classifier_agent  # noqa: E402
from agents.deps import SaplingDeps  # noqa: E402
from db.connection import page_all, pg_quote_value, table  # noqa: E402
from services.chunk_visibility import (  # noqa: E402
    COURSE_MATERIAL, PERSONAL_NOTES,
)
from services.chunker import chunk_document, chunk_prose  # noqa: E402
from services.encryption import decrypt_if_present  # noqa: E402
from services.rag_service import chunk_id  # noqa: E402

#: Enough text to judge. Below this the classifier invents a document (the same
#: reasoning as routes/documents.py::MIN_EXTRACTED_CHARS).
MIN_CHARS = 50

#: Ids per `in.(…)` filter — see chunk_visibility._ID_BATCH for the reasoning.
_ID_BATCH = 50


def _classify(text: str) -> tuple[str, float | None]:
    """The classifier's shareability, and the confidence it was judged at.

    The confidence is kept, not discarded (#482): decide_visibility reads a
    missing one as PRIVATE, so a row stored without it could never be re-shared
    by a re-index, however confidently it was judged course material.
    """
    deps = SaplingDeps(
        user_id="backfill", course_id=None, supabase=None, request_id="backfill",
    )
    result = run_agent_sync(
        classifier_agent.run(
            text[:20_000], deps=deps, usage_limits=WORKER_LIMITS,
        )
    )
    return result.output.shareability or PERSONAL_NOTES, result.output.confidence


def _decision(answer: str, confidence: float | None) -> dict:
    """The pair the live upload stores (#482), so a re-index reproduces it."""
    return {"shareability": answer, "shareability_confidence": confidence}


def _course_code(offering_id: str) -> str | None:
    """BU course code for a document's offering — the `course_chunks` partition."""
    if not offering_id:
        return None
    rows = table("course_offerings").select(
        "course_id", filters={"id": f"eq.{offering_id}"}, limit=1,
    )
    if not rows:
        return None
    rows = table("courses").select(
        "course_code", filters={"id": f"eq.{rows[0]['course_id']}"}, limit=1,
    )
    return (rows[0].get("course_code") or None) if rows else None


def _in_list(values: list[str]) -> str:
    return f"in.({','.join(pg_quote_value(v) for v in values)})"


def _sole_contributor_ids(ids: list[str], user_id: str) -> tuple[list[str], list[str]]:
    """Split `ids` into (this uploader's alone, also fed by someone else).

    Ids absent from the ledger count as sole: a row with no contributor entry
    predates #629's seeding or was never shared, and either way nobody else has
    claimed it.
    """
    others: set[str] = set()
    for i in range(0, len(ids), _ID_BATCH):
        batch = ids[i : i + _ID_BATCH]
        rows = table("course_chunk_contributors").select(
            "chunk_id,user_id", filters={"chunk_id": _in_list(batch)},
        )
        for row in rows or []:
            if row["user_id"] != user_id:
                others.add(row["chunk_id"])
    sole = [i for i in ids if i not in others]
    return sole, sorted(others)


def _existing(ids: list[str]) -> list[str]:
    found: list[str] = []
    for i in range(0, len(ids), _ID_BATCH):
        batch = ids[i : i + _ID_BATCH]
        rows = table("course_chunks").select("id", filters={"id": _in_list(batch)})
        found.extend(r["id"] for r in rows or [])
    return found


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Fill documents.shareability and withdraw the chunks of "
                    "anything that is not course material."
    )
    parser.add_argument("--dry-run", action="store_true", default=True)
    parser.add_argument("--apply", dest="dry_run", action="store_false")
    args = parser.parse_args()

    # PAGED. An unbounded read stops at PostgREST's max_rows and answers 206 —
    # a 2xx — so the script would report a clean summary having silently skipped
    # everything past the first page, and the operator would move on to the
    # re-index, which privatises every untouched document (`shareability=None`).
    docs = list(page_all(
        table("documents"),
        "id,file_name,user_id,offering_id,extracted_text,category,shareability",
        filters={"shareability": "is.null", "deleted_at": "is.null"},
        order="id",
    ))
    print(f"{len(docs)} document(s) with no stored shareability.")

    counts: dict[str, int] = {}
    deleted = shared_with_others = unlocated = 0
    for doc in docs:
        doc_id = doc["id"]
        user_id = doc.get("user_id") or ""
        text = decrypt_if_present(doc.get("extracted_text")) or ""
        if len(text.strip()) < MIN_CHARS:
            answer, confidence = PERSONAL_NOTES, None
            why = "no readable extracted_text"
        else:
            answer, confidence = _classify(text)
            why = "classified"
        counts[answer] = counts.get(answer, 0) + 1
        print(f"  {doc_id[:8]} {doc.get('file_name', '')!r:40} -> {answer} ({why})")

        if answer == COURSE_MATERIAL:
            if not args.dry_run:
                table("documents").update(
                    _decision(answer, confidence), filters={"id": f"eq.{doc_id}"},
                )
            continue

        # Locate the chunks by re-deriving their ids from this document's own
        # text, so the search does not depend on `doc_id` (last-writer-wins on a
        # deduped row — a filter on it misses the leaking case exactly).
        code = _course_code(doc.get("offering_id") or "")
        if not code or not text:
            print("      (no course code or no text — nothing to withdraw)")
            if not args.dry_run:
                table("documents").update(
                    _decision(answer, confidence), filters={"id": f"eq.{doc_id}"},
                )
            continue

        # BOTH chunking strategies, unioned. `chunk_for_category` routes on the
        # category, indexing used `classification.category`, and
        # `documents.category` is user-editable via PATCH /doc/{id} — so a
        # student who re-labels a solved problem set from `assignment` (prose
        # windows) to `other` (block chunks) would make a category-routed
        # re-chunk produce entirely different boundaries, different content
        # hashes, and zero matches. Any chunker change since the rows were
        # written does the same. There are only two strategies, so trying both
        # costs nothing and removes the whole failure mode.
        ids = sorted({
            chunk_id(code, c)
            for chunker in (chunk_prose, chunk_document)
            for c in chunker(text)
        })
        present = _existing(ids)

        if not present:
            # LOUD, and shareability is deliberately NOT stored. The next run
            # filters on `shareability is.null`, so writing it here would retire
            # the document permanently while its chunks stayed in the shared
            # pool — a clean-looking log over exactly the rows this script
            # exists to withdraw.
            print(
                f"      !! located NONE of this document's {len(ids)} expected "
                "chunk ids — NOT storing shareability, so a later run retries. "
                "Likely the chunker changed, or the text differs from what was "
                "indexed. Investigate before re-running."
            )
            unlocated += 1
            continue

        sole, joint = _sole_contributor_ids(present, user_id)
        shared_with_others += len(joint)
        print(f"      located {len(present)} chunk(s)")
        if joint:
            print(
                f"      {len(joint)} also uploaded by someone else — left "
                "shared, their classification stands"
            )
        if sole:
            print(f"      withdrawing {len(sole)} chunk(s)")

        if args.dry_run:
            continue

        table("documents").update(
            _decision(answer, confidence), filters={"id": f"eq.{doc_id}"},
        )
        for i in range(0, len(sole), _ID_BATCH):
            batch = sole[i : i + _ID_BATCH]
            # DELETE, not a visibility flip: the flip leaves the row reachable
            # through the contributor clause and the #629 resync would flip it
            # back. The cascade takes the ledger rows with it.
            table("course_chunks").delete(filters={"id": _in_list(batch)})
            deleted += len(batch)

    print("\nSummary:", ", ".join(f"{k}={v}" for k, v in sorted(counts.items())) or "nothing")
    print(f"chunks left shared (jointly uploaded): {shared_with_others}")
    if unlocated:
        print(
            f"!! {unlocated} document(s) had NONE of their expected chunks "
            "located and were left unclassified — re-run after investigating"
        )
    if args.dry_run:
        print("(dry run — nothing written; pass --apply)")
    else:
        print(f"chunks withdrawn: {deleted}")
        print(
            "\nNow re-index, so the withdrawn content comes back under the "
            "PRIVATE id namespace:\n"
            "    python scripts/backfill_document_chunks.py --apply"
        )


if __name__ == "__main__":
    main()

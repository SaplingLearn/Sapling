"""A full, live study dataset for a developer's own LOCAL account.

    python -m db.seed_local_study --owner-email you@gmail.com
    python -m db.seed_local_study --owner-user-id user_123

A new local account gets this once, by itself: ``seed_local_rich.seed_owner``
(what the sign-in watcher and the rich seed's owner flags run) calls ``apply``
after the rich copy is in and before it completes onboarding. The command
above is the way to put the data back, or forward to today, by hand.

Why this is not part of ``seed_local_rich``'s dataset: that dataset is FIXED.
Its dates never move, and the E2E journeys, the oracles and the integration
suite assert on the ``rich-*`` accounts row for row. It is also small: one
study guide, six flashcards, three quizzes, every exam in the past. This
script layers a term's worth of study data on top of an account that already
has the rich copy, in three of its classes: CS101, MATH210 and BIO110.

Per class it writes (content in ``db/local_study_data/``):

- graph_nodes/edges .. 16 to 18 concepts across all four mastery tiers, with
                       their prerequisites
- node_mastery_events  one per finished quiz and tutor session
- documents .......... 11 or 12 lectures, slides, readings and assignments and
                       a syllabus, uploaded over the last eleven weeks
- assignments ........ a past exam, one inside two weeks, a final, and
                       homework, quizzes and a project around them
- quiz_attempts ...... 11 to 15 finished quizzes over the last month, with
                       their quiz_responses (and, between the classes, one
                       waiting to be resumed and two abandoned)
- quiz_context ....... the digest (common mistakes, weak areas) per concept
- flashcards ......... a deck per concept, from never reviewed to well worn
- flashcard_sets ..... three saved sets, some tied to an exam
- sessions/messages .. four or five tutor sessions; tutor time is read from
                       their MESSAGE times (services/study/daily.py)
- study_guides ....... four or five guides. Between the classes: every
                       scope, goal and depth, every block type, some saved,
                       some with new lectures since, one still generating,
                       one with a failed section and one in the pre-redesign
                       format
- topic_checklists ... the course outline, grouped into four units and linked
                       to the exams, stored under the outline's REAL evidence
                       hash so the Study page does not regenerate it

Every date is relative to the day it runs, every row has a deterministic id
and every write is an upsert, so it is safe to re-run: running it again on a
later day moves the same rows back to "now" and puts them back as seeded (a
check you answered, a guide you regenerated). That is why the automatic run
happens only on an account's first seed and never again. It only writes rows
it owns (ids start with ``study-``), with three exceptions on the classes it
fills: a concept or prerequisite the account already has is updated in place
under the id it has, the quiz digest of such a concept is replaced, and so is
the class's one ``topic_checklists`` row.

An owner is required: the fixture accounts (``rich-*``) are the E2E baseline
and are never a default. Local only: refuses unless APP_ENV is local/test and
SUPABASE_URL is local. It calls no model and nothing outside the local stack;
every encrypted column is encrypted with the configured key.
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db import seed_helpers as h               # noqa: E402
from db.connection import table                # noqa: E402
from services.encryption import encrypt_if_present, encrypt_json  # noqa: E402

_ENCRYPTED_TEXT = {
    "assignments": ("points_possible", "points_earned"),
    "documents": ("summary", "extracted_text"),
    "flashcards": ("front", "back"),
    "messages": ("content",),
}
_ENCRYPTED_JSON = {
    "documents": ("concept_notes",),
    "quiz_attempts": ("questions_json", "answers_json"),
    "quiz_context": ("context_json",),
    "sessions": ("summary_json",),
    "study_guides": ("content", "answers"),
}
#: The key a table's rows are upserted on, where it is not ``id``. These two
#: are keyed the way the app writes them, so a row the app made for the same
#: answer or concept is replaced, never duplicated.
_ON_CONFLICT = {
    "quiz_responses": "attempt_id,question_index",
    "quiz_context": "user_id,concept_node_id",
}


def _encrypted(table_name: str, row: dict) -> dict:
    out = dict(row)
    for column in _ENCRYPTED_TEXT.get(table_name, ()):
        out[column] = encrypt_if_present(out[column])
    for column in _ENCRYPTED_JSON.get(table_name, ()):
        out[column] = None if out[column] is None else encrypt_json(out[column])
    return out


def _upsert(table_name: str, rows: list[dict]) -> None:
    """One bulk write per table: insert each row, or update it in place."""
    if rows:
        table(table_name).upsert(
            [_encrypted(table_name, row) for row in rows],
            on_conflict=_ON_CONFLICT.get(table_name, "id"),
        )


def _scope(owner_id: str, course_id: str) -> dict | None:
    """The owner's enrollment in the class, or None when they have none (a
    sample course they dropped stays dropped)."""
    # Imported here: it pulls in the agents package, which a `--help` or a
    # refused (non-local) run has no business loading.
    from fastapi import HTTPException
    from services.topic_checklist_service import resolve_scope

    try:
        # The SAME enrollment the Study page's outline and a new study guide
        # resolve (the current term's, else the student's most recent one), so
        # the documents and exams seeded here are the ones they read.
        return resolve_scope(owner_id, course_id, None)
    except HTTPException:
        return None


def _enrolled(owner_id: str, course_id: str, scope: dict):
    """What the account already has for the class: the concepts on its tree
    and the prerequisite edges out of them, which keep their ids."""
    from db.local_study_data import Enrolled

    found = table("graph_nodes").select(
        "id,concept_name", filters={"user_id": f"eq.{owner_id}", "course_id": f"eq.{course_id}"},
    ) or []
    nodes = {row["concept_name"]: row["id"] for row in found}
    linked = table("graph_edges").select(
        "id,source_node_id,target_node_id",
        filters={
            "user_id": f"eq.{owner_id}",
            "relationship_type": "eq.prerequisite",
            "source_node_id": f"in.({','.join(nodes.values())})",
        },
    ) if nodes else []
    return Enrolled(
        enrollment_id=scope["enrollment_id"],
        offering_id=scope["offering_id"],
        nodes=nodes,
        edges={(e["source_node_id"], e["target_node_id"]): e["id"] for e in linked or []},
    )


def _seed_outline(owner_id: str, scope: dict, topics: list[dict]) -> None:
    """Store the outline under the hash of the evidence as it NOW stands.

    Must run after the documents, exams and concepts are in: they are that
    evidence. A matching hash is what makes the Study page treat the outline
    as current; anything else and it would regenerate it with the model on the
    next visit, and the units and exam links seeded here would be whatever
    the model decided."""
    from services.topic_checklist_service import build_snapshot

    # (tests/test_seed_local_study.py validates the payload against the
    # outline's own model, so the script need not import the agents package.)
    table("topic_checklists").upsert({
        "enrollment_id": scope["enrollment_id"],
        "input_hash": build_snapshot(owner_id, scope)["hash"],
        "content": encrypt_json({"topics": topics}),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }, on_conflict="enrollment_id")


def _report(owner_id: str, rows: dict[str, list[dict]], outlines: int, skipped: list[str]) -> None:
    print(f"\nStudy seed (owner {owner_id}):")
    for table_name, table_rows in rows.items():
        print(f"  {table_name:22s} {len(table_rows)}")
    print(f"  {'topic_checklists':22s} {outlines}")
    for course_id in skipped:
        print(f"  (not enrolled in {course_id}: skipped)")
    print("\n  Open http://localhost:3000/study/guide, /study, /quiz and /flashcards.")


def apply(owner_id: str, now: datetime | None = None, *, report: bool = True) -> dict[str, int]:
    """Write the dataset onto the account; returns rows written per table.

    The CLI prints the per-table report (``report=True``); ``seed_owner``
    passes its own flag on, so a watcher thread prints nothing. Raises, never
    exits, so that thread gets an ordinary exception: ValueError when the
    account is in none of the classes, RuntimeError off a local stack.
    """
    if not h.is_local_backend():
        raise RuntimeError("REFUSING: the study seed only writes to a local stack.")
    # Imported here for the same reason as the outline service above: the
    # guide builder runs the app's own section check.
    from db.local_study_data import CLASSES, TABLES, outline, placements, plan

    now = now or datetime.now().astimezone()
    scopes = {data.key: _scope(owner_id, data.course_id) for data in CLASSES}
    skipped = [data.course_id for data in CLASSES if scopes[data.key] is None]
    enrolled = {
        data.key: _enrolled(owner_id, data.course_id, scopes[data.key])
        for data in CLASSES if scopes[data.key] is not None
    }
    if not enrolled:
        raise ValueError(
            "This account is enrolled in none of the sample classes. Sign in on the local "
            "stack, or run `python -m db.seed_local_rich` with the same --owner flag, first."
        )
    rows = plan(now, owner_id, enrolled)
    for table_name in TABLES:
        _upsert(table_name, rows[table_name])
    places = placements(now, owner_id, enrolled)
    for place in places:
        _seed_outline(owner_id, scopes[place.data.key], outline.topics(place))
    if report:
        _report(owner_id, rows, len(places), skipped)
    return {**{name: len(rows[name]) for name in TABLES}, "topic_checklists": len(places)}


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Seed a term of study data onto a local account.")
    owner_group = parser.add_mutually_exclusive_group(required=True)
    owner_group.add_argument("--owner-email", help="Email of an existing local Google account")
    owner_group.add_argument("--owner-user-id", help="ID of an existing local account")
    args = parser.parse_args(argv if argv is not None else [])
    if not h.local_app_env():
        sys.exit("REFUSING: the study seed requires APP_ENV=local or APP_ENV=test.")
    if not h.local_supabase_url():
        url = (os.getenv("SUPABASE_URL") or "").strip()
        sys.exit(f"REFUSING: SUPABASE_URL {url!r} is not local.")

    from db.seed_local_owner import resolve_owner
    try:
        owner_id = resolve_owner(email=args.owner_email, user_id=args.owner_user_id)["id"]
        apply(owner_id)
    except ValueError as exc:
        parser.exit(1, f"{exc}\n")


if __name__ == "__main__":
    main(sys.argv[1:])

"""Recent study activity for the LOCAL Study page, dated relative to today.

    python -m db.seed_local_study --owner-email you@gmail.com
    python -m db.seed_local_study --owner-user-id user_123
    python -m db.seed_local_study            # the fixture student (rich-user-active)

Why this is not part of ``seed_local_rich``: that dataset is FIXED. Its dates
never move, and the E2E journeys, the oracles and the integration suite assert
on it row for row. A few weeks after it was written every exam in it is in the
past and nothing was studied "this week", so the Study page has nothing to
show: zero minutes, no upcoming exam, no pace notice, no per-exam readiness.

This script layers a week of activity on top of an account that already has
the rich data (run ``seed_local_rich`` first), all of it in CS101:

- graph_nodes/edges .. seven more CS101 concepts (twelve in all) and their
                       prerequisites, so the roadmap has four full columns
- assignments ........ two upcoming exams and a homework due tomorrow
- quiz_attempts ...... four completed quizzes across the last five days
- flashcards ......... decks named for the concepts, some reviewed this week
- sessions/messages .. three tutor sessions; two were never "ended", so their
                       time comes from their last message (routes/study.py)
- node_mastery_events  this week's mastery changes (the "+N% this week" chip)
- topic_checklists ... the course outline, grouped into FOUR units and linked to
                       the two exams, stored under the outline's REAL evidence
                       hash so the Study page does not regenerate it

Every row has a deterministic id and is UPSERTED, so it is safe to re-run:
running it again on a later day moves the same rows back to "this week"
instead of adding more. It only ever writes rows it owns (ids start with
``study-``) plus the one ``topic_checklists`` row for the CS101 enrollment; the
five concepts the rich seed created are read, never changed.

Local only: refuses unless APP_ENV is local/test and SUPABASE_URL is local.
"""
from __future__ import annotations

import argparse
import hashlib
import os
import sys
from datetime import date, datetime, time, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import get_mastery_tier            # noqa: E402
from db import seed_helpers as h               # noqa: E402
from db.connection import table                # noqa: E402
from services.encryption import encrypt_if_present, encrypt_json  # noqa: E402

COURSE_ID = "rich-course-cs101"
FIXTURE_USER = "rich-user-active"

#: The CS101 concepts the rich seed tracks. Everything below hangs off these
#: names, so the script checks they exist before writing anything.
VARIABLES = "Variables and Types"
CONTROL_FLOW = "Control Flow"
RECURSION = "Recursion"
ALGORITHMS = "Algorithms"
POINTERS = "Pointers and Memory"
CONCEPTS = (VARIABLES, CONTROL_FLOW, RECURSION, ALGORITHMS, POINTERS)

#: Seven more, added by THIS seed (the rich seed's five cannot fill four
#: roadmap columns). (key, name, mastery 0..1, times studied, days since studied)
FUNCTIONS = "Functions"
ARRAYS = "Arrays and Strings"
STRUCTS = "Structs"
SORTING = "Sorting and Searching"
LINKED_LISTS = "Linked Lists"
STACKS = "Stacks and Queues"
TREES = "Trees"
_EXTRA_NODES = [
    ("functions", FUNCTIONS, 0.86, 6, 2),
    ("arrays", ARRAYS, 0.64, 4, 3),
    ("structs", STRUCTS, 0.0, 0, None),
    ("sorting", SORTING, 0.34, 3, 9),
    ("linkedlists", LINKED_LISTS, 0.52, 2, 6),
    ("stacks", STACKS, 0.0, 0, None),
    ("trees", TREES, 0.0, 0, None),
]
EXTRA_CONCEPTS = tuple(name for _, name, *_ in _EXTRA_NODES)
ALL_CONCEPTS = CONCEPTS + EXTRA_CONCEPTS

# Prerequisites among the twelve (source is needed before target). The rich
# seed already links some of its own five; these only ADD.
_EDGES = [
    (CONTROL_FLOW, FUNCTIONS), (FUNCTIONS, RECURSION),
    (VARIABLES, POINTERS), (VARIABLES, ARRAYS), (POINTERS, STRUCTS),
    (ARRAYS, SORTING), (ALGORITHMS, SORTING),
    (POINTERS, LINKED_LISTS), (STRUCTS, LINKED_LISTS),
    (LINKED_LISTS, STACKS), (LINKED_LISTS, TREES), (RECURSION, TREES),
]

# (key, title, type, days from today)
_ASSIGNMENTS = [
    ("midterm2", "Midterm 2", "exam", 9),
    ("final", "Final Exam", "exam", 27),
    ("hw6", "Homework 6: Recursion", "homework", 1),
]

# (key, concept, days ago, clock hour, minutes spent, score, total, mastery before, after)
# "Days ago 0" is anchored to NOW instead of a clock hour (see _moment).
_QUIZZES = [
    ("recursion", RECURSION, 0, 0, 7, 7, 10, 0.20, 0.25),
    ("controlflow", CONTROL_FLOW, 1, 17, 9, 8, 10, 0.52, 0.60),
    ("variables", VARIABLES, 3, 19, 6, 9, 10, 0.88, 0.92),
    ("algorithms", ALGORITHMS, 5, 16, 8, 8, 10, 0.74, 0.80),
]

# (key, concept, front, back, days ago it was last reviewed or None)
_FLASHCARDS = [
    ("rec-1", RECURSION, "What must every recursive function have?", "A base case that stops the recursion.", 0),
    ("rec-2", RECURSION, "What is the call stack?", "The record of active function calls, one frame each.", 0),
    ("rec-3", RECURSION, "What causes a stack overflow?", "Recursion that never reaches its base case.", 0),
    ("rec-4", RECURSION, "What is tail recursion?", "A recursive call that is the function's last action.", None),
    ("cf-1", CONTROL_FLOW, "What does `break` do in a loop?", "Exits the nearest enclosing loop immediately.", 1),
    ("cf-2", CONTROL_FLOW, "What does `continue` do?", "Skips to the loop's next iteration.", 1),
    ("cf-3", CONTROL_FLOW, "When does a `while` loop stop?", "When its condition evaluates to false.", 1),
    ("cf-4", CONTROL_FLOW, "What is short-circuit evaluation?", "Stopping a boolean expression once its result is known.", 1),
    ("ptr-1", POINTERS, "What is a pointer?", "A variable that holds a memory address.", 4),
    ("ptr-2", POINTERS, "What is a dangling pointer?", "A pointer to memory that has been freed.", 4),
]

# (key, concept, name, days ago, clock hour, explicitly ended after N minutes or None,
#  minutes into the session of each message)
# The two un-ended sessions are the common case in real use: the student closes
# the tab, so the session's length is its last message.
_SESSIONS = [
    ("recursion", RECURSION, "Tracing Recursive Calls", 2, 18, 25, (0, 4, 11, 19, 24)),
    ("controlflow", CONTROL_FLOW, "Loops and Conditions", 1, 20, None, (0, 5, 12, 17, 22)),
    ("pointers", POINTERS, "Getting Started with Pointers", 0, 0, None, (0, 3, 8, 12)),
]

_TUTOR_LINES = (
    ("user", "Can we go through {topic} again? I keep getting stuck."),
    ("assistant", "Of course. Tell me what you already know about {topic}, and where it stops making sense."),
    ("user", "I follow the definition, but I lose track when I try an example."),
    ("assistant", "Then let's take one small example and walk it line by line together."),
    ("user", "That helps. Can I try the next one myself?"),
)

# (key, concept, days ago, delta, reason)
_MASTERY_EVENTS = [
    ("recursion", RECURSION, 0, 0.05, "quiz: recursion"),
    ("controlflow", CONTROL_FLOW, 1, 0.08, "quiz: control flow"),
    ("variables", VARIABLES, 3, 0.04, "quiz: variables"),
    ("algorithms", ALGORITHMS, 5, 0.06, "quiz: algorithms"),
]

# The outline: FOUR units (the roadmap's columns, and the most it shows across),
# each concept under one, and which exams cover it. Midterm 2 is the middle of
# the course; the final is everything.
# (unit, [(concept, importance, prerequisites, exam keys)])
_OUTLINE = [
    ("Programming Foundations", [
        (VARIABLES, 0.8, [], ["final"]),
        (CONTROL_FLOW, 0.9, [VARIABLES], ["final"]),
        (FUNCTIONS, 0.9, [CONTROL_FLOW], ["midterm2", "final"]),
    ]),
    ("Memory and Data", [
        (POINTERS, 0.8, [VARIABLES], ["midterm2", "final"]),
        (ARRAYS, 0.8, [VARIABLES], ["midterm2", "final"]),
        (STRUCTS, 0.6, [POINTERS], ["final"]),
    ]),
    ("Algorithmic Problem Solving", [
        (RECURSION, 0.9, [FUNCTIONS], ["midterm2", "final"]),
        (ALGORITHMS, 0.8, [CONTROL_FLOW], ["midterm2", "final"]),
        (SORTING, 0.8, [ARRAYS, ALGORITHMS], ["midterm2", "final"]),
    ]),
    ("Data Structures", [
        (LINKED_LISTS, 0.8, [POINTERS, STRUCTS], ["final"]),
        (STACKS, 0.6, [LINKED_LISTS], ["final"]),
        (TREES, 0.7, [LINKED_LISTS, RECURSION], ["final"]),
    ]),
]


def id_prefix(owner_id: str) -> str:
    """Stable per-account prefix, so two local accounts never share rows."""
    return "study-" + hashlib.sha256(owner_id.encode()).hexdigest()[:10]


def _slug(name: str) -> str:
    return "-".join(name.lower().split())


def _moment(now: datetime, days_ago: int, hour: int, *, minutes_before_now: int = 0) -> datetime:
    """A point in the student's LOCAL day `days_ago` days back.

    Earlier days sit at a fixed clock hour. Today is anchored to `now` instead
    (`minutes_before_now`), because a fixed hour could be in the future."""
    if days_ago == 0:
        moment = now - timedelta(minutes=minutes_before_now)
        if moment.date() == now.date():
            return moment
        # Run just after midnight: "N minutes ago" was yesterday, which would
        # leave today empty. Pin it to the first seconds of today instead.
        return min(now, datetime.combine(now.date(), time(0, 0, 30), tzinfo=now.tzinfo))
    day = (now - timedelta(days=days_ago)).date()
    return datetime.combine(day, time(hour, 0), tzinfo=now.tzinfo)


def _utc(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).isoformat()


def plan(now: datetime, *, owner_id: str, enrollment_id: str, offering_id: str,
         nodes: dict[str, str]) -> dict[str, list[dict]]:
    """Every row this seed writes (the outline aside), as plaintext.

    Pure: `now` is an aware datetime in the student's local zone, `nodes` maps
    concept name -> graph node id. Encryption happens in `apply`, so a test can
    read what is planned."""
    prefix = id_prefix(owner_id)
    today: date = now.date()
    rows: dict[str, list[dict]] = {}

    extra_nodes = []
    for key, name, score, studied, days_since in _EXTRA_NODES:
        extra_nodes.append({
            "id": f"{prefix}-node-{key}", "user_id": owner_id, "course_id": COURSE_ID,
            "concept_name": name, "subject": name.split()[0],
            "mastery_score": score, "mastery_tier": get_mastery_tier(score),
            "times_studied": studied,
            "last_studied_at": None if days_since is None else _utc(_moment(now, days_since, 18)),
        })
    rows["graph_nodes"] = extra_nodes
    # Every concept's node id. A concept that already exists on the account
    # (the rich seed's five, or one of the seven from an earlier run) keeps the
    # id it has; `nodes` wins.
    node_ids = {**{row["concept_name"]: row["id"] for row in extra_nodes}, **nodes}
    for row in extra_nodes:
        row["id"] = node_ids[row["concept_name"]]
    # The id names the pair, not its position in the list: adding an edge must
    # not renumber the others onto rows that already exist.
    rows["graph_edges"] = [{
        "id": f"{prefix}-edge-{_slug(source)}--{_slug(target)}", "user_id": owner_id,
        "source_node_id": node_ids[source], "target_node_id": node_ids[target],
        "relationship_type": "prerequisite", "strength": 0.8,
    } for source, target in _EDGES]

    rows["assignments"] = [{
        "id": f"{prefix}-asg-{key}", "enrollment_id": enrollment_id, "title": title,
        "due_date": (today + timedelta(days=days)).isoformat(),
        "assignment_type": kind, "source": "manual", "points_possible": "100",
    } for key, title, kind, days in _ASSIGNMENTS]

    quizzes = []
    for key, concept, days_ago, hour, minutes, score, total, before, after in _QUIZZES:
        # Today's quiz finished 50 minutes ago, ahead of today's tutor session.
        done = _moment(now, days_ago, hour, minutes_before_now=50)
        quizzes.append({
            "id": f"{prefix}-qa-{key}", "user_id": owner_id, "concept_node_id": nodes[concept],
            "score": score, "total": total, "difficulty": "medium",
            "questions_json": [{"q": f"A question about {concept}.", "a": "The right answer"}],
            "answers_json": [{"q": f"A question about {concept}.", "given": "The right answer", "correct": True}],
            "created_at": _utc(done - timedelta(minutes=minutes)), "completed_at": _utc(done),
            "mastery_before": before, "mastery_after": after,
        })
    rows["quiz_attempts"] = quizzes

    cards = []
    for key, concept, front, back, reviewed_days_ago in _FLASHCARDS:
        reviewed = None if reviewed_days_ago is None else _moment(now, reviewed_days_ago, 21, minutes_before_now=20)
        cards.append({
            "id": f"{prefix}-fc-{key}", "user_id": owner_id, "offering_id": offering_id,
            # The topic is the concept's own name: that is how the Study page
            # counts a concept's cards and files a review under it.
            "topic": concept, "front": front, "back": back,
            "times_reviewed": 0 if reviewed is None else 2,
            "last_rating": None if reviewed is None else 3,
            "last_reviewed_at": None if reviewed is None else _utc(reviewed),
        })
    rows["flashcards"] = cards

    sessions, messages = [], []
    for key, concept, name, days_ago, hour, ended_after, beats in _SESSIONS:
        # Today's session started 40 minutes ago and is still "open".
        started = _moment(now, days_ago, hour, minutes_before_now=40)
        session_id = f"{prefix}-sess-{key}"
        sessions.append({
            "id": session_id, "user_id": owner_id, "offering_id": offering_id,
            "mode": "socratic", "topic": concept, "name": name,
            "summary_json": {"bullets": [f"Worked through {concept} with an example"]},
            "started_at": _utc(started),
            "ended_at": None if ended_after is None else _utc(started + timedelta(minutes=ended_after)),
        })
        for i, minute in enumerate(beats):
            role, line = _TUTOR_LINES[i % len(_TUTOR_LINES)]
            messages.append({
                "id": f"{session_id}-msg-{i + 1}", "session_id": session_id, "role": role,
                "content": line.format(topic=concept),
                # Never later than now (a session started minutes ago).
                "created_at": _utc(min(now, started + timedelta(minutes=minute))),
            })
    rows["sessions"], rows["messages"] = sessions, messages

    rows["node_mastery_events"] = [{
        "id": f"{prefix}-evt-{key}", "node_id": nodes[concept], "delta": delta, "reason": reason,
        "created_at": _utc(_moment(now, days_ago, 19, minutes_before_now=50)),
    } for key, concept, days_ago, delta, reason in _MASTERY_EVENTS]
    return rows


def outline_topics(prefix: str, source_id: str) -> list[dict]:
    """The stored outline (a TopicOutline payload), exams linked by assignment id."""
    topics = []
    for unit, children in _OUTLINE:
        topics.append({
            "name": unit, "description": f"{unit}: the concepts this part of the course builds.",
            "parent": "", "prerequisites": [], "source_ids": [source_id],
            "assessment_ids": [], "importance": 0.9,
        })
        for concept, importance, prerequisites, exams in children:
            topics.append({
                "name": concept, "description": f"{concept}, covered under {unit}.",
                "parent": unit, "prerequisites": prerequisites, "source_ids": [source_id],
                "assessment_ids": [f"{prefix}-asg-{key}" for key in exams],
                "importance": importance,
            })
    return topics


_ENCRYPTED_TEXT = {
    "assignments": ("points_possible",),
    "flashcards": ("front", "back"),
    "messages": ("content",),
}
_ENCRYPTED_JSON = {
    "quiz_attempts": ("questions_json", "answers_json"),
    "sessions": ("summary_json",),
}


def _encrypted(table_name: str, row: dict) -> dict:
    out = dict(row)
    for column in _ENCRYPTED_TEXT.get(table_name, ()):
        out[column] = encrypt_if_present(out[column])
    for column in _ENCRYPTED_JSON.get(table_name, ()):
        out[column] = encrypt_json(out[column])
    return out


def _insert_missing(table_name: str, rows: list[dict], keys: str, *, refresh: tuple[str, ...] = ()) -> None:
    """Insert rows whose natural key is not there yet. One that is there is left
    exactly as it is (it may be the rich seed's, or the student's own), apart
    from the `refresh` columns, which are this seed's dates."""
    for row in rows:
        natural = {key: row[key] for key in keys.split(",")}
        if h.exists_by(table_name, natural):
            if refresh:
                table(table_name).update(
                    {column: row[column] for column in refresh},
                    filters={key: f"eq.{value}" for key, value in natural.items()},
                )
            h.record(table_name, created=False)
        else:
            table(table_name).insert(_encrypted(table_name, row))
            h.record(table_name, created=True)


def _upsert(table_name: str, rows: list[dict], on_conflict: str = "id") -> None:
    for row in rows:
        existed = h.exists_by(table_name, {key: row[key] for key in on_conflict.split(",")})
        table(table_name).upsert(_encrypted(table_name, row), on_conflict=on_conflict)
        h.record(table_name, created=not existed)


def _context(owner_id: str) -> dict:
    """The owner's CS101 enrollment and concept nodes, or a clear reason why not."""
    # Imported here: it pulls in the agents package, which a `--help` or a
    # refused (non-local) run has no business loading.
    from fastapi import HTTPException
    from services.topic_checklist_service import resolve_scope

    try:
        # The SAME enrollment the Study page's outline is read for (the current
        # term's, else the student's most recent one), so the exams seeded here
        # are the ones the outline can link.
        scope = resolve_scope(owner_id, COURSE_ID, None)
    except HTTPException as exc:
        raise SystemExit(
            f"This account has no CS101 enrollment ({exc.detail}). "
            "Run `python -m db.seed_local_rich` (with the same --owner flag) first."
        ) from None
    found = table("graph_nodes").select(
        "id,concept_name", filters={"user_id": f"eq.{owner_id}", "course_id": f"eq.{COURSE_ID}"},
    ) or []
    # Only the concepts this seed knows: the five it needs, plus any of its
    # seven that an earlier run (or the student) already created.
    nodes = {r["concept_name"]: r["id"] for r in found if r["concept_name"] in ALL_CONCEPTS}
    missing = [c for c in CONCEPTS if c not in nodes]
    if missing:
        raise SystemExit(
            f"This account is missing CS101 concepts {missing}. "
            "Run `python -m db.seed_local_rich` (with the same --owner flag) first."
        )
    return {"scope": scope, "nodes": nodes}


def _seed_outline(owner_id: str, scope: dict) -> bool:
    """Store the outline under the hash of the evidence as it NOW stands.

    Must run after the exams are in: they are part of that evidence. A matching
    hash is what makes the Study page treat the outline as current; anything
    else and it would regenerate it with the model on the next visit, and the
    exam links seeded here would be whatever the model decided."""
    from services.topic_checklist_service import build_snapshot

    snapshot = build_snapshot(owner_id, scope)
    sources = snapshot["payload"]["sources"]
    if not sources:
        print("  (no course material for CS101 on this account: outline skipped)")
        return False
    topics = outline_topics(id_prefix(owner_id), sources[0]["id"])
    # (tests/test_seed_local_study.py validates this payload against the
    # outline's own model, so the script need not import the agents package.)
    _upsert("topic_checklists", [{
        "enrollment_id": scope["enrollment_id"], "input_hash": snapshot["hash"],
        "content": encrypt_json({"topics": topics}),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }], on_conflict="enrollment_id")
    return True


_SUMMARY_ORDER = [
    "graph_nodes", "graph_edges", "assignments", "quiz_attempts", "flashcards", "sessions", "messages",
    "node_mastery_events", "topic_checklists",
]


def apply(owner_id: str, now: datetime | None = None) -> None:
    if not h.is_local_backend():
        raise RuntimeError("REFUSING: the study seed only writes to a local stack.")
    now = now or datetime.now().astimezone()
    context = _context(owner_id)
    scope = context["scope"]
    rows = plan(now, owner_id=owner_id, enrollment_id=scope["enrollment_id"],
                offering_id=scope["offering_id"], nodes=context["nodes"])
    h.reset_counts()
    # Concepts before their edges, sessions before their messages (FKs); the
    # outline last, because the concepts and exams are part of its evidence.
    _insert_missing("graph_nodes", rows["graph_nodes"], "user_id,course_id,concept_name",
                    refresh=("last_studied_at",))
    _insert_missing("graph_edges", rows["graph_edges"],
                    "user_id,source_node_id,target_node_id,relationship_type")
    for table_name in ("assignments", "quiz_attempts", "flashcards", "sessions", "messages",
                       "node_mastery_events"):
        _upsert(table_name, rows[table_name])
    _seed_outline(owner_id, scope)
    # Not h.print_summary: its "re-run was a no-op" line would be wrong here,
    # where a re-run re-dates every row it finds.
    print(f"\nStudy seed (owner {owner_id}, CS101 {scope['semester']}):".replace("  ", " "))
    for name in _SUMMARY_ORDER:
        c = h.counts.get(name, {"created": 0, "skipped": 0})
        print(f"  {name:22s} created={c['created']:<3d} re-dated={c['skipped']}")
    print("\n  Open http://localhost:3000/study and pick CS101.")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Seed a week of study activity into a local stack.")
    owner_group = parser.add_mutually_exclusive_group()
    owner_group.add_argument("--owner-email", help="Email of an existing local Google account")
    owner_group.add_argument("--owner-user-id", help="ID of an existing local account")
    args = parser.parse_args(argv if argv is not None else [])
    if not h.local_app_env():
        sys.exit("REFUSING: the study seed requires APP_ENV=local or APP_ENV=test.")
    if not h.local_supabase_url():
        url = (os.getenv("SUPABASE_URL") or "").strip()
        sys.exit(f"REFUSING: SUPABASE_URL {url!r} is not local.")

    owner_id = FIXTURE_USER
    if args.owner_email is not None or args.owner_user_id is not None:
        from db.seed_local_owner import resolve_owner
        try:
            owner_id = resolve_owner(email=args.owner_email, user_id=args.owner_user_id)["id"]
        except ValueError as exc:
            parser.exit(1, f"{exc}\n")
    apply(owner_id)


if __name__ == "__main__":
    main(sys.argv[1:])

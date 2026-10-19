"""Opt-in, LOCAL E2E assets for a real graded prerequisite→goal journey.

The normal rich seed is unchanged. Before any learner session, diagnostic
replaces only Binary/Bitwise course items with free-response variants and
installs an explicitly synthetic .99 initial prior (zero observations). Once
the real diagnostic reaches its plan, practice adds fresh free/teachback level
3 items. A released free-response class remains a recheck; the new teachback
class can earn independent evidence through the ordinary grader. No attempt,
evidence, release, help, goal or session metadata is written here.

The optional pre-activity readiness stage adds an independent fourth fixture
concept, Binary Place Value. Its source is the rich Binary course chunk; its
topology and function-model questions are synthetic browser test inputs, never
real learner evidence or a claim that four concepts were pedagogically verified.
"""

from __future__ import annotations

import argparse
import os
from urllib.parse import urlsplit

from db import seed_helpers as h
from db.connection import table
from db.seed_local_rich import COURSE_CS, USER_LOOP, loop_node_id
from learning.checks import question_hash
from services.encryption import decrypt_if_present, encrypt_if_present

SLUGS = ("binary", "bitwise")
DIAGNOSTIC_COUNTS = {1: 1, 2: 6, 3: 3}
INITIAL_PRIOR = 0.99  # Test input, never a claim earned by these questions.
READINESS_CONCEPT = "Binary Place Value"


def _require_local() -> None:
    host = urlsplit(os.getenv("SUPABASE_URL", "")).hostname
    if host not in {"127.0.0.1", "localhost", "::1"} or os.getenv("APP_ENV") not in {
        "local",
        "test",
    }:
        raise RuntimeError("Goal journey fixtures require a local/test loopback database")


def _template(item_id: str) -> dict:
    rows = table("check_items").select("*", filters={"id": f"eq.{item_id}"}, limit=1)
    if not rows or rows[0]["course_id"] != COURSE_CS:
        raise RuntimeError(f"Missing canonical rich journey item: {item_id}")
    return rows[0]


def fixture_item(template: dict, *, slug: str, stage: str, format: str, variant: int) -> dict:
    """Clone the reviewed function-mode asset, preserving source and rubric.

    Hash the novel plaintext BEFORE canonical encryption. The fixture's
    variation marker identifies the scripted case, not a calibrated question.
    """
    row = {key: value for key, value in template.items() if key != "created_at"}
    difficulty = int(template["difficulty"])
    row["id"] = f"rich-goal-{slug}-{stage}-{format}-d{difficulty}-{variant}"
    prompt = (
        f"{decrypt_if_present(template['prompt'])} "
        f"[goal journey {stage}, {format}, variant {variant}]"
    )
    row.update(
        format=format,
        prompt=encrypt_if_present(prompt),
        question_hash=question_hash(prompt),
        graded=False,
    )
    return row


def _require_readiness_pristine(sessions: list) -> None:
    """Check every existing owned course node before changing this fixture."""
    owned = table("graph_nodes").select(
        "id", filters={"user_id": f"eq.{USER_LOOP}", "course_id": f"eq.{COURSE_CS}"}
    )
    ids = sorted(row["id"] for row in owned if row.get("id"))
    if (
        not ids
        or sessions
        or table("node_mastery_events").select(
            "id", filters={"node_id": f"in.({','.join(ids)})"}, limit=1
        )
    ):
        raise RuntimeError("Readiness fixtures must precede every learner session and observation")


def _seed_readiness_concept(templates: dict) -> None:
    from db.e2e_handler_constants import read_constants
    from services.graph_service import _normalize_concept, apply_graph_update

    # The actual writer owns identity generation, ownership and deduplication.
    # Tests discover its UUID by exact owner/course/name rather than forcing IDs.
    apply_graph_update(USER_LOOP, {"new_nodes": [{"concept_name": READINESS_CONCEPT}]}, COURSE_CS)
    nodes = table("graph_nodes").select(
        "id",
        filters={
            "user_id": f"eq.{USER_LOOP}",
            "course_id": f"eq.{COURSE_CS}",
            "concept_name": f"eq.{READINESS_CONCEPT}",
        },
        limit=2,
    )
    if len(nodes) != 1 or not nodes[0].get("id"):
        raise RuntimeError("Readiness concept was not created uniquely by the graph writer")
    (stem,) = read_constants("E2E_LOOP_PROBE_PROMPT")
    for difficulty, count in DIAGNOSTIC_COUNTS.items():
        template = templates["binary", difficulty]
        if not template.get("source_chunk_ids"):
            raise RuntimeError("Readiness assets require the existing Binary course source chunk")
        for variant in range(count):
            row = fixture_item(
                template, slug="place-value", stage="readiness", format="free", variant=variant
            )
            prompt = f"{stem} [{READINESS_CONCEPT}, free, difficulty {difficulty}, readiness variant {variant}]"
            row["prompt"], row["question_hash"] = encrypt_if_present(prompt), question_hash(prompt)
            row["concept_key"] = _normalize_concept(READINESS_CONCEPT)
            h.upsert("check_items", row, on_conflict="course_id,concept_key,question_hash")
    h.upsert(
        "learner_state",
        {"user_id": USER_LOOP, "node_id": nodes[0]["id"], "p_known": INITIAL_PRIOR},
        on_conflict="user_id,node_id",
    )


def seed_goal_continuation_items(stage: str) -> None:
    _require_local()
    if stage not in {"diagnostic", "practice", "readiness"}:
        raise ValueError("stage must be diagnostic, practice or readiness")
    sessions = table("sessions").select(
        "id,ended_at,loop_state", filters={"user_id": f"eq.{USER_LOOP}"}
    )
    if stage in {"diagnostic", "readiness"}:
        if stage == "readiness":
            _require_readiness_pristine(sessions)
        if sessions or table("node_mastery_events").select(
            # 0023_graph_integrity: events belong to a node, not user_id.
            "id",
            filters={
                "node_id": f"in.({','.join(loop_node_id(USER_LOOP, slug) for slug in SLUGS)})"
            },
            limit=1,
        ):
            raise RuntimeError(
                "Diagnostic fixtures must precede every learner session and observation"
            )
        # Read all canonical templates before replacing either concept's bank.
        templates = {
            (slug, difficulty): _template(f"rich-check-{slug}-free-d{difficulty}")
            for slug in SLUGS
            for difficulty in DIAGNOSTIC_COUNTS
        }
        if stage == "readiness" and any(
            not templates["binary", difficulty].get("source_chunk_ids")
            for difficulty in DIAGNOSTIC_COUNTS
        ):
            raise RuntimeError("Readiness assets require the existing Binary course source chunk")
        for slug in SLUGS:
            key = templates[slug, 1]["concept_key"]
            table("check_items").delete(
                {"course_id": f"eq.{COURSE_CS}", "concept_key": f"eq.{key}"}
            )
            for difficulty, count in DIAGNOSTIC_COUNTS.items():
                for variant in range(count):
                    row = fixture_item(
                        templates[slug, difficulty],
                        slug=slug,
                        stage="diagnostic",
                        format="free",
                        variant=variant,
                    )
                    h.upsert("check_items", row, on_conflict="course_id,concept_key,question_hash")
            h.upsert(
                "learner_state",
                {
                    "user_id": USER_LOOP,
                    "node_id": loop_node_id(USER_LOOP, slug),
                    "p_known": INITIAL_PRIOR,
                },
                on_conflict="user_id,node_id",
            )
        if stage == "readiness":
            _seed_readiness_concept(templates)
    else:
        open_plans = [
            row
            for row in sessions
            if not row.get("ended_at")
            and isinstance(row.get("loop_state"), dict)
            and row["loop_state"].get("phase") == "plan"
            and row["loop_state"].get("goal")
        ]
        if len(open_plans) != 1:
            raise RuntimeError(
                "Practice assets require exactly one real, goal-scoped diagnostic plan"
            )
        for slug in SLUGS:
            template = _template(f"rich-goal-{slug}-diagnostic-free-d3-0")
            for format in ("free", "teachback"):
                row = fixture_item(template, slug=slug, stage=stage, format=format, variant=0)
                h.upsert("check_items", row, on_conflict="course_id,concept_key,question_hash")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=("diagnostic", "practice", "readiness"))
    seed_goal_continuation_items(parser.parse_args().stage)

"""Opt-in, LOCAL E2E assets for the varied-practice journeys (learning-loop
spec §13 A140, A141; frontend/e2e/learn-varied-practice.spec.ts).

The normal rich seed is unchanged. Each stage adds synthetic concepts to the
loop student's course (through the graph writer), their question assets
(through the app's own check-item write: encrypted, hashed, linted) and one
teach-phase session planned on them, and prints the ids the journey drives the
REAL routes with as JSON. It writes no attempt, evidence, release, help or
flag: the journey turns its flags on and earns every observation by grading.

Every concept also gets one free item at difficulty 2, stored first: the
concept's post-test reserve (A23/A126 — the free item at the middle
difficulty), which no in-session check ever poses, so the practice items
below are exactly what the journey's checks choose among.

- `varied` (A140): one concept with three free items at difficulty 1, each
  stored by its own write so they are created in order — S, then T1 on S's
  surface, then T2 on another. The first check poses S (the oldest; no surface
  is met yet). Once S is graded, T1's surface is met and T2's is not: with
  varied_isomorphs on the next check poses T2, with it off T1 (the oldest).
- `multi` (A141): a prerequisite and an apex concept joined by a real
  `prerequisite` edge, two items of the prerequisite (free, then teachback)
  and one of the apex at difficulty 3, the combination's free and teachback
  items (stored under its key with its apex and components), and an explicitly
  synthetic 0.99 prior on both concepts with ZERO observations — a test input,
  never a claim earned by these questions: the gate's strong unassisted
  observation on each component is earned by the journey's own correct
  answers. The session is planned [prerequisite, apex].
"""

from __future__ import annotations

import argparse
import json
import os
import uuid
from urllib.parse import urlsplit

from db import seed_helpers as h
from db.connection import table
from db.seed_local_rich import COURSE_CS, OFF_CS_S26, USER_LOOP

INITIAL_PRIOR = 0.99  # Test input, never a claim earned by these questions.
FINAL = "The size of each parameter update step"


def _require_local() -> None:
    host = urlsplit(os.getenv("SUPABASE_URL", "")).hostname
    if host not in {"127.0.0.1", "localhost", "::1"} or os.getenv("APP_ENV") not in {
        "local",
        "test",
    }:
        raise RuntimeError("Varied-practice fixtures require a local/test loopback database")


def _draft(concept: str, prompt: str, fmt: str = "free", difficulty: int = 2, **surface):
    from learning.checks import CheckItemDraft
    from learning.surface import SurfacedCheckItemDraft

    fields = dict(
        concept=concept,
        format=fmt,
        difficulty=difficulty,
        prompt=prompt,
        reference_answer=f"Each step moves the parameters by the rate. Final answer: {FINAL}.",
        final_answer=FINAL,
        rubric=["Names the step size.", "Ties the step to the gradient."],
        wrong_keys=["rate_is_iteration_count"],
        wrong_texts=["Confuses the learning rate with the number of iterations."],
    )
    if surface:
        return SurfacedCheckItemDraft(**fields, **surface)
    return CheckItemDraft(**fields)


def _store(key: str, drafts) -> list[str]:
    """The app's own write (services/check_item_service._store_screened):
    every text encrypted, the hash over the plaintext prompt, linted, the key
    marked verified as an agreeing A124 solve would leave it."""
    from services.check_item_service import _Screened, _store_screened

    screened = [_Screened(d.format, d, verified=True, key_checked=True) for d in drafts]
    return _store_screened(COURSE_CS, key, None, screened).ids


def _reserve(key: str, name: str, token: str) -> None:
    """The concept's post-test reserve: a free item at the middle difficulty."""
    from learning.params import CHECK_ITEM_DIFFICULTIES

    prompt = f"[e2e-reserve] What does the learning rate control? ({name}, {token})"
    _store(key, [_draft(name, prompt, difficulty=CHECK_ITEM_DIFFICULTIES[1])])


def _hashes(ids: list[str]) -> list[str]:
    rows = table("check_items").select("id,question_hash", filters={"id": f"in.({','.join(ids)})"})
    by_id = {r["id"]: r["question_hash"] for r in rows or []}
    return [by_id[i] for i in ids]


def _node(name: str) -> str:
    rows = table("graph_nodes").select(
        "id",
        filters={"user_id": f"eq.{USER_LOOP}", "course_id": f"eq.{COURSE_CS}", "concept_name": f"eq.{name}"},
        limit=2,
    )
    if len(rows or []) != 1:
        raise RuntimeError(f"{name!r} was not created uniquely by the graph writer")
    return rows[0]["id"]


def _session(plan: list[str]) -> str:
    session = str(uuid.uuid4())
    table("sessions").insert(
        {
            "id": session,
            "user_id": USER_LOOP,
            "offering_id": OFF_CS_S26,
            "mode": "socratic",
            "topic": "Varied practice journey",
            "loop_state": {
                "phase": "teach",
                "plan": {"approved": plan, "cursor": 0},
                "concept": plan[0],
                "teach_turns": 0,
                "concept_checks": 0,
            },
            "loop_state_rev": 0,
        }
    )
    return session


def seed_varied() -> dict:
    from services.check_item_service import concept_key
    from services.graph_service import apply_graph_update

    token = uuid.uuid4().hex[:8]
    name = f"Varied Practice Concept {token}"
    apply_graph_update(USER_LOOP, {"new_nodes": [{"concept_name": name}]}, COURSE_CS)
    node, key = _node(name), concept_key(name)
    _reserve(key, name, token)
    ids = []
    for label, rep, ctx in (
        ("S", "applied", "e2e lecture recap"),
        ("T1", "applied", "e2e lecture recap"),
        ("T2", "numeric", "e2e step sizes"),
    ):
        prompt = f"[e2e-varied][{label}] In one sentence, what does the learning rate control? ({token})"
        draft = _draft(name, prompt, difficulty=1, surface_representation=rep, surface_context=ctx)
        ids += _store(key, [draft])
    return {"session_id": _session([node]), "node_id": node, "hashes": dict(zip(("S", "T1", "T2"), _hashes(ids)))}


def seed_multi() -> dict:
    from learning.multi_concept import combo_key
    from learning.params import CHECK_ITEM_FORMATS, MULTI_CONCEPT_DIFFICULTY
    from services.check_item_service import concept_key
    from services.concept_prereqs import edge_payload
    from services.graph_service import apply_graph_update

    token = uuid.uuid4().hex[:8]
    pre, apex = f"Varied Prerequisite {token}", f"Varied Apex {token}"
    apply_graph_update(
        USER_LOOP,
        {
            "new_nodes": [{"concept_name": pre}, {"concept_name": apex}],
            "new_edges": [edge_payload(pre, apex)],
        },
        COURSE_CS,
    )
    pre_node, apex_node = _node(pre), _node(apex)
    pre_key, apex_key = concept_key(pre), concept_key(apex)
    d3 = MULTI_CONCEPT_DIFFICULTY
    _reserve(pre_key, pre, token)
    _reserve(apex_key, apex, token)
    _store(pre_key, [_draft(pre, f"[e2e-multi][pre][free] What is the step size? ({token})", difficulty=d3)])
    _store(pre_key, [_draft(pre, f"[e2e-multi][pre][teachback] Teach the step size. ({token})", "teachback", d3)])
    _store(apex_key, [_draft(apex, f"[e2e-multi][apex][free] What does the rate scale? ({token})", difficulty=d3)])
    label = f"{apex} + {pre}"
    combo_ids = _store(
        combo_key([apex_key, pre_key]),
        [
            _draft(label, f"[e2e-multi][combo][{fmt}] Pick a rate for this descent run. ({token})", fmt, d3)
            for fmt in CHECK_ITEM_FORMATS
            if fmt != "mc_reason"  # the journey answers a free or teachback combination
        ],
    )
    for node in (pre_node, apex_node):
        h.upsert(
            "learner_state",
            {"user_id": USER_LOOP, "node_id": node, "p_known": INITIAL_PRIOR},
            on_conflict="user_id,node_id",
        )
    return {
        "session_id": _session([pre_node, apex_node]),
        "pre_node": pre_node,
        "apex_node": apex_node,
        "combo_hashes": _hashes(combo_ids),
        "combo_key": combo_key([apex_key, pre_key]),
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=("varied", "multi"))
    _require_local()
    out = seed_varied() if parser.parse_args().stage == "varied" else seed_multi()
    print(json.dumps(out))

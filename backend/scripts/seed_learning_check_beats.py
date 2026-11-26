"""Opt-in, LOCAL E2E assets for the W1.3 close-beat and W2.3
reason-before-submit journeys (frontend/e2e/learn-loop.spec.ts).

The rich seed's loop items are free / teachback only (SEED_LOOP_FORMATS), and
the real diagnostic spends most of them, so a journey walked off the rich seed
cannot choose which formats a concept's checks may serve — and cannot tell the
W1.3 preference apart from the plain rotation (on the second check the
rotation already puts teachback first). Each stage here adds synthetic
concepts to the loop student's course (through the graph writer), their items
(through the app's own check-item write: encrypted, hashed, lettered — the
varied-practice seed's writer) and one teach-phase session planned on them,
and prints the ids the journey drives the REAL UI with as JSON. It writes no
attempt, evidence, release, help or flag.

Every concept gets its post-test reserve first (a free item at the middle
difficulty, never posed in session), so the items below are exactly what the
concept's checks choose among. Every practice item is at difficulty 1.

- `close` (W1.3): plan [close concept, next concept]. The close concept has
  two free items (F1 stored before F2) and one mc_reason item (M). Check 1
  rotates free first → F1. Check 2 is the segment close
  (concept_checks == LOOP_CHECKS_PER_CONCEPT - 1): the plain rotation there is
  (teachback, mc_reason, free) and there is no teachback, so without the
  generative-core preference it would pose M; with it, F2. The next concept
  has one free item, so the cursor's move is visible after the close beat.
- `reason` (W2.3): plan [reason concept]. One free item (F) and one
  mc_reason item (M). Check 1 → F (optional reasoning box); check 2, the
  segment close, finds no generative item left and falls back to M (the
  graded one-sentence reason, required to submit).

Usage: `python -m scripts.seed_learning_check_beats <close|reason>` (from
backend/). Frontend: `frontend/e2e/support/db.ts::seedCheckBeats`.
"""

from __future__ import annotations

import argparse
import json
import uuid

from db.connection import table
from db.seed_local_rich import COURSE_CS, OFF_CS_S26, USER_LOOP
from scripts.seed_learning_varied_practice import (
    FINAL,
    _draft,
    _hashes,
    _node,
    _require_local,
    _reserve,
    _store,
)

#: mc_reason options: the correct one first (the writer letters and places
#: them), each distractor with its own misconception (A37).
_OPTIONS = (
    (FINAL, None, None),
    ("The number of iterations to run", "rate_is_iteration_count",
     "Confuses the learning rate with the number of iterations."),
    ("The value of the loss", "rate_is_loss_value",
     "Treats the learning rate as the loss being minimised."),
    ("The sign of the gradient", "rate_sets_step_direction",
     "Thinks the learning rate sets the direction of the step."),
)


def _mc_draft(concept: str, prompt: str):
    from learning.checks import CheckItemDraft, OptionDraft

    return CheckItemDraft(
        concept=concept,
        format="mc_reason",
        difficulty=1,
        prompt=prompt,
        options=[
            OptionDraft(text=text, is_correct=key is None, misconception_key=key, misconception_text=why)
            for text, key, why in _OPTIONS
        ],
        reference_answer=f"Each step moves the parameters by the rate. Final answer: {FINAL}.",
        final_answer=FINAL,
        rubric=["Names the step size.", "Ties the step to the gradient."],
        wrong_keys=[],
        wrong_texts=[],
    )


def _concept(label: str, token: str) -> tuple[str, str, str]:
    """A fresh concept on the loop student's course: (name, node id, key)."""
    from services.check_item_service import concept_key
    from services.graph_service import apply_graph_update

    name = f"{label} {token}"
    apply_graph_update(USER_LOOP, {"new_nodes": [{"concept_name": name}]}, COURSE_CS)
    key = concept_key(name)
    _reserve(key, name, token)
    return name, _node(name), key


def _free(key: str, name: str, tag: str, token: str) -> str:
    prompt = f"[e2e-beat][{tag}] In your own words, what does the learning rate control? ({token})"
    return _store(key, [_draft(name, prompt, difficulty=1)])[0]


def _mc(key: str, name: str, tag: str, token: str) -> str:
    prompt = f"[e2e-beat][{tag}] Which option names what the learning rate controls? ({token})"
    return _store(key, [_mc_draft(name, prompt)])[0]


def _session(plan: list[str], topic: str) -> str:
    session = str(uuid.uuid4())
    table("sessions").insert(
        {
            "id": session,
            "user_id": USER_LOOP,
            "offering_id": OFF_CS_S26,
            "mode": "socratic",
            "topic": topic,
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


def seed_close() -> dict:
    token = uuid.uuid4().hex[:8]
    name, node, key = _concept("Close Beat Concept", token)
    # stored in this order: F1 is the older free item, so check 1 takes it
    ids = {"F1": _free(key, name, "F1", token), "F2": _free(key, name, "F2", token), "M": _mc(key, name, "M", token)}
    next_name, next_node, next_key = _concept("Close Beat Next", token)
    _free(next_key, next_name, "N1", token)
    return {
        "session_id": _session([node, next_node], "Close beat journey"),
        "node_id": node,
        "next_node_id": next_node,
        "hashes": dict(zip(ids, _hashes(list(ids.values())), strict=True)),
    }


def seed_reason() -> dict:
    token = uuid.uuid4().hex[:8]
    name, node, key = _concept("Reason Concept", token)
    ids = {"F": _free(key, name, "F", token), "M": _mc(key, name, "M", token)}
    return {
        "session_id": _session([node], "Reason before submit journey"),
        "node_id": node,
        "hashes": dict(zip(ids, _hashes(list(ids.values())), strict=True)),
        "mc_correct_text": FINAL,
    }


if __name__ == "__main__":
    from services.encryption_canary import abort_unless_key_verified

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=("close", "reason"))
    stage = parser.parse_args().stage
    _require_local()
    # M14: never seal under a key the database was not written with.
    abort_unless_key_verified("scripts.seed_learning_check_beats")
    print(json.dumps(seed_close() if stage == "close" else seed_reason()))

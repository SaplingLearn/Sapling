"""Self-explanation prompts (spec §13 A139, flag `self_explanation_prompts`).
Pure: loop-state documents and step records in, decisions out — no I/O, no
model, no PKG-06 import (rungs are plain ints), so it sits in PURE_MODULES.

At a key juncture the turn's single question (A121: one open question per
turn) becomes an interrogative "why does this follow?" prompt — Bisra et al.
2018: prompted self-explanation g = 0.55, interrogative prompts 0.56 against
imperative 0.40; the benefit comes from the student generating the
explanation, at junctures rather than at every step (VanLehn 2011: finer than
the step adds little). The junctures are decided HERE, in code, never by the
model:

  • `worked_example`    — a hint turn served at H4, the worked example on an
                          isomorph (the self-explanation literature's home ground);
  • `released_solution` — a hint turn at H5 (the completion problem) or H6 (the
                          worked answer), or a feedback turn that released the
                          answer (a wrong or idk answer: the stored reference is
                          shown above it);
  • `first_correct`     — the feedback turn of the session's first check on the
                          concept answered correctly with no help (correct, rung
                          0 after the help floor, not assisted — A133's "correct
                          with no help").

At most SELF_EXPLAIN_MAX_PER_CONCEPT prompts per concept per session: the
first juncture the concept reaches takes it. The reply is DIAGNOSTIC only: it
is stored encrypted (learning/self_explain_store.py) for staff analysis and is
never evidence, mastery, a misconception record or a band-control input — the
audit's warning: LLM readings of free-text explanations raise about four false
alarms per true misconception, so nothing here reads it at all.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from learning.params import SELF_EXPLAIN_JUNCTURES, SELF_EXPLAIN_MAX_PER_CONCEPT

#: loop_state key: {"open": the open prompt | None, "prompted": [node ids],
#: "ack": a replied prompt's id the next model turn acknowledges | None}.
KEY = "self_explain"

#: The prompts, one interrogative sentence each, ending in a single "?" (the
#: turn shape's question rule). Code's text, never the model's: the juncture
#: decides which. loop_state stores the KEY (A38: no free text there).
WORKED_EXAMPLE_PROMPT = "Why does each step of that worked example follow from the one before it?"
COMPLETION_PROMPT = "Why does each step shown so far follow from the one before it?"
RELEASED_ANSWER_PROMPT = "Why does that answer follow from what the question gives you?"
FIRST_CORRECT_PROMPT = "Why does your answer follow from what the question gives you?"
PROMPTS: dict[str, str] = {
    "worked_example": WORKED_EXAMPLE_PROMPT,
    "completion": COMPLETION_PROMPT,
    "released_answer": RELEASED_ANSWER_PROMPT,
    "first_correct": FIRST_CORRECT_PROMPT,
}


def prompt_text(prompt: Mapping[str, Any]) -> str:
    """The text of a stored prompt (its `prompt_key`)."""
    return PROMPTS[prompt["prompt_key"]]

_H4, _H5, _H6 = 4, 5, 6


def _doc(state: Mapping[str, Any]) -> dict:
    raw = state.get(KEY)
    return raw if isinstance(raw, dict) else {}


def prompted(state: Mapping[str, Any]) -> list[str]:
    """The concepts this session already prompted on, in order."""
    return [n for n in _doc(state).get("prompted") or [] if isinstance(n, str)]


def may_prompt(state: Mapping[str, Any], node_id: str | None) -> bool:
    """Below the per-concept cap for this session (SELF_EXPLAIN_MAX_PER_CONCEPT)."""
    return bool(node_id) and prompted(state).count(node_id) < SELF_EXPLAIN_MAX_PER_CONCEPT


def unhelped_correct(entry: Mapping[str, Any] | None) -> bool:
    """A graded step answered correctly with no help: verdict correct, its
    recorded rung 0 (the help floor already applied, A93) and not assisted."""
    if not isinstance(entry, Mapping):
        return False
    rung = entry.get("max_rung")
    return (
        entry.get("last_verdict") == "correct"
        and not isinstance(rung, bool)
        and isinstance(rung, int)
        and rung == 0
        and entry.get("assisted") is False
    )


def first_unhelped_on_concept(steps: Mapping[str, Any], node_id: str, question_hash: str) -> bool:
    """`question_hash` is the session's first check on `node_id` answered
    correctly with no help: no OTHER step on the concept graded before it was."""
    mine = steps.get(question_hash) if isinstance(steps, Mapping) else None
    if not unhelped_correct(mine):
        return False
    at = mine.get("graded_at")
    for qh, entry in (steps or {}).items():
        if qh == question_hash or not isinstance(entry, Mapping) or entry.get("node_id") != node_id:
            continue
        other = entry.get("graded_at")
        if unhelped_correct(entry) and isinstance(other, (int, float)) and isinstance(at, (int, float)) and other <= at:
            return False
    return True


def juncture(
    *,
    phase: str,
    rung: int,
    answer_released: bool,
    first_correct: bool,
) -> tuple[str, str] | None:
    """(juncture, prompt key) for a turn about to be served, or None. `rung` is the
    rung the turn's help is served at (a hint turn's; H6 when a leaking
    deterministic payload is served as H6). Feedback: a released answer, else
    the session's first unhelped correct answer on the concept. On one turn the
    junctures never coincide — a hint turn is one rung, a feedback turn either
    released or correct."""
    if phase == "hint":
        if rung == _H4:
            return "worked_example", "worked_example"
        if rung == _H5:
            return "released_solution", "completion"
        if rung >= _H6:
            return "released_solution", "released_answer"
        return None
    if phase == "feedback":
        if answer_released:
            return "released_solution", "released_answer"
        if first_correct:
            return "first_correct", "first_correct"
    return None


def open_prompt(state: Mapping[str, Any]) -> dict | None:
    raw = _doc(state).get("open")
    return raw if isinstance(raw, dict) and isinstance(raw.get("id"), str) else None


def record_prompt(state: dict, prompt: Mapping[str, Any]) -> None:
    """The turn that serves `prompt` opens it and counts it against the concept
    (inside that turn's compare-and-set write)."""
    if prompt.get("juncture") not in SELF_EXPLAIN_JUNCTURES:
        raise ValueError(f"unknown self-explanation juncture {prompt.get('juncture')!r}")
    if prompt.get("prompt_key") not in PROMPTS:
        raise ValueError(f"unknown self-explanation prompt {prompt.get('prompt_key')!r}")
    doc = dict(_doc(state))
    doc["open"] = dict(prompt)
    doc["prompted"] = [*prompted(state), prompt["node_id"]]
    state[KEY] = doc


def close_open(state: dict) -> dict | None:
    """Clear the open prompt (a reply, a skip, or the next served turn — the
    student moved on); returns it. Nothing else changes."""
    current = open_prompt(state)
    if current is None:
        return None
    doc = dict(_doc(state))
    doc["open"] = None
    state[KEY] = doc
    return current


def ack_due(state: Mapping[str, Any]) -> str | None:
    """A replied prompt's id the next model turn acknowledges (flag-on prompt line)."""
    ack = _doc(state).get("ack")
    return ack if isinstance(ack, str) and ack else None


def set_ack(state: dict, prompt_id: str | None) -> None:
    doc = dict(_doc(state))
    doc["ack"] = prompt_id
    state[KEY] = doc


def mark_closed_by_reply(state: dict, prompt_id: str) -> bool:
    """Record that the reply route closed `prompt_id` — True only the FIRST
    time, inside the one compare-and-set write that decides it, so a reply's
    transcript row and event are written exactly once however many requests
    committed it (second review: a slow winner and its retry both wrote them).
    Prompt ids only (A38), at most one per concept per session."""
    doc = dict(_doc(state))
    done = [p for p in doc.get("replied") or [] if isinstance(p, str)]
    if prompt_id in done:
        return False
    doc["replied"] = [*done, prompt_id]
    state[KEY] = doc
    return True

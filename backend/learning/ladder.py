"""Hint ladder (spec §3.3) and deterministic turns (spec §13 A17). Pure:
stdlib and learning.* only (invariant 2).

Each rung names what the tutor may emit. The text is an instruction to the
tutor prompt (PKG-07), never prose shown to the student.
"""

from __future__ import annotations

from enum import IntEnum
from typing import Iterable, Literal, NamedTuple, Protocol, Sequence

from learning import params


class Rung(IntEnum):
    H0 = 0
    H1 = 1
    H2 = 2
    H3 = 3
    H4 = 4
    H5 = 5
    H6 = 6


RUNG_INTENT: dict[Rung, str] = {
    Rung.H0: "Acknowledge or verify the student's correct step. No new information.",
    Rung.H1: "One pump or focus question (what is the first thing you need?). No content.",
    Rung.H2: "Concept pointer: cite the retrieved course passage or definition. No solution steps.",
    Rung.H3: "One leading question about the very next step only.",
    Rung.H4: "Worked example on an isomorph (different surface, same structure). Never the item itself.",
    Rung.H5: "Completion problem: partial solution with the last steps blanked (backward fade).",
    Rung.H6: "Full solution. Practice items only; never graded coursework; never exam mode.",
}


def intent(rung: Rung) -> str:
    return RUNG_INTENT[Rung(rung)]


def next_rung(rung: Rung) -> Rung:
    return Rung(min(int(rung) + 1, int(Rung.H6)))


# ── deterministic turns (spec §13 A17) ───────────────────────────────────────

PAYLOAD_JOIN = "\n\n"
PayloadSource = Literal["passages", "sibling", "reference"]


class ItemLike(Protocol):
    """The check-item fields the ladder reads (PKG-04 CheckItem; spec A2/A22).
    Structural, so ladder.py never imports learning.checks or storage."""

    question_hash: str
    concept_key: str
    format: str
    difficulty: int
    prompt: str
    reference_answer: str
    stepwise: bool


class DeterministicPayload(NamedTuple):
    rung: Rung
    text: str
    source: PayloadSource
    revealed_hash: str | None = None  # H4: the sibling shown (loop_state["revealed"], A23)


def check_pose(prompt: str) -> str:
    """The check-phase turn: the item prompt verbatim, no model call (A17). The
    prompt was leak-checked at generation (PKG-04 validate_draft)."""
    if not prompt.strip():
        raise ValueError("check_pose: blank item prompt")
    return prompt


def _is_isomorph(sibling: ItemLike, item: ItemLike) -> bool:
    return (
        sibling.concept_key == item.concept_key
        and sibling.format == item.format
        and sibling.difficulty == item.difficulty
        and sibling.question_hash != item.question_hash
        and bool(sibling.stepwise)
        and bool(sibling.reference_answer.strip())
    )


def deterministic_content(
    rung: Rung,
    item: ItemLike,
    siblings: Sequence[ItemLike],
    passages: Sequence[str],
    *,
    exclude_hashes: Iterable[str] = (),
) -> DeterministicPayload | None:
    """Template content for H2/H4/H6 (spec A17). `passages` is resolved,
    visibility-filtered, decrypted text passed in (invariant 2). The caller runs
    leak.detect_leak(reference=item.reference_answer, emitted=payload.text,
    rung=payload.rung, final_answer=item.final_answer, canonical_answer=item.canonical_answer,
    correct_option=item.correct_option) — the ACTIVE item's decrypted
    structured answer (A34; selection serves only items that have one) and, for
    an mc_reason item, its key letter (owner decision A38, 06 gap: detector
    "option"; None on other formats) — before emitting any payload (invariant
    27) and asks for H6 only under gates.h6_allowed. None -> the LLM writes
    the rung.

    H4 never shows a sibling whose hash is in `exclude_hashes`. The caller
    passes at least the concept's `checks.posttest_reserve_hash` (A23: only the
    post-test serves it, and a develop-band item sits at its difficulty), plus
    any other hash it must not reveal."""
    rung = Rung(rung)
    excluded = set(exclude_hashes)
    if rung == Rung.H2:
        kept = [p.strip() for p in passages if p.strip()][: params.LOOP_SOURCE_CHUNKS_MAX]
        return DeterministicPayload(rung, PAYLOAD_JOIN.join(kept), "passages") if kept else None
    if rung == Rung.H4:
        for sibling in siblings:
            if sibling.question_hash not in excluded and _is_isomorph(sibling, item):
                text = PAYLOAD_JOIN.join((sibling.prompt, sibling.reference_answer))
                return DeterministicPayload(rung, text, "sibling", sibling.question_hash)
        return None
    if rung == Rung.H6 and item.reference_answer.strip():
        return DeterministicPayload(rung, item.reference_answer, "reference")
    return None

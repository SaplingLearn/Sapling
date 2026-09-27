"""Hint ladder (spec §3.3) and deterministic turns (spec §13 A17). Pure:
stdlib and learning.* only (invariant 2).

Each rung names what the tutor may emit. The text is an instruction to the
tutor prompt (PKG-07), never prose shown to the student.
"""

from __future__ import annotations

from enum import IntEnum


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

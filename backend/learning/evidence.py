"""Evidence model (spec §5, §13 A1) and §3.1 observation weights.

The only input shape apply_graph_update accepts on the loop path. Weights
are DERIVED from the flags here: the `weight` a caller passes is replaced by
evidence_weight(ev) at validation, and apply_graph_update journals that
number. No LLM, no db: this module is data + arithmetic.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator

from learning.params import (
    CHANNELS,
    GRADER_LOW_CONFIDENCE,
    LADDER_MAX_RUNG,
    PROPAGATION_CHANNEL,
    RUNG_ASSISTED_MIN,
    RUNG_NO_CREDIT_MIN,
    STRONG_CHANNELS,
    WEIGHT_ASSISTED,
    WEIGHT_LOW_CONFIDENCE,
    WEIGHT_SAME_SESSION_RECHECK,
)

#: The item's channel (spec §5). §13 A1: there is no "idk" channel; an
#: explicit "I don't know" is `idk=True` on the item's channel. Equal to
#: params.CHANNELS and fsrs.RATING_CHANNELS (pinned by test).
Channel = Literal["free_response", "mc_reasoned", "mc", "teachback_llm", "chat_turn"]

#: node_mastery_events.event_type for rows written by the evidence path (spec §4).
EVIDENCE_EVENT_TYPE = "evidence"
#: graph_edges.relationship_type the propagation walks (spec §3.1).
PREREQ_RELATIONSHIP_TYPE = "prerequisite"

__all__ = [
    "EVIDENCE_EVENT_TYPE",
    "PREREQ_RELATIONSHIP_TYPE",
    "PROPAGATION_CHANNEL",  # re-exported from params: one name, one value
    "Channel",
    "Evidence",
    "evidence_weight",
    "is_strong_channel",
]


class Evidence(BaseModel):
    node_id: str
    channel: Channel  # the ITEM's channel
    idk: bool = False  # §13 A1: explicit "I don't know" → incorrect, S_IDK, channel's G
    correct: bool
    assisted: bool = False  # any rung H1..H3 used before the answer
    max_rung: int = Field(default=0, ge=0, le=LADDER_MAX_RUNG)
    weight: float = Field(default=1.0, ge=0.0, le=1.0)  # derived: evidence_weight(self)
    session_id: str | None = None
    check_item_id: str | None = None
    question_hash: str | None = None
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)  # grader confidence
    same_session_recheck: bool = False

    @model_validator(mode="after")
    def _consistency(self) -> Evidence:
        if self.idk and self.correct:
            raise ValueError("idk evidence cannot be correct")
        if self.max_rung >= RUNG_ASSISTED_MIN:
            # Rungs unlock in order (PKG-06 gates), so any rung means H1 was used.
            self.assisted = True
        elif self.assisted:
            # And assisted means a rung H1..H3 was used (spec §5), so an
            # assisted answer with no rung is read as H1: fsrs.rating_for keys
            # on max_rung (Hard) and must agree with the assisted BKT weight.
            self.max_rung = RUNG_ASSISTED_MIN
        self.weight = evidence_weight(self)
        return self


def is_strong_channel(channel: str) -> bool:
    """Spec §3.1 channel table, `strong?` column (params.STRONG_CHANNELS).
    An unknown channel, "idk" included, raises ValueError."""
    if channel not in CHANNELS:
        raise ValueError(f"unknown channel {channel!r}")
    return channel in STRONG_CHANNELS


def evidence_weight(ev: Evidence) -> float:
    """Product of the applicable §3.1 weights, from the flags only.

    0.0 means "no upward BKT evidence" (spec §3.3: correct after H4–H6);
    apply_graph_update then leaves p_known untouched and lets FSRS record
    the Again rating. A wrong answer (idk included) at any rung is a standard
    incorrect observation: WEIGHT_ASSISTED applies to correct answers only.
    """
    if ev.correct and ev.max_rung >= RUNG_NO_CREDIT_MIN:
        return 0.0
    w = 1.0
    if ev.correct and ev.assisted:
        w *= WEIGHT_ASSISTED
    if ev.same_session_recheck:
        w *= WEIGHT_SAME_SESSION_RECHECK
    if ev.confidence is not None and ev.confidence < GRADER_LOW_CONFIDENCE:
        w *= WEIGHT_LOW_CONFIDENCE
    return w

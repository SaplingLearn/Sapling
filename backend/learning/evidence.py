"""Evidence model (spec §5, §13 A1) and §3.1 observation weights.

The only input shape apply_graph_update accepts on the loop path. Weights
are DERIVED from the flags here: the `weight` a caller passes is replaced by
evidence_weight(ev) at validation, and apply_graph_update journals that
number. No LLM, no db: this module is data + arithmetic.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    StrictStr,
    field_validator,
    model_validator,
)

from learning.params import (
    CHANNELS,
    GRADER_LOW_CONFIDENCE,
    LADDER_MAX_RUNG,
    PROPAGATION_CHANNEL,
    PROBE_DIFFICULTY_SHIFT,
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

#: Which backend produced an evidence verdict (spec §5, §13 A22). "jev" is PKG-15's.
#: Equal to the node_mastery_events.grader_backend CHECK list (pinned by test).
GraderBackend = Literal["deterministic", "gemini", "gemini_second", "jev"]

#: PKG-10 (spec §3.3): the slip / misconception / novice rule's verdict on one
#: graded attempt — the six §3.3 verdicts plus "none" for a plain correct
#: answer with nothing to diagnose. learning.misconceptions.Verdict is this.
MisconceptionVerdict = Literal[
    "none", "unknown", "slip", "misconception", "gap", "not_known", "novice"
]


class PlanningPersistenceUnavailable(RuntimeError):
    """A durable learning-readiness write/read failed; retry, never guess."""


class PlanningProvenance(BaseModel):
    """Trusted item/route provenance, attached only after the final help read."""

    model_config = ConfigDict(extra="forbid", strict=True)
    check_item_id: StrictStr = Field(min_length=1)
    difficulty: StrictInt
    synthetic_idk: StrictBool
    previously_seen: StrictBool

    @field_validator("difficulty")
    @classmethod
    def _known_difficulty(cls, value):
        if value not in PROBE_DIFFICULTY_SHIFT:
            raise ValueError("unknown diagnostic difficulty")
        return value


class PlanningObservation(PlanningProvenance):
    """IDs/flags only; an append-only record of the final actual Evidence."""

    node_id: StrictStr = Field(min_length=1)
    question_hash: StrictStr = Field(min_length=1)
    channel: Channel
    correct: StrictBool
    idk: StrictBool
    assisted: StrictBool
    max_rung: StrictInt = Field(ge=0, le=LADDER_MAX_RUNG)
    same_session_recheck: StrictBool
    independent: StrictBool

    @model_validator(mode="after")
    def _consistent(self):
        if self.idk and self.correct:
            raise ValueError("idk cannot be correct")
        if self.synthetic_idk and not self.idk:
            raise ValueError("synthetic idk must be an unknown outcome")
        if self.assisted != (self.max_rung >= RUNG_ASSISTED_MIN):
            raise ValueError("help flags disagree")
        expected = not (
            self.max_rung
            or self.assisted
            or self.same_session_recheck
            or self.synthetic_idk
            or self.previously_seen
        )
        if self.independent is not expected:
            raise ValueError("independence disagrees with final provenance")
        return self


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
    "GraderBackend",
    "MisconceptionVerdict",
    "evidence_weight",
    "flush_pending",
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
    grader_backend: GraderBackend | None = None  # A22 provenance; PKG-05 reopen of PKG-03
    # PKG-10 reopen of PKG-03 (spec §5): the rule's verdict (None when it did not
    # run) and the key the student's reason matched (A22). No column journals
    # them (spec §4): the durable record is the `misconceptions` row.
    verdict: MisconceptionVerdict | None = None
    wrong_key: str | None = None
    # NULL/absent for legacy, quiz, review and posttest evidence. Never infer it.
    planning_provenance: PlanningProvenance | None = None
    # A route-owned grading claim, never supplied by a model or a client.
    # One flush batch uses one identity for transactional replay/reconciliation.
    operation_id: str | None = None
    # Trusted route time for replayable grades; absent keeps commit-order semantics.
    observed_at: datetime | None = None

    @field_validator("observed_at")
    @classmethod
    def _observed_time(cls, value):
        if value is not None:
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError("Evidence observation time must include a timezone")
            return value.astimezone(timezone.utc)
        return value

    @field_validator("operation_id")
    @classmethod
    def _operation_identity(cls, value):
        if value is None:
            return value
        try:
            canonical = str(UUID(value))
        except (ValueError, TypeError, AttributeError):
            raise ValueError("Invalid evidence operation identity") from None
        if canonical != value:
            raise ValueError("Evidence operation identity must be a canonical UUID")
        return value

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
        if self.planning_provenance is not None and (
            self.check_item_id != self.planning_provenance.check_item_id or not self.question_hash
        ):
            raise ValueError("planning provenance does not bind this check item")
        return self


def planning_observation(ev: Evidence) -> dict | None:
    """Derive from final Evidence, after refloor and writer-forced rechecks."""
    provenance = ev.planning_provenance
    if provenance is None:
        return None
    return PlanningObservation(
        **provenance.model_dump(),
        node_id=ev.node_id,
        question_hash=ev.question_hash,
        channel=ev.channel,
        correct=ev.correct,
        idk=ev.idk,
        assisted=ev.assisted,
        max_rung=ev.max_rung,
        same_session_recheck=ev.same_session_recheck,
        independent=not (
            ev.max_rung
            or ev.assisted
            or ev.same_session_recheck
            or provenance.synthetic_idk
            or provenance.previously_seen
        ),
    ).model_dump()


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


def flush_pending(deps, course_id: str | None) -> list:
    """Persist `deps.pending_evidence` through the single graph writer, once.

    Called by the ROUTE after grade_answer (PKG-07's /check/answer, A16), never
    by grade_answer itself. Empty list → `[]` and no call. Otherwise ONE
    apply_graph_update call with a snapshot of the list; errors propagate, and
    the list is cleared only after a successful write so the route can decide
    whether to retry or report. Returns apply_graph_update's changes.
    """
    if not deps.pending_evidence:
        return []
    # Local import: services.graph_service imports this module (PKG-03), so a
    # module-level import here would be circular.
    from services.graph_service import apply_graph_update

    changes = apply_graph_update(deps.user_id, {"evidence": list(deps.pending_evidence)}, course_id)
    deps.pending_evidence.clear()
    return changes

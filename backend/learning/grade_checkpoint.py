"""Authenticated, owner-bound grade recovery; never a second grader call.

Only the encrypted envelope is stored in loop_state. It includes the exact
evidence batch and code-side continuation, not a rubric or reference answer.
The route validates ownership first and retains this envelope until the
operation and session continuation have both been acknowledged.
"""

from __future__ import annotations

import json
import math
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from learning.evidence import Channel, Evidence, GraderBackend, PlanningPersistenceUnavailable, planning_observation
from learning.misconceptions import Attempt, is_key
from learning.params import LADDER_MAX_RUNG
from services.encryption import decrypt, encrypt

KEY = "grade_checkpoint"


class _Metadata(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, hide_input_in_errors=True)


class _Answer(_Metadata):
    question_hash: str = Field(min_length=1)
    answer_text: str
    selected_option: str | None
    reason: str | None
    idk: bool


class _Observation(_Metadata):
    node_id: str = Field(min_length=1)
    question_hash: str = Field(min_length=1)
    difficulty: int = Field(ge=1, le=3)
    channel: Channel
    correct: bool
    idk: bool
    max_rung: int = Field(ge=0, le=LADDER_MAX_RUNG)
    same_session_recheck: bool
    synthetic_idk: bool
    independent: bool


class _GoalObservation(_Observation):
    previously_seen: bool


class _Graded(_Metadata):
    graded_at: float = Field(ge=0, allow_inf_nan=False)
    last_correct: bool
    last_verdict: Literal["correct", "not_yet", "idk"]
    max_rung: int = Field(ge=0, le=LADDER_MAX_RUNG)
    assisted: bool
    node_id: str = Field(min_length=1)
    channel: Channel
    confidence: float | None = Field(ge=0, le=1, allow_inf_nan=False)
    grader_backend: GraderBackend | None
    fsrs_rating: int = Field(ge=1, le=4)
    p_before: float = Field(ge=0, le=1, allow_inf_nan=False)
    feedback_given: bool

    @field_validator("feedback_given")
    @classmethod
    def _feedback_pending(cls, value):
        if value:
            raise ValueError("Grade feedback is already materialized")
        return value
    goal_observation: _GoalObservation | None = None


class _Marker(_Metadata):
    node_id: str = Field(min_length=1)
    wrong_key: str
    check_item_id: str = Field(min_length=1)

    @field_validator("wrong_key")
    @classmethod
    def _wrong_key(cls, value):
        if not is_key(value):
            raise ValueError("Invalid misconception key")
        return value


class _Diagnosis(_Metadata):
    attempt: dict
    confront: _Marker | None
    cleared: _Marker | None
    record: _Marker | None


class _CheckContinuation(_Metadata):
    graded: _Graded
    correct: bool
    genuine: bool
    diagnosis: _Diagnosis | None
    rendered: str
    answer: _Answer
    verdict: Literal["correct", "not_yet", "idk"]
    refused: bool


class _ProbeContinuation(_Metadata):
    observation: _Observation
    correct: bool
    check_item_id: str = Field(min_length=1)


def _primary(evidences: list[Evidence], node_id: str) -> Evidence:
    matches = [ev for ev in evidences if ev.node_id == node_id]
    if len(matches) != 1:
        raise ValueError("Grade continuation has no unique primary evidence")
    return matches[0]


def _bind_observation(observation: _Observation, ev: Evidence) -> None:
    if any(getattr(observation, key) != getattr(ev, key) for key in (
        "node_id", "question_hash", "channel", "correct", "idk", "max_rung", "same_session_recheck",
    )):
        raise ValueError("Grade observation disagrees with evidence")
    canonical = planning_observation(ev)
    if canonical is None and (observation.independent or observation.synthetic_idk):
        raise ValueError("Grade observation provenance is unavailable")
    if canonical is not None:
        for key in ("difficulty", "synthetic_idk", "independent"):
            if getattr(observation, key) != canonical[key]:
                raise ValueError("Grade observation provenance disagrees")
        if isinstance(observation, _GoalObservation) and observation.previously_seen != canonical["previously_seen"]:
            raise ValueError("Goal observation provenance disagrees")


def _bind_diagnosis(diagnosis: _Diagnosis | None, ev: Evidence) -> None:
    if diagnosis is None:
        return
    attempt = Attempt.model_validate(diagnosis.attempt, strict=True)
    if any(getattr(attempt, key) != getattr(ev, key) for key in ("node_id", "question_hash", "correct", "idk")):
        raise ValueError("Grade diagnosis disagrees with evidence")
    if attempt.wrong_key is not None and not is_key(attempt.wrong_key):
        raise ValueError("Invalid grade diagnosis key")
    diagnosis.attempt = attempt.model_dump(mode="json")
    for marker in (diagnosis.confront, diagnosis.cleared, diagnosis.record):
        if marker is not None and marker.node_id != ev.node_id:
            raise ValueError("Grade misconception marker disagrees with evidence")
    for marker in (diagnosis.confront, diagnosis.record):
        if marker is not None and marker.check_item_id != ev.check_item_id:
            raise ValueError("Grade misconception item disagrees with evidence")


def _continuation(kind: str, raw: dict, evidences: list[Evidence]) -> dict:
    if kind == "probe":
        value = _ProbeContinuation.model_validate(raw)
        ev = _primary(evidences, value.observation.node_id)
        _bind_observation(value.observation, ev)
        if value.correct != ev.correct or value.check_item_id != ev.check_item_id:
            raise ValueError("Probe continuation outcome disagrees with evidence")
        return value.model_dump(mode="json")
    value = _CheckContinuation.model_validate(raw)
    ev = _primary(evidences, value.graded.node_id)
    expected_verdict = "idk" if ev.idk else "correct" if ev.correct else "not_yet"
    if (value.correct != ev.correct or value.answer.question_hash != ev.question_hash
        or value.answer.idk != ev.idk or value.verdict != expected_verdict
        or value.graded.last_correct != ev.correct or value.graded.last_verdict != expected_verdict
        or value.graded.channel != ev.channel or value.graded.max_rung != ev.max_rung
        or value.graded.assisted != ev.assisted or value.graded.confidence != ev.confidence
        or value.graded.grader_backend != ev.grader_backend
        or not math.isclose(value.graded.graded_at, ev.observed_at.timestamp(), rel_tol=0, abs_tol=.000001)
        or (value.genuine and ev.idk) or (value.refused and not ev.idk)):
        raise ValueError("Check continuation outcome disagrees with evidence")
    if ev.planning_provenance is not None and value.refused != ev.planning_provenance.synthetic_idk:
        raise ValueError("Check refusal provenance disagrees with evidence")
    if value.graded.goal_observation is not None:
        _bind_observation(value.graded.goal_observation, ev)
    _bind_diagnosis(value.diagnosis, ev)
    result = value.model_dump(mode="json")
    if value.graded.goal_observation is None:
        result["graded"].pop("goal_observation", None)
    return result


class GradeCheckpoint(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, hide_input_in_errors=True)

    version: Literal[1] = 1
    kind: Literal["check", "probe"]
    operation_id: str
    user_id: str = Field(min_length=1)
    session_id: str = Field(min_length=1)
    course_id: str | None = Field(min_length=1)
    question_hash: str = Field(min_length=1)
    goal_version: int = Field(ge=0)
    evidence: list[dict] = Field(min_length=1)
    continuation: dict

    @field_validator("version", mode="before")
    @classmethod
    def _version(cls, value):
        if type(value) is not int or value != 1:
            raise ValueError("Unsupported grade checkpoint version")
        return value

    @field_validator("operation_id")
    @classmethod
    def _identity(cls, value):
        if str(UUID(value)) != value:
            raise ValueError("Noncanonical grade operation")
        return value

    @model_validator(mode="after")
    def _binding(self):
        canonical = []
        evidences = []
        observed = set()
        for raw in self.evidence:
            ev = Evidence.model_validate(raw)
            if (ev.operation_id != self.operation_id or ev.session_id != self.session_id
                    or ev.question_hash != self.question_hash or ev.observed_at is None):
                raise ValueError("Grade evidence binding disagrees")
            canonical.append(ev.model_dump(mode="json"))
            evidences.append(ev)
            observed.add(ev.observed_at)
        if len(observed) != 1:
            raise ValueError("Grade evidence observation times disagree")
        # Retain only the Evidence contract, not ignored keys from a raw dict.
        self.evidence = canonical
        self.continuation = _continuation(self.kind, self.continuation, evidences)
        return self


def seal(checkpoint: GradeCheckpoint) -> str:
    try:
        # The model is mutable; validate again before committing its ciphertext.
        canonical = GradeCheckpoint.model_validate(checkpoint.model_dump(mode="json"))
        return encrypt(json.dumps(canonical.model_dump(mode="json"), sort_keys=True,
                                  separators=(",", ":"), allow_nan=False))
    except Exception:
        raise PlanningPersistenceUnavailable("Saved grade checkpoint unavailable") from None


def open_checkpoint(value, *, kind: str, operation_id: str, user_id: str,
                    session_id: str, course_id: str | None, question_hash: str) -> GradeCheckpoint:
    """No plaintext fallback, exception payload, or partial checkpoint recovery."""
    try:
        if not isinstance(value, str):
            raise ValueError("Missing encrypted grade checkpoint")
        checkpoint = GradeCheckpoint.model_validate_json(decrypt(value))
        expected = (kind, operation_id, user_id, session_id, course_id, question_hash)
        actual = (checkpoint.kind, checkpoint.operation_id, checkpoint.user_id,
                  checkpoint.session_id, checkpoint.course_id, checkpoint.question_hash)
        if actual != expected:
            raise ValueError("Grade checkpoint binding disagrees")
        return checkpoint
    except Exception:
        # Pydantic/decryption exceptions can contain learner prose. Do not chain them.
        raise PlanningPersistenceUnavailable("Saved grade recovery unavailable") from None

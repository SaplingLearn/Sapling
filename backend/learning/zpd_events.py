"""Typed emit helpers for the zpd.* events (spec §6). Payloads carry ids,
counts, enums and bools only — never student or tutor text.

Keyword-only thin wrappers over `services.events_service.log_event`. Like
log_event they never raise into a request: a payload that cannot be built (a
caller bug) is dropped with a log line. Emitted by nobody in PKG-06; PKG-07,
PKG-08 and PKG-10 call them.
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Literal

from learning.ladder import Rung
from learning.leak import Detector
from learning.policy import Band, BandAction, CeilingReason, Tier
from services.events_service import log_event

logger = logging.getLogger("sapling.learning.zpd_events")

Phase = Literal["probe", "plan", "teach", "check", "feedback", "close", "posttest"]  # A8: posttest
Rating = Literal["too_easy", "appropriate", "too_hard"]
BandTrigger = Literal["high", "stable_high", "low", "wheelspin"]
GraderBackend = Literal["deterministic", "gemini", "gemini_second", "jev"]  # spec §5 (A22/A24)


def _emit(
    event_type: str,
    category: str,
    user_id: str,
    request_id: str | None,
    build: Callable[[], dict[str, Any]],
) -> None:
    try:
        payload = build()
    except Exception:
        logger.warning("%s: payload could not be built; event dropped", event_type, exc_info=True)
        return
    log_event(
        event_type, category=category, user_id=user_id, request_id=request_id, payload=payload
    )


def emit_zpd_step(
    *,
    user_id: str,
    request_id: str | None,
    concept_id: str,
    question_hash: str,
    phase: Phase,
    channel: str,
    band: Band,
    ceiling: Rung,
    ceiling_reason: CeilingReason,
    first_attempt_correct: bool,
    n_attempts: int,
    max_rung_used: Rung,
    rungs: list[dict],
    time_to_first_attempt_ms: int | None,
    time_to_correct_ms: int | None,
    independent_time_ms: int | None,
    assisted: bool,
    confidence: float | None,
    fsrs_rating: int,
    p_known_before: float,
    p_known_after: float,
    r_before: float | None,
    item_difficulty: int,
    tier: Tier | None = None,
    grader_backend: GraderBackend | None = None,
) -> None:
    def build() -> dict[str, Any]:
        payload: dict[str, Any] = {
            "concept_id": concept_id,
            "question_hash": question_hash,
            "phase": phase,
            "channel": channel,
            "band": band,
            "ceiling": int(ceiling),
            "ceiling_reason": CeilingReason(ceiling_reason).value,
            "first_attempt_correct": first_attempt_correct,
            "n_attempts": n_attempts,
            "max_rung_used": int(max_rung_used),
            "rungs": [{"rung": int(r["rung"]), "dwell_ms": int(r["dwell_ms"])} for r in rungs],
            "time_to_first_attempt_ms": time_to_first_attempt_ms,
            "time_to_correct_ms": time_to_correct_ms,
            "independent_time_ms": independent_time_ms,
            "assisted": assisted,
            "confidence": confidence,
            "fsrs_rating": int(fsrs_rating),
            "p_known_before": p_known_before,
            "p_known_after": p_known_after,
            "r_before": r_before,
            "item_difficulty": item_difficulty,
        }
        # A15/A24: present only when known — omitted, never zeroed or blanked.
        if tier is not None:
            payload["tier"] = tier
        if grader_backend is not None:
            payload["grader_backend"] = grader_backend
        return payload

    _emit("zpd.step", "usage", user_id, request_id, build)


def emit_zpd_offer(*, user_id: str, request_id: str | None, accepted: bool, band: Band) -> None:
    _emit("zpd.offer", "usage", user_id, request_id, lambda: {"accepted": accepted, "band": band})


def emit_zpd_band_adjust(
    *,
    user_id: str,
    request_id: str | None,
    direction: BandAction,
    trigger: BandTrigger,
    window_stats: dict,
) -> None:
    _emit(
        "zpd.band_adjust",
        "usage",
        user_id,
        request_id,
        lambda: {
            "direction": BandAction(direction).value,
            "trigger": trigger,
            "window_stats": dict(window_stats),
        },
    )


def emit_zpd_wheelspin(
    *,
    user_id: str,
    request_id: str | None,
    concept_id: str,
    opps: int,
    unassisted_next: float | None,
    htc_k: float | None,
    prerequisite_ids: list[str],
) -> None:
    _emit(
        "zpd.wheelspin",
        "error",
        user_id,
        request_id,
        lambda: {
            "concept_id": concept_id,
            "opps": opps,
            "unassisted_next": unassisted_next,
            "htc_k": htc_k,
            "prerequisite_ids": list(prerequisite_ids),
        },
    )


def emit_zpd_leak(
    *,
    user_id: str,
    request_id: str | None,
    rung_emitted: Rung,
    ceiling: Rung,
    detector: Detector,
) -> None:
    _emit(
        "zpd.leak",
        "error",
        user_id,
        request_id,
        lambda: {
            "rung_emitted": int(rung_emitted),
            "ceiling": int(ceiling),
            "detector": detector,
            "request_id": request_id,
        },
    )


def emit_zpd_rating(
    *, user_id: str, request_id: str | None, rating: Rating, checks_since_last: int
) -> None:
    _emit(
        "zpd.rating",
        "usage",
        user_id,
        request_id,
        lambda: {"rating": rating, "checks_since_last": checks_since_last},
    )

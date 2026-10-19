"""Durable planning needs from owned evidence; no learner prose or graph writes."""

from collections.abc import Mapping

from pydantic import ValidationError

from db.connection import page_all, table
from learning.evidence import PlanningObservation, PlanningPersistenceUnavailable


class _EvidenceRead:
    def select_with_count(self, *args, **kwargs):
        return table("node_mastery_events").select_with_count(*args, **kwargs)


def _bound_observation(row: dict) -> dict | None:
    try:
        observation = PlanningObservation.model_validate(row.get("planning_observation"))
    except (ValidationError, TypeError):
        return None
    values = observation.model_dump()
    # The JSON envelope cannot relabel the actual immutable event it accompanies.
    for key in (
        "node_id",
        "question_hash",
        "check_item_id",
        "channel",
        "correct",
        "assisted",
        "max_rung",
    ):
        if type(row.get(key)) is not type(values[key]) or row[key] != values[key]:
            return None
    if observation.idk != (row.get("reason") == f"evidence:{observation.channel}:idk"):
        return None
    return values


def read_planning_history(user_id: str, course_id: str, node_ids) -> list[dict]:
    """Global first exposure, then current owned-course planning projection.

    Unknown/invalid legacy rows consume their hash but certify nothing. A
    journal event always wins over its current-session snapshot, including a
    NULL envelope. Current-only legacy snapshots cannot be promoted: they do
    not prove durable provenance or chronology. Diagnostic/UI state stays intact.
    Read failures propagate: an explicit goal must retry rather than fall back
    to an old high posterior. All pages use the journal's stable total order.
    """
    try:
        rows = list(
            page_all(
                _EvidenceRead(),
                "id,node_id,question_hash,check_item_id,channel,correct,assisted,max_rung,reason,"
                "planning_observation,created_at,evidence_seq,graph_nodes!inner(user_id,course_id)",
                filters={
                    "graph_nodes.user_id": f"eq.{user_id}",
                    "event_type": "eq.evidence",
                    "question_hash": "not.is.null",
                },
                order="created_at.asc,evidence_seq.asc.nullslast,id.asc",
            )
        )
    except Exception as exc:
        raise PlanningPersistenceUnavailable("learning evidence read unavailable") from exc

    return project_planning_history(rows, user_id, course_id, node_ids)


def project_planning_history(rows, user_id: str, course_id: str, node_ids) -> list[dict]:
    """Project an already chronologically ordered, owner-scoped journal."""
    wanted = set(node_ids)
    history = []
    for row in rows:
        owner = row.get("graph_nodes")
        if not isinstance(owner, Mapping) or owner.get("user_id") != user_id:
            continue
        question_hash = row.get("question_hash")
        if not isinstance(question_hash, str) or not question_hash.strip():
            continue
        observation = None
        if owner.get("course_id") == course_id and row.get("node_id") in wanted:
            observation = _bound_observation(row)
        history.append(observation or {"question_hash": question_hash})

    return history

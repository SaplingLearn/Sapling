"""What the student knows: mastery per concept, and the mistakes their quiz
history recorded.

The knowledge graph is keyed on the abstract course id, not the offering.
Both reads go through ``tool_signals`` so a student who has data but reads
back none is counted instead of looking like a new student.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from config import get_mastery_tier
from db.connection import pg_quote_value, table
from models.study_guide import Tier
from services.encryption import decrypt_json_column
from services.tool_signals import Expect, report_empty_result_async

logger = logging.getLogger(__name__)

FEATURE = "study_guide"
MAX_MISTAKES_PER_CONCEPT = 3
MAX_MISTAKES = 12
#: Digest fields that hold mistakes, most specific first.
_MISTAKE_FIELDS = ("common_mistakes", "weak_areas")


@dataclass(frozen=True)
class QuizMistake:
    """One recorded mistake. ``id`` (``m1``, ``m2``, ...) is what the writer
    cites; ``concept`` is the name in the student's tree."""

    id: str
    concept: str
    text: str


def concept_key(name: str) -> str:
    """A concept name for matching: case and spacing do not count."""
    return " ".join(name.split()).casefold()


async def _anodes(user_id: str, course_id: str) -> list[dict]:
    """The student's concepts in the course, without root nodes."""
    rows = await table("graph_nodes").aselect(
        "id,concept_name,mastery_score",
        filters={
            "user_id": f"eq.{user_id}",
            "course_id": f"eq.{course_id}",
            "mastery_tier": "neq.subject_root",
        },
        order="concept_name.asc,id.asc",
    ) or []
    return [row for row in rows if (row.get("concept_name") or "").strip()]


async def amastery(user_id: str, course_id: str) -> dict[str, float]:
    """Mastery score (0 to 1) per concept name for the course."""
    nodes = await _anodes(user_id, course_id)
    scores = {n["concept_name"]: float(n.get("mastery_score") or 0.0) for n in nodes}
    await report_empty_result_async(
        "study_guide_mastery",
        user_id=user_id,
        count=len(scores),
        expect=Expect.HAS_GRAPH,
        feature=FEATURE,
        scope={"course_id": f"eq.{course_id}"},
    )
    return scores


def tiers(scores: dict[str, float]) -> dict[str, Tier]:
    """Mastery tier per concept name."""
    return {name: get_mastery_tier(score) for name, score in scores.items()}


def _digest_mistakes(context_json) -> list[str]:
    """The mistakes one quiz digest holds, without repeats. Raises when the
    column does not decrypt."""
    digest = decrypt_json_column(context_json)
    if not isinstance(digest, dict):
        return []
    texts: dict[str, str] = {}
    for field in _MISTAKE_FIELDS:
        entries = digest.get(field)
        for entry in entries if isinstance(entries, list) else []:
            text = " ".join(str(entry or "").split())
            if text:
                texts.setdefault(text.casefold(), text)
    return list(texts.values())


def _mistakes_by_node(rows: list[dict]) -> dict[str, list[str]]:
    """Node id to its mistakes, for the digests that decrypt and hold any."""
    found: dict[str, list[str]] = {}
    for row in rows:
        try:
            texts = _digest_mistakes(row.get("context_json"))
        except Exception as exc:  # a wrong key, a damaged value, not JSON
            logger.warning(
                "study guide: a quiz digest did not decrypt (%s); left out", type(exc).__name__,
            )
            continue
        if texts:
            found[row["concept_node_id"]] = texts
    return found


async def amistakes(user_id: str, course_id: str, concepts: list[str]) -> list[QuizMistake]:
    """The student's recorded quiz mistakes for those concepts, in the order
    the concepts are given: at most three per concept and twelve in all."""
    wanted = {concept_key(name): position for position, name in enumerate(concepts)}
    nodes = [n for n in await _anodes(user_id, course_id) if concept_key(n["concept_name"]) in wanted]
    if not nodes:
        return []
    nodes.sort(key=lambda n: wanted[concept_key(n["concept_name"])])
    node_ids = f"in.({','.join(pg_quote_value(n['id']) for n in nodes)})"
    rows = await table("quiz_context").aselect(
        "concept_node_id,context_json",
        filters={"user_id": f"eq.{user_id}", "concept_node_id": node_ids},
    ) or []
    by_node = _mistakes_by_node(rows)
    await report_empty_result_async(
        "study_guide_mistakes",
        user_id=user_id,
        count=len(by_node),
        expect=Expect.HAS_ATTEMPTS,
        feature=FEATURE,
        scope={"concept_node_id": node_ids},
    )
    picked = [
        (node["concept_name"], text)
        for node in nodes
        for text in by_node.get(node["id"], [])[:MAX_MISTAKES_PER_CONCEPT]
    ][:MAX_MISTAKES]
    return [
        QuizMistake(id=f"m{number}", concept=concept, text=text)
        for number, (concept, text) in enumerate(picked, start=1)
    ]

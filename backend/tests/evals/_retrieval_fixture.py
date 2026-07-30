"""FixtureRetrieval — an offline TutorRetrieval over tutor_course.json.

Implements the ADR 0023 retrieval seam for the chat_tutor evals: every read
tool the tutor can call is served from the committed synthetic course
fixture, so record/live eval runs are Supabase-free and byte-deterministic
given the same model output.

Semantics deliberately mirror the Supabase-backed pure functions:
  - course_materials  — keyword-overlap ranking via the shared _score
    (`chat_context._score_material` + `_tokenize`), course/user scoping,
    top-`limit`.
  - graph_neighborhood — seed match on `_normalize_concept`, depth-1 edge
    expansion, `limit` + `truncated`, names only (fixture has no row ids
    at all, which is the point).
  - concept_mastery    — mastery ASC (weakest first), like the
    `graph_nodes` read's `order=mastery_score.asc`.
  - progress           — same 0.7/0.4 thresholds as `read_user_progress`.
  - session_history    — newest-first, last `n`.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agents.tools.chat_context import (
    CourseMaterial,
    CourseProgress,
    SessionMessage,
    _score_material,
    _tokenize,
)
from agents.tools.graph_read import (
    ConceptEdge,
    ConceptMastery,
    ConceptNode,
    GraphNeighborhood,
)
from services.graph_service import _normalize_concept

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "tutor_course.json"


def load_fixture() -> dict[str, Any]:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


class FixtureRetrieval:
    """TutorRetrieval implementation backed by tutor_course.json."""

    def __init__(self, fixture: dict[str, Any] | None = None):
        self.fixture = fixture or load_fixture()

    # -- scoping helpers ---------------------------------------------------

    def _owns(self, user_id: str) -> bool:
        return user_id == self.fixture.get("user_id")

    def _course_matches(self, course_id: str | None) -> bool:
        return bool(course_id) and course_id == self.fixture["course"]["course_id"]

    # -- TutorRetrieval ----------------------------------------------------

    async def course_materials(
        self, course_id: str | None, query: str, limit: int, *, user_id: str
    ) -> list[CourseMaterial]:
        if not self._course_matches(course_id) or not self._owns(user_id):
            return []
        docs = [
            {
                "id": d["document_id"],
                "file_name": d["file_name"],
                "summary": d.get("summary"),
                "concept_notes": d.get("concept_notes") or [],
            }
            for d in self.fixture.get("documents", [])
        ]
        query_tokens = _tokenize(query)
        docs.sort(key=lambda d: _score_material(query_tokens, d), reverse=True)
        return [
            CourseMaterial(
                document_id=d["id"],
                file_name=d["file_name"],
                summary=d["summary"],
                concept_notes=d["concept_notes"],
            )
            for d in docs[: max(0, int(limit))]
        ]

    async def graph_neighborhood(
        self,
        user_id: str,
        course_id: str | None,
        concepts: list[str],
        *,
        limit: int = 20,
    ) -> GraphNeighborhood:
        empty = GraphNeighborhood(concepts=[], edges=[], truncated=False)
        if not self._owns(user_id):
            return empty
        if course_id is not None and not self._course_matches(course_id):
            return empty

        by_norm = {
            _normalize_concept(c["concept_name"]): c
            for c in self.fixture.get("concepts", [])
        }
        seeds = [
            by_norm[_normalize_concept(name)]
            for name in concepts
            if _normalize_concept(name) in by_norm
        ]
        selected: dict[str, dict] = {
            _normalize_concept(c["concept_name"]): c for c in seeds
        }

        # Depth-1 expansion along fixture edges.
        touched_edges: list[dict] = []
        for e in self.fixture.get("edges", []):
            src, tgt = _normalize_concept(e["source"]), _normalize_concept(e["target"])
            if src in selected or tgt in selected:
                touched_edges.append(e)
                for norm in (src, tgt):
                    if norm not in selected and norm in by_norm:
                        selected[norm] = by_norm[norm]

        truncated = len(selected) > max(0, int(limit))
        kept = list(selected.values())[: max(0, int(limit))]
        kept_norms = {_normalize_concept(c["concept_name"]) for c in kept}
        edges = [
            ConceptEdge(
                source=e["source"],
                target=e["target"],
                relationship_type=e.get("relationship_type", "related"),
                strength=e.get("strength"),
            )
            for e in touched_edges
            if _normalize_concept(e["source"]) in kept_norms
            and _normalize_concept(e["target"]) in kept_norms
        ]
        return GraphNeighborhood(
            concepts=[
                ConceptNode(
                    concept_name=c["concept_name"],
                    mastery=c["mastery"],
                    mastery_tier=c["mastery_tier"],
                    last_reviewed_at=c.get("last_reviewed_at"),
                )
                for c in kept
            ],
            edges=edges,
            truncated=truncated,
        )

    async def concept_mastery(
        self, user_id: str, course_id: str | None
    ) -> list[ConceptMastery]:
        if not self._owns(user_id):
            return []
        if course_id is not None and not self._course_matches(course_id):
            return []
        rows = sorted(self.fixture.get("concepts", []), key=lambda c: c["mastery"])
        return [
            ConceptMastery(
                concept_name=c["concept_name"],
                mastery=c["mastery"],
                last_reviewed_at=c.get("last_reviewed_at"),
            )
            for c in rows
        ]

    async def progress(self, user_id: str, course_id: str | None) -> CourseProgress:
        empty = CourseProgress(
            total_concepts=0,
            mastered_count=0,
            weak_count=0,
            in_progress_count=0,
            avg_mastery=0.0,
        )
        if not self._owns(user_id):
            return empty
        if course_id is not None and not self._course_matches(course_id):
            return empty
        scores = [c["mastery"] for c in self.fixture.get("concepts", [])]
        if not scores:
            return empty
        mastered = sum(1 for m in scores if m >= 0.7)
        weak = sum(1 for m in scores if m < 0.4)
        return CourseProgress(
            total_concepts=len(scores),
            mastered_count=mastered,
            weak_count=weak,
            in_progress_count=len(scores) - mastered - weak,
            avg_mastery=round(sum(scores) / len(scores), 4),
        )

    async def session_history(
        self, session_id: str, last_n: int
    ) -> list[SessionMessage]:
        if not session_id:
            return []
        n = max(0, int(last_n))
        msgs = self.fixture.get("messages", [])[-n:] if n else []
        out = []
        for m in reversed(msgs):  # newest first, like the Supabase read
            role = {"user": "user", "assistant": "model", "model": "model"}.get(
                (m.get("role") or "").lower()
            )
            if role is None or not m.get("content"):
                continue
            out.append(
                SessionMessage(
                    role=role,
                    content=m["content"],
                    created_at=m.get("created_at") or "",
                )
            )
        return out

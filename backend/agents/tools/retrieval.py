"""Retrieval seam for the chat tutor (ADR 0023; issue #149).

The tutor's read tools each bottom out in a pure async function that hits
Supabase (`chat_context.py`, `graph_read.py`).
That coupling kept `chat_tutor` out of the offline eval harness (ADR 0021
decision 4): record/live eval runs had no Supabase, so every tool call
degraded to empty and the cassettes captured a tutor with amnesia.

`TutorRetrieval` is the seam: a Protocol with one method per read surface.
`SupabaseRetrieval` is the production implementation — it delegates to
today's pure functions verbatim, so behavior is byte-identical. Each tutor
tool wrapper resolves `ctx.deps.retrieval or _SUPABASE` before fetching;
production passes `retrieval=None` (the SaplingDeps default) and gets the
Supabase impl, while evals inject `FixtureRetrieval`
(tests/evals/_retrieval_fixture.py) and never touch a database.

Keep the Protocol method signatures aligned with the pure functions they
shadow — the wrappers pass LLM-chosen args through unchanged and inject
the security-sensitive ids (user_id / course_id / session_id) from deps.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:  # circular-import guard: these modules import agents.deps
    from agents.tools.chat_context import (
        CourseMaterial,
        CourseProgress,
        SessionMessage,
    )
    from agents.tools.graph_read import ConceptMastery, GraphNeighborhood


@runtime_checkable
class TutorRetrieval(Protocol):
    """Everything the chat tutor's read tools need to fetch.

    One method per read surface; each mirrors the corresponding pure
    function's signature (minus nothing — ids stay explicit so a fixture
    impl can honor scoping the same way Supabase does).
    """

    async def course_materials(
        self, course_id: str | None, query: str, limit: int, *, user_id: str
    ) -> list["CourseMaterial"]: ...

    async def graph_neighborhood(
        self,
        user_id: str,
        course_id: str | None,
        concepts: list[str],
        *,
        limit: int = 20,
    ) -> "GraphNeighborhood": ...

    async def concept_mastery(
        self, user_id: str, course_id: str | None
    ) -> list["ConceptMastery"]: ...

    async def progress(
        self, user_id: str, course_id: str | None
    ) -> "CourseProgress": ...

    async def session_history(
        self, session_id: str, last_n: int
    ) -> list["SessionMessage"]: ...


class SupabaseRetrieval:
    """Production retrieval: delegates to the existing pure functions.

    Deliberately thin — no caching, no reshaping. The pure functions
    already own scoping, decryption-at-the-boundary, and degrade-to-empty
    error handling; this class only routes.
    """

    async def course_materials(
        self, course_id: str | None, query: str, limit: int, *, user_id: str
    ) -> list["CourseMaterial"]:
        from agents.tools.chat_context import search_course_materials

        return await search_course_materials(course_id, query, limit, user_id=user_id)

    async def graph_neighborhood(
        self,
        user_id: str,
        course_id: str | None,
        concepts: list[str],
        *,
        limit: int = 20,
    ) -> "GraphNeighborhood":
        from agents.tools.graph_read import read_graph_neighborhood

        return await read_graph_neighborhood(user_id, course_id, concepts, limit=limit)

    async def concept_mastery(
        self, user_id: str, course_id: str | None
    ) -> list["ConceptMastery"]:
        from agents.tools.graph_read import read_concepts_for_user

        return await read_concepts_for_user(user_id, course_id)

    async def progress(
        self, user_id: str, course_id: str | None
    ) -> "CourseProgress":
        from agents.tools.chat_context import read_user_progress

        return await read_user_progress(user_id, course_id)

    async def session_history(
        self, session_id: str, last_n: int
    ) -> list["SessionMessage"]:
        from agents.tools.chat_context import read_session_history

        return await read_session_history(session_id, last_n)


# Module-level singleton: the wrappers' `ctx.deps.retrieval or _SUPABASE`
# fallback. Stateless, so sharing one instance across requests is safe.
_SUPABASE = SupabaseRetrieval()


def resolve_retrieval(deps) -> TutorRetrieval:
    """Return the injected retrieval impl, or the Supabase default.

    `deps.retrieval` is typed `Any` on SaplingDeps (avoids the circular
    import deps → retrieval → chat_context → deps); `getattr` keeps this
    robust to hand-rolled test doubles that omit the field.
    """
    return getattr(deps, "retrieval", None) or _SUPABASE

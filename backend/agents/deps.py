"""Shared dependencies passed to every Sapling Pydantic AI agent.

Agents receive a SaplingDeps instance via the `deps` parameter and access
it inside tools via `RunContext[SaplingDeps]`. This is the seam between
agent code and the rest of the backend (DB, auth context, logging).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class SaplingDeps:
    """Dependencies threaded through every agent run.

    Attributes:
        user_id: The authenticated user's Supabase user ID.
        course_id: The course context for the current request, if any.
        supabase: The Supabase client (from db.connection). Typed as Any
            to avoid coupling agent code to a specific Supabase SDK
            version.
        request_id: A correlation ID for tracing across a single
            user-facing request. Used by Logfire spans.
        session_id: The active chat session, when applicable. Used by tools
            that need to scope reads to *this* conversation (e.g.
            read_session_history_tool). Optional — agent runs that don't
            happen inside a session (eval mode, batch tasks) leave it None.
        graph_updates: Accumulates graph update payloads emitted by tools
            during a run so the route can persist them in graph_update_json
            for concepts_covered derivation in end_session.
        mastery_changes: Accumulates the real before/after mastery deltas
            returned by apply_graph_update so the route can surface them in
            the chat response for parity with the legacy path.
        feature: Which product surface is driving this run ("quiz",
            "tutor", …). Several tools are registered on more than one
            agent — `read_concepts_for_user` is on both the quiz and the
            tutor — so a tool cannot name its caller from its own module.
            Observability that attributes per-feature (services/
            tool_signals.py) reads it from here. Defaults to "unknown"
            rather than to any real feature: a wrong attribution is worse
            than an absent one.
        retrieval: Optional TutorRetrieval implementation (ADR 0023). When
            None (production), the tutor's read tools fall back to the
            Supabase-backed impl in agents/tools/retrieval.py — byte-
            identical behavior. Evals inject a FixtureRetrieval here so
            record/live runs never touch a database. Typed Any to avoid
            the circular import deps → retrieval → chat_context → deps.
    """

    user_id: str
    course_id: str | None
    supabase: Any
    request_id: str
    session_id: str | None = None
    feature: str = "unknown"
    graph_updates: list = field(default_factory=list)
    mastery_changes: list = field(default_factory=list)
    retrieval: Any = None

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
            the chat response. Always empty since PKG-14b: no tutor tool
            moves mastery any more (update_mastery_tool is gone); kept
            because services/chat_stream.py and the chat wire shape
            (`mastery_changes: []`) still read it.
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
        share_class_context: Whether this student consented to class-derived
            data (the "Class intel" toggle, migration 0037). Tools that read
            OTHER students' aggregated work — `read_misconceptions_for_course`
            — must return nothing when it is False. It lives here rather than
            in the prompt because a system-prompt instruction is a request to
            a model, and consent is not something to leave to one: the tool is
            registered on quiz_agent unconditionally and the prompt tells the
            model to call it every run. Defaults True to match the column
            default; an explicit False is the only thing that suppresses.
        learning_loop: Result of `learning.gate.learning_loop_for_request`,
            computed ONCE by the route at request entry (owner decision 00)
            and carried here, so nothing below the route re-reads
            `user_settings` per call; the gate fails closed, so an unset
            kill switch or a failed read lands here as False. Selects the
            loop tool set and routes. Defaults False —
            the legacy path.
        loop_state: The session's typed loop state (PKG-06); None on the
            legacy path.
        pending_evidence: `learning.evidence.Evidence` dicts accumulated by
            `graded_check_tool` (PKG-05) for the ROUTE to persist through
            `apply_graph_update` — tools never write graph tables.
        loop_turn: The `learning.turn_shape.TurnLimits` for this loop tutor
            turn (phase, model ceiling, answer released). The loop tutor's
            output validator judges the FINAL structured turn against it;
            None → the loosest unreleased limits. Typed Any so agents/deps.py
            stays free of learning/ imports.
        loop_leak: The loop route's leak guard for this turn (PKG-07 fix
            round 2, N1): `.leaks(text) -> bool` and `.retried`. The
            output validator re-runs a leaking turn ONCE with the problem
            named; None → no leak check (no active item, or released).
    """

    user_id: str
    course_id: str | None
    supabase: Any
    request_id: str
    session_id: str | None = None
    feature: str = "unknown"
    share_class_context: bool = True
    graph_updates: list = field(default_factory=list)
    mastery_changes: list = field(default_factory=list)
    retrieval: Any = None
    learning_loop: bool = False
    loop_state: Any = None
    pending_evidence: list = field(default_factory=list)
    loop_turn: Any = None
    loop_leak: Any = None

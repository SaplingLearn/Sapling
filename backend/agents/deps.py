"""Shared dependencies passed to every Sapling Pydantic AI agent.

Agents receive a SaplingDeps instance via the `deps` parameter and access
it inside tools via `RunContext[SaplingDeps]`. This is the seam between
agent code and the rest of the backend (DB, auth context, logging).
"""

from __future__ import annotations

from dataclasses import dataclass
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
    """

    user_id: str
    course_id: str | None
    supabase: Any
    request_id: str

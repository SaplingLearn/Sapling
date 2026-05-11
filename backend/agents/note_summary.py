"""Note-summary agent — short paragraph summary of a single user note.

Output type is intentionally one field (NoteSummary.summary) per the
"keep agent output types small" lesson from
docs/attempts/2026-05-03-orchestrator-schema-complexity.md.
"""
from __future__ import annotations

import hashlib

from pydantic import BaseModel, Field
from pydantic_ai import Agent

from agents._providers import model_for
from agents.deps import SaplingDeps


class NoteSummary(BaseModel):
    summary: str = Field(
        description="2–4 sentence summary of the note's main idea.",
    )


_PROMPT = (
    "You are summarizing a single student's note. Produce a faithful "
    "2–4 sentence summary that captures the key idea and any "
    "explicit open questions the student wrote. Do not invent facts; "
    "if the note is empty or near-empty, say so plainly. Output Markdown."
)

_PROMPT_HASH = hashlib.sha256(_PROMPT.encode("utf-8")).hexdigest()[:12]


note_summary_agent = Agent[SaplingDeps, NoteSummary](
    model=model_for("note_summary"),
    deps_type=SaplingDeps,
    output_type=NoteSummary,
    system_prompt=_PROMPT,
    metadata={"prompt_version": _PROMPT_HASH, "agent": "note_summary"},
)

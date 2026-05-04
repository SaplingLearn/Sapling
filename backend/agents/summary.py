"""Document summary agent.

Produces a structured summary from extracted document text. Replaces
the inline summarization step in routes/documents.py and is reused by
study_guide generation in a future prompt.
"""

from __future__ import annotations

from pydantic import BaseModel, Field
from pydantic_ai import Agent

from agents._providers import model_for
from agents.deps import SaplingDeps


class Summary(BaseModel):
    """Typed output for the summary agent."""

    headline: str = Field(
        max_length=140,
        description="Single-sentence summary for a card view.",
    )
    abstract: str = Field(
        max_length=1500,
        description="3-5 sentence overview. Plain text. No markdown.",
    )
    key_points: list[str] = Field(
        min_length=3,
        max_length=8,
        description="3-8 most important takeaways, each one sentence.",
    )


summary_agent = Agent[SaplingDeps, Summary](
    model=model_for("summary"),
    deps_type=SaplingDeps,
    output_type=Summary,
    system_prompt=(
        "You are summarizing a student-uploaded document so the student "
        "can find it later in their library and so downstream agents "
        "(study guide, quiz, tutor) can reason over its content.\n\n"
        "Produce: a single-sentence headline (<=140 chars) that names "
        "what this document is about; a 3-5 sentence abstract in plain "
        "prose with no markdown, math, or fenced blocks; and 3-8 key "
        "takeaways, each one sentence, ordered by importance.\n\n"
        "Stay grounded in the document. Do not embellish with general "
        "knowledge the text does not state. If the document is sparse "
        "or near-empty, say so in the headline rather than padding."
    ),
)

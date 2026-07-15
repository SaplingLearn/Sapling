"""Study-group summary agent.

Replaces the inline ``call_gemini`` call in routes/social.py. Produces a short
plain-text summary of a study group's collective knowledge, focused on
complementary strengths and shared goals.
"""

from __future__ import annotations

import hashlib

from pydantic import BaseModel, Field
from pydantic_ai import Agent

from agents._providers import model_for
from agents.deps import SaplingDeps


class SocialSummary(BaseModel):
    summary: str = Field(
        description=(
            "2-3 sentence summary of the study group's collective knowledge, "
            "focused on complementary strengths and shared goals."
        ),
    )


_SYSTEM_PROMPT = (
    "You summarize a study group's collective knowledge for its members. Given "
    "each member's mastered and struggling concepts, write a 2-3 sentence "
    "summary that highlights the group's complementary strengths and shared "
    "goals. Keep it encouraging and concrete. Do not invent members or topics "
    "beyond what you are given."
)
_PROMPT_HASH = hashlib.sha256(_SYSTEM_PROMPT.encode("utf-8")).hexdigest()[:12]


social_summary_agent = Agent[SaplingDeps, SocialSummary](
    model=model_for("social_summary"),
    deps_type=SaplingDeps,
    output_type=SocialSummary,
    system_prompt=_SYSTEM_PROMPT,
    metadata={"prompt_version": _PROMPT_HASH, "agent": "social_summary"},
)

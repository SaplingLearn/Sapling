"""Shared model/provider construction for Sapling agents.

Each agent has a task-specific default. Operators can override any model
via env vars without touching code:

    SAPLING_MODEL_CLASSIFIER=gemini-2.5-flash-lite
    SAPLING_MODEL_SUMMARY=gemini-2.5-flash-lite
    SAPLING_MODEL_CONCEPTS=gemini-2.5-flash
    SAPLING_MODEL_SYLLABUS=gemini-2.5-flash
    SAPLING_MODEL_QUIZ=gemini-2.5-flash-lite

Defaults are tuned per task: cheaper models for simpler classifications,
flagship Flash for tasks where output quality drives downstream UX.
"""

from __future__ import annotations

import os
from typing import Literal

from pydantic_ai.models.google import GoogleModel
from pydantic_ai.providers.google import GoogleProvider

from config import GEMINI_API_KEY


AgentTask = Literal["classifier", "summary", "concepts", "syllabus", "quiz"]


# Defaults are conservative. Bumping a model up costs more; the env var
# escape hatch lets us A/B without redeploying.
_DEFAULTS: dict[AgentTask, str] = {
    "classifier": "gemini-2.5-flash-lite",
    "summary": "gemini-2.5-flash-lite",
    "concepts": "gemini-2.5-flash",
    "syllabus": "gemini-2.5-flash",
    # Quiz generation defaults to lite: it's a single-shot non-streaming
    # call where the agent pulls structured graph data via tools, so the
    # bulk of the value is in tool wiring, not raw model strength.
    "quiz": "gemini-2.5-flash-lite",
}


# Pydantic AI's GoogleProvider expects an API key at construction. CI and
# import-time tools don't have GEMINI_API_KEY set; the dummy keeps imports
# clean and only fails at .run() time when the agent actually needs Gemini.
_provider = GoogleProvider(api_key=GEMINI_API_KEY or "dummy-key-for-import")


def model_for(task: AgentTask) -> GoogleModel:
    """Return the configured model for a given pipeline task.

    Reads SAPLING_MODEL_<TASK_UPPER> from env first, falls back to the
    per-task default. Returns a GoogleModel sharing the project provider.
    """
    env_key = f"SAPLING_MODEL_{task.upper()}"
    name = os.getenv(env_key) or _DEFAULTS[task]
    return GoogleModel(name, provider=_provider)


# Back-compat shim for any caller still using google_model(name).
def google_model(name: str) -> GoogleModel:
    """Return a configured GoogleModel sharing the project-wide provider."""
    return GoogleModel(name, provider=_provider)

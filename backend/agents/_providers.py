"""Shared model/provider construction for Sapling agents.

Each agent module previously instantiated its own GoogleProvider with the
GEMINI_API_KEY-or-dummy fallback. Centralizing here keeps the boilerplate
in one place and lets us swap providers/models from a single seam.
"""

from __future__ import annotations

from pydantic_ai.models.google import GoogleModel
from pydantic_ai.providers.google import GoogleProvider

from config import GEMINI_API_KEY


# Pydantic AI's GoogleProvider expects an API key at construction. CI and
# import-time tools don't have GEMINI_API_KEY set; the dummy keeps imports
# clean and only fails at .run() time when the agent actually needs Gemini.
_provider = GoogleProvider(api_key=GEMINI_API_KEY or "dummy-key-for-import")


def google_model(name: str) -> GoogleModel:
    """Return a configured GoogleModel sharing the project-wide provider."""
    return GoogleModel(name, provider=_provider)

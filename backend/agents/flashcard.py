"""Flashcard agent.

One agent for every flashcard LLM task (generation, OCR-split, cleanup, cloze).
Replaces the raw `call_gemini` seams in `services/flashcard_import_service.py`
and `gemini_service.generate_flashcards`. Task-specific instructions live in the
existing prompt templates (flashcard_generation.txt, flashcard_cleanup.txt,
flashcard_cloze.txt, flashcard_ocr_split.txt) that callers pass as the user
message; the agent just enforces the front/back output shape.
"""

from __future__ import annotations

import hashlib

from google.genai.types import ThinkingConfig
from pydantic import BaseModel, Field
from pydantic_ai import Agent
from pydantic_ai.models.google import GoogleModelSettings

from agents._providers import model_for


class FlashCard(BaseModel):
    front: str = Field(description="Front of the card — a question, term, or cloze prompt.")
    back: str = Field(description="Back of the card — the answer or definition.")


class Flashcards(BaseModel):
    cards: list[FlashCard] = Field(
        default_factory=list,
        description="The generated/cleaned study cards.",
    )


_SYSTEM_PROMPT = (
    "You create study flashcards. Follow the task instructions in the user "
    "message, and return the result as a list of cards, each with a clear "
    "`front` (question, term, or cloze prompt) and `back` (answer or "
    "definition). Base card content on the material provided; do not invent "
    "facts it does not support. Omit any card you cannot fill both sides of."
)
_PROMPT_HASH = hashlib.sha256(_SYSTEM_PROMPT.encode("utf-8")).hexdigest()[:12]


# Pin the sampling params the legacy `call_gemini` flashcard path used so the
# migration doesn't silently flip cost/latency/determinism: temperature 0.7,
# an 8192-token output cap, and thinking disabled (budget 0). GoogleModel's
# defaults would otherwise enable dynamic thinking and provider-default
# temperature. Flash accepts thinking_budget=0 (unlike Pro).
_FLASHCARD_SETTINGS = GoogleModelSettings(
    temperature=0.7,
    max_tokens=8192,
    google_thinking_config=ThinkingConfig(thinking_budget=0),
)


flashcard_agent = Agent[None, Flashcards](
    model=model_for("flashcard"),
    output_type=Flashcards,
    system_prompt=_SYSTEM_PROMPT,
    model_settings=_FLASHCARD_SETTINGS,
    metadata={"prompt_version": _PROMPT_HASH, "agent": "flashcard"},
)

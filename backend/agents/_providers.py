"""Shared model/provider construction for Sapling agents.

Each agent has a task-specific default. Operators can override any model
via env vars without touching code:

    SAPLING_MODEL_CLASSIFIER=gemini-2.5-flash-lite
    SAPLING_MODEL_SUMMARY=gemini-2.5-flash-lite
    SAPLING_MODEL_CONCEPTS=gemini-2.5-flash
    SAPLING_MODEL_SYLLABUS=gemini-2.5-flash
    SAPLING_MODEL_QUIZ=gemini-2.5-flash-lite
    SAPLING_MODEL_CHAT_TUTOR=gemini-2.5-pro

Defaults are tuned per task: cheaper models for simpler classifications,
flagship Flash for tasks where output quality drives downstream UX, and
the Pro tier for the conversational tutor where reasoning depth matters.
"""

from __future__ import annotations

import os
from typing import Literal

from pydantic_ai.models.google import GoogleModel
from pydantic_ai.providers.google import GoogleProvider

from config import GEMINI_API_KEY


AgentTask = Literal[
    "classifier", "summary", "concepts", "syllabus", "quiz", "chat_tutor",
    "note_summary", "note_concepts", "note_chat",
    "study_guide", "social_summary",
    "flashcard",
    "course_summary", "quiz_context",
    "concept_scan", "concept_describe",
]


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
    # Chat tutor runs on Pro: it streams a multi-turn pedagogical
    # conversation where reasoning depth and instruction following drive
    # perceived quality. Matches main's tutor default after PR #73
    # (`feat(learn): use gemini-2.5-pro for tutor chat`) and PR #74
    # (`fix(learn): allow thinking on gemini-2.5-pro multiturn calls`).
    "chat_tutor": "gemini-2.5-pro",
    "note_summary": "gemini-2.5-flash-lite",
    "note_concepts": "gemini-2.5-flash-lite",
    "note_chat": "gemini-2.5-flash",
    # Study guide is quality-sensitive multi-topic generation → full Flash.
    "study_guide": "gemini-2.5-flash",
    # Social summary is short-form prose → the cheaper lite tier is enough.
    "social_summary": "gemini-2.5-flash-lite",
    # Flashcard generation/cleanup/cloze — content quality matters → full Flash.
    # Only the model *name* matches the legacy call_gemini flashcard path; the
    # legacy sampling params (temperature=0.7, max_output_tokens=8192,
    # thinking disabled) are pinned separately as model_settings on the agent
    # in agents/flashcard.py so full parity with the old path is preserved.
    "flashcard": "gemini-2.5-flash",
    # Instructor class summary — a few paragraphs of analysis → full Flash.
    "course_summary": "gemini-2.5-flash",
    # Quiz-context notes are short structured extraction → the lite tier.
    "quiz_context": "gemini-2.5-flash-lite",
    # Scan-concepts extends an existing course concept set from a short
    # context (existing concepts + optional doc summary) → the cheap lite
    # tier, matching the MODEL_LITE the legacy path used.
    "concept_scan": "gemini-2.5-flash-lite",
    # One-sentence concept blurb for the knowledge-map rail — a tiny,
    # short-output generation → the cheap lite tier.
    "concept_describe": "gemini-2.5-flash-lite",
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


def model_name_for(task: AgentTask) -> str:
    """Resolve the model name for a task (env override, else default).

    Same resolution `model_for` uses, exposed as a bare name so callers that
    need to rebuild the model on a different provider don't duplicate it.
    """
    return os.getenv(f"SAPLING_MODEL_{task.upper()}") or _DEFAULTS[task]


def fresh_model_for(task: AgentTask) -> GoogleModel:
    """`model_for(task)` but on a fresh provider — see `fresh_google_model`.

    Use for agent runs driven on a throwaway/per-request event loop (anything
    behind `run_agent_sync`'s ``asyncio.run``, or a stream's second request):
    the shared client's pooled connection outlives the loop that opened it and
    trips ``RuntimeError: Event loop is closed`` on the next reuse.
    """
    return fresh_google_model(model_name_for(task))


def fresh_google_model(name: str) -> GoogleModel:
    """Like `google_model`, but on a NEW GoogleProvider — a fresh google.genai
    client with its own connection pool, instead of the shared `_provider`.

    A streaming tutor turn makes TWO sequential streamed model requests in one
    run (reply → tool calls → continuation). Reusing the shared client's pooled
    HTTP connection across them surfaced `RuntimeError: Event loop is closed`
    in google-genai's httpx teardown (the pooled connection carried a stale
    event-loop reference). A per-request client, created and used only on the
    live request loop, sidesteps the cross-loop connection reuse.
    """
    provider = GoogleProvider(api_key=GEMINI_API_KEY or "dummy-key-for-import")
    return GoogleModel(name, provider=provider)

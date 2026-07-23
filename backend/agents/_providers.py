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
from typing import TYPE_CHECKING, Callable, Literal

from pydantic_ai.models.google import GoogleModel
from pydantic_ai.providers.google import GoogleProvider

from config import GEMINI_API_KEY

if TYPE_CHECKING:  # keep pydantic-ai's function-model imports out of the prod path
    from pydantic_ai.messages import ModelMessage, ModelResponse
    from pydantic_ai.models.function import AgentInfo


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


# ── Test seam: SAPLING_MODEL_MODE (#391) ───────────────────────────────────
#
# `model_for` is the single construction point for every agent's model, so it
# is the only place a deterministic model can be swapped in without stubbing
# whole agent objects (which leaves the real prompt/tool/output wiring
# untested). Modes:
#
#   real     — GoogleModel. The production default; an unset/empty var is real,
#              so nothing about the deployed path or the hermetic unit lane
#              changes.
#   function — pydantic-ai FunctionModel, driven by a per-task handler a test
#              registers via `register_function_handler`. Scripted tool calls
#              run through the REAL tool registration, arg-schema validation,
#              and retry loop.
#   cassette — record/replay from tests/evals. Reserved here (issue #391 scope)
#              but not yet built; raises rather than silently falling through.
#
# Why this sits ABOVE the transport guard (#379): a FunctionModel never builds a
# `google.genai` request, so a function-mode run does not touch the patched
# `BaseApiClient` and needs no hermetic-guard exemption. If a change ever makes
# function mode reach the transport, `test_function_mode_rides_above_transport_
# guard` fails — that is the design invariant, not an accident.
ModelMode = Literal["real", "function", "cassette"]

# task -> handler(messages, info) -> ModelResponse. Consulted ONLY in function
# mode (off by default), so it can never affect production or the default lane.
FunctionModelHandler = Callable[
    ["list[ModelMessage]", "AgentInfo"], "ModelResponse"
]
_FUNCTION_HANDLERS: dict[str, FunctionModelHandler] = {}


def _model_mode() -> str:
    """The active model mode. Unset/blank → 'real'. Normalized for stray
    case/whitespace so a CI or shell-exported value isn't brittle."""
    return (os.getenv("SAPLING_MODEL_MODE") or "real").strip().lower()


def register_function_handler(task: AgentTask, handler: FunctionModelHandler) -> None:
    """Register the FunctionModel handler for a task (function mode only).

    The handler has pydantic-ai's FunctionModel signature: it receives the
    request messages and an `AgentInfo` (carrying the agent's registered tools
    and output tools) and returns a `ModelResponse`. Tests use this to script
    tool calls / final output for a specific agent.
    """
    _FUNCTION_HANDLERS[task] = handler


def unregister_function_handler(task: AgentTask) -> None:
    _FUNCTION_HANDLERS.pop(task, None)


def clear_function_handlers() -> None:
    """Drop all registered handlers. Tests call this around each case so
    process-global registrations never leak between them."""
    _FUNCTION_HANDLERS.clear()


def _function_model_for(task: AgentTask) -> GoogleModel:
    """Build a FunctionModel that dispatches to the task's registered handler at
    run time. The lookup is deferred to the call (not capture time) so a handler
    registered after the agent was imported still takes effect."""
    from pydantic_ai.models.function import FunctionModel

    def _dispatch(messages, info):
        handler = _FUNCTION_HANDLERS.get(task)
        if handler is None:
            raise LookupError(
                f"SAPLING_MODEL_MODE=function but no handler is registered for "
                f"task {task!r}. Call agents._providers.register_function_handler("
                f"{task!r}, ...) before running the agent."
            )
        return handler(messages, info)

    # Typed as GoogleModel for the shared return signature; FunctionModel is a
    # pydantic-ai Model like GoogleModel and agents accept either.
    return FunctionModel(_dispatch, model_name=f"function:{task}")  # type: ignore[return-value]


def model_for(task: AgentTask) -> GoogleModel:
    """Return the configured model for a given pipeline task.

    Dispatches on SAPLING_MODEL_MODE (default 'real'). In real mode, reads the
    per-task SAPLING_MODEL_<TASK_UPPER> override first (ADR 0008), else the
    per-task default, and returns a GoogleModel sharing the project provider.
    In function mode, returns a FunctionModel (see the seam notes above).
    """
    mode = _model_mode()
    if mode == "real":
        env_key = f"SAPLING_MODEL_{task.upper()}"
        name = os.getenv(env_key) or _DEFAULTS[task]
        return GoogleModel(name, provider=_provider)
    if mode == "function":
        return _function_model_for(task)
    if mode == "cassette":
        raise NotImplementedError(
            "SAPLING_MODEL_MODE=cassette (record/replay from tests/evals) is "
            "reserved by #391 but not yet implemented; use 'function' for "
            "deterministic agent tests or 'real' for live calls."
        )
    raise ValueError(
        f"unknown SAPLING_MODEL_MODE={mode!r}; expected one of 'real', "
        f"'function', 'cassette'. An unrecognized mode is a config error, not a "
        f"silent fall-through to real (which would bill Gemini)."
    )


# Back-compat shim for any caller still using google_model(name).
def google_model(name: str) -> GoogleModel:
    """Return a configured GoogleModel sharing the project-wide provider."""
    return GoogleModel(name, provider=_provider)

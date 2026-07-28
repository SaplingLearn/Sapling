"""Shared model/provider construction for Sapling agents.

Each agent has a task-specific default. Operators can override any model
via env vars without touching code:

    SAPLING_MODEL_CLASSIFIER=gemini-2.5-flash-lite
    SAPLING_MODEL_SUMMARY=gemini-2.5-flash-lite
    SAPLING_MODEL_CONCEPTS=gemini-2.5-flash
    SAPLING_MODEL_SYLLABUS=gemini-2.5-flash
    SAPLING_MODEL_QUIZ=gemini-2.5-flash-lite
    SAPLING_MODEL_CHAT_TUTOR=gemini-2.5-pro
    SAPLING_MODEL_OCR_VISION=gemini-2.5-flash

Defaults are tuned per task: cheaper models for simpler classifications,
flagship Flash for tasks where output quality drives downstream UX, and
the Pro tier for the conversational tutor where reasoning depth matters.
"""

from __future__ import annotations

import asyncio
import importlib
import os
import threading
import weakref
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any, Callable, Literal

from pydantic_ai.models.google import GoogleModel
from pydantic_ai.providers.google import GoogleProvider

from config import GEMINI_API_KEY

if TYPE_CHECKING:  # keep pydantic-ai's function-model imports out of the prod path
    from pydantic_ai.messages import ModelMessage, ModelResponse
    from pydantic_ai.models import Model, ModelRequestParameters
    from pydantic_ai.models.function import AgentInfo
    from pydantic_ai.settings import ModelSettings
    from pydantic_ai.usage import RequestUsage


AgentTask = Literal[
    "classifier", "summary", "concepts", "syllabus", "quiz", "chat_tutor",
    "note_summary", "note_concepts", "note_chat",
    "study_guide", "social_summary",
    "flashcard",
    "course_summary", "quiz_context",
    "concept_scan", "concept_describe",
    "ocr_vision",
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
    # Page-image OCR (handwritten/scanned coursework). Must be a
    # vision-capable model, and transcription accuracy on handwritten
    # mathematics is exactly where the lite tier degrades → full Flash.
    "ocr_vision": "gemini-2.5-flash",
}


def _new_provider() -> GoogleProvider:
    """A fresh `GoogleProvider` (fresh `google.genai` client + httpx connection
    pool). CI and import-time tools don't have GEMINI_API_KEY set; the dummy
    keeps imports clean and only fails at .run() time when the agent actually
    needs Gemini."""
    return GoogleProvider(api_key=GEMINI_API_KEY or "dummy-key-for-import")


# ── #354 root-cause fix: loop-scoped provider, not a process-wide singleton ─
#
# Every agent is built ONCE, at import time, from `Agent(model=model_for(task),
# ...)` — so whatever `Model` instance `model_for`/`google_model` hand back is
# shared across every later `.run()` call for that agent's whole process
# lifetime. Until this fix, that model wrapped ONE module-level `GoogleProvider`
# singleton, and `GoogleProvider.__init__` eagerly builds an `httpx.AsyncClient`
# whose connection pool binds internal asyncio primitives (locks, etc.) to
# whichever event loop is running the first time a request actually goes out
# over it.
#
# `run_agent_sync` (`agents/_run.py`, `asyncio.run`) drives agents on a BRAND
# NEW throwaway loop per call, closed on return — and, identically, so does any
# test that calls `asyncio.run()` more than once against the same shared agent
# in one process (e.g. `tests/test_ocr_pipeline.py::test_agent_parse` then
# the `parsed_assignments` fixture feeding `test_save_to_db`, #436). Reusing
# the singleton's client after its original loop closes trips
# `RuntimeError: Event loop is closed` on the very next call through it —
# every SECOND real call, alternating forever.
#
# A prior attempt (#358, never merged) fixed this by sweeping every
# `run_agent_sync` call SITE to pass a `model=` override built on a fresh
# provider. That requires every current AND future caller to remember the
# override — `agents/ocr_vision.py` already needed its own ad hoc copy of the
# same idea for the one path #358 didn't wait for (OCR page transcription),
# and `test_save_to_db`'s failure shows a caller (`calendar_service`'s
# syllabus-extraction agent) that wasn't even on #358's sweep list. The issue
# itself flagged this as "the tactical sweep", with "make the shared provider
# loop-safe" as the strategic fix.
#
# `_LoopSafeGoogleModel` is that strategic fix: instead of a fixed provider, it
# keeps one provider PER currently-running event loop (a `WeakKeyDictionary`
# keyed by the loop object itself, so entries vanish on their own once a
# throwaway loop is garbage-collected — no unbounded growth over a long
# process's lifetime of `run_agent_sync` calls). Built once via `model_for`/
# `google_model` and assigned to an agent at import time exactly like before,
# it transparently rebuilds its provider the first time a NEW loop calls it,
# and reuses the cached one for as long as that loop stays alive — the same
# connection-pooling benefit the old singleton gave the one loop that matters
# most, FastAPI's persistent per-process async loop, while never reusing a
# client across two different loops. No call site — present or future — has
# to know event loops exist.
class _LoopSafeGoogleModel(GoogleModel):
    """A `GoogleModel` whose provider is rebuilt per running event loop
    instead of fixed at construction. See the module-level comment above for
    why (#354/#436)."""

    def __init__(self, model_name: str) -> None:
        super().__init__(model_name, provider=_new_provider())
        self._loop_providers: "weakref.WeakKeyDictionary[Any, GoogleProvider]" = (
            weakref.WeakKeyDictionary()
        )
        self._loop_providers_lock = threading.Lock()

    def _bind_to_current_loop(self) -> None:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            # No running loop (e.g. inspected outside a request/run) — leave
            # whatever provider is already set.
            return
        with self._loop_providers_lock:
            provider = self._loop_providers.get(loop)
            if provider is None:
                provider = _new_provider()
                self._loop_providers[loop] = provider
            self._provider = provider

    async def __aenter__(self):
        self._bind_to_current_loop()
        return await super().__aenter__()

    async def request(
        self,
        messages: "list[ModelMessage]",
        model_settings: "ModelSettings | None",
        model_request_parameters: "ModelRequestParameters",
    ) -> "ModelResponse":
        self._bind_to_current_loop()
        return await super().request(messages, model_settings, model_request_parameters)

    async def count_tokens(
        self,
        messages: "list[ModelMessage]",
        model_settings: "ModelSettings | None",
        model_request_parameters: "ModelRequestParameters",
    ) -> "RequestUsage":
        self._bind_to_current_loop()
        return await super().count_tokens(messages, model_settings, model_request_parameters)

    @asynccontextmanager
    async def request_stream(
        self,
        messages: "list[ModelMessage]",
        model_settings: "ModelSettings | None",
        model_request_parameters: "ModelRequestParameters",
        run_context=None,
    ):
        self._bind_to_current_loop()
        async with super().request_stream(
            messages, model_settings, model_request_parameters, run_context
        ) as stream:
            yield stream


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


def clear_function_handlers() -> None:
    """Drop all registered handlers. Tests call this around each case so
    process-global registrations never leak between them."""
    _FUNCTION_HANDLERS.clear()


# ── Boot-time handler registration for out-of-process runs (#392) ──────────
#
# `register_function_handler` covers in-process tests, but the E2E browser lane
# boots the backend as a separate uvicorn process (`SAPLING_MODEL_MODE=function
# make e2e-up`) where no pytest fixture can reach the registry. ADR 0019
# anticipated this: full-journey lanes "must set SAPLING_MODEL_MODE=function at
# process start ... then register per-task handlers". SAPLING_FUNCTION_HANDLERS
# names a module (e.g. `agents.function_handlers_e2e`) whose import registers
# handlers. It is consulted lazily, once, and ONLY on a dispatch miss — so the
# normal (hermetic) pytest lane, which registers explicitly and does not set
# the var, is unchanged, and a test that forgot to register a handler still
# gets the loud LookupError. (The seam's own tests DO set the var, resetting
# the latch around each case.)

_ENV_HANDLERS_LOADED = False


def _load_env_handlers_module() -> None:
    """Import the SAPLING_FUNCTION_HANDLERS module (once per process).

    A bad module path raises ImportError loudly at EVERY dispatch, not just
    the first — a broken E2E boot must fail the run, never silently fall
    through to LookupError with the wrong story. That is why the latch is
    set only after a successful import (or when there is nothing to load):
    latching before the import would permanently cache the failure as
    "loaded" and downgrade every later dispatch to the generic LookupError.
    """
    global _ENV_HANDLERS_LOADED
    if _ENV_HANDLERS_LOADED:
        return
    module = (os.getenv("SAPLING_FUNCTION_HANDLERS") or "").strip()
    if module:
        importlib.import_module(module)  # raises before the latch on failure
    _ENV_HANDLERS_LOADED = True


def _function_model_for(task: AgentTask) -> "Model":
    """Build a FunctionModel that dispatches to the task's registered handler at
    run time. The lookup is deferred to the call (not capture time) so a handler
    registered after the agent was imported still takes effect."""
    from pydantic_ai.models.function import FunctionModel

    def _dispatch(messages, info):
        handler = _FUNCTION_HANDLERS.get(task)
        if handler is None:
            # Out-of-process runs (E2E uvicorn) register via the env-named
            # module; loaded lazily on the first miss, no-op when unset.
            _load_env_handlers_module()
            handler = _FUNCTION_HANDLERS.get(task)
        if handler is None:
            raise LookupError(
                f"SAPLING_MODEL_MODE=function but no handler is registered for "
                f"task {task!r}. Call agents._providers.register_function_handler("
                f"{task!r}, ...) before running the agent (or point "
                f"SAPLING_FUNCTION_HANDLERS at a module that does)."
            )
        return handler(messages, info)

    return FunctionModel(_dispatch, model_name=f"function:{task}")


def model_name_for(task: AgentTask) -> str:
    """The Gemini model *name* configured for a task, without building a Model.

    The ADR-0008 resolution rule in one place: per-task
    SAPLING_MODEL_<TASK_UPPER> override first, else the per-task default.
    `model_for` uses it in real mode; callers that need the name as data (the
    OCR cache key keys on it, because a different model transcribes a scan
    differently) use it directly rather than reaching for a parallel env knob.

    Deliberately does NOT dispatch on SAPLING_MODEL_MODE: this is a total,
    never-raising read of configuration, safe to call on paths (cache keys)
    where a config-mode error must not become a request failure.
    """
    return os.getenv(f"SAPLING_MODEL_{task.upper()}") or _DEFAULTS[task]


def model_for(task: AgentTask) -> "Model":
    """Return the configured model for a given pipeline task.

    Dispatches on SAPLING_MODEL_MODE (default 'real'). In real mode, reads the
    per-task SAPLING_MODEL_<TASK_UPPER> override first (ADR 0008), else the
    per-task default, and returns a `_LoopSafeGoogleModel` (#354/#436 — see the
    comment above that class) so the caller never has to think about which
    event loop it ends up running on. In function mode, returns a FunctionModel
    (see the seam notes above).
    """
    mode = _model_mode()
    if mode == "real":
        return _LoopSafeGoogleModel(model_name_for(task))
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
    """Return a configured GoogleModel for a bare model name (bypassing the
    per-task `_DEFAULTS`/env-override resolution `model_for` does), on the
    same loop-safe basis as `model_for` (#354/#436)."""
    return _LoopSafeGoogleModel(name)

"""Shared model/provider construction for Sapling agents.

Each agent has a task-specific default. Operators can override any model
via env vars without touching code:

    SAPLING_MODEL_CLASSIFIER=claude-haiku-5-5
    SAPLING_MODEL_QUIZ=claude-haiku-5-5
    SAPLING_MODEL_CHAT_TUTOR=claude-sonnet-5-5
    SAPLING_MODEL_SYLLABUS=gemini-2.5-flash      # roll one slot back to Gemini

The provider is inferred from the model name (`claude-*` → Anthropic,
`gemini-*` → Google; ADR 0030), so a slot moves between providers with an
env flip and no code change. Defaults are tuned per task: Claude Haiku 5.5
for every generation slot (it prices at or below the Gemini Flash/Flash-Lite
tiers it replaced — the no-price-increase rule) with per-task `effort`, and
Claude Sonnet 5.5 for the conversational tutor where reasoning depth matters.
RAG embeddings are NOT an agent and stay on Gemini (`services/rag_service.py`):
Anthropic has no embeddings API.
"""

from __future__ import annotations

import asyncio
import importlib
import os
import threading
import weakref
from dataclasses import replace
from typing import TYPE_CHECKING, Any, Callable, Literal

from pydantic_ai.models.anthropic import AnthropicModel, AnthropicModelSettings
from pydantic_ai.models.google import GoogleModel, GoogleModelSettings
from pydantic_ai.profiles.anthropic import AnthropicModelProfile
from pydantic_ai.providers.anthropic import AnthropicProvider
from pydantic_ai.providers.google import GoogleProvider

from config import ANTHROPIC_API_KEY, GEMINI_API_KEY

if TYPE_CHECKING:  # keep pydantic-ai's function-model imports out of the prod path
    from pydantic_ai.messages import ModelMessage, ModelResponse
    from pydantic_ai.models import Model
    from pydantic_ai.models.function import AgentInfo


AgentTask = Literal[
    "classifier", "summary", "concepts", "syllabus", "quiz", "chat_tutor",
    "note_summary", "note_concepts", "note_chat",
    "study_guide", "social_summary",
    "flashcard",
    "course_summary", "quiz_context",
    "concept_scan", "concept_describe",
    "ocr_vision",
    "decision",
    "topic_checklist",
]


# Defaults are conservative. Bumping a model up costs more; the env var
# escape hatch lets us A/B (or roll a slot back to a gemini-* model) without
# redeploying.
#
# Gemini → Claude mapping (ADR 0030). Haiku 5.5 lists at $0.10/$0.50 per MTok
# (prompts ≤100K tokens) against Flash-Lite's $0.10/$0.40 and Flash's
# $0.30/$2.50, so every former Flash and Flash-Lite slot moves to Haiku and the
# quality/cost dial is `effort` (see `_ANTHROPIC_EFFORT`) rather than a model
# tier. The tutor keeps a step-up model, Sonnet 5.5, like it kept Pro.
_DEFAULTS: dict[AgentTask, str] = {
    "topic_checklist": "claude-haiku-5-5",
    "classifier": "claude-haiku-5-5",
    "summary": "claude-haiku-5-5",
    "concepts": "claude-haiku-5-5",
    "syllabus": "claude-haiku-5-5",
    # Quiz generation is a single-shot non-streaming call where the agent
    # pulls structured graph data via tools, so the bulk of the value is in
    # tool wiring, not raw model strength.
    "quiz": "claude-haiku-5-5",
    # Chat tutor runs on the step-up model: it streams a multi-turn
    # pedagogical conversation where reasoning depth and instruction following
    # drive perceived quality (the role gemini-2.5-pro held, PR #73/#74).
    "chat_tutor": "claude-sonnet-5-5",
    "note_summary": "claude-haiku-5-5",
    "note_concepts": "claude-haiku-5-5",
    "note_chat": "claude-haiku-5-5",
    "study_guide": "claude-haiku-5-5",
    "social_summary": "claude-haiku-5-5",
    "flashcard": "claude-haiku-5-5",
    "course_summary": "claude-haiku-5-5",
    "quiz_context": "claude-haiku-5-5",
    "concept_scan": "claude-haiku-5-5",
    "concept_describe": "claude-haiku-5-5",
    # Page-image OCR (handwritten/scanned coursework). Must be a
    # vision-capable model; every Claude model takes image input.
    "ocr_vision": "claude-haiku-5-5",
    # The typed decision seam's LLM backend (services/decisions.py, ADR 0027):
    # a handful of yes/no / choice / ordered-scale judgments per call, short
    # structured output, latency-sensitive. This is the `flash_lite` decision
    # backend (the variant name predates the provider swap) and the fallback
    # when Jev is unavailable.
    "decision": "claude-haiku-5-5",
}


# The admin `/api/gemini-test` connectivity probe has no `_DEFAULTS` task of
# its own; it just needs the cheapest round-trip. Pinned here so probe sites
# (agents/health.py) can't drift from each other.
HEALTH_PROBE_MODEL = "claude-haiku-5-5"


# ── Per-task request settings ────────────────────────────────────────────
#
# Attached to the Model instance (`Model(settings=...)`), so they are the
# BOTTOM layer of pydantic-ai's merge: an agent's own `model_settings` and a
# run-level `model_settings=` both override them. Keyed by provider because
# the knobs don't translate — Gemini has a thinking *budget*, Claude 5.x has
# only adaptive thinking steered by `effort` (a budget is a 400 there).

# Claude requires `max_tokens` on every request and pydantic-ai defaults it to
# 4096 — thinking tokens count against it, so a long structured output (a
# study guide, a 10-question quiz) after a think would truncate mid-JSON.
# 16K keeps every non-streaming call well under the SDK's 10-minute
# non-streaming guard while leaving headroom.
_ANTHROPIC_MAX_TOKENS = 16_000

# `effort` is the Claude quality/cost dial. Haiku 5.5 defaults to `medium`;
# the slots that ran on Flash-Lite (no thinking) drop to `low`, the slots that
# ran on full Flash (dynamic thinking) keep `medium`. The tutor sits at `low`
# (Anthropic's guidance for chat on Sonnet 5.5); routes/learn.py raises it to
# `medium` for the "smart" preference the same way it used to grant Pro a
# thinking budget.
_ANTHROPIC_EFFORT: dict[AgentTask, Literal["low", "medium", "high"]] = {
    "classifier": "low",
    "summary": "low",
    "quiz": "medium",
    "concepts": "medium",
    "syllabus": "medium",
    "topic_checklist": "medium",
    "chat_tutor": "low",
    "note_summary": "low",
    "note_concepts": "low",
    "note_chat": "medium",
    "study_guide": "medium",
    "social_summary": "low",
    # Flashcards ran on Flash with thinking disabled for parity with the
    # legacy call_gemini path; `low` is the nearest Claude setting.
    "flashcard": "low",
    "course_summary": "medium",
    "quiz_context": "low",
    "concept_scan": "low",
    "concept_describe": "low",
    "ocr_vision": "medium",
    "decision": "low",
}


# Slots whose runs are TOOL LOOPS — several requests per run, each resending
# the same system prompt + tool definitions + growing history — get automatic
# prompt caching (top-level `cache_control`; the breakpoint follows the last
# cacheable block). Measured live on the tutor: the second request of a turn
# read ~99% of its input from cache at 0.1x the input rate. Single-shot
# structured workers are left uncached: a 5-minute cache write costs 1.25x
# and they rarely repeat a prefix in time to read it back.
_ANTHROPIC_CACHED_TASKS: frozenset[AgentTask] = frozenset({"chat_tutor", "quiz", "note_chat"})


def _anthropic_settings_for(task: AgentTask | None) -> AnthropicModelSettings:
    settings = AnthropicModelSettings(max_tokens=_ANTHROPIC_MAX_TOKENS)
    if task is not None and task in _ANTHROPIC_EFFORT:
        settings["anthropic_effort"] = _ANTHROPIC_EFFORT[task]
    if task in _ANTHROPIC_CACHED_TASKS:
        settings["anthropic_cache"] = True
    return settings


def _google_settings_for(task: AgentTask | None) -> GoogleModelSettings | None:
    """Gemini-only knobs that used to live on individual agents. Only reached
    when a slot is pointed back at a gemini-* model."""
    if task == "flashcard":
        # Parity with the legacy call_gemini flashcard path: temperature 0.7,
        # thinking disabled. (Claude 4.7+ rejects non-default sampling
        # settings, so this cannot sit on the agent anymore.)
        from google.genai.types import ThinkingConfig

        return GoogleModelSettings(
            temperature=0.7,
            google_thinking_config=ThinkingConfig(thinking_budget=0),
        )
    return None


# ── Claude 5.x model profile ─────────────────────────────────────────────
#
# pydantic-ai picks request behaviour from a per-model-name profile, and the
# pinned 1.x line (`requirements.txt` caps <2 over the run_stream_events
# change) predates the Claude 5.x generation: for `claude-haiku-5-5` /
# `claude-sonnet-5-5` / `claude-opus-5-5` it falls back to a legacy profile
# that (a) sends a forced `tool_choice: any` for every structured output —
# Opus 5.5 and Sonnet 5.5 reject forcing with a 400, and Haiku 5.5 thinks by
# default, which also refuses forcing — (b) forwards `temperature`, which
# Claude 4.7+ rejects, and (c) never enables native JSON output. The
# overrides below are the 5.x facts pydantic-ai 2.x encodes for these names.
_CLAUDE_5_PREFIXES = (
    "claude-opus-5",
    "claude-sonnet-5",
    "claude-haiku-5",
    "claude-fable-5",
    "claude-mythos-5",
)


def _anthropic_profile(model_name: str) -> AnthropicModelProfile:
    profile = AnthropicModelProfile.from_profile(
        AnthropicProvider.model_profile(model_name)
    )
    if model_name.startswith(_CLAUDE_5_PREFIXES):
        profile = profile.update(
            AnthropicModelProfile(
                supports_json_schema_output=True,
                anthropic_supports_adaptive_thinking=True,
                anthropic_supports_effort=True,
                anthropic_supports_xhigh_effort=True,
                anthropic_disallows_budget_thinking=True,
                anthropic_disallows_sampling_settings=True,
                anthropic_supports_forced_tool_choice=False,
            )
        )
    if profile.supports_json_schema_output:
        # Structured output via `output_config.format` (constrained JSON)
        # instead of pydantic-ai's default output TOOL: the output tool is
        # what forces `tool_choice`, which thinking-on Claude models refuse.
        # Set here, at the provider, so the agents keep a plain
        # `output_type=Model` and a slot pointed back at Gemini keeps
        # Gemini's own default (tool output — Gemini 2.5 can't combine native
        # output with function tools, which the quiz agent has).
        profile = replace(profile, default_structured_output_mode="native")
    return profile


def _new_provider() -> GoogleProvider:
    """A fresh `GoogleProvider` (fresh `google.genai` client + httpx connection
    pool). CI and import-time tools don't have GEMINI_API_KEY set; the dummy
    keeps imports clean and only fails at .run() time when the agent actually
    needs Gemini."""
    return GoogleProvider(api_key=GEMINI_API_KEY or "dummy-key-for-import")


def _new_anthropic_provider() -> AnthropicProvider:
    """A fresh `AnthropicProvider` — a fresh `AsyncAnthropic` client over its
    OWN httpx pool (pydantic-ai's `create_async_http_client()`, not a cached
    shared one), so the per-loop cache below gets a genuinely loop-private
    connection pool. Same dummy-key-for-import rule as `_new_provider`."""
    return AnthropicProvider(api_key=ANTHROPIC_API_KEY or "dummy-key-for-import")


# ── #354 root-cause fix: loop-scoped provider, resolved at READ time ───────
#
# Every agent is built ONCE, at import time, from `Agent(model=model_for(task),
# ...)` — so whatever `Model` instance `model_for`/`provider_model` hand back is
# shared across every later `.run()` call for that agent's whole process
# lifetime, across every concurrent request. Until this fix, that model
# wrapped ONE module-level `GoogleProvider` singleton, and `GoogleProvider.
# __init__` eagerly builds an `httpx.AsyncClient` whose connection pool binds
# internal asyncio primitives (locks, etc.) to whichever event loop is running
# the first time a request actually goes out over it.
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
# FIX-ROUND-1 CORRECTION (PR review finding, concurrency bug): the first
# version of `_LoopSafeGoogleModel` resolved the right provider under a lock
# in `_bind_to_current_loop()`, but then handed it off through a single
# shared MUTABLE `self._provider` attribute — and `self` is itself a
# module-level singleton shared by every concurrent call to the agent it
# backs. `GoogleModel._generate_content` reads `self.client` (→
# `self._provider.client`) only AFTER an `await` (`self._build_content_and_
# config(...)`); in that window, a DIFFERENT thread running a DIFFERENT event
# loop — exactly what happens under concurrent requests, since every
# sync-`def` route drives `run_agent_sync` on a fresh thread + throwaway
# loop, and `gemini_vision_backend._run_from_anywhere` does the same for OCR
# — could call its OWN `_bind_to_current_loop()` and overwrite that same
# shared attribute. The first call would then resume and read a provider
# bound to someone ELSE's — possibly already-closed — loop: a deterministic
# every-second-call flake turned into a probabilistic, load-dependent one,
# not fixed. Confirmed empirically: 6 threads × 20 sequential `asyncio.run`
# calls against one shared instance, with an `asyncio.sleep` standing in for
# the real await gap, produced 95/120 mismatches between the provider bound
# for a call and the one actually read back.
#
# The fix below removes the hand-off entirely — there is no longer any
# instance attribute that one thread resolves and a later expression, on
# a possibly-different thread, trusts is still current. `self._provider` (the
# base `GoogleModel`/`Model` attribute) is now a FIXED TEMPLATE: constructed
# once, in `__init__`, and never reassigned afterward. It backs only the
# handful of reads that are genuinely loop-INDEPENDENT — `system`/`base_url`,
# and the bare `.name`/`.base_url` pydantic-ai's own inherited `count_tokens`/
# usage-metadata code reads directly off `self._provider` — which are
# identical no matter which provider instance answers them, because every
# provider this module ever constructs (`_new_provider()`) is built with the
# exact same arguments (deterministic given the API key). This module does
# NOT override `system`/`base_url`; they stay on the inherited GoogleModel
# implementation, reading the fixed template, by this explicit design choice.
#
# The ONE read that IS loop-affine — `.client`, the actual `google.genai.
# Client` that makes real HTTP requests — is overridden below as a PROPERTY
# that resolves `asyncio.get_running_loop()` → the loop-keyed cache FRESH, AT
# THE MOMENT OF EVERY ACCESS, and returns immediately: no `await`, no
# instance-attribute write, nothing for a concurrent thread to race against
# in between "resolve" and "use". Every inherited method (`request`,
# `count_tokens`, `request_stream`, `_generate_content`, ...) reads
# `self.client` through ordinary Python attribute lookup, so this one
# override covers every one of them automatically — none of `request`/
# `count_tokens`/`request_stream` need to be (and are no longer) overridden
# themselves. Because there is no shared pointer left to go stale, correctness
# no longer depends on timing: whichever thread/loop happens to be running
# when `.client` is evaluated gets exactly (and only) the provider that
# belongs to it, cached per-loop in a `WeakKeyDictionary` keyed by the loop
# object itself so entries vanish on their own once a throwaway loop is
# garbage-collected (no unbounded growth over a long process's lifetime of
# `run_agent_sync` calls). The one persistent loop that matters most —
# FastAPI's per-process async loop, shared by every `async def` route handler
# for the app's whole lifetime — still gets the same connection-pooling
# benefit the old singleton gave it, since its cache entry is looked up (not
# rebuilt) on every subsequent call. No call site — present or future — has
# to know event loops (or threads) exist.
#
# PROVIDER SWAP (ADR 0030): the same loop affinity holds for the Anthropic SDK —
# `AsyncAnthropic` wraps its own `httpx.AsyncClient` — so the mechanism lives
# in `_LoopSafeProviderMixin` and both concrete models (`_LoopSafeGoogleModel`,
# `_LoopSafeAnthropicModel`) inherit it. Each subclass names only how to build
# a fresh provider; `AnthropicModel.client`, like `GoogleModel.client`, is a
# plain read of `self._provider.client`, so the one property override covers
# every inherited request path on both.
class _LoopSafeProviderMixin:
    """`.client` resolves the provider bound to the CURRENTLY RUNNING event
    loop at every access, instead of caching one on `self`. See the
    module-level comment above for why (#354/#436, and the fix-round-1
    correction to this class's first version, which cached a shared
    `self._provider` pointer and raced under concurrent requests).

    Mix in BEFORE the concrete pydantic-ai model so this `client` property
    wins the MRO, and call `_init_loop_safety()` after the model's own
    `__init__` (whose `provider=` becomes the fixed template)."""

    _provider: Any

    def _new_loop_provider(self) -> Any:  # pragma: no cover - abstract
        raise NotImplementedError

    def _init_loop_safety(self) -> None:
        self._loop_providers: "weakref.WeakKeyDictionary[Any, Any]" = (
            weakref.WeakKeyDictionary()
        )
        self._loop_providers_lock = threading.Lock()

    def _provider_for_current_loop(self) -> Any:
        """The provider bound to whichever event loop is running RIGHT NOW,
        creating one on first use. Deliberately never cached anywhere on
        `self` — every caller (`client`, `__aenter__`, `__aexit__`) calls
        this at the exact point of use, so the result can never go stale by
        the time it's read. Caching it into an instance attribute between
        "resolve" and "use" is exactly the fix-round-1 bug this replaces."""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            # No running loop — a plain sync caller inspecting `.client`
            # outside any asyncio context (e.g. a test). Nothing can race
            # this: with no loop, there is no concurrent request in flight
            # to collide with. The fixed template is a safe, deterministic
            # fallback.
            return self._provider
        with self._loop_providers_lock:
            provider = self._loop_providers.get(loop)
            if provider is None:
                provider = self._new_loop_provider()
                self._loop_providers[loop] = provider
            return provider

    @property
    def client(self):
        return self._provider_for_current_loop().client

    async def __aenter__(self):
        provider = self._provider_for_current_loop()
        await provider.__aenter__()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        provider = self._provider_for_current_loop()
        await provider.__aexit__(exc_type, exc_val, exc_tb)


class _LoopSafeGoogleModel(_LoopSafeProviderMixin, GoogleModel):
    """A `GoogleModel` with a per-event-loop provider (see the mixin)."""

    def __init__(self, model_name: str, *, settings: GoogleModelSettings | None = None) -> None:
        # `provider=` here becomes a fixed TEMPLATE (see module comment) —
        # constructed once, never reassigned, read only for loop-independent
        # metadata. It must NEVER be read for `.client` — that's what the
        # mixin's property override is for.
        super().__init__(model_name, provider=_new_provider(), settings=settings)
        self._init_loop_safety()

    def _new_loop_provider(self) -> GoogleProvider:
        # Module-level lookup at call time, so a test that patches
        # `_providers._new_provider` after construction still takes effect.
        return _new_provider()


class _LoopSafeAnthropicModel(_LoopSafeProviderMixin, AnthropicModel):
    """An `AnthropicModel` with a per-event-loop provider (see the mixin) and
    the Claude 5.x profile from `_anthropic_profile`."""

    def __init__(
        self, model_name: str, *, settings: AnthropicModelSettings | None = None
    ) -> None:
        super().__init__(
            model_name,
            provider=_new_anthropic_provider(),
            profile=_anthropic_profile(model_name),
            settings=settings,
        )
        self._init_loop_safety()

    def _new_loop_provider(self) -> AnthropicProvider:
        return _new_anthropic_provider()

    def prepare_request(self, model_settings, model_request_parameters):
        # Resolve the 'auto' output mode to the profile default BEFORE
        # AnthropicModel.prepare_request runs. pydantic-ai 1.107 only marks a
        # native output schema strict (→ `additionalProperties: false`,
        # unsupported constraints moved into descriptions) when the mode is
        # ALREADY 'native' on entry; a profile-default 'native' is resolved
        # later, in the base class, so the schema went out non-strict and
        # Claude 400'd every structured call ("additionalProperties must be
        # explicitly set to false"). Explicit `NativeOutput(...)` never hit
        # this, which is why upstream only exercises it through our profile.
        return super().prepare_request(
            model_settings,
            model_request_parameters.with_default_output_mode(
                self.profile.default_structured_output_mode
            ),
        )


# ── Test seam: SAPLING_MODEL_MODE (#391) ───────────────────────────────────
#
# `model_for` is the single construction point for every agent's model, so it
# is the only place a deterministic model can be swapped in without stubbing
# whole agent objects (which leaves the real prompt/tool/output wiring
# untested). Modes:
#
#   real     — the slot's provider model (Anthropic or Google, by model name).
#              The production default; an unset/empty var is real, so nothing
#              about the deployed path or the hermetic unit lane changes.
#   function — pydantic-ai FunctionModel, driven by a per-task handler a test
#              registers via `register_function_handler`. Scripted tool calls
#              run through the REAL tool registration, arg-schema validation,
#              and retry loop.
#   cassette — record/replay from tests/evals. Reserved here (issue #391 scope)
#              but not yet built; raises rather than silently falling through.
#
# Why this sits ABOVE the transport guard (#379): a FunctionModel never builds a
# provider request, so a function-mode run touches neither patched transport
# (google-genai's `BaseApiClient`, anthropic's `AsyncAPIClient`/`SyncAPIClient`)
# and needs no hermetic-guard exemption. If a change ever makes
# function mode reach the transport, `test_function_mode_rides_above_transport_
# guard` fails — that is the design invariant, not an accident.

# task -> handler(messages, info) -> ModelResponse. Consulted ONLY in function
# mode (off by default), so it can never affect production or the default lane.
FunctionModelHandler = Callable[
    ["list[ModelMessage]", "AgentInfo"], "ModelResponse"
]
_FUNCTION_HANDLERS: dict[str, FunctionModelHandler] = {}

# Streamed-replay pacing (#356). 0 = off: text parts replay as one whole
# delta each, exactly the pre-pacing behavior. When a handlers module opts
# in (set_function_stream_delay_ms), _stream_dispatch re-chunks text into
# _FUNCTION_STREAM_CHUNK_CHARS-sized deltas with this delay between them, so
# browser journeys have a real mid-stream window to act in (Stop a turn,
# switch sessions). Only the streamed lane paces; the JSON lane and the
# joined stream text stay byte-identical to the handler's constant.
_FUNCTION_STREAM_DELAY_MS = 0.0
_FUNCTION_STREAM_CHUNK_CHARS = 24


def set_function_stream_delay_ms(ms: float) -> None:
    """Opt the function-mode STREAMED replay into pacing (see the comment on
    _FUNCTION_STREAM_DELAY_MS above). Called by boot-time handler modules
    (agents/function_handlers_e2e.py) rather than wired to another lane env
    var; `clear_function_handlers()` resets it so in-process tests always
    start unpaced."""
    global _FUNCTION_STREAM_DELAY_MS
    _FUNCTION_STREAM_DELAY_MS = max(0.0, float(ms))


def function_stream_delay_ms() -> float:
    """Public read of the streamed-replay pacing knob (tests pin it)."""
    return _FUNCTION_STREAM_DELAY_MS


class UnregisteredHandlerError(LookupError):
    """Raised by the function-mode dispatch when a task has no registered
    handler (see `_function_model_for`). A dedicated subclass — rather than a
    bare `LookupError` — lets callers that need to distinguish "seam is
    misconfigured for this task" from any other `LookupError`-family bug
    (a stray `KeyError`/`IndexError` deep in agent/response handling) catch
    precisely this one instead of the whole builtin hierarchy (#446 PR
    review: routes/graph.py used to catch bare `LookupError`, which silently
    downgraded unrelated KeyError/IndexError bugs to a 502 instead of letting
    them surface as the generic 500). Keeping `LookupError` as the base class
    preserves any existing code that already catches the builtin type."""


def _model_mode() -> str:
    """The active model mode. Unset/blank → 'real'. Normalized for stray
    case/whitespace so a CI or shell-exported value isn't brittle."""
    return (os.getenv("SAPLING_MODEL_MODE") or "real").strip().lower()


def model_mode() -> str:
    """Public read of the active SAPLING_MODEL_MODE, for call sites outside
    `agents/` that need to gate on the same seam but don't want a `Model`.

    `_model_mode` stays private to this module for `model_for`'s internal
    dispatch. This is the one sanctioned way a non-agent module reaches the
    seam: `services/rag_service.py` builds a raw `google.genai.Client` for
    embeddings (predating #391), so it gates on `model_mode() == "real"`
    rather than importing the private name across a package boundary (#439).
    Callers of rag_service — `routes/documents.py`'s indexing among them —
    inherit that gate rather than repeating it (#628).
    """
    return _model_mode()


def register_function_handler(task: AgentTask, handler: FunctionModelHandler) -> None:
    """Register the FunctionModel handler for a task (function mode only).

    The handler has pydantic-ai's FunctionModel signature: it receives the
    request messages and an `AgentInfo` (carrying the agent's registered tools
    and output tools) and returns a `ModelResponse`. Tests use this to script
    tool calls / final output for a specific agent.
    """
    _FUNCTION_HANDLERS[task] = handler


def clear_function_handlers() -> None:
    """Drop all registered handlers and reset the streamed-replay pacing
    knob. Tests call this around each case so process-global registrations
    (and a handlers module's pacing opt-in) never leak between them."""
    global _FUNCTION_STREAM_DELAY_MS
    _FUNCTION_HANDLERS.clear()
    _FUNCTION_STREAM_DELAY_MS = 0.0


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
    import json

    from pydantic_ai.models.function import DeltaToolCall, FunctionModel

    def _resolve_handler() -> FunctionModelHandler:
        handler = _FUNCTION_HANDLERS.get(task)
        if handler is None:
            # Out-of-process runs (E2E uvicorn) register via the env-named
            # module; loaded lazily on the first miss, no-op when unset.
            _load_env_handlers_module()
            handler = _FUNCTION_HANDLERS.get(task)
        if handler is None:
            raise UnregisteredHandlerError(
                f"SAPLING_MODEL_MODE=function but no handler is registered for "
                f"task {task!r}. Call agents._providers.register_function_handler("
                f"{task!r}, ...) before running the agent (or point "
                f"SAPLING_FUNCTION_HANDLERS at a module that does)."
            )
        return handler

    def _dispatch(messages, info):
        return _resolve_handler()(messages, info)

    async def _stream_dispatch(messages, info):
        # Streamed runs (`agent.run_stream_events`, the SSE tutor routes) reuse
        # the SAME registered handler rather than a parallel stream registry:
        # the handler's ModelResponse is replayed as a stream — each text part
        # as one delta, each tool call as a DeltaToolCall — so a task's handler
        # constants stay byte-identical between the JSON and streamed lanes
        # (spec assertions compare against the same E2E_* constants either way).
        #
        # Pacing (#356): when set_function_stream_delay_ms opted this process
        # in, text is re-chunked into small deltas with a sleep between them —
        # a real mid-stream window for browser journeys. The delay is read
        # AFTER _resolve_handler(), which is what imports a boot-time handlers
        # module that sets the knob, so the very first paced stream paces.
        response = _resolve_handler()(messages, info)
        delay_s = _FUNCTION_STREAM_DELAY_MS / 1000.0
        emitted_text = False
        for index, part in enumerate(response.parts):
            kind = getattr(part, "part_kind", "")
            if kind == "text":
                if not part.content:
                    continue
                if delay_s > 0:
                    chunks = [
                        part.content[i : i + _FUNCTION_STREAM_CHUNK_CHARS]
                        for i in range(0, len(part.content), _FUNCTION_STREAM_CHUNK_CHARS)
                    ]
                else:
                    chunks = [part.content]
                for chunk in chunks:
                    if emitted_text and delay_s > 0:
                        await asyncio.sleep(delay_s)
                    emitted_text = True
                    yield chunk
            elif kind == "tool-call":
                args = part.args
                json_args = args if isinstance(args, str) else json.dumps(args or {})
                yield {
                    index: DeltaToolCall(
                        name=part.tool_name,
                        json_args=json_args,
                        tool_call_id=part.tool_call_id,
                    )
                }

    return FunctionModel(
        _dispatch, stream_function=_stream_dispatch, model_name=f"function:{task}"
    )


ProviderName = Literal["anthropic", "google"]


def _bare_model_name(name: str) -> str:
    """Drop an optional `provider:` qualifier (`anthropic:claude-haiku-5-5`)."""
    return name.rsplit(":", 1)[-1].strip()


def provider_for_model(name: str) -> ProviderName:
    """Which provider serves a model name: `claude-*` → anthropic,
    `gemini-*` → google. Anything else is a config error and raises — a typo'd
    SAPLING_MODEL_* must fail loudly, not silently route to some default."""
    bare = _bare_model_name(name)
    if bare.startswith("claude-"):
        return "anthropic"
    if bare.startswith("gemini-"):
        return "google"
    raise ValueError(
        f"cannot infer the provider for model {name!r}: expected a 'claude-*' "
        f"(Anthropic) or 'gemini-*' (Google) model name."
    )


def model_name_for(task: AgentTask) -> str:
    """The model *name* configured for a task, without building a Model.

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


def provider_model(name: str, *, task: AgentTask | None = None) -> "Model":
    """A real, loop-safe model for a bare model name, on the provider the name
    implies, carrying `task`'s per-provider default settings when given.

    Bypasses the per-task `_DEFAULTS`/env-override resolution `model_for`
    does — it is the per-request override path (the tutor/quiz fast/smart
    preference, the health probe) — and, like those callers always did,
    does NOT consult SAPLING_MODEL_MODE: callers gate on `model_mode()`
    first (#391/#392).
    """
    bare = _bare_model_name(name)
    if provider_for_model(bare) == "anthropic":
        return _LoopSafeAnthropicModel(bare, settings=_anthropic_settings_for(task))
    return _LoopSafeGoogleModel(bare, settings=_google_settings_for(task))


def model_for(task: AgentTask) -> "Model":
    """Return the configured model for a given pipeline task.

    Dispatches on SAPLING_MODEL_MODE (default 'real'). In real mode, reads the
    per-task SAPLING_MODEL_<TASK_UPPER> override first (ADR 0008), else the
    per-task default, and returns a loop-safe Anthropic or Google model
    (#354/#436 — see `_LoopSafeProviderMixin`) for whichever provider that
    name implies (ADR 0030), so the caller never has to think about which
    event loop it ends up running on. In function mode, returns a
    FunctionModel (see the seam notes above).
    """
    mode = _model_mode()
    if mode == "real":
        return provider_model(model_name_for(task), task=task)
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
        f"silent fall-through to real (which would bill a live provider)."
    )

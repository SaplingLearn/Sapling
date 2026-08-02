"""The SAPLING_MODEL_MODE test seam (#391).

`agents/_providers.py::model_for` is the single place every agent's model is
built. Until #391 it returned only a `GoogleModel`, so there was no way to
substitute a deterministic model without stubbing whole agent objects — which
means today's agent tests never exercise the real prompt, tool registration, or
output-schema wiring. This module pins the seam:

  - `SAPLING_MODEL_MODE=real` (the default) → `GoogleModel`. Production and the
    ~976 hermetic unit tests are unchanged: a missing/empty var is `real`.
  - `SAPLING_MODEL_MODE=function` → pydantic-ai `FunctionModel`, driven by a
    per-task handler tests register. Scripted tool calls flow through the REAL
    tool registration, arg-schema validation, and retry loop.

The load-bearing property (issue #391, and the #379 hermetic-guard comment): the
`FunctionModel` substitutes **above** the google-genai transport. A real agent
run in `function` mode must NOT trip the autouse `_hermetic_llm_transport` guard
and needs no exemption marker — because `FunctionModel` never constructs a
`google.genai` request. `test_function_mode_rides_above_transport_guard` asserts
exactly that, so a future refactor that accidentally routes function-mode back
through Gemini fails loudly here.
"""
from __future__ import annotations

import pytest
from pydantic_ai.models.function import FunctionModel
from pydantic_ai.models.google import GoogleModel
from pydantic_ai.messages import ModelResponse, TextPart, ToolCallPart

from agents._providers import (
    clear_function_handlers,
    model_for,
    register_function_handler,
)
from agents.classifier import DocumentClassification, classifier_agent
from agents.deps import SaplingDeps
from agents.note_chat import note_chat_agent


@pytest.fixture(autouse=True)
def _clean_function_registry():
    """Function-mode handlers are process-global; reset around every test so
    registrations never leak between tests (they can only matter in function
    mode, which is off by default, but keep the seam pristine regardless)."""
    clear_function_handlers()
    yield
    clear_function_handlers()


def _deps() -> SaplingDeps:
    return SaplingDeps(
        user_id="seam-user",
        course_id="seam-course",
        supabase=None,
        request_id="seam-req",
        session_id="seam-note",
    )


# ── Mode dispatch ─────────────────────────────────────────────────────────


def test_default_mode_returns_google_model(monkeypatch):
    """No SAPLING_MODEL_MODE set → real GoogleModel. This is the production
    default; the ~976 hermetic tests rely on it staying unchanged."""
    monkeypatch.delenv("SAPLING_MODEL_MODE", raising=False)
    assert isinstance(model_for("classifier"), GoogleModel)


def test_mode_real_explicit_returns_google_model(monkeypatch):
    monkeypatch.setenv("SAPLING_MODEL_MODE", "real")
    assert isinstance(model_for("quiz"), GoogleModel)


def test_mode_is_case_and_whitespace_insensitive(monkeypatch):
    """Env vars picked up from shells/CI often carry stray case/whitespace;
    the mode read must not be brittle to that."""
    monkeypatch.setenv("SAPLING_MODEL_MODE", "  Function  ")
    register_function_handler("classifier", lambda m, i: ModelResponse(parts=[TextPart(content="x")]))
    assert isinstance(model_for("classifier"), FunctionModel)


def test_mode_function_returns_function_model(monkeypatch):
    monkeypatch.setenv("SAPLING_MODEL_MODE", "function")
    register_function_handler("classifier", lambda m, i: ModelResponse(parts=[TextPart(content="x")]))
    assert isinstance(model_for("classifier"), FunctionModel)


def test_real_mode_still_honors_per_task_env_override(monkeypatch):
    """SAPLING_MODEL_MODE must not clobber the existing per-task model
    override (ADR 0008) — real mode still reads SAPLING_MODEL_<TASK>."""
    monkeypatch.setenv("SAPLING_MODEL_MODE", "real")
    monkeypatch.setenv("SAPLING_MODEL_QUIZ", "gemini-2.5-pro")
    m = model_for("quiz")
    assert isinstance(m, GoogleModel)
    assert m.model_name == "gemini-2.5-pro"


def test_unknown_mode_fails_loudly(monkeypatch):
    """An unrecognized mode is a configuration error, not a silent fall-through
    to real — a typo'd SAPLING_MODEL_MODE must never quietly bill Gemini."""
    monkeypatch.setenv("SAPLING_MODEL_MODE", "functon")
    with pytest.raises(ValueError, match="SAPLING_MODEL_MODE"):
        model_for("classifier")


def test_cassette_mode_is_declared_but_not_yet_implemented(monkeypatch):
    """`cassette` is a recognized mode name (issue #391 scope) but replay is a
    follow-up; it must raise a pointed NotImplementedError, not dial out."""
    monkeypatch.setenv("SAPLING_MODEL_MODE", "cassette")
    with pytest.raises(NotImplementedError, match="cassette"):
        model_for("classifier")


# ── Registry ──────────────────────────────────────────────────────────────


def test_function_mode_without_registered_handler_raises_on_run(monkeypatch):
    """A FunctionModel is returned eagerly, but running an agent whose task has
    no registered handler must fail with a pointed error (naming the task), not
    hang or dial out."""
    monkeypatch.setenv("SAPLING_MODEL_MODE", "function")
    with classifier_agent.override(model=model_for("classifier")):
        with pytest.raises(Exception) as exc:
            classifier_agent.run_sync("some document", deps=_deps())
    assert "classifier" in str(exc.value)


# ── Acceptance criterion: real agent driven by FunctionModel, asserting on
#    tool-call arguments (issue #391). ─────────────────────────────────────


def test_real_agent_driven_by_function_model_asserts_tool_call_args(monkeypatch):
    """AC: an integration-style test drives a REAL agent with FunctionModel and
    asserts on tool-call arguments.

    Uses `note_chat_agent` — one of the agents #391 unblocks — because its tools
    take LLM-chosen arguments (`search_course_materials(query, limit)`), unlike
    the arg-less quiz/graph readers. The scripted tool call flows through real
    tool registration and pydantic arg-schema validation before the tool body
    runs, so recording the query the tool body actually receives proves the
    whole wiring executed, not just that the model emitted a part.
    """
    monkeypatch.setenv("SAPLING_MODEL_MODE", "function")

    # Spy on the tool body: records the args the wrapper passes AFTER pydantic
    # has validated the model's tool-call arguments against the real schema.
    received: dict = {}

    async def _spy_search(course_id, query, limit=5, *, user_id):
        received.update(course_id=course_id, query=query, limit=limit, user_id=user_id)
        return []

    monkeypatch.setattr(
        "agents.tools.chat_context.search_course_materials", _spy_search
    )

    seen_tools: dict = {}
    calls = {"n": 0}

    def handler(messages, info) -> ModelResponse:
        # Tool registration ran for real: the agent's function tools are visible.
        seen_tools["names"] = sorted(t.name for t in info.function_tools)
        calls["n"] += 1
        if calls["n"] == 1:
            # First turn: script a call to a real function tool with real args.
            # The tool is registered under its prompt-facing name (#135:
            # note_chat.py wires Tool(search_course_materials_tool,
            # name="search_course_materials") so the wire name matches the
            # system prompt's `search_course_materials`).
            return ModelResponse(
                parts=[
                    ToolCallPart(
                        tool_name="search_course_materials",
                        args={"query": "gradient descent", "limit": 3},
                    )
                ]
            )
        # Second turn (after the tool returns): produce the freeform answer.
        return ModelResponse(
            parts=[TextPart(content="Gradient descent steps downhill to cut loss.")]
        )

    register_function_handler("note_chat", handler)

    with note_chat_agent.override(model=model_for("note_chat")):
        result = note_chat_agent.run_sync("How does gradient descent work?", deps=_deps())

    # The real tools were registered (registration ran through the agent).
    assert "search_course_materials" in seen_tools["names"]
    assert "read_active_note" in seen_tools["names"]
    # The LLM-chosen tool-call arguments were schema-validated and dispatched to
    # the real tool body with the deps-scoped user/course fields injected.
    assert received["query"] == "gradient descent"
    assert received["limit"] == 3
    assert received["user_id"] == "seam-user"
    assert received["course_id"] == "seam-course"
    # The agent looped past the tool call to a final answer.
    assert "gradient descent" in result.output.lower()
    assert calls["n"] == 2


def test_function_model_output_tool_args_validate_and_retry_loop_runs(monkeypatch):
    """The retry loop runs for real: a first scripted output with an out-of-range
    field is rejected by the real DocumentClassification schema, the agent asks
    the model to retry, and the corrected second response is accepted."""
    monkeypatch.setenv("SAPLING_MODEL_MODE", "function")
    calls = {"n": 0}

    def handler(messages, info) -> ModelResponse:
        calls["n"] += 1
        out_tool = info.output_tools[0].name
        if calls["n"] == 1:
            # confidence=5.0 violates the real ge=0/le=1 schema → ModelRetry.
            return ModelResponse(
                parts=[
                    ToolCallPart(
                        tool_name=out_tool,
                        args={
                            "category": "syllabus",
                            "is_syllabus": True,
                            "confidence": 5.0,
                            "rationale": "schedule + grading rubric present",
                        },
                    )
                ]
            )
        return ModelResponse(
            parts=[
                ToolCallPart(
                    tool_name=out_tool,
                    args={
                        "category": "syllabus",
                        "is_syllabus": True,
                        "confidence": 0.9,
                        "rationale": "schedule + grading rubric present",
                    },
                )
            ]
        )

    register_function_handler("classifier", handler)
    with classifier_agent.override(model=model_for("classifier")):
        result = classifier_agent.run_sync("CS101 syllabus", deps=_deps())

    assert isinstance(result.output, DocumentClassification)
    assert result.output.confidence == 0.9
    assert calls["n"] == 2  # the retry actually happened


def test_tutor_graph_read_scripted_through_real_registration(monkeypatch):
    """#149 seam test (mirrors the note_chat AC test above): a scripted
    `read_graph_neighborhood` ToolCallPart flows through the REAL chat-tutor
    tool registration + pydantic arg-schema validation, the spied tool body
    receives the LLM-chosen concepts/limit with the deps-injected user/course
    ids, and the agent loops to a second-turn final text."""
    from agents.chat_tutor import socratic_agent
    from agents.tools.graph_read import ConceptNode, GraphNeighborhood

    monkeypatch.setenv("SAPLING_MODEL_MODE", "function")

    received: dict = {}

    async def _spy_hood(user_id, course_id, concepts, *, limit=20):
        received.update(
            user_id=user_id, course_id=course_id,
            concepts=list(concepts), limit=limit,
        )
        return GraphNeighborhood(
            concepts=[
                ConceptNode(
                    concept_name="Limits", mastery=0.7, mastery_tier="learning"
                )
            ],
            edges=[],
            truncated=False,
        )

    # Patch the pure function; deps.retrieval is None here, so the wrapper
    # resolves SupabaseRetrieval, which delegates to exactly this seam.
    monkeypatch.setattr(
        "agents.tools.graph_read.read_graph_neighborhood", _spy_hood
    )

    seen_tools: dict = {}
    calls = {"n": 0}

    def handler(messages, info) -> ModelResponse:
        seen_tools["names"] = sorted(t.name for t in info.function_tools)
        calls["n"] += 1
        if calls["n"] == 1:
            return ModelResponse(
                parts=[
                    ToolCallPart(
                        tool_name="read_graph_neighborhood",
                        args={"concepts": ["limits"], "limit": 5},
                    )
                ]
            )
        return ModelResponse(
            parts=[TextPart(content="Your grasp of Limits is coming along — what does a limit describe?")]
        )

    register_function_handler("chat_tutor", handler)

    with socratic_agent.override(model=model_for("chat_tutor")):
        result = socratic_agent.run_sync("How solid are my limits?", deps=_deps())

    # Both #149 read tools are registered under their prompt-facing names.
    assert "read_graph_neighborhood" in seen_tools["names"]
    assert "read_concepts_for_user" in seen_tools["names"]
    # Schema-validated args reached the real body with deps-injected ids.
    assert received == {
        "user_id": "seam-user",
        "course_id": "seam-course",
        "concepts": ["limits"],
        "limit": 5,
    }
    # Second turn produced the final text; exactly one tool round trip.
    assert "Limits" in result.output
    assert calls["n"] == 2


# ── The load-bearing property: function mode is ABOVE the transport guard. ──


def test_hermetic_transport_guard_is_installed_in_this_lane():
    """Sanity: this test carries no exemption marker, so the autouse
    `_hermetic_llm_transport` guard (#379) must be patched over the google-genai
    transport. If this ever fails, the next test's 'no egress' claim is vacuous.
    """
    from google.genai import _api_client as genai_api_client

    assert getattr(genai_api_client.BaseApiClient.request, "_sapling_llm_guard", False)


def test_function_mode_rides_above_transport_guard(monkeypatch):
    """The core #391 requirement: a real agent runs to completion in function
    mode in the DEFAULT hermetic lane (no e2e_staging/integration/live_llm
    marker). It does not trip UnstubbedLLMEgress because FunctionModel never
    constructs a google-genai request — the substitution is above the transport,
    not a hole punched through the guard.
    """
    monkeypatch.setenv("SAPLING_MODEL_MODE", "function")

    def handler(messages, info) -> ModelResponse:
        out_tool = info.output_tools[0].name
        return ModelResponse(
            parts=[
                ToolCallPart(
                    tool_name=out_tool,
                    args={
                        "category": "lecture_notes",
                        "is_syllabus": False,
                        "confidence": 0.8,
                        "rationale": "narrative notes, no schedule",
                    },
                )
            ]
        )

    register_function_handler("classifier", handler)
    with classifier_agent.override(model=model_for("classifier")):
        result = classifier_agent.run_sync("week 1 lecture notes", deps=_deps())
    assert result.output.category == "lecture_notes"


def test_default_real_mode_agent_run_still_trips_the_guard():
    """Counter-check: without the function seam, a real agent run in the hermetic
    lane DOES hit the guard. Proves the guard is genuinely in the path and that
    function mode (above) is what avoids it — not some unrelated exemption.

    UnstubbedLLMEgress subclasses RuntimeError; we match on the message rather
    than the class so this doesn't depend on whether pytest imported the conftest
    as `conftest` or `tests.conftest` (they are distinct module objects, so the
    class identities differ)."""
    with pytest.raises(RuntimeError, match="unstubbed LLM egress"):
        classifier_agent.run_sync("anything", deps=_deps())


# ── Streamed runs (#349): the seam serves run_stream_events too ───────────


def test_function_mode_streams_text_from_the_same_handler(monkeypatch):
    """The SSE tutor routes drive agents via `run_stream_events`. A streamed
    run in function mode must be served by the SAME registered handler as a
    JSON run — its text replayed as stream deltas — so spec assertions can
    compare both lanes against one E2E_* constant. Before #349 the seam's
    FunctionModel had no `stream_function`, so every streamed turn errored
    into the legacy fallback and the streamed path was untestable."""
    import asyncio

    monkeypatch.setenv("SAPLING_MODEL_MODE", "function")
    register_function_handler(
        "note_chat",
        lambda m, i: ModelResponse(parts=[TextPart(content="streamed seam reply")]),
    )

    async def collect() -> tuple[list[str], str | None]:
        deltas: list[str] = []
        final: str | None = None
        with note_chat_agent.override(model=model_for("note_chat")):
            async for event in note_chat_agent.run_stream_events(
                "hello", deps=_deps()
            ):
                cls_name = type(event).__name__
                if cls_name == "PartStartEvent":
                    part = getattr(event, "part", None)
                    if getattr(part, "part_kind", None) == "text" and part.content:
                        deltas.append(part.content)
                elif cls_name == "PartDeltaEvent":
                    delta = getattr(event, "delta", None)
                    if getattr(delta, "part_delta_kind", None) == "text":
                        deltas.append(delta.content_delta)
                elif cls_name == "AgentRunResultEvent":
                    final = event.result.output
        return deltas, final

    deltas, final = asyncio.run(collect())
    assert "".join(deltas) == "streamed seam reply"
    assert final == "streamed seam reply"


def test_function_mode_streams_scripted_tool_calls(monkeypatch):
    """A streamed function-mode run must also replay scripted TOOL CALLS (as
    DeltaToolCall chunks) through the real tool-registration/validation loop —
    the streamed twin of the JSON-lane acceptance test above."""
    import asyncio

    monkeypatch.setenv("SAPLING_MODEL_MODE", "function")

    received: dict = {}

    async def _spy_search(course_id, query, limit=5, *, user_id):
        received.update(query=query, limit=limit)
        return []

    monkeypatch.setattr(
        "agents.tools.chat_context.search_course_materials", _spy_search
    )

    calls = {"n": 0}

    def handler(messages, info) -> ModelResponse:
        calls["n"] += 1
        if calls["n"] == 1:
            return ModelResponse(
                parts=[
                    ToolCallPart(
                        tool_name="search_course_materials",
                        args={"query": "eigenvalues", "limit": 2},
                    )
                ]
            )
        return ModelResponse(parts=[TextPart(content="used the tool")])

    register_function_handler("note_chat", handler)

    async def run() -> tuple[str | None, list[str]]:
        final: str | None = None
        tool_events: list[str] = []
        with note_chat_agent.override(model=model_for("note_chat")):
            async for event in note_chat_agent.run_stream_events(
                "find eigenvalues", deps=_deps()
            ):
                cls_name = type(event).__name__
                if cls_name == "FunctionToolCallEvent":
                    tool_events.append(cls_name)
                elif cls_name == "AgentRunResultEvent":
                    final = event.result.output
        return final, tool_events

    final, tool_events = asyncio.run(run())
    # The scripted call streamed as a real mid-run tool event, was
    # schema-validated, and dispatched to the real (spied) tool body.
    assert tool_events == ["FunctionToolCallEvent"]
    assert received == {"query": "eigenvalues", "limit": 2}
    assert final == "used the tool"
    assert calls["n"] == 2


# ── Streamed-replay pacing (#356) ─────────────────────────────────────────
#
# Browser journeys that act MID-STREAM (Stop a turn, switch sessions while
# streaming) need a real time window between deltas — a FunctionModel that
# replays its whole reply in one instant delta makes those journeys
# unwritable. `set_function_stream_delay_ms` paces ONLY the streamed replay:
# text is re-chunked into small deltas with a sleep between them, while the
# JSON lane (and the joined stream text) stays byte-identical to the
# handler's constant. Default is 0 — no pacing, single whole-part delta —
# so nothing changes for existing tests or the hermetic lane unless a
# handlers module opts in (agents/function_handlers_e2e.py does).


async def _collect_stream_deltas(agent, task, prompt) -> tuple[list[str], str | None]:
    deltas: list[str] = []
    final: str | None = None
    with agent.override(model=model_for(task)):
        async for event in agent.run_stream_events(prompt, deps=_deps()):
            cls_name = type(event).__name__
            if cls_name == "PartStartEvent":
                part = getattr(event, "part", None)
                if getattr(part, "part_kind", None) == "text" and part.content:
                    deltas.append(part.content)
            elif cls_name == "PartDeltaEvent":
                delta = getattr(event, "delta", None)
                if getattr(delta, "part_delta_kind", None) == "text":
                    deltas.append(delta.content_delta)
            elif cls_name == "AgentRunResultEvent":
                final = event.result.output
    return deltas, final


def test_stream_pacing_chunks_text_between_sleeps(monkeypatch):
    """With a pacing delay set, streamed text replays as multiple small
    deltas (24-char chunks) whose join is byte-identical to the handler's
    reply, and the run takes at least (chunks - 1) * delay of wall clock —
    the mid-stream window the #356 journeys act inside."""
    import asyncio
    import time

    from agents._providers import function_stream_delay_ms, set_function_stream_delay_ms

    monkeypatch.setenv("SAPLING_MODEL_MODE", "function")
    reply = "x" * 60  # 3 chunks at 24 chars
    register_function_handler(
        "note_chat", lambda m, i: ModelResponse(parts=[TextPart(content=reply)])
    )
    set_function_stream_delay_ms(25)
    assert function_stream_delay_ms() == 25

    start = time.monotonic()
    deltas, final = asyncio.run(_collect_stream_deltas(note_chat_agent, "note_chat", "hi"))
    elapsed = time.monotonic() - start

    assert deltas == ["x" * 24, "x" * 24, "x" * 12]
    assert final == reply  # joined text identical to the JSON-lane constant
    # Two inter-chunk sleeps of 25ms each give a hard lower bound; asserting
    # only the lower bound keeps this stable on a loaded CI runner.
    assert elapsed >= 0.05


def test_stream_pacing_defaults_off_and_resets_with_clear(monkeypatch):
    """Default is a single whole-part delta (no pacing), and
    clear_function_handlers() — which every seam test fixture already calls —
    also resets a previously-set delay, so pacing can never leak between
    tests the way a bare module global would."""
    import asyncio

    from agents._providers import function_stream_delay_ms, set_function_stream_delay_ms

    monkeypatch.setenv("SAPLING_MODEL_MODE", "function")
    set_function_stream_delay_ms(150)
    clear_function_handlers()
    assert function_stream_delay_ms() == 0

    reply = "y" * 60
    register_function_handler(
        "note_chat", lambda m, i: ModelResponse(parts=[TextPart(content=reply)])
    )
    deltas, final = asyncio.run(_collect_stream_deltas(note_chat_agent, "note_chat", "hi"))
    assert deltas == [reply]  # one delta: the whole part, exactly as before
    assert final == reply

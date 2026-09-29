"""Boot-time function-handler registration for the E2E lane (#392).

The #391 seam registers handlers in-process; the browser E2E lane boots the
backend as a separate uvicorn process, so #392 adds `SAPLING_FUNCTION_HANDLERS`
— a module path imported lazily (once) on the first dispatch miss — plus
`agents/function_handlers_e2e.py`, the module the E2E stack points it at.

Also pins the route-side gap that made the env module necessary but not
sufficient: `routes.learn._resolve_model_pref` used to build a live
GoogleModel for the browser's fast/smart preference, silently bypassing the
seam on every tutor turn (the ModelToggle default is "fast", so the browser
ALWAYS sends a pref). In any non-real mode it must return None.
"""

from __future__ import annotations

import sys

import pytest
from pydantic_ai.models.google import GoogleModel

import agents._providers as providers
from agents._providers import clear_function_handlers, model_for
from agents.chat_tutor import socratic_agent
from agents.classifier import classifier_agent
from agents.concept_describe import build_message, concept_describe_agent
from agents.concept_scan import concept_scan_agent
from agents.deps import SaplingDeps
from agents.note_chat import note_chat_agent
from agents.note_concepts import note_concepts_agent
from agents.note_summary import note_summary_agent
from agents.quiz import quiz_agent
from agents.summary import summary_agent
from routes.learn import _resolve_model_pref
from routes.quiz import (
    _agent_question_to_wire,
    _resolve_model_pref as _resolve_quiz_model_pref,
)


@pytest.fixture(autouse=True)
def _clean_function_registry(monkeypatch):
    """Reset the process-global registry AND the once-only env-module latch so
    each case observes a cold seam (same posture as test_model_mode_seam.py)."""
    clear_function_handlers()
    monkeypatch.setattr(providers, "_ENV_HANDLERS_LOADED", False)
    sys.modules.pop("agents.function_handlers_e2e", None)
    yield
    clear_function_handlers()
    sys.modules.pop("agents.function_handlers_e2e", None)


def _deps() -> SaplingDeps:
    return SaplingDeps(
        user_id="e2e-user",
        course_id="e2e-course",
        supabase=None,
        request_id="e2e-req",
        session_id="e2e-session",
    )


# ── SAPLING_FUNCTION_HANDLERS autoload ────────────────────────────────────


def test_env_module_registers_chat_tutor_handler_on_dispatch(monkeypatch):
    """The full E2E-boot contract: function mode + the env-named module give a
    real chat_tutor agent run the module's fixed deterministic reply — through
    the real agent wiring, with no handler registered by the test itself."""
    monkeypatch.setenv("SAPLING_MODEL_MODE", "function")
    monkeypatch.setenv(
        "SAPLING_FUNCTION_HANDLERS", "agents.function_handlers_e2e"
    )

    with socratic_agent.override(model=model_for("chat_tutor")):
        result = socratic_agent.run_sync("What is recursion?", deps=_deps())

    from agents.function_handlers_e2e import E2E_TUTOR_REPLY

    assert result.output == E2E_TUTOR_REPLY


def test_unset_env_module_still_raises_pointed_lookup_error(monkeypatch):
    """Without SAPLING_FUNCTION_HANDLERS the #391 posture is unchanged: a
    missing handler is a loud LookupError naming the task — the autoload hook
    must not soften it."""
    monkeypatch.setenv("SAPLING_MODEL_MODE", "function")
    monkeypatch.delenv("SAPLING_FUNCTION_HANDLERS", raising=False)

    with socratic_agent.override(model=model_for("chat_tutor")):
        with pytest.raises(Exception) as exc:
            socratic_agent.run_sync("What is recursion?", deps=_deps())
    assert "chat_tutor" in str(exc.value)


def test_bad_env_module_path_fails_loudly(monkeypatch):
    """A typo'd module path must surface as ImportError at first dispatch —
    a broken E2E boot fails the run rather than quietly running handler-less."""
    monkeypatch.setenv("SAPLING_MODEL_MODE", "function")
    monkeypatch.setenv("SAPLING_FUNCTION_HANDLERS", "agents.no_such_module")

    with socratic_agent.override(model=model_for("chat_tutor")):
        with pytest.raises(Exception) as exc:
            socratic_agent.run_sync("What is recursion?", deps=_deps())
    assert "no_such_module" in str(exc.value)


def test_bad_env_module_path_fails_loudly_on_every_dispatch(monkeypatch):
    """Regression (#434 review): the latch must not cache a FAILED import as
    loaded. Two dispatches within one latch lifetime (no fixture reset in
    between) must BOTH surface the module path — the original code latched
    before importing, so the second dispatch silently downgraded to the
    generic LookupError and the broken-boot story disappeared."""
    monkeypatch.setenv("SAPLING_MODEL_MODE", "function")
    monkeypatch.setenv("SAPLING_FUNCTION_HANDLERS", "agents.no_such_module")

    with socratic_agent.override(model=model_for("chat_tutor")):
        for attempt in (1, 2):
            with pytest.raises(Exception) as exc:
                socratic_agent.run_sync("What is recursion?", deps=_deps())
            assert "no_such_module" in str(exc.value), (
                f"dispatch {attempt} lost the bad-module story: {exc.value}"
            )


def test_explicit_registration_wins_over_env_module(monkeypatch):
    """The env module is a dispatch-miss fallback only: a handler registered
    in-process (the pytest pattern) is never shadowed by it."""
    from pydantic_ai.messages import ModelResponse, TextPart

    monkeypatch.setenv("SAPLING_MODEL_MODE", "function")
    monkeypatch.setenv(
        "SAPLING_FUNCTION_HANDLERS", "agents.function_handlers_e2e"
    )
    providers.register_function_handler(
        "chat_tutor",
        lambda m, i: ModelResponse(parts=[TextPart(content="explicit wins")]),
    )

    with socratic_agent.override(model=model_for("chat_tutor")):
        result = socratic_agent.run_sync("What is recursion?", deps=_deps())
    assert result.output == "explicit wins"


def test_start_session_json_route_serves_tutor_handler_in_function_mode(monkeypatch):
    """#151a: the JSON /start-session route now runs chat_tutor_agent (task
    "chat_tutor") — so in function mode the SAME env-registered chat_tutor
    handler covers the session opener by task dispatch, with no new handler
    registration. Route-level: the greeting the route returns IS
    E2E_TUTOR_REPLY (the constant frontend/e2e/tutor.spec.ts asserts), and
    the lazy PENDING_SESSIONS contract holds. /action dispatches the same
    task, so this one route-level proof covers the whole by-task claim."""
    from unittest.mock import patch

    from fastapi.testclient import TestClient

    from main import app
    from routes.learn import PENDING_SESSIONS

    monkeypatch.setenv("SAPLING_MODEL_MODE", "function")
    monkeypatch.setenv(
        "SAPLING_FUNCTION_HANDLERS", "agents.function_handlers_e2e"
    )

    PENDING_SESSIONS.clear()
    client = TestClient(app)
    try:
        with (
            socratic_agent.override(model=model_for("chat_tutor")),
            patch("routes.learn._get_course_id_for_topic", return_value=""),
            patch("routes.learn.get_graph", return_value={"nodes": [], "edges": []}),
        ):
            r = client.post("/api/learn/start-session", json={
                "user_id": "e2e-user", "topic": "Recursion", "mode": "socratic",
            })

        from agents.function_handlers_e2e import E2E_TUTOR_REPLY

        assert r.status_code == 200
        data = r.json()
        assert data["initial_message"] == E2E_TUTOR_REPLY
        assert data["session_id"] in PENDING_SESSIONS
        assert PENDING_SESSIONS[data["session_id"]]["assistant_reply"] == E2E_TUTOR_REPLY
    finally:
        PENDING_SESSIONS.clear()


# ── routes.learn model_pref override respects the mode ────────────────────


def test_resolve_model_pref_returns_none_in_function_mode(monkeypatch):
    """In function mode the browser's fast/smart pref must NOT produce a live
    GoogleModel override — that would put real Gemini back in the path the
    seam exists to remove (the browser always sends a pref)."""
    monkeypatch.setenv("SAPLING_MODEL_MODE", "function")
    assert _resolve_model_pref("fast") is None
    assert _resolve_model_pref("smart") is None


def test_resolve_model_pref_still_builds_override_in_real_mode(monkeypatch):
    """Default lane unchanged: real mode keeps the per-request override."""
    monkeypatch.delenv("SAPLING_MODEL_MODE", raising=False)
    m = _resolve_model_pref("fast")
    assert isinstance(m, GoogleModel)
    assert m.model_name == "gemini-2.5-flash-lite"
    assert _resolve_model_pref(None) is None


# ── Quiz journey contract (#393) ──────────────────────────────────────────
#
# frontend/e2e/quiz.spec.ts drives the real /quiz UI against a uvicorn booted
# with the two env vars and answers B, C, A expecting a 3/3 score. That is
# only deterministic while the env-registered quiz handler keeps producing
# exactly that quiz — through the REAL quiz_agent (output-tool schema
# validation included) and the REAL routes/quiz.py wire mapping. Pinned here
# so drift in the handler, the Quiz schema, or the wire mapping fails in CI
# instead of mid-browser-run.


def test_env_module_quiz_handler_produces_the_scripted_quiz(monkeypatch):
    """Full E2E-boot contract for the quiz task: function mode + the env-named
    module give a real quiz_agent run the fixed three-question quiz, with no
    handler registered by the test itself."""
    monkeypatch.setenv("SAPLING_MODEL_MODE", "function")
    monkeypatch.setenv(
        "SAPLING_FUNCTION_HANDLERS", "agents.function_handlers_e2e"
    )

    with quiz_agent.override(model=model_for("quiz")):
        result = quiz_agent.run_sync("Generate 5 medium questions.", deps=_deps())

    quiz = result.output
    assert len(quiz.questions) == 3
    # Correct options at indexes 1, 2, 0 → wire labels B, C, A.
    assert [q.options.index(q.correct_answer) for q in quiz.questions] == [1, 2, 0]
    assert all(q.question.startswith("E2E deterministic question") for q in quiz.questions)


def test_quiz_handler_wire_labels_match_the_browser_spec(monkeypatch):
    """Through the route's real wire mapping, the correct labels are exactly
    E2E_QUIZ_CORRECT_LABELS — the click sequence frontend/e2e/quiz.spec.ts
    hardcodes. Changing the ordering means updating the spec in the same PR
    (testids are API, and so is this sequence)."""
    monkeypatch.setenv("SAPLING_MODEL_MODE", "function")
    monkeypatch.setenv(
        "SAPLING_FUNCTION_HANDLERS", "agents.function_handlers_e2e"
    )

    with quiz_agent.override(model=model_for("quiz")):
        result = quiz_agent.run_sync("Generate 5 medium questions.", deps=_deps())

    from agents.function_handlers_e2e import E2E_QUIZ_CORRECT_LABELS

    labels = []
    for i, q in enumerate(result.output.questions):
        wire = _agent_question_to_wire(q, i + 1)
        assert wire is not None  # correct_answer appears verbatim in options
        labels.append(next(o["label"] for o in wire["options"] if o["correct"]))
    assert labels == list(E2E_QUIZ_CORRECT_LABELS)


def test_quiz_resolve_model_pref_returns_none_in_function_mode(monkeypatch):
    """The quiz half of the same bypass fixed in routes/learn.py: a fast/smart
    pref must not produce a live GoogleModel override in any non-real mode.
    The quiz UI sends no pref today, but any client that did would silently
    put live Gemini back in the function-mode path."""
    monkeypatch.setenv("SAPLING_MODEL_MODE", "function")
    assert _resolve_quiz_model_pref("fast") is None
    assert _resolve_quiz_model_pref("smart") is None


def test_quiz_resolve_model_pref_still_builds_override_in_real_mode(monkeypatch):
    """Default lane unchanged: real mode keeps the quiz per-request override."""
    monkeypatch.delenv("SAPLING_MODEL_MODE", raising=False)
    m = _resolve_quiz_model_pref("smart")
    assert isinstance(m, GoogleModel)
    assert m.model_name == "gemini-2.5-pro"
    assert _resolve_quiz_model_pref(None) is None


# ── Upload-pipeline handlers (#387) ───────────────────────────────────────


def test_env_module_registers_upload_pipeline_handlers_on_dispatch(monkeypatch):
    """#387's boot contract on the same once-per-process autoload: a real
    classifier run gets the module's scripted structured output — emitted
    through the agent's REAL output tool, so the DocumentClassification
    schema validated it — and that single import also registered the
    parallel workers (summary, concepts) and the post-roll course_summary."""
    monkeypatch.setenv("SAPLING_MODEL_MODE", "function")
    monkeypatch.setenv(
        "SAPLING_FUNCTION_HANDLERS", "agents.function_handlers_e2e"
    )

    with classifier_agent.override(model=model_for("classifier")):
        result = classifier_agent.run_sync("week 3 lecture notes", deps=_deps())

    from agents.function_handlers_e2e import E2E_DOC_CATEGORY, E2E_DOC_SHAREABILITY

    assert result.output.category == E2E_DOC_CATEGORY
    # #630: the handler has to answer the shareability field too. An omission
    # would arrive as None and index every lane upload private — which no
    # function-mode assertion could notice, because embedding is disabled below
    # the seam (#439) and nothing is indexed at all.
    assert result.output.shareability == E2E_DOC_SHAREABILITY
    assert result.output.is_syllabus is False
    for task in ("classifier", "summary", "concepts", "course_summary"):
        assert task in providers._FUNCTION_HANDLERS


def test_env_module_summary_handler_passes_real_output_schema(monkeypatch):
    """The scripted summary payload must satisfy the Summary output tool's
    real schema (headline <= 140 chars, 3-8 key points): drift between the
    module constants and the schema fails here, in the hermetic lane, not
    three phases into a browser run."""
    monkeypatch.setenv("SAPLING_MODEL_MODE", "function")
    monkeypatch.setenv(
        "SAPLING_FUNCTION_HANDLERS", "agents.function_handlers_e2e"
    )

    with summary_agent.override(model=model_for("summary")):
        result = summary_agent.run_sync("some document text", deps=_deps())

    from agents.function_handlers_e2e import E2E_DOC_ABSTRACT, E2E_DOC_HEADLINE

    assert result.output.headline == E2E_DOC_HEADLINE
    assert result.output.abstract == E2E_DOC_ABSTRACT
    assert 3 <= len(result.output.key_points) <= 8


# ── Concept description (#446) ────────────────────────────────────────────
#
# routes/graph.py's POST /api/graph/{user}/concept-description runs
# concept_describe_agent (tool-less, structured `ConceptDescription` output).
# Before #446 this module registered six tasks but not `concept_describe`, so
# function mode's dispatch raised LookupError and the route 500'd. This is
# the constants-sync contract test: frontend/e2e/tutor.spec.ts asserts
# E2E_CONCEPT_DESCRIPTION verbatim.


def test_env_module_registers_concept_describe_handler_on_dispatch(monkeypatch):
    """Full E2E-boot contract for concept_describe: function mode + the
    env-named module give a real concept_describe_agent run the module's
    fixed description — through the REAL structured output tool, with no
    handler registered by the test itself."""
    monkeypatch.setenv("SAPLING_MODEL_MODE", "function")
    monkeypatch.setenv(
        "SAPLING_FUNCTION_HANDLERS", "agents.function_handlers_e2e"
    )

    with concept_describe_agent.override(model=model_for("concept_describe")):
        result = concept_describe_agent.run_sync(
            build_message("Recursion", "CS 101"), deps=_deps()
        )

    from agents.function_handlers_e2e import E2E_CONCEPT_DESCRIPTION

    assert result.output.description == E2E_CONCEPT_DESCRIPTION
    assert "concept_describe" in providers._FUNCTION_HANDLERS


def test_concept_describe_handler_passes_real_output_schema(monkeypatch):
    """The scripted description must satisfy ConceptDescription's real schema
    (max_length=400) — drift between the module constant and the schema fails
    here, in the hermetic lane, not mid-browser-run."""
    monkeypatch.setenv("SAPLING_MODEL_MODE", "function")
    monkeypatch.setenv(
        "SAPLING_FUNCTION_HANDLERS", "agents.function_handlers_e2e"
    )

    with concept_describe_agent.override(model=model_for("concept_describe")):
        result = concept_describe_agent.run_sync(
            build_message("Recursion", None), deps=_deps()
        )

    from agents.function_handlers_e2e import E2E_CONCEPT_DESCRIPTION

    assert result.output.description == E2E_CONCEPT_DESCRIPTION
    assert len(E2E_CONCEPT_DESCRIPTION) <= 400


# ── Concept scan (#151b) ──────────────────────────────────────────────────
#
# routes/documents.py's POST /doc/{id}/scan-concepts and
# /course/{id}/scan-concepts run concept_scan_agent (tool-less, structured
# NewConcepts output — names only). Request-path: the route drives the agent
# via run_agent_sync and performs the graph write itself, so registering it
# is correct (the concept_describe reasoning). Unregistered, a function-mode
# scan raised UnregisteredHandlerError — which the route's #151b best-effort
# degrade would mask as {"concepts": [], "added": 0, ...}, silently hiding
# real scan coverage from the browser lane.


def test_env_module_registers_concept_scan_handler_on_dispatch(monkeypatch):
    """Full E2E-boot contract for concept_scan: function mode + the env-named
    module give a real concept_scan_agent run the module's fixed new-concept
    names — through the REAL structured output tool (NewConcepts caps the
    list at 15), with no handler registered by the test itself."""
    monkeypatch.setenv("SAPLING_MODEL_MODE", "function")
    monkeypatch.setenv(
        "SAPLING_FUNCTION_HANDLERS", "agents.function_handlers_e2e"
    )

    with concept_scan_agent.override(model=model_for("concept_scan")):
        result = concept_scan_agent.run_sync(
            'Course: "CS 101"\nConcepts already in the graph:\n- Recursion',
            deps=_deps(),
        )

    from agents.function_handlers_e2e import E2E_SCAN_NEW_CONCEPTS

    assert result.output.concepts == E2E_SCAN_NEW_CONCEPTS
    assert 0 < len(E2E_SCAN_NEW_CONCEPTS) <= 15
    assert "concept_scan" in providers._FUNCTION_HANDLERS


# ── Notetaker agent actions (F5a) ─────────────────────────────────────────
#
# routes/notes.py's summarize / extract-concepts / chat run note_summary,
# note_concepts, and note_chat — all request-path (the route awaits the agent
# and returns its output to the user). Before F5a this module registered
# seven tasks but none of these three, so function mode's dispatch raised
# UnregisteredHandlerError and each route 500'd. These are the boot +
# constants-sync contract tests: note_summary/note_concepts flow through the
# REAL structured output tools, note_chat through a plain-text response.


def test_env_module_registers_note_summary_handler_on_dispatch(monkeypatch):
    """note_summary has a structured output (NoteSummary.summary): a real agent
    run gets the module's fixed summary through the REAL output tool, with no
    handler registered by the test itself."""
    monkeypatch.setenv("SAPLING_MODEL_MODE", "function")
    monkeypatch.setenv(
        "SAPLING_FUNCTION_HANDLERS", "agents.function_handlers_e2e"
    )

    with note_summary_agent.override(model=model_for("note_summary")):
        result = note_summary_agent.run_sync(
            "Title: Recursion\n\nBody:\nA function that calls itself.",
            deps=_deps(),
        )

    from agents.function_handlers_e2e import E2E_NOTE_SUMMARY

    assert result.output.summary == E2E_NOTE_SUMMARY
    assert "note_summary" in providers._FUNCTION_HANDLERS


def test_env_module_registers_note_concepts_handler_on_dispatch(monkeypatch):
    """note_concepts has a structured output (NoteConcepts.concepts, a list of
    Title-Case names, 0–15 entries): the real agent returns the module's fixed
    list through the REAL output tool, and it satisfies that schema bound."""
    monkeypatch.setenv("SAPLING_MODEL_MODE", "function")
    monkeypatch.setenv(
        "SAPLING_FUNCTION_HANDLERS", "agents.function_handlers_e2e"
    )

    with note_concepts_agent.override(model=model_for("note_concepts")):
        result = note_concepts_agent.run_sync(
            "Title: Recursion\n\nBody:\nA function that calls itself.",
            deps=_deps(),
        )

    from agents.function_handlers_e2e import E2E_NOTE_CONCEPTS

    assert result.output.concepts == E2E_NOTE_CONCEPTS
    assert all(isinstance(c, str) and c.strip() for c in result.output.concepts)
    assert len(result.output.concepts) <= 15
    assert "note_concepts" in providers._FUNCTION_HANDLERS


def test_env_module_registers_note_chat_handler_on_dispatch(monkeypatch):
    """note_chat returns plain str, so its handler emits a text ModelResponse
    (like chat_tutor): the real agent run yields the module's fixed reply with
    none of its function tools (read_active_note, ...) fired."""
    monkeypatch.setenv("SAPLING_MODEL_MODE", "function")
    monkeypatch.setenv(
        "SAPLING_FUNCTION_HANDLERS", "agents.function_handlers_e2e"
    )

    with note_chat_agent.override(model=model_for("note_chat")):
        result = note_chat_agent.run_sync("What is a base case?", deps=_deps())

    from agents.function_handlers_e2e import E2E_NOTE_CHAT_REPLY

    assert result.output == E2E_NOTE_CHAT_REPLY
    assert "note_chat" in providers._FUNCTION_HANDLERS


# ── #149 guard: the e2e tutor handler stays tool-free ─────────────────────


def test_e2e_tutor_handler_makes_no_tool_calls_and_no_graph_writes(monkeypatch):
    """The chat tutor grew two read tools (#149), but the deterministic E2E
    handler must keep answering in ONE text response: zero ToolCallParts in
    the transcript, and the deps write accumulators (graph_updates /
    mastery_changes) stay empty — the browser journeys' graph oracles
    depend on tutor turns not mutating the graph."""
    monkeypatch.setenv("SAPLING_MODEL_MODE", "function")
    monkeypatch.setenv(
        "SAPLING_FUNCTION_HANDLERS", "agents.function_handlers_e2e"
    )

    deps = _deps()
    with socratic_agent.override(model=model_for("chat_tutor")):
        result = socratic_agent.run_sync("What is recursion?", deps=deps)

    tool_calls = [
        part
        for message in result.all_messages()
        for part in getattr(message, "parts", []) or []
        if type(part).__name__ == "ToolCallPart"
    ]
    assert tool_calls == [], (
        f"E2E tutor handler scripted tool calls: {[p.tool_name for p in tool_calls]}"
    )
    assert deps.graph_updates == []
    assert deps.mastery_changes == []


# ── Slow-stream trigger + lane pacing (#356) ──────────────────────────────
#
# frontend/e2e/streaming.spec.ts needs a mid-stream window to press Stop /
# switch sessions inside. The env module (a) sets the streamed-replay pacing
# knob at import, and (b) serves a LONG deterministic reply when the user
# message carries E2E_SLOW_STREAM_TRIGGER — giving those journeys several
# seconds of real streaming. The default (no trigger) reply must stay
# E2E_TUTOR_REPLY byte-for-byte: tutor.spec.ts asserts it verbatim.


def test_env_module_slow_trigger_returns_slow_reply(monkeypatch):
    """A tutor turn whose message carries the trigger gets the long slow-lane
    constant — through the real agent wiring via the env-autoloaded module."""
    monkeypatch.setenv("SAPLING_MODEL_MODE", "function")
    monkeypatch.setenv(
        "SAPLING_FUNCTION_HANDLERS", "agents.function_handlers_e2e"
    )

    with socratic_agent.override(model=model_for("chat_tutor")):
        result = socratic_agent.run_sync(
            "Walk me through this E2E_SLOW_STREAM please", deps=_deps()
        )

    from agents.function_handlers_e2e import E2E_TUTOR_SLOW_REPLY

    assert result.output == E2E_TUTOR_SLOW_REPLY


def test_env_module_default_reply_unchanged_by_trigger_support(monkeypatch):
    """Regression guard: a normal message (no trigger) still gets the fixed
    E2E_TUTOR_REPLY — the slow lane must never hijack the default journey."""
    monkeypatch.setenv("SAPLING_MODEL_MODE", "function")
    monkeypatch.setenv(
        "SAPLING_FUNCTION_HANDLERS", "agents.function_handlers_e2e"
    )

    with socratic_agent.override(model=model_for("chat_tutor")):
        result = socratic_agent.run_sync("What is recursion?", deps=_deps())

    from agents.function_handlers_e2e import E2E_TUTOR_REPLY

    assert result.output == E2E_TUTOR_REPLY


def test_env_module_import_sets_stream_pacing(monkeypatch):
    """Importing the module opts the lane into streamed-replay pacing (150ms
    between chunked deltas) so mid-stream journeys have a window to act in.
    In-process tests stay unpaced: the autouse registry reset
    (clear_function_handlers) zeroes the knob again after each case."""
    monkeypatch.setenv("SAPLING_MODEL_MODE", "function")
    monkeypatch.setenv(
        "SAPLING_FUNCTION_HANDLERS", "agents.function_handlers_e2e"
    )

    with socratic_agent.override(model=model_for("chat_tutor")):
        socratic_agent.run_sync("What is recursion?", deps=_deps())

    from agents._providers import function_stream_delay_ms

    assert function_stream_delay_ms() == 150


# ── Check items (learning loop PKG-04) ────────────────────────────────────


def test_env_module_registers_check_items_handler_on_dispatch(monkeypatch):
    """PKG-04: the check_items generator is a REQUEST-PATH agent in function
    mode (the upload hook runs it synchronously there), so it must have a
    handler that passes the real flat output schema and code validation —
    one free and one teachback item for each function-mode upload concept,
    and CHECK_ITEM_MC_MIN_PER_CONCEPT mc_reason items, so a function-mode pass
    leaves no concept below the A37 floor and makes no top-up call."""
    monkeypatch.setenv("SAPLING_MODEL_MODE", "function")
    monkeypatch.setenv("SAPLING_FUNCTION_HANDLERS", "agents.function_handlers_e2e")
    from agents.check_items import check_items_agent
    from learning.checks import validate_draft
    from learning.params import CHECK_ITEM_FORMATS
    with check_items_agent.override(model=model_for("check_items")):
        result = check_items_agent.run_sync("Concepts: Gradient Descent; Learning Rate", deps=_deps())

    from agents.function_handlers_e2e import (
        E2E_CHECK_ITEM_FINAL_ANSWER,
        E2E_CHECK_ITEM_MC_WRONG_KEYS,
        E2E_CHECK_ITEM_MC_WRONG_TEXTS,
        E2E_CHECK_ITEM_OPTIONS,
        E2E_CHECK_ITEM_REFERENCE,
        E2E_CHECK_ITEM_WRONG_KEY,
        E2E_CHECK_ITEM_WRONG_TEXT,
        E2E_DOC_CONCEPTS,
    )
    from learning.checks import WrongReason, common_wrong, lettered_options, repair_draft
    from learning.params import (
        CHECK_ITEM_DIFFICULTIES,
        CHECK_ITEM_MC_MIN_PER_CONCEPT,
        CHECK_ITEM_MC_OPTIONS,
    )

    items = result.output.items
    first = CHECK_ITEM_DIFFICULTIES[0]
    mc_levels = CHECK_ITEM_DIFFICULTIES[:CHECK_ITEM_MC_MIN_PER_CONCEPT]
    assert [(i.concept, i.format, i.difficulty) for i in items] == [
        pair
        for name, _, _ in E2E_DOC_CONCEPTS
        for pair in [
            *((name, fmt, first) for fmt in CHECK_ITEM_FORMATS if fmt != "mc_reason"),
            *((name, "mc_reason", level) for level in mc_levels),
        ]
    ]
    for name, _, _ in E2E_DOC_CONCEPTS:
        mc = [i for i in items if i.concept == name and i.format == "mc_reason"]
        assert len(mc) == CHECK_ITEM_MC_MIN_PER_CONCEPT, "a function-mode pass needs no top-up"
    assert len({i.prompt for i in items}) == len(items), "prompts must differ so hashes differ"
    for i in items:
        assert i.reference_answer == E2E_CHECK_ITEM_REFERENCE
        assert i.answer_kind == "free" and i.stepwise is False
        # A34: every item states its final answer (validate_draft checks it occurs
        # in the reference, not in the prompt, and is the correct option's text)
        assert i.final_answer == E2E_CHECK_ITEM_FINAL_ANSWER
        assert validate_draft(i) == [], validate_draft(i)
        assert repair_draft(i) == (i, []), "the constants need no repair"
    for i in (i for i in items if i.format == "mc_reason"):
        # A37: option objects, no letters — code letters them and places the key
        assert [o.model_dump() for o in i.options] == E2E_CHECK_ITEM_OPTIONS
        assert len(i.options) == CHECK_ITEM_MC_OPTIONS
        (correct,) = [o for o in i.options if o.is_correct]
        assert correct.text == E2E_CHECK_ITEM_FINAL_ANSWER
        assert (correct.misconception_key, correct.misconception_text) == (None, None)
        distractors = [o for o in i.options if not o.is_correct]
        assert [o.misconception_key for o in distractors] == E2E_CHECK_ITEM_MC_WRONG_KEYS
        assert [o.misconception_text for o in distractors] == E2E_CHECK_ITEM_MC_WRONG_TEXTS
        # A37 round 4: each distractor states its own misconception, the item
        # lists none, and code takes its common wrong reasons from the options
        assert i.wrong_keys == [] and i.wrong_texts == []
        assert common_wrong(i) == [
            WrongReason(key=k, text=t)
            for k, t in zip(E2E_CHECK_ITEM_MC_WRONG_KEYS, E2E_CHECK_ITEM_MC_WRONG_TEXTS)
        ]
        stored, letter = lettered_options(i, slot_key=b"any server secret")
        assert [o.letter for o in stored if o.wrong_key is None] == [letter]
        assert [o.wrong_key for o in stored if o.wrong_key] == E2E_CHECK_ITEM_MC_WRONG_KEYS
    for i in (i for i in items if i.format != "mc_reason"):
        assert i.options == []
        assert common_wrong(i) == [
            WrongReason(key=E2E_CHECK_ITEM_WRONG_KEY, text=E2E_CHECK_ITEM_WRONG_TEXT)
        ]
    assert "check_items" in providers._FUNCTION_HANDLERS


def test_the_mc_reason_top_up_rides_the_check_items_handler(monkeypatch):
    """A37 (coordinator's ruling, 2026-09-28): the top-up is its own agent on
    the check_items model slot, so function mode answers it with the
    check_items handler — no handler of its own, no UnregisteredHandlerError.
    Code keeps only the concept's mc_reason drafts (check_item_service)."""
    monkeypatch.setenv("SAPLING_MODEL_MODE", "function")
    monkeypatch.setenv("SAPLING_FUNCTION_HANDLERS", "agents.function_handlers_e2e")
    from agents.check_items_topup import check_items_topup_agent
    from agents.function_handlers_e2e import E2E_DOC_CONCEPTS

    with check_items_topup_agent.override(model=model_for("check_items")):
        result = check_items_topup_agent.run_sync("Concept: Gradient Descent", deps=_deps())
    concepts = {i.concept for i in result.output.items}
    assert concepts == {name for name, _, _ in E2E_DOC_CONCEPTS}


# ── Decision seam (learning loop PKG-05b) ─────────────────────────────────


def test_env_module_registers_decision_handler_on_dispatch(monkeypatch):
    """PKG-05b: the decision agent's E2E handler serves BOTH per-run output
    types off the real schema — the token → "yes" / the first OPTION key,
    else "no" / "none" — at the fixed E2E_DECISION_CONFIDENCE."""
    monkeypatch.setenv("SAPLING_MODEL_MODE", "function")
    monkeypatch.setenv("SAPLING_FUNCTION_HANDLERS", "agents.function_handlers_e2e")
    from agents.decision import DecisionPickOutput, build_decision_message, decision_agent
    from agents.function_handlers_e2e import E2E_DECISION_CONFIDENCE, E2E_DECISION_YES_TOKEN

    opts = [("w_loop", "loop"), ("w_speed", "speed")]
    hit = build_decision_message(f"Q {E2E_DECISION_YES_TOKEN}", [("S", "x")], opts)
    miss = build_decision_message("Q", [("S", "x")], opts)
    with decision_agent.override(model=model_for("decision")):
        picks = [
            decision_agent.run_sync(m, deps=_deps(), output_type=DecisionPickOutput).output
            for m in (hit, miss)
        ]
        yes, no = (decision_agent.run_sync(m, deps=_deps()).output for m in (hit, miss))
    assert [p.choice for p in picks] == ["w_loop", "none"]
    assert (yes.answer, no.answer) == ("yes", "no")
    assert yes.confidence == picks[1].confidence == E2E_DECISION_CONFIDENCE
    # Request-path from PKG-10 on (match_wrong_reason without a prior grade);
    # until then services/decisions.py is its only runner, and no route calls it.
    assert "decision" in providers._FUNCTION_HANDLERS


@pytest.mark.parametrize("slot", ["loop_tutor_lite", "loop_tutor", "loop_tutor_deep"])
def test_env_module_registers_loop_tutor_handler_on_dispatch(monkeypatch, slot):
    """PKG-07: one loop_tutor_agent, three tier slots picked per run (spec §3.5, A15);
    the E2E module serves every slot the same fixed reply, with no tool call."""
    monkeypatch.setenv("SAPLING_MODEL_MODE", "function")
    monkeypatch.setenv("SAPLING_FUNCTION_HANDLERS", "agents.function_handlers_e2e")
    from agents.loop_tutor import loop_tutor_agent

    deps = _deps()
    result = loop_tutor_agent.run_sync("What is a base case?", deps=deps, model=model_for(slot))

    from agents.function_handlers_e2e import E2E_LOOP_TUTOR_REPLY, E2E_LOOP_TUTOR_TURN
    from learning.turn_shape import render_turn

    assert result.output == E2E_LOOP_TUTOR_TURN
    assert render_turn(result.output) == E2E_LOOP_TUTOR_REPLY
    assert not deps.pending_evidence  # the handler scripts no tool call; the loop has no grader tool


@pytest.mark.parametrize("slot", ["loop_tutor_lite", "loop_tutor", "loop_tutor_deep"])
@pytest.mark.parametrize("phase,ceiling,released", [
    ("teach", 0, False), ("teach", 3, False), ("hint", 1, False), ("feedback", 6, True),
])
def test_e2e_loop_handler_returns_valid_turn(monkeypatch, slot, phase, ceiling, released):
    """PKG-07 unblock S1: the E2E seam answers the structured output type with a
    turn that passes the output validator at the TIGHTEST limits (a 1-sentence body
    at H0/H1), so no E2E loop turn ever burns an output retry."""
    monkeypatch.setenv("SAPLING_MODEL_MODE", "function")
    monkeypatch.setenv("SAPLING_FUNCTION_HANDLERS", "agents.function_handlers_e2e")
    from agents.function_handlers_e2e import E2E_LOOP_TUTOR_TURN
    from agents.loop_tutor import loop_tutor_agent
    from learning.turn_shape import turn_limits, validate_turn

    limits = turn_limits(phase, ceiling, released)
    assert validate_turn(E2E_LOOP_TUTOR_TURN, limits) == []
    deps = _deps()
    deps.loop_turn = limits
    result = loop_tutor_agent.run_sync("What is a base case?", deps=deps, model=model_for(slot))
    assert result.output == E2E_LOOP_TUTOR_TURN
    assert result.usage().requests == 1  # no output retry


def test_env_module_serves_session_close(monkeypatch):
    """PKG-09: the close agent is on the request path (POST /api/learn/loop/close
    and the loop end_session), so the E2E lane needs its handler."""
    from agents.session_close import session_close_agent

    monkeypatch.setenv("SAPLING_MODEL_MODE", "function")
    monkeypatch.setenv("SAPLING_FUNCTION_HANDLERS", "agents.function_handlers_e2e")

    with session_close_agent.override(model=model_for("session_close")):
        result = session_close_agent.run_sync("close this session", deps=_deps())

    from agents.function_handlers_e2e import (
        E2E_CLOSE_IF_THEN,
        E2E_CLOSE_MISCONCEPTIONS,
        E2E_CLOSE_SELF_EVAL,
        E2E_CLOSE_SUMMARY,
    )

    assert result.output.summary == E2E_CLOSE_SUMMARY
    assert result.output.self_eval_prompt == E2E_CLOSE_SELF_EVAL
    assert result.output.if_then_plan == E2E_CLOSE_IF_THEN
    assert result.output.open_misconception_keys == E2E_CLOSE_MISCONCEPTIONS
    assert E2E_CLOSE_IF_THEN.startswith("If ") and ", then " in E2E_CLOSE_IF_THEN
    assert E2E_CLOSE_SELF_EVAL.endswith("?") and E2E_CLOSE_SELF_EVAL.count("?") == 1


# ── PKG-10: the misconception path on the E2E lane ─────────────────────────


def test_e2e_grader_wrong_reason_token_matches_the_first_listed_key(monkeypatch):
    """PKG-10 wires decisions.match_wrong_reason on the request path (with the
    grader's result as `prior`, so no decision-agent run). The E2E lane makes
    the matched key deterministic: an answer holding
    E2E_GRADER_WRONG_REASON_TOKEN is graded wrong with the item's FIRST listed
    common wrong reason matched; two such answers on two isomorphs of one
    concept are a misconception (PKG-13's journey types the token)."""
    import asyncio
    from unittest.mock import patch

    from agents.grader import grader_agent
    from agents.tools.check import CheckAnswer, grade_answer
    from learning.misconceptions import confront_of
    from learning.policy import LoopState
    from services import decisions

    monkeypatch.setenv("SAPLING_MODEL_MODE", "function")
    monkeypatch.setenv("SAPLING_FUNCTION_HANDLERS", "agents.function_handlers_e2e")
    from agents.function_handlers_e2e import (
        E2E_GRADER_CORRECT_TOKEN,
        E2E_GRADER_WRONG_REASON_TOKEN,
    )
    from tests.test_learning_check_tool import _item
    from learning.checks import WrongReason

    wrong = [WrongReason(key="w_loop", text="loops"), WrongReason(key="w_speed", text="speed")]
    items = [
        _item(id=f"ci-{qh}", question_hash=qh, difficulty=2, common_wrong=wrong)
        for qh in ("h1", "h2")
    ]
    deps = SaplingDeps(
        user_id="e2e-user",
        course_id="e2e-course",
        supabase=None,
        request_id="e2e-req",
        session_id="e2e-session",
        learning_loop=True,
        loop_state=LoopState().to_json(),
    )
    with (
        grader_agent.override(model=model_for("grader")),
        patch("learning.misconceptions.record", side_effect=AssertionError("route-only")),
        patch.object(decisions, "_run_decision") as run,
    ):
        outs = [
            asyncio.run(
                grade_answer(
                    it,
                    CheckAnswer(
                        question_hash=it.question_hash,
                        answer_text=f"{E2E_GRADER_WRONG_REASON_TOKEN}: it just loops",
                    ),
                    deps=deps,
                    node_id="n1",
                )
            )
            for it in items
        ]
        right = asyncio.run(
            grade_answer(
                items[0],
                CheckAnswer(question_hash="h1", answer_text=f"{E2E_GRADER_CORRECT_TOKEN} stops"),
                deps=deps,
                node_id="n2",
            )
        )
    run.assert_not_called()
    assert [(o.correct, o.wrong_key, o.verdict) for o in outs] == [
        (False, "w_loop", "unknown"),
        (False, "w_loop", "misconception"),
    ]
    assert outs[0].diagnosis["record"] is None
    assert outs[1].diagnosis["record"] == {
        "node_id": "n1",
        "check_item_id": "ci-h2",
        "wrong_key": "w_loop",
    }
    assert confront_of(deps.loop_state)["wrong_key"] == "w_loop"
    assert right.correct is True and right.wrong_key is None and right.matched_wrong_key is None


# ── Learning loop, PKG-13: the phase-aware loop_tutor handler ──────────────
#
# The loop_tutor handler answers by PHASE so frontend/e2e/learn-loop.spec.ts
# can tell a hint turn from a feedback turn from a teach turn. It reads the
# phase off THIS run's user prompt — the prefix routes/learn_loop.py assembles
# with agents.loop_tutor.phase_prefix — never off the history, where an earlier
# turn's prefix would answer a later teach turn with the hint reply. The
# pattern values are copied from agents/loop_tutor.py's phase rules, so a
# prompt rewrite that drops them fails these tests, not the browser lane.

_LOOP_SLOTS = ["loop_tutor_lite", "loop_tutor", "loop_tutor_deep"]
#: (phase, ceiling, answer_released, verdict) — one real prefix per model phase.
_LOOP_PHASE_CASES = {
    "teach": ("teach", 1, False, None),
    "hint": ("hint", 1, False, None),
    "feedback": ("feedback", 6, True, "not_yet"),
}


def _loop_turn_message(phase_key: str, student_text: str = "help me") -> tuple[str, object]:
    """The user message a real loop run carries for `phase_key`, and its limits."""
    from agents.loop_tutor import assemble_turn_message, new_nonce, phase_prefix
    from learning.turn_shape import clamp_model_ceiling, turn_limits

    phase, ceiling, released, verdict = _LOOP_PHASE_CASES[phase_key]
    prefix = phase_prefix(
        phase=phase,
        band="novice",
        ceiling=ceiling,
        item_prompt=None if phase == "teach" else "[e2e-loop] A seeded check item.",
        item_format=None if phase == "teach" else "free",
        answer_released=released,
        verdict=verdict,
    )
    message = assemble_turn_message(
        prefix=prefix, blocks=[], nonce=new_nonce(), student_text=student_text
    )
    return message, turn_limits(phase, clamp_model_ceiling(ceiling, released), released)


def _loop_turn_for(phase_key: str) -> dict:
    import agents.function_handlers_e2e as m

    return {
        "teach": m.E2E_LOOP_TUTOR_TURN,
        "hint": m.E2E_LOOP_HINT_TURN,
        "feedback": m.E2E_LOOP_FEEDBACK_TURN,
    }[phase_key]


@pytest.mark.parametrize("slot", _LOOP_SLOTS)
@pytest.mark.parametrize("phase_key", ["teach", "hint", "feedback"])
def test_loop_tutor_handler_answers_by_phase_on_every_tier_slot(monkeypatch, slot, phase_key):
    """Spec §13 A15: code picks the tier slot per run (feedback after a correct
    answer runs on loop_tutor_lite), so the scripted reply depends on the PHASE
    of the real prefix, never on the slot — and no turn burns an output retry."""
    monkeypatch.setenv("SAPLING_MODEL_MODE", "function")
    monkeypatch.setenv("SAPLING_FUNCTION_HANDLERS", "agents.function_handlers_e2e")
    from agents.loop_tutor import loop_tutor_agent
    from learning.turn_shape import render_turn

    message, limits = _loop_turn_message(phase_key)
    deps = _deps()
    deps.loop_turn = limits
    result = loop_tutor_agent.run_sync(message, deps=deps, model=model_for(slot))
    turn = _loop_turn_for(phase_key)
    assert result.output == turn
    assert result.usage().requests == 1  # no output retry
    assert not deps.pending_evidence  # no tool call

    import agents.function_handlers_e2e as m

    reply = {
        "teach": m.E2E_LOOP_TUTOR_REPLY,
        "hint": m.E2E_LOOP_HINT_REPLY,
        "feedback": m.E2E_LOOP_FEEDBACK_REPLY,
    }[phase_key]
    assert render_turn(result.output) == reply


def test_loop_tutor_handler_reads_this_runs_prompt_not_the_history(monkeypatch):
    """A teach turn after a hint turn carries the hint prefix in its HISTORY;
    the handler must still answer it with the teach reply."""
    monkeypatch.setenv("SAPLING_MODEL_MODE", "function")
    monkeypatch.setenv("SAPLING_FUNCTION_HANDLERS", "agents.function_handlers_e2e")
    from pydantic_ai.messages import ModelRequest, ModelResponse, TextPart, UserPromptPart

    from agents.function_handlers_e2e import E2E_LOOP_HINT_REPLY, E2E_LOOP_TUTOR_TURN
    from agents.loop_tutor import loop_tutor_agent

    hint_message, _ = _loop_turn_message("hint")
    teach_message, limits = _loop_turn_message("teach")
    history = [
        ModelRequest(parts=[UserPromptPart(content=hint_message)]),
        ModelResponse(parts=[TextPart(content=E2E_LOOP_HINT_REPLY)]),
    ]
    deps = _deps()
    deps.loop_turn = limits
    result = loop_tutor_agent.run_sync(
        teach_message, deps=deps, model=model_for("loop_tutor"), message_history=history
    )
    assert result.output == E2E_LOOP_TUTOR_TURN


def test_loop_phase_patterns_are_real_and_unique_phase_prompt_text():
    """Each pattern is verbatim prompt source, appears in its own phase's real
    prefix, and in no other phase's prefix nor the system prompt — so it can
    neither be invented nor misfire."""
    import pathlib

    from agents.function_handlers_e2e import E2E_LOOP_PHASE_PATTERNS
    from agents.loop_tutor import _LOOP_SYSTEM_PROMPT, LOOP_OUTPUT_TEMPLATE

    src = (pathlib.Path(__file__).resolve().parents[1] / "agents" / "loop_tutor.py").read_text()
    assert set(E2E_LOOP_PHASE_PATTERNS) == {"hint", "feedback"}
    for phase, pattern in E2E_LOOP_PHASE_PATTERNS.items():
        assert len(pattern) >= 12, (phase, pattern)
        assert pattern in src, f"{phase!r} pattern {pattern!r} is not in agents/loop_tutor.py"
        assert pattern not in _LOOP_SYSTEM_PROMPT + LOOP_OUTPUT_TEMPLATE
        for other in _LOOP_PHASE_CASES:
            message, _ = _loop_turn_message(other)
            assert (pattern in message) == (other == phase), (phase, other)


def test_loop_turn_constants_are_valid_turns_at_the_tightest_limits():
    """Every scripted loop turn passes the output validator — shape, control
    tags, LaTeX and the below-H4 invented-math provenance check — at H0 (a
    one-sentence body), with nothing given, so the served path never retries."""
    from agents.function_handlers_e2e import (
        E2E_LOOP_FEEDBACK_TURN,
        E2E_LOOP_HINT_TURN,
        E2E_LOOP_TUTOR_TURN,
    )
    from learning.turn_shape import turn_limits, validate_turn

    for phase, turn in (
        ("teach", E2E_LOOP_TUTOR_TURN),
        ("hint", E2E_LOOP_HINT_TURN),
        ("feedback", E2E_LOOP_FEEDBACK_TURN),
    ):
        for ceiling in (0, 1, 2, 3):
            assert validate_turn(turn, turn_limits(phase, ceiling, False), source="") == [], (
                phase,
                ceiling,
            )


def test_loop_constants_do_not_state_a_seeded_answer():
    """A hint or feedback reply carrying the grader's correct token would let the
    journey pass a check it never answered; one carrying the seeded items' final
    answer (or a 6-gram of their reference) would be a real leak."""
    import agents.function_handlers_e2e as m
    from learning.checks import answer_run, find_runs
    from learning.params import LEAK_NGRAM

    texts = (
        m.E2E_LOOP_TUTOR_REPLY,
        m.E2E_LOOP_HINT_REPLY,
        m.E2E_LOOP_FEEDBACK_REPLY,
        m.E2E_LOOP_PROBE_PROMPT,
    )
    reference = answer_run(m.E2E_LOOP_REFERENCE)
    grams = {reference[i : i + LEAK_NGRAM] for i in range(len(reference) - LEAK_NGRAM + 1)}
    for text in texts:
        run = answer_run(text)
        assert m.E2E_GRADER_CORRECT_TOKEN not in text
        assert m.E2E_GRADER_WRONG_REASON_TOKEN not in text
        assert not find_runs(run, answer_run(m.E2E_LOOP_FINAL_ANSWER)), text
        assert not {run[i : i + LEAK_NGRAM] for i in range(len(run) - LEAK_NGRAM + 1)} & grams
    # A34: the final answer is copied verbatim from the reference and absent from the prompt.
    assert m.E2E_LOOP_FINAL_ANSWER in m.E2E_LOOP_REFERENCE
    assert not find_runs(answer_run(m.E2E_LOOP_PROBE_PROMPT), answer_run(m.E2E_LOOP_FINAL_ANSWER))
    # The E2E grader grades on the token anywhere in its message, which quotes the
    # reference and the prompt: a token there would grade EVERY answer correct.
    assert m.E2E_GRADER_CORRECT_TOKEN not in m.E2E_LOOP_REFERENCE
    assert m.E2E_LOOP_PROBE_PROMPT.startswith("[e2e-loop]")


def test_loop_turn_body_and_question_survive_the_served_path_at_the_journeys_rung():
    """frontend/e2e/learn-loop.spec.ts asserts the model-written body and question
    of the hint (H1) and correct-verdict feedback turns: at H0/H1 the route serves
    the KEY IDEA from code (routes.learn_loop.served_render), so the journey pins
    the two fields that reach the student verbatim."""
    import agents.function_handlers_e2e as m
    from learning.ladder import Rung
    from routes.learn_loop import served_render

    for phase, turn, body, question, verdict in (
        ("hint", m.E2E_LOOP_HINT_TURN, m.E2E_LOOP_HINT_BODY, m.E2E_LOOP_HINT_QUESTION, None),
        (
            "feedback",
            m.E2E_LOOP_FEEDBACK_TURN,
            m.E2E_LOOP_FEEDBACK_BODY,
            m.E2E_LOOP_FEEDBACK_QUESTION,
            "correct",
        ),
    ):
        assert (turn["body"], turn["question"]) == (body, question)
        for rung in (Rung.H0, Rung.H1):
            served = served_render(turn, phase=phase, rung=rung, verdict=verdict)
            assert body in served and question in served

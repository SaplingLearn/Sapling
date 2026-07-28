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
from agents.deps import SaplingDeps
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

    from agents.function_handlers_e2e import E2E_DOC_CATEGORY

    assert result.output.category == E2E_DOC_CATEGORY
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

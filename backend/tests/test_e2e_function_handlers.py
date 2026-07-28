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
from agents.deps import SaplingDeps
from routes.learn import _resolve_model_pref


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

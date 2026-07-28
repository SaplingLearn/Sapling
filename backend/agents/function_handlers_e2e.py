"""Deterministic FunctionModel handlers for the E2E browser lane (#392).

Importing this module registers per-task handlers on the #391 seam. It is
loaded ONLY when the backend boots with both

    SAPLING_MODEL_MODE=function
    SAPLING_FUNCTION_HANDLERS=agents.function_handlers_e2e

(see `_providers._load_env_handlers_module`). Production and the pytest lane
never import it: the env vars are unset there, and pytest registers its own
scripted handlers explicitly per test.

Design constraints for every handler in this file:

- **Fixed output.** Replies are constants the Playwright specs assert on
  verbatim (rendered in the UI and decrypted out of the database). Echoing
  request content back would couple the constant to route-side prompt
  assembly (RAG prefixes, constraint suffixes) — keep it fixed.
- **No tool calls.** Scripted tool calls belong in the pytest seam tests
  (`tests/test_model_mode_seam.py`), where the side effects are spied. A
  browser journey wants zero model-driven writes beyond what the route
  itself persists, so `graph_update` / `mastery_changes` stay empty.

Journeys for other tasks (quiz, notes, documents) should append their
handlers here rather than growing parallel modules.
"""

from __future__ import annotations

from pydantic_ai.messages import ModelResponse, TextPart

from agents._providers import register_function_handler

# Asserted verbatim by frontend/e2e/tutor.spec.ts (rendered reply + decrypted
# messages.content readback). Keep the two literals in sync.
E2E_TUTOR_REPLY = (
    "[e2e-function-model] Deterministic tutor reply: every recursive function "
    "needs a base case so it can stop calling itself."
)


def _chat_tutor_handler(messages, info) -> ModelResponse:
    return ModelResponse(parts=[TextPart(content=E2E_TUTOR_REPLY)])


register_function_handler("chat_tutor", _chat_tutor_handler)

"""Deterministic FunctionModel handlers for the E2E browser lane (#392).

Importing this module registers per-task handlers on the #391 seam. It is
loaded ONLY when the backend boots with both

    SAPLING_MODEL_MODE=function
    SAPLING_FUNCTION_HANDLERS=agents.function_handlers_e2e

(see `_providers._load_env_handlers_module`). Production and the normal
(hermetic) pytest lane never import it: the env vars are unset there, and
pytest registers its own scripted handlers explicitly per test. The seam's
own tests (`tests/test_e2e_function_handlers.py`) are the one exception —
they set the vars deliberately to exercise this module.

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

from pydantic_ai.messages import ModelResponse, TextPart, ToolCallPart

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


# ── Quiz (#393) ────────────────────────────────────────────────────────────
#
# Fixed three-question quiz. The correct options sit at indexes 1, 2, 0;
# routes/quiz.py assigns wire labels in options order, so the correct labels
# are B, C, A. frontend/e2e/quiz.spec.ts clicks exactly that sequence and
# backend/tests/test_e2e_function_handlers.py pins it — KEEP ALL THREE IN
# SYNC (E2E_QUIZ_CORRECT_LABELS is that contract, exported like
# E2E_TUTOR_REPLY above). The count deliberately ignores the requested
# num_questions: the route stores whatever the agent returns, and a fixed
# count keeps the journey's mastery math (3 correct × +0.03 = +0.09)
# byte-stable across runs. The `concept` field is fixed too (the route
# derives mastery from the DB node it looked up, never from this field).
#
# The single ToolCallPart below is the agent's OUTPUT tool (the structured
# Quiz result) — not a function tool, so the no-tool-calls constraint above
# holds. `quiz_context` stays deliberately unregistered: submit_quiz updates
# it in a BackgroundTask wrapped in `except Exception: pass`, so an
# unscripted handler fails fast with no post-response DB write racing the
# next test's truncate + re-seed.

E2E_QUIZ_CORRECT_LABELS = ("B", "C", "A")

_E2E_QUIZ_QUESTIONS = [
    {
        "question": f"E2E deterministic question {n}: which option is marked correct?",
        "type": "multiple_choice",
        "difficulty": "medium",
        "options": [f"Q{n} option A", f"Q{n} option B", f"Q{n} option C", f"Q{n} option D"],
        "correct_answer": f"Q{n} option {label}",
        "explanation": f"Scripted E2E fixture: option {label} is the marked answer for question {n}.",
        "concept": "Recursion",
    }
    for n, label in zip((1, 2, 3), E2E_QUIZ_CORRECT_LABELS)
]


def _quiz_handler(messages, info) -> ModelResponse:
    return ModelResponse(
        parts=[
            ToolCallPart(
                tool_name=info.output_tools[0].name,
                args={"questions": _E2E_QUIZ_QUESTIONS},
            )
        ]
    )


register_function_handler("quiz", _quiz_handler)

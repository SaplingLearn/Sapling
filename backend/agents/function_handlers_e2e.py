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

from agents._providers import (
    FunctionModelHandler,
    register_function_handler,
    set_function_stream_delay_ms,
)

# Streamed-replay pacing (#356): re-chunk streamed text into small deltas with
# 150ms between them, giving the mid-stream journeys (Stop a turn, switch
# sessions while streaming — frontend/e2e/streaming.spec.ts) a real window to
# act in. Import-time is the right moment: this module only loads in the E2E
# lane, and the seam reads the knob after resolving the handler, so even the
# first stream paces. Replies are unchanged byte-for-byte — pacing only slices
# HOW the same constant streams. The seam tests' clear_function_handlers()
# resets the knob, so in-process pytest runs stay unpaced.
set_function_stream_delay_ms(150)

# Asserted verbatim by frontend/e2e/tutor.spec.ts (rendered reply + decrypted
# messages.content readback). Keep the two literals in sync.
E2E_TUTOR_REPLY = (
    "[e2e-function-model] Deterministic tutor reply: every recursive function "
    "needs a base case so it can stop calling itself."
)

# Slow lane for mid-stream journeys (#356). A tutor message carrying the
# trigger substring streams this LONG reply instead — ~1000 chars ≈ 40+ paced
# chunks ≈ a 6-second window to press Stop or switch sessions inside.
# Asserted verbatim by frontend/e2e/streaming.spec.ts (including the final
# sentence as the completion sentinel). Keep the literals in sync.
E2E_SLOW_STREAM_TRIGGER = "E2E_SLOW_STREAM"
E2E_TUTOR_SLOW_REPLY = (
    "[e2e-function-model] Deterministic SLOW tutor reply for mid-stream "
    "journeys. Recursion solves a problem by reducing it to a smaller copy "
    "of itself, and every recursive function needs two ingredients: a base "
    "case that stops the descent, and a recursive step that makes real "
    "progress toward that base case on every call. Picture the call stack "
    "as a tower of postponed promises: each frame waits for the smaller "
    "problem beneath it to resolve before it can finish its own work. When "
    "the base case finally answers, the tower unwinds in reverse order and "
    "every waiting frame completes with the value it was promised. If the "
    "recursive step ever fails to shrink the problem, the tower grows "
    "without bound until the runtime refuses to add another frame and the "
    "program crashes with a stack overflow. That is the whole discipline in "
    "one sentence: shrink toward a base case you are certain to reach. This "
    "is the final sentence of the slow deterministic reply."
)


def _last_user_prompt_text(messages) -> str:
    """The most recent user-prompt text in a pydantic-ai message history.

    Used only for trigger sniffing, so it is deliberately tolerant: content
    may be a plain string or a sequence mixing strings with binary parts
    (pydantic-ai allows both); non-string members are ignored."""
    for message in reversed(messages):
        for part in reversed(getattr(message, "parts", None) or []):
            if getattr(part, "part_kind", "") != "user-prompt":
                continue
            content = getattr(part, "content", "")
            if isinstance(content, str):
                return content
            try:
                return " ".join(c for c in content if isinstance(c, str))
            except TypeError:
                return ""
    return ""


def _chat_tutor_handler(messages, info) -> ModelResponse:
    if E2E_SLOW_STREAM_TRIGGER in _last_user_prompt_text(messages):
        return ModelResponse(parts=[TextPart(content=E2E_TUTOR_SLOW_REPLY)])
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


# ── Document upload pipeline (#387) ─────────────────────────────────────────
#
# The SSE /api/documents/upload journey runs: classifier → (summary ∥
# concepts) → graph merge → persist. The classifier is scripted as a
# NON-syllabus category so syllabus extraction never runs and no assignment
# side effects fire. `course_summary` covers the post-roll
# update_course_context task so it completes through the real agent instead
# of its template fallback.
#
# These agents have structured `output_type`s, so each handler emits its
# fixed payload through the agent's OUTPUT tool (`info.output_tools[0]`) —
# the same channel a Gemini structured response uses, validated by the real
# output schema. That stays within this module's no-tool-calls constraint:
# no *function* tools are invoked and the model drives zero writes; the
# route itself performs the graph merge and persistence.

E2E_DOC_CATEGORY = "lecture_notes"
E2E_DOC_HEADLINE = "Deterministic E2E lecture notes on gradient descent."
# Asserted (as a substring, rendered + decrypted-readback) by
# frontend/e2e/upload.spec.ts. Keep the literals in sync.
E2E_DOC_ABSTRACT = (
    "These lecture notes introduce gradient descent as an iterative "
    "optimization procedure. They define the loss surface, derive the "
    "parameter update rule, and discuss how the learning rate governs "
    "convergence. The treatment is deterministic fixture content for the "
    "E2E upload journey."
)
E2E_DOC_KEY_POINTS = [
    "Gradient descent iteratively steps against the gradient of the loss.",
    "The learning rate controls the size of each update step.",
    "Convergence behavior depends on the shape of the loss surface.",
]
E2E_DOC_CONCEPTS = [
    ("Gradient Descent", "Iterative optimization that steps against the loss gradient.", 0.9),
    ("Learning Rate", "Step-size hyperparameter governing each descent update.", 0.7),
]


def _structured_output(args: dict) -> FunctionModelHandler:
    """Handler emitting `args` through the agent's registered output tool, so
    the REAL output schema validates the payload before the agent returns."""

    def handler(messages, info) -> ModelResponse:
        return ModelResponse(
            parts=[ToolCallPart(tool_name=info.output_tools[0].name, args=args)]
        )

    return handler


register_function_handler(
    "classifier",
    _structured_output({
        "category": E2E_DOC_CATEGORY,
        "is_syllabus": False,
        "confidence": 0.95,
        "rationale": "Scripted E2E classification: narrative notes, no schedule.",
    }),
)
register_function_handler(
    "summary",
    _structured_output({
        "headline": E2E_DOC_HEADLINE,
        "abstract": E2E_DOC_ABSTRACT,
        "key_points": E2E_DOC_KEY_POINTS,
    }),
)
register_function_handler(
    "concepts",
    _structured_output({
        "concepts": [
            {"name": name, "description": desc, "importance": imp}
            for name, desc, imp in E2E_DOC_CONCEPTS
        ],
    }),
)
register_function_handler(
    "course_summary",
    _structured_output({
        "summary": (
            "Scripted E2E course summary: the class is progressing "
            "steadily; review the struggling concepts listed above."
        ),
    }),
)


# ── Concept description (#446) ──────────────────────────────────────────────
#
# `POST /api/graph/{user}/concept-description` (routes/graph.py) runs
# concept_describe_agent, a tool-less agent with a structured
# `ConceptDescription` output (a single `description` field — see
# agents/concept_describe.py). Request-path, not a post-response
# BackgroundTask, so registering it is safe (unlike `quiz_context`, which
# stays deliberately unregistered — see the quiz section above).

# Asserted verbatim by frontend/e2e/tutor.spec.ts (rendered concept-blurb
# text). Keep the two literals in sync.
E2E_CONCEPT_DESCRIPTION = (
    "[e2e-function-model] Deterministic concept blurb: recursion is when a "
    "function calls itself on a smaller version of the same problem."
)

register_function_handler(
    "concept_describe",
    _structured_output({"description": E2E_CONCEPT_DESCRIPTION}),
)

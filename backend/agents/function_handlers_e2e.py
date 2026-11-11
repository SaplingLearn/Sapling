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

import json
import re

from pydantic_ai.messages import ModelResponse, TextPart, ToolCallPart

from agents._decision_fixtures import DECISION_ANSWERS
from agents._providers import (
    FunctionModelHandler,
    register_function_handler,
    set_function_stream_delay_ms,
)
from learning.params import (
    CHECK_ITEM_DIFFICULTIES,
    CHECK_ITEM_FORMATS,
    CHECK_ITEM_MC_MIN_PER_CONCEPT,
    MULTI_CONCEPT_DIFFICULTY,
)
from learning.turn_shape import (
    ANSWER_VERDICT_LEADS,
    LOOP_PLAN_OPENER,
    LOOP_PROBE_OPENER,
    TurnTemplate,
    render_turn,
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
    prompt = "\n".join(
        part.content for message in messages for part in message.parts
        if getattr(part, "part_kind", None) == "user-prompt" and isinstance(part.content, str)
    )
    tool = info.output_tools[0]
    if "PlannedQuestion" in ((tool.parameters_json_schema or {}).get("$defs") or {}):
        # Spec §13 A144: the planned agent (agents/quiz_planned.py) rides this
        # slot with its own schema, told apart by it.
        return ModelResponse(
            parts=[ToolCallPart(tool_name=tool.name, args={"questions": _e2e_planned(prompt)})]
        )
    requested = re.search(r"question_format: (short_answer|numeric|symbolic|mixed)\.", prompt)
    questions = _E2E_QUIZ_QUESTIONS
    if requested:
        formats = ["short_answer", "numeric", "symbolic"] if requested[1] == "mixed" else [requested[1]] * 3
        answers = {"short_answer": "base case", "numeric": "0.5", "symbolic": "2x+2"}
        questions = [{
            "question": f"E2E written question {n}: enter the {kind} fixture answer.",
            "type": kind, "difficulty": "medium", "options": [],
            "correct_answer": answers[kind],
            "accepted_answers": ["termination condition"] if kind == "short_answer" else [],
            "explanation": "Scripted written-answer fixture.", "concept": "Recursion",
        } for n, kind in enumerate(formats, 1)]
    return ModelResponse(
        parts=[
            ToolCallPart(
                tool_name=info.output_tools[0].name,
                args={"questions": questions},
            )
        ]
    )


register_function_handler("quiz", _quiz_handler)


# ── Planned quiz questions (spec §13 A144, flag `quiz_planned_questions`) ──
#
# The planned agent rides the quiz slot (above, told apart by its schema). One
# item per `QUESTION <n>:` line of the message, so the count follows the plan.
# A multiple-choice item's correct option is E2E_CHECK_ITEM_FINAL_ANSWER, at
# the position E2E_QUIZ_CORRECT_LABELS gives slot n (B, C, A, B, ...), and its
# stem carries the `[e2e-function-model][<CONCEPT>]` marker: so the quiz
# checks' handlers (quiz_check, below) find the concept the item tests and
# solve it to its key, and every planned E2E item is VERIFIED. Its three
# distractors are E2E check items' own (E2E_CHECK_ITEM_OPTIONS[1:]), each
# tagged with its misconception key when the message lists that key; a
# QUESTION line's TARGET no distractor carries yet goes on the first untagged
# distractor (the seeded loop course's key, `wrong_token`, is no E2E option's,
# so a target on it tags the first distractor — the one a journey picks). A
# written item (FORMAT short_answer, or mixed: even slots) answers
# E2E_CHECK_ITEM_FINAL_ANSWER too, so the solve agrees with it in code.
# Contract: tests/test_e2e_function_handlers.py. Keep in sync.

E2E_PLANNED_STEM = "E2E planned question {n} [e2e-function-model][{concept}]: what does the learning rate control?"
E2E_PLANNED_WRITTEN_STEM = (
    "E2E planned written question {n} [e2e-function-model][{concept}]: name what the learning "
    "rate controls."
)
E2E_PLANNED_EXPLANATION = "Scripted planned fixture: the learning rate sets the size of each update step."
_PLANNED_SLOT_RE = re.compile(r"^QUESTION (\d+): difficulty (\w+)\.(?: TARGET: ([a-z0-9_]+))?", re.M)
_PLANNED_CONCEPT_RE = re.compile(r"^CONCEPT: (.+)$", re.M)
_PLANNED_FORMAT_RE = re.compile(r"^FORMAT: (\w+)$", re.M)


def _e2e_planned(prompt: str) -> list[dict]:
    concept_m = _PLANNED_CONCEPT_RE.search(prompt)
    concept = concept_m.group(1).strip() if concept_m else "Recursion"
    fmt_m = _PLANNED_FORMAT_RE.search(prompt)
    fmt = fmt_m.group(1) if fmt_m else "multiple_choice"
    listed = set(re.findall(r"^- ([a-z0-9_]+): ", prompt, re.M))
    distractors = E2E_CHECK_ITEM_OPTIONS[1:]
    items = []
    for slot_text, _difficulty, target in _PLANNED_SLOT_RE.findall(prompt):
        n = int(slot_text)
        written = fmt in ("short_answer", "numeric", "symbolic") or (fmt == "mixed" and n % 2 == 0)
        if written:
            items.append({
                "slot": n,
                "question": E2E_PLANNED_WRITTEN_STEM.format(n=n, concept=concept),
                "type": "short_answer",
                "options": [],
                "option_misconceptions": [],
                "accepted_answers": [],
                "correct_answer": E2E_CHECK_ITEM_FINAL_ANSWER,
                "explanation": E2E_PLANNED_EXPLANATION,
            })
            continue
        correct_at = "ABCD".index(E2E_QUIZ_CORRECT_LABELS[(n - 1) % len(E2E_QUIZ_CORRECT_LABELS)])
        options = [d["text"] for d in distractors]
        tags = [d["misconception_key"] if d["misconception_key"] in listed else "" for d in distractors]
        if target and target not in tags and "" in tags:
            tags[tags.index("")] = target
        options.insert(correct_at, E2E_CHECK_ITEM_FINAL_ANSWER)
        tags.insert(correct_at, "")
        items.append({
            "slot": n,
            "question": E2E_PLANNED_STEM.format(n=n, concept=concept),
            "type": "multiple_choice",
            "options": options,
            "option_misconceptions": tags,
            "accepted_answers": [],
            "correct_answer": E2E_CHECK_ITEM_FINAL_ANSWER,
            "explanation": E2E_PLANNED_EXPLANATION,
        })
    return items


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
# #630: the handler must answer the shareability field too. Lecture notes are
# the course's material, so this keeps the lane's uploads SHARED — which is what
# the pre-#630 lane did, so no spec assertion moves. (Nothing is actually
# indexed in function mode: embedding is disabled below the seam per #439.)
E2E_DOC_SHAREABILITY = "course_material"
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
# Spec §13 A118: the scripted (prerequisite, dependent) relations — the step
# size only means something once the descent it scales is understood. Every
# name is one of E2E_DOC_CONCEPTS, so services/concept_prereqs.py resolves the
# set with zero drops (tests/test_e2e_function_handlers.py pins that). One
# payload serves both extraction variants: the flag-off output schema (the
# pre-A118 BaseConceptList) ignores the key, the flag-on ConceptList reads it.
# Written as a prerequisite edge only behind the upload_prereq_edges flag:
# frontend/e2e/upload.spec.ts asserts none with the flag off (the lane's
# default) and exactly this one, oriented, with it on. Keep all three in sync.
E2E_DOC_PREREQUISITES = [("Gradient Descent", "Learning Rate")]


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
        "shareability": E2E_DOC_SHAREABILITY,
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
        "prerequisites": [
            {"prerequisite": pre, "dependent": dep}
            for pre, dep in E2E_DOC_PREREQUISITES
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


# ── Concept scan (#151b) ────────────────────────────────────────────────────
#
# routes/documents.py's POST /doc/{id}/scan-concepts and
# /course/{id}/scan-concepts run concept_scan_agent — tool-less, structured
# `NewConcepts` output (names only, max 15 — see agents/concept_scan.py).
# Request-path: the route drives the agent via run_agent_sync and performs
# the graph write itself, so registering it is correct (the concept_describe
# reasoning; quiz_context stays deliberately unregistered — see the quiz
# section above). Unregistered, function mode's dispatch raised
# UnregisteredHandlerError, which the route's best-effort degrade (#151b)
# masked as an empty scan — hiding real scan coverage from the browser lane.
#
# Constants continue the upload fixture's gradient-descent theme so a scan
# after the scripted upload reads coherently in the UI. Backend contract
# test: tests/test_e2e_function_handlers.py. Keep them in sync.

E2E_SCAN_NEW_CONCEPTS = ["Momentum Optimization", "Convex Loss Surfaces"]

register_function_handler(
    "concept_scan",
    _structured_output({"concepts": E2E_SCAN_NEW_CONCEPTS}),
)


# ── Notetaker agent actions (F5a) ───────────────────────────────────────────
#
# routes/notes.py runs three request-path notetaker actions the browser awaits
# and renders:
#   POST /api/notes/{id}/summarize        → note_summary  (structured)
#   POST /api/notes/{id}/extract-concepts → note_concepts (structured)
#   POST /api/notes/{id}/chat             → note_chat      (plain text)
# None were registered here before, so function mode's dispatch raised
# UnregisteredHandlerError and each route 500'd. All three are request-path
# (the route awaits the agent and returns its output to the user), never a
# post-response BackgroundTask, so registering them is correct — the same
# reason concept_describe above is registered but quiz_context is not.
#
# note_summary/note_concepts have structured `output_type`s (NoteSummary /
# NoteConcepts), so each emits its fixed payload through the agent's OUTPUT
# tool via `_structured_output` — validated by the real output schema.
# note_chat returns plain `str`, so it emits a text ModelResponse like
# `_chat_tutor_handler`. note_chat carries function tools (read_active_note,
# search_course_materials, apply_graph_update), but the scripted text reply
# invokes none of them, holding this module's no-tool-calls / zero
# model-driven-writes constraint.

# NoteSummary.summary — a faithful 2–4 sentence Markdown summary.
E2E_NOTE_SUMMARY = (
    "[e2e-function-model] Deterministic note summary: the note captures "
    "recursion as a function that calls itself on a smaller subproblem, and "
    "flags the base case as the student's open question."
)
# NoteConcepts.concepts — Title-Case names (0–15) merged into the graph.
E2E_NOTE_CONCEPTS = ["Recursion", "Base Case"]
# note_chat plain-text reply, rendered in the notetaker's sidecar chat panel.
E2E_NOTE_CHAT_REPLY = (
    "[e2e-function-model] Deterministic note-chat reply: your note's base "
    "case is what stops the recursion from calling itself forever."
)


def _note_chat_handler(messages, info) -> ModelResponse:
    return ModelResponse(parts=[TextPart(content=E2E_NOTE_CHAT_REPLY)])


register_function_handler(
    "note_summary", _structured_output({"summary": E2E_NOTE_SUMMARY})
)
register_function_handler(
    "note_concepts", _structured_output({"concepts": E2E_NOTE_CONCEPTS})
)
register_function_handler("note_chat", _note_chat_handler)


# ── Check items (learning loop PKG-04) ─────────────────────────────────────
#
# Request-path in function mode: routes/documents.py runs the generator
# synchronously inside the upload when SAPLING_MODEL_MODE=function, since
# post-response handlers stay unregistered by design. Inert when the loop is
# off for the uploader (the kill-switch lane, or their learning_loop flag off);
# the default lane runs it (scripts/e2e-up.sh turns the flag on).
# For each E2E_DOC_CONCEPTS name — the function-mode upload's concepts, so
# each draft's `concept` matches the call's batch — one free and one teachback
# item, and CHECK_ITEM_MC_MIN_PER_CONCEPT mc_reason items (difficulties 1, 2):
# a function-mode pass leaves no concept below the A37 mc_reason floor, so it
# makes no top-up call. The top-up agent rides this same handler (it runs on
# the check_items slot) and keeps only its concept's mc_reason drafts.
# Prompts differ per (concept, format, difficulty) so every question_hash
# differs; the difficulty-1 prompts are the ones PKG-04 shipped.
# Backend contract test: tests/test_e2e_function_handlers.py. Keep in sync.

E2E_CHECK_ITEM_PROMPT_TEMPLATE = (
    "[e2e-function-model][{concept}][{format}] In one sentence, what does the "
    "learning rate control in gradient descent?"
)
E2E_CHECK_ITEM_REFERENCE = (
    "The learning rate controls the size of each parameter update step "
    "taken along the negative gradient."
)
# A34: every item states its final answer, verbatim from its reference (and,
# for mc_reason, the correct option's text) — never in the prompt.
E2E_CHECK_ITEM_FINAL_ANSWER = "The size of each parameter update step"
E2E_CHECK_ITEM_RUBRIC = [
    "Names the step size or update magnitude.",
    "Ties the step to the gradient direction.",
]
E2E_CHECK_ITEM_WRONG_KEY = "rate_is_iteration_count"
E2E_CHECK_ITEM_WRONG_TEXT = "Confuses the learning rate with the number of iterations."
# mc_reason (A22, A37): four option OBJECTS — the correct one first, flagged
# is_correct with no misconception, then three distractors, each stating its
# own misconception (a key and a sentence). The item lists no wrong_keys /
# wrong_texts of its own: code takes its common wrong reasons from the
# distractors (checks.common_wrong), so the stored common_wrong_json is
# E2E_CHECK_ITEM_MC_WRONG_KEYS paired with E2E_CHECK_ITEM_MC_WRONG_TEXTS. No
# letters: code letters the options and places the correct one at a slot keyed
# by the server secret over the question_hash (checks.lettered_options), so the
# stored letter of each concept's item is fixed by its prompt and the stack's
# ENCRYPTION_KEY.
E2E_CHECK_ITEM_MC_WRONG_KEYS = [
    E2E_CHECK_ITEM_WRONG_KEY,
    "rate_is_loss_value",
    "rate_sets_step_direction",
]
E2E_CHECK_ITEM_MC_WRONG_TEXTS = [
    E2E_CHECK_ITEM_WRONG_TEXT,
    "Treats the learning rate as the loss being minimised.",
    "Thinks the learning rate sets the direction of the step.",
]
E2E_CHECK_ITEM_OPTIONS = [
    {"text": E2E_CHECK_ITEM_FINAL_ANSWER, "is_correct": True,
     "misconception_key": None, "misconception_text": None},
    {"text": "The number of iterations to run", "is_correct": False,
     "misconception_key": E2E_CHECK_ITEM_MC_WRONG_KEYS[0],
     "misconception_text": E2E_CHECK_ITEM_MC_WRONG_TEXTS[0]},
    {"text": "The value of the loss", "is_correct": False,
     "misconception_key": E2E_CHECK_ITEM_MC_WRONG_KEYS[1],
     "misconception_text": E2E_CHECK_ITEM_MC_WRONG_TEXTS[1]},
    {"text": "The sign of the gradient", "is_correct": False,
     "misconception_key": E2E_CHECK_ITEM_MC_WRONG_KEYS[2],
     "misconception_text": E2E_CHECK_ITEM_MC_WRONG_TEXTS[2]},
]


def _e2e_check_item(
    concept: str, fmt: str, difficulty: int = CHECK_ITEM_DIFFICULTIES[0]
) -> dict:
    label = fmt if difficulty == CHECK_ITEM_DIFFICULTIES[0] else f"{fmt} {difficulty}"
    item = {
        "concept": concept,
        "format": fmt,
        "difficulty": difficulty,
        "prompt": E2E_CHECK_ITEM_PROMPT_TEMPLATE.format(concept=concept, format=label),
        "reference_answer": E2E_CHECK_ITEM_REFERENCE,
        "final_answer": E2E_CHECK_ITEM_FINAL_ANSWER,
        "rubric": E2E_CHECK_ITEM_RUBRIC,
        "wrong_keys": [E2E_CHECK_ITEM_WRONG_KEY],
        "wrong_texts": [E2E_CHECK_ITEM_WRONG_TEXT],
        "answer_kind": "free",
        "stepwise": False,
        "chunk_ids": [],
    }
    if fmt == "mc_reason":
        # The reference quotes the correct option's text and names no letter.
        item.update({"wrong_keys": [], "wrong_texts": [], "options": E2E_CHECK_ITEM_OPTIONS})
    return item


#: The plain drafter's scripted payload: every E2E_DOC_CONCEPTS concept's items.
E2E_CHECK_ITEMS = [
    item
    for name, _, _ in E2E_DOC_CONCEPTS
    for item in [
        *(_e2e_check_item(name, fmt) for fmt in CHECK_ITEM_FORMATS if fmt != "mc_reason"),
        *(
            _e2e_check_item(name, "mc_reason", level)
            for level in CHECK_ITEM_DIFFICULTIES[:CHECK_ITEM_MC_MIN_PER_CONCEPT]
        ),
    ]
]

# Spec §13 A140 (flag `varied_isomorphs`): the varied drafter and its top-up
# ride this slot with their own schema (VariedCheckItemDraft: answer_kind and
# stepwise left to code, the surface descriptor in), told apart by the output
# tool's $defs. They get the SAME items, each with a surface of its own: the
# n-th item of a concept the n-th of E2E_CHECK_ITEM_SURFACES, so no two items of
# a concept share a representation or a context.
# frontend/e2e/learn-varied-practice.spec.ts reads these. Keep them in sync.
E2E_CHECK_ITEM_SURFACES = [
    ("verbal", "e2e lecture recap"),
    ("applied", "e2e training run"),
    ("numeric", "e2e step sizes"),
    ("visual", "e2e loss curve"),
]
_VARIED_DRAFT = "VariedCheckItemDraft"
_DERIVED_FIELDS = ("answer_kind", "stepwise")


def _e2e_varied(items: list[dict]) -> list[dict]:
    """The items in the varied schema, the n-th of each concept on the n-th surface."""
    seen: dict[str, int] = {}
    out = []
    for item in items:
        n = seen.get(item["concept"], 0)
        seen[item["concept"]] = n + 1
        rep, context = E2E_CHECK_ITEM_SURFACES[n % len(E2E_CHECK_ITEM_SURFACES)]
        varied = {k: v for k, v in item.items() if k not in _DERIVED_FIELDS}
        varied.update(surface_representation=rep, surface_context=context)
        out.append(varied)
    return out


# Spec §13 A141 (flag `multi_concept_items`): the multi-concept drafter rides
# this slot with the plain schema; its message lists the combinations under
# agents/check_items_combo.py::COMBINATIONS_HEADER. Each listed label gets one
# item per format at MULTI_CONCEPT_DIFFICULTY, built like every E2E item with
# the label as its concept — so its question carries the
# `[e2e-function-model][<label>]` marker the alignment and key-check handlers
# read. frontend/e2e/learn-varied-practice.spec.ts reads these. Keep in sync.
_COMBINATIONS_HEADER = "Combinations (write items for each; copy the label exactly into `concept`)."
_LIST_LINE_RE = re.compile(r"^- (.+)$", re.M)


def _combination_labels(text: str) -> list[str]:
    """The labels a multi-concept request lists (none for any other request)."""
    start = text.find(_COMBINATIONS_HEADER)
    if start < 0:
        return []
    section = text[start:].split("\n\n", 1)[0]
    return _LIST_LINE_RE.findall(section)


def _check_items_handler(messages, info) -> ModelResponse:
    """The check_items slot: the plain drafter and the A37 top-up get
    E2E_CHECK_ITEMS exactly as before; the A140 varied drafter and top-up get
    the same items in their schema; the A141 multi-concept drafter gets one
    item per format for each combination it lists."""
    tool = info.output_tools[0]
    defs = (tool.parameters_json_schema or {}).get("$defs", {})
    labels = _combination_labels(_last_user_prompt_text(messages))
    if labels:
        items = [
            _e2e_check_item(label, fmt, MULTI_CONCEPT_DIFFICULTY)
            for label in labels
            for fmt in CHECK_ITEM_FORMATS
        ]
    else:
        items = _e2e_varied(E2E_CHECK_ITEMS) if _VARIED_DRAFT in defs else E2E_CHECK_ITEMS
    return ModelResponse(parts=[ToolCallPart(tool_name=tool.name, args={"items": items})])


register_function_handler("check_items", _check_items_handler)


# ── Check-item alignment check (spec §13 A119) ────────────────────────────
#
# Request-path in function mode like the drafting above: every drafting call's
# valid drafts go through the check_items_verify agent before they are stored,
# and an unavailable check drops them (fail closed) — so the lane needs a
# handler or no item would ever be stored. It keeps every E2E item exactly as
# drafted: every CRITERION line of every ITEM block is asked, and the concept
# each item tests is the one its question names in its
# `[e2e-function-model][<concept>]` marker (E2E_CHECK_ITEM_PROMPT_TEMPLATE) —
# the concept it was drafted for, one of the upload's E2E_DOC_CONCEPTS. An item
# without the marker tests "none" (the handler cannot tell, so it says so).
# Content-driven only in that way; ids come off the message's `ITEM <id>` /
# `CRITERION <id>:` lines (agents/check_items_verify.py::build_verify_prompt).
# Emits through the OUTPUT tool → the real schema validates. Contract:
# tests/test_e2e_function_handlers.py. Keep in sync.

E2E_VERIFY_WHY = "[e2e-function-model] The question asks for this."
E2E_VERIFY_ASKS = "[e2e-function-model] What the question asks."
_ITEM_HEAD_RE = re.compile(r"^ITEM (\S+)$", re.M)
_CRITERION_RE = re.compile(r"^CRITERION (\S+):", re.M)
_E2E_CONCEPT_RE = re.compile(r"\[e2e-function-model\]\[([^\]\n]+)\]")


# Spec §13 A141: the multi-concept alignment check rides this slot with its own
# schema (`components` rows), told apart by it: every criterion asked, and every
# `COMPONENT <id>:` of an item carrying the `[e2e-function-model][...]` marker
# needed (an item without it: none needed, so it is rejected — the handler
# cannot tell).
_COMPONENT_RE = re.compile(r"^COMPONENT (\S+):", re.M)


def _verify_handler(messages, info) -> ModelResponse:
    text, tool = _last_user_prompt_text(messages), info.output_tools[0]
    combining = "components" in (tool.parameters_json_schema or {}).get("properties", {})
    heads = list(_ITEM_HEAD_RE.finditer(text))
    criteria, concepts, components = [], [], []
    for n, head in enumerate(heads):
        block = text[head.end() : heads[n + 1].start() if n + 1 < len(heads) else len(text)]
        item = head.group(1)
        criteria += [
            {"item": item, "criterion": cid, "why": E2E_VERIFY_WHY, "asked": True}
            for cid in _CRITERION_RE.findall(block)
        ]
        marked = _E2E_CONCEPT_RE.search(block)
        concepts.append(
            {"item": item, "asks": E2E_VERIFY_ASKS, "concept": marked.group(1) if marked else "none"}
        )
        components += [
            {"item": item, "component": kid, "why": E2E_VERIFY_WHY, "required": bool(marked)}
            for kid in _COMPONENT_RE.findall(block)
        ]
    if combining:
        args = {"criteria": criteria, "components": components}
    else:
        args = {"criteria": criteria, "concepts": concepts}
    return ModelResponse(parts=[ToolCallPart(tool_name=tool.name, args=args)])


register_function_handler("check_items_verify", _verify_handler)


# ── Check-item key check (spec §13 A124) ──────────────────────────────────
#
# Request-path in function mode like the alignment check above: every drafting
# call's valid drafts are solved blind on the check_items_solve slot before
# they are stored, and an unavailable check drops them (fail closed) — so the
# lane needs a handler or no item would ever be stored. One handler serves both
# agents on the slot, told apart by the output tool's schema (the grader
# handler's way): the solve (`solutions`) and the free-text key match
# (`matches`).
# - The solve agrees with every E2E item's key, so every item the check_items
#   handler drafts is stored VERIFIED (canonical_verified): an mc_reason item's
#   answer is the letter of the OPTION line whose text is
#   E2E_CHECK_ITEM_FINAL_ANSWER (the letters are code's, keyed by the stack's
#   ENCRYPTION_KEY, so the handler reads them off the message); a short-answer
#   item carrying the `[e2e-function-model][<concept>]` marker answers
#   E2E_CHECK_ITEM_FINAL_ANSWER, the same token run as its key, so code settles
#   it and no match call is made. Anything else — no such option, no marker, a
#   number to compute — the handler cannot tell, so it says unsolvable (the item
#   is then held), never a guess.
# - The match says two answers agree only when they are the same text
#   (whitespace and case aside).
# Ids come off the message's `ITEM <id>` / `OPTION <letter>:` lines
# (agents/check_items_solve.py::build_solve_prompt,
# agents/check_items_key_match.py::build_match_prompt). Emits through the OUTPUT
# tool → the real schema validates. Contract: tests/test_e2e_function_handlers.py.
# Keep in sync.

E2E_SOLVE_BASIS = "[e2e-function-model] Read off the passages."
E2E_MATCH_WHY = "[e2e-function-model] Compared the two answers."
_OPTION_LINE_RE = re.compile(r"^OPTION (\S+): (.*)$", re.M)
_ANSWER_LINE_RE = re.compile(r"^ANSWER: (.*)$", re.M)
_MATCH_LINE_RE = re.compile(r"^(FIRST|SECOND) ANSWER: (.*)$", re.M)


def _e2e_solution(item: str, block: str) -> dict:
    answer_line = _ANSWER_LINE_RE.search(block)
    wants = answer_line.group(1) if answer_line else ""
    answer = ""
    if wants.startswith("the letter"):
        answer = next(
            (letter for letter, text in _OPTION_LINE_RE.findall(block)
             if text.strip() == E2E_CHECK_ITEM_FINAL_ANSWER),
            "",
        )
    elif wants == "short" and _E2E_CONCEPT_RE.search(block):
        answer = E2E_CHECK_ITEM_FINAL_ANSWER
    return {"item": item, "basis": E2E_SOLVE_BASIS, "solvable": bool(answer), "answer": answer}


def _e2e_match(item: str, block: str) -> dict:
    said = dict(_MATCH_LINE_RE.findall(block))
    first, second = (" ".join(said.get(k, "").split()).casefold() for k in ("FIRST", "SECOND"))
    return {"item": item, "why": E2E_MATCH_WHY, "same": bool(first) and first == second}


def _solve_handler(messages, info) -> ModelResponse:
    text, tool = _last_user_prompt_text(messages), info.output_tools[0]
    matching = "matches" in (tool.parameters_json_schema or {}).get("properties", {})
    heads = list(_ITEM_HEAD_RE.finditer(text))
    rows = []
    for n, head in enumerate(heads):
        block = text[head.end() : heads[n + 1].start() if n + 1 < len(heads) else len(text)]
        rows.append((_e2e_match if matching else _e2e_solution)(head.group(1), block))
    args = {"matches": rows} if matching else {"solutions": rows}
    return ModelResponse(parts=[ToolCallPart(tool_name=tool.name, args=args)])


register_function_handler("check_items_solve", _solve_handler)


# ── The quiz's item gates (spec §13 A145, flag `quiz_item_gates`) ─────────
#
# The A119 concept check, the A124 blind solve and the key match run on
# generated quiz questions on the `quiz_check` slot (the agents above, on
# another model). One handler for the slot, told apart by the output tool's
# schema: `concepts` → the alignment handler, otherwise the solve / match
# handler — the same answers they give check items (a question's concept is
# its `[e2e-function-model][<concept>]` marker; a multiple-choice question is
# solved to the option reading E2E_CHECK_ITEM_FINAL_ANSWER, anything else is
# unsolvable). One difference: a quiz question WITHOUT the marker (the plain
# E2E quiz's) tests the quizzed concept, the FIRST name the check lists
# (services/quiz_learning.py lists it first), so a plain quiz under the gates
# is served — as practice, its key unsolved and ungrounded — never dropped.

_CONCEPT_LINE_RE = re.compile(r"^- (.+)$", re.M)


def _quiz_check_handler(messages, info) -> ModelResponse:
    properties = (info.output_tools[0].parameters_json_schema or {}).get("properties", {})
    if "concepts" not in properties:
        return _solve_handler(messages, info)
    response = _verify_handler(messages, info)
    listed = _CONCEPT_LINE_RE.findall(_last_user_prompt_text(messages))
    call = response.parts[0]
    for row in call.args.get("concepts", []):
        if row["concept"] == "none" and listed:
            row["concept"] = listed[0].strip()
    return response


register_function_handler("quiz_check", _quiz_check_handler)


# ── Learning loop grader (PKG-05) ───────────────────────────────────────────
#
# grade_answer (a route helper, spec §13 A16) runs grader_agent as its OWN
# call, so the E2E lane needs a handler — for both slots: the second opinion
# runs the same agent on the "grader_second" slot (A22). Content-driven in
# exactly one way: a student answer containing E2E_GRADER_CORRECT_TOKEN grades
# every rubric item yes, anything else every item no. Rubric labels come off the
# prompt's `RUBRIC ITEM <label>:` lines (agents/grader.py::build_grader_message;
# each label is fresh and random per grading call, spec §13 A33, and grade()
# maps labels back), so any seeded item works. `addresses_grader` and
# `contradicts_reference` are always false (spec §13 A33: an E2E answer never
# addresses the grader, and its all-yes is no conflict). E2E_GRADER_CONFIDENCE
# sits above GRADER_LOW_CONFIDENCE (and so above the second-opinion floor): E2E
# evidence is full-weight, and the second slot's full second opinion fires only
# to confirm a credited verdict on an answer with a suspicion signal or a
# conflicted all-yes (A33) — never on the bare token, which is one identifier.
# Every credited item quotes the whole student answer as its `support`, and the
# span check grade() then makes on the grader_second slot (grader-guard round
# a33, the coordinator's ruling: same agent, output type `SpanVerdicts`, told
# apart here by the output tool's schema) says yes to a span holding the token.
# So a token answer costs two runs: the grade and its span check. Emits through
# the OUTPUT tool → the real schema validates. Request-path once PKG-07's
# /check/answer calls grade_answer (no route does yet). Contract:
# tests/test_learning_check_tool.py; PKG-13's learn-loop.spec.ts types the token.
#
# PKG-10: a (not correct) answer holding E2E_GRADER_WRONG_REASON_TOKEN asserts the
# item's FIRST listed common wrong reason (`matched_wrong_key` = the first
# `COMMON WRONG REASON <key>:` line of the message); grade_answer then takes the
# key through decisions.match_wrong_reason with this result as `prior` (no
# decision run). Two such answers on two isomorphs of one concept record a
# misconception and make the next feedback turn a confronting one (two in the
# probe record it too, never confronted — spec §13 A120). Contract:
# tests/test_e2e_function_handlers.py.

E2E_GRADER_CORRECT_TOKEN = "E2E_GRADER_CORRECT"
E2E_GRADER_WRONG_REASON_TOKEN = "E2E_GRADER_WRONG_REASON"
E2E_GRADER_CONFIDENCE = 0.95
E2E_GRADER_HINT = "[e2e-function-model] Deterministic grader hint: check the base case first."

_RUBRIC_ID_RE = re.compile(r"^RUBRIC ITEM (\S+):", re.M)
_WRONG_KEY_RE = re.compile(r"^COMMON WRONG REASON (\S+):", re.M)


def _grader_handler(messages, info) -> ModelResponse:
    text, tool = _last_user_prompt_text(messages), info.output_tools[0]
    verdict = "yes" if E2E_GRADER_CORRECT_TOKEN in text else "no"
    labels = _RUBRIC_ID_RE.findall(text)
    properties = (tool.parameters_json_schema or {}).get("properties", {})
    if "withdrawn" in properties:
        # the context check (A33 finish): an E2E answer never takes anything back
        labels = re.findall(r"^SPAN (\S+):$", text, re.M)
        args = {"withdrawn": [f"{rid}:no" for rid in labels]}
        return ModelResponse(parts=[ToolCallPart(tool_name=tool.name, args=args)])
    if "addresses_grader" not in properties:
        # the span check (round a33): its spans are the grading run's quotes below
        # A33 finish: the span check reports the span asserted before its verdicts
        args = {
            "asserted": [f"{rid}:{verdict}" for rid in labels],
            "item_results": [f"{rid}:{verdict}" for rid in labels],
        }
        return ModelResponse(parts=[ToolCallPart(tool_name=tool.name, args=args)])
    answer = " ".join(line[2:] for line in text.splitlines() if line.startswith("> "))
    listed = _WRONG_KEY_RE.findall(text)  # never a quoted answer line ("> " first)
    hit = verdict == "no" and E2E_GRADER_WRONG_REASON_TOKEN in answer
    matched = listed[0] if hit and listed else ""
    args = {
        "addresses_grader": False,  # A33: an E2E answer never addresses the grader
        "contradicts_reference": False,  # A33 (round a33): nor contradicts the reference
        "item_results": [f"{rid}:{verdict}" for rid in labels],
        # round a33: each credited item quotes the whole answer, which holds the token
        "support": [f"{rid}: {answer}" for rid in labels] if verdict == "yes" else [],
        "confidence": E2E_GRADER_CONFIDENCE,
        "matched_wrong_key": matched,
        "feedback_hint": E2E_GRADER_HINT,
    }
    return ModelResponse(parts=[ToolCallPart(tool_name=tool.name, args=args)])


register_function_handler("grader", _grader_handler)
register_function_handler("grader_second", _grader_handler)


# ── Learning loop decision seam (PKG-05b) ───────────────────────────────────
#
# Content-driven in exactly one way (like the grader handler): E2E_DECISION_YES_TOKEN in
# the prompt → "yes" / the first listed OPTION key; else "no" / "none". The run's output
# type is read off info.output_tools[0], so the REAL schema validates. Keep in sync with
# tests/test_learning_decisions.py and tests/test_e2e_function_handlers.py.
E2E_DECISION_YES_TOKEN = "E2E_DECISION_YES"
E2E_DECISION_CONFIDENCE = 0.9
_OPTION_KEY_RE = re.compile(r"^OPTION (\S+):", re.M)


def _decision_handler(messages, info) -> ModelResponse:
    text, tool = _last_user_prompt_text(messages), info.output_tools[0]
    hit = E2E_DECISION_YES_TOKEN in text
    if "choice" in (tool.parameters_json_schema or {}).get("properties", {}):
        keys = _OPTION_KEY_RE.findall(text)
        args = {
            "choice": keys[0] if hit and keys else "none",
            "confidence": E2E_DECISION_CONFIDENCE,
        }
    else:
        args = {"answer": "yes" if hit else "no", "confidence": E2E_DECISION_CONFIDENCE}
    return ModelResponse(parts=[ToolCallPart(tool_name=tool.name, args=args)])


register_function_handler("learning_decision", _decision_handler)


# ── Learning loop tutor (PKG-07) ───────────────────────────────────────────
#
# Served for ALL THREE tier slots (the loop route picks the slot per run; spec
# §3.5). The loop agent has no grader tool and this handler scripts no tool call
# (module rule: no tool calls, zero model-driven writes). Since the PKG-07
# unblock (S1) the agent's output is the STRUCTURED turn
# (learning.turn_shape.LoopTurnOut via PromptedOutput), so the handler answers
# with the turn's JSON as one text part — which the streamed seam replays as
# text deltas, exactly the shape stream_structured_turn parses. The turn passes
# the output validator at the TIGHTEST limits (a one-sentence body, H0/H1), so
# no E2E loop turn burns an output retry. E2E_LOOP_TUTOR_REPLY is the RENDERED
# turn (render_turn), the text the route persists and
# frontend/e2e/learn-loop.spec.ts (PKG-13) can assert. Keep in sync with
# tests/test_loop_tutor_agent.py and tests/test_e2e_function_handlers.py.
E2E_LOOP_TUTOR_TURN = {
    "key_idea": (
        "[e2e-function-model] A recursive function needs a base case it is "
        "guaranteed to reach."
    ),
    "body": "Try writing the base case for factorial before anything else.",
    "question": "Which input should stop the recursion?",
}
E2E_LOOP_TUTOR_REPLY = render_turn(E2E_LOOP_TUTOR_TURN)



# ── Learning loop tutor by phase (PKG-13) ──────────────────────────────────
#
# One handler, fixed turns keyed on the PHASE of the run: the hint turn, the
# feedback turn, the answer-check teach turn (spec §13 A121, below), and
# everything else (teach, a quiz-ask session's opener — a probe-phase opener
# is a template and runs no model) the PKG-07 turn above. The phase is read
# off THIS run's user prompt — the prefix
# services/loop/ assembles with agents.loop_tutor.phase_prefix — never off
# the history, where an earlier hint turn's prefix would answer a later teach
# turn with the hint reply. The pattern values are copied verbatim from
# agents/loop_tutor.py::_PHASE_RULES; tests/test_e2e_function_handlers.py pins
# that each is real prompt source, sits in its own phase's prefix only, and is
# absent from the system prompt. Every turn is valid at the tightest limits
# (H0, a one-sentence body, nothing given), so no E2E loop turn burns an output
# retry. The served text can differ from the *_REPLY render: at H0/H1 the route
# serves the key idea of a hint or a correct-verdict feedback from code, at H2
# the hint question, and a released feedback leads with "The answer: …"
# (services/loop/served.py::served_render / released_lead). Asserted verbatim by
# frontend/e2e/learn-loop.spec.ts. Keep in sync.
E2E_LOOP_PHASE_PATTERNS: dict[str, str] = {
    "hint": "the student asked for help with the check item below",
    "feedback": "the student has just submitted an answer to the check",
}
# The body and question reach the student verbatim at H0/H1 (the key idea is
# then code's); the journey asserts these two.
E2E_LOOP_HINT_BODY = "Reread the item and name the one thing it wants you to state."
E2E_LOOP_HINT_QUESTION = "What is the first thing you need before you can answer this?"
E2E_LOOP_HINT_TURN = {
    "key_idea": (
        "[e2e-function-model] Deterministic loop hint: start from what the check "
        "item asks for."
    ),
    "body": E2E_LOOP_HINT_BODY,
    "question": E2E_LOOP_HINT_QUESTION,
}
E2E_LOOP_HINT_REPLY = render_turn(E2E_LOOP_HINT_TURN)
E2E_LOOP_FEEDBACK_BODY = "Look at which part of the item your answer addressed."
E2E_LOOP_FEEDBACK_QUESTION = "How would you check that part yourself next time?"
E2E_LOOP_FEEDBACK_TURN = {
    "key_idea": (
        "[e2e-function-model] Deterministic loop feedback: compare your answer "
        "with what the check item asks for."
    ),
    "body": E2E_LOOP_FEEDBACK_BODY,
    "question": E2E_LOOP_FEEDBACK_QUESTION,
}
E2E_LOOP_FEEDBACK_REPLY = render_turn(E2E_LOOP_FEEDBACK_TURN)

# The seeded loop check items (db/seed_local_rich.py::seed_learning_loop imports
# these). Every item's PLAINTEXT prompt starts with E2E_LOOP_PROBE_PROMPT (the
# journey asserts the probe card and the check pose show it); the reference
# closes with "Final answer: <E2E_LOOP_FINAL_ANSWER>." (spec §13 A34: the final
# answer is copied verbatim from the reference and never printed by the
# prompt). The E2E grader above grades on E2E_GRADER_CORRECT_TOKEN anywhere in
# its message, which quotes the prompt AND the reference — so neither may hold
# the token, or every answer (a wrong one, an idk) would be graded correct.
E2E_LOOP_PROBE_PROMPT = (
    "[e2e-loop] Check item: type the e2e grader's correct token to be marked correct."
)
E2E_LOOP_FINAL_ANSWER = "the kilo sentinel phrase"
E2E_LOOP_REFERENCE = (
    "A seeded loop item is closed by its fixed sentinel wording. "
    f"Final answer: {E2E_LOOP_FINAL_ANSWER}."
)


# ── Spec §13 A121: the turn template's loop constants ──────────────────────
#
# On by default: the probe-phase session opener is a TEMPLATE (no model run, no
# teaching, no question) — learn-loop.spec.ts asserts it on the check-in card —
# and a teach turn that poses the concept's check is served WITHOUT the question
# the model wrote (E2E_LOOP_CHECK_POSING_REPLY: the PKG-07 turn, question
# dropped). With the `loop_tutor_v2` flag on, a teach turn answering the
# student's reply to the tutor's own question carries the [ANSWER CHECK] line
# (agents/loop_tutor.py::ANSWER_CHECK_LINE; the pattern is copied from it and
# pinned by tests/test_e2e_function_handlers.py), and its turn must fill
# answer_verdict: the seam judges a reply carrying E2E_LOOP_CHAT_ANSWER_TOKEN
# correct and any other reply not_an_answer (a follow-up question, say), so the
# quiz "Ask about this" follow-up still gets the plain teach reply. A correct
# verdict is served as its plain line first, with no "Key idea:" label; a turn
# that also poses a check drops its question (services/loop/served.py::
# served_render) — E2E_LOOP_ANSWER_REPLY. Flag off, no prefix carries the
# pattern, so the seam never answers with a verdict.
E2E_LOOP_PROBE_OPENER = LOOP_PROBE_OPENER
E2E_LOOP_PLAN_OPENER = LOOP_PLAN_OPENER
E2E_LOOP_CHECK_POSING_REPLY = render_turn(E2E_LOOP_TUTOR_TURN, TurnTemplate(question=False))
E2E_LOOP_ANSWER_CHECK_PATTERN = "Your previous turn ended with a question, and the student's"
E2E_LOOP_CHAT_ANSWER_TOKEN = "E2E_CHAT_ANSWER_RIGHT"
E2E_LOOP_ANSWER_LEAD = ANSWER_VERDICT_LEADS["correct"]
E2E_LOOP_ANSWER_TURN = {"answer_verdict": "correct", **E2E_LOOP_TUTOR_TURN}
E2E_LOOP_NOT_AN_ANSWER_TURN = {"answer_verdict": "not_an_answer", **E2E_LOOP_TUTOR_TURN}
#: The answer-check turn as served when it also poses the concept's next check
#: (the flag-on journey's second teach turn): the verdict line, the key idea
#: unlabelled, the body — and no question.
E2E_LOOP_ANSWER_REPLY = render_turn(
    E2E_LOOP_ANSWER_TURN, TurnTemplate(label=True, question=False, answer_check=True)
)


# ── Spec §13 A138 / A139: the teach-phase prompts' loop constants ───────────
#
# Flag-on prompt paths only (`segment_prequestion`, `self_explanation_prompts`);
# no flag-off prefix carries either pattern, so every flag-off E2E reply above
# is unchanged. The patterns are copied from agents/loop_tutor.py's
# PREQUESTION_LINE and SELF_EXPLAIN_ACK_LINE (tests/test_e2e_function_handlers.py
# pins that each is real prompt source and sits only in its own prefix).
#   • A138: the teach turn that explains an answered prequestion — code serves
#     the answer above it ("The answer: …", learning/prequestion.answer_lead),
#     then this turn (E2E_LOOP_PREQUESTION_REPLY, labelled as any default teach
#     turn is). The seeded prequestion items (scripts/seed_learning_teach_prompts.py)
#     are multiple choice with B correct, and B is their OWN sentinel,
#     E2E_LOOP_PREQUESTION_ANSWER — never E2E_LOOP_FINAL_ANSWER, so the
#     learn_loop oracle tells a prequestion's release from a check's (review
#     fix: one shared sentinel let the first answered prequestion count as a
#     release of every check's answer).
#   • A139: the first model turn after a self-explanation reply opens its body
#     with an acknowledgement — the phase's own turn with its body replaced by
#     E2E_LOOP_SELF_EXPLAIN_ACK_BODY. The prompts themselves are code's text
#     (learning/self_explain.py), never the model's.
E2E_LOOP_PREQUESTION_PATTERN = "Before any teaching on this concept the student was asked the"
E2E_LOOP_PREQUESTION_TURN = {
    "key_idea": (
        "[e2e-function-model] Deterministic prequestion explanation: the answer rests "
        "on the one idea the question tests."
    ),
    "body": "Set your guess beside the answer above and find where they part.",
    "question": "What would you check first on a question like this next time?",
}
E2E_LOOP_PREQUESTION_REPLY = render_turn(E2E_LOOP_PREQUESTION_TURN)
E2E_LOOP_PREQUESTION_ANSWER = "the papa sentinel phrase"
E2E_LOOP_SELF_EXPLAIN_ACK_PATTERN = "The student has answered your last 'why' question"
E2E_LOOP_SELF_EXPLAIN_ACK_BODY = "Thanks for putting that step into your own words."


def _loop_tutor_handler(messages, info) -> ModelResponse:
    prompt = _last_user_prompt_text(messages)
    if E2E_LOOP_PHASE_PATTERNS["hint"] in prompt:
        turn = E2E_LOOP_HINT_TURN
    elif E2E_LOOP_PHASE_PATTERNS["feedback"] in prompt:
        turn = E2E_LOOP_FEEDBACK_TURN
    elif E2E_LOOP_ANSWER_CHECK_PATTERN in prompt:
        turn = (
            E2E_LOOP_ANSWER_TURN
            if E2E_LOOP_CHAT_ANSWER_TOKEN in prompt
            else E2E_LOOP_NOT_AN_ANSWER_TURN
        )
    elif E2E_LOOP_PREQUESTION_PATTERN in prompt:
        turn = E2E_LOOP_PREQUESTION_TURN
    else:
        turn = E2E_LOOP_TUTOR_TURN
    if E2E_LOOP_SELF_EXPLAIN_ACK_PATTERN in prompt:
        turn = {**turn, "body": E2E_LOOP_SELF_EXPLAIN_ACK_BODY}
    return ModelResponse(parts=[TextPart(content=json.dumps(turn))])


# One handler for the three tier slots (spec §13 A15): the tier is chosen in
# code per run, so the scripted reply never depends on it.
for _slot in ("loop_tutor_lite", "loop_tutor", "loop_tutor_deep"):
    register_function_handler(_slot, _loop_tutor_handler)


# ── Session close (PKG-09) ─────────────────────────────────────────────────
# The close agent runs on POST /api/learn/loop/close and the loop end_session
# when the session has evidence (spec §13 A25). Its structured output passes
# agents.session_close.served_close unchanged: one question, an "If …, then …"
# plan, no key it was not given. PKG-13's journey asserts E2E_CLOSE_IF_THEN in
# the rendered close. Keep in sync with tests/test_e2e_function_handlers.py.
E2E_CLOSE_SUMMARY = (
    "[e2e-function-model] Deterministic session close: the student checked "
    "recursion base cases and moved from unsure to mostly sure; the off-by-one "
    "boundary is still open."
)
E2E_CLOSE_SELF_EVAL = (
    "[e2e-function-model] Which step of the base-case argument were you least sure of?"
)
E2E_CLOSE_IF_THEN = (
    "If the next session opens with a recursion check, then write the base case "
    "before the recursive step."
)
E2E_CLOSE_MISCONCEPTIONS: list[str] = []

register_function_handler(
    "session_close",
    _structured_output({
        "summary": E2E_CLOSE_SUMMARY,
        "self_eval_prompt": E2E_CLOSE_SELF_EVAL,
        "if_then_plan": E2E_CLOSE_IF_THEN,
        "open_misconception_keys": E2E_CLOSE_MISCONCEPTIONS,
    }),
)

# ── Typed decision seam / tutor router (#640, ADR 0027) ─────────────────────
#
# services/decisions.py runs the `decision` agent on the FunctionModel whenever
# SAPLING_MODEL_MODE=function and the `decision_router` flag is on (any on
# variant runs the `function` backend there; scripts/e2e-up.sh switches the
# flag on for the lane), and the observe-only tutor router
# (services/tutor_router.py) calls it once per student chat turn. Request-path (scheduled from the chat routes on the
# request's own loop, not a post-response BackgroundTask), so it is registered
# — unregistered, every tutor turn would log a handled
# UnregisteredHandlerError and emit an all-defaults decision.
#
# Fixed answers for the router's five keys, every one ABOVE the default
# confidence floor so the lane exercises the "answer applied" path rather than
# the defaults path. They are deliberately the answers the router's safe
# defaults would give anyway (retrieve, no rewrite, not graded, not an
# injection) plus a complexity — and nothing acts on them (observe-only), so
# no journey's visible behaviour depends on them. Emitted through the agent's
# OUTPUT tool, validated by the real DecisionOutput schema. Pinned by
# tests/test_e2e_function_handlers.py; keep in sync.

# The constant lives in the side-effect-free agents/_decision_fixtures.py so
# the showcase module can register the SAME answers without importing this one.
# The E2E_* alias is kept on purpose: this module's constants are the names
# specs and tests/test_e2e_function_handlers.py pin (the "byte-match to an
# E2E_* constant" tell in CLAUDE.md).
E2E_DECISION_ANSWERS = DECISION_ANSWERS

register_function_handler(
    "decision", _structured_output({"answers": E2E_DECISION_ANSWERS})
)


def _topic_checklist_handler(messages, info) -> ModelResponse:
    # Fixed course-fixture topics, with evidence IDs taken from the request so
    # the production reference validator is exercised rather than bypassed.
    payload = json.loads(_last_user_prompt_text(messages))
    topics = []
    for name in ("Recursion", "Variables and Types"):
        source = next((s for s in payload["sources"] if s["text"] == name), None)
        if source:
            topics.append({"name": name, "description": f"Study {name.lower()} using your course materials.",
                           "importance": 0.9, "source_ids": [source["id"]]})
    return _structured_output({"topics": topics})(messages, info)


register_function_handler("topic_checklist", _topic_checklist_handler)

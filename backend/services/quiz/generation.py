"""
backend/services/quiz/generation.py — moved from routes/quiz.py (#118).

Quiz generation: the agent run (`_quiz_via_agent`), its error contract
(`_generate_or_502`), generation telemetry, and the POST /generate
handler body.

Function bodies are verbatim from the route; names (leading
underscores included) are unchanged, and routes/quiz.py re-exports them.
"""
import asyncio
import logging
import uuid
from typing import NamedTuple

from starlette.concurrency import run_in_threadpool
from starlette.requests import Request

from pydantic_ai.exceptions import UsageLimitExceeded, UnexpectedModelBehavior

from agents import ORCHESTRATOR_LIMITS, TOPUP_LIMITS
from agents.quiz import quiz_agent, Quiz, PROMPT_VERSION
from agents.quiz_planned import (
    PROMPT_VERSION as PLANNED_PROMPT_VERSION,
    build_message as build_planned_message,
    quiz_planned_agent,
)
from agents.deps import SaplingDeps
from agents.usage import record_agent_usage, served_model_name
from db.connection import table
from models import GenerateQuizBody
from services import events_service
from services.auth_guard import guard_off_loop, require_admin, require_self
from services.llm_budget import LLMBudgetExceeded
from services.quiz.config import (
    QUIZ_GENERATE_RATE_LIMIT,
    QUIZ_GENERATE_RATE_WINDOW_SEC,
    QUIZ_GENERATION_TIMEOUT_SEC,
    QUIZ_TOPUP_DROP_RATIO,
    QUIZ_TOPUP_MAX_RETRIES,
    REQUESTED_DIFFICULTIES,
)
from services.request_limits import aclaim_rate_limit
from services import quiz_learning
from services.feature_flags import flag_on
from services.quiz_learning import GenerationPlan
from learning import quiz_evidence, quiz_gates
# fastapi's HTTPException, through the package's one fastapi seam (errors.py:
# QuizAPIError IS an HTTPException, the #540 A3 envelope contract).
from services.quiz.errors import HTTPException, QuizAPIError, QuizErrorCode
from services.encryption import encrypt_json
from services.quiz.grading import WRITTEN_TYPES
from services.academics import course_offering_ids
from services.exam_proximity import days_until_next_exam, exam_prompt_line
from services.quiz.signals import CourseScope, QuizSignals, gather_signals
from services.quiz.signals import prompt_block as signal_block
from services.quiz.identity import question_hash, normalize_text, wire_question_hash
from services.quiz.repetition import recent_question_identities
from services import prompt_dimensions
from services.request_context import current_request_id
from services.quiz.attempts import _insert_attempt
from services.quiz.grounding import (
    CourseMaterial,
    CourseRow,
    _UNKNOWN_MATERIAL,
    _course_material,
    _course_row,
    _do_not_repeat_block,
    _log_rag_uncovered,
)
from services.quiz.limits import _daily_spend_exceeded, _refund_generate_slot
from services.quiz.practice import _renumber, _reserved_misses
from services.quiz.wire import (
    _agent_question_to_wire,
    _client_questions,
    _record_plan,
    _resolved_difficulty,
)

# Log records keep the name they had in routes/quiz.py before the #118 split:
# the move must not change what an operator (or a caplog test) filters on.
logger = logging.getLogger("routes.quiz")


def _log_generation_failed(body, request_id: str | None, reason: str) -> None:
    """#544 F3: make a 502 the student saw a 502 an admin can count."""
    events_service.log_event(
        "quiz.generation_failed",
        category="error",
        user_id=body.user_id,
        request_id=request_id,
        payload={
            "concept_node_id": body.concept_node_id,
            "difficulty": body.difficulty,
            "num_questions": body.num_questions,
            "reason": reason,
            # F6: whatever the prompt had managed to assemble before it
            # failed. An ungrounded timeout and a grounded one are different
            # diagnoses, and the failure path is where that matters most.
            **prompt_dimensions.snapshot(),
        },
    )


def _record_answer_key_flag(
    body: GenerateQuizBody, quiz_id: str, request_id: str | None,
) -> None:
    """#546: make the deprecated `include_answer_key` flag's remaining
    callers countable, not merely logged.

    Deleting the parameter is gated on one number reaching zero — nobody
    still asks for the client-side answer key — and a `logger.info` is not
    a number: nothing rolls log lines up, and the grace window exists
    precisely for callers nobody is watching the logs for. #375's admin
    analytics aggregates the `events` table by event_type, so one event per
    population is a count an admin can already read off the existing
    endpoint, with no schema or endpoint work (#117 convention).

    Three caller populations, told apart by whether the field was on the
    wire at all (`model_fields_set`) rather than by its value — because the
    default flip makes "omitted" and "explicit false" the same *response*
    but very different *callers*:

    * explicit true  → ``quiz.answer_key_served``. The straggler the grace
      window is for; the response really carried the key. This is the count
      that must be zero before the parameter is deleted.
    * omitted        → ``quiz.answer_key_flag_omitted``. A flag-unaware
      caller, already on the keyless shape. Deletion is a no-op for them,
      but they are the population whose response shape silently changed at
      the flip, and before this they had no telemetry at all.
    * explicit false → nothing. Every shipped #537 client sends this on
      every generate; an event here would be a row per quiz, swamping the
      rollup it lands in to say something already known.

    Two event types rather than one carrying a `flag` payload field: the
    by_event_type rollup does not break payloads out, so a single type
    would surface one number mixing the population that blocks deletion
    with the one that doesn't — exactly the distinction the gate needs.

    Fire-and-forget like the `quiz.started` emit below: `log_event` never
    blocks and swallows its own failures, so telemetry can't fail a
    generation that already succeeded.
    """
    if "include_answer_key" not in body.model_fields_set:
        events_service.log_event(
            "quiz.answer_key_flag_omitted",
            category="usage",
            user_id=body.user_id,
            request_id=request_id,
            payload={"quiz_id": quiz_id},
        )
        return
    if not body.include_answer_key:
        return
    logger.info(
        "quiz: generate served the client-side answer key "
        "(include_answer_key=true, deprecated — #546) quiz_id=%s", quiz_id,
    )
    events_service.log_event(
        "quiz.answer_key_served",
        category="usage",
        user_id=body.user_id,
        request_id=request_id,
        payload={"quiz_id": quiz_id},
    )


# Per-request model override map. Mirrors the chat tutor's
# fast/smart toggle so quiz body's `model_pref` resolves to the same
# model strings as Learn. None falls through to the agent's
# task-default model from agents/_providers.py::model_for("quiz").
_PREF_MODEL_NAMES: dict[str, str] = {
    "fast": "claude-haiku-5-5",
    "smart": "claude-sonnet-5-5",
}


def _resolve_model_pref(model_pref: str | None):
    """Build a provider-model override for the per-request fast/smart
    preference, or return None to use the agent's default.

    `override_model` is imported lazily so that constructing a provider
    (which reads its API key at call time) only happens when an override
    is actually requested — not at module import. agents.quiz is already
    in this route's import graph, so this isn't about import-path isolation; it's about deferring the
    one runtime side-effect (the provider build) to the request that
    needs it.
    """
    if not model_pref:
        return None
    from agents._providers import _model_mode, override_model
    if _model_mode() != "real":
        # #391 seam: the per-request fast/smart override must not bypass
        # SAPLING_MODEL_MODE by constructing a live provider model. Same fix as
        # routes/learn.py (#392) — there the browser always sends a pref;
        # the quiz UI does not send one today, but any client that did would
        # silently put a live provider back in the function-mode path. Fall
        # through to the agent's default model, which model_for("quiz")
        # already built for the active mode.
        return None
    name = _PREF_MODEL_NAMES.get(model_pref)
    if not name:
        return None
    return override_model(name, "quiz")


def _writer_model_name(model_pref: str | None) -> str:
    """The name of the model that writes this request's questions: the
    fast/smart override exactly when `_resolve_model_pref` builds one, else
    the quiz slot's model. Learning-loop spec §13 A145: the item gates' blind
    solve verifies a key only on a model other than this one (A124)."""
    from agents._providers import _model_mode, model_name_for

    name = _PREF_MODEL_NAMES.get(model_pref) if model_pref else None
    if name and _model_mode() == "real":
        return name
    return model_name_for("quiz")


class GeneratedQuiz(NamedTuple):
    """What one generation produced.

    `exam_days_away` rides back with the questions rather than being resolved
    again by the caller: it is used for the prompt here and stored on the
    attempt there, and two lookups could disagree if an exam were entered
    between them.
    """

    questions: list[dict]
    exam_days_away: int | None = None


_MCQ_TOPUP_RULE = (
    "multiple_choice items need exactly 4 options and correct_answer must "
    "appear VERBATIM in options."
)
_WRITTEN_TOPUP_RULE = (
    "for short_answer, numeric and symbolic items options must be empty and "
    "correct_answer is the canonical answer (short_answer: a term or brief fact "
    "of at most 8 words, never a sentence; numeric: a plain number or fraction; "
    "symbolic: an expression in the supported grammar, with single-letter "
    "variables only and no words or Greek-letter names)."
)


def _topup_format_rule(question_format: str) -> str:
    """The format contract the top-up retry restates — the one that applies
    to the requested format, so a written quiz is never told to put its
    answer in options it must not have."""
    if question_format == "multiple_choice":
        return _MCQ_TOPUP_RULE
    if question_format in WRITTEN_TYPES:
        return f"{question_format} only; {_WRITTEN_TOPUP_RULE}"
    return f"{_MCQ_TOPUP_RULE} And {_WRITTEN_TOPUP_RULE}"


def _quiz_user_message(
    *, concept_name: str, material, routing_msg: str, plan, question_format: str, recent,
) -> str:
    """The generation run's user message: the routing message over the course
    material — or, under a plan (learning-loop spec §13 A144), the planned
    agent's message: told what to write and nothing else (the concept, the
    plan's question lines and the misconception keys) over the same grounding
    and do-not-repeat list."""
    if plan is not None:
        return build_planned_message(
            concept_name=concept_name,
            question_format=question_format,
            specs=plan.specs,
            keys=plan.keys,
            material_block=material.block,
            recently_asked=_do_not_repeat_block(recent),
        )
    if material.block:
        return (
            "COURSE MATERIAL for '" + concept_name + "':\n\n" + material.block
            + "\n\n[GENERATE QUIZ]\n" + routing_msg
        )
    return routing_msg


def _topup_message(*, user_message: str, plan, missing: int, question_format: str,
                   concept_name: str, filled_slots: set[int], material, recent,
                   already: str) -> str:
    """#543 E2's top-up request: more questions of the requested format — or,
    under a plan (A144), the plan slots still open — naming the stems already
    in the quiz so a deterministic model does not re-emit them."""
    if plan is None:
        topup_msg = (
            f"{user_message}\n\n[TOP-UP] Some questions were rejected for "
            f"format errors. Generate {missing} MORE questions on the same "
            f"concept. Remember: {_topup_format_rule(question_format)}"
        )
    else:
        topup_msg = build_planned_message(
            concept_name=concept_name,
            question_format=question_format,
            specs=[s for s in plan.specs if s.slot not in filled_slots][:missing],
            keys=plan.keys,
            material_block=material.block,
            recently_asked=_do_not_repeat_block(recent),
        ) + "\n\n[TOP-UP] Write only the QUESTION lines above."
    if already:
        topup_msg += (
            f"\n\nDo NOT repeat any of these questions, which are "
            f"already in the quiz:\n{already}"
        )
    return topup_msg


async def _quiz_via_agent(
    *,
    user_id: str,
    course_id: str | None,
    concept_node_id: str,
    concept_name: str,
    num_questions: int,
    difficulty: str,
    use_shared_context: bool,
    request_id: str,
    model_pref: str | None = None,
    question_format: str = "multiple_choice",
    times_studied: int | None = None,
    has_graph: bool | None = None,
    plan: GenerationPlan | None = None,
    gate=None,
) -> GeneratedQuiz:
    """Run quiz_agent and return questions in the legacy wire shape.

    Learning-loop spec §13 A144/A145, both None while their flags are off
    (and then nothing below changes): `plan` runs the planned agent
    (agents/quiz_planned.py) on the learner model's question specs instead of
    quiz_agent, and `gate` — an async `(questions, material) -> GateRun`
    (services/quiz_learning.py::gate_questions) — checks each run's new
    questions before they are kept; a dropped question counts toward the
    bounded top-up like a drifted one.

    `has_graph` is what the CALLER knows about this student's knowledge graph
    in this course, for the F5 dark-scope report in `quiz_signals`. Left None
    on purpose: the request path (`generate_quiz` → `_generate_or_502`) read
    an owner-scoped `graph_nodes` row on its way here and passes True, but
    `scripts/benchmark_quiz.py` calls this same function with a fixture user
    that has none — so asserting the fact in here would make every benchmark
    run write a false `quiz.tool_empty`.

    The agent's tools (read_concepts_for_user, read_misconceptions_for_course)
    pull weak-area + class misconception data themselves, replacing the
    manual prompt-string augmentation that used to live in generate_quiz.

    `model_pref` ("fast" or "smart") overrides the agent's default model
    on this single run. Anything else (None, unknown string) falls
    through to model_for("quiz") at agent-construction time.
    """
    deps = SaplingDeps(
        user_id=user_id,
        course_id=course_id,
        supabase=None,
        request_id=request_id,
        feature="quiz",
        # The Class-intel opt-out reaches the misconceptions tool through
        # deps, not through the prompt: the tool is registered on the agent
        # unconditionally and step 2 of the system prompt tells the model to
        # call it every run, so the routing sentence below can only ever ADD
        # emphasis — it cannot withhold the data (#553 review).
        share_class_context=use_shared_context,
    )
    # Keep this message routing-only; the workflow + adaptive rules
    # live in the system prompt. We just hand the agent the inputs it
    # needs and trust the prompt to drive tool calls.
    if difficulty == "adaptive":
        # #540 A1: no target difficulty — the agent picks the whole mix
        # from mastery + recent accuracy (ADAPTIVE MODE in the system
        # prompt). Every emitted question still carries a concrete
        # easy|medium|hard; the route reports the overall pick back to
        # the client as `resolved_difficulty`.
        difficulty_clause = (
            f"Generate {num_questions} questions in ADAPTIVE MODE: you "
            f"choose each question's difficulty (easy, medium, or hard) "
            f"from the student's mastery and recent accuracy, per the "
            f"adaptive-mode rules in your system prompt."
        )
    else:
        difficulty_clause = (
            f"Generate {num_questions} {difficulty} questions for the student."
        )

    # ONE resolution of the two things the legs below share. Four of them want
    # the same two answers — grounding wants this course's `course_code`, the
    # H4 flashcard signal wants its `course_name` (same row), and both exam
    # proximity and the H4 tutor signal want this course's offerings. Because
    # those legs run CONCURRENTLY they cannot share by accident, so resolving
    # here is what stops one generation from asking the same questions twice.
    #
    # These two are themselves independent, so they run concurrently with each
    # other: the pair costs the LONGER of them — one `courses` read or one
    # `course_offerings` read — ahead of the gather, and removes three from
    # inside it.
    #
    # The trade, stated plainly (#592 review C15): this is a serial PREFIX. It
    # cuts three round-trips out of a healthy request, but under a degraded
    # Supabase it adds up to one client timeout (30s, db/connection.py) ahead
    # of the gather and outside QUIZ_GENERATION_TIMEOUT_SEC, which bounds only
    # the agent runs. Handing each leg a future to await instead would recover
    # that — but the recovery is small: `_course_material` cannot start
    # without the `courses` row and both the exam and signal legs need the
    # offerings, so the only leg that could genuinely start early is the
    # recently-asked read. One cheap read's worth of overlap is not worth
    # three awaited tasks with hand-rolled per-leg degradation in the hottest
    # function in this file.
    #
    # return_exceptions=True for the same reason the gather below uses it:
    # both helpers already degrade internally, so this is the backstop for the
    # failure they cannot catch — a raise from the to_thread machinery itself,
    # or on the way in or out. Without it that raise leaves `_quiz_via_agent`
    # for the generic handler and 502s a generation that only needed to run
    # ungrounded.
    course_row, offering_ids = await asyncio.gather(
        asyncio.to_thread(_course_row, course_id),
        asyncio.to_thread(course_offering_ids, course_id),
        return_exceptions=True,
    )
    if isinstance(course_row, BaseException):
        # Precise about what is lost: grounding needs `course_code`, and the
        # FLASHCARD signal needs `course_name` — but the tutor signal needs
        # neither and still runs on the offerings below. Saying "without the
        # course-scoped signals" here would describe a degradation that isn't
        # the one that happened.
        logger.warning(
            "quiz: course lookup failed (%s); generating ungrounded, and the "
            "flashcard signals report unknown",
            type(course_row).__name__, exc_info=course_row,
        )
        # failed=True rather than a bare empty row, so E8 reports
        # `coverage_unknown` instead of claiming this course has no BU code —
        # and so the flashcard read is skipped rather than run offering-only,
        # which would miss every AI-generated card and call the remainder the
        # whole collection.
        course_row = CourseRow(failed=True)
    if isinstance(offering_ids, BaseException):
        logger.warning(
            "quiz: offering resolution failed (%s); the offering-scoped "
            "signals report unknown",
            type(offering_ids).__name__, exc_info=offering_ids,
        )
        # None, not []: "could not tell". An empty list would assert this
        # course has no offering at all, tripping the F5 dark-scope report on
        # what is really a transport failure.
        offering_ids = None
    course_scope = CourseScope(
        offering_ids=offering_ids,
        course_name=course_row.name,
        name_failed=course_row.failed,
    )

    # Course-material grounding does blocking network I/O (a Gemini
    # embedding call, bounded at 60s) plus sync Supabase reads. Run it in a
    # worker thread so a slow/stalled retrieval can't freeze this worker's
    # event loop for every other in-flight request. Matches the
    # asyncio.to_thread pattern used by the agent read tools.
    #
    # E6's recently-asked read and H3's exam-proximity lookup are independent
    # Supabase reads, so all three run CONCURRENTLY rather than in sequence —
    # they have nothing to say to each other, and serializing them would add
    # every one of their latencies to every generation. Proximity costs
    # several round-trips on its own, so running it before this block made it
    # fully additive.
    #
    # return_exceptions=True because ALL THREE are best-effort context, and a
    # bare gather propagates the first failure straight out of generation: an
    # unreadable past attempt would 502 a quiz that needed no history at all.
    # Each helper already degrades internally; this is the backstop for the
    # failure they cannot catch (an unexpected raise on the way in or out).
    material, recent, exam_days_away, signals = await asyncio.gather(
        asyncio.to_thread(
            _course_material, course_id, concept_name,
            course=course_row, user_id=user_id,
        ),
        asyncio.to_thread(
            recent_question_identities, user_id, concept_node_id
        ),
        asyncio.to_thread(
            days_until_next_exam, user_id, course_id, offering_ids=offering_ids,
        ),
        asyncio.to_thread(
            gather_signals, user_id, concept_node_id,
            times_studied=times_studied,
            # `concept_name` comes off the `graph_nodes` row this route already
            # read; `scope` is the shared resolution above. The course-keyed
            # signals (flashcards, tutor recency) key on the OFFERING, and the
            # tutor scan matches the concept by name in `graph_update_json`.
            course_id=course_id,
            concept_name=concept_name,
            scope=course_scope,
            # Passed through from OUR caller, never assumed here: `_quiz_via_agent`
            # is also the entry point `scripts/benchmark_quiz.py` drives, with a
            # fixture user that has no graph at all.
            has_graph=has_graph,
        ),
        return_exceptions=True,
    )
    if isinstance(signals, BaseException):
        logger.warning(
            "quiz: student-signal gather failed (%s); generating without them",
            type(signals).__name__, exc_info=signals,
        )
        signals = QuizSignals()
    if isinstance(exam_days_away, BaseException):
        logger.warning(
            "quiz: exam-proximity lookup failed (%s); generating without it",
            type(exam_days_away).__name__, exc_info=exam_days_away,
        )
        exam_days_away = None
    if isinstance(material, BaseException):
        logger.warning(
            "quiz: course-material assembly failed (%s); generating ungrounded",
            type(material).__name__, exc_info=material,
        )
        # _UNKNOWN_MATERIAL, not _EMPTY_MATERIAL: assembly raised, so we know
        # nothing about this course's coverage. E8 must report
        # `coverage_unknown` rather than claiming the course has no BU code.
        material = _UNKNOWN_MATERIAL
    if isinstance(recent, BaseException):
        logger.warning(
            "quiz: recently-asked read failed (%s); generating without a "
            "do-not-repeat list", type(recent).__name__, exc_info=recent,
        )
        recent = []

    routing_msg = (
        f"{difficulty_clause} "
        f"The target concept is '{concept_name}' "
        f"(concept_node_id={concept_node_id}). Follow the workflow in your "
        f"system prompt; pass concept_node_id='{concept_node_id}' to "
        f"read_recent_quiz_attempts."
    )
    if use_shared_context:
        routing_msg += (
            " Also call read_misconceptions_for_course and use those misconceptions "
            "as distractors and probes."
        )
    # H3/#555: one line, dates only, and only inside the proximity horizon.
    # The sentence itself lives next to the number it renders, in
    # `services/exam_proximity.py`, so the prompt-budget benchmark measures
    # the real one instead of a hand-copy (it had one, and it was stale).
    routing_msg += exam_prompt_line(exam_days_away)

    # H4/#556: the signals that were already in reach and never asked for.
    # Appended as one short line, and recorded as dimensions so F6 can price
    # it — the issue's whole framing is "land these behind the measurement so
    # we can see what each costs before deciding what stays".
    routing_msg += signal_block(signals)
    prompt_dimensions.record(**signals.as_dimensions())
    _log_rag_uncovered(
        material,
        user_id=user_id,
        concept_node_id=concept_node_id,
        request_id=request_id,
    )
    routing_msg += _do_not_repeat_block(recent)
    routing_msg += f"\nquestion_format: {question_format}. Only generate the requested format; mixed uses a useful variety.\n"

    user_message = _quiz_user_message(
        concept_name=concept_name, material=material, routing_msg=routing_msg,
        plan=plan, question_format=question_format, recent=recent,
    )

    # F6: what this prompt is made of, so `llm_usage.prompt_tokens` (same
    # request_id) becomes attributable to sections instead of estimated.
    # Recorded BEFORE the run so a failed generation still reports its
    # composition — an ungrounded timeout is a different diagnosis from a
    # grounded one.
    prompt_dimensions.record(
        blocks=sorted(
            b for b, present in (
                ("catalog", material.has_catalog),
                ("rag", material.rag_grounded),
                ("recently_asked", bool(recent)),
                ("misconceptions_requested", use_shared_context),
            ) if present
        ),
        k_chunks=material.chunk_count,
        material_chars=len(material.block),
        recent_asked=len(recent),
        routing_chars=len(routing_msg),
        adaptive=difficulty == "adaptive",
    )
    quiz_learning.record_generation_dimensions(plan, gate)

    model_override = _resolve_model_pref(model_pref)
    run_kwargs: dict = {"deps": deps}
    if model_override is not None:
        run_kwargs["model"] = model_override
    agent = quiz_agent if plan is None else quiz_planned_agent

    async def _run(message: str, limits) -> tuple[Quiz, str]:
        # #544 F2: bound EACH agent run rather than the whole function.
        # Wrapping the outer coroutine cancelled it mid-flight, and
        # CancelledError is a BaseException — it flew straight past the
        # top-up's serve-what-we-have handler and threw away questions the
        # student had already paid for. Timing out one run raises an
        # ordinary TimeoutError the existing handlers can reason about.
        result = record_agent_usage(
            await asyncio.wait_for(
                agent.run(message, usage_limits=limits, **run_kwargs),
                timeout=QUIZ_GENERATION_TIMEOUT_SEC,
            ),
            feature="quiz", task="quiz", user_id=deps.user_id,
        )
        # Returned per-run, not resolved once for the function: a top-up is
        # a SEPARATE model call and can be served by a different model than
        # the first run (a provider-side reroute, or a future retry that
        # escalates tiers). Stamping one model over all of them would make
        # provenance quietly wrong in exactly the case it exists to record.
        return result.output, served_model_name(result, "quiz")

    # Filter out questions the agent got wrong (correct_answer not among
    # the options, duplicate/insufficient options, no single correct
    # answer) and duplicate stems within this attempt —
    # _agent_question_to_wire returns None for the former,
    # _validate_wire_question backs it. Survivors are re-numbered so
    # question ids stay 1-based and contiguous.
    #
    # `dropped` counts questions we REJECTED, which is a different thing
    # from "fewer than requested": the Quiz schema lets a run return any
    # count, and the E2E seam always returns 3 no matter what was asked.
    # Keying the top-up on under-delivery therefore fired a second full
    # generation on perfectly good responses.
    wire_questions: list[dict] = []
    seen_stems: set[str] = set()
    seen_hashes: set[str] = set()
    dropped = 0

    # E5 provenance shared by every question this generation produces. The
    # chunk ids are attempt-level, not per-item: they are the sources that
    # were in the prompt when the question was written, which is the honest
    # claim — the model never tells us which chunk it drew any single
    # question from.
    provenance_base = {
        "prompt_version": PROMPT_VERSION if plan is None else PLANNED_PROMPT_VERSION,
        "chunk_ids": list(material.chunk_ids),
        # Two separate facts, not one fuzzy one: whether retrieved document
        # chunks grounded the question, and whether the official catalog
        # block was present. Collapsing them into a single `grounded` made
        # a catalog-only course record every question as ungrounded.
        "rag_grounded": material.rag_grounded,
        "catalog": material.has_catalog,
    }

    # A144: the plan slots a kept planned question answers (a slot is written
    # once; a dropped one is asked again by the top-up).
    filled_slots: set[int] = set()

    def _absorb(quiz: Quiz, model: str) -> None:
        nonlocal dropped
        for q in quiz.questions:
            spec = tags = None
            if plan is not None:
                planned = quiz_learning.planned_question(q, plan, filled_slots, concept_name)
                if planned is None:
                    dropped += 1
                    continue
                q, spec, tags = planned
            if question_format != "mixed" and q.type != question_format:
                dropped += 1
                continue
            # E5: identity is the dedupe key now. The stem check is kept
            # alongside it and is the COARSER of the two — a hash covers the
            # stem AND the options, so a model re-emitting one stem with
            # reworded options passes the hash check and is caught here.
            # Dropping it would have narrowed #543's duplicate-question
            # guard, which is not a trade E5 needs to make.
            stem = normalize_text(q.question)
            qhash = question_hash(q.question, [q.type] if q.type in WRITTEN_TYPES else q.options)
            if qhash in seen_hashes or stem in seen_stems:
                logger.warning(
                    "quiz: dropping duplicate question (hash=%s, stem_len=%d)",
                    qhash, len(stem),
                )
                dropped += 1
                continue
            mapped = _agent_question_to_wire(q, len(wire_questions) + 1)
            if mapped is None:
                dropped += 1
                continue
            mapped["provenance"] = {**provenance_base, "model": model}
            mapped["material_context"] = (
                "course_material" if material.rag_grounded else "catalog" if material.has_catalog else "general"
            )
            if spec is not None:
                _record_plan(mapped, spec, tags, plan)
                filled_slots.add(spec.slot)
            seen_stems.add(stem)
            seen_hashes.add(qhash)
            wire_questions.append(mapped)

    _absorb(*await _run(user_message, ORCHESTRATOR_LIMITS))
    # A145: check the questions each run adds; a dropped one counts as a drop
    # (the top-up asks again) and frees its plan slot.
    dropped += await quiz_learning.keep_gated(gate, wire_questions, 0, material, filled_slots)

    # #543 E2: one bounded top-up when DRIFT cost us a big share of the
    # quiz. Gated on questions actually dropped (never on a clean short
    # response), and it runs for total drift too — that's the case a
    # retry most obviously helps, and the old `wire_questions and` guard
    # made it the only case that never retried. Bounded because a retry
    # loop against a drifting model burns tokens without converging.
    if dropped and dropped >= num_questions * QUIZ_TOPUP_DROP_RATIO:
        for _ in range(QUIZ_TOPUP_MAX_RETRIES):
            missing = max(1, num_questions - len(wire_questions))
            logger.info(
                "quiz: topping up after drift (have=%d, dropped=%d, requested=%d)",
                len(wire_questions), dropped, num_questions,
            )
            # Name the stems to avoid: "different from the ones already
            # asked" is unactionable otherwise, and a deterministic model
            # re-emits the same questions, which the dedupe above then
            # discards — a full generation for nothing.
            already = "\n".join(f"- {q['question']}" for q in wire_questions)
            topup_msg = _topup_message(
                user_message=user_message, plan=plan, missing=missing,
                question_format=question_format, concept_name=concept_name,
                filled_slots=filled_slots, material=material, recent=recent,
                already=already,
            )
            try:
                start = len(wire_questions)
                _absorb(*await _run(topup_msg, TOPUP_LIMITS))
                dropped += await quiz_learning.keep_gated(
                    gate, wire_questions, start, material, filled_slots
                )
            except (Exception, asyncio.TimeoutError) as e:
                # The request deliberately SUCCEEDS from here — serve the
                # short quiz with an honest count. No traceback: the E2E
                # logscan oracle reports those as findings, and this path
                # is a handled degradation, not a bug (same rule the
                # quiz_context seam skip follows).
                logger.warning(
                    "quiz: top-up run failed (%s: %s); serving what we have",
                    type(e).__name__, e,
                )
                break
            if len(wire_questions) >= num_questions:
                break

    if not wire_questions:
        # All questions dropped — raise so generate_quiz's bare-Exception
        # catch degrades to HTTP 502 (the raw-Gemini legacy fallback was
        # retired in #145) rather than serving an empty quiz.
        raise RuntimeError(
            "quiz_agent produced no valid questions after wire-format validation"
        )
    # Never serve more than asked for (a generous top-up run can overshoot).
    return GeneratedQuiz(
        questions=wire_questions[:num_questions],
        exam_days_away=exam_days_away,
    )


def _lint_questions(questions: list[dict]) -> list[dict]:
    """Learning-loop spec §13 A132: store A113's item-flaw codes with every
    question of the attempt being assembled (`lint_flags`, in the encrypted
    `questions_json`; [] = linted clean). Generated and re-served (G5) items
    alike are linted here, the one place an attempt's questions are final, so
    a re-served item carries the current linter's answer. Submit reads the
    codes to decide whether an answer is mastery evidence
    (`learning.quiz_evidence.evidence_exclusion`); no client ever sees them
    (`_strip_answer_key`'s allowlist, `_INTERNAL_QUESTION_KEYS`)."""
    for question in questions:
        question["lint_flags"] = quiz_evidence.lint_question(question)
    return questions


def _item_gate(
    user_id: str, course_id: str | None, concept_name: str, request_id: str, writer_model: str
):
    """Learning-loop spec §13 A145: the gate hook `_quiz_via_agent` runs on
    each generation run's new questions — the A119 concept check and the
    A124 blind solve against the course's concepts and the passages the
    questions were written from, on a model other than `writer_model` (the
    one that wrote them). It never fails the quiz: when the checks cannot run
    at all, the run's questions are served as practice, never evidence."""

    async def gate(questions: list[dict], material: CourseMaterial):
        try:
            names = await asyncio.to_thread(quiz_learning.course_concept_names, user_id, course_id)
            return await quiz_learning.gate_questions(
                questions,
                user_id=user_id,
                course_id=course_id,
                concept_name=concept_name,
                concept_names=names,
                passages=list(material.passages),
                request_id=request_id,
                writer_model=writer_model,
            )
        except Exception as exc:
            logger.warning("quiz: item gates unavailable (%s); serving as practice", type(exc).__name__)
            unchecked = quiz_gates.Gate(
                quiz_gates.PRACTICE, quiz_gates.ALIGNMENT_UNVERIFIED, quiz_gates.KEY_UNVERIFIED
            ).stored()
            for question in questions:
                question[quiz_gates.GATE_KEY] = dict(unchecked)
            return quiz_learning.GateRun(kept=list(questions))

    return gate


async def _generate_or_502(
    body: GenerateQuizBody,
    *,
    request_id: str,
    course_id: str | None,
    concept_name: str,
    times_studied: int | None,
    count: int,
    slot: float | None,
    plan: GenerationPlan | None = None,
    gate=None,
) -> GeneratedQuiz:
    """Run generation, or raise the error the client contract calls for.

    `count` is what to generate NOW, which is not `body.num_questions` when
    G5 recovered part of the quiz from a previous attempt. `slot` is the
    rate-limit slot this request claimed, refunded on every failure exit.
    `plan` and `gate` are the learning-loop spec §13 A144/A145 hooks (None
    while their flags are off).
    """
    try:
        # Each agent run inside is individually bounded by
        # QUIZ_GENERATION_TIMEOUT_SEC (see _run) — cancelling the whole
        # coroutine here would discard a partial quiz the top-up handler
        # is designed to serve.
        return await _quiz_via_agent(
            user_id=body.user_id,
            course_id=course_id,
            concept_node_id=body.concept_node_id,
            concept_name=concept_name,
            num_questions=count,
            difficulty=body.difficulty,
            use_shared_context=body.use_shared_context,
            request_id=request_id,
            model_pref=body.model_pref,
            question_format=body.question_format,
            times_studied=times_studied,
            # A fact, not a guess (#592): `generate_quiz` reached here only
            # after an owner-scoped `graph_nodes` read, and `course_id` came
            # off that very row. It spares the F5 reporter a probe that could
            # only tell it what we just saw — once per generation, forever.
            has_graph=True,
            **({"plan": plan} if plan is not None else {}),
            **({"gate": gate} if gate is not None else {}),
        )
    except LLMBudgetExceeded as e:
        # #119: the per-user LLM budget refused the run before it spent
        # anything. Answered with the code the quiz spend cap (#544 F1) uses,
        # which the client already renders; the slot goes back like any
        # refusal that generated nothing.
        _refund_generate_slot(body.user_id, slot)
        raise QuizAPIError(
            status_code=429,
            code=QuizErrorCode.QUIZ_DAILY_LIMIT_REACHED,
            message=e.detail,
            headers=e.headers,
        ) from e
    except HTTPException:
        # The 404 for an unknown concept node is raised before the agent call;
        # never swallow a known HTTP state.
        _refund_generate_slot(body.user_id, slot)
        raise
    except asyncio.TimeoutError as e:
        # #544 F2: distinct from a generic failure — the client can say
        # "that took too long" and offering a retry obviously makes sense.
        # NB: only asyncio.TimeoutError. The builtin TimeoutError is in the
        # OSError family, so catching it too would relabel a transport
        # socket timeout as a wall-clock generation timeout.
        logger.warning(
            "quiz: generation timed out after %ss request_id=%s",
            QUIZ_GENERATION_TIMEOUT_SEC, request_id,
        )
        _refund_generate_slot(body.user_id, slot)
        _log_generation_failed(body, request_id, "timeout")
        raise QuizAPIError(
            status_code=502,
            code=QuizErrorCode.QUIZ_GENERATION_TIMEOUT,
            message="Quiz generation took too long. Please try again.",
        ) from e
    except (UsageLimitExceeded, UnexpectedModelBehavior) as e:
        # The raw-Gemini legacy fallback was retired in #145; degrade to 502
        # rather than serving a quiz from a second LLM path.
        logger.warning("Quiz agent guardrails tripped; returning 502", exc_info=e)
        _refund_generate_slot(body.user_id, slot)
        _log_generation_failed(body, request_id, "agent_guardrail")
        raise QuizAPIError(
            status_code=502,
            code=QuizErrorCode.QUIZ_GENERATION_FAILED,
            message="Quiz generation is temporarily unavailable. Please try again.",
        ) from e
    except Exception as e:
        logger.exception("Unexpected quiz-agent failure; returning 502")
        _refund_generate_slot(body.user_id, slot)
        _log_generation_failed(body, request_id, "agent_error")
        raise QuizAPIError(
            status_code=502,
            code=QuizErrorCode.QUIZ_GENERATION_FAILED,
            message="Quiz generation is temporarily unavailable. Please try again.",
        ) from e


async def generate_quiz(body: GenerateQuizBody, request: Request):
    await guard_off_loop(require_self, body.user_id, request)
    if body.include_answer_key:
        # PKG-14b owner decision 2 (spec §13 A94): the client-side answer key is a
        # quiz-farming tool — admin only (403 before any generation runs). The
        # shipped client always sends false (lib/quiz/api.ts). require_admin reads
        # roles on every call, so it hops off the event loop (#756 review).
        await run_in_threadpool(require_admin, request)
    # The concrete trio is CHECK-constrained on quiz_attempts (0025 +
    # the #540 'adaptive' extension); reject drift before we run the
    # agent or write an attempt row.
    if body.difficulty not in REQUESTED_DIFFICULTIES:
        raise QuizAPIError(
            status_code=400,
            code=QuizErrorCode.QUIZ_DIFFICULTY_INVALID,
            message=(
                "That difficulty isn't available. Choose easy, medium, "
                "hard, or adaptive."
            ),
        )
    # #117: on the event loop: reads are `a*` calls, sync helpers hop off it.
    node_rows = await table("graph_nodes").aselect(
        "*",
        filters={"id": f"eq.{body.concept_node_id}", "user_id": f"eq.{body.user_id}"},
    )
    if not node_rows:
        raise QuizAPIError(
            status_code=404,
            code=QuizErrorCode.QUIZ_CONCEPT_NOT_FOUND,
            message="We couldn't find that concept in your knowledge graph.",
        )
    node = node_rows[0]
    course_id = node.get("course_id") or None
    concept_name = node.get("concept_name") or ""

    # Unify with the middleware-stamped request ID so agent traces and any
    # downstream error payloads share the same correlation key.
    request_id = (
        getattr(request.state, "request_id", None)
        or current_request_id()
        or str(uuid.uuid4())
    )

    # #544 F1: cost guards run AFTER ownership (a stranger's node 404s
    # first, so probing can't consume a victim's quota) and BEFORE the
    # model call. Neither rejection is a backend failure, so neither emits
    # quiz.generation_failed.
    retry_after, slot = await aclaim_rate_limit(
        f"quiz_generate:{body.user_id}",
        limit=QUIZ_GENERATE_RATE_LIMIT,
        window_sec=QUIZ_GENERATE_RATE_WINDOW_SEC,
    )
    if retry_after is not None:
        raise QuizAPIError(
            status_code=429,
            code=QuizErrorCode.QUIZ_RATE_LIMITED,
            message=(
                "You've generated a lot of quizzes just now — "
                "take a moment and try again shortly."
            ),
            headers={"Retry-After": str(retry_after)},
        )
    # G5 (#537): "practise the ones you missed" re-serves the exact items the
    # student got wrong on a previous attempt — verbatim, with no model call
    # for them. Resolved BEFORE the spend cap because a quiz that is entirely
    # re-served spends nothing: the cap's own message is about "AI-generated
    # study material", and there is none here.
    try:
        reserved = await _reserved_misses(body)
    except QuizAPIError:
        # None of these refusals is a generation: a stale attempt id off a
        # results screen the student left open would otherwise spend their
        # quota eight times over and then 429 them having generated nothing.
        # Same rule _generate_or_502 follows on every one of its exits.
        _refund_generate_slot(body.user_id, slot)
        raise
    recovered = list(reserved.questions) if reserved else []
    missing = body.num_questions - len(recovered)

    if missing > 0 and await run_in_threadpool(_daily_spend_exceeded, body.user_id):
        logger.warning(
            "quiz: daily spend cap reached user=%s request_id=%s",
            body.user_id, request_id,
        )
        # #760: refused before anything was generated, so it must not cost a
        # rate-limit slot. The cap can't be checked before the claim — whether
        # it applies depends on how much G5 re-served — so hand back this
        # request's exact slot instead.
        _refund_generate_slot(body.user_id, slot)
        raise QuizAPIError(
            status_code=429,
            code=QuizErrorCode.QUIZ_DAILY_LIMIT_REACHED,
            message=(
                "You've reached today's limit for AI-generated study "
                "material. It resets tomorrow."
            ),
        )

    # F6: open the prompt-composition capture for this request. Both the
    # route and the agent's read tools contribute; the snapshot rides into
    # quiz.started, which shares this request_id with the llm_usage row.
    prompt_dimensions.start_capture()
    if reserved is not None:
        # Recorded before the run, so a generation that then fails still
        # reports how much of this quiz it was only topping up.
        prompt_dimensions.record(reserved_count=len(recovered))

    questions = recovered
    # H3/#555 caveat, deliberate: `days_until_next_exam` is resolved INSIDE
    # _quiz_via_agent (one lookup serves both the prompt and the stored
    # column), so a quiz that generates nothing records no `exam_days_away`.
    # The column therefore means "exam proximity at generation time", and a
    # fully re-served practice attempt leaves it NULL rather than repeating
    # the source attempt's value — which would be a different day's answer.
    # Analytics keying on it must read it as "generated quizzes only". Paying
    # for the lookup on a path that makes no model call, purely to fill a
    # column nothing reads back on the request path, is the trade not taken.
    exam_days_away = None
    # Learning-loop spec §13 A144/A145: each flag resolved ONCE for this
    # request, for the student, and its answer carried down. Off (the
    # default), nothing below changes.
    planned_on, gates_on = await run_in_threadpool(
        lambda: (
            flag_on(quiz_learning.PLANNED_QUESTIONS_FLAG, body.user_id),
            flag_on(quiz_learning.ITEM_GATES_FLAG, body.user_id),
        )
    )
    if missing > 0:
        plan = (
            await run_in_threadpool(
                quiz_learning.generation_plan,
                body.user_id,
                body.concept_node_id,
                course_id=course_id,
                concept_name=concept_name,
                count=missing,
                requested=body.difficulty,
                question_format=body.question_format,
            )
            if planned_on
            else None
        )
        try:
            generated = await _generate_or_502(
                body,
                request_id=request_id,
                course_id=course_id,
                concept_name=concept_name,
                times_studied=node.get("times_studied"),
                count=missing,
                slot=slot,
                plan=plan,
                gate=(
                    _item_gate(
                        body.user_id,
                        course_id,
                        concept_name,
                        request_id,
                        _writer_model_name(body.model_pref),
                    )
                    if gates_on
                    else None
                ),
            )
        except QuizAPIError:
            if not recovered:
                raise
            # A quiz was recoverable and the top-up wasn't: serve the short
            # quiz rather than deny the student practice they'd already
            # earned. Same call the top-up handler makes one level down, and
            # the response says exactly what it contains. The slot refund
            # inside _generate_or_502 stands — that generation really did
            # fail, whatever else we manage to serve.
            logger.warning(
                "quiz: remainder generation failed; serving the %d re-served "
                "question(s) request_id=%s", len(recovered), request_id,
            )
        else:
            # The do-not-repeat block should already keep generation off the
            # re-served items (they were served on the source attempt, so E6
            # names them), but a model that repeats one anyway must not put
            # the same item in front of the student twice in one quiz.
            reserved_hashes = {
                h for h in (wire_question_hash(q) for q in recovered) if h
            }
            # The stem check is the COARSER of the two and is why _absorb
            # keeps both: a hash covers the stem AND the options, so a model
            # re-emitting a re-served stem with reworded distractors clears
            # the hash check. _absorb's own `seen_stems` only ever holds the
            # current run's questions, never the re-served ones, so this is
            # the only place that case can be caught.
            reserved_stems = {
                normalize_text(q.get("question") or "") for q in recovered
            } - {""}
            questions = recovered + [
                q for q in generated.questions
                if wire_question_hash(q) not in reserved_hashes
                and normalize_text(q.get("question") or "") not in reserved_stems
            ]
            exam_days_away = generated.exam_days_away
    regenerated_count = len(questions) - len(recovered)
    if gates_on:
        # A145: a re-served question stored before the gates is practice.
        quiz_learning.ungated_practice(questions)
    _renumber(questions)
    _lint_questions(questions)

    quiz_id = str(uuid.uuid4())
    attempt_row = {
        "id": quiz_id,
        "user_id": body.user_id,
        "concept_node_id": body.concept_node_id,
        "difficulty": body.difficulty,
        "questions_json": encrypt_json(questions),
    }
    # H3/#555: recorded so the question "do deadline-aware quizzes perform
    # differently?" is answerable later. Omitted when unknown rather than
    # written as an explicit null, mirroring apply_graph_update's rule: an
    # environment that took this code before the migration keeps generating
    # instead of 400ing on a column PostgREST's schema cache doesn't have.
    if exam_days_away is not None:
        attempt_row["exam_days_away"] = exam_days_away
    try:
        await run_in_threadpool(_insert_attempt, attempt_row)
    except Exception as e:
        # #760: the quiz was generated (and billed) but there is no row to
        # serve it from, so the student got nothing. Same three duties as
        # every other failure exit: refund THIS request's slot, make the 502
        # countable, and answer with the contract's retryable code rather
        # than an opaque 500.
        logger.exception(
            "quiz: attempt insert failed after generation request_id=%s",
            request_id,
        )
        _refund_generate_slot(body.user_id, slot)
        _log_generation_failed(body, request_id, "attempt_insert_failed")
        prompt_dimensions.clear()
        raise QuizAPIError(
            status_code=502,
            code=QuizErrorCode.QUIZ_GENERATION_FAILED,
            message="Quiz generation is temporarily unavailable. Please try again.",
        ) from e
    if reserved is not None:
        # G5, closing the pair opened before the run: how this quiz was
        # actually assembled. Rides quiz.started on the F6 snapshot, which
        # shares a request_id with the llm_usage row — so "this generation
        # cost N prompt tokens for 2 of its 5 questions" is answerable.
        prompt_dimensions.record(regenerated_count=regenerated_count)
    # #117: quiz.started once the attempt row exists. num_questions is the
    # actual generated count (the agent may return fewer than requested).
    events_service.log_event(
        "quiz.started",
        category="usage",
        user_id=body.user_id,
        request_id=request_id,
        payload={
            "quiz_id": quiz_id,
            "concept_node_id": body.concept_node_id,
            "num_questions": len(questions),
            "difficulty": body.difficulty,
            # F6: the prompt's composition, carried on the event that
            # already shares a request_id with this generation's llm_usage
            # row — so prompt_tokens becomes attributable to sections
            # rather than estimated. Ids/counts/enums only, per the #117
            # payload rule; no prompt text goes anywhere near this.
            **prompt_dimensions.snapshot(),
        },
    )
    prompt_dimensions.clear()
    # #541 C3 / #546: the answer key (per-option `correct` booleans) ships
    # to the client only behind the deprecated include_answer_key flag.
    # Lifecycle prose is documented once, on the field itself — see
    # models.GenerateQuizBody.include_answer_key.
    _record_answer_key_flag(body, quiz_id, request_id)
    response_questions = _client_questions(questions, body.include_answer_key)

    # #540 A1: echo what generation actually chose. requested_difficulty
    # is what the student asked for (may be 'adaptive');
    # resolved_difficulty is the overall mix the agent produced (always
    # concrete) — so the client can say "we picked hard for you" instead
    # of repeating the request back.
    return {
        "quiz_id": quiz_id,
        "questions": response_questions,
        "requested_difficulty": body.difficulty,
        "resolved_difficulty": _resolved_difficulty(questions),
        # #543 E2: never silently short-change a quiz. Drift (and the
        # bounded top-up) can leave fewer questions than asked for; the
        # client can now say so instead of pretending this is what was
        # requested.
        "requested_count": body.num_questions,
        "delivered_count": len(questions),
        # G5 (#537): present whenever the request named a source attempt, and
        # then always — so the three outcomes stay distinguishable and the
        # client can label each honestly: re-served everything
        # (regenerated_count 0), re-served some (both non-zero), re-served
        # nothing and fell back to generation (reserved_count 0). Additive: a
        # request that isn't practising a past attempt never sees the key.
        **(
            {
                "source": {
                    "attempt_id": reserved.attempt_id,
                    "reserved_count": len(recovered),
                    "regenerated_count": regenerated_count,
                }
            }
            if reserved is not None
            else {}
        ),
    }

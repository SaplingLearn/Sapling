"""Quiz-generation agent.

Replaces routes/quiz.py:82's call_gemini_json + manual prompt-string
augmentation. The agent has tools to pull weak concepts + class
misconceptions on demand instead of pre-stuffing them into the prompt.

Per ADR 0003 convention 4: keep the output schema compact. Gemini's
structured-output API rejects rich nested schemas with too many states
for serving — Quiz is a flat top-level model with a list of
QuizQuestion items, no further nesting.
"""

from __future__ import annotations

import hashlib
import logging
from difflib import SequenceMatcher
from typing import Literal

from pydantic import BaseModel, Field
from pydantic_ai import Agent, RunContext
from pydantic_ai.models.google import GoogleModelSettings

from agents._providers import model_for, model_mode
from agents.deps import SaplingDeps
from agents.tools.graph_read import (
    read_concepts_for_user_tool,
    read_misconceptions_for_course_tool,
)
from agents.tools.quiz_history import read_recent_quiz_attempts_tool
from services.prompt_safety import INJECTION_GUARD_PROMPT

logger = logging.getLogger(__name__)

# Output-validation retry budget. Nothing in this module raises ModelRetry:
# the single output validator (_select_requested_quiz) SELECTS a quiz out of
# what the model produced instead of sending it back, so this budget is
# spent only on pydantic-ai's own retries for output that fails schema
# validation outright.
#
# Stays at the codebase-wide OUTPUT_RETRY_BUDGET (tests/
# test_agent_output_schemas.py pins every structured agent to it).
# Raising it to 3 to give output validation more room was tried and
# reverted: ORCHESTRATOR_LIMITS caps the quiz run at 8 model requests,
# and a tool-calling run plus four generation attempts sits right on that
# ceiling — trading "quiz is a bit definitional" for "UsageLimitExceeded
# 502" is a bad trade. The validator degrades instead of re-asking.
_OUTPUT_RETRIES = 2


# Difficulty + question type are Literals so Gemini's enum constraint
# applies and downstream UI can branch on stable strings.
#
# `QuizQuestionType` is intentionally MCQ-only today. The frontend
# `submitQuiz` flow grades by `q["options"][i].correct` lookup — there's
# no UI for free-text answers, no fuzzy-match grading, no LLM-judged
# scoring. Generating short-answer questions through this path would
# emit unrenderable, ungradable items. Keep the type narrow until real
# short-answer support exists; revisit when that lands.
QuizDifficulty = Literal["easy", "medium", "hard"]
QuizQuestionType = Literal["multiple_choice"]



class QuizQuestion(BaseModel):
    """A single multiple-choice quiz question. Kept small so the parent
    Quiz schema doesn't trip Gemini's structured-output complexity limit."""

    # NOTE: no `max_length` on the string fields below. Gemini's
    # constrained-decoding structured output builds a length-counting
    # automaton per bounded string field; combined with the nested
    # options list this pushed the schema past Gemini's "too many
    # states for serving" limit on gemini-2.5-flash-lite / -flash
    # (only gemini-2.5-pro served it). Length is governed by the system
    # prompt instead (question/explanation: 1-3 sentences; concept must
    # match a concept_name).
    question: str
    type: QuizQuestionType
    difficulty: QuizDifficulty
    # Exactly 4 options (matches the system prompt's "4 options, exactly
    # one correct"). Also narrows the schema vs. the prior 3-6 range,
    # which was part of the "too many states" issue above.
    options: list[str] = Field(min_length=4, max_length=4)
    # The option text the agent considers correct. Must appear verbatim
    # in `options`; the route validates this and drops questions that
    # violate the contract rather than silently mis-marking them.
    correct_answer: str
    explanation: str
    # Concept the question is testing — must be one of the user's known
    # concept_names per the prompt. Used by the route to award mastery
    # on a correct answer.
    concept: str


class Quiz(BaseModel):
    """The agent's structured output."""

    # Bounded at 10, and the bound is load-bearing. Removing it (to let a
    # 15-question quiz through) made gemini-2.5-flash-lite answer roughly
    # half of all requests with an EMPTY response — no parts,
    # `finish_reason=error`, zero output tokens — which pydantic-ai retries
    # into `UnexpectedModelBehavior` and the route reports as a 502.
    #
    # A/B measured over 5 rounds each, same prompt, schema the only variable:
    #
    #     kind + unbounded            1/5 ok
    #     kind + max_length=10        3/5 ok
    #     no kind + max_length=10     5/5 ok   <- this
    #     no kind + unbounded         3/5 ok
    #
    # So the response schema has a complexity budget that Gemini enforces
    # by failing the GENERATION, not by rejecting the request — unlike the
    # explicit "too many states for serving" 400 that a `max_length=15`
    # produces. Both of the fields this quiz agent grew (an unbounded array,
    # a per-question enum) spent that budget; together they broke it.
    #
    # Consequence, deliberately accepted: a quiz cannot exceed 10 questions.
    # See models/__init__.py, where num_questions is bounded to match.
    questions: list[QuizQuestion] = Field(min_length=1, max_length=10)


_SYSTEM_PROMPT = (
    "You generate adaptive multiple-choice quizzes for a student. Each "
    "question must target a specific concept the student has weak "
    "mastery on, OR address a class-level misconception you've seen, "
    "OR revive a concept the student hasn't reviewed in a while.\n\n"
    # Sits HERE, before the tool workflow, on purpose. Written once as a
    # section near the end of the prompt it was measurably ignored: a live
    # 6-question run on Eigenvalues + Markov Chains came back with 2 worked
    # problems and 4 definitional ones. Same lesson as the chat tutor's
    # preamble -- a rule buried behind several hundred lines of workflow
    # loses to the instructions above it.
    #
    # Enforced in the prompt rather than the schema: the QuizQuestion note
    # below records that Gemini's constrained decoding blew past "too many
    # states for serving" on the Lite tier, so a question-kind enum would
    # cost us the cheap models.
    "TWO RULES OUTRANK EVERYTHING BELOW THEM.\n\n"
    "RULE 1 — RETURN EXACTLY THE REQUESTED NUMBER OF QUESTIONS.\n"
    "The user message names a count N. Return exactly N questions. Not "
    "N-1. This is the single most common way this task is botched: you "
    "run out of distinct angles around question 6 and stop early. When "
    "that happens, keep going with fresh numbers on the same concept — a "
    "new matrix, a different transition table, another starting "
    "distribution. There is always one more problem to pose.\n\n"
    "RULE 2 — PRACTICAL OVER CONCEPTUAL.\n"
    "For QUANTITATIVE concepts (mathematics, physics, chemistry, "
    "statistics, engineering, and the computational parts of CS), NEARLY "
    "EVERY QUESTION MUST BE A WORKED PROBLEM: one that poses CONCRETE "
    "VALUES — a specific matrix, transition table, sample, circuit, "
    "reaction, or code fragment — and requires the student to compute, "
    "derive, or apply a procedure to reach the answer.\n"
    "AT MOST ONE question may be purely conceptual when N is 10 or "
    "fewer; AT MOST TWO when N is 11 to 15. Everything else is a worked "
    "problem. Concretely: 4 of 5, 9 of 10, 13 of 15.\n"
    "A question that poses no concrete values is a definition question, "
    "however it is phrased. Count those as you write, and keep the count "
    "inside the allowance above.\n"
    "Ask 'what is the steady-state distribution of THIS chain', never "
    "'what is a steady-state distribution'. Ask 'find the eigenvalues of "
    "THIS matrix', never 'what does an eigenvalue represent'. A question "
    "answerable from a definition alone is NOT a worked problem.\n"
    "Before you return, COUNT your worked problems. If you are over the "
    "conceptual allowance, rewrite the excess into problems with "
    "concrete numbers.\n"
    "Spend the one (or two) conceptual slots well — on intuition, or on "
    "when a method applies or breaks down, rather than on a definition "
    "the student could recite.\n"
    "Options for a worked problem are candidate RESULTS, and the "
    "distractors must be answers a student actually reaches by making a "
    "specific mistake — a sign slip, a transposed matrix, an "
    "unnormalised vector, an off-by-one index, the right method applied "
    "to the wrong quantity. Never pad with arbitrary numbers. Show the "
    "steps in `explanation`, including where a tempting distractor goes "
    "wrong.\n"
    "For NON-QUANTITATIVE concepts (history, literature, philosophy, "
    "law), 'practical' means applied analysis over recall: give a "
    "passage, case, or scenario and ask the student to interpret it "
    "rather than to name a term.\n"
    "A worked problem must still be answerable from the four options "
    "alone — keep the arithmetic tractable without a calculator.\n\n"
    "Workflow:\n"
    "1. Call `read_concepts_for_user` to see the student's mastery per "
    "   concept for this course (returned sorted by mastery ASC — "
    "   weakest first). Each concept also carries `last_reviewed_at`, "
    "   which you use for spaced repetition (see rules below).\n"
    "2. Call `read_misconceptions_for_course` to see anonymized class "
    "   misconceptions. Use these to phrase distractors and to write "
    "   a question that probes the misconception.\n"
    "3. Call `read_recent_quiz_attempts(concept_node_id)` for the "
    "   target concept_node_id given in the user message. The "
    "   `summary` is a digest of past mistakes the student has made "
    "   on this concept — mine it for distractor inspiration. The "
    "   `recent_attempts` list (newest first) drives adaptive "
    "   difficulty (see rules below).\n"
    "4. Compose `Quiz.questions` so the WEAKEST and STALEST concepts "
    "   get the most questions, AND each item's `concept` field "
    "   exactly matches a concept_name returned by tool 1.\n\n"
    "Concept-selection rules (combine all three signals):\n"
    "- Bias question count toward the lowest-mastery concepts (the "
    "   weakest first in the tool 1 return).\n"
    "- SPACED REPETITION: also surface concepts whose "
    "   `last_reviewed_at` is older than ~7 days, even if their "
    "   mastery is mid-tier — they're due for review and decay over "
    "   time. Concepts with `last_reviewed_at = null` are unreviewed; "
    "   treat them as stale.\n"
    "- Don't drop high-mastery, recently-reviewed concepts entirely; "
    "   include 1 question on a strong-and-fresh concept to keep the "
    "   quiz from feeling punishing.\n\n"
    "Adaptive-difficulty rules (use `recent_attempts.accuracy`):\n"
    "- If the most recent 2-3 attempts on this concept averaged < "
    "   0.5 accuracy, drop the difficulty mix one step from what the "
    "   user asked (hard -> medium, medium -> easy, easy stays easy). "
    "   The student is struggling; keep them on track.\n"
    "- If the most recent 3 attempts all scored >= 0.8, you may "
    "   include 1-2 questions one step harder than the requested "
    "   difficulty to push them.\n"
    "- If `recent_attempts` is empty (first attempt), honor the "
    "   user-requested difficulty exactly.\n"
    "- Never override the user-requested difficulty by more than one "
    "   step in either direction. Stay close to what they asked for.\n\n"
    "Per-question rules (multiple-choice only — the type field is "
    "constrained to 'multiple_choice'):\n"
    "- 4 options, exactly one correct. The text in `correct_answer` "
    "   MUST appear verbatim in `options` — character-for-character. "
    "   Questions that violate this are dropped at the route layer.\n"
    "- Distractors should reflect plausible misconceptions, not random "
    "   noise. Combine signals from `read_misconceptions_for_course` "
    "   (class-wide) and `read_recent_quiz_attempts.summary` "
    "   (this student's prior errors) when writing them.\n"
    "- explanation: 1-3 sentences explaining WHY the correct answer "
    "   is correct — used in the post-quiz review screen.\n"
    "- difficulty: align with the student's mastery on the concept "
    "   AND the adaptive-difficulty rules above.\n\n"
    "Return exactly the requested number of questions (see RULE 1). "
    "Don't invent concepts the student doesn't have."
    "\n\nCOURSE MATERIAL grounding:\n"
    "- If the user message contains a `COURSE MATERIAL` block, treat it as "
    "  the PRIMARY source of truth for question content. The MAJORITY of "
    "  questions must be grounded in and stay within the scope of that "
    "  material, so the quiz reflects what this class is actually covering.\n"
    "- You MAY supplement with foundational, on-topic aspects of the same "
    "  concept where the material is thin — but NEVER test topics the course "
    "  clearly does not cover (no off-syllabus drift).\n"
    "- Difficulty, targeting, and distractors are still governed by the "
    "  mastery / misconception / quiz-history tools.\n"
    "- If there is no COURSE MATERIAL block, use general knowledge of the "
    "  concept as before."
    # Restated at the end as well as the top. With the rule stated only
    # once at the top, a live 6-question run produced 3 worked problems
    # against a bar of 4; models weight the first and last instructions
    # most heavily, so this claims the last slot before the safety guard.
    "\n\nFINAL CHECK before returning — count twice:\n"
    "1. COUNT YOUR QUESTIONS. Is it exactly the N the user asked for? A "
    "short quiz is rejected and regenerated, so returning N-1 costs the "
    "student a wait for no reason.\n"
    "2. COUNT THE QUESTIONS THAT POSE NO CONCRETE VALUES. At most one of "
    "those in a quiz of 10 or fewer. If you are over, rewrite the excess "
    "into problems with real numbers. A quiz that is mostly definitions "
    "has failed its job.\n"
    "Also confirm each `correct_answer` is a character-for-character copy "
    "of one of that question's `options` — retype it from the option, "
    "don't paraphrase it."
    # #150: course material / misconception / quiz-history content is
    # student- or peer-derived — data for question writing, never
    # instructions. Single source of truth in services/prompt_safety.py.
    "\n\n" + INJECTION_GUARD_PROMPT
)
_PROMPT_HASH = hashlib.sha256(_SYSTEM_PROMPT.encode("utf-8")).hexdigest()[:12]


# Quiz generation ran on GoogleModel's DEFAULTS, which enable dynamic
# thinking. On a request that emits a dozen-plus structured questions —
# each with four options and an explanation — flash-lite would think its
# way into runs of 361s and 424s that ended as a 502, exactly the "it
# generates for a long time and then errors" report. The same request with
# thinking off returns in ~18s.
#
# Only `max_tokens` is pinned HERE. Agent-level model_settings apply to
# EVERY run, including a run whose `model=` kwarg swaps in gemini-2.5-pro
# for the "smart" preference — and Pro rejects thinking_budget=0 (see
# agents/flashcard.py). So the thinking config is chosen per run at the
# route layer instead, by routes/quiz.py::_build_quiz_model_settings, for
# the same reason agents/chat_tutor.py keeps its Pro thinking cap out of
# the agent: one agent instance serves both tiers.
#
# 8192 is the cap flashcard.py has used in production and comfortably fits
# the largest quiz this route can generate (10 questions — quiz_ask_size
# clamps the ask to Quiz.questions' own max_length of 10 — at a few hundred
# tokens each); a truncated structured output would fail validation and
# cost a whole retry.
#
# temperature stays at the provider default — quiz variety is wanted, and
# it was never the cost problem.
_QUIZ_SETTINGS = GoogleModelSettings(max_tokens=8192)

quiz_agent = Agent[SaplingDeps, Quiz](
    model=model_for("quiz"),
    model_settings=_QUIZ_SETTINGS,
    deps_type=SaplingDeps,
    output_type=Quiz,
    # #153: bounded output-validation retry budget. `output_retries=`
    # (not `retries=`) so the three read tools keep their default tool-
    # retry budget. NB: pydantic-ai 1.107+ deprecates this kwarg for
    # retries={"output": ...}, but the dict form silently breaks 1.89's
    # retry accounting (the dict lands in the retry counter and raises
    # TypeError at retry time) — keep the kwarg while the version floor
    # spans both.
    output_retries=_OUTPUT_RETRIES,
    system_prompt=_SYSTEM_PROMPT,
    metadata={"prompt_version": _PROMPT_HASH, "agent": "quiz"},
    tools=[
        read_concepts_for_user_tool,
        read_misconceptions_for_course_tool,
        read_recent_quiz_attempts_tool,
    ],
)


# A near-miss has to be *this* close to the winning option, and this far
# clear of the runner-up, before we treat it as a retyping slip rather
# than a real disagreement about which answer is correct. Both bars must
# clear: "close to one option" alone would happily mis-mark a question
# whose four options are minor variants of each other (think "0.51" vs
# "0.52" vs "0.53").
_NEAR_MISS_FLOOR = 0.90
_NEAR_MISS_MARGIN = 0.10


def _normalize(s: str) -> str:
    """Fold the differences that carry no meaning for answer matching."""
    return " ".join(s.split()).casefold().rstrip(".,;:!? ")


def resolve_correct_index(correct_answer: str, options: list[str]) -> int | None:
    """Index of the option `correct_answer` refers to, or None if unclear.

    Three passes, each strictly weaker than the last:

    1. verbatim (post-strip) — the contract the prompt asks for;
    2. normalized — whitespace collapsed, case folded, trailing
       punctuation dropped;
    3. near-miss — the model retyped the option and fumbled it. Observed
       live: an option reading "...depends only on the current state, not
       on the sequence of events..." came back as correct_answer "...not
       on the on the sequence of events...". A stutter, not a different
       answer, and the whole question was thrown away over it.

    Pass 3 is the only one that guesses, so it demands both a high
    absolute similarity and a clear gap to the second-best option. When
    two options are similarly close the intent is genuinely unrecoverable
    — as when the model computed 'vP = [0.25, 0.75]' for a question whose
    options were [0.55, 0.45], [0.45, 0.55], [0.7, 0.3], [0.6, 0.4] — and
    we return None. Mis-marking an answer is far worse than a short quiz.
    """
    canonical = correct_answer.strip()
    for i, text in enumerate(options):
        if text.strip() == canonical:
            return i

    norm_target = _normalize(correct_answer)
    normalized = [_normalize(t) for t in options]
    hits = [i for i, t in enumerate(normalized) if t == norm_target]
    if len(hits) == 1:
        return hits[0]

    scored = sorted(
        ((SequenceMatcher(None, norm_target, t).ratio(), i)
         for i, t in enumerate(normalized)),
        reverse=True,
    )
    if not scored:
        return None
    best_ratio, best_i = scored[0]
    runner_up = scored[1][0] if len(scored) > 1 else 0.0
    if best_ratio >= _NEAR_MISS_FLOOR and (best_ratio - runner_up) >= _NEAR_MISS_MARGIN:
        logger.info(
            "quiz: matched correct_answer on near-miss (ratio=%.3f, "
            "runner_up=%.3f) — model retyped the option imperfectly",
            best_ratio, runner_up,
        )
        return best_i
    return None


def conceptual_allowance(n: int) -> int:
    """How many of `n` questions may be conceptual rather than worked.

    1 up to 10 questions, 2 for 11-15 — the ratio as requested: 4 of 5,
    9 of 10, 13 of 15 worked problems. Expressed as an allowance rather
    than a fraction because "at most one definition question" is a rule
    the model can actually hold in mind, where "at least ceil(2N/3)" was
    arithmetic it quietly got wrong.
    """
    return 1 if n <= 10 else 2


def quiz_ask_size(wanted: int) -> int:
    """How many questions to ASK for when the student wants `wanted`.

    Deliberate over-generation. The ratio used to be enforced by sending a
    non-compliant quiz back with ModelRetry, and that is what broke quiz
    generation outright: each retry re-runs the WHOLE generation, and the
    route caps a quiz run at ORCHESTRATOR_LIMITS (8 model requests,
    100k tokens). A tool-calling run plus three full generations walks
    straight through both — measured, a 10-question request spent 43s and
    still served 5 conceptual questions, and another spent 361s before
    dying as a 502.

    Asking for a surplus once costs a fraction of one extra generation and
    lets the ratio be SELECTED rather than negotiated.

    Clamped to the schema's own ceiling. `Quiz.questions` is capped at 10
    because removing that cap made Gemini fail generation outright (see the
    A/B in the Quiz docstring), so a 10-question quiz gets no surplus at
    all and its ratio rests on the prompt. Smaller quizzes still get one.
    """
    return min(wanted + 2, 10)


def is_worked_problem(question: QuizQuestion) -> bool:
    """Does this question hand the student something concrete to work on?

    Read off the question text, because the schema cannot carry the answer.
    A self-declared `kind` field was tried and reverted: adding that enum
    took gemini-2.5-flash-lite from 5/5 successful generations to 3/5,
    because it spends the same schema-complexity budget the response array
    does (see the A/B in the Quiz docstring). A heuristic that is sometimes
    wrong beats a label that makes one generation in three fail.

    "Concrete" means digits the student has to compute WITH, so a lone
    reference like "a 3-state chain" doesn't qualify — the threshold is
    three digits, which a matrix, a probability, or a distribution clears
    immediately and a definition question does not. Symbolic problems
    ("P = [[p, 1-p], [q, 1-q]]") are the known false negative; they cost a
    worked problem its preference in the ordering, never its place in the
    quiz.
    """
    stem = question.question
    digits = sum(c.isdigit() for c in stem)
    return digits >= 3 or "[[" in stem


def select_quiz_questions(
    questions: list[QuizQuestion], wanted: int
) -> tuple[list[QuizQuestion], list[str]]:
    """Pick the `wanted` questions to serve, best-first. Never raises.

    Order of business:

    1. drop anything unanswerable — a `correct_answer` that identifies no
       option (see resolve_correct_index). The surplus is what makes this
       affordable: it used to cost the student a question, or a retry;
    2. RESERVE the conceptual slot(s) — `conceptual_allowance(wanted)` of
       them, when the model produced any. The ask was "9 worked problems
       and one conceptual question about the concept", so the allowance is
       a place setting, not merely a ceiling: with enough worked problems
       to fill the quiz outright, taking worked-only would quietly drop the
       one question that checks whether the student knows what they are
       computing;
    3. fill the rest with worked problems, in the model's own order;
    4. if that still falls short, take the remaining conceptual questions
       rather than serve a short quiz. A quiz that is one question light is
       a worse failure than one that is a little definitional.

    Returns the selection plus human-readable notes for the caller to log,
    so the compromises are visible instead of silent.
    """
    notes: list[str] = []

    answerable = [
        q for q in questions
        if resolve_correct_index(q.correct_answer, q.options) is not None
    ]
    if len(answerable) != len(questions):
        notes.append(
            f"dropped {len(questions) - len(answerable)} unanswerable "
            f"question(s) (correct_answer matched no option)"
        )

    worked = [q for q in answerable if is_worked_problem(q)]
    conceptual = [q for q in answerable if not is_worked_problem(q)]

    allowance = conceptual_allowance(wanted)
    reserved = min(allowance, len(conceptual), wanted)
    chosen = worked[: wanted - reserved]
    chosen += conceptual[:reserved]

    if len(chosen) < wanted:
        shortfall = wanted - len(chosen)
        # Identity, not value equality. `q not in chosen` compares QuizQuestion
        # by field values (Pydantic's __eq__), and the model genuinely does
        # emit duplicates — RULE 1 of the system prompt tells it to keep going
        # when it "runs out of distinct angles around question 6". Two
        # field-identical conceptual questions would then look like one
        # already-chosen question, the backfill would drop the second, and the
        # student would get a SHORT quiz with a usable question left unused.
        # Every other membership decision in this function (and the reordering
        # below) keys on id(), so this one does too.
        already = {id(q) for q in chosen}
        extra = [q for q in conceptual if id(q) not in already][:shortfall]
        chosen += extra
        if extra:
            notes.append(
                f"only {len(worked)} worked problem(s) available for a "
                f"{wanted}-question quiz — served {len(extra)} conceptual "
                f"question(s) over the allowance of {allowance}"
            )

    if len(chosen) < wanted:
        notes.append(
            f"served {len(chosen)} of {wanted} requested questions — the "
            f"model returned too few usable ones"
        )

    # Back to the model's original ordering: the selection above groups by
    # kind, which would otherwise front-load every worked problem and park
    # the conceptual one at the end of every quiz.
    order = {id(q): i for i, q in enumerate(questions)}
    chosen.sort(key=lambda q: order.get(id(q), 0))
    return chosen, notes


@quiz_agent.output_validator
def _select_requested_quiz(ctx: RunContext[SaplingDeps], quiz: Quiz) -> Quiz:
    """Turn whatever the model produced into the quiz asked for.

    Selection, never negotiation. THIS VALIDATOR MUST NOT RAISE. Every
    version that could was measured causing the failure it meant to
    prevent:

    - raising on a bad ratio re-ran the whole generation twice, taking a
      10-question request from ~18s to 43s (and 361s in one case) and
      still serving 5 conceptual questions;
    - raising on a shortfall was worse. flash-lite intermittently returns
      almost nothing — one sampled run produced a single usable question —
      and re-asking produced the same, so the run died as
      `UnexpectedModelBehavior: Exceeded maximum output retries (2)` and
      the route turned it into a 502. That was 1 request in 5.

    A short or slightly definitional quiz is a bad quiz. An exception is no
    quiz at all, after two minutes of waiting. The notes above are logged so
    the compromise is visible; pydantic-ai's own schema retries still cover
    genuinely malformed output, which is the one case a retry does fix.
    """
    wanted = getattr(ctx.deps, "num_questions", None)
    if not wanted or wanted < 1:
        return quiz
    if model_mode() == "function":
        # The E2E seam returns a fixed three-question quiz and
        # "deliberately ignores the requested num_questions" — see
        # agents/function_handlers_e2e.py. Trimming it to the requested 2
        # would break E2E_QUIZ_CORRECT_LABELS, the clicks in
        # frontend/e2e/quiz.spec.ts, and the journey's mastery arithmetic.
        # The seam is the fixture; it is not the model's output to police.
        return quiz

    chosen, notes = select_quiz_questions(quiz.questions, wanted)
    for note in notes:
        logger.warning("quiz: %s", note)
    return Quiz(questions=chosen) if chosen else quiz

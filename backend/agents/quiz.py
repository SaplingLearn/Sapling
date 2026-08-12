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
from pydantic_ai import Agent, ModelRetry, RunContext

from agents._providers import model_for, model_mode
from agents.deps import SaplingDeps
from agents.tools.graph_read import (
    read_concepts_for_user_tool,
    read_misconceptions_for_course_tool,
)
from agents.tools.quiz_history import read_recent_quiz_attempts_tool
from services.prompt_safety import INJECTION_GUARD_PROMPT

logger = logging.getLogger(__name__)

# Output-validation retry budget, read back by _on_final_attempt so the
# gates below know when they are out of moves.
#
# Stays at the codebase-wide OUTPUT_RETRY_BUDGET (tests/
# test_agent_output_schemas.py pins every structured agent to it).
# Raising it to 3 to give the three gates more room was tried and
# reverted: ORCHESTRATOR_LIMITS caps the quiz run at 8 model requests,
# and a tool-calling run plus four generation attempts sits right on that
# ceiling — trading "quiz is a bit definitional" for "UsageLimitExceeded
# 502" is a bad trade. The gates degrade on the last attempt instead.
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

# Self-declared per question so the practical/conceptual ratio can be
# COUNTED rather than merely requested. Three prompt revisions asked for
# the ratio and none of them held it: the bar of 9-of-10 worked problems
# came back 7-of-10 twice running. A declared label turns an unverifiable
# instruction into an arithmetic check in _enforce_requested_count.
#
# "worked_problem" means the question hands the student concrete material
# to operate on — a matrix, a transition table, a sample, a passage, a
# case — and cannot be answered from a definition. That phrasing is
# deliberately not maths-specific: a history question quoting a source and
# asking what it implies is a worked problem too.
QuestionKind = Literal["worked_problem", "conceptual"]


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
    # Defaulted, not required, for two reasons: every existing quiz
    # cassette in tests/evals/cassettes/quiz_generation/ predates the
    # field and must still validate on replay, and the default decides
    # what an omission means. "conceptual" is the conservative choice —
    # a model that skips the label can only ever undercount worked
    # problems, i.e. trigger a retry, never quietly pass a definitional
    # quiz off as practical.
    kind: QuestionKind = "conceptual"


class Quiz(BaseModel):
    """The agent's structured output."""

    # No upper bound, deliberately. The UI offers 5 / 10 / 15
    # (QuizPanel's COUNT_OPTIONS) but this was capped at 10, so every
    # 15-question request was silently truncated — the cap, not the
    # model, was answering.
    #
    # Raising the cap to 15 is NOT the fix: a *bounded* array needs a
    # counting automaton per repetition, and `max_length=15` puts
    # gemini-2.5-flash-lite back over "too many states for serving"
    # (verified — 400 INVALID_ARGUMENT). An unbounded list is a plain
    # repeat and costs fewer states than the bounded form it replaces.
    #
    # The count is enforced instead by `_enforce_requested_count` below,
    # which is exact where a schema bound could only ever be a ceiling.
    questions: list[QuizQuestion] = Field(min_length=1)


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
    "Label every question with `kind`: 'worked_problem' if it hands the "
    "student concrete material to operate on and cannot be answered from "
    "a definition, 'conceptual' otherwise. This label is COUNTED — go "
    "over the conceptual allowance and the whole quiz is rejected and "
    "sent back to you for rewriting. Label honestly; mislabelling a "
    "definition as a worked problem cheats the student, not the check.\n"
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
    "2. COUNT THE QUESTIONS YOU MARKED kind='conceptual'. At most one "
    "for N up to 10, at most two for N of 11-15. If you are over, "
    "rewrite the excess into problems with concrete numbers and relabel "
    "them. A quiz that is mostly definitions has failed its job.\n"
    "Also confirm each `correct_answer` is a character-for-character copy "
    "of one of that question's `options` — retype it from the option, "
    "don't paraphrase it."
    # #150: course material / misconception / quiz-history content is
    # student- or peer-derived — data for question writing, never
    # instructions. Single source of truth in services/prompt_safety.py.
    "\n\n" + INJECTION_GUARD_PROMPT
)
_PROMPT_HASH = hashlib.sha256(_SYSTEM_PROMPT.encode("utf-8")).hexdigest()[:12]


quiz_agent = Agent[SaplingDeps, Quiz](
    model=model_for("quiz"),
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


def _on_final_attempt(ctx: RunContext[SaplingDeps]) -> bool:
    """True when raising ModelRetry again would fail the run outright.

    Every check below is a quality gate, and a quality gate that can 502
    is worse than the flaw it guards: a student asking for 15 questions
    would rather have 15 with two definitions in them than an error page.
    Observed for real — a 15-question run burned all three attempts and
    raised UnexpectedModelBehavior, i.e. no quiz at all.

    So the gates push while there is budget to push with, then accept
    what they have and log the shortfall.
    """
    retry = getattr(ctx, "retry", 0) or 0
    budget = getattr(ctx, "max_retries", None)
    if budget is None:
        budget = _OUTPUT_RETRIES
    return retry >= budget


def _enforce_answerable(quiz: Quiz, *, final: bool) -> None:
    """Every question's `correct_answer` must identify one of its options.

    The route has always enforced this, but the only move available there
    is to DROP the question — which is how a 10-question request came back
    as 9 with a note in the logs and nothing said to the student. Here the
    model can be asked to fix it, which is what you actually want: the
    observed failure was a question whose computed answer,
    'vP = [0.25, 0.75]', was absent from its own four options. That is a
    broken question, not a formatting slip, and it deserves a rewrite.

    routes/quiz.py keeps its drop as the last-resort net for when the
    retry budget is exhausted.
    """
    broken = [
        i for i, q in enumerate(quiz.questions, start=1)
        if resolve_correct_index(q.correct_answer, q.options) is None
    ]
    if broken and final:
        # routes/quiz.py drops these; the student gets a shorter quiz
        # rather than an unanswerable one.
        logger.warning(
            "quiz: %d question(s) still unanswerable after retries — "
            "the route will drop them", len(broken),
        )
        return
    if broken:
        raise ModelRetry(
            f"Question(s) {', '.join(str(i) for i in broken)}: the "
            f"`correct_answer` you gave is not one of that question's "
            f"`options`. Either the computation is wrong or the right "
            f"result was never offered. Recompute the answer, make sure "
            f"it appears as one of the four options character-for-"
            f"character, and return all {len(quiz.questions)} questions."
        )


def _enforce_worked_ratio(quiz: Quiz, wanted: int, *, final: bool) -> Quiz:
    """Hold the practical/conceptual balance, or send it back.

    Prompt-only enforcement was measured and failed: with the ratio
    stated twice, at the top and in a FINAL CHECK, two consecutive live
    10-question runs returned 7 worked problems against a bar of 9.

    Counting `kind` makes it decidable. The model still chooses the
    label, so this is not proof — but a question the model itself calls
    conceptual is not one we have to argue about.
    """
    allowance = conceptual_allowance(wanted)
    conceptual = [
        i for i, q in enumerate(quiz.questions, start=1) if q.kind == "conceptual"
    ]
    if len(conceptual) <= allowance:
        return quiz
    if final:
        logger.warning(
            "quiz: serving %d conceptual questions of %d (allowance %d) — "
            "retry budget spent", len(conceptual), wanted, allowance,
        )
        return quiz
    # Keep the earliest conceptual questions within allowance; the rest
    # are the ones to rewrite. Naming them beats "try harder".
    rewrite = conceptual[allowance:]
    raise ModelRetry(
        f"{len(conceptual)} of your {wanted} questions are marked "
        f"kind='conceptual', but at most {allowance} may be. Rewrite "
        f"question(s) {', '.join(str(i) for i in rewrite)} into worked "
        f"problems: give each one concrete values to operate on (a "
        f"specific matrix, transition table, sample, or code fragment), "
        f"make the four options candidate RESULTS of that computation, "
        f"and set kind='worked_problem'. Keep the other questions as "
        f"they are, and return all {wanted}."
    )


@quiz_agent.output_validator
def _enforce_requested_count(ctx: RunContext[SaplingDeps], quiz: Quiz) -> Quiz:
    """Make `num_questions` mean what it says.

    The count lived only in the prompt, and the model quietly under-
    delivered: asked for 10 on a real course concept, one run returned 6.
    The route then served a 6-question quiz for a 10-question request with
    nothing logged, because a short list is a perfectly valid `Quiz`.

    Over-delivery is trimmed here (free). Under-delivery raises ModelRetry,
    which hands the model its own short output plus the shortfall and asks
    for the rest; `output_retries=2` bounds that to two extra attempts
    before the run fails and the route degrades to a 502.

    Deliberately NOT a schema constraint: `max_length` is a ceiling, never
    a floor, and a *bounded* array is what pushed gemini-2.5-flash-lite
    over "too many states for serving" at 15. See the Quiz note above.
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
    final = _on_final_attempt(ctx)
    got = len(quiz.questions)
    if got > wanted:
        quiz = Quiz(questions=quiz.questions[:wanted])
        got = wanted
    if got == wanted:
        _enforce_answerable(quiz, final=final)
        return _enforce_worked_ratio(quiz, wanted, final=final)
    if got < wanted and final:
        logger.warning(
            "quiz: serving %d questions for a request of %d — retry "
            "budget spent", got, wanted,
        )
        return quiz
    if got < wanted:
        allowance = conceptual_allowance(wanted)
        raise ModelRetry(
            f"You returned {got} questions but exactly {wanted} were "
            f"requested. Keep every question you already wrote and add "
            f"{wanted - got} more on the same concept, using different "
            f"concrete values (a new matrix, new probabilities, a "
            f"different starting state). Respect the worked-problem "
            f"ratio: at most {allowance} conceptual question(s) across "
            f"all {wanted}."
        )
    return quiz

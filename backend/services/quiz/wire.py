"""
backend/services/quiz/wire.py — moved from routes/quiz.py (#118).

The quiz wire format: agent output -> stored question dicts, the keyless
client projection, and the per-question validity checks.

Function bodies are verbatim from the route; names (leading
underscores included) are unchanged, and routes/quiz.py re-exports them.
"""
import logging
import re

from agents.quiz import QuizQuestion
from services.quiz.config import CONCRETE_DIFFICULTIES
from services.encryption import decrypt_json_column
from services.quiz.grading import WRITTEN_TYPES, numeric_value
from services.quiz.algebra import equivalent_algebra
from services.fingerprint import fingerprint
from services.quiz.identity import question_hash

# Log records keep the name they had in routes/quiz.py before the #118 split:
# the move must not change what an operator (or a caplog test) filters on.
logger = logging.getLogger("routes.quiz")


# ── Wire-format helpers (legacy + agent paths share this shape) ──────────────
#
# `submit_quiz` expects each question dict to look like:
#   {
#     "id": int,
#     "question": str,
#     "options": [{"label": "A"|"B"|..., "text": str, "correct": bool}, ...],
#     "explanation": str,
#     "concept_tested": str,
#     "difficulty": "easy"|"medium"|"hard",
#   }
# This is the format the original quiz_generation.txt prompt produced.
# The agent's QuizQuestion has a flatter shape — we map it back here so the
# stored `questions_json` and the response payload don't change. Frontend
# `submitQuiz`/`scoreQuiz` flows are unaffected.


_OPTION_LABELS = ["A", "B", "C", "D", "E", "F"]


# Rank order for tie-breaking the overall difficulty report — derived from
# the config tuple so a difficulty added there can't be silently dropped by
# _resolved_difficulty's counting.
_DIFFICULTY_RANK = {d: i for i, d in enumerate(CONCRETE_DIFFICULTIES)}


# The keys a keyless (student-facing) question may carry. An ALLOWLIST,
# not a denylist: `explanation` states the correct answer in prose, and a
# stored row from an older shape can hold the answer under any key at all
# (the rich seed has {"q":..., "a":...}). Anything not listed here never
# reaches a client that hasn't answered yet.
_KEYLESS_QUESTION_KEYS = ("id", "question", "concept_tested", "difficulty", "type", "material_context")
_KEYLESS_OPTION_KEYS = ("label", "text")


def _written_response_text(row: dict) -> str:
    if not row.get("answer_text"):
        return ""
    value = decrypt_json_column(row["answer_text"])
    return value.get("text", "") if isinstance(value, dict) else ""


def _is_wire_question(q) -> bool:
    """True if this stored question is in the current wire shape, so
    _strip_answer_key can be trusted to remove everything sensitive."""
    if isinstance(q, dict) and q.get("type") in WRITTEN_TYPES:
        return _validate_wire_question(q)
    return (
        isinstance(q, dict)
        and isinstance(q.get("options"), list)
        and bool(q.get("options"))
        and all(isinstance(o, dict) and "label" in o for o in q["options"])
    )


def _strip_answer_key(wire_questions: list[dict]) -> list[dict]:
    """The student-facing view of a question: no per-option `correct`
    booleans and no `explanation` (#541 C3, tightened in #542 review).

    Built by allowlist, so a question shape this function doesn't
    recognise can't leak an answer through an unexpected key. Callers must
    gate on _is_wire_question first — an unrecognised shape has no safe
    keyless projection at all.
    """
    stripped = []
    for q in wire_questions:
        q2 = {k: q[k] for k in _KEYLESS_QUESTION_KEYS if k in q}
        q2["options"] = [
            {k: o[k] for k in _KEYLESS_OPTION_KEYS if k in o}
            for o in q.get("options", [])
        ]
        stripped.append(q2)
    return stripped


def _resolved_difficulty(wire_questions: list[dict]) -> str:
    """The overall difficulty generation actually produced (#540 A1).

    Mode of the per-question difficulties; ties break to the harder value
    so the report never understates what the student is about to face.
    Defaults to 'medium' when nothing usable is present (can't happen for
    agent output — QuizQuestion.difficulty is a concrete Literal — but
    this also runs on stored legacy rows).
    """
    counts: dict[str, int] = {}
    for q in wire_questions:
        d = q.get("difficulty")
        if d in _DIFFICULTY_RANK:
            counts[d] = counts.get(d, 0) + 1
    if not counts:
        return "medium"
    return max(counts, key=lambda d: (counts[d], _DIFFICULTY_RANK[d]))


# The wire contract every emitted question must satisfy (#543 E3). The
# agent schema carries no option bound (agents/quiz.py: nested array bounds
# 400 on Gemini), so the route is the only check on option count, and it is
# the boundary the stored questions_json and every grading path trust.
_MIN_OPTIONS = 2
# What the agent must emit for a multiple-choice item (the system prompt's "4
# options"). Checked per item in _agent_question_to_wire, not in the agent's
# output schema, so one short item is dropped instead of failing the quiz.
_MCQ_OPTIONS = 4
_MAX_ANSWER_CHARS = 2000
# Generation-only guards for items a student cannot answer fairly (found
# clicking through live quizzes). Applied in _agent_question_to_wire, never in
# _validate_wire_question, which also re-checks stored attempts on resume.
# A symbolic key whose letter run is a word is not a product: the grammar
# reads "lambda" as a*a*b*d*l*m, so the real answer is wrong and an anagram
# is right. A 4+ letter run is taken as a word; so is a short Greek-letter or
# constant name ("pi r^2" grades as p*i*r^2, and a student typing the symbol
# cannot match it at all). Short products ("2xy", "mgh") stay allowed. Function
# names need no entry here: the grammar refuses them, and
# _validate_wire_question drops a key it cannot parse.
_SYMBOLIC_LETTER_RUN = re.compile(r"[A-Za-z]+")
_SYMBOLIC_WORD_MIN = 4
# "mu" and "xi" are left out: m*u (mass times initial velocity) and x*i are
# ordinary products in mechanics and algebra keys.
_SYMBOLIC_NAMES = frozenset({"pi", "nu", "rho", "tau", "phi", "chi", "psi", "eta"})
# A short-answer key is a term or brief fact (docs/quiz-formats.md); exact
# matching can never accept a sentence or paragraph key. A sentence break is a
# semicolon, "!" or "?", or a full stop, each followed by more text, except a
# full stop right after an initial ("John F. Kennedy", "U.S.", "e.g.") or a
# known abbreviation ("St. Louis", "Prof. Xavier", "Sept. 11"). A full stop
# after anything else — a word, a number, a bracket, a quote, a percent sign
# ("x (y). Then", '"ATP". It', "10%. Then") — ends a sentence.
_SHORT_ANSWER_MAX_WORDS = 8
# A stem cut at an inner quote ends in the space that preceded the quote
# ('...as the ', 'Consider this definition. '); a whole stem the model padded
# usually ends in a newline ("Define osmosis.\n", a code fence). So: trailing
# spaces are a cut unless the stem ends in its question mark, a "___" blank or
# a code fence; a trailing newline is padding unless the stem stops on ":" or
# "," (content was coming: 'Read the code:\n').
_WHOLE_STEM_ENDINGS = ("?", "_", "`")
_CUT_BEFORE_NEWLINE = (":", ",")
_SENTENCE_BREAK = re.compile(r"(?:;|([A-Za-z0-9]*)([.!?]))\s+\S")
_ABBREVIATIONS = frozenset({
    "mr", "mrs", "ms", "dr", "prof", "st", "mt", "ft", "jr", "sr", "sgt", "capt", "col",
    "gen", "lt", "pres", "gov", "sen", "rep", "rev", "hon", "dept", "univ", "inc", "ltd",
    "co", "corp", "vs", "etc", "approx", "no", "vol", "fig", "eq", "ch", "sec", "jan",
    "feb", "mar", "apr", "jun", "jul", "aug", "sep", "sept", "oct", "nov", "dec",
})


def _is_symbolic_word(key: str) -> bool:
    return any(
        len(run) >= _SYMBOLIC_WORD_MIN or run.lower() in _SYMBOLIC_NAMES
        for run in _SYMBOLIC_LETTER_RUN.findall(key)
    )


def _is_sentence(key: str) -> bool:
    if len(key.split()) > _SHORT_ANSWER_MAX_WORDS:
        return True
    for m in _SENTENCE_BREAK.finditer(key):
        word, mark = m.groups()
        if mark is None or mark != ".":
            return True  # a semicolon, "!" or "?" mid-key
        if word.lower() == "no" and key[m.end() - 1].isdigit():
            continue  # "Symphony No. 9", "No. 10 Downing Street" — but not "No. It is not."
        if word.lower() != "no" and ((len(word) == 1 and word.isalpha()) or word.lower() in _ABBREVIATIONS):
            continue
        return True  # after a word, a number, or punctuation (word == "")
    return False


def _unfair_written_key(q: QuizQuestion) -> str | None:
    """Why this written item's key cannot be fairly matched, or None.

    An item is judged on everything the grader accepts, not the canonical key
    alone: a sentence-length key with a short alias ("base case") still lets
    the student who writes the term get it right.
    """
    keys = [k.strip() for k in (q.correct_answer, *q.accepted_answers) if k.strip()]
    if q.type == "symbolic" and _is_symbolic_word(q.correct_answer.strip()):
        return "symbolic key is a word"
    if q.type == "short_answer" and all(_is_sentence(k) for k in keys):
        return "short-answer key is a sentence"
    return None


def _validate_wire_question(wire: dict) -> bool:
    """True if this wire question is answerable and gradable.

    Rejects: fewer than two options, duplicate option text (the student
    can pick "the same" answer and be wrong), and anything other than
    exactly one correct option (zero = ungradable free point per #129,
    two = the grader's first-match wins silently).
    """
    if wire.get("type") in WRITTEN_TYPES:
        answer = wire.get("correct_answer")
        return (
            isinstance(answer, str) and bool(answer.strip())
            and len(answer) <= _MAX_ANSWER_CHARS and not wire.get("options")
            and (wire["type"] != "numeric" or numeric_value(answer) is not None)
            and (wire["type"] != "symbolic" or equivalent_algebra(answer, answer))
        )
    options = wire.get("options") or []
    qid = wire.get("id")
    if len(options) < _MIN_OPTIONS:
        logger.warning(
            "quiz: dropping question id=%s — only %d option(s)", qid, len(options)
        )
        return False
    # Compare exactly as GRADING does (_agent_question_to_wire matches
    # correct_answer with `text.strip() == canonical`): case-sensitively.
    # Casefolding here would reject items whose options differ only by
    # case — `list` vs `List` is a real question, and one this route
    # graded correctly before the check existed.
    texts = [str(o.get("text", "")).strip() for o in options]
    if len(set(texts)) != len(texts):
        logger.warning("quiz: dropping question id=%s — duplicate option text", qid)
        return False
    n_correct = sum(1 for o in options if o.get("correct"))
    if n_correct != 1:
        logger.warning(
            "quiz: dropping question id=%s — %d correct options (need exactly 1)",
            qid, n_correct,
        )
        return False
    return True


def _agent_question_to_wire(q: QuizQuestion, qid: int) -> dict | None:
    """Map an agent QuizQuestion to the legacy wire-format dict, or
    return None if the question violates the contract.

    The agent must produce `correct_answer` as one of the strings in
    `q.options` verbatim. If that invariant is broken (LLM drift), we
    DROP the question rather than silently mark an arbitrary option
    correct — emitting an unverifiable question to the user is worse
    than a slightly shorter quiz.

    Returning None lets the caller filter questions out cleanly.
    """
    stem = q.question.rstrip()
    if stem != q.question:
        # Gemini can end a function-call string at an inner double quote
        # ('...referred to as the "energy currency"' served as '...as the ',
        # 'Fill in the blank: "..."' as 'Fill in the blank: '). See
        # _WHOLE_STEM_ENDINGS for how a cut is told from padding; a whole stem
        # is served trimmed.
        padded_with_newline = "\n" in q.question[len(stem):]
        cut = (
            stem.endswith(_CUT_BEFORE_NEWLINE)
            if padded_with_newline
            else not stem.endswith(_WHOLE_STEM_ENDINGS)
        )
        if cut:
            logger.warning("quiz: dropping question id=%d — stem cut off mid-string", qid)
            return None
        q = q.model_copy(update={"question": stem})
    if q.type in WRITTEN_TYPES:
        if (reason := _unfair_written_key(q)) is not None:
            logger.warning("quiz: dropping question id=%d — %s", qid, reason)
            return None
        if q.options:
            # A written item with answer choices is format drift: drop it here,
            # per item (agents/quiz.py keeps this out of the output schema).
            logger.warning("quiz: dropping question id=%d — written item has options", qid)
            return None
        # A blank or unbounded alias is dropped on its own; it says nothing
        # about whether the rest of the item is sound.
        accepted = [a for a in q.accepted_answers if a.strip() and len(a) <= _MAX_ANSWER_CHARS]
        wire = {
            "id": qid, "type": q.type, "question": q.question, "options": [],
            "correct_answer": q.correct_answer, "accepted_answers": accepted,
            "explanation": q.explanation, "concept_tested": q.concept,
            "difficulty": q.difficulty,
            "question_hash": question_hash(q.question, [q.type]),
        }
        return wire if _validate_wire_question(wire) else None
    if len(q.options) != _MCQ_OPTIONS:
        logger.warning(
            "quiz: dropping question id=%d — %d option(s), need %d",
            qid, len(q.options), _MCQ_OPTIONS,
        )
        return None
    options: list[dict] = []
    matched = False
    canonical = q.correct_answer.strip()
    for i, text in enumerate(q.options[: len(_OPTION_LABELS)]):
        is_correct = (not matched) and (text.strip() == canonical)
        if is_correct:
            matched = True
        options.append({
            "label": _OPTION_LABELS[i],
            "text": text,
            "correct": is_correct,
        })
    if not matched:
        # Generation drift: agent's correct_answer doesn't match any
        # option verbatim. Surface in logs (Logfire span carries the
        # question_id correlation) and drop. Caller filters None.
        #
        # Don't log the raw text — student-content concept names and
        # quiz answers don't belong in stdout/Railway logs. The
        # fingerprint is stable enough to correlate with the same
        # generation drift if it recurs; the full content is still in
        # Logfire spans (where the scrubber from PR #67 controls egress).
        # services.fingerprint.fingerprint joins parts with the ASCII
        # unit-separator (\x1f), so option text containing pipes or
        # other punctuation can't accidentally collide.
        canonical_only = q.correct_answer.strip()
        fp = fingerprint(canonical_only, q.options)
        logger.warning(
            "quiz: dropping question id=%d — correct_answer not found in "
            "options (n_options=%d, canonical_len=%d, fp=%s)",
            qid, len(q.options), len(canonical_only), fp,
        )
        return None
    if not _validate_wire_question({"id": qid, "options": options}):
        return None
    return {
        "id": qid,
        "question": q.question,
        "options": options,
        "explanation": q.explanation,
        "concept_tested": q.concept,
        "difficulty": q.difficulty,
        # E5: stable identity, computed from the same normalized stem +
        # option set every future reader will derive it from. `id` is only
        # unique WITHIN an attempt; this is what survives across attempts
        # (E6's repetition guard) and, later, across students (item stats).
        "question_hash": question_hash(q.question, q.options),
    }


# Keys that exist for the server's benefit and are never part of the client
# contract. `_strip_answer_key`'s allowlist already excludes them on the
# keyless (default) path; this is the same exclusion for the opt-in keyed
# path (`include_answer_key=true` — see
# models.GenerateQuizBody.include_answer_key, #546), so provenance can't leak
# into a browser payload just because a caller asked for the answer key too.
#
# `question_hash` sits here too — not because it is sensitive (it is the
# student's own question) but because nothing client-side consumes it yet.
# Per-question feedback (#26) is the change that should surface it, and it
# should do so by adding it to the keyless allowlist, deliberately.
_INTERNAL_QUESTION_KEYS = ("provenance", "question_hash")


def _client_questions(wire_questions: list[dict], include_answer_key: bool) -> list[dict]:
    """The questions as the client may see them."""
    if not include_answer_key:
        return _strip_answer_key(wire_questions)
    return [
        {k: v for k, v in q.items() if k not in _INTERNAL_QUESTION_KEYS}
        for q in wire_questions
    ]

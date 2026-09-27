"""Check item models, identity, selection, validation (spec §2, §3.4, §3.5, §4;
§13 A2, A17, A22, A23).

Pure: imports nothing from agents/, db/, services/. The hash normalization is
a deliberate copy of services/quiz_identity.py's idea, versioned separately —
the two identities must be able to change independently. Items are course
assets keyed on (course_id, concept_key); the concept_key rule itself lives in
services/graph_service._normalize_concept and is applied by the service.

References are model-generated and unverified (A17): nothing here calls them
verified, and `canonical_verified` is never set true by this package (A22).

Every item states its final answer as a structured field (§13 A34): the
generator knows the answer, so it says it, and nothing parses a reference for
one. `answer_tokens` is the one reading of such an answer — validate_draft
checks a draft's final_answer with it, and PKG-06's learning/leak.py matches
the stored final_answer in tutor text with it. It lives here, not in leak.py,
because the upload path (which validates drafts) must not load the dark
PKG-06 layer.
"""

from __future__ import annotations

import hashlib
import math
import re
import unicodedata
from collections.abc import Iterable, Sequence
from decimal import Decimal, InvalidOperation
from typing import Literal, NamedTuple

from pydantic import BaseModel, Field

from learning.params import (
    CHECK_HASH_VERSION,
    CHECK_ITEM_ANSWER_KINDS,
    CHECK_ITEM_DIFFICULTIES,
    CHECK_ITEM_FINAL_ANSWER_MAX_TOKENS,
    CHECK_ITEM_FORMATS,
    CHECK_ITEM_MIN_RUBRIC,
    CHECK_ITEM_MIN_WRONG,
    CHECK_ITEM_STEPWISE_MIN_STEPS,
)

_SEP = "\x1f"  # unit separator: never appears in normalized text
_STEP_LINE = re.compile(r"^\s*\d+[.)]", re.MULTILINE)  # a numbered step, A17/A22
_WORD = re.compile(r"\w+")
# Leak-comparison tokens: a word (a number's decimal points and the letters
# after it included, so "2.5", "2x" and "2.5x" are one token each), or one
# math symbol. Sentence punctuation (. , ; : ! ? quotes brackets dashes) is not
# a token, so a reference ending in "." still matches mid-sentence; operators
# are, so "x = 2" is not found inside "x + 2 = 4". Every token is a whole run
# of the plain \w+ tokenizer's tokens, or a symbol it dropped.
_LEAK_TOKEN = re.compile(r"\d+(?:\.\d+)*\w*|\w+|[+\-*/=<>^%×÷±≤≥≠≈√∑∏∫∂∞→←⇒⇔]")
# Concept-name tokens shorter than this ("of", "to", "a") say nothing about
# which passage discusses the concept, so rank_chunks_for_concept ignores them.
# The one small literal the PKG-04 prompt allows here: a tokenizer floor, not a
# loop tuning knob, so it does not live in learning/params.py.
_MIN_TOKEN_LEN = 3
# English function words of that length or more. They occur in almost any
# passage, so a match on one says nothing about the concept: without this,
# "Causes of the French Revolution" met the backfill's relevance floor (A23)
# against a CS passage through "the" and was drafted from unrelated text.
# Every NLTK English stopword of that length (its contractions split by the
# \w+ tokenizer: "don't" -> "don"), plus the determiners, quantifiers,
# conjunctions and adverbs it leaves out ("every", "one", "since", "however").
# Content words stay, however common ("use", "force", "case").
_STOPWORDS = frozenset(
    """
    about above across after again against ain all almost along already also
    although always among amongst and another any anyone anything are aren
    because been before being below between beyond both but can cannot could
    couldn despite did didn does doesn doing don down during each either else
    even ever every everyone everything few for from further hadn has hasn have
    had haven having hence her here hers herself him himself his how however indeed
    instead into isn its itself just like many may might mightn more most much
    must mustn myself needn neither never none nor not nothing now off often once
    one only onto other our ours ourselves out over own per perhaps quite rather
    same several shall shan she should shouldn since some someone something still
    such than that the their theirs them themselves then there therefore these
    they this those though through throughout thus too toward towards under
    unless until upon very via was wasn were weren what whatever when whenever
    where whereas wherever whether which whichever while who whoever whom whose
    why will with within without won would wouldn yet you your yours yourself
    yourselves
    """.split()
)
# Articles and determiners the concept-name rule looks past (A34): they add
# nothing a hint naming the concept would not also say.
_DETERMINERS = frozenset({"the", "a", "an", "its", "this", "that"})
_MC_REASON = "mc_reason"
_NUMERIC = "numeric"


class RubricItem(BaseModel):
    id: str
    text: str


class WrongReason(BaseModel):
    key: str
    text: str


class Option(BaseModel):
    letter: str
    text: str
    wrong_key: str | None = None  # None on the correct option


class CheckItem(BaseModel):
    """One stored check item, DECRYPTED. A course asset keyed on
    (course_id, concept_key) — no node_id (A2)."""

    id: str
    course_id: str
    concept_key: str
    document_id: str | None = None
    format: str
    difficulty: int
    prompt: str
    reference_answer: str
    rubric: list[RubricItem]
    common_wrong: list[WrongReason]
    options: list[Option] | None = None
    correct_option: str | None = None
    answer_kind: Literal["free", "numeric"] = "free"
    canonical_answer: str | None = None
    tolerance: float | None = None
    canonical_verified: bool = False
    stepwise: bool = False
    source_chunk_ids: list[str]
    question_hash: str
    graded: bool = False
    created_at: str | None = None
    # A34: None on a row drafted before the column existed — never served
    # (is_servable); scripts/backfill_check_items.py regenerates its concept.
    final_answer: str | None = None


class CheckItemDraft(BaseModel):
    """The agent's per-item output. FLAT — str / int / bool / list[str] only
    (docs/attempts/2026-05-03-orchestrator-schema-complexity.md)."""

    concept: str = Field(
        description="which of this call's concepts the item assesses, copied exactly"
    )
    format: str = Field(description="one of free | teachback | mc_reason")
    difficulty: int = Field(description="1 recall, 2 application, 3 transfer")
    prompt: str
    reference_answer: str = Field(
        description="complete model answer; its LAST sentence is 'Final answer: <final_answer>.'"
    )
    final_answer: str = Field(
        description=(
            "the final answer reference_answer concludes with, copied word for word from "
            "its closing 'Final answer:' sentence without the label; at most "
            f"{CHECK_ITEM_FINAL_ANSWER_MAX_TOKENS} tokens"
        )
    )
    rubric: list[str] = Field(default_factory=list)
    wrong_keys: list[str] = Field(
        default_factory=list,
        description="every format: snake_case misconception ids, same length as wrong_texts",
    )
    wrong_texts: list[str] = Field(
        default_factory=list, description="wrong_texts[i] describes wrong_keys[i]"
    )
    option_letters: list[str] = Field(default_factory=list)  # mc_reason only
    option_texts: list[str] = Field(default_factory=list)
    option_wrong_keys: list[str] = Field(
        default_factory=list,
        description='one entry per option letter, same order; "" for the correct option',
    )
    correct_option: str = ""
    answer_kind: str = "free"
    canonical_answer: str = ""  # numeric only; "" = none
    tolerance: str = ""  # "" = none; parsed in code
    stepwise: bool = Field(
        default=False, description="true only if reference_answer has numbered step lines"
    )
    chunk_ids: list[str] = Field(default_factory=list)


# ── answer normalisation (A34) ─────────────────────────────────────────────
#
# A final answer is compared as a run of tokens: a number (ASCII digits, a
# thousands-separated "1,250" whole, a decimal part, a bare ".5") by its value,
# a word (any letters) casefolded, or one math symbol. Before tokenizing,
# "**" is "^", a superscript run is "^" and its characters ("x²" = "x^2",
# "10⁻³" = "10^-3"), a multiplication sign (* × · ⋅ ∙ ∗) is juxtaposition,
# a minus sign or en dash is "-", and any other non-ASCII character is NFKC-
# folded. Whitespace, brackets and sentence punctuation are no token, so
# "6 x ^ 2", "6*x**2", "6x²" and "(6x^2)." are all 6 x ^ 2.

_SUPERSCRIPTS = "⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻⁼⁽⁾ⁿⁱ"
_FROM_SUPERSCRIPT = str.maketrans(_SUPERSCRIPTS, "0123456789+-=()ni")
_POWER = "**"
_EXPONENT = "^"
_TIMES = frozenset("*×·⋅∙∗")
_MINUS = frozenset("\u2212\u2012\u2013")  # minus sign, figure dash, en dash
_JUXTAPOSE = " "
_ANSWER_TOKEN = re.compile(
    r"([0-9]{1,3}(?:,[0-9]{3})+(?![0-9])(?:\.[0-9]+)?|[0-9]+(?:\.[0-9]+)?|\.[0-9]+)"
    r"|([^\W\d_]+)"
    r"|([-+=<>/^%±≤≥≠≈√∑∏∫∂∞→←⇒⇔÷])"
)


class AnswerToken(NamedTuple):
    value: str  # a number's canonical spelling, a casefolded word, or one symbol
    start: int  # span in the ORIGINAL text (a rewrite keeps its source span)
    end: int
    number: bool


def number_value(text: str) -> str:
    """A number's canonical spelling: no separators, leading or trailing zeros
    ("01,250.0" -> "1250", ".50" -> "0.5")."""
    whole, _, frac = text.replace(",", "").partition(".")
    whole, frac = whole.lstrip("0") or "0", frac.rstrip("0")
    return f"{whole}.{frac}" if frac else whole


def _fold(ch: str) -> str:
    piece = ch if ch.isascii() else unicodedata.normalize("NFKC", ch)
    return "".join(_JUXTAPOSE if c in _TIMES else "-" if c in _MINUS else c for c in piece)


def _normalised(text: str) -> tuple[str, list[tuple[int, int]]]:
    """`text` rewritten as above, with the original span of each character. A
    superscript run is one unit: every character it becomes (its "^" too)
    spans the whole run, so a stripper never masks part of it (the rest would
    start a new run and read as a new "^")."""
    out: list[str] = []
    spans: list[tuple[int, int]] = []
    i = 0
    while i < len(text):
        end = i
        while end < len(text) and text[end] in _SUPERSCRIPTS:
            end += 1
        if end > i:
            piece = _EXPONENT + text[i:end].translate(_FROM_SUPERSCRIPT)
        elif text.startswith(_POWER, i):
            piece, end = _EXPONENT, i + len(_POWER)
        else:
            piece, end = _fold(text[i]), i + 1
        out.append(piece)
        spans.extend([(i, end)] * len(piece))
        i = end
    return "".join(out), spans


def answer_tokens(text: str | None) -> list[AnswerToken]:
    """The A34 tokens of `text`, each with its span in `text`."""
    norm, spans = _normalised(text or "")
    tokens = []
    for m in _ANSWER_TOKEN.finditer(norm):
        number, word, symbol = m.groups()
        if number is not None:
            value = number_value(number)
        elif word is not None:
            value = word.casefold()
        else:
            value = symbol
        tokens.append(
            AnswerToken(value, spans[m.start()][0], spans[m.end() - 1][1], number is not None)
        )
    return tokens


def answer_run(text: str | None) -> tuple[str, ...]:
    return tuple(t.value for t in answer_tokens(text))


def find_runs(values: Sequence[str], run: Sequence[str]) -> list[int]:
    """Every index at which `run` occurs in `values` as consecutive tokens; []
    for an empty run."""
    run = tuple(run)
    if not run:
        return []
    k = len(run)
    return [
        i
        for i in range(len(values) - k + 1)
        if values[i] == run[0] and tuple(values[i : i + k]) == run
    ]


def contains_run(values: Sequence[str], run: Sequence[str]) -> bool:
    return bool(find_runs(values, run))


def answer_in(text: str | None, answer: str | None) -> bool:
    """Whether `answer` occurs in `text` as a whole run of answer tokens (an
    answer with no token occurs nowhere)."""
    return contains_run(answer_run(text), answer_run(answer))


def is_servable(item) -> bool:
    """A34: only an item that states a final answer can be leak-checked, so
    only such an item is ever selected (fail closed; a legacy row is None)."""
    return bool(answer_run(getattr(item, "final_answer", None)))


# ── identity ───────────────────────────────────────────────────────────────


def normalize(value) -> str:
    """Whitespace runs collapse to one space, then casefold (the
    quiz_identity.normalize_text idea, copied — not imported)."""
    if value is None:
        return ""
    return " ".join(str(value).split()).casefold()


def _sha256(body: str) -> str:
    # errors="replace": a lone surrogate must not raise; identity is metadata.
    return hashlib.sha256(body.encode("utf-8", errors="replace")).hexdigest()


def question_hash(prompt_plaintext) -> str:
    """Full sha256 hex of the version tag and the normalized PLAINTEXT prompt.
    Reads CHECK_HASH_VERSION at call time: bumping it re-keys every item."""
    return _sha256(f"{CHECK_HASH_VERSION}{_SEP}{normalize(prompt_plaintext)}")


def item_id(course_id: str, concept_key: str, question_hash: str) -> str:
    """Primary key of an item: stable per (course_id, concept_key,
    question_hash), so a re-run upserts onto the same row (A2)."""
    return _sha256(f"{course_id}{_SEP}{concept_key}{_SEP}{question_hash}")


# ── validation ─────────────────────────────────────────────────────────────


def _words(value) -> str:
    """normalize(), then punctuation dropped: the word sequence of a text."""
    return " ".join(_WORD.findall(normalize(value)))


def _leak_tokens(value) -> str:
    """normalize(), then the _LEAK_TOKEN sequence, space-joined."""
    return " ".join(_LEAK_TOKEN.findall(normalize(value)))


def leak_in_prompt(prompt, reference_answer) -> bool:
    """True when the (normalized, non-empty) reference answer appears verbatim
    inside the (normalized) prompt, compared as whole tokens: sentence
    punctuation is ignored, so a reference ending in "." still leaks into a
    prompt that continues the sentence, while math operators and decimals are
    kept, so "x = 2" does not leak into "Solve x + 2 = 4"."""
    ref = _leak_tokens(reference_answer)
    if not ref:
        return False
    return f" {ref} " in f" {_leak_tokens(prompt)} "


def _finite_float(text: str) -> float | None:
    try:
        value = float(text)
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


def _option_reasons(draft: CheckItemDraft) -> list[str]:
    letters, texts, keys = draft.option_letters, draft.option_texts, draft.option_wrong_keys
    if not (len(letters) == len(texts) == len(keys)):
        return [
            f"option arrays differ in length: {len(letters)} letters, "
            f"{len(texts)} texts, {len(keys)} wrong keys"
        ]
    reasons = []
    if len(set(letters)) != len(letters):
        reasons.append("option letters are not distinct")
    correct = [i for i, letter in enumerate(letters) if letter == draft.correct_option]
    if len(correct) != 1:
        reasons.append(
            f"option: {len(correct)} option_letters entries equal correct_option "
            f"{draft.correct_option!r} (need exactly 1)"
        )
        return reasons
    if keys[correct[0]]:
        reasons.append("option: the correct option carries a wrong_key")
    distractors = [i for i in range(len(letters)) if i != correct[0]]
    if not distractors:
        reasons.append("option: mc_reason has no distractor")
    listed = set(draft.wrong_keys)
    for i in distractors:
        if keys[i] not in listed:
            reasons.append(
                f"option {letters[i]!r}: distractor wrong_key {keys[i]!r} is not in wrong_keys"
            )
    return reasons


def _decimal(text: str) -> Decimal | None:
    try:
        return Decimal(text.strip())
    except (InvalidOperation, ValueError):
        return None


_E_NOTATION = ("e",)
_TIMES_TEN = ("10", _EXPONENT)
_X_TIMES_TEN = ("x", *_TIMES_TEN)
_SIGNS = ("-", "+")
_RELATIONS = frozenset({"=", "≈"})
_FRACTION = "/"


def _exponent(after: Sequence[str]) -> str:
    """The integer exponent written right after a number ("e23", "× 10^23",
    "x 10^-3"), as text; "0" when there is none."""
    for lead in (_E_NOTATION, _TIMES_TEN, _X_TIMES_TEN):
        if tuple(after[: len(lead)]) != lead:
            continue
        rest = list(after[len(lead) :])
        sign = rest.pop(0) if rest and rest[0] in _SIGNS else ""
        if rest and rest[0].isdigit():
            return sign + rest[0]
    return "0"


def _stated_value(tokens: list[AnswerToken]) -> Decimal | None:
    """The value a numeric final answer states: the first number after its
    last '=' or '≈' (from the start when it has none, so "v_0 = 5 m/s" states
    5, not the subscript), negative after a '-', the quotient when '/' and a
    second number follow it ("1/2" states 0.5; "m/s" is no fraction), else
    scaled by an exponent written right after it; None when it states no
    number (or divides by zero)."""
    values = [t.value for t in tokens]
    start = max((i + 1 for i, v in enumerate(values) if v in _RELATIONS), default=0)
    for i in range(start, len(tokens)):
        if not tokens[i].number:
            continue
        sign = "-" if i and values[i - 1] == "-" else ""
        if values[i + 1 : i + 2] == [_FRACTION] and i + 2 < len(tokens) and tokens[i + 2].number:
            numerator, denominator = _decimal(f"{sign}{values[i]}"), _decimal(values[i + 2])
            return numerator / denominator if numerator is not None and denominator else None
        return _decimal(f"{sign}{values[i]}e{_exponent(values[i + 1 :])}")
    return None


def _correct_option_text(draft: CheckItemDraft) -> str | None:
    letters, texts = draft.option_letters, draft.option_texts
    hits = [i for i, letter in enumerate(letters) if letter == draft.correct_option]
    if len(letters) != len(texts) or len(hits) != 1:
        return None  # the option rule reports it
    return texts[hits[0]]


def _names_the_concept(run: tuple[str, ...], concept: tuple[str, ...]) -> bool:
    """Whether a final answer is (part of) the concept name, a determiner
    aside: "The base case." names "Base Case" as surely as "base case" does,
    and would block every hint that says "the base case"."""
    if contains_run(concept, run):
        return True
    core = tuple(t for t in run if t not in _DETERMINERS)
    return bool(core) and contains_run(tuple(t for t in concept if t not in _DETERMINERS), core)


def _final_answer_reasons(draft: CheckItemDraft) -> list[str]:
    """A34: the final answer the reference concludes with, stated verbatim."""
    run = answer_run(draft.final_answer)
    if not run:
        return ["final_answer is empty"]
    reasons = []
    if len(run) > CHECK_ITEM_FINAL_ANSWER_MAX_TOKENS:
        reasons.append(
            f"final_answer has {len(run)} tokens; at most {CHECK_ITEM_FINAL_ANSWER_MAX_TOKENS}"
        )
    if not contains_run(answer_run(draft.reference_answer), run):
        reasons.append("final_answer does not occur in reference_answer")
    if contains_run(answer_run(draft.prompt), run):
        reasons.append(
            "final_answer occurs in the prompt: an answer the question prints is no secret"
        )
    if _names_the_concept(run, answer_run(draft.concept)):
        reasons.append("final_answer is (part of) the concept name: it would block every hint")
    if draft.answer_kind == _NUMERIC and _finite_float(draft.canonical_answer) is not None:
        stated = _stated_value(answer_tokens(draft.final_answer))
        if stated is None or stated != _decimal(draft.canonical_answer):
            reasons.append(
                f"final_answer states {stated if stated is not None else 'no number'}, "
                f"not canonical_answer {draft.canonical_answer!r}"
            )
    if draft.format == _MC_REASON:
        # Equal, not merely containing it: the leak check matches the WHOLE
        # final answer, so "A: <text>" would let a hint quote <text> unflagged.
        option = _correct_option_text(draft)
        if option is not None and run != answer_run(option):
            reasons.append("final_answer is not the correct option's text")
    return reasons


def validate_draft(draft: CheckItemDraft) -> list[str]:
    """Every reason `draft` is unusable; [] when it may be stored. Each reason
    names the rule it is about (format, difficulty, prompt, reference, rubric,
    wrong, leak, answer_kind, option, canonical, tolerance, stepwise,
    final_answer)."""
    reasons: list[str] = []
    if draft.format not in CHECK_ITEM_FORMATS:
        reasons.append(f"format {draft.format!r} is not one of {CHECK_ITEM_FORMATS}")
    if draft.difficulty not in CHECK_ITEM_DIFFICULTIES:
        reasons.append(f"difficulty {draft.difficulty!r} is not one of {CHECK_ITEM_DIFFICULTIES}")
    if not draft.prompt.strip():
        reasons.append("prompt is empty")
    if not draft.reference_answer.strip():
        reasons.append("reference answer is empty")
    rubric = [r for r in draft.rubric if r.strip()]
    if len(rubric) < CHECK_ITEM_MIN_RUBRIC:
        reasons.append(f"rubric has {len(rubric)} item(s); needs >= {CHECK_ITEM_MIN_RUBRIC}")
    if len(draft.wrong_keys) != len(draft.wrong_texts):
        reasons.append(
            f"wrong_keys ({len(draft.wrong_keys)}) and wrong_texts "
            f"({len(draft.wrong_texts)}) differ in length"
        )
    if len(draft.wrong_keys) < CHECK_ITEM_MIN_WRONG:
        reasons.append(f"{len(draft.wrong_keys)} wrong reason(s); needs >= {CHECK_ITEM_MIN_WRONG}")
    if len(set(draft.wrong_keys)) != len(draft.wrong_keys):
        reasons.append("duplicate wrong keys")
    if any(not k.strip() for k in draft.wrong_keys):
        reasons.append("blank wrong key")
    if draft.prompt.strip() and leak_in_prompt(draft.prompt, draft.reference_answer):
        reasons.append("leak: the reference answer appears in the prompt")
    if draft.answer_kind not in CHECK_ITEM_ANSWER_KINDS:
        reasons.append(f"answer_kind {draft.answer_kind!r} is not one of {CHECK_ITEM_ANSWER_KINDS}")
    if draft.format == _MC_REASON:
        reasons.extend(_option_reasons(draft))
    if draft.answer_kind == _NUMERIC:
        if _finite_float(draft.canonical_answer) is None:
            reasons.append(f"canonical_answer {draft.canonical_answer!r} is not a number")
        if draft.tolerance != "":
            tol = _finite_float(draft.tolerance)
            if tol is None or tol < 0:
                reasons.append(f"tolerance {draft.tolerance!r} is not a number >= 0")
    if draft.stepwise:
        steps = len(_STEP_LINE.findall(draft.reference_answer))
        if steps < CHECK_ITEM_STEPWISE_MIN_STEPS:
            reasons.append(
                f"stepwise reference has {steps} numbered step(s); "
                f"needs >= {CHECK_ITEM_STEPWISE_MIN_STEPS}"
            )
    reasons.extend(_final_answer_reasons(draft))
    return reasons


def parse_tolerance(draft: CheckItemDraft) -> float | None:
    """The stored `tolerance`: a float for a numeric item with one, else None."""
    if draft.answer_kind != _NUMERIC or draft.tolerance == "":
        return None
    return _finite_float(draft.tolerance)


def clean_chunk_ids(draft: CheckItemDraft, allowed: Iterable[str]) -> list[str]:
    """Cited ids that are in `allowed`, in cited order, deduplicated. An
    unknown citation is dropped, never fatal."""
    allowed = set(allowed)
    out: list[str] = []
    for cid in draft.chunk_ids:
        if cid in allowed and cid not in out:
            out.append(cid)
    return out


# ── passage ranking ────────────────────────────────────────────────────────


def _score(concept_name: str, text: str) -> int:
    name = normalize(concept_name)
    tokens = {t for t in _WORD.findall(name) if len(t) >= _MIN_TOKEN_LEN and t not in _STOPWORDS}
    words = set(_WORD.findall(normalize(text)))
    if tokens:
        return len(tokens & words)
    # A name with no content token of the floor length ("Pi", "UI", "This and
    # That") scores 1 when the whole name appears as a word sequence, so the
    # backfill's relevance floor never makes such a concept permanently
    # undraftable.
    phrase = _words(name)
    return int(bool(phrase) and f" {phrase} " in f" {_words(text)} ")


def rank_chunks_for_concept(
    concept_name: str, chunks, *, limit: int, min_score: int = 0
) -> list[dict]:
    """Deterministic passage ranking (no embeddings, no LLM — spec §12): the
    number of distinct casefolded name tokens (length >= _MIN_TOKEN_LEN, not a
    _STOPWORDS function word) that occur as words in the chunk, below
    `min_score` dropped, ordered by (score desc, chunk_index asc, id), the
    first `limit` returned."""
    scored = []
    for chunk in chunks:
        score = _score(concept_name, chunk.get("chunk_text") or "")
        if score < min_score:
            continue
        scored.append((-score, chunk.get("chunk_index") or 0, str(chunk.get("id") or ""), chunk))
    scored.sort(key=lambda row: row[:3])
    return [row[3] for row in scored[:limit]]


# ── selection ──────────────────────────────────────────────────────────────


def select_item(
    items: Iterable[CheckItem],
    *,
    format: str,
    difficulty: int,
    exclude_hashes: Iterable[str] = (),
) -> CheckItem | None:
    """A servable item (A34: it states a final answer) of exactly `format`
    whose hash is not excluded: the first at exactly `difficulty` (ties by
    (created_at, id)), else the nearest difficulty (lower first on ties), else
    None. Format is never substituted — each format is a different evidence
    channel (spec §3.1)."""
    excluded = set(exclude_hashes)
    candidates = [
        i
        for i in items
        if i.format == format and i.question_hash not in excluded and is_servable(i)
    ]
    if not candidates:
        return None
    return min(
        candidates,
        key=lambda i: (abs(i.difficulty - difficulty), i.difficulty, i.created_at or "", i.id),
    )


def posttest_reserve_hash(items: Iterable[CheckItem]) -> str | None:
    """The concept's post-test reserve (A23): the lowest question_hash among
    servable (A34) `free` items at CHECK_ITEM_DIFFICULTIES[1], else the lowest
    servable overall, else None. Probe, in-session checks and review never
    serve it; the post-test does, so an item with no final answer is never it."""
    items = [i for i in items if is_servable(i)]
    mid = CHECK_ITEM_DIFFICULTIES[1]
    preferred = [i.question_hash for i in items if i.format == "free" and i.difficulty == mid]
    if preferred:
        return min(preferred)
    return min((i.question_hash for i in items), default=None)

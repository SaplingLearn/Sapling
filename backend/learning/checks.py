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

An mc_reason draft states its options as objects (§13 A37): each option's text,
whether it is the correct one, and — on a distractor — the wrong key naming the
misconception that makes it tempting. It carries no letters. `repair_draft`
makes the repairs that need no guess, `validate_draft` names every remaining
fault by its rule, and `lettered_options` letters the valid options and places
the correct one at a slot keyed by a server secret, so the model can neither
drift a key off its option nor bias the answer's position, and a client that
knows the question_hash cannot compute it. `stored_rubric` appends code's own
criterion to an mc_reason rubric, so a reason that only restates the chosen
option never passes the grader.
"""

from __future__ import annotations

import hashlib
import hmac
import math
import re
import string
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
    CHECK_ITEM_MC_OPTIONS,
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
_DETERMINERS = frozenset({"the", "a", "an", "its", "their", "this", "that", "these", "those"})
# The regular English plural endings the concept-name rule reads on the
# concept's last word ("base case" / "base cases", "class" / "classes").
_PLURAL_ENDINGS = ("s", "es")
_HYPHEN = "-"
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


class OptionDraft(BaseModel):
    """One mc_reason option as the agent states it (§13 A37). No letter: code
    letters the options and places the correct one after validation."""

    text: str = Field(
        description=(
            "the option exactly as the student reads it; at most "
            f"{CHECK_ITEM_FINAL_ANSWER_MAX_TOKENS} tokens (the correct one is the final_answer)"
        )
    )
    is_correct: bool = Field(
        description="true on exactly one option, the correct answer; false on every distractor"
    )
    wrong_key: str | None = Field(
        default=None,
        description=(
            "null on the correct option; on a distractor, the one entry of this item's "
            "wrong_keys that names the misconception making it tempting (a different "
            "entry for each distractor)"
        ),
    )


class CheckItemDraft(BaseModel):
    """The agent's per-item output. Flat — str / int / bool / list[str] —
    except `options`, one list of small objects (§13 A37;
    docs/attempts/2026-05-03-orchestrator-schema-complexity.md)."""

    concept: str = Field(
        description="which of this call's concepts the item assesses, copied exactly"
    )
    format: str = Field(description="one of free | teachback | mc_reason")
    difficulty: int = Field(description="1 recall, 2 application, 3 transfer")
    prompt: str
    options: list[OptionDraft] = Field(
        default_factory=list,
        description=(
            f"mc_reason only: exactly {CHECK_ITEM_MC_OPTIONS} options, the correct one first "
            "(is_correct true, wrong_key null), then the distractors (is_correct false, each "
            "with its own wrong_key); [] for free and teachback"
        ),
    )
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
    rubric: list[str] = Field(
        default_factory=list,
        description=(
            f"every format: at least {CHECK_ITEM_MIN_RUBRIC} criteria, each one binary check a "
            "grader marks present or absent; for mc_reason they judge the student's reason"
        ),
    )
    wrong_keys: list[str] = Field(
        default_factory=list,
        description=(
            f"every format, never empty: at least {CHECK_ITEM_MIN_WRONG} snake_case misconception "
            f"id(s) — for mc_reason at least {CHECK_ITEM_MC_OPTIONS - 1}, one per distractor in "
            "the distractors' order — same length as wrong_texts"
        ),
    )
    wrong_texts: list[str] = Field(
        default_factory=list, description="wrong_texts[i] describes wrong_keys[i]"
    )
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


# An option named by its letter — "option B", "choice (C)", "Options B and D",
# "Options: A. …", "Option B's claim", "option (b)", "option d". Code letters
# the options after validation (A37), so a letter the agent wrote names
# nothing, and a reference that says "Option A is correct" would tell the
# grader the wrong option once code moved it. Only a letter code assigns
# (A–D for CHECK_ITEM_MC_OPTIONS = 4) counts, right after the word: in
# brackets in either case; bare, uppercase or b–d, standing alone or as a
# possessive ("B's"). A bare lowercase "a" is the article ("option a student
# picks") unless a ")" follows it; "optional", "option, A-level", "option
# B-tree" and "the option I prefer" do not count. A bare "(A)" with no
# "option" before it is not read: a stem names its variables that way ("the
# area of a circle (A)").
_OPTION_LETTERS = string.ascii_uppercase[:CHECK_ITEM_MC_OPTIONS]
_ALONE = r"(?![\w-]|['\u2019](?!s\b))"  # nothing word-like follows, a possessive 's aside
_LETTER_REF = re.compile(
    r"\b(?i:options?|choices?)\s*:?\s*(?:"
    rf"[(\[](?i:[{_OPTION_LETTERS}])[)\]]"  # (b), [C]
    rf"|[{_OPTION_LETTERS}][).:]?{_ALONE}"  # B, B), B., B's
    rf"|[{_OPTION_LETTERS[1:].lower()}]{_ALONE}"  # b, c, d
    rf"|[{_OPTION_LETTERS.lower()}]\){_ALONE}"  # a), b)
    ")"
)


# Closing punctuation an option's text may carry or not ("The loss value." is
# "The loss value").
_OPTION_END = ".,;:!?"


def _option_form(text: str) -> str:
    """How two option texts compare for the option_text rule: whitespace runs
    collapsed, casefolded, closing punctuation dropped — every other character
    kept, so "f'(g(x)) * g'(x)" and "f(g'(x)) * g'(x)" stay two options (the
    A34 answer tokens drop primes and brackets, which is right for a final
    answer's run and wrong here)."""
    return normalize(text).rstrip(_OPTION_END).rstrip()


def _blank(key: str | None) -> bool:
    return not (key or "").strip()


#: The A37 option rules, by the word each reason of `_option_reasons` leads with.
MC_OPTION_RULES = (
    "option_count",
    "one_correct",
    "correct_key",
    "distractor_key",
    "option_text",
    "letter",
)


def _option_reasons(draft: CheckItemDraft) -> list[str]:
    """The A37 option rules of an mc_reason draft, each reason led by its
    rule word (MC_OPTION_RULES). Options are numbered from 1 as the agent
    wrote them."""
    options = draft.options
    reasons = []
    if len(options) != CHECK_ITEM_MC_OPTIONS:
        reasons.append(
            f"option_count: {len(options)} options, but mc_reason needs exactly "
            f"{CHECK_ITEM_MC_OPTIONS}"
        )
    correct = [n for n, o in enumerate(options, start=1) if o.is_correct]
    if len(correct) != 1:
        reasons.append(f"one_correct: {len(correct)} options marked is_correct, not exactly 1")
    for n in correct:
        if not _blank(options[n - 1].wrong_key):
            reasons.append(
                f"correct_key: option {n} is marked correct and carries wrong_key "
                f"{options[n - 1].wrong_key!r} (the correct option has none)"
            )
    listed = set(draft.wrong_keys)
    keyed: dict[str, int] = {}
    for n, option in enumerate(options, start=1):
        if option.is_correct:
            continue
        if _blank(option.wrong_key):
            reasons.append(f"distractor_key: option {n} has no wrong_key")
            continue
        if option.wrong_key not in listed:
            reasons.append(
                f"distractor_key: option {n}'s wrong_key {option.wrong_key!r} is not in wrong_keys"
            )
        if option.wrong_key in keyed:
            reasons.append(
                f"distractor_key: options {keyed[option.wrong_key]} and {n} share wrong_key "
                f"{option.wrong_key!r} (each distractor names its own misconception)"
            )
        keyed.setdefault(option.wrong_key, n)
    seen: dict[str, int] = {}
    for n, option in enumerate(options, start=1):
        form = _option_form(option.text)
        if not answer_run(option.text):
            reasons.append(f"option_text: option {n} states nothing")
        elif form in seen:
            reasons.append(f"option_text: options {seen[form]} and {n} read the same")
        else:
            seen[form] = n
    for field in ("prompt", "reference_answer"):
        hit = _LETTER_REF.search(getattr(draft, field))
        if hit:
            reasons.append(
                f"letter: the {field} names an option by its letter ({hit.group(0)!r}), "
                "but code letters the options"
            )
    return reasons


# The markers agents.check_items.build_prompt puts before each passage: "[chunk
# <id>]" or "[passage]". Never course content — only an agent that copied one
# into its text writes it there. Copied markers come in runs ("[chunk a],
# [chunk b]", "(see [chunk a] and [chunk b])"), so a run goes as one: markers
# joined by a comma, semicolon, slash, "&", "and", "or" or nothing, with a
# "see"/"cf." before it, and the brackets around it when they hold nothing
# else. No quantifier precedes the first bracket or lead word, so a long
# whitespace run is scanned once per bracket (the whitespace before a run is
# trimmed by _seam, not matched).
_MARKER = r"\[(?:chunk[ \t]+[^\s\[\]]+|passage)\]"
_MARKER_RUN = rf"(?:\b(?:see|cf\.?)[ \t]+)?{_MARKER}(?:\s*(?:[,;/&]\s*|(?:and|or)\s+)?{_MARKER})*"
_CHUNK_MARKER = re.compile(rf"[(\[]\s*{_MARKER_RUN}\s*[)\]]|{_MARKER_RUN}", re.IGNORECASE)
# Punctuation that can meet across a removed run, and the marks that end a
# sentence (kept over a comma, semicolon or colon).
_SEAM = ".,;:!?"
_TEXT_FIELDS = ("prompt", "reference_answer", "final_answer")
_TEXT_LISTS = ("rubric", "wrong_texts")


def _seam(left: str, right: str) -> str:
    """`left` + `right` once a marker run between them is gone: the spaces
    before the run go with it, and where punctuation meets across the gap
    one mark stays — left's, unless only right's ends a sentence ("7;" + "."
    is "7."); at the start of the text, right's is dropped."""
    left = left.rstrip(" \t")
    body = right.lstrip()
    mark = body[: len(body) - len(body.lstrip(_SEAM))]
    if not mark:
        return left + right
    core = left.rstrip(_SEAM)
    ours = left[len(core) :]
    if not left.strip():
        return left + body[len(mark) :]
    if not ours:
        return left + body
    end = next((c for c in mark if c in _SENTENCE_END), "")
    if end and not any(c in _SENTENCE_END for c in ours):
        return core + end + body[len(mark) :]
    return left + body[len(mark) :]


def _unmarked(text: str) -> str:
    if not _CHUNK_MARKER.search(text):
        return text
    while (hit := _CHUNK_MARKER.search(text)) is not None:
        text = _seam(text[: hit.start()], text[hit.end() :])
    return text.strip()


def _remove_markers(draft: CheckItemDraft) -> list[str]:
    """Remove the passage markers from every text `draft` stores, in place;
    the names of the fields that carried one."""
    marked = []
    for name in _TEXT_FIELDS:
        clean = _unmarked(getattr(draft, name))
        if clean != getattr(draft, name):
            setattr(draft, name, clean)
            marked.append(name)
    for name in _TEXT_LISTS:
        clean = [_unmarked(t) for t in getattr(draft, name)]
        if clean != getattr(draft, name):
            setattr(draft, name, clean)
            marked.append(name)
    for option in draft.options:
        clean = _unmarked(option.text)
        if clean != option.text:
            option.text = clean
            if "options" not in marked:
                marked.append("options")
    return marked


# A reference's closing sentence names its final answer (A34): "Final answer:".
_FINAL_LABEL = re.compile(r"\bfinal\s+answer\b", re.IGNORECASE)
_SENTENCE_END = (".", "!", "?")


def _closed(reference: str, final_answer: str) -> str:
    """`reference` with A34's closing sentence, "Final answer: <final_answer>.",
    appended — the final answer verbatim, one full stop between sentences."""
    body, answer = reference.rstrip(), final_answer.strip()
    if not body.endswith(_SENTENCE_END):
        body += "."
    return f"{body} Final answer: {answer}" + ("" if answer.endswith(_SENTENCE_END) else ".")


def repair_draft(draft: CheckItemDraft) -> tuple[CheckItemDraft, list[str]]:
    """`draft` with the repairs that need no guess made (§13 A37), and one
    line per repair, led by the rule it satisfies. The input is never mutated.

    correct_key — an mc_reason draft with EXACTLY one option marked is_correct
    whose wrong_key is not null (a key, or "") gets that key cleared:
    is_correct is explicit, so which option is correct is not in doubt, and
    A34's rule that final_answer equal the correct option's text still
    cross-checks the flag.

    final_answer — an mc_reason reference that names no "Final answer" and
    does not contain the final answer gets A34's closing sentence, "Final
    answer: <final_answer>.", when exactly one option is marked is_correct and
    final_answer is that option's text: the draft states its answer twice,
    explicitly and in agreement, and only the sentence quoting it is missing.
    A reference whose closing sentence names something else is a
    contradiction, not an omission, and stays dropped. So does a reference
    that contains any distractor's text anywhere: it may be arguing for that
    option, and telling an endorsement from a rebuttal would be a guess. So
    does a free or teachback reference, whose final answer has no second
    statement to agree with (A34's containment check is what ties it to the
    reference).

    chunk_marker — a "[chunk <id>]" or "[passage]" marker the agent copied
    from its prompt into any text the item stores (prompt, reference, final
    answer, rubric, wrong texts, option texts) is removed, in every format:
    it is the prompt builder's, never course content, and the reference
    reaches the grader and the tutor's H4/H6 hint payloads. A run of markers
    goes as one, with its separators, a "see"/"cf." before it and brackets
    that held nothing else, and where punctuation meets across the gap one
    mark stays, so no "Afro-Eurasia.," or "(,)." is left behind. chunk_ids is
    untouched. Runs first, so every other rule reads the clean text.

    stepwise — a draft that claims `stepwise` while its reference has fewer
    than CHECK_ITEM_STEPWISE_MIN_STEPS numbered lines drops the claim: code
    measures the reference, and an item that is not stepwise only stops being
    an H4 sibling candidate (A17).

    Nothing else is repaired: which option is correct (none or several
    marked) is never inferred, and a distractor's missing, shared or unlisted
    key is never guessed."""
    fixed = draft.model_copy(deep=True)
    repairs: list[str] = []
    marked = _remove_markers(fixed)
    if marked:
        repairs.append(
            f"chunk_marker: the {', '.join(marked)} carried a [chunk <id>] or [passage] "
            "marker, which was removed (repaired)"
        )
    correct = [o for o in fixed.options if o.is_correct]
    mc_one = fixed.format == _MC_REASON and len(correct) == 1
    if mc_one and correct[0].wrong_key is not None:
        n = fixed.options.index(correct[0]) + 1
        key, correct[0].wrong_key = correct[0].wrong_key, None
        repairs.append(
            f"correct_key: option {n} is marked correct, so its wrong_key {key!r} "
            "was cleared (repaired)"
        )
    final = answer_run(fixed.final_answer)
    reference = answer_run(fixed.reference_answer)
    if (
        mc_one
        and final
        and final == answer_run(correct[0].text)
        and fixed.reference_answer.strip()
        and not _FINAL_LABEL.search(fixed.reference_answer)
        and not contains_run(reference, final)
        and not any(
            contains_run(reference, answer_run(o.text)) for o in fixed.options if not o.is_correct
        )
    ):
        fixed.reference_answer = _closed(fixed.reference_answer, fixed.final_answer)
        repairs.append(
            "final_answer: the reference had no closing 'Final answer:' sentence, so one "
            "quoting the option marked correct was appended (repaired)"
        )
    if fixed.stepwise:
        steps = len(_STEP_LINE.findall(fixed.reference_answer))
        if steps < CHECK_ITEM_STEPWISE_MIN_STEPS:
            fixed.stepwise = False
            repairs.append(
                f"stepwise: the reference has {steps} numbered step(s), fewer than "
                f"{CHECK_ITEM_STEPWISE_MIN_STEPS}, so the stepwise claim was dropped (repaired)"
            )
    return (fixed, repairs) if repairs else (draft, [])


#: The criterion code appends to every stored mc_reason rubric (§13 A37,
#: review): the grader checks each criterion strictly, and this one fails a
#: reason that only restates the chosen option. Without it a correct pick plus
#: "Because the answer is <option text>" passed 5 of 6 live items (the review)
#: and 21 of 28 stored items the fixer graded directly, since a correct option
#: often carries its own justification and the model's criteria can be met by
#: the pick; with it, 2 of 28, while the reference's own reason still passed 27
#: of 28. Its wording is measured: a version asking for a fact "the final
#: answer's own words do not already state" failed 9 of 12 reference reasons.
MC_REASON_CRITERION = (
    "The reason supports the choice with at least one fact, cause, mechanism or piece of "
    "evidence. A reason that only repeats or rewords the chosen answer earns no."
)


def stored_rubric(draft: CheckItemDraft) -> list[RubricItem]:
    """The rubric an item is stored with: the draft's non-blank criteria as
    r1..rn, then — on an mc_reason item — MC_REASON_CRITERION as r(n+1). It is
    not the model's, so it never counts toward CHECK_ITEM_MIN_RUBRIC."""
    rubric = [
        RubricItem(id=f"r{i}", text=text)
        for i, text in enumerate((t for t in draft.rubric if t.strip()), start=1)
    ]
    if draft.format == _MC_REASON:
        rubric.append(RubricItem(id=f"r{len(rubric) + 1}", text=MC_REASON_CRITERION))
    return rubric


def lettered_options(draft: CheckItemDraft, *, slot_key: bytes) -> tuple[list[Option], str]:
    """The stored options of a valid mc_reason draft and the correct letter
    (§13 A37): the distractors in the order the agent wrote them, the correct
    option inserted at a slot drawn from HMAC-SHA256(slot_key, question_hash)
    — uniform over the slots, stable for a prompt (a re-run upserts the same
    letters), never the agent's choice, and secret: the client is sent the
    question_hash, so a slot computed from it alone would give the answer
    away — then lettered A, B, C, … in that order. `slot_key` is the server's
    secret (the service derives it from ENCRYPTION_KEY); there is no default.
    The correct option stores no wrong_key. Raises ValueError unless exactly
    one option is marked correct (validate_draft first) or on an empty key."""
    if not isinstance(slot_key, bytes) or not slot_key:
        raise ValueError("slot_key must be the non-empty server secret (bytes)")
    correct = [o for o in draft.options if o.is_correct]
    if len(correct) != 1:
        raise ValueError(f"{len(correct)} options marked is_correct: exactly 1 must be")
    distractors = [o for o in draft.options if not o.is_correct]
    digest = hmac.new(slot_key, question_hash(draft.prompt).encode("ascii"), hashlib.sha256)
    slot = int(digest.hexdigest(), 16) % len(draft.options)
    ordered = distractors[:slot] + correct + distractors[slot:]
    options = [
        Option(letter=letter, text=o.text, wrong_key=None if o.is_correct else o.wrong_key)
        for letter, o in zip(string.ascii_uppercase, ordered)
    ]
    return options, options[slot].letter


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


# The most tokens an exponent spans after its number: "x", "10", "^", a sign
# and the digits.
_EXPONENT_SPAN = len(_X_TIMES_TEN) + 2


def _exponent(after: Sequence[str]) -> tuple[str, int]:
    """The integer exponent written right after a number ("e23", "× 10^23",
    "x 10^-3"), as text, and how many tokens of `after` it spans; ("0", 0)
    when there is none."""
    for lead in (_E_NOTATION, _TIMES_TEN, _X_TIMES_TEN):
        if tuple(after[: len(lead)]) != lead:
            continue
        rest = list(after[len(lead) : _EXPONENT_SPAN])
        sign = rest.pop(0) if rest and rest[0] in _SIGNS else ""
        if rest and rest[0].isdigit():
            return sign + rest[0], len(lead) + len(sign) + 1
    return "0", 0


def written_value(values: Sequence[str], i: int) -> tuple[Decimal | None, int]:
    """The magnitude of the number `values[i]` (answer-token values) scaled by
    an exponent written right after it ("2.5 × 10^-3" and "2.5e-3" are
    0.0025), and the index of the last token it spans (i when there is no
    exponent). Reads at most _EXPONENT_SPAN tokens, so a scan over every
    number stays linear."""
    exponent, used = _exponent(values[i + 1 : i + 1 + _EXPONENT_SPAN])
    return _decimal(f"{values[i]}e{exponent}"), i + used


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
        value, _ = written_value(values, i)
        return -value if sign and value is not None else value
    return None


def _correct_option_text(draft: CheckItemDraft) -> str | None:
    correct = [o.text for o in draft.options if o.is_correct]
    return correct[0] if len(correct) == 1 else None  # else the one_correct rule reports it


def _unhyphenated(run: tuple[str, ...]) -> tuple[str, ...]:
    """`run` with every '-' between two words dropped: "base-case" is spelled
    "base case" (between numbers or symbols a '-' is an operator and stays)."""
    return tuple(
        t
        for i, t in enumerate(run)
        if not (
            t == _HYPHEN and 0 < i < len(run) - 1 and run[i - 1].isalpha() and run[i + 1].isalpha()
        )
    )


def _number_forms(a: str, b: str) -> bool:
    """Whether one word is the other's regular plural ("case" / "cases",
    "class" / "classes"); a word shorter than _MIN_TOKEN_LEN has none ("i" /
    "is", "a" / "as")."""
    short, long = sorted((a, b), key=len)
    return (
        len(short) >= _MIN_TOKEN_LEN
        and short.isalpha()
        and long in {short + ending for ending in _PLURAL_ENDINGS}
    )


def _in_a_spelling(concept: tuple[str, ...], run: tuple[str, ...]) -> bool:
    """Whether `run` occurs in the concept name as a hint may spell it: word
    for word, except that the name's LAST word may take the other number
    ("base cases" for "Base Case"; "bases" is in no spelling of it)."""
    k, last = len(run), len(concept) - 1
    return bool(run) and any(
        all(
            c == r or (i + j == last and _number_forms(c, r))
            for j, (c, r) in enumerate(zip(concept[i : i + k], run))
        )
        for i in range(len(concept) - k + 1)
    )


def _names_the_concept(run: tuple[str, ...], concept: tuple[str, ...]) -> bool:
    """Whether a final answer is (part of) the concept name as a hint may
    spell it — a determiner aside, a hyphen between words as a space, the
    name's last word in either number: "The base case.", "Base cases" and
    "the base-case" name "Base Case" as surely as "base case" does, and each
    would block every hint that says it. An irregular plural ("matrices" for
    "Matrix") is another word to this rule."""
    run, concept = _unhyphenated(run), _unhyphenated(concept)
    if _in_a_spelling(concept, run):
        return True
    core = tuple(t for t in run if t not in _DETERMINERS)
    return _in_a_spelling(tuple(t for t in concept if t not in _DETERMINERS), core)


def _final_answer_reasons(draft: CheckItemDraft) -> list[str]:
    """A34: the final answer the reference concludes with, stated verbatim."""
    run = answer_run(draft.final_answer)
    if not run:
        return ["final_answer is empty"]
    reasons = []
    if len(run) > CHECK_ITEM_FINAL_ANSWER_MAX_TOKENS:
        reasons.append(
            f"final_answer has {len(run)} tokens, at most {CHECK_ITEM_FINAL_ANSWER_MAX_TOKENS}"
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
    wrong, leak, answer_kind, canonical, tolerance, stepwise, final_answer; an
    mc_reason draft's A37 option rules lead with option_count, one_correct,
    correct_key, distractor_key, option_text or letter). Run repair_draft
    first to store what it can repair."""
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
        reasons.append(f"rubric has {len(rubric)} item(s), needs >= {CHECK_ITEM_MIN_RUBRIC}")
    if len(draft.wrong_keys) != len(draft.wrong_texts):
        reasons.append(
            f"wrong_keys ({len(draft.wrong_keys)}) and wrong_texts "
            f"({len(draft.wrong_texts)}) differ in length"
        )
    if len(draft.wrong_keys) < CHECK_ITEM_MIN_WRONG:
        reasons.append(f"{len(draft.wrong_keys)} wrong reason(s), needs >= {CHECK_ITEM_MIN_WRONG}")
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
                f"stepwise reference has {steps} numbered step(s), "
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

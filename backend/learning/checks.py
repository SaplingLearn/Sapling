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
whether it is the correct one, and — on a distractor — its own misconception,
a key and a sentence naming the mistake that makes it tempting. It carries no
letters and no wrong-reason lists of its own: `common_wrong` takes the item's
common wrong reasons from its distractors, so there is nothing for a key to
cross-reference. `repair_draft` makes the repairs that need no guess,
`validate_draft` names every remaining fault by its rule, and
`lettered_options` letters the valid options and places the correct one at a
slot keyed by a server secret, so the model can neither drift a misconception
off its option nor bias the answer's position, and a client that knows the
question_hash cannot compute it. `stored_rubric` appends code's own criterion
to an mc_reason rubric, so a reason that only restates the chosen option never
passes the grader.
"""

from __future__ import annotations

import hashlib
import hmac
import math
import re
import string
import unicodedata
from collections.abc import Iterable, Mapping, Sequence
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
    POSTTEST_ITEM_MATCHES,
    POSTTEST_RESERVE_FORMATS,
    POSTTEST_RESERVE_MIN_LEFT,
    POSTTEST_SKIP_REASONS,
    PRETEST_FORM_MATCHES,
    SURFACE_FAMILIARITY_UNKNOWN,
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
# concept's last word ("base case" / "base cases", "class" / "classes"), and
# a consonant + "y" that takes "-ies" ("fallacy" / "fallacies": the A37 third
# review's live check stored "Logical fallacy" for "Logical Fallacies").
_PLURAL_ENDINGS = ("s", "es")
_Y, _IES = "y", "ies"
_VOWELS = frozenset("aeiou")
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
    # A113: learning.item_lint's flags ([] = clean); None on a row stored
    # before the linter ran (scripts/backfill_check_item_lint.py fills it).
    lint_flags: list[str] | None = None


class OptionDraft(BaseModel):
    """One mc_reason option as the agent states it (§13 A37). No letter: code
    letters the options and places the correct one after validation. A
    distractor carries its own misconception as two flat scalars (a nested
    {key, text} model would be an optional nested model on the correct option
    and take the output past the #153 budget of 20 properties)."""

    text: str = Field(
        description=(
            "the option exactly as the student reads it; at most "
            f"{CHECK_ITEM_FINAL_ANSWER_MAX_TOKENS} tokens (the correct one is the final_answer); "
            "as long and as detailed as the other options (the correct one is never the "
            "longest) and never its own reason (the answer alone, no 'because' or '; <why>' "
            "clause)"
        )
    )
    is_correct: bool = Field(
        description="true on exactly one option, the correct answer; false on every distractor"
    )
    misconception_key: str | None = Field(
        default=None,
        description=(
            "null on the correct option; on a distractor, a short snake_case id of the "
            "misconception that makes it tempting, different on each distractor (reuse the "
            "same id across items for the same misconception)"
        ),
    )
    misconception_text: str | None = Field(
        default=None,
        description=(
            "null on the correct option; on a distractor, one sentence describing that "
            "misconception (each distractor states a different one)"
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
            "(is_correct true, both misconception fields null), then the distractors "
            "(is_correct false, each with its own misconception_key and misconception_text); "
            "[] for free and teachback"
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
            f"free and teachback, never empty: at least {CHECK_ITEM_MIN_WRONG} snake_case "
            "misconception id(s), same length as wrong_texts; [] for mc_reason (each distractor "
            "states its own misconception)"
        ),
    )
    wrong_texts: list[str] = Field(
        default_factory=list,
        description="wrong_texts[i] describes wrong_keys[i]; [] for mc_reason",
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


def states_final_answer(item) -> bool:
    """A34: whether the item states a final answer — what a leak check needs
    (a legacy row's is None). The served-text scan reads every posed item that
    states one, a held item included (learning/served_scan.py)."""
    return bool(answer_run(getattr(item, "final_answer", None)))


# ── key holds (A124) ───────────────────────────────────────────────────────
#
# An item whose key nobody has confirmed is HELD — never served, its key never
# released — while one of these codes is in its lint_flags and
# canonical_verified is false. The independent solve sets the first two
# (learning/item_keys.py), a human audit verdict the last two; an admin's
# approval (the A22 instructor confirmation) or an audit verdict "correct"
# sets canonical_verified, which lifts the hold. Defined here, beside
# is_servable, because the hold is part of what may be served.

KEY_DISPUTED = "key_disputed"  # an independent solve gave a different answer
KEY_UNSOLVED = "key_unsolved"  # an independent solve found the passages do not settle one
KEY_AUDIT_WRONG = "key_audit_wrong"  # a human audit verdict: the key is wrong
KEY_AUDIT_AMBIGUOUS = "key_audit_ambiguous"  # a human audit verdict: more than one answer fits
#: Every key-hold code, in the order they are stored (after the A113 and A119 codes).
KEY_HOLD_FLAGS = (KEY_DISPUTED, KEY_UNSOLVED, KEY_AUDIT_WRONG, KEY_AUDIT_AMBIGUOUS)


def key_held_flags(flags, canonical_verified) -> bool:
    """A124: key-held — a key-hold code among `flags` and the key not confirmed."""
    return not canonical_verified and any(f in KEY_HOLD_FLAGS for f in flags or ())


# ── provenance (A128) ──────────────────────────────────────────────────────
#
# An item drafted from its document's extracted text because the document's
# INDEXING FAILED (an embeddings outage, an exhausted re-drive) cites no source
# chunk: the H2 rung and the feedback turn have no passage to show, and the
# item's provenance is the document, not a passage. It is stored and served
# like any other (no new item state), but marked, so the A113 review queue
# lists it and every selector prefers an item that has its sources. A document
# whose indexing was SKIPPED by design (the #439 seam: function mode, no key)
# drafts unmarked: that is a configured mode, not a failure.

UNSOURCED = "unsourced"  # drafted from extracted text: its document's indexing failed
#: Every provenance code, in the order they are stored (after the A124 holds).
PROVENANCE_FLAGS = (UNSOURCED,)


def unsourced(item) -> bool:
    """A128: the item was drafted from extracted text after a failed index."""
    return UNSOURCED in (getattr(item, "lint_flags", None) or ())


def key_held(item) -> bool:
    """`key_held_flags` over a stored item (or anything with its lint_flags and
    canonical_verified)."""
    return key_held_flags(getattr(item, "lint_flags", None), getattr(item, "canonical_verified", False))


# ── staff holds (A123, on the same hold) ───────────────────────────────────
#
# Two more hold codes, both the staff's. REPORTS_THRESHOLD: enough students
# reported the item (ITEM_REPORT_QUARANTINE_MIN_REPORTERS) and it is
# quarantined until staff decide (check_item_reviews status 'quarantined').
# STAFF_RETIRED: staff retired it, and its rows go once its evidence is voided
# (status 'retired'). A confirmed key lifts neither — a report can be about
# more than the key — only a staff decision does. The database derives both
# from check_item_reviews (check_item_hold_flags, applied by the report and
# decision functions in the decision's own transaction and by a trigger on
# every later write of the row; migration 20261108072715), so no write path
# here can drop or forge one.

REPORTS_THRESHOLD = "reports_threshold"
STAFF_RETIRED = "staff_retired"
#: The staff-hold codes, in the order they are stored (after KEY_HOLD_FLAGS).
STAFF_HOLD_FLAGS = (REPORTS_THRESHOLD, STAFF_RETIRED)
#: Every hold code, key holds (A124) then staff holds (A123).
HOLD_FLAGS = (*KEY_HOLD_FLAGS, *STAFF_HOLD_FLAGS)


def held_flags(flags, canonical_verified) -> bool:
    """Held — served to no student, its key never released: a staff hold
    (A123) whatever the key's status, or a key hold on a key nobody confirmed
    (A124, `key_held_flags`). The one hold every student read applies."""
    return any(f in STAFF_HOLD_FLAGS for f in flags or ()) or key_held_flags(flags, canonical_verified)


def held(item) -> bool:
    """`held_flags` over a stored item (or anything with its lint_flags and
    canonical_verified)."""
    return held_flags(getattr(item, "lint_flags", None), getattr(item, "canonical_verified", False))


def is_servable(item) -> bool:
    """A34: only an item that states a final answer can be leak-checked, so
    only such an item is ever selected (fail closed; a legacy row is None).
    A124: and never a held one (a key nobody has confirmed after a dispute;
    A123: an item its reporters quarantined or staff retired)."""
    return states_final_answer(item) and not held(item)


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


def is_finite_number(text) -> bool:
    """Whether `text` reads as one finite number — validate_draft's own
    reading of a numeric canonical_answer (spec §13 A140: the varied drafter
    states the canonical value and code reads the answer kind from it)."""
    return _finite_float(text) is not None


def numbered_steps(reference: str | None) -> int:
    """How many numbered step lines ('1.' or '2)' at a line start) a
    reference holds — the count the `stepwise` rules read (A17/A22; spec §13
    A140: the varied drafter numbers its steps and code reads them)."""
    return len(_STEP_LINE.findall(reference or ""))


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


# The model's own working, written into an mc_reason reference instead of a
# model answer (third review of A37): "Let's assume 'Appeal to Fear' is an
# option.", "I must generate options." — the planning "let's"/"let me", or
# the pronoun "I" (at the start of a sentence or clause, so "DNA polymerase I
# can" and "World War I will" are not it) with a verb of planning or doubt.
# The reference is the grader's gold standard and reaches the H4/H6 hint
# payloads, so such a draft is dropped. Measured on the 877 references the
# A37 runs recorded: 5 of 763 mc_reason references match, every one of them
# deliberation, and 0 of 114 free or teachback ones. "Let us write …" and
# "Let x be …" are a derivation's idiom and do not count. The words the rule
# reads (the named group: "let's", "I will") are not working when they lie
# inside a verbatim quote of the final answer, of an option's text or of a
# line the stem puts in quote marks: A37's closing "Final answer: I will visit
# Paris." quotes a language item's answer, and "I think, therefore I am" is a
# quotation (`_working`). A quote is compared with ' and ’ as one character
# and without the quote marks that wrap it, as A34's final-answer check reads
# the closing sentence.
_DELIBERATION = re.compile(
    r"\b(?P<let>(?i:let['’]s|let\s+me))\b"
    r"|(?:^|[.!?:;,]\s+|\b(?i:so|and|but|then|now|here|first|next)\s+)"
    r"(?P<i>I(?:['’](?:ll|m\s+going)|\s+(?:will|must|need|think|should|have\s+to)))\b"
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


# Curly quote marks and apostrophes, folded to straight ones one character
# for one, so a folded text keeps every offset of the original.
_QUOTE_FOLD = str.maketrans("\u2018\u2019\u201c\u201d", "''\"\"")
_QUOTE_MARKS = "\"'"
# A line the stem puts in quote marks (on folded text). A single quote mark
# opens only where no letter precedes it and closes only where none follows,
# so a possessive or a contraction ("Descartes' view", "isn't") opens none.
_STEM_QUOTE = re.compile(r'"([^"]+)"|(?<!\w)\'(.+?)\'(?!\w)')


def _stem_quotes(prompt: str | None) -> list[str]:
    """The lines `prompt` puts in quote marks."""
    return [a or b for a, b in _STEM_QUOTE.findall((prompt or "").translate(_QUOTE_FOLD))]


def _quoted_spans(reference: str, texts: Iterable[str]) -> list[tuple[int, int]]:
    """Where `reference` quotes one of `texts` verbatim: whole words, case
    and whitespace runs aside, ' and ’ (and " and “ ”) as one character, the
    text's wrapping quote marks and closing punctuation dropped."""
    folded = reference.translate(_QUOTE_FOLD)
    spans: list[tuple[int, int]] = []
    for text in texts:
        bare = (text or "").translate(_QUOTE_FOLD).strip()
        words = (
            bare.lstrip(_QUOTE_MARKS).rstrip(_QUOTE_MARKS + _OPTION_END + string.whitespace).split()
        )
        if not words:
            continue
        quote = r"(?<!\w)" + r"\s+".join(map(re.escape, words)) + r"(?!\w)"
        spans.extend(m.span() for m in re.finditer(quote, folded, re.IGNORECASE))
    return spans


def _working(draft: CheckItemDraft) -> re.Match | None:
    """The first `_DELIBERATION` match in an mc_reason reference whose words
    do not lie wholly inside a quote of the final answer, an option's text or
    a line the stem puts in quote marks. Only a quote that holds the whole
    match hides it, so an option "I" never hides "So I think", and working
    beside a quote is still found."""
    reference = draft.reference_answer
    quoted = _quoted_spans(
        reference,
        [
            draft.final_answer,
            *(o.text for o in draft.options or ()),
            *_stem_quotes(draft.prompt),
        ],
    )
    for match in _DELIBERATION.finditer(reference):
        start, end = match.span("let") if match.group("let") else match.span("i")
        if not any(q_start <= start and end <= q_end for q_start, q_end in quoted):
            return match
    return None


def _blank(key: str | None) -> bool:
    return not (key or "").strip()


def _shown(value: str) -> str:
    """`value` quoted for a reason or a repair line. create_items joins those
    with "; ", so a model-written key holding one shows it as ", " instead."""
    return repr(value.replace("; ", ", "))


# ── mc_reason misconceptions (A37) ─────────────────────────────────────────
#
# Each distractor states its own misconception, and the item's common wrong
# reasons are read off the distractors (common_wrong), so the one thing left
# to check is that the distractors state DIFFERENT misconceptions under
# DIFFERENT keys. A key is only the misconception's id: when two distractors
# stating different misconceptions share one, or a distractor that states one
# gives no key, code keys it from its own text (misconception_slug) — no
# guess. Two distractors stating the same misconception are not two mistakes,
# and no key makes them so: that draft is dropped. Keys are compared and
# stored in one form, snake_case (wrong_key_form), in every format.

_SLUG_WORD = re.compile(r"[a-z0-9]+")
_APOSTROPHES = str.maketrans("", "", "'\u2019")  # "doesn't" is one word
# How many content words a derived key keeps, and how many hex digits of the
# text's digest tell two derived keys apart. Key-format literals, not loop
# tuning knobs, so they do not live in learning/params.py.
_SLUG_MAX_WORDS = 6
_SLUG_DIGEST_LEN = 8
_SLUG_FALLBACK = "misconception"
# The negations a derived key keeps although _STOPWORDS lists them: without
# its "not", "Thinks recursion does not need a base case." was keyed
# thinks_recursion_need_a_base_case, the opposite mistake (review of A37
# round 4). The "-n't" stems stand for a contraction whose apostrophe is not
# one _APOSTROPHES drops ("doesn`t").
_NEGATIONS = frozenset(
    """
    ain aren cannot couldn didn doesn don hadn hasn haven isn mightn mustn needn
    neither never none nor not nothing shan shouldn wasn weren without won wouldn
    """.split()
)
_SLUG_STOPWORDS = _STOPWORDS - _NEGATIONS
# What a model writes in misconception_text for "none" (compared as option
# texts are). Stored, it read as a common wrong reason: "COMMON WRONG REASON
# k1: N/A" in the grader's prompt (review of A37 round 4).
_NO_MISCONCEPTION = frozenset(
    {"n/a", "na", "none", "null", "nil", "nothing", "tbd", "todo", "unknown", "not applicable"}
)


def _states_misconception(text: str | None) -> bool:
    """Whether a distractor's misconception_text states a mistake at all: a
    letter or digit in any script, and not a placeholder (_NO_MISCONCEPTION)."""
    return any(ch.isalnum() for ch in text or "") and _option_form(text) not in _NO_MISCONCEPTION


def _form_digest(text: str) -> str:
    return _sha256(_option_form(text))[:_SLUG_DIGEST_LEN]


def _ascii_words(text: str) -> list[str]:
    """`text`'s Latin words and numbers: apostrophes dropped, accents folded
    to ASCII, casefolded."""
    folded = unicodedata.normalize("NFKD", text.translate(_APOSTROPHES))
    return _SLUG_WORD.findall(folded.encode("ascii", "ignore").decode("ascii").casefold())


def wrong_key_form(key: str | None) -> str:
    """The form a wrong-reason key is compared and stored in, in every format:
    snake_case — apostrophes dropped, accents folded to ASCII, casefolded, and
    every run of other characters one "_" ("Confuses-Ethos " ->
    "confuses_ethos"); "" for a key with no Latin letter or digit. A key is
    only an id, so writing it this way guesses nothing (review of A37 round
    4: "Foo", "foo" and "foo " had passed as three keys, and 33 of 276 live
    distractor keys were stored in kebab or mixed case beside code's
    snake_case ones)."""
    return "_".join(_ascii_words(key or ""))


def misconception_slug(text: str) -> str:
    """A snake_case key for a misconception, from its own text: its first
    _SLUG_MAX_WORDS words that are not English function words (_STOPWORDS,
    except the _NEGATIONS, which a key keeps so that it never names the
    opposite mistake), accents folded to ASCII, apostrophes dropped;
    "misconception_<digest>" for a text with no Latin letter or digit.
    Deterministic."""
    words = _ascii_words(text)
    content = [w for w in words if w not in _SLUG_STOPWORDS] or words
    if not content:
        return f"{_SLUG_FALLBACK}_{_form_digest(text)}"
    return "_".join(content[:_SLUG_MAX_WORDS])


def common_wrong(draft: CheckItemDraft) -> list[WrongReason]:
    """The common wrong reasons an item is stored with (common_wrong_json):
    for mc_reason, each distractor's misconception in the order the agent
    wrote the distractors — the draft's own wrong_keys / wrong_texts are not
    read — and for free and teachback, wrong_keys paired with wrong_texts.
    For a draft validate_draft passed."""
    if draft.format == _MC_REASON:
        return [
            WrongReason(key=o.misconception_key or "", text=o.misconception_text or "")
            for o in draft.options
            if not o.is_correct
        ]
    return [WrongReason(key=k, text=t) for k, t in zip(draft.wrong_keys, draft.wrong_texts)]


#: The A37 option rules, by the word each reason of `_option_reasons` leads with.
MC_OPTION_RULES = (
    "option_count",
    "one_correct",
    "correct_misconception",
    "misconception_key",
    "misconception_text",
    "option_text",
    "letter",
)


def _misconception_reasons(options: list[OptionDraft]) -> list[str]:
    """correct_misconception, misconception_key and misconception_text:
    the correct option states none; every distractor states one (a text
    with no letter or digit, or a placeholder such as "N/A", states none),
    under a snake_case key of its own (keys compared in wrong_key_form, so
    "Foo" and "foo " are one key), and no two distractors state the same one
    (compared as option texts are: whitespace, case and closing punctuation
    aside)."""
    reasons = []
    keyed: dict[str, int] = {}
    stated: dict[str, int] = {}
    for n, option in enumerate(options, start=1):
        key, said = option.misconception_key, option.misconception_text
        if option.is_correct:
            if not (_blank(key) and _blank(said)):
                reasons.append(
                    f"correct_misconception: option {n} is marked correct and carries a "
                    "misconception (the correct option has none)"
                )
            continue
        form = wrong_key_form(key)
        if _blank(key):
            reasons.append(f"misconception_key: option {n} has no misconception_key")
        elif not form:
            reasons.append(
                f"misconception_key: option {n}'s key {_shown(key)} has no Latin letter or digit"
            )
        elif form in keyed:
            reasons.append(
                f"misconception_key: options {keyed[form]} and {n} share misconception_key "
                f"{_shown(form)} (each distractor has its own)"
            )
        else:
            keyed[form] = n
            if key != form:
                reasons.append(
                    f"misconception_key: option {n}'s key {_shown(key)} is not snake_case "
                    f"({_shown(form)})"
                )
        if _blank(said):
            reasons.append(f"misconception_text: option {n} has no misconception_text")
            continue
        if not _states_misconception(said):
            reasons.append(
                f"misconception_text: option {n} states no misconception ({_shown(said)})"
            )
            continue
        form = _option_form(said)
        if form in stated:
            reasons.append(
                f"misconception_text: options {stated[form]} and {n} state the same misconception"
            )
        else:
            stated[form] = n
    return reasons


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
    reasons.extend(_misconception_reasons(options))
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
# into its text writes it there, alone or as one bracket listing several ids
# ("[chunk a, chunk b]", "[chunks a and b]"; the live check of the A37 review
# round 2 stored 8 such texts). Copied markers come in runs ("[chunk a],
# [chunk b]", "(see [chunk a] and [chunk b])"), so a run goes as one: markers
# joined by a comma, semicolon, slash, "&", "and", "or" or nothing, with a
# "see"/"cf." before it, and the brackets around it when they hold nothing
# else. No quantifier precedes the first bracket or lead word, so a long
# whitespace run is scanned once per bracket (the whitespace before a run is
# trimmed by _seam, not matched); inside a bracket, ids are parted by a
# separator, never by whitespace alone, so "chunk" as an id or as a prefix is
# decided at once. An id holds no separator character and is taken whole
# (possessive: it never gives back the "and" of "x.and.y"), so where one id
# ends is decided once — when an id could hold "/" or "&", each one after an
# unclosed "[chunk " was read both ways, and 27 slashes took 29 s (third
# review of A37). _unmarked resumes each search near the gap (_resume_at).
_MARKER_ID = r"[^\s\[\],;/&]++"
_MARKER_ID_SEP = r"[ \t]*(?:[,;/&]|and\b|or\b)[ \t]*"
_MARKER = (
    rf"\[(?:chunks?[ \t]+{_MARKER_ID}(?:{_MARKER_ID_SEP}(?:chunks?[ \t]+)?{_MARKER_ID})*"
    r"|passage)\]"
)
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


_LEAD_WORDS = ("see", "cf.", "cf")


def _resume_at(text: str, pos: int) -> int:
    """Where the next marker search starts once a run ending at `pos` is
    gone: before the whitespace, the "see"/"cf." and the bracket that
    `text[:pos]` ends with, since each can now open a run with the text after
    the gap ("([chunk a] cf. [chunk b])" -> "(cf. [chunk b])" is one bracket
    that holds nothing else). No run started any earlier, so the removals of
    one text read it about once, not once each (8,000 markers took 2 s when
    each removal searched from the start). A marker that removing another
    would complete inside an unclosed bracket ("[chunk x[chunk a]]") is not
    read: the text never held it."""

    def before_space(i: int) -> int:
        while i and text[i - 1].isspace():
            i -= 1
        return i

    pos = before_space(pos)
    for word in _LEAD_WORDS:
        start = pos - len(word)
        if start >= 0 and text[start:pos].casefold() == word:
            if not start or not text[start - 1].isalnum():
                pos = before_space(start)
            break
    return pos - 1 if pos and text[pos - 1] in "([" else pos


def _unmarked(text: str) -> str:
    if not _CHUNK_MARKER.search(text):
        return text
    pos = 0
    while (hit := _CHUNK_MARKER.search(text, pos)) is not None:
        left = text[: hit.start()]
        text = _seam(left, text[hit.end() :])
        # _seam keeps `left` up to its trailing spaces and marks.
        pos = _resume_at(text, len(left.rstrip(" \t").rstrip(_SEAM)))
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
        for name in ("text", "misconception_text"):
            value = getattr(option, name)
            clean = _unmarked(value) if value is not None else None
            if clean != value:
                setattr(option, name, clean)
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


def _keys_from_texts(keys: list[str | None], texts: list[str | None]) -> dict[int, str]:
    """The key-from-text repair of repair_draft over one list of wrong
    reasons — an mc_reason draft's distractors, or a free or teachback
    draft's wrong_keys paired with wrong_texts: index -> the key derived from
    that reason's own text (misconception_slug; with the text's digest
    appended when another reason already holds it), for each key whose
    wrong_key_form is blank (no key, or none with a Latin letter or digit) or
    shared with another reason's key. {} unless every text states a
    misconception and no two state the same one: each key is then only the
    id of a stated text, so deriving it guesses nothing and keeps every key
    distinct."""
    if not all(_states_misconception(t) for t in texts):
        return {}
    said = [_option_form(t) for t in texts]
    if len(set(said)) != len(said):
        return {}
    held = [wrong_key_form(k) for k in keys]
    taken = {form for form in held if form and held.count(form) == 1}
    derived: dict[int, str] = {}
    for i, (form, text) in enumerate(zip(held, texts)):
        if form and held.count(form) == 1:
            continue
        slug = misconception_slug(text)
        key = next((k for k in (slug, f"{slug}_{_form_digest(text)}") if k not in taken), None)
        if key is None:  # a digest collision: left for validation to drop
            continue
        taken.add(key)
        derived[i] = key
    return derived


def _had(key: str | None) -> str:
    """What a reason re-keyed by _keys_from_texts had, for its repair line."""
    form = wrong_key_form(key)
    if form:
        return f"the shared key {_shown(form)}"
    if _blank(key):
        return "no key"
    return f"the key {_shown(key)}, which has no Latin letter or digit"


def _rekey_misconceptions(options: list[OptionDraft]) -> list[str]:
    """The misconception_key repair of repair_draft, in place on `options`
    (exactly one of them marked correct); one line per distractor keyed."""
    numbered = [(n, o) for n, o in enumerate(options, start=1) if not o.is_correct]
    derived = _keys_from_texts(
        [o.misconception_key for _, o in numbered], [o.misconception_text for _, o in numbered]
    )
    lines = []
    for i, key in derived.items():
        n, option = numbered[i]
        was = _had(option.misconception_key)
        option.misconception_key = key
        lines.append(
            f"misconception_key: option {n} had {was}, so it was keyed {_shown(key)} from its "
            "own misconception_text (repaired)"
        )
    return lines


def _repair_wrong_keys(draft: CheckItemDraft) -> list[str]:
    """The wrong_keys repair of repair_draft for a free or teachback draft,
    in place on `draft`; one line per key rewritten. As for mc_reason
    distractors: a key with a form of its own is written in that form, and
    one whose form is blank or shared with another key is keyed from its own
    wrong text (_keys_from_texts) when the two lists are paired."""
    keys, texts = draft.wrong_keys, draft.wrong_texts
    forms = [wrong_key_form(k) for k in keys]
    lines = []
    for i, (key, form) in enumerate(zip(keys, forms)):
        if form and form != key and forms.count(form) == 1:
            keys[i] = form
            lines.append(
                f"wrong_keys: key {_shown(key)} was written in snake_case as {_shown(form)} "
                "(repaired)"
            )
    if len(keys) != len(texts):
        return lines
    for i, key in _keys_from_texts(keys, texts).items():
        was = _had(keys[i])
        keys[i] = key
        lines.append(
            f"wrong_keys: wrong reason {i + 1} had {was}, so it was keyed {_shown(key)} from its "
            "own wrong text (repaired)"
        )
    return lines


def _snake_case_keys(options: list[OptionDraft]) -> list[str]:
    """The distractor half of the key-form repair of repair_draft, in place on
    `options`; one line per key rewritten. A key with no Latin letter or digit,
    or one whose form another distractor's key shares, is left for the
    misconception_key repair (_keys_from_texts), which keys it from its own
    misconception_text."""
    forms = [wrong_key_form(o.misconception_key) for o in options if not o.is_correct]
    lines = []
    for n, option in enumerate(options, start=1):
        key = option.misconception_key
        form = wrong_key_form(key)
        if option.is_correct or not form or form == key or forms.count(form) > 1:
            continue
        option.misconception_key = form
        lines.append(
            f"misconception_key: option {n}'s key {_shown(key)} was written in snake_case as "
            f"{_shown(form)} (repaired)"
        )
    return lines


def repair_draft(draft: CheckItemDraft) -> tuple[CheckItemDraft, list[str]]:
    """`draft` with the repairs that need no guess made (§13 A37), and one
    line per repair, led by the rule it satisfies. The input is never mutated.

    correct_misconception — an mc_reason draft with EXACTLY one option marked
    is_correct whose misconception_key or misconception_text is not null (a
    value, or "") gets both cleared: is_correct is explicit, so which option
    is correct is not in doubt, and A34's rule that final_answer equal the
    correct option's text still cross-checks the flag.

    misconception_key / wrong_keys — a key is only an id, so a key with a
    Latin letter or digit is written in its snake_case form (wrong_key_form):
    each distractor's key in an mc_reason draft with exactly one option marked
    is_correct, and each wrong key of a free or teachback draft, unless
    another's key has the same form (a shared key, below). Then, in an
    mc_reason draft with exactly one option marked is_correct where every
    distractor states a misconception_text and no two state the same one, or
    in a free or teachback draft whose wrong_keys and wrong_texts are paired
    where every wrong text states a misconception and no two state the same
    one, a key that is blank in that form (none, or none with a Latin letter
    or digit: "误解") or shared with another is keyed from its own text
    (misconception_slug; a key another already holds gets the text's digest
    appended; _keys_from_texts). Each wrong reason is stated, so its key is
    only an id: re-keying guesses nothing, and every key stays distinct. A
    draft where two reasons state one misconception, or one states none, is
    left as it is and dropped.

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
    marked) is never inferred, a distractor's missing misconception is never
    invented, and two distractors stating one misconception are never told
    apart."""
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
    if mc_one and (
        correct[0].misconception_key is not None or correct[0].misconception_text is not None
    ):
        n = fixed.options.index(correct[0]) + 1
        correct[0].misconception_key = correct[0].misconception_text = None
        repairs.append(
            f"correct_misconception: option {n} is marked correct, so its misconception "
            "was cleared (repaired)"
        )
    if mc_one:
        repairs.extend(_snake_case_keys(fixed.options))
        repairs.extend(_rekey_misconceptions(fixed.options))
    if fixed.format != _MC_REASON:
        repairs.extend(_repair_wrong_keys(fixed))
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
    return rubric_entries(draft.rubric, draft.format)


def rubric_entries(criteria: Iterable[str], format: str) -> list[RubricItem]:
    """`stored_rubric` over content criteria and a format: the non-blank
    criteria as r1..rn, then MC_REASON_CRITERION on an mc_reason item. The
    A119 alignment rewrites a stored item's rubric with it, so a trimmed
    rubric is numbered and closed exactly as a freshly stored one."""
    rubric = [
        RubricItem(id=f"r{i}", text=text)
        for i, text in enumerate((t for t in criteria if t.strip()), start=1)
    ]
    if format == _MC_REASON:
        rubric.append(RubricItem(id=f"r{len(rubric) + 1}", text=MC_REASON_CRITERION))
    return rubric


def content_criteria(item) -> list[str]:
    """A stored item's (decrypted CheckItem's) own criteria: its rubric texts
    without the system-appended MC_REASON_CRITERION of an mc_reason item —
    what the A119 alignment check judges."""
    return [
        r.text
        for r in getattr(item, "rubric", None) or []
        if not (getattr(item, "format", None) == _MC_REASON and r.text == MC_REASON_CRITERION)
    ]


def lettered_options(draft: CheckItemDraft, *, slot_key: bytes) -> tuple[list[Option], str]:
    """The stored options of a valid mc_reason draft and the correct letter
    (§13 A37): the distractors in the order the agent wrote them, the correct
    option inserted at a slot drawn from HMAC-SHA256(slot_key, question_hash)
    — uniform over the slots, stable for a prompt (a re-run upserts the same
    letters), never the agent's choice, and secret: the client is sent the
    question_hash, so a slot computed from it alone would give the answer
    away — then lettered A, B, C, … in that order. `slot_key` is the server's
    secret (the service derives it from ENCRYPTION_KEY); there is no default.
    The correct option stores no wrong_key; a distractor stores its
    misconception_key, the key common_wrong stores its misconception under.
    Raises ValueError unless exactly one option is marked correct
    (validate_draft first) or on an empty key."""
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
        Option(letter=letter, text=o.text, wrong_key=None if o.is_correct else o.misconception_key)
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


def stated_value(text: str | None) -> Decimal | None:
    """The value a numeric answer states, read by the A34 final-answer rule
    (`_stated_value`): "v = 5 m/s" states 5, "1/2" 0.5, "2.5 × 10^-3" 0.0025;
    None when it states no number. The A124 key check reads the independent
    solve's numeric answer with it."""
    return _stated_value(answer_tokens(text))


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
    "class" / "classes", "fallacy" / "fallacies" after a consonant, never
    "relay" / "relaies"); a word shorter than _MIN_TOKEN_LEN has none ("i" /
    "is", "a" / "as")."""
    short, long = sorted((a, b), key=len)
    if len(short) < _MIN_TOKEN_LEN or not short.isalpha():
        return False
    forms = {short + ending for ending in _PLURAL_ENDINGS}
    if short.endswith(_Y) and short[-2] not in _VOWELS:
        forms.add(short[: -len(_Y)] + _IES)
    return long in forms


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


def _wrong_list_reasons(draft: CheckItemDraft) -> list[str]:
    """A free or teachback draft's paired wrong_keys / wrong_texts (A22),
    its keys compared and stored in wrong_key_form: a key that is blank, or
    has no Latin letter or digit, is named as such, and two keys of one form
    are a duplicate (repair_draft keys either from its own wrong text). Each
    wrong text states a misconception, as a distractor's misconception_text
    does: one with no letter or digit, or a placeholder such as "N/A", states
    none (_states_misconception), and stored it would reach the grader as a
    common wrong reason."""
    reasons = []
    for i, text in enumerate(draft.wrong_texts, start=1):
        if not _states_misconception(text):
            reasons.append(
                f"wrong_texts: wrong reason {i} states no misconception ({_shown(text)})"
            )
    if len(draft.wrong_keys) != len(draft.wrong_texts):
        reasons.append(
            f"wrong_keys ({len(draft.wrong_keys)}) and wrong_texts "
            f"({len(draft.wrong_texts)}) differ in length"
        )
    if len(draft.wrong_keys) < CHECK_ITEM_MIN_WRONG:
        reasons.append(f"{len(draft.wrong_keys)} wrong reason(s), needs >= {CHECK_ITEM_MIN_WRONG}")
    forms = [wrong_key_form(k) for k in draft.wrong_keys]
    named = [form for form in forms if form]
    if len(set(named)) != len(named):
        reasons.append("duplicate wrong keys")
    if any(_blank(k) for k in draft.wrong_keys):
        reasons.append("blank wrong key")
    for key, form in zip(draft.wrong_keys, forms):
        if not form and not _blank(key):
            reasons.append(f"wrong_keys: key {_shown(key)} has no Latin letter or digit")
        elif form and key != form:
            reasons.append(f"wrong_keys: key {_shown(key)} is not snake_case ({_shown(form)})")
    return reasons


def validate_draft(draft: CheckItemDraft) -> list[str]:
    """Every reason `draft` is unusable; [] when it may be stored. Each reason
    names the rule it is about (format, difficulty, prompt, reference, rubric,
    wrong, leak, answer_kind, canonical, tolerance, stepwise, final_answer; an
    mc_reason draft's A37 option rules lead with option_count, one_correct,
    correct_misconception, misconception_key, misconception_text, option_text
    or letter, and its reference is checked for the model's own working under
    deliberation). The wrong rules read a free or teachback draft's
    wrong_keys / wrong_texts; an mc_reason draft's wrong reasons are its
    distractors' misconceptions (common_wrong), and its own lists are not
    read. Run repair_draft first to store what it can repair."""
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
    if draft.format != _MC_REASON:  # an mc_reason item's are its distractors' (A37)
        reasons.extend(_wrong_list_reasons(draft))
    if draft.prompt.strip() and leak_in_prompt(draft.prompt, draft.reference_answer):
        reasons.append("leak: the reference answer appears in the prompt")
    if draft.answer_kind not in CHECK_ITEM_ANSWER_KINDS:
        reasons.append(f"answer_kind {draft.answer_kind!r} is not one of {CHECK_ITEM_ANSWER_KINDS}")
    if draft.format == _MC_REASON:
        reasons.extend(_option_reasons(draft))
        working = _working(draft)
        if working:
            reasons.append(
                f"deliberation: the reference_answer is the model's own working "
                f"({working.group(0).strip(' .!?:;,')!r}), not a model answer"
            )
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
    reasons.extend(_wrong_text_answer_reasons(draft))
    return reasons


def _wrong_text_answer_reasons(draft: CheckItemDraft) -> list[str]:
    """PKG-10 fix round F3, decided in fix round 4 (spec §13 A77): a common
    wrong reason never states the final answer. The confrontation line puts a
    stored wrong reason in front of the tutor while the answer may still be
    unreleased, and it withholds a text that states it — through
    learning.leak.confront_text_states_answer, the SAME function this lint
    calls, so a stored wrong reason is exactly one the line can serve (rounds 2
    and 3 kept a drafting-only role heuristic that drifted from the serve check
    in both directions). The drafter has no option letter yet (letters are
    placed after validation, A37): the correct option's TEXT is checked, the
    letter only at serve. No stated final answer: _final_answer_reasons
    refuses the draft."""
    if not answer_run(draft.final_answer):
        return []
    # lazy (learning.leak imports this module); drafting runs only with the loop on
    from learning.leak import confront_text_states_answer

    correct = next((o.text for o in draft.options if o.is_correct), None)
    return [
        f"wrong reason {w.key!r} states the final answer"
        for w in common_wrong(draft)
        if w.text
        and confront_text_states_answer(
            w.text,
            final_answer=draft.final_answer,
            canonical_answer=draft.canonical_answer,
            option_text=correct if draft.format == _MC_REASON else None,
        )
    ]


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


def serve_quality(item) -> tuple[int, int, bool]:
    """How a serving picker ranks two items its own rule treats as equal
    (spec §13 A129): a confirmed key first (`_verify_rank`: an independent
    blind solve agreed, staff approved it or an audit found it correct, A124),
    then the item-flaw lint tier (`lint_rank`: linted clean, never linted,
    flagged — A113, A119, A128), then, between two flagged items, one with its
    sources before an `unsourced` one (A128). It is the post-test's order
    (`_quality_rank`, A126) without its hash tie-break, refined by A128's
    provenance, so no picker contradicts the post-test.

    Every picker compares it only AFTER its own rule's keys (the difficulty
    target, the strand, the channel, novelty, the reserve exclusions), so it
    only ever chooses among items that rule leaves equal, and a flagged item
    still serves when it is all the rule allows. It is no evidence weight: a
    flag is not a wrong key, and a held item is never servable at all."""
    return (_verify_rank(item), lint_rank(item), unsourced(item))


def select_item(
    items: Iterable[CheckItem],
    *,
    format: str,
    difficulty: int,
    exclude_hashes: Iterable[str] = (),
    familiarity: Mapping[str, int] | None = None,
) -> CheckItem | None:
    """A servable item (A34: it states a final answer; A124: not held) of exactly `format`
    whose hash is not excluded: the nearest to `difficulty` (exactly it first,
    then the nearest, lower first on ties), else None. Format is never
    substituted — each format is a different evidence channel (spec §3.1).
    At the chosen difficulty, the best by `serve_quality` (A129: a confirmed
    key, then clean, never-linted, flagged; A128: an item with its sources
    before an `unsourced` one), then the oldest (created_at, id). Difficulty
    stays first, because the band's target is a learning requirement and an
    item's quality is a preference among items that meet it.

    `familiarity` (spec §13 A140, the cue-familiarity dial; a student with
    varied_isomorphs on): question_hash → how familiar the item's surface is
    to the student on this concept (learning.surface.familiarity_by_hash).
    It ranks after serve_quality and before the age tie-break, so it chooses
    only among items the difficulty and quality keys leave equal; an item it
    does not list ranks as an unknown surface. None (the flag off): the key is
    exactly the one above."""
    excluded = set(exclude_hashes)
    candidates = [
        i
        for i in items
        if i.format == format and i.question_hash not in excluded and is_servable(i)
    ]
    if not candidates:
        return None
    if familiarity is None:
        return min(
            candidates,
            key=lambda i: (
                abs(i.difficulty - difficulty),
                i.difficulty,
                *serve_quality(i),
                i.created_at or "",
                i.id,
            ),
        )
    return min(
        candidates,
        key=lambda i: (
            abs(i.difficulty - difficulty),
            i.difficulty,
            *serve_quality(i),
            familiarity.get(i.question_hash, SURFACE_FAMILIARITY_UNKNOWN),
            i.created_at or "",
            i.id,
        ),
    )


def lint_rank(item) -> int:
    """How a post-test choice ranks an item by its item-flaw lint (§13 A113):
    0 linted clean, 1 never linted (lint_flags None), 2 flagged — any stored
    code, so an `unsourced` item (A128) goes after one with its sources."""
    flags = getattr(item, "lint_flags", None)
    if flags is None:
        return 1
    return 2 if flags else 0


def lint_tiers(items: Iterable[CheckItem]) -> list[list[CheckItem]]:
    """`items` split by lint_rank — clean, never linted, flagged — each in
    its given order (A113: the post-test tries them in that order)."""
    tiers: list[list[CheckItem]] = [[], [], []]
    for item in items:
        tiers[lint_rank(item)].append(item)
    return tiers


def _verify_rank(item) -> int:
    """0 when the key is confirmed (`canonical_verified`: an independent blind
    solve agreed, an admin approved it or an audit found it correct, A124), else 1."""
    return 0 if getattr(item, "canonical_verified", False) else 1


def _quality_rank(item) -> tuple:
    """How two items one rule allows compare (A126): a confirmed key first
    (A124 — a wrong key is no measurement at all), then the item-flaw lint
    (A113: clean, never linted, flagged), then the lowest question_hash."""
    return (_verify_rank(item), lint_rank(item), item.question_hash)


def _reserve_format_rank(fmt: str) -> int:
    return POSTTEST_RESERVE_FORMATS.index(fmt) if fmt in POSTTEST_RESERVE_FORMATS else len(
        POSTTEST_RESERVE_FORMATS
    )


def _parallel_rank(item, first) -> tuple:
    """How close `item` is to the first reserve's shape — the second reserve
    is its parallel form (A126): the same format and difficulty (a duplicate
    cell — the pool allows it only when it holds more than one item there), else
    the same difficulty in the next POSTTEST_RESERVE_FORMATS format, else the
    same format at the nearest difficulty (the lower on a tie), else the nearest
    difficulty in format order; then _quality_rank."""
    same_d, same_f = item.difficulty == first.difficulty, item.format == first.format
    level = 0 if same_d and same_f else 1 if same_d else 2 if same_f else 3
    return (
        level,
        abs(item.difficulty - first.difficulty),
        item.difficulty,
        _reserve_format_rank(item.format),
        *_quality_rank(item),
    )


def posttest_reserve_hashes(items: Iterable[CheckItem]) -> tuple[str, ...]:
    """The concept's protected post-test items (A23, A126), in window order: up
    to two question hashes, computed from the concept's bank at read time like
    every A23 reserve before them — no stored status, nothing to migrate.

    The FIRST is the A23 reserve: among servable (A34; never held, A124) items,
    the `free` ones at CHECK_ITEM_DIFFICULTIES[1], else every servable one —
    the best by _quality_rank (a confirmed key, then the lint tier, A113, then
    the lowest hash). The SECOND is its parallel form (_parallel_rank: the same
    cell when the pool has two items there, else the same difficulty in the
    next format of POSTTEST_RESERVE_FORMATS, …), taken only when at least
    POSTTEST_RESERVE_MIN_LEFT servable items remain beside both, so a small
    bank keeps its one reserve and its practice. Probe, in-session checks,
    review and the H4 siblings never serve either; the post-test does."""
    servable: dict[str, CheckItem] = {}
    for item in items:
        if is_servable(item):
            servable.setdefault(item.question_hash, item)
    pool = list(servable.values())
    mid = CHECK_ITEM_DIFFICULTIES[1]
    preferred = [i for i in pool if i.format == POSTTEST_RESERVE_FORMATS[0] and i.difficulty == mid]
    candidates = preferred or pool
    if not candidates:
        return ()
    first = min(candidates, key=_quality_rank)
    rest = [i for i in pool if i.question_hash != first.question_hash]
    if len(rest) - 1 < POSTTEST_RESERVE_MIN_LEFT:
        return (first.question_hash,)
    second = min(rest, key=lambda i: _parallel_rank(i, first))
    return (first.question_hash, second.question_hash)


def posttest_reserve_hash(items: Iterable[CheckItem]) -> str | None:
    """The FIRST post-test reserve (posttest_reserve_hashes), or None."""
    reserves = posttest_reserve_hashes(items)
    return reserves[0] if reserves else None


def posttest_reserves(items: Iterable[CheckItem]) -> frozenset[str]:
    """Every protected post-test item of the concept (posttest_reserve_hashes) —
    what probe, in-session checks, review and the H4 siblings exclude."""
    return frozenset(posttest_reserve_hashes(items))


# ── the outcome item a window poses (spec §13 A126) ─────────────────────────


_MATCH_RANK = {"exact": 0, "difficulty": 1, "format": 2, "none": 3, "no_pretest": 3}
assert set(_MATCH_RANK) == set(POSTTEST_ITEM_MATCHES)


def pretest_match(item, pretest) -> str:
    """How a post-test item compares with the student's pretest item (the
    concept's FIRST graded item, the A112 anchor): `exact` (same format and
    difficulty), `difficulty` (same difficulty only — the cognitive demand
    matched, the response format not), `format` (same format only), `none`, or
    `no_pretest` when there is no pretest item to compare with."""
    if pretest is None:
        return "no_pretest"
    same_d, same_f = item.difficulty == pretest.difficulty, item.format == pretest.format
    return "exact" if same_d and same_f else "difficulty" if same_d else "format" if same_f else "none"


def pretest_form(items: Sequence[CheckItem], excluded: Iterable[str] = ()) -> CheckItem | None:
    """The concept's matched pretest form (spec §13 A130, flag
    `probe_matched_pretest`): the item the probe asks FIRST on a concept the
    student has no graded evidence on, so that the answer — the concept's
    anchor, its A112 pretest — is parallel to the post-test reserves the
    delayed outcome will be measured on (A126).

    Among the servable items (A34, A124) that are neither a reserve
    (`posttest_reserve_hashes`, over the whole bank) nor in `excluded` (what
    the student must not be asked: seen, revealed, reported, asked, withdrawn):
    the best by its matches to the reserves (`pretest_match`), compared as
    their sorted ranks — so a form exact to one reserve and difficulty-matched
    to the other comes before one difficulty-matched to both — kept only when
    its best match is in PRETEST_FORM_MATCHES (the same format and difficulty,
    else the same difficulty; a format-only or no match is no parallel form);
    then A129's serve_quality; then the reserves' format order
    (POSTTEST_RESERVE_FORMATS: the strong channels first); then the lowest
    hash. None when the bank has no reserve or no parallel form is left: the
    probe then keeps its own first-item rule. Never a reserve: a reserve asked
    now would be no fresh outcome item later."""
    reserves = posttest_reserve_hashes(items)
    if not reserves:
        return None
    by_hash = {i.question_hash: i for i in items}
    protected = [by_hash[h] for h in reserves]
    skip = set(excluded) | set(reserves)
    acceptable = max(_MATCH_RANK[m] for m in PRETEST_FORM_MATCHES)
    best: tuple | None = None
    chosen: CheckItem | None = None
    for item in items:
        if item.question_hash in skip or not is_servable(item):
            continue
        matches = tuple(sorted(_MATCH_RANK[pretest_match(r, item)] for r in protected))
        if matches[0] > acceptable:
            continue
        key = (matches, *serve_quality(item), _reserve_format_rank(item.format), item.question_hash)
        if best is None or key < best:
            best, chosen = key, item
    return chosen


class PosttestChoice(NamedTuple):
    item: CheckItem
    match: str  # POSTTEST_ITEM_MATCHES: the item against the student's pretest item
    source: str  # POSTTEST_ITEM_SOURCES: a protected reserve, or a fallback


def choose_posttest_item(
    items: Sequence[CheckItem],
    excluded: Iterable[str],
    *,
    window_index: int,
    pretest: CheckItem | None = None,
) -> PosttestChoice | None:
    """The item window `window_index` (its index in POSTTEST_WINDOWS_DAYS)
    poses, and how it was chosen (A126). Never an item in `excluded` (seen,
    revealed or reported: A23, A113) and never an unservable one (A34, A124).

    1. A FRESH RESERVE (posttest_reserve_hashes) — protected from probe, check
       and review, so whether it is still fresh never depends on how the
       student did: the one that best matches the student's pretest item
       (pretest_match: exact, then difficulty, then format, then neither),
       then the window's own reserve (the first for the first window, the
       second for the second), then reserve order. Every window has one while
       both are fresh; the first window takes the better-matched one.
    2. Else a FALLBACK — a fresh unprotected item — by the same match, then a
       `free` item (A23's order), a confirmed key, the lint tier, the nearest
       CHECK_ITEM_DIFFICULTIES[1], the lower difficulty and the lowest hash.
       Its availability depends on what the student practised, which is why
       the pose records the source and the match: an analysis can restrict
       to reserve-sourced or matched outcomes.
    None when nothing fresh and servable is left."""
    excluded = set(excluded)
    fresh = [i for i in items if is_servable(i) and i.question_hash not in excluded]
    if not fresh:
        return None
    reserves = posttest_reserve_hashes(items)
    own = reserves[window_index] if 0 <= window_index < len(reserves) else None
    protected = [i for i in fresh if i.question_hash in reserves]
    mid = CHECK_ITEM_DIFFICULTIES[1]
    if protected:
        chosen = min(
            protected,
            key=lambda i: (
                _MATCH_RANK[pretest_match(i, pretest)],
                0 if i.question_hash == own else 1,
                reserves.index(i.question_hash),
            ),
        )
        return PosttestChoice(chosen, pretest_match(chosen, pretest), "reserve")
    chosen = min(
        fresh,
        key=lambda i: (
            _MATCH_RANK[pretest_match(i, pretest)],
            0 if i.format == "free" else 1,
            _verify_rank(i),
            lint_rank(i),
            abs(i.difficulty - mid),
            i.difficulty,
            i.question_hash,
        ),
    )
    return PosttestChoice(chosen, pretest_match(chosen, pretest), "fallback")


def posttest_skip_reason(items: Iterable[CheckItem], *, exposed: Iterable[str]) -> str:
    """Why a due window has nothing to pose (POSTTEST_SKIP_REASONS), given that
    choose_posttest_item found nothing fresh: `no_items` when the concept has
    no servable item at all; `exhausted` when every servable item is in
    `exposed` (seen or revealed, A23); else `reported` — what is left is only
    excluded because the student reported it (A113)."""
    exposed = set(exposed)
    servable = [i for i in items if is_servable(i)]
    if not servable:
        reason = "no_items"
    elif all(i.question_hash in exposed for i in servable):
        reason = "exhausted"
    else:
        reason = "reported"
    assert reason in POSTTEST_SKIP_REASONS
    return reason

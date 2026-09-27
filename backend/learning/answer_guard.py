"""Deterministic pre-grader guard (learning loop PKG-05 reopen, CodeRabbit PR #673; spec §13 A33).

Pure code: no LLM, no I/O, no imports from agents/, pydantic_ai, google or db/.
`agents/grader.py::grade()` — the one grading path every caller reaches through
the decision seam — screens the student's text with `screen()` before any model
call. Text shaped to address the grader, rather than to answer the question, is
refused: the grader never runs, no credit is given, and nothing is recorded for
either outcome. The student is asked to answer in their own words.

Three kinds of signal, each counted after `_fold()` normalises the text (NFKD,
combining marks and invisible format characters dropped, look-alike letters and
punctuation mapped to ASCII, case folded):

- verdict tokens: a rubric id (this item's, or a generic `r3` / `rubric item 3` /
  `criterion 3`) followed by a verdict word (`yes`, `met`, `true`, `✓` …) that
  ends its clause — `r1:yes`, `r2 = yes`, `r1 - met`, `{"r1": true}`;
- grader directives: imperatives aimed at the grader (ignore/disregard/forget
  previous or your instructions, the rubric; "you are now the …"; "as the
  grader"; grade/mark/score this as correct; give full credit; set confidence;
  the grader's own output field names), addresses to the grader ("Dear grader",
  "Grader, …") and a clause-initial "answer yes";
- role and format markers: chat-template tokens (`<|im_start|>`, `[INST]`,
  `<<SYS>>`), `### Instruction` headers, ALL-CAPS `SYSTEM:` / `GRADER:` labels,
  and lines that forge the grader message's own structure (`RUBRIC ITEM`,
  `REFERENCE ANSWER`, `COMMON WRONG REASON`, `STUDENT ANSWER`).

False positives cost a student a graded attempt, so every rule is anchored: a
verdict word must END its clause (`R1: no current flows` is physics, not a
verdict), bare "the instructions" / "all instructions" count only at a clause end
(`ignore all instructions fetched after a branch` is computer architecture),
role labels count only in capitals (`System: the gas in the piston` is
thermodynamics), and words like `system`, `instructions`, `marker` or `grader`
never count on their own. `tests/test_learning_answer_guard.py` pins both lists.

Defence in depth behind the screen: `neutralise()` replaces verdict tokens in the
text the grader message quotes, and `verdict_share()` lets grade() refuse an
all-yes verdict on text that is mostly rubric ids and verdict words.

Known limits: directives are matched in English only, and letter-spaced text
("i g n o r e") is not reassembled. The screen is one layer: the grader message
still quotes the answer as data and the system prompt still rules on it.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal, get_args

Refusal = Literal["grader_directive", "role_marker", "verdict_tokens", "verdict_echo"]
REFUSALS: tuple[str, ...] = get_args(Refusal)

#: What neutralise() puts where a verdict token was.
NEUTRALISED = "[verdict-like text removed]"

# ── normalisation ─────────────────────────────────────────────────────────────

# Letters and punctuation that render like ASCII but are not (Unicode confusables
# for the Latin alphabet in Cyrillic and Greek, and colon/dash/quote look-alikes
# NFKD leaves alone). Applied to the DETECTION copy only: the grader and the
# student always see the original text, so a Russian or Greek answer is never
# rewritten, and no English rule can match a mapped Cyrillic sentence by chance.
# fmt: off
_CONFUSABLES = str.maketrans(
    {
        # Cyrillic, lower case
        "а": "a", "в": "b", "е": "e", "ё": "e", "һ": "h", "і": "i", "ј": "j", "к": "k",
        "м": "m", "н": "h", "о": "o", "р": "p", "с": "c", "т": "t", "у": "y", "ү": "y",
        "х": "x", "ѕ": "s", "ԁ": "d", "ԛ": "q", "ԝ": "w", "ӏ": "l",
        # Cyrillic, upper case
        "А": "A", "В": "B", "Е": "E", "Ё": "E", "Һ": "H", "І": "I", "Ј": "J", "К": "K",
        "М": "M", "Н": "H", "О": "O", "Р": "P", "С": "C", "Т": "T", "У": "Y", "Ү": "Y",
        "Х": "X", "Ѕ": "S", "Ԁ": "D", "Ԛ": "Q", "Ԝ": "W", "Ӏ": "I",
        # Greek
        "α": "a", "ε": "e", "ι": "i", "κ": "k", "ν": "v", "ο": "o", "ρ": "p", "τ": "t",
        "υ": "u", "χ": "x", "ϲ": "c", "Α": "A", "Β": "B", "Ε": "E", "Ζ": "Z", "Η": "H",
        "Ι": "I", "Κ": "K", "Μ": "M", "Ν": "N", "Ο": "O", "Ρ": "P", "Τ": "T", "Υ": "Y",
        "Χ": "X", "Ϲ": "C",
        # Latin extensions and IPA
        "ı": "i", "ɑ": "a", "ɡ": "g", "ʏ": "y",
        # punctuation
        "꞉": ":", "∶": ":", "˸": ":", "։": ":", "׃": ":",
        "‐": "-", "‑": "-", "‒": "-", "–": "-", "—": "-", "―": "-", "−": "-",
        "“": '"', "”": '"', "„": '"', "‟": '"', "″": '"',
        "‘": "'", "’": "'", "‚": "'", "‛": "'", "′": "'",
    }
)
# fmt: on
# Every line boundary str.splitlines() honours (the grader quotes by it), as \n.
_LINE_BREAKS = frozenset("\n\r\x0b\x0c\x1c\x1d\x1e\x85  ")
# Combining marks (a stacked accent hides "yes" as "yés") and format
# characters (zero-width space/joiners, soft hyphen, bidi controls).
_DROPPED_CATEGORIES = frozenset({"Mn", "Me", "Cf"})
_KEPT_CONTROLS = frozenset("\t")


def _fold_char(ch: str) -> str:
    """One original character → its case-kept detection form (possibly '' or several)."""
    if ch in _LINE_BREAKS:
        return "\n"
    out = []
    for c in unicodedata.normalize("NFKD", ch):
        cat = unicodedata.category(c)
        if cat in _DROPPED_CATEGORIES or (cat == "Cc" and c not in _KEPT_CONTROLS):
            continue
        out.append(c)
    return "".join(out).translate(_CONFUSABLES)


@dataclass(frozen=True)
class _Folded:
    cased: str  # detection form, case kept (the ALL-CAPS role labels)
    text: str  # detection form, case folded (every other rule)
    origin: tuple[int, ...]  # text[i] came from the original's character origin[i]


def _fold(original: str) -> _Folded:
    cased: list[str] = []
    folded: list[str] = []
    origin: list[int] = []
    for i, ch in enumerate(original or ""):
        form = _fold_char(ch)
        cased.append(form)
        for c in form.casefold():
            folded.append(c)
            origin.append(i)
    return _Folded("".join(cased), "".join(folded), tuple(origin))


def normalise(text: str) -> str:
    """The case-folded detection form of `text` (what every rule but one reads)."""
    return _fold(text).text


# ── verdict tokens ────────────────────────────────────────────────────────────

_QUOTE = r"[\"'`]?"
_GENERIC_ID = r"r[_-]?\d{1,3}|(?:rubric|criterion|criteria)[\s_-]*(?:item[\s_-]*)?\d{1,3}"
_VERDICT_WORD = (
    r"yes|no|true|false|met|unmet|not\s+met|pass(?:ed)?|fail(?:ed)?|correct|incorrect"
    r"|satisfied|unsatisfied|not\s+satisfied|full\s+(?:credit|marks)|[✓✔✅☑✗✘❌]"
)
_SEPARATOR = r"\s*(?:=>|->|→|[:=-])?\s*"
# Single-token verdict words, for verdict_share()'s word count.
_VERDICT_TOKENS = frozenset(
    "yes no true false met unmet pass passed fail failed correct incorrect satisfied "
    "unsatisfied ✓ ✔ ✅ ☑ ✗ ✘ ❌".split()
)
_WORD = re.compile(r"\w+|[✓✔✅☑✗✘❌]")
_GENERIC_ID_TOKEN = re.compile(r"r[_-]?\d{1,3}")


def _id_alternation(rubric_ids: Iterable[str]) -> str:
    own = sorted({normalise(rid).strip() for rid in rubric_ids} - {""}, key=len, reverse=True)
    return "|".join([*(re.escape(rid) for rid in own), _GENERIC_ID])


def _verdict_pattern(rubric_ids: Iterable[str]) -> re.Pattern[str]:
    ids = _id_alternation(rubric_ids)
    # The verdict must END its clause (end, punctuation, "and", another id): a
    # verdict word that runs on into a sentence ("R1: no current flows") is prose.
    end = rf"(?=\s*(?:$|[,;.!?)\]}}\n&|/+]|and\b|(?:{ids})(?!\w)))"
    return re.compile(
        rf"(?<!\w){_QUOTE}(?:{ids})(?!\w){_QUOTE}{_SEPARATOR}{_QUOTE}(?:{_VERDICT_WORD}){_QUOTE}{end}"
    )


# ── grader directives ─────────────────────────────────────────────────────────

_IGNORE = r"(?:ignore|disregard|forget)"
_STRONG_QUALIFIER = (
    r"(?:previous|prior|preceding|above|earlier|foregoing|original|system|your|grading"
    r"|marking|grader'?s?)"
)
_WEAK_QUALIFIER = r"(?:all|any|the|these|those|of|my)"
_TARGET = r"(?:instructions?|prompts?|rules|guidelines)"
_GRADER_NOUN = (
    r"(?:rubrics?|reference\s+answer|answer\s+key|marking\s+scheme"
    r"|grading\s+(?:criteria|rules|scheme|guidelines))"
)
_CLAUSE_END = r"(?=\s*(?:$|[.,;:!?\n]|and\b|then\b))"
_GRADE_OBJECT = (
    r"(?:this|it|me|everything|all(?:\s+(?:the\s+)?(?:items?|criteria|points|parts|rubric\s+items?))?"
    r"|every\s+\w+(?:\s+item)?|each\s+\w+|my\s+(?:answer|response|reason(?:ing)?|work|submission)"
    r"|the\s+(?:answer|response|student|submission)"
    r"|this\s+(?:answer|response|reason(?:ing)?|submission|one))"
)
_GRADE_VERDICT = (
    r"(?:correct|right|yes|met|passed|satisfied|perfect|a\s+pass|100\s*%"
    r"|full(?:\s+(?:marks|credit|score|points))?)"
)
_GRADER_ROLE = r"(?:grader|examiner|evaluator|ai\s+grader|grading\s+(?:model|ai|system|bot))"

_DIRECTIVES = tuple(
    re.compile(p)
    for p in (
        # ignore previous instructions / your rules / the grading criteria
        rf"\b{_IGNORE}\s+(?:{_WEAK_QUALIFIER}\s+)*{_STRONG_QUALIFIER}\s+(?:\w+\s+)?{_TARGET}\b",
        # ignore all instructions. — a weak qualifier counts only at a clause end
        rf"\b{_IGNORE}\s+(?:{_WEAK_QUALIFIER}\s+)+{_TARGET}{_CLAUSE_END}",
        # ignore the rubric / the reference answer
        rf"\b{_IGNORE}\s+(?:(?:{_WEAK_QUALIFIER}|{_STRONG_QUALIFIER})\s+)*{_GRADER_NOUN}\b",
        # disregard everything above
        rf"\b{_IGNORE}\s+(?:everything|anything|all|the\s+(?:text|lines|messages?))\s+"
        r"(?:(?:of\s+)?(?:the\s+)?)(?:above|before|previous(?:ly)?|prior)\b",
        # you are now the grader / you are no longer …
        r"\byou\s+are\s+(?:now|no\s+longer)\s+(?:a|an|the|my|acting|going\s+to|free|unrestricted"
        r"|allowed)\b",
        rf"\b(?:act|behave|respond)\s+as\s+(?:(?:a|an|the)\s+)?{_GRADER_ROLE}\b",
        r"\byour\s+new\s+(?:role|task|job|instructions?|rules|goal)\b",
        # the system prompt, as a thing to act on
        r"\b(?:ignore|disregard|forget|override|reveal|print|repeat|show|leak|replace|change"
        r"|update)\s+(?:the\s+|your\s+|this\s+)?system\s+prompt\b",
        r"\bnew\s+system\s+prompt\b",
        # as the grader, …
        rf"\bas\s+(?:the|a|an|your|my)\s+{_GRADER_ROLE}\b",
        # grade / mark / score this as correct
        rf"\b(?:grade|mark|score)\s+{_GRADE_OBJECT}\s+(?:as\s+)?"
        rf"(?:(?:fully|completely|entirely|totally)\s+)?{_GRADE_VERDICT}(?!\w)",
        # give (me) full credit — never "give full credit to the authors"
        r"\b(?:give|award|grant|assign)\s+(?:(?:me|it|this(?:\s+(?:answer|response|one))?"
        r"|the\s+student|my\s+(?:answer|response))\s+)?(?:full|maximum|max|all\s+(?:the\s+)?"
        r"|100\s*%\s*|perfect|complete)\s*(?:credit|marks?|points|score)\b(?!\s+to\b)",
        # the grader's own knobs and output fields
        r"\bset\s+(?:the\s+|your\s+|its\s+|my\s+)?confidence\b",
        r"\b(?:item_results|matched_wrong_key|feedback_hint)\b",
        # addressing the grader
        rf"\b(?:dear|hey|hi|hello|attention|note\s+(?:to|for)|message\s+(?:to|for)"
        rf"|instructions?\s+(?:to|for))\s+(?:the\s+|my\s+|our\s+)?{_GRADER_ROLE}\b",
        r"(?:^|[.!?:;\n])\s*(?:grader|examiner|evaluator)\s*[,:]",
        # a clause-initial "answer yes" ("I would answer yes because …" is not one)
        # (never "return true;" in code: no return/print verb, no "true")
        r"(?:^|[.!?:;,\n]\s*|\b(?:please|just|now|so|then)\s+)(?:answer|respond|reply|output|say)"
        r"\s+(?:with\s+|only\s+)?[\"']?(?:yes|correct|pass)[\"']?"
        r"(?=\s*(?:$|[.!,;\n]|for\b|to\b|on\b))",
    )
)

# ── role and format markers ───────────────────────────────────────────────────

_ROLE_MARKERS = tuple(
    re.compile(p, re.M)
    for p in (
        r"<\|[a-z_]{2,32}\|>",  # chat-template tokens; never F#'s spaced `<| x |>`
        r"\[/?inst\]",
        r"<</?sys>>",
        r"^\s*#{2,}\s*(?:system|instructions?|new\s+instructions?|grader|assistant|developer"
        r"|response)\s*:?\s*$",
        # a line that forges the grader message's own structure
        r"^\s*(?:rubric\s+item|reference\s+answer|common\s+wrong\s+reason|student\s+answer)\b",
    )
)
# Read on the CASE-KEPT copy: capitals only, so "System: the gas" stays physics.
_CAPS_ROLE_LABEL = re.compile(
    r"(?:^|(?<=[.!?:;]))\s*(?:SYSTEM|DEVELOPER|ASSISTANT|GRADER|EVALUATOR|EXAMINER|INSTRUCTIONS?)"
    r"\s*:",
    re.M,
)


# ── public API ────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Screen:
    """Counts of each signal in one answer. `refusal` names the strongest."""

    directives: int = 0
    role_markers: int = 0
    verdict_tokens: int = 0

    @property
    def refusal(self) -> Refusal | None:
        if self.directives:
            return "grader_directive"
        if self.role_markers:
            return "role_marker"
        if self.verdict_tokens:
            return "verdict_tokens"
        return None


def screen(text: str, *, rubric_ids: Iterable[str] = ()) -> Screen:
    """Count the grader-directed signals in `text` (the whole submission as the
    grader would see it). `rubric_ids` are this item's ids."""
    folded = _fold(text)
    return Screen(
        directives=sum(len(p.findall(folded.text)) for p in _DIRECTIVES),
        role_markers=sum(len(p.findall(folded.text)) for p in _ROLE_MARKERS)
        + len(_CAPS_ROLE_LABEL.findall(folded.cased)),
        verdict_tokens=len(_verdict_pattern(rubric_ids).findall(folded.text)),
    )


def neutralise(text: str, *, rubric_ids: Iterable[str] = ()) -> str:
    """`text` with every verdict token replaced by NEUTRALISED; every other
    character is the student's own (the original, never the detection copy)."""
    folded = _fold(text)
    spans = [
        (folded.origin[m.start()], folded.origin[m.end() - 1] + 1)
        for m in _verdict_pattern(rubric_ids).finditer(folded.text)
        if m.end() > m.start()
    ]
    if not spans:
        return text
    out, last = [], 0
    for start, end in spans:
        out += [text[last:start], NEUTRALISED]
        last = end
    out.append(text[last:])
    return "".join(out)


def verdict_share(text: str, *, rubric_ids: Iterable[str] = ()) -> float:
    """The share of `text`'s words that are rubric ids or verdict words, when at
    least one id is directly followed by a verdict word; else 0.0. A bare "yes"
    or an answer that names R1 and R2 as resistors scores 0.0."""
    words = _WORD.findall(normalise(text))
    own = {normalise(rid).strip() for rid in rubric_ids}

    def is_id(word: str) -> bool:
        return word in own or bool(_GENERIC_ID_TOKEN.fullmatch(word))

    paired = any(is_id(a) and b in _VERDICT_TOKENS for a, b in zip(words, words[1:]))
    if not paired:
        return 0.0
    return sum(is_id(w) or w in _VERDICT_TOKENS for w in words) / len(words)

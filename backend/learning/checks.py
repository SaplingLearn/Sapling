"""Check item models, identity, selection, validation (spec §2, §3.4, §3.5, §4;
§13 A2, A17, A22, A23).

Pure: imports nothing from agents/, db/, services/. The hash normalization is
a deliberate copy of services/quiz_identity.py's idea, versioned separately —
the two identities must be able to change independently. Items are course
assets keyed on (course_id, concept_key); the concept_key rule itself lives in
services/graph_service._normalize_concept and is applied by the service.

References are model-generated and unverified (A17): nothing here calls them
verified, and `canonical_verified` is never set true by this package (A22).
"""

from __future__ import annotations

import hashlib
import math
import re
from collections.abc import Iterable
from typing import Literal

from pydantic import BaseModel, Field

from learning.params import (
    CHECK_HASH_VERSION,
    CHECK_ITEM_ANSWER_KINDS,
    CHECK_ITEM_DIFFICULTIES,
    CHECK_ITEM_FORMATS,
    CHECK_ITEM_MIN_RUBRIC,
    CHECK_ITEM_MIN_WRONG,
    CHECK_ITEM_STEPWISE_MIN_STEPS,
)

_SEP = "\x1f"  # unit separator: never appears in normalized text
_STEP_LINE = re.compile(r"^\s*\d+[.)]", re.MULTILINE)  # a numbered step, A17/A22
_WORD = re.compile(r"\w+")
# Leak-comparison tokens: a decimal number whole, a word, or one math symbol.
# Sentence punctuation (. , ; : ! ? quotes brackets dashes) is not a token, so
# a reference ending in "." still matches mid-sentence; operators are, so
# "x = 2" is not found inside "x + 2 = 4".
_LEAK_TOKEN = re.compile(r"\d+(?:\.\d+)*|\w+|[+\-*/=<>^%×÷±≤≥≠≈√∑∏∫∂∞→←⇒⇔]")
# Concept-name tokens shorter than this ("of", "to", "a") say nothing about
# which passage discusses the concept, so rank_chunks_for_concept ignores them.
# The one small literal the PKG-04 prompt allows here: a tokenizer floor, not a
# loop tuning knob, so it does not live in learning/params.py.
_MIN_TOKEN_LEN = 3
# English function words of that length or more. They occur in almost any
# passage, so a match on one says nothing about the concept: without this,
# "Causes of the French Revolution" met the backfill's relevance floor (A23)
# against a CS passage through "the" and was drafted from unrelated text.
_STOPWORDS = frozenset(
    """
    about above across after against along also among and any are because been
    before being below between both but can could did does doing down during each
    either few for from had has have having her here hers him his how into its
    just may might more most must nor not off onto only other our ours out over
    own per same shall she should some such than that the their theirs them then
    there these they this those through too under until upon very via was were
    what when where which while who whom whose why will with within without would
    yet you your yours
    """.split()
)
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


class CheckItemDraft(BaseModel):
    """The agent's per-item output. FLAT — str / int / bool / list[str] only
    (docs/attempts/2026-05-03-orchestrator-schema-complexity.md)."""

    concept: str = Field(
        description="which of this call's concepts the item assesses, copied exactly"
    )
    format: str = Field(description="one of free | teachback | mc_reason")
    difficulty: int = Field(description="1 recall, 2 application, 3 transfer")
    prompt: str
    reference_answer: str
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


def validate_draft(draft: CheckItemDraft) -> list[str]:
    """Every reason `draft` is unusable; [] when it may be stored. Each reason
    names the rule it is about (format, difficulty, prompt, reference, rubric,
    wrong, leak, answer_kind, option, canonical, tolerance, stepwise)."""
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
    """An item of exactly `format` whose hash is not excluded: the first at
    exactly `difficulty` (ties by (created_at, id)), else the nearest
    difficulty (lower first on ties), else None. Format is never substituted —
    each format is a different evidence channel (spec §3.1)."""
    excluded = set(exclude_hashes)
    candidates = [i for i in items if i.format == format and i.question_hash not in excluded]
    if not candidates:
        return None
    return min(
        candidates,
        key=lambda i: (abs(i.difficulty - difficulty), i.difficulty, i.created_at or "", i.id),
    )


def posttest_reserve_hash(items: Iterable[CheckItem]) -> str | None:
    """The concept's post-test reserve (A23): the lowest question_hash among
    `free` items at CHECK_ITEM_DIFFICULTIES[1], else the lowest overall, else
    None. Probe, in-session checks and review never serve it."""
    items = list(items)
    mid = CHECK_ITEM_DIFFICULTIES[1]
    preferred = [i.question_hash for i in items if i.format == "free" and i.difficulty == mid]
    if preferred:
        return min(preferred)
    return min((i.question_hash for i in items), default=None)

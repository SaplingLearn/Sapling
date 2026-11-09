"""Check-item alignment: apply the verifier's answers in code (spec §13 A119).

Pure: imports learning.item_lint and learning.checks only (both pure), so it is listed in
tests/test_learning_loop_invariants.py::PURE_MODULES.

A drafted check item can ask one thing and grade another. Live (2026-11-07,
claude-haiku-5-5 drafting a hash-tables lecture) an mc_reason item asked "Pick
the load factor and give the reason", but one rubric criterion wanted the 0.5
linear-probing threshold — so a student who picked 0.8 because 4 / 5 = 0.8 was
graded wrong — and the item was tagged "open addressing" while it tests Load
Factor, so the evidence moved the wrong node. The A113 linter reads only the
stem and options and could catch neither.

The agents/check_items_verify.py agent answers two typed questions per item —
for each content criterion, does the question (stem, and an mc item's options)
ask the student for it; and which ONE listed course concept the question
tests, or "none" — and THIS module turns the answers into what is stored:

- a criterion the question does not ask for is dropped; the system-appended
  mc_reason reason criterion (checks.MC_REASON_CRITERION) is never sent and
  never dropped;
- no content criterion left → the item is rejected;
- the tested concept is in scope and differs from the item's → re-tagged; the
  answer "none", or a concept outside the scope → rejected;
- no usable verdict (no answer for the item, a criterion left unanswered, or
  two answers that disagree) → `unverified`; the caller's rule decides (the
  draft path drops the item, the backfill leaves a stored one untouched).

What changed is recorded as ALIGNMENT_FLAGS codes beside the linter's own in
check_items.lint_flags (`merge_flags`), so the A113 review queue lists the
item. Nothing here trusts the model for a bound: ids are matched exactly,
anything unlisted is ignored, and a missing or conflicting answer is never a
"yes".
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import NamedTuple

from learning.checks import KEY_HOLD_FLAGS, PROVENANCE_FLAGS, STAFF_HOLD_FLAGS
from learning.item_lint import LINT_FLAGS

RUBRIC_UNASKED_DROPPED = "rubric_unasked_dropped"
CONCEPT_RETAGGED = "concept_retagged"
#: Every alignment code, in the order they are stored (after LINT_FLAGS).
ALIGNMENT_FLAGS = (RUBRIC_UNASKED_DROPPED, CONCEPT_RETAGGED)

#: The verifier's answer for "tests none of the listed concepts".
NONE = "none"

# Why an item is rejected. Also the drop reasons the mc_reason top-up is told
# (agents/check_items_topup.py), so each names its rule first.
UNASKED_RUBRIC = "rubric: the question asks for none of the item's criteria (alignment check)"
NO_CONCEPT = "concept: the question tests none of the listed course concepts (alignment check)"
OUT_OF_SCOPE = "concept: the alignment check named a concept outside the course's list"
UNVERIFIED = "unverified: the alignment check gave no complete verdict for this item"
#: Spec §13 A141: a multi-concept draft one of whose components the question
#: does not need (align_components).
NOT_COMBINED = (
    "concept: the question does not need every concept it combines (alignment check)"
)
#: A short code per reason, for output that must carry no text (the backfill).
REASON_CODES = {
    UNASKED_RUBRIC: "no_asked_criterion",
    NO_CONCEPT: "tests_no_concept",
    OUT_OF_SCOPE: "concept_out_of_scope",
    UNVERIFIED: "unverified",
    NOT_COMBINED: "not_combined",
}


class Verdict(NamedTuple):
    """The verifier's answers for one item, as collected (`collect`)."""

    asked: Mapping[str, bool]  # criterion id ("c1", "c2", ...) -> asked
    concept: str  # the verifier's concept answer as written ("none" = none)


class Alignment(NamedTuple):
    """What `align` decided for one item."""

    keep: tuple[int, ...]  # indices of the content criteria kept, in order
    concept_key: str  # the key the item belongs under (its own unless re-tagged)
    flags: tuple[str, ...] = ()  # ALIGNMENT_FLAGS codes for what changed
    reject: str | None = None  # why the item is rejected; None = store/keep it
    unverified: bool = False  # no complete verdict (reject is UNVERIFIED then)


def concept_key(name) -> str:
    """services/graph_service._normalize_concept's rule (case-fold, collapse
    whitespace), restated because this module is pure; a test pins the two
    equal. The service keys items by it (spec §13 A2)."""
    return " ".join(str(name or "").split()).casefold()


def criterion_ids(count: int) -> list[str]:
    """The ids the verifier sees an item's content criteria under, in order."""
    return [f"c{i}" for i in range(1, count + 1)]


def _answer_key(answer: str) -> str:
    """The verifier's concept answer as a concept key: surrounding quotes and a
    closing full stop are not part of a name, nothing else is forgiven."""
    return concept_key(str(answer or "").strip().strip("\"'“”‘’").rstrip("."))


def collect(
    criteria: Iterable[tuple[str, str, bool]], concepts: Iterable[tuple[str, str]]
) -> dict[str, Verdict]:
    """The verifier's output — (item id, criterion id, asked) rows and (item
    id, concept) rows — as one Verdict per item id. An item answered twice in
    disagreement (a criterion yes and no, or two different concepts) gets no
    verdict at all, so `align` reports it unverified: a conflict is never read
    as either answer. An item with criterion rows but no concept row, or the
    reverse, gets none either."""
    asked: dict[str, dict[str, bool]] = {}
    conflicted: set[str] = set()
    for item, criterion, value in criteria:
        item, criterion = str(item).strip(), str(criterion).strip().lower()
        seen = asked.setdefault(item, {})
        if criterion in seen and seen[criterion] != bool(value):
            conflicted.add(item)
        seen[criterion] = bool(value)
    tested: dict[str, str] = {}
    for item, concept in concepts:
        item = str(item).strip()
        if item in tested and _answer_key(tested[item]) != _answer_key(concept):
            conflicted.add(item)
        tested.setdefault(item, str(concept))
    return {
        item: Verdict(asked[item], tested[item])
        for item in asked.keys() & tested.keys()
        if item not in conflicted
    }


def align(
    criteria_count: int,
    own_key: str,
    verdict: Verdict | None,
    scope: Mapping[str, str],
) -> Alignment:
    """Apply one item's verdict. `criteria_count` is how many content criteria
    the item has (the reason criterion excluded), `own_key` its concept key,
    `scope` the course concepts it may belong to ({concept_key: name}). The
    item's own concept is always in scope."""
    ids = criterion_ids(criteria_count)
    if verdict is None or any(cid not in verdict.asked for cid in ids):
        return Alignment((), own_key, (), UNVERIFIED, unverified=True)
    keep = tuple(i for i, cid in enumerate(ids) if verdict.asked[cid])
    if not keep:
        return Alignment(keep, own_key, (), UNASKED_RUBRIC)
    tested = _answer_key(verdict.concept)
    if not tested or tested == NONE:
        return Alignment(keep, own_key, (), NO_CONCEPT)
    if tested != own_key and tested not in scope:
        return Alignment(keep, own_key, (), OUT_OF_SCOPE)
    flags = []
    if len(keep) < criteria_count:
        flags.append(RUBRIC_UNASKED_DROPPED)
    if tested != own_key:
        flags.append(CONCEPT_RETAGGED)
    return Alignment(keep, tested, tuple(flags))


# ── multi-concept items (spec §13 A141) ─────────────────────────────────────
#
# A multi-concept item is filed under its combination (learning/
# multi_concept.py), never re-tagged: the check answers, per item, the A119
# criteria question and, for EVERY component it combines, whether a student
# needs that concept to answer the question. Every component must be needed:
# an item that does not combine what it claims is rejected (NOT_COMBINED),
# never stored under a narrower tag.


class ComponentVerdict(NamedTuple):
    """The multi-concept check's answers for one item (`collect_components`)."""

    asked: Mapping[str, bool]  # criterion id -> asked
    required: Mapping[str, bool]  # component id ("k1", "k2", ...) -> needed


def component_ids(count: int) -> list[str]:
    """The ids the check sees an item's components under, in order (apex first)."""
    return [f"k{i}" for i in range(1, count + 1)]


def collect_components(
    criteria: Iterable[tuple[str, str, bool]], components: Iterable[tuple[str, str, bool]]
) -> dict[str, ComponentVerdict]:
    """(item, criterion, asked) and (item, component, required) rows as one
    verdict per item id. An item answered twice in disagreement on either
    gets none (unverified, as `collect`), and so does an item with criteria
    rows but no component row, or the reverse."""
    asked: dict[str, dict[str, bool]] = {}
    needed: dict[str, dict[str, bool]] = {}
    conflicted: set[str] = set()
    for table, rows in ((asked, criteria), (needed, components)):
        for item, key, value in rows:
            item, key = str(item).strip(), str(key).strip().lower()
            seen = table.setdefault(item, {})
            if key in seen and seen[key] != bool(value):
                conflicted.add(item)
            seen[key] = bool(value)
    return {
        item: ComponentVerdict(asked[item], needed[item])
        for item in asked.keys() & needed.keys()
        if item not in conflicted
    }


def align_components(
    criteria_count: int, component_count: int, own_key: str, verdict: ComponentVerdict | None
) -> Alignment:
    """Apply one multi-concept item's verdict: an unasked criterion dropped,
    no content criterion left → rejected; a component not needed → rejected
    (NOT_COMBINED); a criterion or a component unanswered → unverified. Never
    re-tagged: the item keeps `own_key` (its combination's key)."""
    ids, kids = criterion_ids(criteria_count), component_ids(component_count)
    if (
        verdict is None
        or any(cid not in verdict.asked for cid in ids)
        or any(kid not in verdict.required for kid in kids)
    ):
        return Alignment((), own_key, (), UNVERIFIED, unverified=True)
    keep = tuple(i for i, cid in enumerate(ids) if verdict.asked[cid])
    if not keep:
        return Alignment(keep, own_key, (), UNASKED_RUBRIC)
    if not all(verdict.required[kid] for kid in kids):
        return Alignment(keep, own_key, (), NOT_COMBINED)
    flags = (RUBRIC_UNASKED_DROPPED,) if len(keep) < criteria_count else ()
    return Alignment(keep, own_key, flags)


def merge_flags(*flag_sets: Iterable[str] | None) -> list[str]:
    """One stored lint_flags list from several sets: the linter's codes in
    LINT_FLAGS order, then the alignment codes in ALIGNMENT_FLAGS order, then
    the A124 key-hold codes in checks.KEY_HOLD_FLAGS order, then the A128
    provenance codes in checks.PROVENANCE_FLAGS order, then A123's staff holds
    in checks.STAFF_HOLD_FLAGS order — last, where the database's
    check_item_hold_flags puts them, so a write and the trigger agree on the
    stored order; an unknown code is dropped (the column holds known codes
    only)."""
    have = {f for flags in flag_sets for f in flags or ()}
    return [
        f
        for f in (
            *LINT_FLAGS, *ALIGNMENT_FLAGS, *KEY_HOLD_FLAGS, *PROVENANCE_FLAGS, *STAFF_HOLD_FLAGS
        )
        if f in have
    ]


def alignment_flags(flags: Iterable[str] | None) -> list[str]:
    """The alignment codes among stored flags (what a re-lint must keep)."""
    have = set(flags or ())
    return [f for f in ALIGNMENT_FLAGS if f in have]


def kept_flags(flags: Iterable[str] | None) -> list[str]:
    """The stored codes no linter run can see again — the alignment codes, the
    hold codes (A124's key holds, A123's staff holds) and the A128 provenance
    codes — which a re-lint or an alignment rewrite keeps, in merge_flags'
    order. (A staff hold is the database's to set and lift; keeping it here
    only keeps a rewrite from fighting the trigger that restores it.)"""
    have = set(flags or ())
    return [
        f
        for f in (*ALIGNMENT_FLAGS, *KEY_HOLD_FLAGS, *PROVENANCE_FLAGS, *STAFF_HOLD_FLAGS)
        if f in have
    ]

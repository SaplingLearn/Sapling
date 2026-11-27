"""Interleave confusable concepts in the daily review queue (spec §13 A114).

Pure: no I/O, no DB, no LLM; ids and keys in, an order out. `learning/review.py`
does the two reads (prerequisite edges, open misconceptions) and applies the
order after DASH ordering and the budget cut, so the day's set and budget never
change.

Why only confusable concepts: interleaving helps when the categories mixed are
similar enough to be confused (Brunmair & Richter 2019, Psych Bull 145(11):
g = 0.42 overall, math g = 0.34, larger when between-category similarity is
high) and hurts for unrelated or word material (words g = -0.39). The DASH
queue already mixes unrelated concepts, so the only lever is WHICH concepts sit
next to each other: a confusable pair is put side by side so the student has to
tell them apart (discriminative contrast), and nothing else moves. Flashcards
are definitional, word-like items and are never pulled forward.

Confusable (both signals are structured data the loop already stores; no name
or text matching): two DIFFERENT graph nodes of the SAME course that
  (1) share a prerequisite parent (siblings: coordinate concepts that build on
      the same idea, e.g. the chain/product/quotient rules under "derivative",
      or t-test/chi-square/ANOVA under "hypothesis testing"), or
  (2) carry the same open misconception wrong_key for this student (the same
      diagnosed wrong reason on both, e.g. `confuses_mitosis_with_meiosis`
      recorded on Mitosis and on Meiosis: direct evidence that THIS student
      mixes them up).
Same course only: the audit's recommendation is "within a course"
(docs/research/learning-loop/2026-11-07-direction-audit.md rec. 14), and it
keeps a course-less queue from pairing two courses' same-named concepts.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Collection, Hashable, Mapping, Sequence


def confusable_partners(
    courses: Mapping[str, str | None],
    parents: Mapping[str, Collection[str]],
    wrong_keys: Mapping[str, Collection[str]],
) -> dict[str, frozenset[str]]:
    """{node id: the other nodes it is confusable with} over the nodes in
    `courses` ({node id: its course id}). `parents` holds each node's
    prerequisite parents, `wrong_keys` its open misconception keys; ids outside
    `courses` are ignored. The relation is symmetric and never reflexive; a
    node with no partner is absent."""
    groups: list[set[str]] = []
    for links in (parents, wrong_keys):
        shared: dict[str, set[str]] = {}
        for node, values in links.items():
            if node in courses:
                for value in values:
                    shared.setdefault(value, set()).add(node)
        groups.extend(shared.values())
    partners: dict[str, set[str]] = {}
    for group in groups:
        for node in group:
            for other in group:
                if other != node and courses[other] == courses[node]:
                    partners.setdefault(node, set()).add(other)
    return {node: frozenset(others) for node, others in partners.items()}


def serve_order(
    keys: Sequence[Hashable],
    partners: Mapping[Hashable, Collection[Hashable]],
    *,
    previous: Hashable | None = None,
    lead: Collection[Hashable] | None = None,
) -> list[int]:
    """The order to serve the queue in: a permutation of `range(len(keys))`.

    `keys` is the queue in DASH order, one key per item (the same key = the
    same concept); `previous` is the key of the item graded just before (None
    at the start of a day). One rule per step: next comes the earliest
    remaining item confusable with the item just placed (`previous` for the
    first step); when there is none, the earliest remaining item. One guard
    overrides it: an item never follows one with the same key (nor `previous`)
    while some arrangement of what is left can avoid it — a key holding more
    than half of the remaining items is placed first, so it never runs out of
    separators. The review queue's keys are unique, so there the guard only
    keeps the concept just graded from being served again right away.

    `lead` (spec §13 A140): the keys the first step may pull, in place of
    `partners[previous]` — for a caller whose relation is about ITEMS while
    `partners` is keyed by concept (the item graded just before need not be
    the queue's item of its concept). None: `partners[previous]`, exactly as
    without it. The guard on `previous` holds either way.

    Hence, for unique keys:
      - no item is added, dropped or repeated (the set and the budget hold);
      - an item with no partner in the queue, and not a partner of `previous`,
        is never pulled forward: such items keep their DASH order among
        themselves;
      - with no `previous`, the first item is the DASH head;
      - after an item whose partner is still waiting, that partner comes next.
    Replaying the order one serve at a time (each step's `previous` = the item
    just served, the queue = what is left) yields the same order, so it
    survives the per-request rebuild of the review queue.
    """
    pending = list(range(len(keys)))
    left = Counter(keys)
    order: list[int] = []
    last = previous
    while pending:
        others = [i for i in pending if keys[i] != last] or pending
        crowded = [i for i in others if 2 * left[keys[i]] > len(pending)]
        pool = crowded or others
        if lead is not None and not order:
            near = lead
        else:
            near = partners.get(last, ()) if last is not None else ()
        pick = next((i for i in pool if keys[i] in near), pool[0])
        order.append(pick)
        pending.remove(pick)
        left[keys[pick]] -= 1
        last = keys[pick]
    return order

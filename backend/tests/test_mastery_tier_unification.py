"""#557 (Workstream H5, epic #537): one set of mastery thresholds.

Three divergent sets existed — `config.get_mastery_tier`'s canonical
0.75/0.45/0.1, the tutor's 0.7/0.4, and flashcards' ad-hoc <0.4 — so a
student could read "Struggling" on the Tree and be counted as in-progress by
the tutor in the same session. These tests pin the agreement rather than the
numbers, so the thresholds stay movable in ONE place.
"""
import asyncio
from unittest.mock import patch

import pytest

from config import get_mastery_tier, is_mastered, is_weak


# One value inside every tier plus every boundary, including the ones the old
# tutor thresholds fell between (0.4-0.45 and 0.7-0.75) — the exact band where
# the two vocabularies disagreed.
SCORES = [
    0.0, 0.05, 0.09, 0.1, 0.25, 0.39, 0.4, 0.42, 0.44,
    0.45, 0.5, 0.69, 0.7, 0.72, 0.74, 0.75, 0.8, 1.0,
]


@pytest.mark.parametrize("score", SCORES)
def test_predicates_agree_with_the_tier_they_describe(score):
    tier = get_mastery_tier(score)
    assert is_mastered(score) is (tier == "mastered")
    # "Weak" is everything below the learning floor: struggling AND unexplored.
    assert is_weak(score) is (tier in {"struggling", "unexplored"})


@pytest.mark.parametrize("score", SCORES)
def test_the_tutor_classifies_a_concept_the_same_way_the_tree_labels_it(score):
    """The user-visible invariant, and the whole point of #557: whatever the
    Tree calls a concept, the tutor must count it as the same thing.

    Driven through the real tool rather than through its constants, so
    reintroducing a local threshold anywhere in that path fails here.
    """
    from agents.tools import chat_context

    with patch.object(
        chat_context, "table",
    ) as t:
        t.return_value.select.return_value = [{"mastery_score": score}]
        progress = asyncio.run(
            chat_context.read_user_progress("u1", "c1")
        )

    tier = get_mastery_tier(score)
    assert progress.total_concepts == 1
    assert progress.mastered_count == (1 if tier == "mastered" else 0)
    assert progress.weak_count == (1 if tier in {"struggling", "unexplored"} else 0)
    assert progress.in_progress_count == (1 if tier == "learning" else 0)


def test_no_module_redefines_the_thresholds_locally():
    """#557's actual failure mode was three copies drifting apart, not one
    wrong number. Cite config; don't re-declare."""
    from agents.tools import chat_context

    assert not hasattr(chat_context, "_MASTERED_THRESHOLD")
    assert not hasattr(chat_context, "_WEAK_THRESHOLD")


def test_flashcards_weak_concepts_use_the_shared_floor():
    """Flashcards drilled `< 0.4`, so concepts in [0.4, 0.45) — struggling on
    the Tree — were never offered for practice."""
    from routes import flashcards

    rows = [
        {"concept_name": "just-below-learning", "mastery_score": 0.42},
        {"concept_name": "learning", "mastery_score": 0.5},
    ]
    with patch.object(flashcards, "table") as t:
        t.return_value.select.return_value = rows
        weak = flashcards._get_weak_concepts("u1", "CS101")

    assert weak == ["just-below-learning"]


def test_the_frontend_mirror_matches_the_backend_thresholds():
    """The fourth copy, and the one that cannot import.

    `Learn.tsx::tierForScore` classifies a STREAMED mastery delta client-side
    so the live Tree matches what a full graph refetch would show. It is a
    deliberate cross-language mirror — but a silent one: move a threshold in
    config.py and a node landing in the newly-shifted band paints one tier
    live and a different tier after the next refetch. That is precisely the
    score/label disagreement #557 exists to kill, just across the wire
    instead of across two Python modules.

    So the mirror is pinned here rather than trusted to a comment.
    """
    import re
    from pathlib import Path

    from config import (
        MASTERY_LEARNING_MIN,
        MASTERY_MASTERED_MIN,
        MASTERY_STRUGGLING_MIN,
    )

    src = (
        Path(__file__).resolve().parents[2]
        / "frontend/src/components/screens/Learn.tsx"
    ).read_text()

    body = re.search(
        r"function tierForScore\(score: number\)[^{]*\{(.*?)\n\}", src, re.S
    )
    assert body, "tierForScore moved or was renamed — re-point this guard"

    found = {
        tier: float(value)
        for value, tier in re.findall(
            r'score >= ([0-9.]+)\) return "(\w+)"', body.group(1)
        )
    }
    assert found == {
        "mastered": MASTERY_MASTERED_MIN,
        "learning": MASTERY_LEARNING_MIN,
        "struggling": MASTERY_STRUGGLING_MIN,
    }, (
        "Learn.tsx::tierForScore has drifted from config.py. Update both, or "
        "the live Tree will label a streamed delta differently from the "
        "refetch that follows it."
    )


def test_weak_concepts_are_capped_weakest_first():
    """`_get_weak_concepts` caps at 15. Widening the floor from 0.4 to 0.45
    (#557) admits more rows, so an unsorted cap lets the newly-admitted
    [0.4, 0.45) concepts displace 0.0-0.1 ones on arbitrary PostgREST row
    order — the surface whose job is drilling the WEAKEST concepts drilling
    the least-weak of the weak instead."""
    from unittest.mock import patch as _patch

    from routes import flashcards

    # Deliberately arrives least-weak first, which is what row order can do.
    rows = [{"concept_name": f"c{i}", "mastery_score": 0.44 - i * 0.02} for i in range(20)]
    with _patch.object(flashcards, "table") as t:
        t.return_value.select.return_value = rows
        weak = flashcards._get_weak_concepts("u1", "CS101")

    assert len(weak) == 15
    scores = {r["concept_name"]: r["mastery_score"] for r in rows}
    assert max(scores[c] for c in weak) < min(
        scores[r["concept_name"]] for r in rows if r["concept_name"] not in weak
    ), "the 15 returned must be the 15 weakest, not the first 15 rows"

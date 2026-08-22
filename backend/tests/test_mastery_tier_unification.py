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

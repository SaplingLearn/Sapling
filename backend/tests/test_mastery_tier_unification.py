"""#557 (Workstream H5, epic #537): one set of mastery thresholds.

Three divergent sets existed — the legacy config cuts 0.75/0.45/0.1, the
tutor's 0.7/0.4, and flashcards' ad-hoc <0.4 — so a student could read
"Struggling" on the Tree and be counted as in-progress by the tutor in the
same session. PKG-14b (spec §11.2): the ONE tier function is now
`learning.bkt.tier_for` (TIER_UNEXPLORED_MAX / BAND_NOVICE_MAX / BKT_PROFICIENT
= 0.10 / 0.30 / 0.95 in `learning/params.py`); the config.py copy is deleted.
These tests pin the agreement rather than the numbers, so the thresholds stay
movable in ONE place.
"""
import asyncio
from unittest.mock import patch

import pytest

from learning.bkt import in_mastered_tier, is_weak, tier_for


# One value inside every tier plus every boundary: the old tutor thresholds'
# bands (0.4-0.45 and 0.7-0.75), the retired legacy cuts, and the PKG-14b
# cuts' own boundaries (0.29/0.3, 0.94/0.95).
SCORES = [
    0.0, 0.05, 0.09, 0.1, 0.25, 0.29, 0.3, 0.39, 0.4, 0.42, 0.44,
    0.45, 0.5, 0.69, 0.7, 0.72, 0.74, 0.75, 0.8, 0.94, 0.95, 1.0,
]


@pytest.mark.parametrize("score", SCORES)
def test_predicates_agree_with_the_tier_they_describe(score):
    tier = tier_for(score)
    assert in_mastered_tier(score) is (tier == "mastered")
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

    tier = tier_for(score)
    assert progress.total_concepts == 1
    assert progress.mastered_count == (1 if tier == "mastered" else 0)
    assert progress.weak_count == (1 if tier in {"struggling", "unexplored"} else 0)
    assert progress.in_progress_count == (1 if tier == "learning" else 0)


def test_no_module_redefines_the_thresholds_locally():
    """#557's actual failure mode was three copies drifting apart, not one
    wrong number. Cite learning.bkt; don't re-declare."""
    import config
    from agents.tools import chat_context

    assert not hasattr(chat_context, "_MASTERED_THRESHOLD")
    assert not hasattr(chat_context, "_WEAK_THRESHOLD")
    # PKG-14b: the legacy config copy is gone (spec §11.2).
    for gone in (
        "MASTERY_MASTERED_MIN", "MASTERY_LEARNING_MIN", "MASTERY_STRUGGLING_MIN",
        "is_mastered", "is_weak",
    ):  # the legacy tier function's own name is inv_21's (test_learning_loop_invariants)
        assert not hasattr(config, gone), gone


def test_flashcards_weak_concepts_use_the_shared_floor():
    """Flashcards drilled `< 0.4`, so concepts struggling on the Tree were
    never offered for practice. PKG-14b: the floor is BAND_NOVICE_MAX (0.30)."""
    from routes import flashcards

    rows = [
        {"concept_name": "just-below-learning", "mastery_score": 0.29},
        {"concept_name": "learning", "mastery_score": 0.3},
    ]
    with patch.object(flashcards, "table") as t:
        t.return_value.select.return_value = rows
        weak = flashcards._get_weak_concepts("u1", "CS101")

    assert weak == ["just-below-learning"]


_REPO = __import__("pathlib").Path(__file__).resolve().parents[2]
#: The three frontend copies of the one tier function (PKG-14b, spec §11.2):
#: (file, function name). Each is parsed with the same regex and compared to
#: learning.params, so the graph and the Learn screen never disagree.
FRONTEND_TIER_MIRRORS = (
    ("frontend/src/components/screens/Learn.tsx", "tierForScore"),
    ("frontend/src/lib/graph/nodeStyle.ts", "tierFor"),
    ("frontend/e2e/graph.spec.ts", "tierFor"),
)


@pytest.mark.parametrize("rel,fn", FRONTEND_TIER_MIRRORS, ids=[f for f, _ in FRONTEND_TIER_MIRRORS])
def test_the_frontend_mirror_matches_the_backend_thresholds(rel, fn):
    """The copies that cannot import.

    `Learn.tsx::tierForScore` classifies a STREAMED mastery delta client-side
    so the live Tree matches what a full graph refetch would show;
    `nodeStyle.ts::tierFor` labels a quiz result's `mastery_after`;
    `e2e/graph.spec.ts::tierFor` is the E2E judge. They are deliberate
    cross-language mirrors — but silent ones: move a threshold in
    learning/params.py and a node landing in the shifted band paints one tier
    live and a different tier after the next refetch. So each is pinned here
    rather than trusted to a comment.
    """
    import re

    from learning.params import BAND_NOVICE_MAX, BKT_PROFICIENT, TIER_UNEXPLORED_MAX

    src = (_REPO / rel).read_text()
    body = re.search(
        rf"function {fn}\(score: number\)[^{{]*\{{(.*?)\n\}}", src, re.S
    )
    assert body, f"{rel}::{fn} moved or was renamed — re-point this guard"

    found = {
        tier: float(value)
        for value, tier in re.findall(
            r'score >= ([0-9.]+)\) return "(\w+)"', body.group(1)
        )
    }
    assert found == {
        "mastered": BKT_PROFICIENT,
        "learning": BAND_NOVICE_MAX,
        "struggling": TIER_UNEXPLORED_MAX,
    }, (
        f"{rel}::{fn} has drifted from learning/params.py. Update both, or "
        "the live Tree will label a streamed delta differently from the "
        "refetch that follows it."
    )


def test_weak_concepts_are_capped_weakest_first():
    """`_get_weak_concepts` caps at 15. An unsorted cap lets the least-weak
    concepts displace 0.0-0.1 ones on arbitrary PostgREST row order — the
    surface whose job is drilling the WEAKEST concepts drilling the
    least-weak of the weak instead. (PKG-14b: rows sit under the 0.30 floor.)"""
    from unittest.mock import patch as _patch

    from routes import flashcards

    # Deliberately arrives least-weak first, which is what row order can do.
    rows = [{"concept_name": f"c{i}", "mastery_score": 0.29 - i * 0.01} for i in range(20)]
    with _patch.object(flashcards, "table") as t:
        t.return_value.select.return_value = rows
        weak = flashcards._get_weak_concepts("u1", "CS101")

    assert len(weak) == 15
    scores = {r["concept_name"]: r["mastery_score"] for r in rows}
    assert max(scores[c] for c in weak) < min(
        scores[r["concept_name"]] for r in rows if r["concept_name"] not in weak
    ), "the 15 returned must be the 15 weakest, not the first 15 rows"

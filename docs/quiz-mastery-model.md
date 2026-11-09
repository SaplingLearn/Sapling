# Quiz mastery model — options for the revamp

**Status:** open question, deliberately undecided. #543 landed the seam
(`services/quiz_config.py::mastery_after` + the two named constants) with the
numbers **unchanged**; the #537 revamp decides the model.

## What ships today

```
after = clamp01(before + correct × 0.03 − wrong × 0.02)
```

Flat, per-item, difficulty-blind, length-blind. Earning is faster than losing
(0.03 vs 0.02), so a mostly-succeeding student trends upward and a bad quiz
dents progress without erasing it. From 0, about 17 consecutive correct answers
reach mastered (`mastery_tier` thresholds live in `config.py::get_mastery_tier`)
— roughly three or four full quizzes.

## What's hard to defend

1. **Length dominates.** A 10-question quiz moves mastery 3.3× as much as a
   3-question one, purely because it has more items. A student can farm mastery
   by always picking the longest quiz.
2. **Difficulty is free.** A correct *hard* answer and a correct *easy* answer
   move the score identically, even though the quiz agent deliberately varies
   difficulty by mastery (`agents/quiz.py` adaptive rules). The signal the agent
   works to produce is discarded at scoring time.
3. **Adaptive mode is unpriced.** Since #540 the agent may choose the mix
   itself; "adaptive" quizzes have no defined difficulty for scoring purposes.

## Options

**A. Keep flat per-item (status quo).** Simplest, already shipped, and the only
option that needs no journey change. Accepts the length and difficulty issues.

**B. Normalize by quiz length.** `delta = (accuracy − passing_threshold) × step`,
so a quiz is worth a fixed amount regardless of item count. Removes the
farm-by-length incentive; makes a 3-question quiz as consequential as a 10, which
may over-weight small samples.

**C. Weight per item by difficulty.** e.g. easy ×0.6, medium ×1.0, hard ×1.5 on
both the credit and the penalty. Uses the agent's difficulty signal; needs a
defined weight for items generated in adaptive mode (the per-question difficulty
is concrete even there, so this is workable).

**D. B + C combined.** Length-normalized and difficulty-weighted. Most defensible
pedagogically, most disruptive to existing numbers, and the hardest to explain in
a UI ("why did I only gain 0.02?").

**E. Replace the linear model.** Something with diminishing returns near the
ceiling (mastery is harder to gain at 0.9 than at 0.3) — e.g. move a fraction of
the remaining distance. Realistic, but no longer readable as "+0.03 per right
answer" in the results screen.

## Constraint on whoever decides

The `#393` journey in `frontend/e2e/quiz.spec.ts` pins **+0.09** for a 3-of-3
quiz (3 × 0.03), asserted
three ways: the UI's before→after, `graph_nodes.mastery_score`, and the
`node_mastery_events.delta` sign. Any change to the model **must** update that
journey in the same commit, with a comment saying why — see the working
agreement in the #537 batch brief. `backend/tests/test_quiz_scoring_e.py`
also pins the constants; that's the tripwire, not an obstacle.

# W7 meta chips — Returning + exam-distance

**Status:** formula locked for W7.1 meta row (2026-11-24)  
**Closes:** port-map hard rule #3 / plan W7 open question on Returning / exam-distance pips.

## Inputs (already on the graph node)

| Field | Source |
|---|---|
| `times_studied` | `GraphNode.times_studied` |
| `last_studied_at` | `GraphNode.last_studied_at` (ISO or null) |
| `mastery_tier` | `GraphNode.mastery_tier` |
| `mastery_score` | `GraphNode.mastery_score` ∈ [0, 1] |

No FSRS due timestamp is required for this slice. If a future due field lands on the quiz concept summary, prefer it for pips and keep this tier/score fallback.

## Returning

**On** when the student has studied this concept before:

```text
times_studied >= 1  OR  last_studied_at != null
```

Shown as a quiet chip: `Returning`. Off for first-touch / unexplored with zero studies.

## Exam-distance pips (1…5)

Design kit `dist` = how far the concept sits from exam-ready (**1 = nearest**, **5 = farthest**).

| Condition | Pips |
|---|---|
| `mastery_tier === "mastered"` | 1 |
| `mastery_tier === "learning"` and `mastery_score >= 0.55` | 2 |
| `mastery_tier === "learning"` | 3 |
| `mastery_tier === "struggling"` | 4 |
| anything else (`unexplored`, hub, missing) | 5 |

UI: five pips; filled count = `6 - pips` so nearer concepts show more filled dots (exam-ready fills the bar).

## Explicit non-goals

- Skill / Bloom chip (Analyze / Apply…) — no field on the summary yet; tier chip stays.
- Live XP wager stakes — A132 confidence only (W7.D1 / W7.4).
- Mastery writes from these chips — display only.

## Code

- Pure: `frontend/src/lib/quiz/metaChips.ts`
- Wire: `QuizConceptSummary` + `QuestionHeader` in `QuizQuestion.tsx`; `QuizScreen` fills study fields from the active node.

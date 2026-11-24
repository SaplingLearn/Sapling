# W7.5 — Quiz focus Hint (scaffold slice)

**Status:** landed (client scaffolding; Bastani ladder deferred)  
**Branch:** `feat/learning-loop-reland`  
**Code:** `frontend/src/components/quiz/question/questionView.ts` (`scaffoldHint` / `hintSlotState`), `QuizQuestion.tsx`

## Choice

**Option (b)** — client-side Hint that only re-surfaces scaffolding already on the question. No new LLM call.

**Option (a) refused:** wire Hint to loop `POST /hint` + `[ACTION: hint]` turn. That API is leak-checked (Bastani / `detect_leak`) but it requires a **learning-loop session** and the `learning_loop` flag. The quiz focus shell is a **quiz attempt**, not a loop session. Bridging them would enable loop flags or invent a quiz↔loop session seam — out of scope for this unblock, and forbidden while flags stay off.

## What Hint shows

| Line | Source | Leak risk |
|---|---|---|
| Focus concept | `concept.name` / wire `concept_tested` (already on meta) | None — identity only |
| Rubric / format rules | `formatHint` (already under written / Sort fields) | None — grader acceptance, not the key |
| Fixed note + Study guide CTA | Static copy → existing leak-safe drawer | Drawer never fetches guide detail / keys |

No stem paraphrase, no option highlighting, no explanation, no Ask seed (`askSeedFor` includes the correct answer — post-check only).

## Exam Twin

Hint is **disabled** in Exam Twin (same tool-light rule as Ask / W7.8).

## Deferred (full Bastani Hint)

A true H1–H6 ladder Hint on quiz needs either:

1. a quiz-scoped, leak-checked hint endpoint that never sees the answer key before H6, or  
2. a deliberate product decision that Practice quiz may open a loop session mid-attempt (flag on, session mint, help ledger).

Until then, the slot stays useful via scaffolding and points students at Study guide / post-check Ask.

## Tests

- `questionView.test.ts` — `scaffoldHint` / `hintSlotState` (Practice on, Exam Twin off, busy/locked)
- `QuizQuestion.slots.test.tsx` — Hint opens panel; no answer text; Exam Twin disabled

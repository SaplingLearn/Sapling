# W7.5 — Quiz focus Hint (scaffold ladder)

**Status:** landed (client Bastani-lite H0–H2; loop `/hint` still deferred)  
**Branch:** `feat/learning-loop-reland`  
**Code:** `questionView.ts` (`scaffoldHint` / `hintLadder` / `hintSlotState`), `QuizQuestion.tsx` `HintPanel`

## Choice

**Option (b)** — client-side Hint that only re-surfaces scaffolding already on the question. No new LLM call.

**Option (a) refused:** wire Hint to loop `POST /hint` + `[ACTION: hint]` turn. That API is leak-checked (Bastani / `detect_leak`) but it requires a **learning-loop session** and the `learning_loop` flag. The quiz focus shell is a **quiz attempt**, not a loop session. Bridging them would enable loop flags or invent a quiz↔loop session seam — out of scope, and forbidden while flags stay off.

## Bastani-lite ladder (client)

| Rung | Content | Source |
|---|---|---|
| H0 | Focus concept | `concept.name` / `concept_tested` |
| H1 | How to answer (when present) | `formatHint` / kit rubric |
| H2 | Fixed note | Static — never the answer |

Each **More help** reveals one rung. **Open Study guide** stays available (leak-safe drawer). No stem paraphrase, option highlighting, explanation, or Ask seed.

## Exam Twin

Hint is **disabled** in Exam Twin (same tool-light rule as Ask / W7.8).

## Deferred (full Bastani Hint)

A true H1–H6 ladder on quiz needs either a quiz-scoped leak-checked hint endpoint, or a deliberate Practice→loop session bridge (flag on). Until then: scaffolding + Study guide + post-check Ask.

## Tests

- `questionView.test.ts` — `scaffoldHint` / `hintLadder` / `hintSlotState`
- `QuizQuestion.slots.test.tsx` — ladder climb; no answer text; Exam Twin disabled

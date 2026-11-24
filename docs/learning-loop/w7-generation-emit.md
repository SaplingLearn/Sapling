# W7 generation emit — kit `interaction` on the wire

**Status:** planned Sort emit landed (2026-11-24) — sanitize + attach; plain quiz schema untouched  
**Closes:** port-map “Later: Generation emits `interaction`” (partial → planned Sort)

## Goal

Quiz generation may attach a kit `interaction` object on a `short_answer` wire question so the focus shell mounts Sort / Label / … / Connect instead of a plain written field. Grading stays the short-answer string path (`correct_answer` / `accepted_answers`); the client encode must match that key.

## Contract

| Rule | Detail |
|---|---|
| Wire type | Only `short_answer` (numeric/symbolic stay plain) |
| Shape | Same client types as `frontend/src/lib/quiz/types.ts` (`kind` + kind fields) |
| Sanitize | Server drops unknown / incomplete payloads — never 502s the quiz |
| Belief | Kit UI does not invent mastery channels; submit still uses written evidence |
| Plain quiz schema | **No** `interaction` on `agents/quiz.QuizQuestion` — flag-off request digests stay byte-identical |
| Planned writer | The kit rides the QUIZ, not the question: `PlannedQuiz.kit_slot` (0 = none) + `PlannedQuiz.kit` (the kit as one JSON-object string), parsed by `PlannedQuiz.kit_for` (fail closed). A nested optional `interaction` object on `PlannedQuestion` broke the output-schema budget (9 properties, `Sub \| None`, depth 3 — `tests/test_agent_output_schemas.py`, `agents/__init__.py`) and a free-form object is not a Claude strict-mode schema. Prompt may emit any sanitized kit kind (≤1 kit item per quiz) when `quiz_planned_questions` is on |
| Function E2E | Default MC/written unchanged. Planned `FORMAT: short_answer` in function mode appends `KIT: sort` → first written slot is `kit_slot` with the Sort kit + `[e2e-kit-sort]`; quiz_check solve returns `E2E_KIT_SORT_ANSWER`. Playwright: `frontend/e2e/quiz-kit.spec.ts` |

## Code

| Piece | Path |
|---|---|
| Sanitize / attach | `services/quiz/interaction.py` |
| Planned field + kit prompt (all sanitized kinds) | `agents/quiz_planned.py` |
| Stamp → wire | `generation._absorb` → `quiz_planned.planned_kit` → `quiz_learning.planned_question(kit=)` → `attach_interaction` |
| Kinds sanitized | All twelve stubs: `sort`…`rank` + `connect` (match / map) |

## Next

1. Richer per-criterion grading (still deferred).

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
| Planned writer | Optional `PlannedQuestion.interaction`; prompt may emit any sanitized kit kind (≤1 kit item per quiz) when `quiz_planned_questions` is on |
| Function E2E | Default / planned handlers stay MC/written fixtures (no Sort) so existing journeys keep clicking |

## Code

| Piece | Path |
|---|---|
| Sanitize / attach | `services/quiz/interaction.py` |
| Planned field + kit prompt (all sanitized kinds) | `agents/quiz_planned.py` |
| Stamp → wire | `quiz_learning.planned_question` → `generation._absorb` → `attach_interaction` |
| Kinds sanitized | All twelve stubs: `sort`…`rank` + `connect` (match / map) |

## Next

1. Dedicated function-mode kit journey (fixtures).  
2. Richer per-criterion grading (still deferred).

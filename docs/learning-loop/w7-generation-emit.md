# W7 generation emit — kit `interaction` on the wire

**Status:** first slice landed (2026-11-24) — sanitize + wire attach; agent prompt still silent  
**Closes:** port-map “Later: Generation emits `interaction`” (partial)

## Goal

Quiz generation may attach a kit `interaction` object on a `short_answer` wire question so the focus shell mounts Sort / Label / … / Connect instead of a plain written field. Grading stays the short-answer string path (`correct_answer` / `accepted_answers`); the client encode must match that key.

## Contract

| Rule | Detail |
|---|---|
| Wire type | Only `short_answer` (numeric/symbolic stay plain) |
| Shape | Same client types as `frontend/src/lib/quiz/types.ts` (`kind` + kind fields) |
| Sanitize | Server drops unknown / incomplete payloads — never 502s the quiz |
| Belief | Kit UI does not invent mastery channels; submit still uses written evidence |
| Prompt | **Not yet** asking the model for `interaction` (Gemini schema budget; rollout later) |
| Function E2E | Default quiz handler stays MC-only so `quiz.spec.ts` keeps clicking A/B/C |

## Code

| Piece | Path |
|---|---|
| Sanitize | `backend/services/quiz/interaction.py::sanitize_interaction` |
| Attach | `wire._agent_question_to_wire` copies a sanitized dict onto the wire item |
| Agent field | Optional `QuizQuestion.interaction: dict \| None` (flat; omitted by default) |
| First kinds | `sort` (+ `connect` match / map). Other kit kinds follow the same helper. |

## Next

1. Prompt + planned writer: emit Sort (then Label…) when format dial / fixtures ask.  
2. Function-mode fixture behind a dedicated journey (not the default three-MC quiz).  
3. Richer per-criterion grading (still deferred).

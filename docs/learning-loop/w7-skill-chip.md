# W7 Bloom skill chip

**Status:** formula locked (2026-11-24)  
**Display only** — never mastery.

## Inputs

| Field | Source |
|---|---|
| `interaction.kind` | Wire kit payload when present |
| `type` | Wire question type |
| `difficulty` | Wire difficulty |

## Labels (Bloom-ish)

| Chip | When |
|---|---|
| Remember | `short_answer` / MC with `easy` and no kit |
| Understand | MC `medium`/`hard`, or plain `short_answer` medium+ |
| Apply | `numeric`, `symbolic`, `calculate`, `position` |
| Analyze | `compare`, `highlight`, `connect` |
| Evaluate | `rank`, `explain` |
| Create | `build`, `sequence`, `dialogue`, `sort`, `label` |

Kit kind wins over type. Missing everything → no chip (tier still shows).

## Code

`frontend/src/lib/quiz/skillChip.ts` → `QuestionHeader` `quiz-skill-chip`.

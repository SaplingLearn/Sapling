# Learning Loop — series ledger (append-only)

Rules: read this file first; refuse to start if any earlier package is `blocked` or `in-progress`. A package marks itself `done`; only the next package that depends on it marks it `verified` after running its State-of-the-world rows. Never rewrite an earlier row — a change of state is a new row. Status enum: `planned | in-progress | done | verified | blocked | reopened`.

| pkg | slug | status | branch | head SHA | tests added | verified-by (pkg, date, command → output) | handoff |
|---|---|---|---|---|---|---|---|
| 00 | foundation | planned | | | | | |
| 01 | bkt-core | planned | | | | | |
| 02 | fsrs-core | planned | | | | | |
| 03 | evidence-state | planned | | | | | |
| 04 | check-items | planned | | | | | |
| 05 | grader-check-tool | planned | | | | | |
| 06 | zpd-policy | planned | | | | | |
| 07 | loop-tutor | planned | | | | | |
| 08 | probe-planner | planned | | | | | |
| 09 | close-brief | planned | | | | | |
| 10 | misconceptions | planned | | | | | |
| 11 | quiz-flashcards | planned | | | | | |
| 12 | review-surfaces | planned | | | | | |
| 13 | frontend-e2e | planned | | | | | |
| 14 | eval-ladder-cutover | planned | | | | | |

## Deviations

Format: `PKG-NN: <spec said> → <did instead> → <why> → <† if an A/B flag stays open>`

(none yet)

## Blocked notes

Format: `PKG-NN <date>: hypothesis · commands run · outputs · what the next human should decide`

(none yet)

# ADR 0032: Separate learning judgments from tutor observation

Status: Implemented on the learning-loop branch; deployment is a separate decision.

## Context

Main's typed decision API and the learning-loop branch independently introduced
`services/decisions.py` and `agents/decision.py`. They have incompatible contracts.
The main API answers generic YesNo/Choice/Score questions for an observe-only tutor
router. The learning API judges check-item answerability, wrong reasons and answer
leaks, and coordinates grading. Replacing either implementation with the other
breaks existing callers and can change student-facing behavior.

## Decision

Keep main's `services/decisions.py`, `agents/decision.py` and `decision` model task.
The router continues to observe persisted turns without controlling tutor output.
Its failures must not fail a completed student response.

Move the learning contract to `services/learning_decisions.py`, backed by
`agents/learning_decision.py` and the `learning_decision` model task. Existing
learning backend selection, privacy controls, grading safeguards and Jev SDK
behavior stay with that contract. Learning callers and replay evaluations import
the learning-specific modules explicitly.

Both tasks record usage. Only `learning_decision`, together with the actual
grader tasks, counts toward the student's graded-answer allowance. Observe-only
`decision` calls still contribute to monetary usage, but are not graded answers.
Function-mode fixtures register both task names with their respective schemas.
Shutdown drains the learning shadow tasks and main's observer tasks and closes
both clients.

## Consequences

The code has two deliberately distinct APIs rather than one overloaded name.
Historical learning design documents that mention `services/decisions.py` describe
the contract now implemented by `services/learning_decisions.py`; main's ADR 0027
continues to describe the generic API. The two existing ADRs numbered 0027 are
historical and are not renumbered here.

This change establishes integration compatibility. It does not validate a model's
grading accuracy or demonstrate improved human learning outcomes.

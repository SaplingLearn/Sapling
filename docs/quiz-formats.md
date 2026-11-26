# MVP1 quiz formats

The quiz settings offer multiple choice, short answers, numeric answers,
algebra, and a subject-appropriate mixed mode. Existing clients and saved
multiple-choice attempts remain supported. The default remains multiple choice.

Short answers are precise terms or brief factual responses, including
fill-in-the-blank questions. Grading ignores capitalization and whitespace,
and accepts the canonical answer or an explicitly generated alternative.
It does not grade essays or infer semantic similarity.

Numeric answers accept exact equivalent fractions, decimals, percentages,
and scientific notation. The question specifies units and any rounding;
the response is a number, without units. There is no implicit rounding tolerance.

Algebra supports rational expressions with single-letter variables,
parentheses, implicit multiplication, and `+ - * / ^`. Integer powers range
from -8 to 8. Equivalence is exact wherever both expressions are defined.
Functions, equations, roots, and non-integer powers are unsupported. Parsing
is bounded and never executes student input or invokes an external evaluator.

Mixed-mode generation is instructed to use math only when the course material
supports it. Non-mathematical courses use short answers and multiple choice.
The existing course-scoped retrieval feeds every format. The question's context
label reports whether retrieved course material, catalog context, or general
concept practice was supplied; it is not a claim that a particular document
passage was cited or verified.

## API and storage

`POST /api/quiz/generate` accepts `question_format`:
`multiple_choice | short_answer | numeric | symbolic | mixed`.
Each returned question has a concrete type; missing types on older attempts
mean multiple choice. Written questions have empty `options`.
Canonical answers and accepted alternatives remain server-side until feedback.

`POST /api/quiz/attempts/{id}/answer` accepts exactly one of `selected_index`
or `answer_text` (nonblank, at most 2,000 characters). The first recorded
answer wins on retries. Written responses are encrypted JSON in
`quiz_responses.answer_text`, with `selected_index` null. Resume decrypts
only the signed-in student's own responses. Final submission grades the
recorded answers and uses the existing mastery, history, and XP paths.

## Evidence policy

All quiz formats retain the existing conservative `mc` evidence likelihood
bucket. Written input graded against a deterministic answer key is not promoted
to strong `free_response` or `mc_reasoned` evidence: those channels require
rubric/reference-grounded grading or a reason, respectively. The recorded grade
still uses the same help-ledger floor and rolling 24-hour question replay guard
as multiple choice. Quiz responses do not acquire learning-check planning
provenance merely because they are typed.

## Deployment and verification

Apply `backend/db/migrations/20261018010000_quiz_written_responses.sql`
through the normal migration runner **before deploying the updated backend**.
Deploy the frontend after the backend. No new package or service is required.

The new browser journey is `frontend/e2e/quiz-written.spec.ts`. Run it against
the migrated, seeded function-mode stack, along with the existing quiz journeys.
The matching deterministic handler is covered in
`backend/tests/test_e2e_function_handlers.py`.

Before deployment signoff, also run the live-provider quiz evaluation/smoke
checks: deterministic tests validate the expanded agent schema locally but
cannot establish provider schema acceptance or generation quality. The local
work session did not have the database/backend browser-test stack available.

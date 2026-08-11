# Tutor grounding and practical quizzes

Date: 2026-08-11
Status: implemented (PR #534, stacked on #533)
Scope: `agents/tools/chat_context.py`, `agents/chat_tutor.py`, `agents/quiz.py`

Three changes that share a cause: the tutor talked *about* the course instead
of teaching, and quizzes tested vocabulary instead of skill.

## 1. `search_course_materials` had never worked

`chat_context.py` filtered `documents.course_id`. **That column does not exist
on any environment** — `documents` keys on `offering_id`; the abstract course
lives one level up (CLAUDE.md: "study/analytics key on `offering_id`").

Every call answered `400 Bad Request`. The tool is written to "degrade
silently to `[]`", so the model saw an empty result and concluded the course
had no such material — then said so to the student:

> I'm sorry, but I couldn't find any information about Markov chains in the
> course materials. Let's focus on the main topics of this course.

That screenshot came from the tutor with PR #533's prompt fix already applied,
which is how we learned the two triggers are independent: #533 addressed the
*catalog block*, this addresses the *tool*.

Two things kept it hidden:

- the silent degradation swallowed the 400 — a logged exception nobody read;
- the evals inject a fixture retrieval seam (ADR 0023) and never issue the
  real query, so the suite could not have caught it.

**Fix.** Resolve offerings via `services/academics.user_offering_ids_for_course`
and filter `offering_id=in.(…)` — the idiom `routes/flashcards.py:141` already
used — plus the `deleted_at` filter the old query omitted, so soft-deleted
documents stop resurfacing in tutor context.

The regression test pins the query by column name, so a schema rename breaks a
test instead of silently disabling the tool again.

## 2. An empty lookup is not information about the course

Even with the query repaired, a course with no uploads returns `[]`, and the
model narrates emptiness as a fact about scope. Emptiness means only that
nothing is indexed — most courses have no uploaded documents at all.

**Fix, in two places.**

`search_course_materials_tool` now returns `CourseMaterialsResult`
(`materials` + `guidance`) rather than a bare list, so an empty lookup arrives
carrying an explicit instruction not to mention it. A rule at the point of the
empty result lands where one thousands of characters earlier in the preamble
does not — which is exactly what the Lite tier demonstrated.

The preamble gains the matching rule: course *information* (instructor,
prerequisites, credits, coverage) is surfaced ONLY when the student asks about
the course itself. Never an opener, never a qualifier.

The rule is deliberately two-sided. Over-correcting into a tutor that refuses
to discuss its own course would be the same failure wearing the opposite mask,
so a test pins that "prerequisites" and "instructor" still count as legitimate
questions.

## 3. Quizzes should be practical

A quiz on Markov chains should mostly ask you to *compute something about a
given chain*; one on eigenvalues should hand you a matrix. It was asking
"what IS a Markov chain?".

**Fix.** Prompt-only. `QuizQuestion`'s own comments record that Gemini's
constrained decoding blew past "too many states for serving" on the Lite tier,
so the schema stays MCQ-only and narrow — a question-kind enum would cost the
cheap models. A worked problem is still four candidate results.

Rule: for quantitative concepts, at least `ceil(2N/3)` of N questions must pose
concrete values and require computation; the remainder stays conceptual.
Distractors must be the answers a student actually reaches by making a specific
mistake — a sign slip, a transposed matrix, an unnormalised vector — never
arbitrary padding. Non-quantitative subjects get applied analysis over recall.

### Placement was the hard part

Stated once as a section near the end of the prompt, the rule was measurably
ignored. Three live 6-question runs on Eigenvalues + Markov Chains, against a
bar of 4 worked problems:

| prompt | worked problems |
|---|---|
| rule stated late | 2 / 6 |
| hoisted before the tool workflow | 3 / 6 |
| + restated as a FINAL CHECK | **5 / 6** |

Models weight first and last instructions most heavily, so the rule claims both
slots. This is the same failure mode as #533's preamble: a correct instruction
buried mid-prompt loses to the instructions around it. Worth remembering as a
general property of this codebase's long system prompts.

## Verification

Deterministic tests cover the query shape, the guidance payload, the preamble
rules, and the quiz prompt. They prove the text changed — not that the model
complies, which is why each change was also checked live:

- tutor, socratic and expository, on a geometric-algorithms course: teaches
  Markov chains, zero course commentary;
- quiz: 5/6 worked problems with verified arithmetic (trace 5 / det 6 → 2,3;
  det = 1·(−2)·3 = −6; `[0.5,0.5]P = [0.55,0.45]`; `πP = π → [1/3,2/3]`) and
  distractors that are real error-results.

## Known limits

- Quiz compliance is high but not guaranteed — it is prompt-enforced, not
  schema-enforced. If it regresses, the next step is a deterministic
  post-generation count in `routes/quiz.py` with a single revision pass,
  which trades latency for a hard guarantee.
- Nothing gates `search_course_materials` *usage* in CI, so a future drop to
  zero calls would again be invisible. See the drift finding in #533.

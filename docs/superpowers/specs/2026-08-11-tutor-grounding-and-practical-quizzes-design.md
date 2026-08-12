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

## 4. The counts were never honoured (2026-08-12)

Reported as "why did it generate 9 questions when I asked for 10". Two
independent causes, plus a third bug sitting behind them.

**The model simply returns fewer than N.** `num_questions` reached the
agent only as prose in the routing message, and `Quiz.questions` allowed
1..10, so a short list was a perfectly valid output. Reproduced against
the real course concept: one run returned **6 of 10**. Nothing logged,
because nothing was wrong as far as the types were concerned.

**A retyping slip threw a question away.** `_agent_question_to_wire`
required `correct_answer` to appear in `options` verbatim and dropped the
question otherwise — right instinct, since mis-marking an answer is worse
than a short quiz, but it fired on cosmetic drift. Observed: an option
reading "…depends only on the current state, not on the sequence of
events…" came back as "…not on **the on the** sequence of events…". One
stuttered word, whole question gone.

**"15 questions" could never have worked.** `QuizPanel`'s picker offers
5 / 10 / 15; `GenerateQuizBody` bounded `num_questions` to `le=10`, so
picking 15 was an unconditional 422 before any of this was reached.

### Fixes

`resolve_correct_index` (moved to `agents/quiz.py`, shared with the route)
resolves the answer in three passes — verbatim, normalized, then a
near-miss requiring both ≥0.90 similarity and a ≥0.10 margin over the
runner-up. Ambiguity still drops: when the model computed
`vP = [0.25, 0.75]` for a question offering `[0.55,0.45]` / `[0.45,0.55]`
/ `[0.7,0.3]` / `[0.6,0.4]`, no answer is recoverable and guessing would
be worse than dropping.

The count, the answerability, and the ratio are now **output validators**
on `quiz_agent`, reading `num_questions` off `SaplingDeps`. Each raises
`ModelRetry` naming exactly what to fix. This is the same lesson as §3 one
notch further along: placement got the ratio from 2/6 to 5/6, but the
tighter bar this section introduces needed enforcement, not wording.

The array bound is **gone**, not raised. `max_length=15` puts
gemini-2.5-flash-lite back over "too many states for serving" (verified,
400 INVALID_ARGUMENT) because a *bounded* array needs a counting
automaton; an unbounded one is a plain repeat and costs less than the
`max_length=10` it replaces. The floor a schema can't express — "at least
N" — is exactly what the validator does express.

### The ratio is now counted, not requested

The user asked for 4/5, 9/10, 13/15. Restating that in the prompt, at
both the first and last position, was measured at **7 worked problems of
10, twice running** — worse than the looser `ceil(2N/3)` bar it replaced.

So `QuizQuestion` gained `kind: "worked_problem" | "conceptual"`,
self-declared, and `_enforce_worked_ratio` counts it. The field is
**defaulted**, not required: every cassette in
`tests/evals/cassettes/quiz_generation/` predates it and must still
validate on replay. The default is `"conceptual"` so that an omission can
only ever trigger a retry, never pass a definitional quiz off as
practical.

Live, after: **10/10 worked at N=10, 14/15 at N=15, 5/5 at N=5.**

### Gates degrade instead of failing

A 15-question run tripped gate after gate and exhausted the retry budget,
raising `UnexpectedModelBehavior` — a 502, i.e. no quiz at all rather than
a quiz with two definitions in it. `_on_final_attempt` reads `ctx.retry`
against `ctx.max_retries`, and on the last attempt every gate accepts what
it has and logs the shortfall. `output_retries` went 2 → 3 to give three
gates room to fire in sequence.

## Known limits

- The ratio is enforced against a label the model assigns itself. It can
  mislabel a definition as a worked problem, and no check would notice.
  The next rung is a heuristic cross-check (does the stem carry concrete
  values?), deliberately not built yet — it misfires on symbolic problems
  like `P = [[p, 1-p], [q, 1-q]]`, which are worked problems with no
  digits in them.
- A generation can still fail outright on a transient provider error
  (seen once at N=5, clean on rerun); the route degrades to 502 as before.
- Nothing gates `search_course_materials` *usage* in CI, so a future drop to
  zero calls would again be invisible. See the drift finding in #533.

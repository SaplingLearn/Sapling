# Tutor grounding and practical quizzes

Date: 2026-08-11
Status: implemented (PR #534, stacked on #533)
Scope: `agents/tools/chat_context.py`, `agents/chat_tutor.py`, `agents/quiz.py`,
`routes/quiz.py`, `models/__init__.py`, `frontend/src/components/QuizPanel.tsx`

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

Rule: for quantitative concepts, NEARLY EVERY question must pose concrete
values and require computation — at most one may be purely conceptual (two
above N=10). That allowance is what `conceptual_allowance` encodes, and it
replaced an earlier `ceil(2N/3)` fraction: "at most one definition question"
is a rule the model can hold in mind, where "at least `ceil(2N/3)`" was
arithmetic it quietly got wrong. Distractors must be the answers a student
actually reaches by making a specific mistake — a sign slip, a transposed
matrix, an unnormalised vector — never arbitrary padding. Non-quantitative
subjects get applied analysis over recall.

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

**"15 questions" could never have worked.** `QuizPanel`'s picker offered
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

`num_questions` now reaches the agent as *data* on `SaplingDeps`, read by a
**single output validator**, `_select_requested_quiz`, which turns whatever the
model produced into the quiz that was asked for. It selects. **It must not
raise.**

### Selection, not negotiation

The first version of this made the count, the answerability and the ratio three
separate validators, each raising `ModelRetry` and naming what to fix. Every one
of them was measured causing the failure it meant to prevent, because a raise
re-runs the WHOLE generation against `ORCHESTRATOR_LIMITS` (8 model requests,
100k tokens):

- raising on a bad ratio took a 10-question request from ~18s to 43s — 361s in
  one case — and still served 5 conceptual questions;
- raising on a shortfall was worse. flash-lite intermittently returns almost
  nothing (one sampled run: a single usable question) and re-asking produced the
  same, so the run died as `UnexpectedModelBehavior: Exceeded maximum output
  retries (2)` and the route turned it into a 502. One request in five.

A short or slightly definitional quiz is a bad quiz. An exception is no quiz at
all, after two minutes of waiting.

So the ratio is bought with **over-generation** instead — the lever the retry
design listed as "not built", which turns out to cost a fraction of one extra
generation where persuasion cost whole ones:

- `quiz_ask_size(wanted)` asks the model for `min(wanted + 2, 10)`;
- `select_quiz_questions(questions, wanted)` then drops questions whose
  `correct_answer` identifies no option, RESERVES `conceptual_allowance(wanted)`
  slots for conceptual questions (the ask was "9 worked problems *and* one
  conceptual question", so the allowance is a place setting, not merely a
  ceiling), fills the rest with worked problems in the model's own order, and
  backfills from the leftover conceptual questions rather than serve a short
  quiz;
- it restores the model's original ordering, or the grouping above would
  front-load every worked problem and park the definition last;
- it returns human-readable notes, which the validator logs, so each compromise
  is visible rather than silent.

pydantic-ai's own schema retries still cover genuinely malformed output, which
is the one case a retry does fix.

### The array bound stays at 10 — and so does the picker

Removing `max_length` was tried, on the theory that an *unbounded* array is a
plain repeat where a bounded one needs a counting automaton, so dropping the
bound would allow 15 questions without the "too many states for serving" 400.
Measured, it was worse than the 400 it avoided: gemini-2.5-flash-lite answered
roughly half of all generations with an empty `finish_reason=error` response —
zero output tokens, no parts — which pydantic-ai spends both output retries on
before raising `UnexpectedModelBehavior`, and the route turns into a 502. A
request rejected up front is a bug you can see; a generation that fails half the
time is one students absorb.

Both fields this agent grew — an unbounded array and a per-question enum — spent
the same schema-complexity budget, and together they broke it. So:

- `Quiz.questions` is `Field(min_length=1, max_length=10)`;
- `GenerateQuizBody.num_questions` is bounded `ge=1, le=10` to match;
- `QuizPanel`'s `COUNT_OPTIONS` offers **5 / 10**. While it offered 5 / 10 / 15,
  picking 15 was an unconditional 422 for every student.

Consequence, deliberately accepted: a quiz cannot exceed 10 questions.

### Classification is inferred, not self-declared

`QuizQuestion` gained a self-declared `kind: "worked_problem" | "conceptual"`,
counted by a ratio gate. Both are gone. The enum took gemini-2.5-flash-lite from
5/5 successful generations to 3/5, for the schema-budget reason above — a
heuristic that is sometimes wrong beats a label that makes one generation in
three fail.

`is_worked_problem` therefore reads the classification off the stem: three or
more digits, or a `[[` matrix literal. Three digits is a threshold a matrix, a
probability or a distribution clears immediately and a definition question does
not. Symbolic problems (`P = [[p, 1-p], [q, 1-q]]`) are the known false
negative, and they are affordable here in a way they would not have been under a
gate: they cost a worked problem its *preference* in the ordering, never its
place in the quiz.

### Latency: thinking off for Lite, capped for Pro

Quiz generation ran on `GoogleModel`'s defaults, which enable dynamic thinking.
On a request that emits a dozen-plus structured questions, flash-lite would
think its way into runs of 361s and 424s that ended as a 502 — exactly the "it
generates for a long time and then errors" report. The same request with
thinking off returns in ~18s, and there is nothing for thinking to do here: the
workflow is fixed by the system prompt, the concepts come from tool results, and
the output shape is constrained by the schema.

The budget is applied **per run, at the route layer** — not pinned on the agent.
Agent-level `model_settings` apply to EVERY run, including the
`model_pref="smart"` run whose `model=` kwarg is gemini-2.5-pro, and Pro rejects
`thinking_budget=0` outright. `routes/quiz.py::_build_quiz_model_settings` sends
0 for Lite/Flash and `_PRO_THINKING_BUDGET = 2048` for Pro, mirroring
`routes/learn.py` and for the same reason `agents/chat_tutor.py` records: one
agent instance serves both tiers.

### One retry, on a genuinely different model

flash-lite also fails a request outright now and then: `finish_reason=error`,
zero output tokens, no parts. Not malformed output — nothing at all. pydantic-ai
spends both output retries re-asking, gets the identical empty response each
time (identical `input_tokens` too), raises `UnexpectedModelBehavior`, and the
route returns 502. Sampled live, roughly one generation in four.

That retry has to change the MODEL: a plain fresh re-run failed both times, at
137s and 144s. `_FALLBACK_MODEL_NAME` is `gemini-2.5-flash` — deliberately not
the "fast" preference, which resolves to flash-lite, this route's own default,
and so would have re-run the identical payload on the identical model for a
second ~140s wait before the same 502.

The escalation is skipped when the caller named a model (an explicit
preference is the student's choice, not something to override on failure), and it
fires only on `UnexpectedModelBehavior`: a `UsageLimitExceeded` retry reuses the
same `ORCHESTRATOR_LIMITS` object, so it is guaranteed to exceed again.

### Retry budget

Raising `output_retries` 2 → 3 to give the (then three) gates more room was
tried and reverted. `OUTPUT_RETRY_BUDGET = 2` is pinned for every structured
agent, and `ORCHESTRATOR_LIMITS` caps the quiz run at 8 model requests — a
tool-calling run plus four generation attempts sits on that ceiling, so the bump
trades "somewhat definitional quiz" for `UsageLimitExceeded`. With the validator
no longer raising, the budget is only ever spent on output that fails schema
validation outright.

### Historical: what the retry-gate design measured

Kept because it is the evidence for the change, not a description of the code.
Under the three raising gates plus the self-declared `kind` field, seven live
10-question runs on the real course concept gave 10 worked problems once, 9
(the bar) four times, 8 once and 7 once — five of seven meeting the bar, against
a pre-change baseline of 7/10 twice. That looked like a win, and would have been
if the cost had been zero. It was not: the same design produced the 43s/361s
latencies and the one-in-five 502 above, which is what over-generation replaced.

## Known limits

- The classification is a heuristic over question text. A symbolic worked
  problem with no digits reads as conceptual; a definition question that happens
  to quote three digits reads as worked. Either way it costs an ordering
  preference, never a question.
- `select_quiz_questions` can only select from what the model returned. When
  flash-lite returns almost nothing the student gets a short quiz and the
  shortfall is logged — deliberately, because raising instead produced no quiz
  at all.
- A generation can still fail outright on a transient provider error; the route
  degrades to 502 after the one escalation above.
- Nothing gates `search_course_materials` *usage* in CI, so a future drop to
  zero calls would again be invisible. See the drift finding in #533.

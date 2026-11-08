# Learning loop: projected model cost per session and per student-month

2026-11-08 · spec §13 A137 · for the owner's Haiku-versus-Sonnet decision before
the A111 re-record. Produced by `backend/scripts/project_loop_cost.py`, offline:
no model, network or database call.

## Why

A real-model walkthrough on 2026-11-07 ran every loop slot on Claude and cost
**$0.145 per session**, with about **$0.02 per Sonnet tutor turn**: roughly 12×
spec §3.5's target of **$0.36 per student-month**. The loop's eight evidence
slots still default to Gemini until their A111 evals are re-recorded on
Claude. This projection compares the model mixes the owner can choose, so the
paid re-record can measure the configuration that will actually ship.

## Method

- **Tokens.** No eval cassette records token counts; they record each agent's
  output. The script estimates tokens as characters / 4 of:
  - each agent's static prefix (tool definitions, system prompt and output
    schema), read from the request the Anthropic SDK would send (its `create`
    is replaced by a function that raises the request back; nothing is sent);
  - each call's variable input, built by the eval modules' own builders
    (`grade()` replayed through the grader eval's cassettes, the loop tutor
    eval's assembled turn, the session-close draft, the decisions eval's
    messages, `check_items.build_prompt`);
  - each call's recorded output.
- **Prices.** `services/llm_pricing.cost_usd`, the function `llm_usage` rows
  are costed with: Haiku 5.5 $0.10 / $0.50 per MTok, Sonnet 5.5 $2 / $10,
  Gemini 2.5 Flash-Lite $0.10 / $0.40, Flash $0.30 / $2.50, Pro $1.25 / $10.
  Claude cache reads cost 0.1× input and 5-minute writes 1.25×.
- **Caching** (A137, `_ANTHROPIC_CACHED_PREFIX_TASKS`). The cached slots are
  the grader and its second opinion, check-item drafting and its alignment
  check, and the three tutor tiers. On those slots the static prefix is read
  from the cache. The table assumes one student alone: the first call of each
  prefix in a session or an upload writes it, and later calls read it.
  `--steady-traffic` assumes other students keep every prefix warm.
- **The session shape** (†: assumptions, all in the script's header).
  - 7 tutor requests per session (§3.5: an optimized 10-turn session uses
    about 7), split 25% lite, 60% standard and 15% deep (§3.5's modelled mix).
  - 8 graded answers (probe and check-ins), 4 typed decisions and 1 close.
  - Production context the single-turn eval cases lack, about 1,400 tokens per
    tutor request: the learner brief at its 1,800-character cap, 6 history
    messages on average, and on half the turns (teach) 5 retrieved chunks of
    about 266 tokens.
  - 12 sessions per active student-month.
  - One 10-concept upload per student-month: 4 drafting calls, each checked by
    the alignment check and the blind solve. This is an upper bound, because
    check items are course assets that every student in the course shares.
  - Thinking, which the cassettes do not record, is assumed per call by Claude
    effort level: low 100 tokens, medium 400, high 1,200. Gemini's deep tier
    averages 800 (§3.5); every other Gemini loop slot runs without thinking.
- **Measured per call** (the eval replay):

  | Call | Static prefix | Variable input | Output | Calls per unit |
  |---|---|---|---|---|
  | grader (first run) | 2,082 | 277 | 87 | 0.87 per graded answer |
  | grader_second, second opinion | 2,082 | 291 | 68 | 0.06 per graded answer |
  | grader_second, span check | 1,688 | 143 | 17 | 0.58 per graded answer |
  | grader_second, context check | 1,670 | 160 | 8 | 0.58 per graded answer |
  | loop_tutor_lite | 2,000 | 2,006 (with context) | 92 | 2.25 requests per turn |
  | loop_tutor (standard) | 2,000 | 2,002 | 84 | 1.00 |
  | loop_tutor_deep | 2,000 | 1,999 | 77 | 1.12 |
  | learning_decision | 236 | 99 | 9 | 0.5 per graded answer |
  | session_close | 699 | 189 | 110 | 1 per session |
  | check_items (3 concepts) | 2,684 | 1,956 | 8,354 | 4 per upload |

  The requests per turn are the recordings' own: Gemini Flash-Lite's lite tier
  retried. The grader eval leans adversarial: its 31 cases include refusals
  and injection attempts.

## The projection

12 sessions per student-month; caching for one student alone.

| Mix | Caching | Tutor | Grading | Decisions + close | **Per session** | Of which thinking | Drafting per upload | **Per student-month** | × target |
|---|---|---|---|---|---|---|---|---|---|
| Today (Gemini defaults) | off | $0.0239 | $0.0077 | $0.0003 | **$0.0319** | $0.0095 | $0.0243 | **$0.407** | 1.1× |
| Haiku, Gemini partners | off | $0.0059 | $0.0081 | $0.0005 | **$0.0146** | $0.0023 | $0.0243 | **$0.199** | 0.6× |
| Haiku, Gemini partners | on | $0.0049 | $0.0071 | $0.0005 | **$0.0125** | $0.0023 | $0.0240 | **$0.174** | 0.5× |
| Haiku + Sonnet deep tier, Gemini partners | off | $0.0292 | $0.0081 | $0.0005 | **$0.0379** | $0.0158 | $0.0243 | **$0.479** | 1.3× |
| Haiku + Sonnet deep tier, Gemini partners | on | $0.0285 | $0.0071 | $0.0005 | **$0.0361** | $0.0158 | $0.0240 | **$0.458** | 1.3× |
| Sonnet tutor, Haiku rest, Gemini partners | off | $0.1176 | $0.0081 | $0.0005 | **$0.1263** | $0.0355 | $0.0243 | **$1.540** | 4.3× |
| Sonnet tutor, Haiku rest, Gemini partners | on | $0.0978 | $0.0071 | $0.0005 | **$0.1055** | $0.0355 | $0.0240 | **$1.290** | 3.6× |
| Haiku, all Claude (Sonnet partners) | off | $0.0059 | $0.0795 | $0.0005 | **$0.0859** | $0.0416 | $0.0948 | **$1.126** | 3.1× |
| Haiku, all Claude (Sonnet partners) | on | $0.0049 | $0.0586 | $0.0005 | **$0.0640** | $0.0416 | $0.0939 | **$0.863** | 2.4× |
| Sonnet tutor, Haiku rest, all Claude | off | $0.1176 | $0.0795 | $0.0005 | **$0.1976** | $0.0747 | $0.0948 | **$2.466** | 6.9× |
| Sonnet tutor, Haiku rest, all Claude | on | $0.0978 | $0.0586 | $0.0005 | **$0.1570** | $0.0747 | $0.0939 | **$1.978** | 5.5× |
| Sonnet, all Claude (Haiku partners) | off | $0.1176 | $0.0498 | $0.0109 | **$0.1783** | $0.0488 | $0.5022 | **$2.641** | 7.3× |
| Sonnet, all Claude (Haiku partners) | on | $0.0978 | $0.0274 | $0.0109 | **$0.1362** | $0.0488 | $0.4842 | **$2.119** | 5.9× |

"Partners" are the two slots the spec requires to run on another model
(INDEPENDENT_SLOTS): the grader's second opinion (A22) and the key solve
(A124). The **Gemini partners** mixes keep both where they are today: the
second opinion on gemini-2.5-flash, and the drafter on gemini-2.5-flash-lite
with the solve on Haiku. The **all Claude** mixes put each partner on the other
Claude model.

Under steady traffic (`--steady-traffic`), the cached rows fall further. The
Haiku mix with Gemini partners costs $0.0116 per session and $0.163 per
student-month. With the Sonnet deep tier it costs $0.0309 and $0.394. With a
Sonnet tutor it costs $0.0914 and $1.121.

## Findings

1. **Today's defaults are close to the target.** The Gemini mix projects to
   $0.032 per session, or $0.41 per student-month at 12 sessions (1.1×). That
   is §3.5's own estimate, so the method agrees with the spec's model.
2. **The walkthrough's 12× is the Sonnet tutor, not Claude as such.** A Sonnet
   tutor turn projects to about $0.017, retries included (the walkthrough
   measured about $0.02). The "Sonnet tutor, Haiku rest" rows ($0.11 to $0.20 per session)
   bracket the walkthrough's $0.145.
3. **Haiku makes the loop cheaper than today.** With the tutor tiers, grader,
   decisions and close on Haiku and the partners on Gemini, a session costs
   $0.012 to $0.015 and a student-month $0.16 to $0.20, about half the target.
4. **The Sonnet deep tier alone** adds about $0.023 per session (+150%), to
   1.3× the target.
5. **The second opinion's model is the largest lever after the tutor.** The
   grader_second slot also runs the span check and the context check on every
   credited answer: 1.2 calls per graded answer in the replay. Put on Sonnet
   to stay independent of a Haiku grader, it makes grading the largest cost of
   a Haiku session: $0.06 to $0.08, more than 10× the Haiku tutor. Sonnet for the key
   solve (needed when the drafter moves to Haiku) multiplies drafting about 4×.
6. **Caching (A137) saves 12 to 26%** on the cached slots for one student
   alone, and 15 to 40% under steady traffic. The static prefix is 50 to 92%
   of each cached call's input.
7. **Thinking is the largest unmeasured term.** Under the assumed allowances it
   is 15 to 50% of a Claude mix's session cost. The cassettes record none.

## For the owner's decision (not a decision)

- **Tutor.** Haiku for every tier projects to half the target; Sonnet for every
  tier projects to 3.5 to 7×. Sonnet for the deep tier only (15% of tutor
  requests) projects to 1.3×. That case rests on the deep tier's eval showing
  a quality gain worth about $0.023 per session.
- **Partners.** Keeping the second opinion and the key solve cross-family
  (Gemini Flash and Haiku, as today) is the cheapest way to keep A22 and A124.
  Moving them onto Sonnet costs more than the whole Haiku tutor.
- **Before the defaults move**, the A111 re-record measures what this
  projection assumes. Run it with `SAPLING_EVAL_USAGE_LOG=<path>`
  (`tests/evals/_replay.py::usage_log`). That writes one JSON line per model
  run: the dataset, the task, the model, and prompt, completion, cached and
  thinking tokens, requests and cost, priced as `llm_usage` prices them. Those
  lines replace this projection's characters / 4, thinking and retry
  assumptions with measurements. After launch, Admin > Analytics > Learning
  loop > "What did it cost?" reports measured $ per active student-month, per
  session, per matched pair and per gain point, overall and per course (A137).

## The quiz in the learning system (spec §13 A144, A145)

2026-11-08, added with the quiz flags. The quiz is not the loop: its calls are
billed to the student under the quiz's own features and its daily spend cap
(`QUIZ_DAILY_SPEND_CAP_USD`), never to the loop's per-session cost. Offline,
by this document's method: characters / 4 of the prompts the code builds
(the system prompt, the output schema and the user message, from
`agents/quiz_planned.py::build_message`, `agents/check_items_verify.py::build_verify_prompt`,
`agents/check_items_solve.py::build_solve_prompt` and
`agents/check_items_key_match.py::build_match_prompt`), thinking at the
effort allowance above (low 100 tokens), no caching, no live call.

**The shape** (†): a five-question multiple-choice quiz, grounded in the
route's five retrieved chunks of about 266 tokens each; a plan naming seven
misconception keys; twenty concept names for the concept check. Output per
question: about 182 tokens from the writer (stem, four options, a tag each,
explanation), 28 from the concept check, 35 from the solve.

| Call | Slot (default model) | Input tokens | Output tokens | $ per quiz |
|---|---|---|---|---|
| Planned writer (`quiz_planned_questions`) | `quiz` (Haiku 5.5, low) | 2,988 | 1,010 | $0.0008 |
| Concept check (A119's agent) | `quiz_check` (Sonnet 5.5, low) | 1,518 | 240 | $0.0054 |
| Blind solve (A124's agent) | `quiz_check` (Sonnet 5.5, low) | 2,501 | 275 | $0.0078 |
| Key match, two written pairs (written quizzes only) | `quiz_check` (Sonnet 5.5, low) | 558 | 160 | $0.0027 |

**The gate calls per question** (`quiz_item_gates`: the concept check and the
solve, run concurrently once per generation run; the key match only for a
written answer the quiz grader rejects):

| `quiz_check` model | Gates per five-question quiz | Per question | Per student-month at 8 quizzes † |
|---|---|---|---|
| Sonnet 5.5 (the default) | $0.0132 | $0.0026 | $0.106 (0.29× the loop's $0.36 target) |
| Gemini 2.5 Flash (`SAPLING_MODEL_QUIZ_CHECK`) | $0.0025 | $0.0005 | $0.020 |
| Gemini 2.5 Flash-Lite | $0.0006 | $0.0001 | $0.005 |

Haiku is not an option: the quiz writes on Haiku, and A124 verifies a key
only by a solve from another model (`services/quiz_learning.py::checks_independent`
refuses it). A drop that triggers the bounded top-up adds one more writer call
and one more gate pass over the new questions (at most double, once). The
planned writer is cheaper than the plain quiz agent it replaces: no tools,
one request, a 1,014-token system prompt against the plain agent's 1,850 and
its tool round trip.

**For the owner's decision (not a decision).** The Sonnet default keeps ADR
0030's Claude-only defaults and costs about as much per quiz as two loop
sessions' grading on Haiku; a cross-family Gemini solver is what A124 itself
prefers and costs a twentieth. Thinking is unmeasured: measure both with
`SAPLING_EVAL_USAGE_LOG` when the planned dataset and the live smoke of the
checks on quiz questions are recorded, and read `quiz.items_gated` for the
yield (verified, practice and dropped per generation) before the flag goes on
for everyone.

## Re-running

```sh
cd backend
SAPLING_EVAL_MODE=replay GEMINI_API_KEY=dummy-not-used-in-replay \
  ANTHROPIC_API_KEY=dummy-not-used-in-replay \
  ENCRYPTION_KEY=0000000000000000000000000000000000000000000000000000000000000000 \
  venv/bin/python scripts/project_loop_cost.py --markdown [--steady-traffic] [--sessions-per-month 12]
```

The script refuses to run in any mode but replay. Every assumption is a named
constant in its header.

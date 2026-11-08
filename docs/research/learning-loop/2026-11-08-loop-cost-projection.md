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

## Wave 4 addendum: the teach-phase prompts with their flags on (A138, A139)

This projection predates wave 4. Both flags ship off and cost nothing off. With
them on, the method above (characters / 4, the same prices and the per-turn
tutor costs of the table) gives the following. It was worked by hand from the
prompt pieces' measured sizes, offline: the script does not model these turns
yet.

- **What A138 adds.** One explaining tutor turn per segment that opens on a
  prequestion. The pose and the answer lead are code's text, and the guess is
  never graded, so there is no grader, decision or second-opinion call.
  - The turn carries `PREQUESTION_LINE` (812 characters, 203 tokens), the item
    block (about 208 characters, 52 tokens), the answer block (about 330, 83)
    and, in the history, the pose row and the guess (about 170, 42): about
    **380 tokens more** than a teach turn.
  - It retrieves nothing: the item's own passages replace retrieval
    (`rag_k` 0, 2 passages instead of 5 chunks of 266 tokens), about **800
    tokens less**. So the explaining turn costs at most one average tutor turn.
  - † 2 segments per session: 8 graded answers at `LOOP_CHECKS_PER_CONCEPT` = 2
    checks per concept, the probe's included. Skips (review, proficient, exam
    mode, no item, pool for checks) make it fewer.
  - **Upper bound:** every explaining turn is an extra turn. **Lower bound:**
    it replaces the segment's first teach turn ("Start with …", which the card
    hides). Then it adds nothing, because its input is smaller.
- **What A139 adds.** No model call: the prompts are code's text. The
  acknowledgement line (364 characters, 91 tokens) rides at most one turn per
  replied prompt. At most 2 prompts per session (once per concept), and each
  reply (about 30 tokens) stays in about 5 later turns' history. That is about
  **480 input tokens per session**.

Upper bound, caching off, 12 sessions per month (A139's share in brackets):

| Mix | Per tutor turn | A138 per session | A139 per session | Per session, flags on | Per student-month, flags on | × target |
|---|---|---|---|---|---|---|
| Today (Gemini defaults) | $0.0034 | +$0.0068 | (+$0.0002) | $0.0389 (+22%) | $0.491 | 1.4× |
| Haiku, Gemini partners | $0.0008 | +$0.0017 | (+$0.00005) | $0.0164 (+12%) | $0.221 | 0.6× |
| Haiku + Sonnet deep tier, Gemini partners | $0.0042 | +$0.0083 | (+$0.0002) | $0.0464 (+22%) | $0.581 | 1.6× |
| Sonnet tutor, Haiku rest, Gemini partners | $0.0168 | +$0.0336 | (+$0.0010) | $0.1609 (+27%) | $1.955 | 5.4× |

Findings:

1. **A138 costs at most one tutor turn per segment**: +12% on a Haiku tutor
   and +22 to 27% on mixes with Gemini or Sonnet. It costs nothing when the
   explanation replaces the turn that would have opened the segment anyway.
   The session's tutor-request budget (§3.5, `LOOP_SESSION_MAX_TUTOR_REQUESTS`)
   counts the explaining turn like any other. At the hard budget level the
   explanation is a template, not a model call.
2. **A139 costs under 1%**: one short line and the replies in later history,
   with no extra call.
3. **What turning them on waits for.** The live loop_tutor recording that each
   flag's prompt line needs (spec §13 A138 (k), A139) also measures these
   turns: run it with `SAPLING_EVAL_USAGE_LOG`, and the lines it writes replace
   this addendum's estimates.

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

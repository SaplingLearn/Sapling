# 0031: The Jev decision backend, as built: the official SDK, shadow first, grading never served

- Status: accepted (built; nothing promoted; `JEV_ENABLED=false` everywhere)
- Date: 2026-10-01
- Relates to: learning-loop spec `docs/superpowers/specs/2026-09-26-learning-loop-design.md`
  §3.6, §6, §8 invariant 24, §13 A24 and A98; PKG-15 (`HANDOFF-15.md`); #642;
  ADR 0024 (the single LLM seam); ADR 0027 (the decision seam, which admitted this
  backend); PR #672 (an earlier, direct-HTTP Jev seam, now superseded)
- Supersedes: PR #672's `services/typesafe_client.py` design (never merged). Amends
  ADR 0027's "Jev absent" clauses.
- Numbering: 0027 is the decision-seam ADR on `feat/learning-loop`. #672's branch also
  has a 0027, and `feat/620-feature-flags` claims 0028 and 0029. 0030 is the
  cutover ADR, so this ADR is 0031.

## Context

ADR 0027 admitted one non-Gemini model backend, `agents/_jev.py`, behind the typed
decision seam. That ADR said Jev would be absent until PKG-15 and gated on a
privacy review. PKG-15 builds the backend. Three choices were open.

1. **SDK or our own HTTP client.** PR #672 wrote a direct `httpx` client. It argued
   that the call is one POST, that the SDK was days old, and that the SDK's
   automatic 429/529 backoff is wrong for a sub-second decision that has a fallback.
   The spec (A24) pins `typesafe-sdk==0.7.2` instead.
2. **What Jev may serve.** The seam has five model decisions. Two of them are grading
   decisions (`grade_rubric_items`, `reason_is_correct`), and since round a33 their
   credit stands on code layers inside `agents/grader.grade()`: the pre-model
   answer screen, quotes that code verifies, the span check, the context check and
   the disowned-frame check. Jev returns an option and its probabilities. It returns
   no quote.
3. **How a shadow stays harmless.** A shadow call must not add latency to the served
   answer, must not fail it, and must not spend the student's daily grade budget.

## Decision

- **The official SDK, configured to fail fast.** `agents/_jev.py` is the only importer
  of `typesafe_sdk` (invariant 24, now scanned in both its `import` and its
  `importlib` spellings). Its `RetryPolicy` allows `JEV_MAX_RETRIES` = 1 retry,
  only on a connection error or a 500/502/503/504. It never retries a timeout, a
  429 or a 529, and it uses no backoff and no Retry-After. That answers #672's
  objection without a second HTTP client. Each attempt has a timeout of
  `JEV_TIMEOUT_MS`, and a wall-clock deadline of `JEV_TIMEOUT_MS × (1 + retries)`
  covers the whole call. The SDK covered everything #672's client did: the
  endpoint, the pinned model, per-call timeouts, typed errors with status codes,
  token usage, the `TYPESAFE_API_KEY` and `TYPESAFE_BASE_URL` env names, and a
  transport hook for hermetic tests. `_jev.py` keeps #672's one-client-per-event-loop
  cache.
- **The build guard.** The client is built only in `_client()`, after
  `enabled()` (`model_mode() == "real" and JEV_ENABLED`) and only when a key is
  set. Function mode never reaches Jev, because `select_backend` returns
  `function` first.
- **Choice questions only (A24).** Every Jev question is a Choice. Yes/no
  decisions use the options `yes`/`no`/`unclear`, which match the Gemini decision
  agent's outputs. A Noul answer carries no confidence. An answer outside the
  listed options, or a question left unanswered, is a failure (`bad_answer`). It is
  never treated as a default answer.
- **The circuit breaker and the budget.** `JEV_CIRCUIT_FAILS` consecutive failed
  calls open the circuit for `JEV_CIRCUIT_COOLDOWN_S`. After the cooldown, one
  probe goes out: success closes the circuit and failure reopens it. A state whose
  estimate exceeds `JEV_STATE_MAX_TOKENS` goes to Gemini (`oversize`). The estimate
  uses 3 chars per token over the state plus its longest question, which is
  pessimistic, because Jev's tokenizer is unpublished. Such a state is never
  truncated, and it is not counted as a breaker failure.
- **What `jev` serves.** `jev` serves only `match_wrong_reason`,
  `item_answerable` and `judge_leak` (`JEV_SERVABLE`). Any failure falls back to
  Gemini, with `decision.fallback{jev → gemini, reason}`. The failures are
  `jev_absent`, `timeout`, `http_<status>`, `transport`, `circuit_open`,
  `oversize`, `bad_answer`, and a confidence below `JEV_MIN_CONFIDENCE` = 0.5 †
  (`low_confidence`). When a served `match_wrong_reason` fails, it falls back to
  the grader's prior key, as before, and no model runs. A served Jev run is a
  decision, so the AI budget is checked first, and its `llm_usage` row has task
  `decision`.
- **Grading is never served from Jev.** For a grading decision, `jev` is served by
  Gemini with `decision.fallback{reason: jev_unsupported}`. To serve grading from
  Jev would mean crediting answers without the A33 layers. The grading decisions
  can still be shadowed: the shadow compares Jev's per-rubric-item verdicts with
  the served `all_yes`. The comparison treats the item as all-yes only when every
  item is yes, and it uses the confidence of the least sure item. Whether a future
  Jev grade can stand on the A33 layers is an owner question (HANDOFF-15).
- **`shadow_jev`.** Gemini serves the decision. Jev is asked the same question in a
  fire-and-forget task, which the served path never awaits. At most
  `JEV_SHADOW_MAX_INFLIGHT` = 32 † tasks run per process; past that a shadow is
  skipped, never queued. The task then emits `decision.shadow` (§6: enums and
  numbers only) and writes an `llm_usage` row with provider `typesafe` and task
  `decision_shadow`. That task is outside `ai_budget.GRADE_TASKS`, so a shadow never
  counts against `STUDENT_DAILY_GRADES`. A refused or unavailable grade is never
  shadowed.
- **No PII on the wire.** The request body is exactly `{state, model, questions}`.
  The state holds the decision State's text fields under fixed labels, and rubric
  items are named by position. No user, request, session or course id is sent in
  a body or a header (tested on the mock transport). The SDK logs request and
  response bodies at DEBUG, so `_jev.py` floors its logger at WARNING. SDK errors,
  which can quote a body, are dropped (`raise ... from None`) and reduced to an
  enum code.
- **Cost.** `jev-1.13.0` is priced at $0.042 per 1M input tokens, with output free
  (#672's rate), in `services/llm_pricing.py`. The cost is stored at 6 decimal
  places, so a call under about 12 input tokens rounds to $0. #672's
  NUMERIC(18,10) widening is not on this branch.
- **Promotion is the owner's decision.** Nothing is promoted. Every
  `DECISION_BACKEND_<NAME>` defaults to `gemini`, and `JEV_ENABLED` defaults to
  false. `python tests/evals/decisions.py --shadow-log …` computes the live §3.6
  gates from an export of shadow events. `promotion_checks` still computes the
  gold gates.

## Consequences

- (+) One HTTP stack, the vendor's. A version bump is a pin change plus a re-run
  of the hermetic suite and the live smoke.
- (+) Shadow data can be collected for the three servable decisions and for both
  grading decisions, with no effect on what students are served.
- (−) The privacy gate (A24) is still open. Code cannot check a contract, so
  `JEV_ENABLED` must stay false wherever student text flows. A shadow sends the
  student's answer to Typesafe.
- (−) The circuit and the shadow cap are per process. With N workers, up to
  N × `JEV_CIRCUIT_FAILS` calls can fail before every circuit is open.
- (−) The live smoke (18 calls, synthetic) measured a shadow p95 of 334 ms from a
  developer machine. `DECISION_P95_MS` is 300 and is to be measured from Sapling's
  host. The sample is far too small to decide anything.

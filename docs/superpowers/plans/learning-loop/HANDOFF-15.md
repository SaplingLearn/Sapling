# HANDOFF-15 — jev-backend

Written by the session that built PKG-15. No `PKG-15-jev-backend.md` prompt exists. The contract was spec §3.6, the module map lines for `agents/_jev.py` and `services/decisions.py`, §6 (`decision.shadow` / `decision.fallback`), §8 invariant 24, §12, and §13 A24. The as-built record is spec §13 **A98** and ADR **0031**. Branch `feat/learning-loop-15-jev`, cut from `feat/learning-loop-14b-cutover` @ d51e8e5e.

## What changed

**Review round R1 (2026-10-01; spec §13 A98 (h)–(o)) changed several of the statements below; where they disagree, this paragraph wins.**
- The breaker releases a half-open probe on every exit that is not a success, cancellation included.
- `decision_shadow` and `decision_jev_extra` rows count in $ only. They never count toward the rate limit, the daily token cap or the grades.
- `typesafe_sdk` is imported lazily.
- With any `APP_ENV` except local/development/dev/test (unset and unknown included; spec §13 A104), no Jev call goes out until `JEV_PRIVACY_GATE_RECORDED=true`.
- The SDK log floor is unconditional.
- `JEV_TIMEOUT_MS` is the TOTAL bound on a call.
- The lifespan drains the shadows and closes the clients at shutdown.
- Shadow keys are normalised to the shown alias.
- The shadow-log gates fail closed and attribute Gemini cost per decision.
- Invariant 24 closes the reviewer's three holes.

`typesafe-sdk==0.7.2` is pinned exactly and locked. The lock gained only that package; its dependencies were already locked and did not move. `backend/agents/_jev.py` is the Jev backend and the only `typesafe_sdk` importer. It builds a client only when `model_mode() == "real"` and `JEV_ENABLED`, one client per event loop, pinned to `jev-1.13.0`, with one retry, only on a connection error or a 5xx other than 529, inside an 800 ms TOTAL wall-clock deadline (R1), a circuit breaker, and a token budget that refuses an oversize state before any call and never truncates it.

`services/decisions.py` now serves `jev` for `match_wrong_reason`, `item_answerable` and `judge_leak`. Any Jev failure falls back to the Gemini answer, with a `decision.fallback` event. A grading decision is never served from Jev (`jev_unsupported`). Under `shadow_jev`, Gemini serves, and Jev runs in a background task that emits `decision.shadow` and an `llm_usage` row (`provider='typesafe'`). `JEV_ENABLED=false` (the default) still forces Gemini for everything. Function mode never reaches Jev.

Invariant 24 is no longer vacuous. PKG-05b's regex never matched `typesafe_sdk`; the invariant now scans every import spelling and the AST build guard, and a self-test feeds it violating sources. `tests/evals/decisions.py` computes the §3.6 live gates from a shadow-log export. Nothing is promoted.

## Symbols added

- `backend/requirements.txt` / `requirements.lock`: `typesafe-sdk==0.7.2` (exact; hashes from `uv pip compile … --generate-hashes --universal --python-version 3.13`).
- `backend/agents/_jev.py`:
  - `PROVIDER = "typesafe"`, `API_KEY_ENV` (= the SDK's `TYPESAFE_API_KEY`), `SDK_LOGGER = "typesafe_sdk"`, `CHARS_PER_TOKEN = 3` †, `RETRY_STATUSES = {500, 502, 503, 504}`.
  - `enabled() -> bool`: `model_mode() == "real" and JEV_ENABLED`. This is the invariant-24 guard.
  - `Question{instructions, options}`: always sent as a Choice. `Answer{choice, confidence, probabilities}`. `Result{answers, model, input_tokens, output_tokens, latency_ms}`.
  - `JevUnavailable(code, *, latency_ms, model, input_tokens, output_tokens)`. `code` is one of `jev_absent`, `oversize`, `circuit_open`, `timeout`, `transport`, `http_<status>`, `bad_answer`.
  - `estimate_tokens(state, questions) -> int`: pessimistic, counting the state plus the longest question.
  - `async ask(state, questions) -> Result`: checks the guard and the key (no call), then the budget (no call, no truncation), then the breaker, then makes the call under the deadline.
  - `_client()`: the only constructor site (invariant 24). `circuit_open()`, `reset_for_tests()`, `_transport_override` (test seam), `_clock` (test seam), `_floor_sdk_logging()`.
- `backend/services/decisions.py`:
  - Constants: `JEV_MIN_CONFIDENCE`, `JEV_SHADOW_MAX_INFLIGHT`, `JEV_SERVABLE`, `JEV_SHADOWABLE`.
  - `jev_request(decision, state) -> (payload, questions, decode)`: public, so evals measure what is sent.
  - `async drain_shadows()`: awaits the in-flight shadows on the current loop.
  - Private: `_serve_jev`, `_call_jev`, `_jev_fell_back`, `_shadow`, `_run_shadow`, `_ShadowDeps`, `_record_jev_usage`.
  - `select_backend`: `jev` → `served="jev"` for `JEV_SERVABLE`, else `gemini` + `jev_unsupported`. `shadow_jev` → `shadow=True` for `JEV_SHADOWABLE` only.
- `backend/services/llm_pricing.py::MODEL_PRICING["jev-1.13.0"] = (0.000042, 0.0)`.
- `llm_usage.task` values: `decision` (a served Jev run) and `decision_shadow` (a shadow; not in `ai_budget.GRADE_TASKS`).
- `decision.fallback.reason` values: `jev_unsupported`, `oversize`, `transport`, `bad_answer`, `http_<status>`. Spec §6 is updated.
- `backend/tests/evals/decisions.py`: `LIVE_GATES`, `NO_CALL_CODES`, `NOT_AN_ERROR`, `GEMINI_TASKS`, `shadow_rows`, `shadow_stats(rows, *, usage_rows=()) -> dict[str, ShadowStats]`, `live_gates`, `shadow_report`, and the CLI `--shadow-log PATH [--usage-log PATH]`.
- `backend/tests/conftest.py::_hermetic_jev_transport` (autouse): a refusing httpx2 transport, so no test reaches Typesafe.
- Tests:
  - `tests/test_learning_jev.py` (27)
  - `tests/test_learning_decisions_jev.py` (34)
  - `tests/test_learning_loop_invariants.py`: `::test_inv_24_typesafe_only_in_jev` (extended), `::test_inv_24_scan_self_test`, `::test_inv_24_behaviour_no_client_without_the_guard`, `::_typesafe_imports`, `::_jev_build_guard_violations`, `::JEV_CLIENT_CLASSES`.
- `backend/.env.example`: `JEV_ENABLED`, `JEV_PRIVACY_GATE_RECORDED`, `TYPESAFE_API_KEY`, `TYPESAFE_BASE_URL`, `DECISION_BACKEND_<NAME>` (all commented out).
- R1 symbols:
  - `agents/_jev.py`: `PRIVACY_GATED_ENVS`, `PRIVACY_GATE_ENV`, `privacy_gate_open()`, `_load_sdk()` (lazy SDK import; missing → `jev_absent`), `_client_class_override` (test seam), `aclose_clients()`. A new `JevUnavailable` code: `privacy_gate`.
  - `services/ai_budget.py::UNCOUNTED_TASKS = {decision_shadow, decision_jev_extra}`.
  - `services/decisions.py`: `JEV_SHADOW_DRAIN_S`, `shutdown_shadows(timeout_s) -> int` (the number dropped), `_EXTRA_TASK = "decision_jev_extra"`, `_shadow_enum`, `_record_billed`.
  - `tests/evals/decisions.py::ShadowStats.gemini_cost_conclusive`.
  - `tests/test_learning_loop_invariants.py`: `_client_class_refs`, `_client_refs_outside_jev`, `_enabled_is_the_guard`.
  - `main.py` lifespan: `await decisions.shutdown_shadows()`, then `await _jev.aclose_clients()`, before `events_service.shutdown()`.
- `docs/decisions/0031-jev-backend-via-typesafe-sdk.md`. ADR 0027 gains an "Amended by: 0031" line.

## Constants chosen

- `JEV_MODEL = "jev-1.13.0"`, `JEV_SDK_VERSION = "typesafe-sdk==0.7.2"`, `JEV_TIMEOUT_MS = 800` †, `JEV_MAX_RETRIES = 1`, `JEV_CIRCUIT_FAILS = 5` †, `JEV_CIRCUIT_COOLDOWN_S = 300` †, `JEV_STATE_MAX_TOKENS = 28_000` † (§3.6, unchanged from PKG-05b).
- `JEV_MIN_CONFIDENCE = 0.5` † (§13 A98; TypeSafe's suggested floor, used by #672).
- `JEV_SHADOW_MAX_INFLIGHT = 32` † (A98).
- `_jev.CHARS_PER_TOKEN = 3` † (pessimistic; Jev's tokenizer is unpublished; #672's estimate).
- `_jev.RETRY_STATUSES = {500, 502, 503, 504}`: never a 429 or 529, never a timeout.
- **Latency bound (R1, corrected):** one Jev call takes at most `JEV_TIMEOUT_MS` = 800 ms of wall clock, retry included (the deadline and the RetryPolicy budget are both 800 ms), and then Gemini serves. The first version's bound was 1.6 s: per-phase timeouts of 800 ms plus one retry. The earlier claim that "a timeout costs ≤ 800 ms" held only for a timeout, not for a slow 5xx followed by a retry.
- `JEV_SHADOW_DRAIN_S = 2.0` † (A98 (n)).
- `jev-1.13.0` price: $0.042 / 1M input tokens, output $0 (#672's figure).

## Deviations from spec

- Spec: `jev` serves any decision. Built: grading decisions under `jev` are served by Gemini with `jev_unsupported`. Why: their credit stands on `grade()`'s A33 layers (screen, verified quotes, span/context/disowned checks), and Jev returns no quote, so serving grading from Jev would credit answers those layers refuse (A98 (c)). They can be shadowed.
- Spec §6: the `decision.fallback` reason enum. Built: it adds `jev_unsupported`, `oversize`, `transport`, `bad_answer` and `http_<status>`, and `jev_absent` also means no key or not real mode. Why: the §6 list had no name for an oversize state, a transport error, an unusable answer or other statuses (A98 (b)).
- Spec: "Usage recorded with provider typesafe". Built: served runs use `task="decision"`; shadows use `task="decision_shadow"`. Why: a shadow must never spend the student's `STUDENT_DAILY_GRADES` (`ai_budget.GRADE_TASKS` counts `decision`). A shadow's cost still lands in the daily and monthly $ sums; it is about $0.00002 per call.
- PKG-05b's invariant-24 regex `typesafe\b`. Built: `typesafe\w*` plus an AST scan. Why: the SDK's import name is `typesafe_sdk`, and `\b` does not fall between "e" and "_", so the PKG-05b scan would never have caught it.
- PKG-05b pin `test_jev_is_served_by_gemini_and_shadow_is_a_noop`. Built: replaced by `test_grading_is_never_served_from_jev_and_its_shadow_runs_beside_gemini`. Why: the behaviour it pinned (`jev_absent`, a no-op shadow) is what PKG-15 replaces.
- PKG-05b pin `test_emit_shadow_payload_refuses_text_and_has_no_caller`. Built: renamed `…has_one_caller` (`_run_shadow`). Why: PKG-15 is its caller.
- PKG-05b pin `test_seam_callers_are_only_grade_answer`. Built: it also allows `agents/_jev.py`, as a reader of the §3.6 settings, and asserts that `_jev.py` calls no decision. Why: `_jev.py` reads `JEV_ENABLED` and the other settings at call time, as the backend under the seam.

## Known gaps

- **The privacy gate (A24) is open.** Code now refuses where it can (R1): see the runbook below. In local or test environments the interlock does not apply, so keep student-derived text out of those.
- **No gold for Jev.** `promotion_checks`' gold gates need ≥ 200 gold labels per decision (`DECISION_PROMOTE_MIN_GOLD`), and the eval has 8 synthetic cases in all. No Jev cassette was recorded. The eval's `decisions` dataset still measures only the Gemini baseline.
- **Cost precision.** `llm_usage.cost_usd` is NUMERIC(12,6), so a Jev call under about 12 input tokens is stored as $0. Real decision states are 430–570 tokens, about $0.00002. #672 / #677's NUMERIC(18,10) migration is not on this branch.
- **Per-process state.** The circuit breaker and the shadow cap are per process. Shadows on a throwaway loop (`run_agent_sync`) are cancelled when that loop closes.
- **Shutdown (R1).** The lifespan drains in-flight shadows for up to 2 s and closes this loop's client. Shadows still running are cancelled and logged as dropped; Typesafe may have billed them, and that usage is unrecorded.
- **The shadow cap.** A request that hits the shadow cap loses that shadow (WARNING only).
- **The A98 sub-items.** The review round is recorded as A98 (h)–(o), not as a new row: the parallel PKG-14 round is taking A99 and up, and a sub-item cannot collide.
- **Pre-existing lint error.** `ruff check .` reports one error that predates this branch (`tests/test_learning_tier_rederive_migration.py:23` E741, from the base). Every file PKG-15 touched is clean.
- **Live smoke (2026-10-01, 18 Jev calls, synthetic inputs only, Gemini stubbed in-process, nothing written to any DB).** 16 were shadow calls across all five shadowable decisions, and 2 were served `jev` `judge_leak` calls.
  - Results: 0 errors, 0 fallbacks.
  - Shadow latency, from a developer machine: p50 237 ms, p95 334 ms, min 133, max 334.
  - Served: 205 ms and 307 ms.
  - 8,298 input tokens in total, about $0.00035. The served model was `jev-1.13.0`.
  - Against the hand labels: 16/16 shadow answers agreed with gold once one mislabelled `item_answerable` case was corrected. The passage answered a different question; Jev's "no" was right.
  - This sample decides nothing, and p95 > `DECISION_P95_MS` (300) here. The gate is to be measured from Sapling's host.
  - The script is not committed. It ran `services/decisions.py` under `shadow_jev`, with the decision agent on a FunctionModel and `grader.grade` stubbed.

## Runbook: the privacy gate (A24's switch)

1. Until the owner records the A24 gate (DPA, ZDR, FERPA/under-18 terms, privacy notice; spec §13 A24), leave `JEV_PRIVACY_GATE_RECORDED` unset in every deployed environment. With it unset, every Jev call is refused in any `APP_ENV` but local/development/dev/test — production, staging, prod, preview, any unknown value and unset alike (an allowlist, spec §13 A104): a served `jev` decision falls back to Gemini with `decision.fallback{reason: privacy_gate}`, and a shadow is not scheduled at all (one WARNING per process). This holds even if `JEV_ENABLED=true` is set by mistake.
2. When the gate is recorded (an ADR or a spec amendment naming the date and the documents), set `JEV_PRIVACY_GATE_RECORDED=true` together with `JEV_ENABLED=true`, then choose `DECISION_BACKEND_<NAME>=shadow_jev` per decision.
3. Revoking: unset `JEV_PRIVACY_GATE_RECORDED`, which is read per call and takes effect at once, or set `JEV_ENABLED=false`, which is read at import and takes effect on restart.

## Verify commands

```
cd backend && venv/bin/python -m pytest tests/test_learning_jev.py -q                         → 42 passed
cd backend && venv/bin/python -m pytest tests/test_learning_decisions_jev.py -q               → 49 passed
cd backend && venv/bin/python -m pytest tests/test_learning_loop_invariants.py -q -k inv_24   → 3 passed
cd backend && venv/bin/python -c "import sys, main; print('typesafe_sdk' in sys.modules)"     → False
cd backend && venv/bin/python -m pytest tests/test_requirements_lock.py -q                    → 3 passed
grep -rlE "^[[:space:]]*(import|from)[[:space:]]+typesafe" backend --include=*.py --exclude-dir=venv --exclude-dir=tests → backend/agents/_jev.py (only)
grep -n "^typesafe-sdk==0.7.2" backend/requirements.txt backend/requirements.lock            → 2 hits
cd backend && SAPLING_EVAL_MODE=replay venv/bin/python tests/evals/run_all.py                 → 16 PASS
cd backend && venv/bin/python tests/evals/decisions.py --shadow-log <events.jsonl> [--usage-log <llm_usage.jsonl>] → JSON per decision; exit 0 only if every live gate passes
```

The full hermetic suite, from `backend/` with no `SAPLING_MODEL_MODE` / `SAPLING_FUNCTION_HANDLERS` set (the CONTINUE command), passes: see the LEDGER row.

## Open questions for the series owner

- (a) **#672 is superseded.** Its direct-HTTP client, flash-lite decision backend and observe-only tutor router are not ported. PKG-15 uses the SDK (configured to fail fast, which answers #672's backoff objection) and the PKG-05b seam. Close #672, or fold its tutor router (#640) and the NUMERIC(18,10) `cost_usd` widening into their own PRs. Meanwhile #672 is untouched.
- (b) **Grading under Jev.** Should a Jev grade ever be served? Doing so needs a way for the A33 layers to stand on it. For example, Jev could answer only the per-item yes/no, and code would still require grade()'s verified quotes and span check, which today are Gemini runs. Meanwhile: never served (`jev_unsupported`); grading is shadowable.
- (c) **Shadow cost and the budget.** Settled by R1: shadow rows count in $ only (about $0.00002 each) and never toward the rate limit, the token cap or the grades. Question for the owner: should they leave the $ caps too?
- (d) **A served Jev decision as a grade.** Settled by R1: never more grades than the Gemini path. A served `match_wrong_reason` with a prior is `decision_jev_extra`.
- (e) **The privacy gate's owner and record.** Where should "the gate passed" be recorded? The code switch is `JEV_PRIVACY_GATE_RECORDED` (see the runbook); the record itself is the owner's choice of an ADR or a spec amendment.
- (f) **CLAUDE.md** still says "there is no other sanctioned LLM seam (ADR 0024)" and has no repo-map line for `agents/_jev.py`. This session did not edit CLAUDE.md. The owner may want one line there (ADR 0027 already amends ADR 0024).

## Post-hoc changes

- PKG-14/15 2026-10-01 (review fix round, M1): the privacy gate is an allowlist — only local/development/dev/test are ungated (`PRIVACY_GATED_ENVS` → `PRIVACY_UNGATED_ENVS` = `config.LOCAL_APP_ENVS`); `test_the_privacy_gate_interlock` +11 cases (prod, preview, beta, a random string, empty, unset, …); `.env.example` updated; spec §13 A104 — commit 1844a0c3
- PKG-14/15 2026-10-01 (review fix round, m5): `shadow_stats` cost is +inf with no Jev call (no vacuous `cost_not_worse` pass); `_run_shadow` agreement compares raw values when both map to "other"; tests/test_learning_decisions_jev.py +5; spec §13 A107 — commit e617aa06

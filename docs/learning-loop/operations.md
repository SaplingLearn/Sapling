# Operations: switches, models, cost, migrations, tests

How the loop is switched, priced, migrated, verified and tested. The deeper
acceptance procedure is the
[engineering readiness record](../operations/learning-engineering-readiness.md);
this page summarises it and adds the developer's view. Commands assume the
repository root unless they start with `cd`.

## Switches

### The kill switch

`LEARNING_LOOP_ENABLED`, parsed once at import by `backend/config.py`
(`backend/config.py::LEARNING_LOOP_ENABLED`):

| Value | Loop |
|---|---|
| unset, empty, `true`, `1`, `yes`, anything else | **on** (an unrecognised spelling logs a warning and stays on) |
| `false`, `0`, `off`, `no` (any case, whitespace ignored) | **off** for every student |

Off means: the legacy routes in `backend/routes/learn.py` stop delegating to
the loop, every `/api/learn/loop/*` route answers
`404 {"detail": "learning loop not enabled"}` (the status probe
`/review/active` answers `200 {"active": false}`), and the frontend renders
the legacy Learn screen. It is read at process start, so a change needs a
redeploy. The legacy tutor that runs instead writes no mastery: quiz and
flashcard evidence still flow through the single writer. The navigation flag
`hide_tutor` is **not** a kill switch: it hides the nav entry but is
deliberately not enforced on `/api/learn/loop`, which also serves Study's
review and post-test (`NAV_FEATURES_NOT_ENFORCED` in
`backend/services/feature_flags.py`). The drill is in the readiness record,
"Kill-switch and rollback drill".

`LEARNING_GATE_TIME_SCALE` (default 1.0) scales every gate time; only the
E2E lanes set it (0.01). Production never sets it (A5).

### Feature flags

Declared in `backend/services/feature_flags.py::REGISTRY`, configured in the
`feature_flags` / `feature_flag_targets` tables from `/admin`. Resolution,
first match wins: `SAPLING_FLAG_<KEY>` env override → fail closed (an
unknown flag or an unreadable store gives `off`) → user rule → role rule →
percentage rollout → stored default. Reads come from a 30-second snapshot
(`FEATURE_FLAGS_SNAPSHOT_TTL_S`; the E2E stack sets 0). Every loop flag ships
`off`.

| Flag | What `on` does | Visible to client | Who turns it on, and when |
|---|---|---|---|
| `item_reports` | Students see "Report this question" on loop and review cards; `POST /api/learn/loop/report` accepts reports. Two reporters put an item on a reversible hold (A123). Reports already made keep excluding their items whatever the flag says (A113). | yes | Owner, any time. |
| `retention_due_badge` | A "retention check due" badge on Study and the Dashboard, and `GET /posttest/due` (404 while off). Turns the delayed post-test from pull to push (A126). | yes | Owner, **at a trial boundary only**, recorded, kept for the whole cohort: it changes the measurement protocol. |
| `probe_matched_pretest` | The probe opens a new concept on a form parallel to its post-test reserves, so pre/post pairs match (A130). One extra `posttest_anchors` read per `/probe/next`. | no | Owner, **at a trial boundary only**, as above. |
| `upload_prereq_edges` | Uploads ask concept extraction for prerequisite relations and write validated prerequisite edges (A118). Changes propagation, bands, wheelspin repair and plan order for upload-built graphs. Off: the upload is byte-identical to before. | no | Owner, after reviewing the effect on plan order. |
| `loop_tutor_v2` | The tutor's v2 turn template: verdict first, "Key idea:" only on new content, the plan's current concept on every teach turn (A121). Off: the tutor request is byte-identical. | no | Only after the `loop_tutor` and `misconception_confront` eval datasets are re-recorded live with `LOOP_EVAL_VARIANT=v2` and pass. |
| `help_gate_strict` | The strict genuine-attempt rule for hints: time alone with the latest hint, novelty, no stem paste (A134). | no | Owner's pedagogy decision, judged by the help-abuse report's "by gate" rows. |
| `segment_prequestion` | Each new concept in a session opens on one ungraded guess at a vetted question, and the answer and an explanation follow at once (A138). It makes the segment's first graded check a half-weight re-check (A76). | no | Only after the explaining turn's prompt is recorded live in the `loop_tutor` evals (owner-approved spend). |
| `self_explanation_prompts` | At a worked example, a shown solution or a first unhelped correct answer, the turn's question becomes "why does this follow?" with a reply box; replies are stored for analysis only (A139). | no | Only after the acknowledgement line is recorded live in the `loop_tutor` evals; judge it by the admin "Do students explain their steps?" panel. |
| `varied_isomorphs` | The uploader's items are drafted with varied scenarios and representations and a stored surface descriptor; the student's picks prefer a surface not yet met; difficulty-1 items are kept out of the review interleave (A140). Read per uploader for drafting and per student for picks. | no | Only after the varied drafter's eval dataset is recorded live and passes. |
| `multi_concept_items` | The uploader's uploads also draft items combining a concept with its direct prerequisites; a student proficient in every component is served one, at most once a session per concept, counted as a half-weight observation on the apex (A141). | no | Only after the combination drafter and its alignment check are recorded live; it drafts nothing unless the uploader also has `upload_prereq_edges`. |
| `crisis_support` | A message stating suicidal ideation, self-harm or acute danger gets a fixed resources card instead of a model turn, on every tutor, loop and notes surface. | no | Owner, after reviewing the copy (`docs/safety/crisis-support.md`). |
| `quiz_concept_plan` | The quiz home proposes concepts from the learner model — FSRS-due reviews first, then open misconceptions, then the ready fringe — and "Review everything due" is the FSRS-due set (`GET /api/quiz/plan`, 404 off; A143). Reads only. | yes | Owner, any time: no model call, no write. |
| `quiz_planned_questions` | Code chooses each quiz question's difficulty and misconception target; the planned writer (`backend/agents/quiz_planned.py`) only writes them, tagging distractors with the named keys (A144). | no | Only after `backend/tests/evals/quiz_generation_planned.py` is recorded live and passes (then it joins `run_all.py`). |
| `quiz_item_gates` | Each generated quiz question passes A119's concept check and A124's blind solve on `quiz_check` before it is served; a misaligned or disputed one is never served, and only a verified one is evidence (A145). Two to three model calls per quiz. | no | After the live smoke of the checks on quiz questions (`backend/tests/evals/quiz_item_gates.py`) is recorded and passes, and the cost is measured (`quiz.items_gated`; the cost projection's quiz section). Before or with `quiz_planned_questions`. |
| `quiz_misconceptions` | A "Sure" wrong answer on a verified quiz question's tagged distractor records that misconception; a correct, unassisted first answer to a verified question listing an open key closes it (A146). | no | After `quiz_planned_questions` and `quiz_item_gates` are on (it acts only on questions generated under both) and the tag yield is measured. |
| `quiz_results_routing` | The quiz results show each skill meter that moved, what is due, and the next step: the review queue, or Learn on the weakest ready concept (A147). Reads only. | no | Owner, any time. |
| `decision_router` | Main's observe-only tutor router (ADR 0027). Not part of the loop; acts on nothing. | no | — |

A flag is resolved once per request, turn or upload and the answer carried
down (`backend/routes/learn_loop.py::_tutor_v2_on`,
`backend/routes/learn_loop.py::_help_gate_strict_on`,
`backend/routes/learn_loop.py::_prequestion_on`,
`backend/routes/learn_loop.py::_self_explain_on`;
`backend/services/check_item_service.py::drafting_flags` reads the two
drafting flags once per run for the uploader, and the backfill, which has no
student, always drafts plain). All four wave-4 flags are off by default and,
off, byte-identical to the code before them.

## Model slots

The ten loop slots, their default models, Claude effort levels and
function-mode handlers are tabled in
[architecture.md](architecture.md#backendagents--the-loops-model-slots).
Operationally:

- **Overrides.** `SAPLING_MODEL_<SLOT>` (for example
  `SAPLING_MODEL_LOOP_TUTOR=claude-sonnet-5-5`) moves a slot with no code
  change. The provider follows the name: `claude-*` → Anthropic, `gemini-*` →
  Google; anything else is an error.
- **Still on Gemini.** `check_items`, `grader`, `grader_second`,
  `learning_decision`, the three `loop_tutor*` tiers and `session_close`
  default to Gemini until their eval datasets are re-recorded live on Claude
  and pass (A111; `backend/agents/_providers.py::LOOP_SLOTS_PENDING_CLAUDE_EVAL`).
  Moving one is: flip its `_DEFAULTS` entry, remove it from the pending set,
  add the model to its evaluated set, in one change.
- **The evidence-slot guard (A128).** At boot (real mode) and whenever a slot
  resolves a model, an evidence slot on a model outside its evaluated set
  logs one warning and emits one `system.unevaluated_slot` event per process;
  `grader_second` on `grader`'s model, or `check_items_solve` on
  `check_items`' model, logs an error and emits `system.slot_not_independent`.
  It never blocks. The admin learning-loop report lists these as
  `slot_warnings`.
- **Routing.** Only the `standard` and `deep` tutor tiers are routable today
  (`backend/agents/loop_tutor.py::LOOP_ROUTABLE_TIERS`); a turn the policy
  assigns to `lite` runs on `standard` (A49, A108).
- **The quiz's check slot (A145).** `quiz_check` (default
  `claude-sonnet-5-5`, effort low) runs the A119 and A124 agents on generated
  quiz questions. It must resolve to a model other than the `quiz` writer's
  (`claude-haiku-5-5`); when an override makes them one model, no quiz key is
  verified and every gated question is practice
  (`backend/services/quiz_learning.py::checks_independent`). The writer is
  the model that wrote the request: a quiz request's `model_pref` `smart`
  writes on `claude-sonnet-5-5`, so its questions are practice under the
  default slot (`backend/routes/quiz.py::_writer_model_name`). A `gemini-*`
  override keeps it independent at a fraction of the cost.
- **Model mode.** `SAPLING_MODEL_MODE` is `real` (default) or `function`;
  it is frozen at boot (`backend/agents/_providers.py::freeze_model_mode`,
  the first call in the lifespan), and `/api/health` reports it.

## Cost

The owner's target is **$0.36 per student-month**
(`backend/learning/params.py::LOOP_COST_TARGET_USD_PER_STUDENT_MONTH`; spec
§1 and §3.5), which prices the routed tutor plan without caching.
[The cost projection](../research/learning-loop/2026-11-08-loop-cost-projection.md)
(2026-11-08) estimates, per configuration:

| Configuration | Per session | Per student-month | Against target |
|---|---|---|---|
| Today's defaults (Gemini loop slots) | $0.0319 | $0.407 | 1.1× |
| Haiku tutor with Gemini partners | $0.0125–0.0146 | $0.174–0.199 | 0.5–0.6× |
| Haiku plus a Sonnet deep tier | — | — | 1.3× |
| Sonnet tutor | — | — | 3.6–4.3× |
| A live walkthrough with every slot on Claude | $0.145 | — | about 12× |

Assumptions: 7 tutor requests, 8 graded answers, 4 decisions and 1 close per
session; 12 sessions and one 10-concept upload per student-month; prompt
caching saves 12–40%. Re-run it with
`backend/scripts/project_loop_cost.py` (replay mode only; it cannot reach a
network):

```sh
cd backend && SAPLING_EVAL_MODE=replay GEMINI_API_KEY=dummy-not-used-in-replay \
  ANTHROPIC_API_KEY=dummy-not-used-in-replay ENCRYPTION_KEY=$(printf '0%.0s' {1..64}) \
  venv/bin/python scripts/project_loop_cost.py --markdown
```

Measured cost, after launch, is the `cost_per_gain` block of
`GET /api/admin/analytics/learning-loop`
(`backend/learning/cost_per_gain.py::cost_per_gain`, A137): dollars per
active student-month, per session and per matched pre/post pair, each with
its n. It needs `llm_usage.course_id` (A137's migration) to attribute
session-less spend.

The projection predates wave 4. With its flags on, a prequestion adds one
explaining tutor turn per segment (a normal, budget-checked turn; a template
at the hard level), a self-explanation prompt adds none (code serves it; only
the next turn carries a one-line acknowledgement), and multi-concept drafting
adds a drafting call and an alignment check per batch of combinations, billed
to the uploader like all drafting (A44). None of this has been costed yet.

The quiz's item gates (A145) are costed offline in the projection's "The quiz
in the learning system" section: about $0.013 per gated five-question quiz
($0.0026 a question) on the default `quiz_check` (Sonnet), about $0.0006 on a
Gemini Flash-Lite override, against about $0.0008 for the planned writer's own
call. They are billed to the student inside the quiz's daily spend cap, not to
the loop.

### Per-student budget

`backend/services/ai_budget.py` is checked before every loop model run
(invariant 23). Defaults live in `backend/config.py` and are env-overridable:

| Variable | Default | Meaning |
|---|---|---|
| `STUDENT_DAILY_BUDGET_USD` | 0.20 | daily spend cap (× `BUDGET_NOVICE_MULTIPLIER` 2.5 for a novice-band concept) |
| `STUDENT_SOFT_FRACTION` | 0.8 | share of a cap at which the soft level starts |
| `STUDENT_MONTHLY_BUDGET_USD` | 2.00 | monthly spend cap |
| `STUDENT_DAILY_TOKENS` | 400000 | daily token cap |
| `STUDENT_DAILY_GRADES` | 300 | daily graded answers (the grader's own cap) |
| `STUDENT_DAILY_TUTOR_CALLS` | 200 | daily tutor call count (`ai_tutor_daily_calls`, A39) |
| `LEARN_RATE_LIMIT_PER_MIN` | 20 | model-running requests per minute |
| `PLATFORM_DAILY_BUDGET_USD` | unset | platform-wide spend **alert** (not a cap) |

Session caps are in `backend/learning/params.py`: 40 tutor requests
(`LOOP_SESSION_MAX_TUTOR_REQUESTS`, hard) and 6 deep requests (12 for a
novice; soft). The **degradation ladder**: at the soft level the tutor's tier
ceiling drops from `deep` to `standard` (a novice keeps `deep` until the
novice deep cap) and teach turns get less retrieved context; at the hard
level no model runs. A hard tutor cap never stops grading, which has only its
own daily cap. JSON routes answer `429 {"detail": "ai budget reached",
"reset_at": …, "scope": …, "session_capped": …}` with `Retry-After`;
streaming routes send a `budget` event and stop. The frontend shows the pause
banner and keeps review and flashcards working. Every cap hit emits
`ai.budget_capped`.

## Migrations and their rollout order

Learning migrations live in `backend/db/migrations/` as
`<UTC timestamp>_learning_<desc>.sql`, applied by `python -m db.migrate` (run
from `backend/`; for staging or production,
`dotenv -f .env.staging run -- python -m db.migrate` with the session-mode
pooler URL on port 5432). They are never edited after they are applied
(invariant 8), and they are additive: a rollback is a code rollback on the
same database, never a down-migration.

**The release fence.** Almost every learning migration must be applied
**before** the code that uses it. Where the platform deploys code first
(`make promote` applies production migrations before its merge confirmation;
`.github/workflows/migrate-staging.yml` applies staging migrations on pushes
to main that touch `backend/db/migrations/`), check the order against the
readiness record before merging. The ordered lists:

- **Checklist and evidence (October 2026):**
  `backend/db/migrations/20261019125459_checklist_budget.sql`,
  `backend/db/migrations/20261019131339_learning_evidence_transaction.sql`,
  `backend/db/migrations/20261019141950_learning_evidence_forward_repair.sql` — before the code;
  drain all old workers (they bypass the new reservation protocol).
- **Wave 2** (`feat/learning-loop-wave2`), in filename order, all before the
  code: item quality (A113), post-test windows (A112), the `claude` grader
  backend (A116 — before any grader slot moves to Claude), item alignment
  (A119), evidence void (A123), item keys (A124), document drafting (A128),
  student confidence (A127), post-test outcomes (A126), the evidence-commit
  reconcile (A123 × A127), void-aware post-test anchors, the misconception
  resolved-reason CHECK, the void grants and exact snapshot floats.
  **`learning_evidence_commit` is re-created three times in this wave and only
  the last is correct:** apply `backend/db/migrations/20261108072715_learning_evidence_void.sql`,
  `backend/db/migrations/20261108092032_learning_student_confidence.sql` and
  `backend/db/migrations/20261108103333_learning_evidence_commit_reconcile.sql` in the same
  migration run, never stopping between the last two; otherwise every
  evidence write fails its batch.
- **Wave 3:** `backend/db/migrations/20261108162223_learning_exact_floats.sql` (A136; either order;
  then run the float probe below) and
  `backend/db/migrations/20261108163653_learning_llm_usage_course_id.sql` (A137; before the code,
  though code ahead of it loses no usage row).
- **Wave 4**, in filename order and one run (the readiness record's single
  "wave-4 rollout ordering" section):
  `backend/db/migrations/20261108184825_learning_teach_prompts.sql` (A138,
  A139: the prequestion and self-explanation tables; **before** the code —
  code ahead of it still grades as before, since A76's release read fails
  closed to "no release");
  `backend/db/migrations/20261108185101_learning_varied_practice.sql` (A140,
  A141: four nullable `check_items` columns; before either flag is turned
  on, and either side of the code while both are off); and
  `backend/db/migrations/20261108193927_learning_report_course_key.sql`
  (A142: the per-course-item report key and the owner check in
  `misconception_record`; either side of the code). Rolling back while a
  multi-concept grade checkpoint is in flight cannot replay it as written:
  roll forward, or drain checkpoints first.

Exact wording, the consequences of a wrong order and the rollback notes for
each are in the readiness record's rollout sections. The data model each
migration builds is in [data-model.md](data-model.md).

## The release verifier

`backend/scripts/learning_release_verify.py` gathers evidence for a release;
it never authorises one (`release_authorized` is always `false`). It loads no
`.env`, starts nothing, runs no model, migration or business RPC, and writes
only its `--output` file (created new, mode 0600, never overwritten). Run from
`backend/`:

| Mode | What it checks |
|---|---|
| (no flags) | Local inventory: the sha256 of every migration file. Status `plan_only_no_live_checks`. |
| `--probe --api-base … --web-base … --expected-commit SHA` | `/api/health` on both origins: service name, model mode (`--expect-model-mode`), and the reported commit prefix. |
| `--expect-loop enabled\|disabled --session-token-file F --user-id U` | `GET /api/learn/loop/status` with a fixed nonexistent session: 200 `active: true`, or the gate's exact 404. A 401 or a generic 404 fails. |
| `--db-audit --db-url-env VAR --expected-db-host H --expected-db-port 5432` | Read-only: no pending or orphan migrations, required learning columns (`REQUIRED_COLUMNS`, which includes the two wave-4 tables and the four new `check_items` columns) and RPC signatures, `extra_float_digits=3`, applied files unchanged against `--migration-reference`. It reads no function body, so A142's re-created functions show only through the ledger check. |
| `--rest-float-probe --rest-url-env VAR --rest-key-env VAR --expected-rest-host H` | One GET of `learning_float_probe()` through PostgREST: are floats exact (A136)? |
| `--log FILE` | Counts named failure signals in a bounded deploy log (event or usage drops, failed accounting hooks, stream failures, platform spend alerts). |

Exit 1 on `failed` or `attention`. The exact staging commands are in the
readiness record, "Safe additional verifier".

## Test lanes

| Lane | Proves for the loop | Command | CI |
|---|---|---|---|
| **Unit** (hermetic) | Policy, math, the invariant scans, routes over a mocked database, agents on function-mode handlers, cassette hash pins | `cd backend && python -m pytest tests/ -q` (CI adds `--ignore=tests/evals --ignore=tests/test_docling_integration.py --ignore=tests/test_ocr_pipeline.py --ignore=tests/test_extraction_backends.py`) | `.github/workflows/ci.yml`, every PR and push to main |
| **Integration** (real local Postgres) | SQL functions, locks, races, migration replay, the evidence transaction, voids, post-test claims, recovery | `supabase start`; `cd backend && SUPABASE_DB_URL=postgresql://postgres:postgres@127.0.0.1:54322/postgres python -m db.migrate`; then `SAPLING_MODEL_MODE=function SAPLING_FUNCTION_HANDLERS=agents.function_handlers_e2e RUN_INTEGRATION=1 python -m pytest -m integration -q` | `.github/workflows/integration.yml`, every PR and push to main |
| **Eval replay** | Recorded model outputs still pass every evaluator against current prompts and schemas (a changed prompt makes a recording stale) | `cd backend && python tests/evals/run_all.py` (one dataset: `python tests/evals/loop_tutor.py`) | `.github/workflows/evals.yml`, PRs touching `backend/agents/**`, `backend/tests/evals/**`, `backend/learning/**`, `backend/routes/learn_loop.py`, the learning decision seam and the few services the datasets read (A142) |
| **Eval record** (live, billable, owner-run) | Re-records cassettes against live models | `SAPLING_EVAL_MODE=record python tests/evals/run_all.py`, then `SAPLING_EVAL_UPDATE_BASELINES=1 python tests/evals/run_all.py`; commit cassettes and `baselines.json` together | none |
| **E2E default lane** | The browser journey on function-mode models: probe → plan → check → hint → feedback → close, resume, budget pause, review, retention check, recovery; with each wave-4 flag turned on for a seeded student, the prequestion and self-explanation journeys (`frontend/e2e/learn-loop.spec.ts`) and varied and multi-concept practice (`frontend/e2e/learn-varied-practice.spec.ts`) | see the stack below; `cd frontend && npx playwright test e2e/learn-loop.spec.ts e2e/learn-varied-practice.spec.ts` | `.github/workflows/e2e.yml`, push to main and manual (not a PR gate) |
| **E2E kill-switch lane** | The legacy Learn screen and tutor return when the loop is off | the same, with `LEARNING_LOOP_ENABLED=false` exported in the same shell for the stack and Playwright | `e2e.yml` matrix `lane: kill-switch` |
| **Accessibility and keyboard** | WCAG 2.1 A/AA scans of every student surface; a keyboard-only loop journey (A135) | `cd frontend && npx playwright test e2e/a11y.spec.ts e2e/learn-keyboard.spec.ts` | inside `e2e.yml` |
| **Oracles** | Database-level judges after a run: evidence without learner state, any `zpd.leak`, mirror drift, a graded step without evidence, a seeded answer served before release, and more | `cd backend && venv/bin/python -m e2e_oracles` (`--check learn_loop` for the loop judge) | inside `e2e.yml`, both lanes |
| **Live opt-in** | A few billable schema checks; none exercises a loop slot | `RUN_LIVE_QUIZ=1`, `RUN_LIVE_TOPIC_CHECKLIST=1`, `RUN_LIVE_TUTOR_TOOLS=1`, `RUN_LIVE_STREAM_RUNGS=1`, `RUN_LIVE_OCR=1`, `RUN_LIVE_OCR_PIPELINE=1` with real keys | none |
| **Learning-trial analysis** | The trial's analysis code on synthetic data | `cd backend && python -m learning_trial power --fast` | via the unit lane |

What no lane proves: that a real provider's output is as good as the recorded
one (replay is frozen; eight loop slots were recorded on Gemini), that a
hosted deploy and a rolling restart behave, or that students learn. The
readiness record lists what still needs owner infrastructure. The wave-4
flag-on prompts — the prequestion's explaining turn, the self-explanation
acknowledgement, the varied drafter and top-up, the combination drafter and
its alignment check — have **no live recording yet**; they run only in
function mode and the offline tests until the owner approves the spend, and
each flag waits on its recording. The same holds for the quiz's planned
writer (`backend/tests/evals/quiz_generation_planned.py`, cases and
evaluators ready, no cassette) and for the A119/A124 agents on quiz
questions on `quiz_check` (`backend/tests/evals/quiz_item_gates.py`). The quiz journeys with the quiz flags on are in
`frontend/e2e/quiz-learning.spec.ts`; the flag-off pins are
`backend/tests/test_quiz_learning_flags_off.py`.

### Hermetic guards

The unit lane cannot reach a network or a live model:
`backend/tests/conftest.py::_hermetic_egress_floor` replaces the Supabase
client's transport and the Anthropic, Google and Jev transports with ones
that raise, for the whole session, and per-test guards stub the database.
Shell `SAPLING_MODEL_<SLOT>` overrides are cleared. A test marked `live_llm`
is skipped unless some `RUN_LIVE_*=1` is set
(`backend/tests/live_opt_in.py::live_opt_in`); `integration` and
`e2e_staging` tests lift the guards for themselves. Evals read no database
whatever `.env` says (`hermetic_budget` in `backend/tests/evals/_replay.py`,
A137).

## Running the loop locally

### With real models

1. `cp backend/.env.local.example backend/.env`, then set `ANTHROPIC_API_KEY`
   and `GEMINI_API_KEY` (the Gemini key serves embeddings and the eight loop
   slots still on Gemini). Leave `LEARNING_LOOP_ENABLED` and
   `SAPLING_MODEL_MODE` unset (on, and real).
2. Install: `python -m venv backend/venv && backend/venv/bin/pip install -r backend/requirements.txt`;
   `cp frontend/.env.local.example frontend/.env.local && (cd frontend && npm ci)`.
3. `scripts/local-up.sh`: starts local Supabase, migrates, creates buckets,
   reloads PostgREST and seeds (`SEED_RICH=1` adds the rich dataset,
   including loop users). Details: [the local Supabase guide](../local-supabase.md).
4. `cd backend && python main.py` and `cd frontend && npm run dev`.
5. Sign in with Google in the browser (fill `GOOGLE_CLIENT_ID` and
   `GOOGLE_CLIENT_SECRET` first; see the local Supabase guide), or, for API
   calls, mint a session cookie for the seeded loop user:
   `curl -si -X POST http://localhost:5000/api/auth/test-login -H 'Content-Type: application/json' -d '{"user_id":"rich-user-loop"}'`
   (test-login answers 404 unless `APP_ENV` is `local` or `test`).

The seeded loop items are fixtures written for the E2E grader. To see real
items, upload real course material: drafting runs in a background pool on the
`check_items` slot (Gemini Flex, with long timeouts) and then the alignment
and key checks; the loop says "preparing" until it is done (A128). Real mode
bills embeddings, drafting, grading and tutoring.

### The local E2E stack

`make e2e-up` boots a deterministic stack (local Supabase, backend without
reload on :5000, the test-profile frontend on :3000, the rich seed) and
`make e2e-down` tears it down. It does **not** set function mode itself:
export `SAPLING_MODEL_MODE=function SAPLING_FUNCTION_HANDLERS=agents.function_handlers_e2e`
first, or the stack calls live models. `scripts/e2e-up.sh` exports
`LEARNING_GATE_TIME_SCALE=0.01`, zero flag-cache TTLs and blank PostHog
tokens, and switches on no loop flag.

The stack is a machine singleton. Hold one `flock` on
`/tmp/claude-<uid>/sapling-e2e-stack.lock` around the whole
up → test → oracles → down cycle, with the teardown inside the same lock (a
separately locked teardown deadlocks: the detached servers inherit the lock):

```sh
mkdir -p /tmp/claude-$(id -u)
flock /tmp/claude-$(id -u)/sapling-e2e-stack.lock bash -c '
  trap "make e2e-down" EXIT
  export SAPLING_MODEL_MODE=function SAPLING_FUNCTION_HANDLERS=agents.function_handlers_e2e
  make e2e-up || exit 1
  (cd frontend && npx playwright test e2e/learn-loop.spec.ts); rc=$?
  (cd backend && venv/bin/python -m e2e_oracles) || rc=1
  exit $rc
'
```

For the kill-switch lane add `export LEARNING_LOOP_ENABLED=false` before
`make e2e-up` (and keep it out of the backend's `.env` file: `scripts/e2e-up.sh` refuses
to start when that file names the variable). The run's global setup checks
that the lane and the stack agree. `flock` is not part of macOS; install it
separately. The full E2E guide is [docs/e2e-exploration.md](../e2e-exploration.md).

## Observability

- **Admin learning-loop report:** `GET /api/admin/analytics/learning-loop`
  (`backend/routes/admin_analytics.py`), shown on the admin analytics page.
  It reports in-band share, hints-to-criterion trends, next-session
  unassisted success, caught leaks and served reveals, unscanned turns,
  ceiling compliance, earnest-revise, the gates, BKT and stated-confidence
  calibration, the learning gain and post-test funnel, cost per gain, slot
  warnings and help abuse, and since wave 4 `self_explanation` (prompts
  shown, replied, skipped; the reply rate and median length; the next item's
  unassisted success after a reply or not, per juncture —
  `backend/learning/self_explain_report.py`) and `multi_concept` (items
  stored and held, served, answered and correct with a Wilson interval, per
  course — `backend/learning/multi_concept_report.py`). Every rate carries its
  n; a missing figure is `null`, never zero, and a failed read of one block
  leaves the rest of the report standing.
- **Check-item review queue:** `/api/admin/check-items` — flagged, reported
  and held items, approve, retire, the key audit (`/audit/sample`,
  `/audit/summary`) and item statistics (`/stats`); a multi-concept item
  names its components ("Combines A + B"), and its statistics use the
  components' own items for the rest score (A131, A141).
- **Events:** `zpd.*`, `learn.*`, `review.*`, `ai.*` and `decision.*` rows in
  `events` (payloads are ids, counts and enums only; wave 4 added
  `learn.prequestion` and `learn.multi_concept_served`); every model run is an
  `llm_usage` row with its session and course where known.
- **Nightly metrics:** `cd backend && python scripts/derive_zpd_metrics.py --dry-run`
  (drop `--dry-run` to write the four derived `learner_state` columns).
- **Trial export:** `python scripts/export_learning_trial.py --arm-label <label> --treatment-variant A`
  (dry run by default; salted pseudonyms; no text).
- **Log signals** worth alerting on: `events queue full`, `events flush dropped`,
  `log_llm_usage failed`, accounting-hook failures and
  `ai_budget: platform spend today`. Outbound failure notifications are
  deferred for the pilot (readiness record).

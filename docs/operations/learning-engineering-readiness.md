# Learning release, rollback and observability acceptance

This is an operator acceptance procedure, not evidence that a deployment or a
learning study has passed. Record a reviewed commit, environment, start/end time,
actual commands, exit codes and immutable proof paths for each rehearsal. Keep
credentials, learner prose, question keys, cookies and raw model output out of
reports. The private pilot and its data/window are not a disposable test stack.

The lifecycle spans session state, evidence writes and provider operations;
ordinary analytics still use queued best-effort telemetry. Audit each durable
boundary against the selected candidate. A healthy page or HTTP 200 does not establish delivered
tutor feedback, durable billing, cross-worker recovery or learning efficacy.
ADRs [0030](../decisions/0030-learning-loop-cutover.md),
[0033](../decisions/0033-goal-scoped-observed-diagnosis.md),
[0034](../decisions/0034-evidence-integrity-and-goal-continuation.md) and
[0035](../decisions/0035-durable-planning-observations.md) and
[0036](../decisions/0036-durable-tutor-turn-recovery.md) define the applicable
learning, kill-switch, provenance and durability contracts.

## What the automation currently verifies

- `.github/workflows/ci.yml` runs the fast backend gate and frontend
  lint/typecheck/unit tests on PRs and main. Its backend gate excludes the evals
  directory and three heavy OCR files. A PR checkout can be a merge ref: retain
  the actual checkout SHA and establish its tree relationship to the candidate.
- `integration.yml` uses an isolated local Supabase database; function-mode
  grading does not demonstrate current real-provider reliability.
- `evals.yml` replays the configured cassette baselines; passing replay does not
  calibrate new items or a live provider.
- `e2e.yml` runs on main or manual dispatch, not automatically for every PR. It
  runs default and kill-switch lanes, uses function mode, uploads artifacts and
  tears down in `always()`. A flaky/retried result is surfaced but is not turned
  into a failing job by its summary step. Inspect retries explicitly.
- `migrate-staging.yml` applies migrations only on main. It skips successfully
  when its staging DB secret is absent. A green/skipped workflow is therefore
  not proof that a particular environment received the migrations.
- `make promote` applies production migrations **before** the merge confirmation.
  It does not auto-revert code or SQL. Its `--verify-only` mode polls the
  production commit and runs general smoke checks, not a complete learning
  journey. Read [the existing promotion runbook](../../backend/promotion/README.md)
  before using it; this document grants no deployment authorization.

## Safe additional verifier

`backend/scripts/learning_release_verify.py` loads no `.env`, creates no app,
starts no service and makes no default network/database connection. From
`backend/`, an inventory-only run is:

```sh
python scripts/learning_release_verify.py --output /private/new-inventory.json
```

The file must not already exist; proofs are created owner-only and never
overwritten. `plan_only_no_live_checks` means precisely that. The tool always
reports `release_authorized: false`, including when all requested checks pass.
Its observations supplement actual rehearsal; a JSON manifest is not a release
gate or an owner approval.

For an explicitly selected staging target:

```sh
python scripts/learning_release_verify.py --probe \
  --api-base https://BACKEND-ORIGIN --web-base https://FRONTEND-ORIGIN \
  --expected-commit REVIEWED_FULL_40_CHARACTER_SHA \
  --expect-model-mode real --expect-loop enabled \
  --session-token-file /private/normal-qa-session-token --user-id QA_USER_ID \
  --output /private/new-staging-health.json
```

Use a normally authenticated, approved staging QA account. The tool neither
mints tokens nor calls test-login. The token file must be regular, owned by the
operator and mode 0600. Only the API origin receives its cookie. Redirects are
rejected. HTTP is accepted only for explicit `--allow-loopback-http` targets.
Every probe is a bounded GET; no model probe, grading, flag change, session
creation or learning write is requested. Status is read using a fixed nonexistent
session ID, not an existing learner session.

Health verifies `sapling-backend`, mode and the deployed **reported SHA prefix**;
`build_commit()` currently exposes seven characters. Full image/source/tree
provenance remains a separate deployment-platform check. A frontend health check
tests the `/api` proxy, not the browser bundle or its authenticated routes.
An unauthenticated 401 is not loop-state proof. Disabled must return the
authenticated loop gate's exact 404 detail; a generic missing-route 404 fails.

An optional explicit DB audit reads only metadata through the existing migration
operations seam and the shared `promotion.preflight` ledger primitives:

```sh
python scripts/learning_release_verify.py --db-audit \
  --db-url-env STAGING_SUPABASE_DB_URL \
  --expected-db-host EXACT_APPROVED_POOLER_HOST --expected-db-port 5432 \
  --migration-reference /private/last-approved-migration-hashes.json \
  --output /private/new-staging-schema.json
```

Set the URL variable through the operator's normal secret mechanism; do not put
its value in a command, report or terminal. The script does not load one for you.
Use the exact approved host and explicit port; transaction-mode port 6543 is
rejected. The connection has read-only transaction defaults, a 5-second connect
and statement timeout, a 1-second lock timeout, and a repeatable-read transaction.
It never applies migrations, baselines a ledger or executes a business RPC.

Acceptance requires no pending/orphan filenames, required learning column types
and the named argument/type signatures declared by learning/budget migrations.
New static RPC declarations are discovered from those migrations. Unsupported or
drop/recreate declarations require a reviewed signature-inventory update rather
than a guessed pass. Keep the critical-column contract current when adding a
migration. Compare applied file hashes with the **previously approved** reference;
do not create a fresh reference from the candidate and call it history proof.

The current critical inventory includes budget account/reservation identities,
states, UTC clocks and immutable receipt fields; learner/graph evidence versions;
and the `learning_evidence_operations` receipt/plan columns. The dynamic RPC
inventory includes checklist admit/start/read/reconcile and evidence
snapshot/commit/receipt signatures. Column presence and a matching signature do
not establish the budget constraints, role grants, locking, replay behavior or
atomicity. Run the real-DB tests for those properties. JSON `turn_activity` and
grade checkpoints live inside encrypted session state: this metadata-only audit
does not inspect or certify their content or a resumed learner workflow.

The ledger stores filenames, not SQL checksums. Metadata checks cannot establish
function bodies, constraints, RLS, trigger behavior, data backfill correctness or
legacy compatibility. Run the established read-only drift report before an
owner-run migration, then rehearse migrations on a non-reset copy of representative
existing data. Preserve original legacy NULL provenance; never infer independence
or erase evidence to make a migration or browser test pass.

## Engineering acceptance record

| Gate | Required observation | Can be checked locally | Owner infrastructure still required |
| --- | --- | --- | --- |
| Candidate identity | Actual checked-out CI ref/tree, immutable image and matching backend/frontend artifact | CI, unit tests, build, reported health prefix | Host/image identity and environment config |
| Existing-data migration | Before/after ledger/schema captures, all files accounted for, critical columns/RPCs, no old-row deletion, app-compatible transitions | Isolated non-reset DB migration/replay tests and metadata audit | Staging snapshot/backup, restore rehearsal and approved promotion ordering |
| Kill switch | Explicit off/redeploy gives authenticated gate 404 and legacy UI; re-enable gives status 200 and loop UI | Both browser lanes plus explicit status probes | Real staging host drill, including frontend cache/bundle and redeploy timing |
| Learning lifecycle | Same goal/version on resume; prerequisite scope; independent/unknown distinction; genuine attempt/help; strict lesson and feedback `done` with no SSE `error`; close/Study | Fixture browser, API/DB/oracles | Bounded real-provider smoke and repeated failure/recovery evaluation |
| Pending feedback recovery | Failed delivery preserves verdict/evidence; Check me stays blocked; Retry feedback does not regrade; successful delivery precedes next item | Deterministic error, retry, stale request and cross-tab tests | Actual provider failure/recovery on disposable authorized QA, with no replay/reset |
| Persistence/restart | Same owner/scope/durable evidence after normal process restart; pending turn timing denies false independent-time credit; stale completions are fenced; interrupted grades reconcile without regrading | Isolated DB and cold-worker/process-restart rehearsal | Host termination/rolling-deploy behavior; lazy unmaterialised openers and every grading boundary must be tested explicitly |
| Costs and telemetry | Completed/incomplete usage visible with request/session join where known; no invented zero-cost receipt; queue/drop failures alert an operator | Hermetic usage/cancellation/drop tests and metadata log scan | Deployed log collection, delivery/alert drill, cost dashboard, reconciliation and response owner |
| Checklist admission and settlement | Participating concurrent requests reserve capacity before paid generation; uncertain bills keep holds; identical settlement replays once; late cache writes are fenced | Real-DB RPC races, expiry/lock waits, rollback, permissions and receipt tests, then bounded provider smoke | Drain old workers, verify configured caps/price policy, observe unknown exposure and reconcile with provider billing |
| Atomic evidence recovery | One operation receipt covers journal, learner state and graph mirror; stale snapshots retry conservatively and conflicting identity fails closed | Real-DB atomic rollback/replay, concurrent legacy writer and cold-worker checkpoint tests | Rolling deployment/restart at each grade boundary; transcript/session checkpoints remain separate from the evidence transaction |
| Rollback | Known compatible code artifact, same DB, preserved learner IDs/goal/evidence; re-enable drill | Disposable isolated rollback rehearsal | Backup/restore authorization, host route/image switch and owner sign-off |

The actual E2E stack is a machine singleton. Wrap the entire up/test/oracle/down
cycle in the existing `/tmp/claude-<uid>/sapling-e2e-stack.lock` discipline from
`CLAUDE.md`; teardown stays inside the same lock. `make e2e-up` resets its test
database. Never point that command at the active pilot, staging or production.
Keep the default and kill-switch reports separate, including skips, retries,
oracle findings, exact source, all setup phases and teardown status.

### Checklist and evidence rollout ordering

1. Rehearse `20261019125459_checklist_budget.sql` and
   `20261019131339_learning_evidence_transaction.sql` on an isolated non-reset
   database, then verify the reviewed migration contents, role grants,
   constraints, critical columns and RPC contracts. Apply these migrations before
   the corresponding backend code. A filename or signature match alone is not
   proof that the deployed SQL body matches the reviewed artifact.
2. Use an owner-approved maintenance/ingress control to pause paid checklist
   refresh during cutover. The checklist route has no dedicated server kill
   switch; hiding navigation or disabling the learning loop does not stop it.
   Drain **all old backend workers** before reopening that traffic. Old workers
   bypass the new reservation protocol and may still have queued usage. Inspect
   that exposure; do not invoke `flush_now()` as an accounting workaround or
   refund holds on a timer.
3. Deploy only the reviewed compatible worker artifact, verify health/model mode
   and run the isolated concurrency/recovery checks before a bounded staging
   smoke. Record active old/new worker counts and deployment overlap. The
   evidence-version triggers make changes by legacy graph/state writers visible
   to optimistic checks; that does not make an arbitrary mixed-version rollout
   or old rollback artifact safe.
4. Observe completed receipts and prepared/started/unknown exposure with the
   approved operations database tooling. Unknown usage retains its full hold in
   its original UTC dispatch period; after the grace period a separately funded
   refresh can proceed, but the uncertain operation is never restarted. Confirm
   settlement/cache publication is atomic and no duplicate queued checklist bill
   is emitted. Preserve receipts across enrollment/owner deletion and reconcile
   unknown exposure before an owner changes account policy.
5. Roll back only to an artifact proven compatible with both additive schemas.
   If it does not participate in budget reservations, keep paid checklist refresh
   paused. Never delete budget/evidence receipts, fabricate missing costs, reset
   learner history or run a guessed down migration to make rollback appear safe.

### Kill-switch and rollback drill

1. Capture candidate and rollback artifact identities, approved environment,
   migration inventory and a normally authenticated QA account's existing session,
   goal/version and durable evidence IDs. Keep encrypted payloads private.
2. Rehearse on isolated infrastructure first. On staging, the owner changes
   `LEARNING_LOOP_ENABLED=false` and redeploys: it is read at process startup.
   A `hide_learn` navigation flag is not this server kill switch.
3. Run the authenticated status verifier with `--expect-loop disabled` and a
   browser drill of Learn and Study. Confirm the legacy tutor has no mastery
   writer; no quiz/flashcard deltas or legacy tier thresholds are restored.
   Do not infer this from a 401, health 200 or a hidden nav link.
4. Re-enable/redeploy and run `--expect-loop enabled`, then inspect the same
   pre-existing session/goal/evidence. Verify the browser's authoritative retry
   state for 5xx/network failures; those failures must not render legacy UI.
5. A code rollback is a separate owner action. Additive migrations remain in
   place. Do not run invented down migrations or delete the planning journal.
   Check the old artifact against the new schema before switching it. An older
   binary that cannot understand a new strict journal/receipt schema is not a
   valid rollback artifact merely because it starts.
6. Capture post-drill source/health, ledger and durable IDs. Empty test histories
   cannot demonstrate nonempty learner-history preservation. A failed or partial
   migration is not fixed by a code revert: use the existing promotion partial-state
   report, preserve its applied-file receipt and get the owner to choose a
   forward repair or an independently rehearsed restore.

### Observability and failure visibility

Capture fresh, source/time-bound deployment logs privately. An optional scan:

```sh
python scripts/learning_release_verify.py --log /private/bounded-deploy.log \
  --output /private/new-log-metadata.json
```

The scanner exports only named category counts and a file hash. It flags queue
overflow/row drops, incomplete usage or accounting hooks, stream failures and
platform spend alerts. Files over 10 MB must be replaced with a bounded capture;
they are not silently truncated into a green result. No matching lines does not
prove logging is enabled, delivered or complete. An expected injected alert also
requires operator review; the scanner does not auto-ignore it.

For a deployed acceptance drill, prove `EVENTS_LOGGING_ENABLED` is on, ordinary
provider/model/request/session usage joins reach the canonical ledger, and an
isolated induced queue/DB-delivery failure reaches the actual operations sink.
Useful source signals include `events queue full`, `events flush dropped`,
`log_llm_usage failed`, incomplete structured usage, accounting hook failures and
the `ai_budget: platform spend today` alert. Some accounting diagnostics are
DEBUG-only: verify collection/alert coverage explicitly. Do not turn on raw
learner/model payload logging to gain visibility.

Use the existing admin `/api/admin/analytics/errors`, `/llm/cost` and
`/learning-loop` routes with a normal authorized admin. Record scan truncation and
null denominators; zero events are not evidence of zero failures. Prove the
platform-spend alert with a separately authorized staging drill and an actual
recipient acknowledgement. Its platform budget is alert-only. A per-user 429
alone does not prove durable reservation or a global monetary cap.

Checklist generation now uses a scoped durable admission/settlement protocol.
Its fixed policy reserves an estimated $0.07644 and 74,576 tokens per operation
against stored ceilings of $0.20/day, $2/month and 400,000 tokens/day; caller
configuration may tighten those ceilings but cannot silently raise them. The
estimate assumes the checked Gemini price components, a cumulative 50,000-token
native full-input counter, three logical requests and at most 8,192 output tokens
per request (including reported thinking). The counter is an estimate, and a
client timeout/cancellation does not prove remote generation or billing stopped.
Unpriced/inconsistent/incomplete usage fails closed into retained exposure.

This scope does **not** cover all app features. Other features' queued ledger
delivery, concurrent workers that do not take this mutex, unknown provider bills
and remote invoice reconciliation remain limits. A failed or dropped ordinary
usage queue entry can still affect the spending snapshot outside the protected
checklist settlement. Do not call the entire app financially capped, or use
`flush_now()` as a production accounting workaround. Verify actual SQL execution
and failure visibility before describing the scoped protocol as rehearsed.

## Separate learning-validity work

The engineering procedure does not complete expert item/key/equivalent-answer/
rubric/prerequisite/difficulty review, held-out grader calibration, or consented
learner immediate assessment, actual two-day retention and unfamiliar transfer.
The finite diagnostic bands remain coarse observations rather than a perfect
knowledge boundary. Human research approvals, participants and outcomes must be
real; no local test, generated rubric, cassette pass or release checklist can
substitute for them. Release-owner approval is an operational authorization,
separate from expert or study approval. Record unresolved engineering risks and
the owner's decision before promotion; do not represent an unrun stage as passed.

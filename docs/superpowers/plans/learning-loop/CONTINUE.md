# Learning loop: handover

**For:** Andres. **Written:** 2026-09-27, 17:40 ET. **Updated:** whenever the build hands more work over.

**Goal:** the learning loop becomes the default learning system for every student, with no opt-in. `LEARNING_LOOP_ENABLED=false` stays as the kill switch.

**Sources:**
- Spec: `docs/superpowers/specs/2026-09-26-learning-loop-design.md`. Its §13 amendments (A1–A37) win over everything else.
- Status: `LEDGER.md` in this folder. A package's state is its **latest** row.

This note has four parts:
1. what is done;
2. what is being worked on right now (**do not start these**);
3. what is handed to you: open work nobody is doing;
4. what to do if the running build stops.

---

## 1. Done

Everything below is merged into `feat/learning-loop` (PR #673). CI is green on it, and every package passed three independent reviews: spec conformance; regression and dark-launch safety; adversarial correctness.

| Package | What it gives us | Verified |
|---|---|---|
| 00 foundation | env flag + gate (fails closed), invariants safety net | suite + migration on a real PG15 + E2E |
| 01 bkt-core | per-concept knowledge estimate (BKT, per-channel guess/slip, capped at 0.999 so a wrong answer always lowers it) | suite; numbers recomputed live |
| 02 fsrs-core | forgetting curve + review scheduling (FSRS-6) | suite; numbers recomputed live |
| 03 evidence-state | Evidence model, `learner_state` table, `apply_graph_update` as the single writer; journal rows carry `evidence_seq` | suite + migration replay + E2E |
| 11 quiz-flashcards | quiz answers become evidence; flashcards on FSRS, due-first | suite + fresh-DB E2E (89/89) |
| 04 check-items | practice questions per concept from uploads: reference answer, rubric, wrong reasons, source chunks, a structured `final_answer`; all encrypted | suite + E2E + live run on real Gemini |
| 05 grader-check-tool | rubric grader (sees the key, never reveals it) + `grade_answer` route helper | suite + E2E + live run |
| 05b decision-seam | typed decision interface where Jev plugs in later (Gemini today) | suite + E2E |
| 06 zpd-policy | hint ladder H0–H6, help ceiling from learner state, attempt/idk rules, answer-leak detector on the structured final answer | 8 review rounds + E2E |
| 06b ai-budget-and-usage | per-student daily AI caps with a degradation ladder that never creates or biases evidence; cached/thinking tokens in `llm_usage` | review + E2E |

**Fixes merged alongside the packages:**
- **CodeRabbit round 1:** the BKT cap, ±inf ratings, and `learning_loop_beta` taken off the student settings API (this removed a deploy race); CI runs with full git history so the migration-immutability check actually runs.
- **CodeRabbit round 2:** a failed source re-check now counts its batch as unavailable; single import style in tests; doc corrections.
- **Test-suite speed:** a gradescope test drove a real browser against BU SSO, which made the local suite 394 s. It's stubbed now; the suite takes about 20 s.
- **Cost:** with the loop on, graded answers no longer regenerate the class summary on gemini-2.5-flash. That was 84% of the spend in the live test. Spec A35.
- **Replay order:** evidence journal rows record the order they were applied in. Spec A36.

**Design and docs, all in the PR:**
- the spec, with amendments A14 (default-on) and A15–A26 (cost plan, ≈ $0.36 per student-month);
- 17 package prompts, the ledger and the hand-offs;
- the research reports in `docs/research/learning-loop/`.

**Live sequence test, 2026-09-27 (real Gemini, local stack).**
- It ran: gate → question generation → correct, wrong and "idk" answers → injection attempt → forgetting at +1/+7/+30 days → quiz evidence → flashcards → cost. A second agent recomputed every number from the spec equations, and all of them matched.
- The whole run cost $0.029. One grade costs about $0.00014.

**Migrations in the PR (9):** `20260926231744_learning_loop_beta`, `20260927024349_learning_learner_state`, `20260927035346_learning_flashcards_fsrs`, `20260927065932_learning_check_items`, `20260927093149_learning_grader_backend`, `20260927093843_learning_session_loop_state`, `20260927165158_learning_check_items_final_answer`, `20260927182054_learning_mastery_event_seq`, `20260927194913_learning_llm_usage_tokens`. All of them replay from an empty DB on the local stack. None has been applied to staging or production.

---

## 2. Being worked on right now: do not start these

Automated runs on the build machine own these three. Each one merges into `feat/learning-loop` itself when its review passes.

| Work | Branch | Owner right now |
|---|---|---|
| **Build of PKG-07 → 08 → 09 → 10, 12, 13, 14**, then a final launch check (both E2E lanes) | lanes `feat/learning-loop-NN-<slug>`, merged one by one into `feat/learning-loop` | build workflow (per package: implement → 3 reviewers → fix → E2E gate → merge + push) |
| **Grader prompt-injection guard, structural version** (spec A33) | `fix/coderabbit-r2` (backup pushed) | security workflow |
| **mc_reason check items stored with structured options** (spec A37) | `fix/mc-reason-options` (backup pushed) | fix workflow |

**Grader guard, what's changing:**
- random rubric labels on each grading call;
- a vendored Unicode UTS #39 confusables table;
- rubric-id verdict tokens become a signal instead of a refusal;
- a second grader opinion on a suspicious all-yes verdict;
- then a 60+ variant red team and a false-positive check.

**mc_reason, why and what:**
- Why: 0 of 12 were being stored, because the model broke the "correct option has an empty wrong key" convention.
- Now: options are `{text, is_correct, wrong_key}` objects, and code assigns the letters.
- It needs a live yield check before it merges.

**How to tell when these are done:**
- a `NN | verified` row in `LEDGER.md`;
- merge commits on `feat/learning-loop` ("Merge PKG-NN …", "Merge … fix/…").

Please don't push to the lane or fix branches while these runs are active.

---

## 3. Handed to you: open work nobody is doing

In priority order.

### 3.1 Staging and production setup for the loop (owner ops)

1. **Staging auto-migrate.** `.github/workflows/migrate-staging.yml` only runs when the `STAGING_SUPABASE_DB_URL` secret is set (feed #71). Check it's set before PR #673 merges, because the 9 learning migrations above apply on merge. If it isn't set, run by hand: `dotenv -f .env.staging run -- python -m db.migrate`.
2. **Staging env (spec §7 table, A14).**
   - Set `LEARNING_LOOP_ENABLED=true` on staging once PKG-07 is merged.
   - Turn the loop on for staff/QA accounts only, by SQL: `update user_settings set learning_loop_beta = true where user_id in (…)`. Upsert the row if it's missing. There is no API or UI for this, by design (A31).
   - Note: with the flag on, every staging upload drafts check items.
3. **Production.** Leave `LEARNING_LOOP_ENABLED` unset during the build. **Pin it to `false` before PR #673 merges** (§11.7 step 1). The first `make promote` after PKG-14 half B ships the ungated changes to every production student, whatever the pin says; read the §11.7 opening paragraph before you promote.
4. **Platform budget alert.** Choose the production `PLATFORM_DAILY_BUDGET_USD`. Then confirm on staging that an `ai.budget_capped{scope: platform}` event reaches you (§11.1 item 4).

### 3.2 Confirm the real AI bill (cost plan check)

Run the `llm_usage` cost rollup on staging and on production. Use the admin analytics page (`/api/admin/analytics`) or SQL grouped by `task` and model, before and after the loop is enabled for staff. Compare against the plan: about $0.36 per student-month, and about $0.00014 per grade.

- **Before the fix:** the class-summary regeneration was the dominant cost. With the loop off, legacy behaviour is unchanged, so check how much it costs today.
- **Check these tasks:** confirm the new `llm_usage` columns (`cached_tokens`, `thinking_tokens`) fill in. Confirm the tier slots appear by name in `task`.

### 3.3 Pre-existing bug: gradebook term chip race

`frontend/e2e/gradebook.spec.ts:35` fails on fast machines. It passes in CI.

- **Cause** (`Landing.tsx`): the demo term chips render while `userId` is still `''`. A click on "Fall 2025" is then undone when the terms load and call `setSelected(currentTerm)`, back to Spring 2026.
- **Fix:** don't let the terms load overwrite a selection the user already made, or don't render clickable chips until the terms have loaded. Add a regression journey (`docs/e2e-exploration.md` §7–§8).
- This isn't part of the learning loop, but it makes local E2E runs noisy.

### 3.4 Local tooling on macOS

- `make explore` / `scripts/explore.sh` don't work on macOS: the lock holder runs `sleep infinity`, which macOS rejects, and `mint_storage_state` hard-codes `localhost:3000`.
- `tools/e2e-env.macos.sh` is the working macOS setup used for this series: Colima, Supabase CLI 2.116.0, bash 5, and shims for `flock`, `setsid`, and uvicorn port 5000 held by AirPlay. Worth folding into `docs/local-supabase.md` and the scripts properly.

### 3.5 Decide: decisions-eval injection baseline

`tests/evals/decisions.py` measures the raw model and keeps `InjectionHeld` at 0.750. The served grading path is gated at 1.0 in the grader eval. This is on purpose: it's the baseline a future Jev backend (PKG-15) is compared against.

**Decide:** keep the raw-model baseline, or route the decisions eval's grading rows through `grade()` and re-record the cassettes.

### 3.6 PKG-15: Jev backend (post-series)

The decision seam (PKG-05b) is ready. Jev can't be built until:
1. there's a Typesafe contract or early-access key;
2. the A24 privacy gate is passed. Zero data retention is enterprise-only, and the under-18 terms matter because student text would be sent.

Owner and legal work first. The prompt shape is in spec A24/§14; research is in the cost/Jev report.

### 3.7 Canopy prompt library is stale

The 30 `learning-loop-pkg-NN-*` prompts in Canopy's Prompt Library are from before the 2026-09-27 amendments (A14–A37) and the two new packages (05b, 06b). The repo files in this folder are the current ones. Re-sync the library from the repo, or retire it.

### 3.8 Human review of PR #673

The PR is large: about 166 files. CodeRabbit **paused** its reviews while the branch was changing fast.

- **Start now** with the merged packages: 00–06b and 11. Go commit by commit in package order; each fix is its own `fix(learning-loop): PKG-NN — …` commit.
- **After the build finishes:** post `@coderabbitai review` and triage its findings the same way (root-cause fixes, no accepted gaps).

---

## 4. If the running build stops

If the automated build stops before PKG-14 is merged (for example, the build machine's session ends), the remaining packages become yours.

1. Find the first package whose latest LEDGER row is not `verified`.
2. Check for pushed work on its lane branch `feat/learning-loop-NN-<slug>`.
3. For `fix/coderabbit-r2` or `fix/mc-reason-options`, if unmerged, finish them first. PKG-07 depends on both.

**Order** (spec §14): 07 → 08 → 09 → 10 → 12 → 13 → 14.
- 12 needs 05, 06b, 07 and 11, so it can run in parallel with 08–10.
- 13 needs 08, 09, 10 and 12. 14 needs everything.

**Per package:**
1. Create the lane:
   ```
   git fetch origin
   git worktree add -b feat/learning-loop-NN-<slug> ../ll-NN origin/feat/learning-loop
   ```
2. Open a fresh Claude Code session in that worktree.
3. Paste the whole `PKG-NN-<slug>.md`, followed by the session overrides and the package notes below.
4. Before merging:
   - three independent reviews;
   - fixes test-first;
   - one E2E cycle on a fresh DB.
5. Merge:
   ```
   git merge --no-ff feat/learning-loop-NN-<slug>
   ```
   For LEDGER/HANDOFF conflicts, keep every row, in order. For code conflicts, keep both sides.
6. Run the full suite, push `feat/learning-loop`, and append a `NN | verified` ledger row.

### Session overrides (paste after the prompt)

```
SESSION OVERRIDES (these beat the prompt file and the README):
1. Branch: you are on feat/learning-loop-NN-<slug>, cut from feat/learning-loop (PR #673), which already has every earlier package. Where the prompt says "branch from main" or "open a PR", read "feat/learning-loop" and "PR #673". Do not push or merge; the last step is the hand-off + ledger commit.
2. Tests: cd backend && venv/bin/python -m pytest tests/ -q -p no:cacheprovider --ignore=tests/evals --ignore=tests/test_docling_integration.py --ignore=tests/test_ocr_pipeline.py --ignore=tests/test_extraction_backends.py → 0 failures. Run targeted tests + tests/test_learning_loop_invariants.py + ruff after every task. Frontend: npm run typecheck && npm run lint && npm test when frontend/ changes.
3. Secrets: never print or commit .env values; git diff --cached | grep -cE "AIza[S]y|GOC[S]PX" must be 0 before every commit; stage explicit paths only.
4. E2E: one whole cycle (e2e-up → playwright → oracles → e2e-down) under the machine lock when the prompt's self-check needs it; replay migrations from an empty DB when the package adds one.
5. Evals: only this package's own dataset, ≤ 8 cases, real GEMINI_API_KEY; never re-record another dataset.
6. Precedence: spec §13 (A1–A37) > earlier HANDOFF files and the code on disk > this prompt. Record every adaptation as a Deviation. A package's ledger state is its LATEST row.
7. Scope: only this package's Files lists, LEDGER.md, HANDOFF-NN.md, and earlier-package reopens per the README protocol.
8. No accepted gaps: if a rule keeps failing review on edge cases, replace it with structured data and a §13 row; never merge with open critical/major findings.
```

### Package notes: decisions already made

**PKG-07:**
- `gates.is_genuine_attempt(matched_non_attempt=gates.has_non_attempt_phrase(text))` — never `matches_non_attempt`. `non_attempt_phrases` is only for grade-or-idk routing of explicit submissions (A16).
- `leak.detect_leak` / `strip_leak` take the item's decrypted `final_answer` (required) and `canonical_answer` (when present) as keyword arguments (A34). Never derive a final answer from reference text.
- `/check/answer` handles a grader-guard refusal as: no credit, no evidence, not a genuine attempt, and a "please answer in your own words" reply (A33).

**PKG-12:** build it only against what PKG-07 and PKG-11 shipped.

**PKG-13:**
- Build the loop UI (Learn + Study) to the spec §11.3 bar.
- Write Playwright journeys that assert database state.
- The rich seed has **no `course_chunks` and no `user_settings` rows**, so seed both for the loop journeys: a staff `learning_loop_beta` row and indexed chunks.

**PKG-14:**
- The owner's go-ahead to make the loop the default is given. Do half A, then half B, in the same run. Half B's commits come after every half A commit, so half B can be reverted on its own.
- Verify both E2E lanes locally:
  - the default lane, with no opt-in;
  - the kill-switch lane, with `LEARNING_LOOP_ENABLED=false`.
- The staging, production and cost-approval steps are the owner's (§11.7, and 3.1 above). List them unchecked in HANDOFF-14.
- Do not add `loop_arm` to the student settings API (same reason as A31).

**Tools:**
- `tools/e2e-env.macos.sh`: the macOS stack. `e2e_cycle <worktree> [playwright args]`, with `E2E_FRESH_DB=1` and `E2E_MID_HOOK`.
- `tools/build-dag.workflow.js`: the Claude Code Workflow script behind this build. Set `repo`, `scratch` and `integration_worktree` in its args.
- Linux uses Podman per `docs/local-supabase.md`.

## Owner launch steps (spec §11.7), after PKG-14 is merged into the PR

1. Pin production `LEARNING_LOOP_ENABLED=false` and set the platform budget alert.
2. Merge PR #673; staging picks it up and auto-migrates.
3. On staging, run the check-items backfill, the smoke test (probe → plan → teach → check → close) and the kill-switch drill.
4. Approve the cost against the ≈ $0.36 per student-month target.
5. `make promote`, then the production backfill (`--all-courses`), then unpin.
6. Watch the abort criteria for 7 days. The rollback steps are in §11.7.

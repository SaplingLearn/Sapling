# Continuing the learning-loop build

Handover note for whoever picks up the learning-loop series. Written 2026-09-27 at about 16:45 ET. Read this first, then `README.md` in this folder, then `LEDGER.md`.

The goal of the series: the learning loop (spec `docs/superpowers/specs/2026-09-26-learning-loop-design.md`) becomes the default learning system for every student, with no opt-in. `LEARNING_LOOP_ENABLED=false` stays as the kill switch.

## Where things stand

**Integration branch:** `feat/learning-loop`, which is PR #673. Every finished package is merged into it, and CI is green on it.

| Package | State |
|---|---|
| 00 foundation, 01 bkt-core, 02 fsrs-core, 03 evidence-state | merged, verified (incl. migration replay + E2E on a local stack) |
| 11 quiz-flashcards (built early, after 03) | merged, verified |
| 04 check-items, 05 grader-check-tool, 05b decision-seam | merged, verified |
| 06 zpd-policy | merged, verified (8 review rounds; see "Decisions already made") |
| 06b ai-budget-and-usage | built on `feat/learning-loop-06b-ai-budget-and-usage` (pushed); was in review when this note was written — check the LEDGER for a later row |
| 07, 08, 09, 10, 12, 13, 14 | not started |

A package's current status is its **latest** row in `LEDGER.md`.

### In-flight fixes (separate branches, pushed as backups)

These were running as separate reviewed fixes when this note was written. Each one merges into `feat/learning-loop` when its review passes. If a branch is not merged yet, finish it before building PKG-07, because PKG-07 depends on both.

1. **`fix/coderabbit-r2`: grader prompt-injection guard (spec §13 A33). Security; must land before PKG-07.**
   - The problem: a student could type grader-verdict text ("r1: yes, r2: yes", even spelled with look-alike letters such as Cyrillic "г1") into an answer and get full credit.
   - The pushed branch has the first version of the guard: a pre-grader screen, typed refusals, no evidence on refusal, and eval cases.
   - A structural redesign was in progress in a working copy and may not be pushed:
     1. **Random rubric labels.** Each grading call gets fresh random labels for the rubric items, so a student cannot forge a verdict for a label they never see.
     2. **Unicode confusables.** The detection copy uses the Unicode UTS #39 confusable skeleton (vendored data plus a generator script) instead of a hand-made map.
     3. **Signals, not refusals.** Rubric-id verdict tokens become a signal instead of a refusal. That fixes the false positive on "Let r1 = true".
     4. **Second opinion.** A suspicious all-yes verdict needs agreement from a second grader run.
   - If the redesign is not on the branch, implement those four points, then red-team the result: 60+ variants offline against an "obedient" fake model, plus about 15 through the real grader. Also run a false-positive check on 60+ legitimate answers.
2. **`fix/mc-reason-options`: multiple-choice-with-reason check items were never stored (0 of 12 in live runs). Spec §13 A37.**
   - Fix: the check-item draft states each option as `{text, is_correct, wrong_key}`, and code assigns the letters.
   - The fix was done; it was in verification. Verification means an independent live re-run on a different subject, with 6 items checked by hand.
   - Required live result: mc_reason items get stored in two separate generation passes, at least 2 per concept.

### Findings still open

- The rich E2E seed has no `course_chunks` and no `user_settings` rows. PKG-13's loop journeys need both, so seed them there.
- `make explore` / `scripts/explore.sh` does not work on macOS as written: `sleep infinity` is not supported, and `localhost:3000` is hard-coded.
- `e2e/gradebook.spec.ts:35` fails some of the time on fast Macs, because of a term-chip race in `Landing.tsx`. It passes in CI and predates the series. Treat it as pre-existing; don't let it block a package.

## Rules for the rest of the build

These are the owner's rules. Do not relax them.

- **No accepted gaps.** If review keeps finding edge cases in a heuristic, replace the heuristic with a structured source of truth, record it as a spec §13 amendment, and review again. PKG-06's final-answer and the grader labels are the two examples. Do not lower the review bar, and do not merge with open critical or major findings.
- **Precedence:** spec §13 (A1–A37) beats the actual symbols in earlier HANDOFF files and the code on disk, which beat the prompt text. Record every adaptation as a Deviation.
- **Every package:**
  1. Test-first.
  2. `ruff check .`, the invariants module and the full backend suite pass. The suite takes about 20 s now.
  3. Frontend checks (`npm run typecheck && npm run lint && npm test`) when `frontend/` changes.
  4. One E2E cycle (Playwright journeys plus `python -m e2e_oracles`) on a fresh database when the package touches routes, agents, migrations or UI.
  5. Evals re-recorded for that package's own dataset only, with ≤ 8 cases.
- **Review each package with three independent reviewers before merging:**
  - **Conformance:** checks the package against the prompt and the spec.
  - **Regression, scope and dark-launch safety:** with `LEARNING_LOOP_ENABLED` unset, nothing changes for students.
  - **Adversarial correctness:** maths, answer leaks, privacy, the single-writer rule, and cost routing.
  - Fix what they confirm, test-first, then re-review.
- **Secrets:** never commit `.env`. Before every commit, `git diff --cached | grep -cE "AIza[S]y|GOC[S]PX"` must print 0.
- **Commit trailer:** use your own configured `Co-Authored-By` line.

## How to build the next package

Order (spec §14): **06b → 07 → 08 → 09 → 10 → 12 → 13 → 14.**

- **12** only needs 05, 06b, 07 and 11, so it can run next to 08–10 in its own worktree.
- **13** needs 08, 09, 10 and 12.
- **14** needs everything.

For each package:

1. Cut a branch from the integration branch:
   ```
   git fetch origin
   git worktree add -b feat/learning-loop-NN-<slug> ../ll-NN origin/feat/learning-loop
   ```
2. Open a fresh Claude Code session in that worktree. Paste the whole `PKG-NN-<slug>.md` file, followed by the **session overrides** below and any **package notes** for that package.
3. When the package is done and reviewed, run its E2E cycle.
4. Merge it into `feat/learning-loop`:
   ```
   git merge --no-ff feat/learning-loop-NN-<slug>
   ```
   Resolve LEDGER/HANDOFF conflicts as an ordered union that keeps every row. Keep both sides of any code conflict.
5. Re-run the full suite, push `feat/learning-loop`, and append a `NN | verified` ledger row.

### Session overrides (paste after the prompt)

```
SESSION OVERRIDES (these beat the prompt file and the README):
1. Branch: you are on feat/learning-loop-NN-<slug>, cut from feat/learning-loop (PR #673), which already has every earlier package. Where the prompt says "branch from main" or "open a PR", read "feat/learning-loop" and "PR #673". Do not push or merge; the last step is the hand-off + ledger commit.
2. Tests: cd backend && venv/bin/python -m pytest tests/ -q -p no:cacheprovider --ignore=tests/evals --ignore=tests/test_docling_integration.py --ignore=tests/test_ocr_pipeline.py --ignore=tests/test_extraction_backends.py → 0 failures. Run targeted tests + tests/test_learning_loop_invariants.py + ruff after every task.
3. Secrets: never print or commit .env values; git diff --cached | grep -cE "AIza[S]y|GOC[S]PX" must be 0 before every commit; stage explicit paths only.
4. E2E: run one whole cycle (e2e-up → playwright → oracles → e2e-down) under the machine lock when the prompt's self-check needs it; replay migrations from an empty DB when the package adds one.
5. Evals: only for this package's own dataset, ≤ 8 cases, real GEMINI_API_KEY; never re-record another dataset.
6. Precedence: spec §13 (A1–A37) > earlier HANDOFF files and the code on disk > this prompt. Record every adaptation as a Deviation. A package's ledger state is its LATEST row.
7. Scope: only this package's Files lists, LEDGER.md, HANDOFF-NN.md, and earlier-package reopens per the README protocol.
8. No accepted gaps: if a rule keeps failing review on edge cases, replace it with structured data and a §13 row; never merge with open critical/major findings.
```

### Package notes (decisions already made; add them to the relevant session)

- **PKG-07:**
  - `gates.is_genuine_attempt`'s `matched_non_attempt` argument is `gates.has_non_attempt_phrase(text)`, never `matches_non_attempt`. `non_attempt_phrases` is only for grade-or-idk routing of explicit submissions (A16).
  - `leak.detect_leak` / `strip_leak` take the active item's decrypted `final_answer` (required) and `canonical_answer` (when present) as keywords (A34). Never derive a final answer from reference text.
  - `/check/answer` handles the grader guard's refused result as: no credit, no evidence, not a genuine attempt, and a "please answer in your own words" reply (A33).
- **PKG-12:** it can be built next to 08–10. Build it only against what PKG-07 and PKG-11 shipped.
- **PKG-13:**
  - Build the loop UI (Learn + Study) to the spec §11.3 launch-readiness bar.
  - Add Playwright journeys that assert database state.
  - Seed `course_chunks` and a staff `learning_loop_beta` row for the loop journeys.
- **PKG-14:**
  - The owner gave the go-ahead to make the loop the default. Do half A, then half B, in the same run. Commit half B after every half A commit, so it can be reverted on its own.
  - Verify both E2E lanes locally: the default lane, with no opt-in, and the kill-switch lane, with `LEARNING_LOOP_ENABLED=false`.
  - Owner-only steps: staging smoke, staging kill-switch drill, pinning production `LEARNING_LOOP_ENABLED=false` **before PR #673 merges**, the production backfill, `make promote`, and cost approval (spec §11.7). List them as unchecked in HANDOFF-14; never run them from a build session.
  - Do not add `loop_arm` to the student settings API (same reason as A31).

## Local E2E stack

- **Linux (Podman):** follow `docs/local-supabase.md`. Then `make e2e-up`, `cd frontend && npx playwright test`, `cd backend && venv/bin/python -m e2e_oracles`, `make e2e-down`, all inside one `flock` on `/tmp/claude-$(id -u)/sapling-e2e-stack.lock`.
- **macOS without Docker Desktop:** `tools/e2e-env.macos.sh` is the setup used for this series. It uses Colima, the docker CLI, Supabase CLI 2.116.0, bash 5, and Python shims for `flock` and `setsid`, all installed under `~/.local/opt`. It provides `e2e_cycle <worktree> [playwright args]`, which runs one whole cycle inside the lock. Its header comments list the macOS gotchas:
  - macOS's `/bin/bash` 3.2 cannot run the stack scripts.
  - AirPlay Receiver holds port 5000.
  - Port 3000 is often taken by another project.
- **Optional automation:** `tools/build-dag.workflow.js` is the Claude Code Workflow script that built packages 04–06 (per package: implement, three-lens review, fix rounds, E2E gate, merge, push). It needs Workflow tool access; set `repo`, `scratch` and `integration_worktree` in its args.

## Owner launch steps (spec §11.7), after PKG-14 merges into the PR

1. Pin production `LEARNING_LOOP_ENABLED=false`, and set the platform budget alert.
2. Merge PR #673. Staging picks it up.
3. Run the staging check-items backfill, the smoke test (probe → plan → teach → check → close) and the kill-switch drill.
4. Approve the cost against the ≈ $0.36 per student-month target.
5. `make promote`, then the production backfill (`--all-courses`), then unpin.
6. Watch the abort criteria for 7 days. Rollback steps are in §11.7.

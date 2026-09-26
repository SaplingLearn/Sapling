# Learning Loop — series ledger (append-only)

Rules: read this file first; refuse to start if any earlier package is `blocked` or `in-progress`. A package marks itself `done`; only the next package that depends on it marks it `verified` after running its State-of-the-world rows. Never rewrite an earlier row — a change of state is a new row. Status enum: `planned | in-progress | done | verified | blocked | reopened`.

| pkg | slug | status | branch | head SHA | tests added | verified-by (pkg, date, command → output) | handoff |
|---|---|---|---|---|---|---|---|
| 00 | foundation | planned | | | | | |
| 01 | bkt-core | planned | | | | | |
| 02 | fsrs-core | planned | | | | | |
| 03 | evidence-state | planned | | | | | |
| 04 | check-items | planned | | | | | |
| 05 | grader-check-tool | planned | | | | | |
| 06 | zpd-policy | planned | | | | | |
| 07 | loop-tutor | planned | | | | | |
| 08 | probe-planner | planned | | | | | |
| 09 | close-brief | planned | | | | | |
| 10 | misconceptions | planned | | | | | |
| 11 | quiz-flashcards | planned | | | | | |
| 12 | review-surfaces | planned | | | | | |
| 13 | frontend-e2e | planned | | | | | |
| 14 | eval-ladder-cutover | planned | | | | | |
| 00 | foundation | done | feat/learning-loop-00-foundation | 8409f89 | 5 modules (30 passed + 8 skipped placeholders) | — | HANDOFF-00.md |

## Deviations

Format: `PKG-NN: <spec said> → <did instead> → <why> → <† if an A/B flag stays open>`

- Series executed on stacked branches (feat/learning-loop-series → NN…); PRs opened after review, not between packages.
- PKG-00: acceptance 1 / Verify line `tests/test_learning_gate.py → 11 passed` → the prompt's test code collects 13 (6 + 3 parametrized + 4) and all pass; HANDOFF-00 Verify says `13 passed` → arithmetic slip in the prompt; later prompts that copy `11 passed` (PKG-01/02/03/04) should expect 13.
- PKG-00: invariants module had `import os` → dropped → unused; `ruff check .` F401 would fail.
- PKG-00: gate tests as written → added autouse `_restore_flag_after_reload` fixture in tests/test_learning_gate.py → `importlib.reload(config)` under `true` would leave `config.LEARNING_LOOP_ENABLED=True` for every later test module; assertions unchanged.
- PKG-00: Behaviour 7 "every §2 module stubbed" → only the Task 6 list is stubbed (pre-existing from da22ee8, verified docstring-only); §2 scripts and §13 A12 modules are not → their owning prompts `Create:` them; outside this package's Files list.
- PKG-00: full suite `pytest tests/ -q` → run with `--ignore=tests/evals --ignore=tests/test_docling_integration.py --ignore=tests/test_ocr_pipeline.py --ignore=tests/test_extraction_backends.py -p no:cacheprovider` → OCR stack not installed on the executing machine (baseline N₀ = 2708 passed, 135 skipped under that command).
- PKG-00: migration applied + E2E cycle → not run; needs local Supabase stack (supabase start): apply 20260926231744_learning_loop_beta.sql via `python -m db.migrate` and confirm settings GET returns `learning_loop_beta` → no supabase CLI / podman / docker on the executing machine; hermetic file-invariant tests only.
- PKG-00: Task 7 `gh pr create` → skipped → stacked-branch run; PRs opened after review.

## Blocked notes

Format: `PKG-NN <date>: hypothesis · commands run · outputs · what the next human should decide`

(none yet)

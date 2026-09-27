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
| 00 | foundation | done | feat/learning-loop-00-foundation | 93b38e9 | 6 modules (40 passed + 8 skipped placeholders; review fixes 76428bb..93b38e9) | — | HANDOFF-00.md |
| 01 | bkt-core | done | feat/learning-loop-01-bkt-core | 1b6d5ef | tests/test_learning_bkt.py (153) + inv_03 | — | HANDOFF-01.md |
| 00 | foundation | verified | feat/learning-loop-00-foundation | 93b38e9 | 6 modules (40 passed + 8 skipped placeholders; review fixes 76428bb..93b38e9) | PKG-01 2026-09-26 (base 3d1c7db): tests/test_learning_gate.py → 13 passed; invariants → 4 passed, 8 skipped; deps/settings/migration → 13 passed; flag grep → 1 hit; migration ls → 1 file; full suite → 2748 passed, 143 skipped | HANDOFF-00.md |

## Deviations

Format: `PKG-NN: <spec said> → <did instead> → <why> → <† if an A/B flag stays open>`

- PKG-00: README "branch from `main`, never stacked" → series executed on stacked branches (feat/learning-loop-series → NN…), PRs opened after review, not between packages → session override for the whole series run.
- PKG-00: acceptance 1 / Verify line `tests/test_learning_gate.py → 11 passed` → the prompt's test code collects 13 (6 + 3 parametrized + 4) and all pass; HANDOFF-00 Verify says `13 passed` → arithmetic slip in the prompt; every later prompt copies `11 passed` and should expect 13: the State-of-the-world rows PKG-01:34, 02:36, 03:34, 04:48, 05:35, 06:34, 07:42, 08:31, 09:43, 10:41, 11:51, 12:34, 13:47, 14:43; the verified-row templates PKG-01:1097, 02:1189; and the regression guards `(11)` at PKG-01:1147, 02:1237. A 13-vs-11 mismatch there is this deviation, not a red row.
- PKG-00: invariants module had `import os` → dropped → unused; `ruff check .` F401 would fail.
- PKG-00: gate tests + inv_11 reload `config` directly → both use `reload_gate` (in the invariants module), which stubs `dotenv.load_dotenv` for the reload and restores every config/gate attribute on undo → the import-time `load_dotenv()` put back `LEARNING_LOOP_ENABLED=true` from backend/.env in the "unset" cases, and reloads leaked their flag value into later tests (the earlier autouse fixture covered only the gate module and is removed); assertions unchanged.
- PKG-00: Task 5 asked for assertions (a)/(b)/(c) → test_learning_settings_flag.py also asserts GET returns the key, PATCH `false` is written, the toggle schedules neither `update_course_context` nor `resync_user_chunk_visibility`, and the model defaults; (c) widens `UpdateSettingsBody.model_dump` → cheap regression guards; pydantic's `extra='ignore'` made the as-written (c) vacuous (it passed with the whitelist deleted).
- PKG-00: migration comment line 1 `-- <ts>_learning_loop_beta.sql` → `-- 20260926231744_learning_loop_beta.sql` → placeholder filled with the real prefix.
- PKG-00: inv_11 spied only on `learning.gate.table` → inv_11 and the env-off gate tests also assert that no call reached the hermetic DB client; `_Boom` records instead of raising → the gate swallows exceptions, so a gate that dropped the flag check and read via `db.connection.table` passed.
- PKG-00: inv_02 `_imports_of` regex (first dotted name per line) → an ast walk that is transitive over `learning` imports (same signature) → `import math, db.connection`, `from .gate import …` and `from learning import gate` passed before. `import ast` is now module-level, so PKG-03/06 skip their "add `import ast`" step (F811).
- PKG-00: inv_08 as written → it also warns in a shallow clone (no skip or fail) → in CI's depth-1 checkout the `--diff-filter=M` half is vacuous; `fetch-depth: 0` in ci.yml is an open question in HANDOFF-00.
- PKG-00: test modules → added tests/test_learning_invariants_meta.py (10; inside the `test_learning_*.py` glob) → it pins the helpers above without moving the pinned counts (gate 13, invariants `4 passed, 8 skipped`).
- PKG-00: Behaviour 7 "every §2 module stubbed" → only the Task 6 list is stubbed (pre-existing from da22ee8, verified docstring-only); §2 scripts and §13 A12 modules are not → their owning prompts `Create:` them; outside this package's Files list.
- PKG-00: full suite `pytest tests/ -q` → run with `--ignore=tests/evals --ignore=tests/test_docling_integration.py --ignore=tests/test_ocr_pipeline.py --ignore=tests/test_extraction_backends.py -p no:cacheprovider` → OCR stack not installed on the executing machine (baseline N₀ = 2708 passed, 135 skipped under that command; after PKG-00 + review fixes, 2748 passed, 143 skipped). This is CI's own ignore set. The literal `pytest tests/ -q` fails exactly 4 tests, all in the untouched `test_extraction_backends.py` (docling/transformers not installed), and they fail the same way on the base.
- PKG-00: acceptance 6 / self-check 6 `git diff --stat main...HEAD` → measured against `feat/learning-loop-series..HEAD` → the stacked run makes the diff against main include the planning base. Against the series base, every path is in the Files lists.
- PKG-00: migration applied + E2E cycle → not run; needs local Supabase stack (supabase start): apply 20260926231744_learning_loop_beta.sql via `python -m db.migrate` and confirm settings GET returns `learning_loop_beta` → no supabase CLI / podman / docker on the executing machine; hermetic file-invariant tests only.
- PKG-00: Task 7 `gh pr create` → skipped → stacked-branch run; PRs opened after review.
- PKG-01: branch from `main` → `feat/learning-loop-01-bkt-core` cut from `feat/learning-loop-00-foundation` HEAD 3d1c7db → stacked series run (see the PKG-00 stacked-branch line).
- PKG-01: SoW row / verified-row template `tests/test_learning_gate.py → 11 passed` → observed and recorded `13 passed` → PKG-00's recorded arithmetic-slip deviation, not a red row.
- PKG-01: full suite `pytest tests/ -q` (SoW `-q -x`) → run with `-p no:cacheprovider --ignore=tests/evals --ignore=tests/test_docling_integration.py --ignore=tests/test_ocr_pipeline.py --ignore=tests/test_extraction_backends.py` → OCR stack not installed (session override; CI's ignore set). N₀ = 2748 passed, 143 skipped; after PKG-01, 2902 passed, 142 skipped.
- PKG-01: acceptance 8 / self-check 6 `git diff --stat main...HEAD` → measured as `git diff --stat feat/learning-loop-00-foundation..HEAD` → stacked run; against the PKG-00 head the diff is exactly the six listed paths.
- PKG-01: commit trailer `Claude Fable 5.1` → `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>` → session override.
- PKG-01: Task 7 `git push` / `gh pr create` → skipped → stacked-branch run; PRs opened after review.

## Blocked notes

Format: `PKG-NN <date>: hypothesis · commands run · outputs · what the next human should decide`

(none yet)

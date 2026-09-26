# HANDOFF-00 — foundation

Written by the session that executed `PKG-00-foundation.md`. Read by every later package that depends on 00. Keep every heading, even if the answer is "none".

## What changed

`config.LEARNING_LOOP_ENABLED` exists and is `True` only for a case-insensitive `"true"` in the env var of the same name; unset, `"false"`, `"0"`, `""`, `"yes"` are all off. `learning.gate.learning_loop_active(user_id)` returns `False` without touching the database when the flag is off, and otherwise reads `user_settings.learning_loop_beta` through `db.connection.table()`; a missing row, a missing key, or any read exception is `False` (the exception is logged at WARNING and never raised). The migration `20260926231744_learning_loop_beta.sql` adds `user_settings.learning_loop_beta boolean NOT NULL DEFAULT false`. The column is selected by `GET /api/profile/{user_id}/settings` (via `_SETTINGS_COLS`) and whitelisted in `PATCH /api/profile/{user_id}/settings`; toggling it does not schedule the #72 class-context refresh or the #629 chunk-visibility resync. `SaplingDeps` carries three inert loop fields; no existing field or default changed and no consumer reads them yet. No route calls the gate and `routes/learn_loop.py` is not mounted, so product behaviour is unchanged with the flag on or off. `tests/test_learning_loop_invariants.py` lists all twelve spec §8 invariants: 02, 07, 08, 11 are asserted, the other eight are `pytest.skip("asserted by PKG-NN")` placeholders. Every module in the Task 6 stub list exists as a docstring-only stub (they came from the planning commit `da22ee8` and were verified, not recreated).

## Symbols added

- `backend/config.py::LEARNING_LOOP_ENABLED` — module-level bool; `os.getenv("LEARNING_LOOP_ENABLED", "false").strip().lower() == "true"`.
- `backend/learning/gate.py::learning_loop_active(user_id: str) -> bool` — env AND `user_settings.learning_loop_beta`; fails closed; never raises; zero DB reads when the env flag is off. Module-level `table` import is the spy point tests patch (`learning.gate.table`).
- `backend/learning/gate.py::logger` — `logging.getLogger("sapling.learning.gate")`.
- `backend/agents/deps.py::SaplingDeps.learning_loop: bool = False` — result of the gate for this request.
- `backend/agents/deps.py::SaplingDeps.loop_state: Any = None` — the session's typed loop state (PKG-06); None on the legacy path.
- `backend/agents/deps.py::SaplingDeps.pending_evidence: list = field(default_factory=list)` — Evidence dicts for the ROUTE to persist via `apply_graph_update`; per-instance.
- Column `user_settings.learning_loop_beta boolean NOT NULL DEFAULT false` — migration `backend/db/migrations/20260926231744_learning_loop_beta.sql`.
- `backend/routes/profile.py::_SETTINGS_COLS` — now includes `learning_loop_beta`; `update_settings` `ALLOWED` includes `"learning_loop_beta"`.
- `backend/models/__init__.py::UpdateSettingsBody.learning_loop_beta: Optional[bool] = None`; `SettingsResponse.learning_loop_beta: bool = False`.
- `backend/tests/test_learning_loop_invariants.py` — `test_inv_01` … `test_inv_12` (names `test_inv_NN_<slug>`); helpers `_imports_of`, `PURE_MODULES`, `FORBIDDEN_IMPORT_ROOTS`, `LEARNING`, `MIGRATIONS`, `BACKEND`.
- Tests: `tests/test_learning_gate.py` (13), `tests/test_learning_deps.py` (3), `tests/test_learning_settings_flag.py` (7), `tests/test_learning_loop_beta_migration.py` (3).

## Constants chosen

None. `LEARNING_LOOP_ENABLED` is a config flag, not a learning constant; `backend/learning/params.py` is still a PKG-01 stub.

## Deviations from spec

- Acceptance criterion 1 / Verify line 1 said `tests/test_learning_gate.py → 11 passed` → the prompt's own test code collects 13 (6 env-off params + 3 env-on params + 4 single tests) and all 13 pass; the Verify line below says `13 passed` → the prompt's count was an arithmetic slip; the tests were kept exactly as written rather than dropping parametrize cases to hit 11. Later prompts that copy `11 passed` (PKG-01/02/03/04 State of the world) should read `13 passed`.
- Task 1 module had `import os` → dropped it → it is unused, and `ruff check .` (F401) would fail on it.
- Task 3 test file → added an autouse `_restore_flag_after_reload` fixture to `tests/test_learning_gate.py` → `importlib.reload(config)` under `LEARNING_LOOP_ENABLED=true` leaves `config.LEARNING_LOOP_ENABLED = True` after monkeypatch restores the env var, which would leak the flag ON into every later test module once routes call the gate (PKG-07+). The fixture re-evaluates config and the gate against the original env after each test. Assertions unchanged.
- Task 5 asked for assertions (a)/(b)/(c) → `tests/test_learning_settings_flag.py` also asserts GET returns the key, PATCH `false` is written, flipping the flag schedules neither `update_course_context` nor `resync_user_chunk_visibility`, and the model defaults → cheap regression guards; additive only.
- Spec Behaviour 7 says every §2 module exists as a stub → only the Task 6 file list is stubbed; `backend/scripts/backfill_check_items.py` (PKG-04), `backend/scripts/derive_zpd_metrics.py` (PKG-14) and the §13 A12 additions (`learning/loop_state_store.py`, `learning/zpd_events.py`, `agents/session_close.py`, `frontend/.../loopState.ts`, `DueQueue.tsx`) are not stubbed → their owning prompts `Create:` them, and this package's Files list does not include them.
- Migration comment line 1 is `-- <ts>_learning_loop_beta.sql` in the prompt → written as `-- 20260926231744_learning_loop_beta.sql` → the placeholder filled with the real prefix.
- Full suite command → run as `venv/bin/python -m pytest tests/ -q -p no:cacheprovider --ignore=tests/evals --ignore=tests/test_docling_integration.py --ignore=tests/test_ocr_pipeline.py --ignore=tests/test_extraction_backends.py` → the OCR stack is not installed on the executing machine (session override).
- Task 7 Step 3 PR → not opened → session override: series executed on stacked branches, PRs opened after review.

## Known gaps

- needs local Supabase stack (supabase start): apply `20260926231744_learning_loop_beta.sql` with `python -m db.migrate` against a real Postgres and confirm `GET /api/profile/{id}/settings` returns `learning_loop_beta: false` for a fresh user. No supabase CLI / podman / docker on the executing machine; the migration is proven only by the hermetic file-invariant tests.
- E2E lanes (Playwright Chapter 1 + oracles) not run for the same reason. No request-path agent or route behaviour changed, so the prompt's self-check item 5 already skips E2E; the only E2E-visible change is the settings payload gaining one key.
- Deploy order: `_SETTINGS_COLS` now names `learning_loop_beta`, so `GET/PATCH /api/profile/{id}/settings` returns PostgREST 400 → 500 on any database where this migration has not been applied. Apply the migration BEFORE the code (the promotion runbook already migrates before merge).
- The gate is not called from any route (PKG-07 wires learn, PKG-11 quiz/flashcards).
- Flakes observed: none.

## Verify commands

```
cd backend && venv/bin/python -m pytest tests/test_learning_gate.py -q                          → 13 passed
cd backend && venv/bin/python -m pytest tests/test_learning_loop_invariants.py -q               → 4 passed, 8 skipped
cd backend && venv/bin/python -m pytest tests/test_learning_deps.py tests/test_learning_settings_flag.py tests/test_learning_loop_beta_migration.py -q → all passed
grep -n "^LEARNING_LOOP_ENABLED" backend/config.py                                               → 1 hit
ls backend/db/migrations/*_learning_loop_beta.sql                                                → 1 file
```

## Open questions for the series owner

- Per-request cache for the gate: `services/request_context.py` exposes only the request-id ContextVar (`current_request_id` / `new_request_id`); there is no per-request cache. The gate therefore does one `user_settings` read per call. PKG-07 decides whether to cache it (e.g. compute once at route entry and carry it on `SaplingDeps.learning_loop`, which is what the field is for).
- `learning_loop_beta` is self-service: any signed-in user can PATCH it on through the settings endpoint (spec §7 asks for exactly that). The env flag is the operator-side kill switch. If the beta cohort must be operator-chosen, that is a later change to `ALLOWED`; taken option: follow the spec.

## Post-hoc changes

(Appended by later packages that modified this package's code. Format: `PKG-MM <date>: <what> — commit <sha>`.)

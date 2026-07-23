# Handoff — Epic #402 Wave 2 (subcutaneous lane + model seam)

Prepared 2026-07-23 against `main` @ `5dee71d`, after wave 1 (plumbing) merged.
Everything below the line is the session prompt.

---

Work the next wave of epic #402 (E2E Regression Suite) in the Sapling repo: **#391, #397, then #398**. Do the planning and speccing yourself, use subagents for implementation, open a PR per unit, run tests as you go, and merge each once CI is green.

## Where things stand

`main` is at `5dee71d`. Wave 1 (plumbing) is merged and closed: #378, #379, #381, #382, and #396 (the last closed as already-delivered — no work remained). Baseline on `main` is **1034 passed, 5 skipped, 1 error**. That error is `tests/test_ocr_pipeline.py::test_save_to_db` (`RuntimeError: Event loop`); it is **pre-existing**, appears only when a real `GEMINI_API_KEY` is set, and CI `--ignore`s that file entirely. Confirm it is unchanged, then leave it alone.

## The work

**#391 — pydantic-ai test seam via `FunctionModel` (`SAPLING_MODEL_MODE`).** Backend, now unblocked. Read the comment on the issue first: #379 added an autouse `_hermetic_llm_transport` fixture in `backend/tests/conftest.py` that patches `google.genai._api_client.BaseApiClient` at the class level, and pydantic-ai's `GoogleModel` wraps a `google.genai.Client`, so the agents lane already rides that seam. `FunctionModel` must substitute **above** the transport. If your design needs the guard disabled to work, you are substituting at the wrong layer — rethink rather than weakening the guard.

**#397 — integration fixtures (psycopg, truncate isolation, seeded users).** Backend, now unblocked, and **re-scoped 2026-07-23** — read the current issue body rather than any cached impression of it. The scope is entirely undone. The defining constraint of this lane: **writes go through the app; assertions read back with raw SQL via psycopg.** The four existing tests in `backend/tests/integration/test_local_stack.py` all assert through `db.connection.table()` — the same PostgREST layer that wrote — which tests the echo, not the database. That is precisely what you are fixing.

**#398 — subcutaneous write-path suite.** Sequential, after #397 merges (it needs the raw-SQL seam). Read the context-refresh comment on the issue for corrected facts.

**Parallelism:** #391 and #397 touch disjoint files — run them as two parallel subagents in worktrees branched from `origin/main`. #398 waits for #397.

## How to build this right

This epic exists because 1034 tests currently pass against `MagicMock` DB stubs that agree with whatever the caller asserts. The failure mode you are fighting is **a test that passes without proving anything**. Everything below follows from that.

- **Write the failing test first and watch it fail for the right reason.** A test that has never failed has not been shown to test anything. For #397 especially: before you trust a new raw-SQL assertion, make it fail by writing a deliberately wrong value, and confirm the failure message points at the real cause.
- **Never assert through the layer you are testing.** If the write went through PostgREST, the assertion must not. This is the entire point of #397; a raw-SQL read that happens to go back through `table()` is the bug, not the test.
- **Prefer stable seams and behavioral assertions over framework internals.** Wave 1 lost time to a test asserting route mounting via `client.app.routes`, which flattens included routers on starlette 1.0 but not 1.3 — green locally, red in CI. Assert on what the code *does*, or on a documented stable structure.
- **Evidence before assertions.** Do not claim a suite passes, a lint is clean, or a bug is fixed without pasting the actual command output. "Should work" is not a result. This applies to subagents too — require real output in their reports and check it.
- **Never paper over a failure.** Do not weaken an assertion, widen an exemption, add a `skip`, or disable a guard to make something green. If a wave-1 guard (`_hermetic_llm_transport`, the hermetic Supabase client, the auth bypass) blocks you, that is a design signal — understand why before touching it. If a test genuinely needs an exemption, extend the existing marker set with a documented reason rather than inventing a parallel mechanism.
- **Keep each diff small and single-purpose.** One issue, one PR. Resist fixing adjacent things you notice; file them instead. #398 in particular is expected to surface real bugs — **those findings are the deliverable, not a blocker.** File each as its own issue and keep the suite PR about the suite. A PR that fixes ten unrelated bugs is unreviewable.
- **Push back when the issue text is wrong.** These issues were written against an older tree and some premises have already drifted. If you verify something that contradicts the issue, say so explicitly in the PR body rather than silently implementing the wrong thing or silently doing something else. A wave-1 agent correctly rejected a suggestion of mine (`env -u GEMINI_API_KEY pytest`) by proving `validate_config()` fail-closes without the key — that was the right call and it saved a bad change.
- **Verify against the pinned dependency versions, not just what is installed.** See the skew warning below. Anything reaching into library internals must be checked against `requirements.lock` and should fail loudly if the seam moves, never silently no-op.
- **Match the surrounding code.** These files have a strong house style — long explanatory docstrings that state *why* a guard exists and what invariant it protects, with issue numbers. Follow it. Comments should record constraints the code cannot express, not narrate what the next line does.

## Environment gotchas that will bite you

- **Shell `grep` and `find` are SHADOWED** and silently truncate results (10 hits where there are 81). Use the Grep/Glob tools or `/usr/bin/grep`. Tell every subagent this explicitly.
- **Backend tests:** `/home/andresl/Projects/sapling/backend/venv/bin/pytest tests/ -q`, run from `backend/`. A fresh worktree has **no venv, no `node_modules`, and no `backend/.env`** — use the primary checkout's venv, and supply CI's dummy env values (`SUPABASE_URL`, `SUPABASE_SERVICE_KEY`, `SESSION_SECRET`, `ENCRYPTION_KEY`) or ~2 `test_storage_service` tests fail spuriously.
- **`GEMINI_API_KEY` must stay SET.** `config.validate_config()` fail-closes without it (#174) and one test enters the FastAPI lifespan, so `env -u GEMINI_API_KEY pytest` is not viable and never will be. Since #379 the suite is provably offline anyway with a real key present.
- **The local venv is behind `requirements.lock`, which is what CI installs**: google-genai 1.74.0 vs 2.9.0, fastapi 0.136/starlette 1.0 vs 0.138/1.3. Locally-green is not proof of CI-green. When a test passes locally and fails in CI, **check version skew before assuming flake or test pollution** — reproducing CI's pytest invocation only rules out ordering and env, not package versions.
- **The integration lane needs the local Supabase stack up:** `supabase start` from the repo root (rootless Podman), then `RUN_INTEGRATION=1 pytest -m integration`. See `docs/local-supabase.md` and `scripts/local-up.sh`. After any migrate, PostgREST needs `NOTIFY pgrst, 'reload schema'` or it 404s "not in schema cache".
- **Programmatic auth:** the canonical minter is `backend/services/session_tokens.py::mint_session`. For pytest call it directly; `POST /api/auth/test-login` exists for Playwright and is gated to `APP_ENV in {local, test}`.

## Conventions

Read `CLAUDE.md` at the repo root. Load-bearing ones here: all Supabase access through `db/connection.py::table()`; migrations are append-only and never edited once applied; encryption goes through `services/encryption.py` — `encrypt_if_present` / `decrypt_if_present` for text, `decrypt_numeric` for `assignments.points_*`, and `encrypt_json` / `decrypt_json` for `sessions.summary_json`; tests live in `backend/tests/`.

## Process

Branch from `origin/main`, not from whatever HEAD happens to be. One PR per unit, conventional-commit messages, ending with `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`. CI must be fully green before merging — including `Backend (pytest)`; do not merge on a partial check list, and if CI never triggers, close/reopen the PR to force it. At the end of the wave, pull and run `/code-review` over the cumulative range.

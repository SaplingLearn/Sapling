# Sapling Backend — Test Suite

All backend tests live here. Tests use **pytest** and mock out Supabase and
Gemini so no live credentials are required (except for the integration tests
marked below).

---

## Quick start

```bash
# From the backend/ directory
cd backend
source venv/bin/activate      # or: fish -c "source venv/bin/activate.fish"

# Run all unit tests (no API key or DB needed)
pytest tests/ -v

# Run a single file
pytest tests/test_graph_service.py -v

# Run a single test
pytest tests/test_quiz_routes.py::TestSubmitQuiz::test_all_correct_returns_full_score -v
```

---

## Fixtures & conftest

`conftest.py` installs two **autouse** safety nets so no unit test touches the
network:

- **Hermetic Supabase** — replaces `db.connection._client` with a stub returning
  empty responses, so any DB call that escapes a test's own `table` mock is
  caught instead of hitting the real project. Tests that need specific rows still
  patch their own `table` / service reference.
- **Session-auth bypass** — stubs `require_self` / `require_admin` /
  `require_role` / `get_session_user_id` so routes can be called with a plain
  `user_id` (no minted HMAC session).

Both are skipped for tests marked `e2e_staging` (see below). Gemini/LLM calls are
mocked per-test, not globally.

---

## Test files

| File | What it covers |
|---|---|
| `test_config.py` | `get_mastery_tier()` — all tier boundary values |
| `test_graph_service.py` | `get_graph`, `add_course`, `delete_course`, `apply_graph_update`, `get_recommendations` — all with mocked DB |
| `test_calendar_routes.py` | Calendar route endpoints (`/save`, `/upcoming`, `/suggest-study-blocks`, `/status`, `/disconnect`), OAuth state encoding |
| `test_learn_routes.py` | Topic→course resolution, `/sessions` list & resume, mode-switch & rename, agent chat path with legacy fallback |
| `test_quiz_routes.py` | Mastery scoring formula, `/quiz/submit` grading logic and result shape |
| `test_shared_course_context.py` | Course context service, system prompt building, quiz prompt augmentation |
| `test_ocr_pipeline.py` | Mocked agent-path unit tests **plus** live-Gemini **integration** tests gated on `GEMINI_API_KEY` (the DB layer is stubbed by the hermetic fixture) |
| `test_supabase.py` | **Connectivity script** — verifies env vars and table access. Run manually: `python tests/test_supabase.py` |
| `test_subcutaneous_staging.py` | **Opt-in staging subcutaneous test** — drives live routes against the REAL staging DB; skipped unless `RUN_STAGING_E2E=1` (see below) |

The table highlights the load-bearing suites; the directory holds ~70 `test_*.py`
files covering routes, services, encryption, and auth scoping.

---

## Integration & E2E tests

- **Live Gemini** — the integration tests in `test_ocr_pipeline.py` are marked
  `skipif(not GEMINI_API_KEY)`, so they auto-skip offline / in CI while the rest
  of that module stays fully mocked. No `--ignore` needed. (Their DB layer is
  stubbed by the hermetic conftest fixture, so they no longer write to a real
  project.)
- **Staging subcutaneous** — `test_subcutaneous_staging.py` (marker `e2e_staging`)
  drives the live routes against the REAL staging DB and is skipped unless
  `RUN_STAGING_E2E=1`. It intentionally bypasses the hermetic DB + auth-bypass
  fixtures:

  ```bash
  RUN_STAGING_E2E=1 dotenv -f .env.staging run -- python -m pytest tests/test_subcutaneous_staging.py -v
  ```

---

## Agent evals (`tests/evals/`)

Not pytest tests — standalone pydantic-evals scripts for the agents (chat
tutor, document classification/summary, concept + syllabus extraction, quiz
generation), run through a record/replay cassette layer selected by
`SAPLING_EVAL_MODE` (`replay` default / `record` / `live`). Cassettes live under
`tests/evals/cassettes/`.

```bash
cd backend
SAPLING_EVAL_MODE=replay python tests/evals/document_classification.py   # offline, uses cassettes
SAPLING_EVAL_MODE=record python tests/evals/document_classification.py   # refresh cassettes (live Gemini)
```

---

## Adding new tests

- Unit tests (no external deps) → add to the relevant `test_*.py` file, mock
  `db.connection.table` at the module where it's used (e.g.
  `patch("routes.calendar.table")`).
- Integration tests → go in `test_ocr_pipeline.py` or a new
  `test_*_integration.py` file.

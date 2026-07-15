# db/ops-code — ops cleanup slice (feedback / issue_reports / newsletter)

Branch: `db/ops-code` (off `db/academics-code`). Smallest slice of the DB modular
redesign. Rewires the ops domain's CODE onto the already-landed schema from
`db/migrations/0026_ops.sql`. No new migrations.

## Contract recap

- API boundary keeps the abstract `course_id`; term/semester is a real second axis;
  class artifacts key on `offering_id`/`enrollment_id`; the knowledge graph keys on
  the abstract `course_id`. (Ops touches none of these — feedback/issue_reports key on
  `user_id`/`session_id` only — so the contract is irrelevant here but not violated.)
- All DB via `db/connection.py::table()`. Text PKs are hand-built with `str(uuid.uuid4())`
  in the insert dict, matching the convention in `services/academics.py` and
  `services/graph_service.py`.

## Schema delta (0026_ops.sql)

`feedback` and `issue_reports` were `DROP … CASCADE` + recreated:

- `feedback.id`: was `SERIAL` integer → now `TEXT PRIMARY KEY DEFAULT gen_random_uuid()::text`.
  - `user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE` (was a bare `TEXT`, no FK).
  - `session_id TEXT REFERENCES sessions(id) ON DELETE SET NULL` (was a bare `TEXT`, no FK).
- `issue_reports.id`: was `SERIAL` integer → now `TEXT PRIMARY KEY DEFAULT gen_random_uuid()::text`.
  - `user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE` (was a bare `TEXT`, no FK).
- `newsletter_emails.approved_at TIMESTAMPTZ` added `IF NOT EXISTS` (drift absorb; prod had it).

The FK additions are enforced server-side; no code change is needed for them beyond
ensuring `user_id`/`session_id` continue to carry valid ids (they already do — they come
straight from the request body / session). The PK change is the only thing the code must
react to: with a text PK we follow the repo convention and supply `id = str(uuid.uuid4())`
explicitly rather than leaning on the DB default, so the insert shape is correct and
consistent with the rest of the redesign.

## File-by-file change map

### `backend/routes/feedback.py`
- Add `import uuid` is already present.
- `submit_feedback`: add `"id": str(uuid.uuid4())` to the `feedback` insert dict
  (current: relies on dropped SERIAL default → new: explicit text PK).
- `submit_issue_report`: add `"id": str(uuid.uuid4())` to the `issue_reports` insert dict
  (same rationale). `screenshot_urls` stays a JSON list (column is `JSONB`).
- No change to `upload_issue_screenshot` (storage-only, no PK).

### `backend/routes/admin.py` — VERIFY ONLY (issue #267)
- `approve_allowlist`: `upsert({"email", "approved_at": now_iso}, on_conflict="email")`.
- `revoke_allowlist`: `update({"approved_at": None}, filters={"email": "eq.<email>"})`.
- Both already read/write `newsletter_emails.approved_at` exactly as 0026 declares it.
  Confirmed: NO code change needed. Note it in the report.

## Tests

New file `backend/tests/test_feedback_routes.py` (POST endpoints had no coverage):
- `test_submit_feedback_inserts_with_text_uuid_pk` — patch `routes.feedback.table`
  with a recording factory; assert the recorded `feedback` insert carries an `id` that
  parses as a UUID and the body fields round-trip (`user_id`, `type`, `rating`,
  `selected_options`, `comment`, `session_id`, `topic`).
- `test_submit_feedback_omits_no_required_fields` — assert the insert dict has the
  expected keys (regression guard against dropping a field).
- `test_submit_issue_report_inserts_with_text_uuid_pk` — same shape for `issue_reports`
  (`id` is a UUID, `user_id`/`topic`/`description`/`screenshot_urls` round-trip).

Uses the same MagicMock-per-table factory pattern as `tests/test_academics.py`.
The existing `tests/test_issue_screenshot_auth.py` (storage upload) is unaffected.

## Out of scope

- Any migration authoring (schema already landed).
- `services/academics.py` and every other domain's files.
- The 2 pre-existing `tests/test_storage_service.py` failures (env-only:
  SUPABASE_URL/SERVICE_KEY unset in the worktree) — not ops, left untouched.
- `models/__init__.py` (`SubmitFeedbackBody`/`SubmitIssueReportBody` are unchanged —
  the API body shape is identical; only the server-side PK generation moves).

## Gate

`$PY -m pytest tests/ -q` stays green (baseline 722 passed + 2 unrelated storage
failures; target ≥ 722 passed, +3 new feedback tests → 725 passed). `$RUFF check .` clean.

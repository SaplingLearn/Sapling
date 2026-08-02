# Local-Supabase follow-ups — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship three local-Supabase follow-ups — a rich re-runnable local seed (#363), an opt-in integration test suite against the real local stack (#362), and the Next.js `middleware`→`proxy` migration (#365).

**Architecture:** #363 adds `backend/db/seed_local_rich.py` (local-guarded, idempotent) plus a shared `backend/db/seed_helpers.py` extracted from `seed_staging.py`. #362 adds `backend/tests/integration/` gated by a new `integration` marker, wired by extending the two autouse hermetic fixtures in `tests/conftest.py`. #365 renames `frontend/src/middleware.ts`→`proxy.ts` (function `middleware`→`proxy`) per the Next 16 convention.

**Tech Stack:** Python 3.14 / FastAPI / PostgREST via `db.connection.table()` / pytest; Next.js 16 / TypeScript / vitest.

## Global Constraints

- All backend DB access goes through `db/connection.py::table()` — never instantiate httpx/supabase directly. (Exception: none needed here.)
- Encryption via `services/encryption.py`: `encrypt_if_present` at write, `decrypt_if_present`/`decrypt_numeric`/`decrypt_json` at read. `ENCRYPTION_KEY` = 64 hex chars, required at import.
- Migrations are append-only; **this work adds NO migrations** (schema is already migrated). Do not edit any `db/migrations/*.sql`.
- `seed_staging.py` is STAGING-ONLY — its dataset/behavior must stay identical (only mechanical helper-import refactor allowed).
- `seed_local_rich` and the integration suite MUST refuse/skip unless the target `SUPABASE_URL` is local (`127.0.0.1`/`localhost`).
- All ids in the rich seed are namespaced `rich-*`.
- Lint gate: `ruff check .` (backend, from `backend/`) and `tsc --noEmit` + `vitest run` (frontend, from `frontend/`).
- Base branch `feat/local-supabase-dev`; work branch `feat/local-followups`; PR → `feat/local-supabase-dev`.
- Backend runs use the primary checkout's venv: `/home/andresl/Projects/sapling/backend/venv/bin/python`, invoked from the worktree's `backend/` (which has the copied local `.env`).

## Encrypted-column reference (authoritative — from migration audit)

| Table.column | write | read |
|---|---|---|
| `users.email` | `encrypt_if_present` | `decrypt_if_present` |
| `user_profiles.{name,first_name,last_name,bio,location}` | `encrypt_if_present` | `decrypt_if_present` |
| `notes.{title,body,last_summary}` | `encrypt_if_present` | `decrypt_if_present` |
| `documents.{summary,extracted_text}` | `encrypt_if_present` | `decrypt_if_present` |
| `documents.concept_notes` | `encrypt_json([{name,description}])` | `decrypt_json` |
| `room_messages.text` | `encrypt_if_present` | `decrypt_if_present` |
| `messages.content` | `encrypt_if_present` | `decrypt_if_present` |
| `sessions.summary_json` | `encrypt_json({...})` | `decrypt_json` |
| `assignments.notes` | `encrypt_if_present` | `decrypt_if_present` |
| `assignments.{points_possible,points_earned}` | `encrypt_if_present` | **`decrypt_numeric`** |
| PLAINTEXT | `user_profiles.{username,website,year,majors,minors,learning_style}`, `flashcards.{front,back,topic}`, `quiz_attempts.*`, `notes.tags`, `curve_*`, catalog, `roles`/`user_roles` | — |

`get_mastery_tier(score)` (`config.py`): ≥0.75 `mastered`, ≥0.45 `learning`, ≥0.10 `struggling`, else `unexplored`.

Admin = role join: `roles.slug='admin'` id is a random UUID → look it up, then insert `user_roles{user_id, role_id}` (conflict `user_id,role_id`).

## Parallelization map (for subagent dispatch)

- **Wave 1 (3 concurrent tracks — disjoint files):**
  - Track A: **Task 1** (`db/seed_helpers.py` + `seed_staging.py` refactor)
  - Track B: **Task 5** (`tests/conftest.py` marker + bypass wiring) — touches only `tests/conftest.py`
  - Track C: **Task 8** (#365 frontend `proxy` migration) — touches only `frontend/src/*`
- **Wave 2 (after Task 1):** Task 2 (`seed_local_rich.py`) → Task 3 (reset-script + docs wiring)
- **Wave 3 (after Task 2 + Task 5):** Task 6 (integration conftest) → Task 7 (integration tests) → Task 9 (CI stretch)
- **Wave 4:** Task 10 (final verification + ruff + Claude code-review gate)

Rationale: Tasks 1, 5, 8 modify non-overlapping files → safe to run in parallel (per the subagent-parallelism convention). Everything else has a real file/data dependency and is sequential.

`table()` API (for reference in tasks): `.select(columns="*", filters=None, order=None, limit=None)`, `.insert(dict|list)`, `.upsert(dict|list, on_conflict="col,col")`, `.update(dict, filters)`, `.delete(filters)`. Filters are PostgREST dicts, e.g. `{"id": f"eq.{x}"}`. Writes echo the row (`return=representation`).

---

### Task 1: Shared seed helpers + `seed_staging` refactor (#363 prep)

**Files:**
- Create: `backend/db/seed_helpers.py`
- Modify: `backend/db/seed_staging.py` (replace inline helpers with imports; dataset unchanged)
- Test: `backend/tests/test_seed_helpers.py`

**Interfaces:**
- Produces: `backend/db/seed_helpers.py` exporting:
  - `counts: defaultdict` — per-table `{"created","skipped"}` tally (module-global, shared).
  - `record(table_name: str, created: bool) -> None`
  - `exists_by(table_name: str, eq_filters: dict) -> bool`
  - `upsert(table_name: str, row: dict, on_conflict: str) -> None`
  - `insert_if_absent(table_name: str, row_id: str, row: dict) -> None`
  - `print_summary(order: list[str], header: str) -> int` (returns total created)
  - `reset_counts() -> None`
  These wrap `db.connection.table()` exactly as the current private `_*` helpers in `seed_staging.py` do (copy the bodies verbatim, drop the leading underscore, take `counts` from the module global).

- [ ] **Step 1: Write the failing test** — `backend/tests/test_seed_helpers.py`

```python
from unittest.mock import MagicMock
import db.seed_helpers as h


def test_upsert_records_created_when_absent(monkeypatch):
    h.reset_counts()
    tbl = MagicMock()
    tbl.select.return_value = []          # not present → created
    monkeypatch.setattr(h, "table", lambda name: tbl)
    h.upsert("schools", {"id": "s1", "slug": "x"}, on_conflict="slug")
    tbl.upsert.assert_called_once()
    assert h.counts["schools"]["created"] == 1
    assert h.counts["schools"]["skipped"] == 0


def test_upsert_records_skipped_when_present(monkeypatch):
    h.reset_counts()
    tbl = MagicMock()
    tbl.select.return_value = [{"slug": "x"}]   # present → skipped
    monkeypatch.setattr(h, "table", lambda name: tbl)
    h.upsert("schools", {"id": "s1", "slug": "x"}, on_conflict="slug")
    assert h.counts["schools"]["skipped"] == 1


def test_insert_if_absent_skips_existing(monkeypatch):
    h.reset_counts()
    tbl = MagicMock()
    tbl.select.return_value = [{"id": "r1"}]
    monkeypatch.setattr(h, "table", lambda name: tbl)
    h.insert_if_absent("enrollments", "r1", {"user_id": "u"})
    tbl.insert.assert_not_called()
    assert h.counts["enrollments"]["skipped"] == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && /home/andresl/Projects/sapling/backend/venv/bin/python -m pytest tests/test_seed_helpers.py -q`
Expected: FAIL / collection error — `db.seed_helpers` does not exist.

- [ ] **Step 3: Create `backend/db/seed_helpers.py`**

```python
"""Shared idempotency + summary helpers for the local/staging seed scripts.

Extracted from ``seed_staging.py`` so ``seed_local_rich.py`` reuses the exact
same upsert-on-UNIQUE / insert-if-absent / summary machinery. All DB access
goes through ``db.connection.table()``.
"""
from __future__ import annotations

from collections import defaultdict

from db.connection import table  # module-level so tests can monkeypatch it

counts: dict[str, dict[str, int]] = defaultdict(lambda: {"created": 0, "skipped": 0})


def reset_counts() -> None:
    counts.clear()


def record(table_name: str, created: bool) -> None:
    counts[table_name]["created" if created else "skipped"] += 1


def exists_by(table_name: str, eq_filters: dict) -> bool:
    filters = {col: f"eq.{val}" for col, val in eq_filters.items()}
    select_col = next(iter(eq_filters))
    rows = table(table_name).select(select_col, filters=filters, limit=1) or []
    return len(rows) > 0


def upsert(table_name: str, row: dict, on_conflict: str) -> None:
    exists = exists_by(table_name, {k: row[k] for k in on_conflict.split(",")})
    table(table_name).upsert(row, on_conflict=on_conflict)
    record(table_name, created=not exists)


def insert_if_absent(table_name: str, row_id: str, row: dict) -> None:
    if exists_by(table_name, {"id": row_id}):
        record(table_name, created=False)
        return
    table(table_name).insert({"id": row_id, **row})
    record(table_name, created=True)


def print_summary(order: list[str], header: str) -> int:
    print(f"\n{header}")
    total_created = 0
    for name in order:
        c = counts.get(name, {"created": 0, "skipped": 0})
        total_created += c["created"]
        print(f"  {name:24s} created={c['created']:<3d} skipped(exists)={c['skipped']}")
    print(f"  {'TOTAL created':24s} {total_created}")
    if total_created == 0:
        print("  (all rows already present — re-run was a no-op)")
    return total_created
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && /home/andresl/Projects/sapling/backend/venv/bin/python -m pytest tests/test_seed_helpers.py -q`
Expected: PASS (3 passed).

- [ ] **Step 5: Refactor `seed_staging.py` to use the shared helpers**

In `backend/db/seed_staging.py`: delete the local `_counts`, `_record`, `_upsert`, `_insert_if_absent`, `_exists_by` definitions and the `_print_summary` body. Add `from db import seed_helpers as h` (alongside the existing imports). Replace call sites: `_upsert(` → `h.upsert(`, `_insert_if_absent(` → `h.insert_if_absent(`, `_exists_by(` → `h.exists_by(`. Replace `_print_summary()` with:

```python
def _print_summary() -> None:
    order = [
        "schools", "courses", "course_offerings", "users", "user_profiles",
        "enrollments", "graph_nodes", "graph_edges", "node_mastery_events",
        "gradebook_categories", "assignments", "documents", "notes",
    ]
    h.print_summary(order, "Seed summary (staging demo data):")
```

In `main()` replace `_counts.clear()` with `h.reset_counts()`.

- [ ] **Step 6: Verify no behavior change — imports clean + full suite green**

Run: `cd backend && /home/andresl/Projects/sapling/backend/venv/bin/python -c "import db.seed_staging"` → no error.
Run: `cd backend && /home/andresl/Projects/sapling/backend/venv/bin/python -m pytest -q --ignore=tests/test_ocr_pipeline.py` → all pass (baseline was 960 passed, 1 skipped; now +3 for seed_helpers).

- [ ] **Step 7: Commit**

```bash
git add backend/db/seed_helpers.py backend/db/seed_staging.py backend/tests/test_seed_helpers.py
git commit -m "refactor(seed): extract shared idempotency helpers into db/seed_helpers (#363)"
```

---

### Task 2: `seed_local_rich.py` — rich local dataset (#363 core)

**Files:**
- Create: `backend/db/seed_local_rich.py`
- Test: `backend/tests/test_seed_local_rich.py` (hermetic guard test only; full run is a verification step)

**Interfaces:**
- Consumes: `db.seed_helpers` (`upsert`/`insert_if_absent`/`exists_by`/`print_summary`/`reset_counts`), `services.encryption` (`encrypt_if_present`/`encrypt_json`), `config.get_mastery_tier`, `db.connection.table`.
- Produces: `main() -> None` (idempotent seed) and `_guard_local() -> None` (raises SystemExit if `SUPABASE_URL` is non-local). All ids namespaced `rich-*`.

**Module skeleton (structure the implementer fills with the dataset below):**

```python
"""LOCAL-ONLY rich seed for E2E / manual testing (#363).

Broad, idempotent, self-contained dataset layered on the canonical terms
(fall-2025 / spring-2026 / summer-2026 from migration 0019). All ids namespaced
`rich-*`. 🔒 columns via services.encryption so they decrypt with the LOCAL
ENCRYPTION_KEY. Refuses to run against a non-local SUPABASE_URL.

Run (from backend/ with the local stack up and backend/.env active):
    python -m db.seed_local_rich
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import get_mastery_tier            # noqa: E402
from db import seed_helpers as h               # noqa: E402
from db.connection import table                # noqa: E402
from services.encryption import encrypt_if_present, encrypt_json  # noqa: E402


def _guard_local() -> None:
    url = (os.getenv("SUPABASE_URL") or "").strip()
    if "127.0.0.1" not in url and "localhost" not in url:
        sys.exit(f"REFUSING: SUPABASE_URL {url!r} is not local — seed_local_rich only writes to local.")


def _admin_role_id() -> str | None:
    rows = table("roles").select("id", filters={"slug": "eq.admin"}, limit=1) or []
    return rows[0]["id"] if rows else None

# ... seed_* step functions (see dataset spec) ...

def main() -> None:
    _guard_local()
    h.reset_counts()
    seed_school(); seed_courses(); seed_offerings()
    seed_users(); seed_enrollments()
    seed_graph(); seed_gradebook()
    seed_rooms(); seed_notes_documents(); seed_flashcards(); seed_quiz(); seed_sessions()
    h.print_summary(_SUMMARY_ORDER, "Seed summary (rich local dataset):")


if __name__ == "__main__":
    main()
```

**Dataset spec (exact tables, columns, encryption, conflict targets):**

- `seed_school()` — `h.upsert("schools", {"id":"rich-school-demo","name":"Rich Local University","slug":"rich-local"}, on_conflict="slug")`.
- `seed_courses()` — 6 courses, `h.upsert("courses", {...}, on_conflict="school_id,course_code")`, columns `id,school_id="rich-school-demo",course_code,course_name,department,credits,description`. Ids/codes:
  `rich-course-cs101` CS101 Computer Science; `rich-course-math210` MATH210 Mathematics; `rich-course-bio110` BIO110 Biology; `rich-course-eng150` ENG150 English; `rich-course-hist200` HIST200 History; `rich-course-chem121` CHEM121 Chemistry.
- `seed_offerings()` — 8 offerings, `h.upsert("course_offerings", {...}, on_conflict="course_id,term_id,section")`, columns `id,course_id,term_id,section="",instructor_name,meeting_times,location`. **Do NOT set `course_code`** (dropped in 0028). Terms: `fall-2025`, `spring-2026`, `summer-2026`. Include CS101 in BOTH `fall-2025` (`rich-off-cs101-f25`) and `spring-2026` (`rich-off-cs101-s26`); one summer offering (`rich-off-eng150-su26`). Others spread across fall/spring.
- `seed_users()` — for each user: `h.upsert("users", {...}, on_conflict="id")` with `id, email=encrypt_if_present(<addr>), onboarding_completed, streak_count, is_approved, auth_provider="google"`, and (for non-empty users) `h.upsert("user_profiles", {...}, on_conflict="user_id")` with `user_id, name/first_name/last_name=encrypt_if_present(...), username, year, majors, minors, learning_style`. Users:
  | id | onboarding_completed | is_approved | profile | roles |
  |---|---|---|---|---|
  | `rich-user-active` | True | True | full | — |
  | `rich-user-second` | True | True | full | — |
  | `rich-user-new` | False | True | minimal (name only) | — |
  | `rich-user-pending` | False | False | minimal | — |
  | `rich-user-admin` | True | True | full | admin |
  For `rich-user-admin`: `rid = _admin_role_id(); if rid: h.insert_if_absent("user_roles", f"rich-user-admin::{rid}", {"user_id":"rich-user-admin","role_id":rid})` — **note** `user_roles` has PK `(user_id, role_id)` and no `id` column, so use `h.upsert("user_roles", {"user_id":..., "role_id": rid}, on_conflict="user_id,role_id")` instead of `insert_if_absent` (which assumes an `id` column). Guard on `rid` being non-None (roles seeded by migration 0002).
- `seed_enrollments()` — `h.upsert("enrollments", {...}, on_conflict="user_id,offering_id")`, columns `id,user_id,offering_id,color,nickname,curve_mode`. `rich-user-active`: CS101 f25+s26, MATH210 s26, BIO110 f25, ENG150 su26 (one `curved` with `curve_avg_target=0.85, curve_sd_delta=0.05`). `rich-user-second`: shares CS101 s26 (`rich-off-cs101-s26`) + HIST200. Curved rows add the two `curve_*` keys.
- `seed_graph()` — per abstract `course_id` (of active user): nodes across all tiers via `h.upsert("graph_nodes", {id,user_id,course_id,concept_name,subject,mastery_score,mastery_tier:get_mastery_tier(score)}, on_conflict="user_id,course_id,concept_name")`; edges covering all four `relationship_type`s (`related`/`prerequisite`/`builds_on`/`part_of`) via `h.upsert("graph_edges", {id,user_id,source_node_id,target_node_id,relationship_type,strength}, on_conflict="user_id,source_node_id,target_node_id,relationship_type")`; append-only `h.insert_if_absent("node_mastery_events", event_id, {node_id,delta,reason})`. ≥3 courses populated, ≥12 nodes total.
- `seed_gradebook()` — categories via `h.insert_if_absent("gradebook_categories", cat_id, {enrollment_id,name,weight,drop_lowest})` (multiple per enrollment: Homework/Exams/Labs/Projects); assignments via `h.insert_if_absent("assignments", asg_id, {enrollment_id,category_id,title,due_date,assignment_type,source, points_possible:encrypt_if_present(str(p)), points_earned:encrypt_if_present(str(e)) or None})`. Include graded (`points_earned` set) AND ungraded (`points_earned=None`), past (`2025-09-…`) AND upcoming (`2026-08-…`, i.e. after 2026-07-21) `due_date`s, spanning `assignment_type ∈ {homework,exam,reading,project,quiz,other}` and `source ∈ {manual,syllabus}`. **Correctness:** `encrypt_if_present(None)` returns `None`, so `points_earned=encrypt_if_present(earned)` where `earned` is `None` for ungraded is correct (do NOT wrap `str(None)`).
- `seed_rooms()` — `h.upsert("rooms", {id,name,invite_code,created_by}, on_conflict="invite_code")` (invite_code is UNIQUE); `h.upsert("room_members", {room_id,user_id}, on_conflict="room_id,user_id")` for both active+second users; `room_messages` via `h.insert_if_absent("room_messages", <fixed-uuid-str>, {room_id,user_id,user_name,text:encrypt_if_present(...)})` — **`room_messages.id` is a UUID column**, so use fixed UUID literals like `"11111111-1111-4111-8111-000000000001"` (valid v4-shaped) as the deterministic id; `user_name` is NOT NULL. 2 rooms, ≥4 messages from both users.
- `seed_notes_documents()` — `notes` via `h.insert_if_absent("notes", note_id, {user_id,offering_id,title:encrypt_if_present(...),body:encrypt_if_present(...),tags:[...]})` (offering_id NOT NULL); `documents` via `h.insert_if_absent("documents", doc_id, {user_id,offering_id,file_name,category,summary:encrypt_if_present(...),concept_notes:encrypt_json([{"name":...,"description":...}]),extracted_text:encrypt_if_present(...)})`. `category ∈ {syllabus,lecture_notes,slides,reading,assignment,study_guide,other}`.
- `seed_flashcards()` — `h.insert_if_absent("flashcards", fc_id, {user_id,offering_id,topic,front,back})` — **plaintext** front/back/topic; grouped by `topic`. ≥6 cards across 2 topics.
- `seed_quiz()` — `h.insert_if_absent("quiz_attempts", qa_id, {user_id,concept_node_id,score,total,difficulty,questions_json:[...],answers_json:[...],completed_at:"2026-05-01T12:00:00Z"})` — `difficulty ∈ {easy,medium,hard}`; a completed attempt sets score/total/answers_json/completed_at. ≥3 attempts.
- `seed_sessions()` — `sessions` via `h.insert_if_absent("sessions", sess_id, {user_id,offering_id,mode,topic,name,summary_json:encrypt_json({"bullets":[...]})})` (`mode ∈ {socratic,expository,teachback}`); `messages` via `h.insert_if_absent("messages", msg_id, {session_id,role,content:encrypt_if_present(...)})` (`role ∈ {user,assistant}`). ≥1 session, ≥4 messages.
- `_SUMMARY_ORDER` — list every table name written, for the summary.

- [ ] **Step 1: Write the failing guard test** — `backend/tests/test_seed_local_rich.py`

```python
import pytest
import db.seed_local_rich as rich


def test_guard_refuses_non_local(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://prod.supabase.co")
    with pytest.raises(SystemExit):
        rich._guard_local()


def test_guard_allows_local(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "http://127.0.0.1:54321")
    rich._guard_local()  # no raise
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && /home/andresl/Projects/sapling/backend/venv/bin/python -m pytest tests/test_seed_local_rich.py -q`
Expected: FAIL — module/`_guard_local` not defined.

- [ ] **Step 3: Implement `backend/db/seed_local_rich.py`** per the skeleton + dataset spec above.

- [ ] **Step 4: Run guard test — passes**

Run: `cd backend && /home/andresl/Projects/sapling/backend/venv/bin/python -m pytest tests/test_seed_local_rich.py -q`
Expected: PASS (2 passed).

- [ ] **Step 5: VERIFICATION — run the seed twice against the live local stack (idempotency)**

Run: `cd backend && /home/andresl/Projects/sapling/backend/venv/bin/python -m db.seed_local_rich`
Expected: prints a summary with `TOTAL created > 0`, exits 0, no traceback.
Run it AGAIN: `cd backend && /home/andresl/Projects/sapling/backend/venv/bin/python -m db.seed_local_rich`
Expected: `TOTAL created 0` and `(all rows already present — re-run was a no-op)`.
Spot-check: `/home/andresl/Projects/sapling/backend/venv/bin/python -c "from dotenv import load_dotenv; load_dotenv(); from db.connection import table; print(len(table('graph_nodes').select('id', filters={'user_id':'eq.rich-user-active'})))"` → a positive count.

- [ ] **Step 6: `ruff check` + commit**

Run: `cd backend && ruff check db/seed_local_rich.py db/seed_helpers.py tests/test_seed_local_rich.py`
```bash
git add backend/db/seed_local_rich.py backend/tests/test_seed_local_rich.py
git commit -m "feat(seed): rich, idempotent local dataset for E2E (#363)"
```

---

### Task 3: Wire rich seed into reset script + document (#363 finish)

**Files:**
- Modify: `scripts/lib/local-common.sh` (add optional rich-seed step to `migrate_reload_seed`)
- Modify: `docs/local-supabase.md` (new subsection)

- [ ] **Step 1: Add the gated rich-seed step** — in `scripts/lib/local-common.sh`, immediately after the existing `db.seed_staging` seed line inside `migrate_reload_seed()`:

```bash
  # Optional rich local dataset (#363): opt-in via SEED_RICH=1.
  if [ "${SEED_RICH:-0}" = "1" ]; then
    echo "▶ Seeding rich local dataset (SEED_RICH=1)…"
    ( cd backend && SUPABASE_DB_URL="$LOCAL_DB_URL" venv/bin/python -m db.seed_local_rich ) \
      || { echo "✗ rich seed failed"; return 1; }
  fi
```
(Match the surrounding indentation/subshell style of the existing `db.seed_staging` call.)

- [ ] **Step 2: Document it** — add to `docs/local-supabase.md` under the "Real course catalog (optional)" section:

```markdown
## Rich local dataset (optional, #363)

The default seed is a single demo user. For a broad, realistic dataset — multiple
users in distinct states (regular, brand-new, pending-approval, admin), 6 courses
across 3 terms, knowledge graphs at varied mastery, a full gradebook, study rooms,
notes, documents, flashcards, quiz history, and tutor sessions — run:

    python -m db.seed_local_rich          # idempotent; re-runnable; local-only (guarded)

Or fold it into a full reset:

    SEED_RICH=1 scripts/local-db-reset.sh # reset → migrate → seed_staging → seed_local_rich

All ids are namespaced `rich-*`; encrypted columns use the local `ENCRYPTION_KEY`.
The script refuses to run against a non-local `SUPABASE_URL`.
```

- [ ] **Step 3: Verify the reset wiring is syntactically sound (dry parse)**

Run: `bash -n scripts/lib/local-common.sh && bash -n scripts/local-db-reset.sh`
Expected: no output (syntax OK). (Do NOT actually run the destructive reset — verification is additive per the agreed mode.)

- [ ] **Step 4: Commit**

```bash
git add scripts/lib/local-common.sh docs/local-supabase.md
git commit -m "chore(seed): wire optional rich seed into local reset + docs (#363)"
```

---

### Task 5: Integration marker + hermetic-fixture bypass wiring (#362 wiring)

**Files:**
- Modify: `backend/tests/conftest.py` (register `integration` marker; extend two autouse bypasses)

**Interfaces:**
- Produces: an `integration` pytest marker; when a test carries it, `_hermetic_supabase_client` and `_bypass_session_auth` early-return (real DB client + real auth guard stay live), exactly as they already do for `e2e_staging`.

- [ ] **Step 1: Register the marker** — in `pytest_configure` (`tests/conftest.py:27`), add after the existing `e2e_staging` line:

```python
    config.addinivalue_line(
        "markers",
        "integration: opt-in tests against the REAL local Supabase stack (needs the "
        "stack up + RUN_INTEGRATION=1). Bypasses the hermetic DB + auth fixtures.",
    )
```

- [ ] **Step 2: Extend both bypass guards** — change the two early-return conditions:

In `_hermetic_supabase_client` (`:63`) and `_bypass_session_auth` (`:94`), replace:
```python
    if request.node.get_closest_marker("e2e_staging"):
        return
```
with:
```python
    if request.node.get_closest_marker("e2e_staging") or request.node.get_closest_marker("integration"):
        return
```

- [ ] **Step 3: Verify the hermetic suite is unaffected**

Run: `cd backend && /home/andresl/Projects/sapling/backend/venv/bin/python -m pytest -q --ignore=tests/test_ocr_pipeline.py`
Expected: same pass count as before (marker registration + an OR clause don't touch existing tests).

- [ ] **Step 4: Commit**

```bash
git add backend/tests/conftest.py
git commit -m "test(conftest): register integration marker + bypass hermetic fixtures for it (#362)"
```

---

### Task 6: Integration conftest — env, skip-gate, seed fixture, session minting (#362)

**Files:**
- Create: `backend/tests/integration/__init__.py` (empty)
- Create: `backend/tests/integration/conftest.py`

**Interfaces:**
- Produces fixtures/utilities for integration tests:
  - Module-level: loads local `backend/.env` with `override=True` **only when `RUN_INTEGRATION=1`** (fixes the ENCRYPTION_KEY/SESSION_SECRET/SUPABASE_* mismatch vs. the root conftest's test defaults). MUST run before any `main`/`services`/`config` import.
  - `mint_session(user_id, ttl=3600) -> str` — local copy (do NOT import from `db.e2e_staging_http`, which builds TestClients at import).
  - autouse session fixture `_require_local_stack` — `pytest.skip` unless `RUN_INTEGRATION=1` and `SUPABASE_URL` is local; then ensures the rich seed is present (calls `db.seed_local_rich.main()`).
  - fixture `client` → `TestClient(app)` (plain, no `with`, so lifespan/`validate_config` doesn't run); fixture `anon_client` → cookie-less `TestClient(app)`.

- [ ] **Step 1: Create `backend/tests/integration/__init__.py`** (empty file).

- [ ] **Step 2: Create `backend/tests/integration/conftest.py`**

```python
"""Fixtures for the opt-in integration suite (#362) — real local Supabase.

Runs ONLY when RUN_INTEGRATION=1 and SUPABASE_URL is local. Loads backend/.env
with override so the seed's ENCRYPTION_KEY / SESSION_SECRET / SUPABASE_* win over
the root conftest's hermetic test defaults (else decryption silently mismatches).
"""
import base64
import hashlib
import hmac
import json
import os
import time
from pathlib import Path

import pytest

_RUN = os.getenv("RUN_INTEGRATION") == "1"

# Must happen BEFORE any config/db/services import so the real key is in place.
if _RUN:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parents[2] / ".env", override=True)


def _is_local() -> bool:
    url = (os.getenv("SUPABASE_URL") or "").strip()
    return "127.0.0.1" in url or "localhost" in url


def mint_session(user_id: str, ttl: int = 3600) -> str:
    """Mint a sapling_session token exactly as auth_guard._decode_session verifies."""
    from config import SESSION_SECRET
    payload = {"user_id": user_id, "exp": int(time.time()) + ttl}
    pb = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
    sig = hmac.new(SESSION_SECRET.encode(), pb.encode(), hashlib.sha256).digest()
    sb = base64.urlsafe_b64encode(sig).decode().rstrip("=")
    return f"{pb}.{sb}"


@pytest.fixture(scope="session", autouse=True)
def _require_local_stack():
    if not _RUN:
        pytest.skip("integration suite: set RUN_INTEGRATION=1 (with the local stack up)")
    if not _is_local():
        pytest.skip(f"integration suite: SUPABASE_URL is not local ({os.getenv('SUPABASE_URL')!r})")
    # Ensure the rich dataset is present (idempotent, additive).
    from db import seed_local_rich
    seed_local_rich.main()
    yield


@pytest.fixture
def client():
    from main import app
    from fastapi.testclient import TestClient
    return TestClient(app)


@pytest.fixture
def anon_client():
    from main import app
    from fastapi.testclient import TestClient
    return TestClient(app)
```

- [ ] **Step 3: Smoke-verify the gate — default run skips cleanly**

Run: `cd backend && /home/andresl/Projects/sapling/backend/venv/bin/python -m pytest tests/integration -q`
Expected: `no tests ran` / all skipped (RUN_INTEGRATION unset). No import errors, no real DB hit.

- [ ] **Step 4: Commit**

```bash
git add backend/tests/integration/__init__.py backend/tests/integration/conftest.py
git commit -m "test(integration): conftest — env override, local-stack gate, session minting (#362)"
```

---

### Task 7: Integration tests — DB, encryption, and route E2E (#362)

**Files:**
- Create: `backend/tests/integration/test_local_stack.py`

**Interfaces:**
- Consumes: `mint_session`, `client`, `anon_client` from the integration conftest; the seeded `rich-user-active`.

- [ ] **Step 1: Write the tests** — `backend/tests/integration/test_local_stack.py`

```python
"""Opt-in integration tests against the real local Supabase (#362).

Run: RUN_INTEGRATION=1 dotenv -f .env run -- \
     /home/andresl/Projects/sapling/backend/venv/bin/python -m pytest -m integration -q
(from backend/, local stack up). The conftest also loads .env, so plain
`RUN_INTEGRATION=1 pytest -m integration` works too.
"""
import pytest

from db.connection import table
from services.encryption import (
    decrypt_if_present, decrypt_numeric, encrypt_if_present,
)
from tests.integration.conftest import mint_session

pytestmark = pytest.mark.integration

_ACTIVE = "rich-user-active"


def test_db_roundtrip_write_read_delete():
    """A real insert → select → delete through db.connection.table()."""
    rid = "rich-it-school-roundtrip"
    table("schools").upsert(
        {"id": rid, "name": "IT Roundtrip", "slug": rid}, on_conflict="id"
    )
    rows = table("schools").select("id,slug", filters={"id": f"eq.{rid}"})
    assert rows and rows[0]["slug"] == rid
    table("schools").delete({"id": f"eq.{rid}"})
    assert table("schools").select("id", filters={"id": f"eq.{rid}"}) == []


def test_encryption_roundtrip_text_and_numeric():
    """Write encrypted → read raw → decrypt; both text and numeric paths."""
    nid = "rich-it-note-enc"
    secret = "integration-secret-body-✓"
    table("notes").upsert(
        {
            "id": nid,
            "user_id": _ACTIVE,
            "offering_id": "rich-off-cs101-s26",
            "title": encrypt_if_present("IT note"),
            "body": encrypt_if_present(secret),
            "tags": ["it"],
        },
        on_conflict="id",
    )
    raw = table("notes").select("body", filters={"id": f"eq.{nid}"})[0]["body"]
    assert raw != secret                       # stored ciphertext, not plaintext
    assert decrypt_if_present(raw) == secret   # round-trips back
    # numeric path via decrypt_numeric
    enc_points = encrypt_if_present("87.5")
    assert decrypt_numeric(enc_points) == 87.5
    table("notes").delete({"id": f"eq.{nid}"})


def test_route_e2e_auth_me(client, anon_client):
    """Full route E2E: real auth guard + real DB + real decryption."""
    anon = anon_client.get("/api/auth/me")
    assert anon.status_code == 401             # no cookie → unauthenticated

    client.cookies.set("sapling_session", mint_session(_ACTIVE))
    res = client.get("/api/auth/me")
    assert res.status_code == 200
    data = res.json()
    assert data["user_id"] == _ACTIVE
    assert data["is_approved"] is True
    assert isinstance(data["name"], str) and data["name"]   # decrypted display name


def test_route_e2e_gradebook_decrypt_numeric(client):
    """Gradebook route returns decrypt_numeric'd points end-to-end."""
    client.cookies.set("sapling_session", mint_session(_ACTIVE))
    # rich-user-active is enrolled in CS101 spring-2026 with graded assignments.
    res = client.get(
        "/api/gradebook/courses/rich-course-cs101",
        params={"user_id": _ACTIVE, "semester": "Spring 2026"},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    graded = [a for a in body["assignments"] if a.get("points_earned") is not None]
    assert graded, "expected at least one graded assignment"
    for a in graded:
        assert isinstance(a["points_earned"], (int, float))     # decrypted numeric
        assert isinstance(a["points_possible"], (int, float))
```

> **Note for implementer:** the `test_route_e2e_gradebook_decrypt_numeric` seed assumptions (course id `rich-course-cs101`, term label `Spring 2026`, ≥1 graded assignment on the active user's CS101-spring enrollment) MUST be guaranteed by Task 2's dataset. If gradebook term-resolution proves finicky, this test is the acceptable one to drop to xfail/skip with a comment — the other three fully satisfy the #362 acceptance (DB round-trip, encryption incl. `decrypt_numeric`, one route E2E). Do NOT weaken the first three.

- [ ] **Step 2: Run the integration suite against the live stack**

Run: `cd backend && RUN_INTEGRATION=1 /home/andresl/Projects/sapling/backend/venv/bin/python -m pytest -m integration -q`
Expected: 4 passed (or 3 passed + 1 skipped if the gradebook route test was skipped per the note). No errors.

- [ ] **Step 3: Confirm default runs still skip integration**

Run: `cd backend && /home/andresl/Projects/sapling/backend/venv/bin/python -m pytest -m integration -q`
Expected: all skipped (RUN_INTEGRATION unset).
Run: `cd backend && /home/andresl/Projects/sapling/backend/venv/bin/python -m pytest -q --ignore=tests/test_ocr_pipeline.py`
Expected: full hermetic suite still green; integration tests skipped.

- [ ] **Step 4: Document how to run** — append to the `docs/local-supabase.md` rich-dataset section:

```markdown
### Integration tests (opt-in, #362)

With the local stack up and `backend/.env` active, from `backend/`:

    RUN_INTEGRATION=1 python -m pytest -m integration -q

These bypass the hermetic mocks and hit the real local Supabase (real Postgres,
encryption round-trips, migrated schema). Skipped by default. The suite seeds the
rich dataset (idempotent) on first run and never resets your DB.
```

- [ ] **Step 5: `ruff check` + commit**

Run: `cd backend && ruff check tests/integration`
```bash
git add backend/tests/integration/test_local_stack.py docs/local-supabase.md
git commit -m "test(integration): DB + encryption + route E2E against local stack (#362)"
```

---

### Task 8: `middleware.ts` → `proxy.ts` migration (#365) — INDEPENDENT

**Files:**
- Create: `frontend/src/proxy.ts` (from `middleware.ts`)
- Create: `frontend/src/proxy.test.ts` (from `middleware.test.ts`)
- Delete: `frontend/src/middleware.ts`, `frontend/src/middleware.test.ts`
- Optional: `frontend/src/app/(public)/page.tsx:85`, `frontend/src/lib/deployGuard.ts:9` (comment-only mentions of "middleware")

**Prereq:** frontend deps. `node_modules` is gitignored/absent in the worktree — reuse the primary checkout's install by symlink (fast, no re-download):
`ln -s /home/andresl/Projects/sapling/frontend/node_modules /home/andresl/Projects/wt-local-followups/frontend/node_modules` (only if absent).

- [ ] **Step 1: Create `frontend/src/proxy.test.ts`** — copy `middleware.test.ts` and update the import + calls + describe label:

```ts
import { describe, expect, it } from 'vitest';
import { NextRequest } from 'next/server';
import { proxy, config } from './proxy';

const ORIGIN = 'https://app.saplinglearn.com';

function req(path: string): NextRequest {
  return new NextRequest(`${ORIGIN}${path}`);
}

describe('proxy — /profile gating (#189)', () => {
  it('redirects an unauthenticated /profile/:id request (no longer passes through)', async () => {
    const res = await proxy(req('/profile/some-user-id'));
    expect(res.headers.get('location')).toBeTruthy();
    expect(res.status).toBe(307);
  });

  it('still lets a genuinely public path pass through (no over-broadening)', async () => {
    const res = await proxy(req('/about'));
    expect(res.headers.get('location')).toBeNull();
  });

  it('lists /profile in config.matcher so proxy actually runs there', () => {
    expect(config.matcher).toContain('/profile/:path*');
  });
});
```

- [ ] **Step 2: Run the new test — fails (no `./proxy`)**

Run: `cd frontend && npx vitest run src/proxy.test.ts`
Expected: FAIL — cannot resolve `./proxy`.

- [ ] **Step 3: Create `frontend/src/proxy.ts`** — copy `middleware.ts` verbatim, rename only the exported function `middleware` → `proxy` (keep `config`/`matcher`, `NextRequest`/`NextResponse` imports, and all gating logic identical):

```ts
export async function proxy(request: NextRequest) {
```
(everything else in the file unchanged, including `export const config = { matcher: [...] }`.)

- [ ] **Step 4: Delete the old files**

```bash
git rm frontend/src/middleware.ts frontend/src/middleware.test.ts
```

- [ ] **Step 5: Run tests + typecheck — pass**

Run: `cd frontend && npx vitest run src/proxy.test.ts`
Expected: PASS (3 passed).
Run: `cd frontend && npx tsc --noEmit`
Expected: no errors.

- [ ] **Step 6: (Optional) update comment-only mentions** in `src/app/(public)/page.tsx:85` and `src/lib/deployGuard.ts:9` (`middleware` → `proxy`) for accuracy. Re-run `npx tsc --noEmit` if touched.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/proxy.ts frontend/src/proxy.test.ts
git commit -m "chore(frontend): migrate middleware convention to proxy (Next 16) (#365)"
```

---

### Task 9: CI workflow for integration suite (#362 STRETCH — unverifiable locally)

**Files:**
- Create: `.github/workflows/integration.yml`

> **Flagged:** cannot be executed in this environment (no GitHub Actions runner). Delivered best-effort; the local `RUN_INTEGRATION=1` path in Task 7 is the real acceptance.

- [ ] **Step 1: Create `.github/workflows/integration.yml`**

```yaml
name: integration (local supabase)

on:
  workflow_dispatch:
  pull_request:
    paths:
      - 'backend/**'
      - '.github/workflows/integration.yml'

jobs:
  integration:
    runs-on: ubuntu-latest
    defaults:
      run:
        working-directory: backend
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.14'
      - uses: supabase/setup-cli@v1
        with:
          version: latest
      - name: Start Supabase
        run: supabase start
        working-directory: .
      - name: Install deps
        run: pip install -r requirements.txt
      - name: Migrate + seed
        run: |
          SUPABASE_DB_URL=postgresql://postgres:postgres@127.0.0.1:54322/postgres python -m db.migrate
          cp .env.local.example .env
          python -m db.seed_local_rich
      - name: Run integration tests
        run: RUN_INTEGRATION=1 python -m pytest -m integration -q
```

- [ ] **Step 2: Lint YAML locally (best-effort)**

Run: `python -c "import yaml,sys; yaml.safe_load(open('.github/workflows/integration.yml'))"` (from repo root)
Expected: no error (valid YAML). Runtime behavior is unverified here.

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/integration.yml
git commit -m "ci: opt-in integration workflow booting Supabase CLI (#362, stretch)"
```

---

### Task 10: Final verification sweep + Claude code-review gate

- [ ] **Step 1: Full backend suite (hermetic) + ruff**

Run: `cd backend && /home/andresl/Projects/sapling/backend/venv/bin/python -m pytest -q --ignore=tests/test_ocr_pipeline.py` → green.
Run: `cd backend && ruff check .` → clean (or only pre-existing baseline findings).

- [ ] **Step 2: Integration suite green against live stack**

Run: `cd backend && RUN_INTEGRATION=1 /home/andresl/Projects/sapling/backend/venv/bin/python -m pytest -m integration -q` → 4 passed (or 3+1 skip per Task 7 note).

- [ ] **Step 3: Frontend green**

Run: `cd frontend && npx vitest run && npx tsc --noEmit` → pass, no errors.

- [ ] **Step 4: Re-run the rich seed idempotency check** — `python -m db.seed_local_rich` twice → 2nd run all-skipped.

- [ ] **Step 5: Per-phase reviews already done via superpowers:requesting-code-review after each task. Now the FINAL whole-branch Claude code review.**

Review the entire `feat/local-followups` diff vs `feat/local-supabase-dev` with the `/code-review` skill (Claude code review over the working branch). Triage findings by severity; fix P0/P1 inline (each fix re-runs the relevant task's verification), then re-review the fixes. (Note: `/code-review ultra` cloud review is user-triggered/billed — this gate uses the local review.)

- [ ] **Step 6: Push + open PR** (only after user go-ahead)

```bash
git push -u origin feat/local-followups
gh pr create --base feat/local-supabase-dev --head feat/local-followups \
  --title "Local-Supabase follow-ups: rich seed, integration suite, proxy migration (#363, #362, #365)" \
  --body "<summary + test evidence; 🤖 Generated with Claude Code>"
```

---

## Self-Review (plan vs. spec)

**Spec coverage:**
- #363 rich seed → Tasks 1–3 (helpers, seed, wiring+docs). ✔ multiple user states, 6 courses/3 terms, graph tiers, gradebook graded/ungraded+curved+past/upcoming, rooms+messages, notes/docs, flashcards, quiz, sessions — all in Task 2 dataset spec. ✔ idempotent + local-guard + docs.
- #362 integration suite → Tasks 5–7 (+9 stretch). ✔ marker, bypass wiring, RUN_INTEGRATION gate, local-only, seed reuse, DB round-trip, encryption incl. decrypt_numeric, route E2E, docs, CI stretch.
- #365 proxy migration → Task 8. ✔ rename file+function, test rename, tsc+vitest, Next 16.
- Final Claude review gate → Task 10. ✔ (per user request, in addition to per-phase reviews).

**Placeholder scan:** No "TBD"/"add error handling" — every code step has concrete code. The seed dataset is specified by exact table/column/encryption/conflict-target + counts rather than 400 inlined literal rows (data, not logic); acceptable and unambiguous.

**Type/name consistency:** `seed_helpers` exports `upsert`/`insert_if_absent`/`exists_by`/`print_summary`/`reset_counts`/`record`/`counts` — used consistently in Tasks 1 & 2. `mint_session(user_id, ttl=3600)` defined and used in Tasks 6 & 7. `_ACTIVE = "rich-user-active"` matches the seeded id. `rich-off-cs101-s26` / `rich-course-cs101` / term label `Spring 2026` used consistently between Task 2 seed and Task 7 gradebook test.

**Known risk flagged in-plan:** gradebook route term-resolution (Task 7 note); `user_roles` has no `id` column so use upsert-on-`user_id,role_id` not `insert_if_absent` (Task 2 note); `encrypt_if_present(None)` returns None so ungraded points are correct (Task 2 note); ENCRYPTION_KEY override ordering (Task 6).

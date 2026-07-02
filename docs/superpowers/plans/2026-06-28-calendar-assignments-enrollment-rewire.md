# Calendar / assignments enrollment-rewire Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `routes/calendar.py` + `services/calendar_service.py` work against the enrollment-keyed `assignments` table (migration 0021) so the dashboard stops 500-ing and the calendar feature functions on the redesigned schema.

**Architecture:** Assignments are always course-tied and key on `enrollment_id`. A new `services/academics.py` resolver turns `(user, abstract course) → enrollment_id` (creating an offering+enrollment when missing); reads fetch the user's enrollments then `assignments WHERE enrollment_id IN (...)`, decorating each row with abstract `course_id`/`course_code`/`course_name` via the existing `offering_course_id` bridge. HTTP request/response shapes are unchanged.

**Tech Stack:** FastAPI, PostgREST via `db.connection.table()`, pytest + `unittest.mock` (mock Supabase per conftest), column encryption via `services/encryption.py`.

## Global Constraints

- All DB access via `db.connection.table()` — never instantiate httpx or import supabase. (CLAUDE.md)
- Enrollment/offering/term resolution lives in `services/academics.py`. (CLAUDE.md)
- `assignments.notes` is column-encrypted: `encrypt_if_present` at write, `decrypt_if_present` at read. (CLAUDE.md)
- Tests live in `backend/tests/`, run `python -m pytest tests/ -q` from `backend/`. Auth is auto-bypassed by `conftest.py` (`require_self` stubbed; path-param `user_id` flows through).
- New `assignments` columns only: `id, enrollment_id, category_id, title, due_date, assignment_type, notes, points_possible, points_earned, source, google_event_id, gradescope_*, curve_*`. There is no `user_id`/`course_id`/`courses` relationship on this table.
- `source` ∈ `{'manual','syllabus'}`. `assignment_type` ∈ `{'homework','exam','reading','project','quiz','other'}`.
- Run all commands from `backend/` using `venv/bin/python` (e.g. `venv/bin/python -m pytest ...`).

---

## Test helper: multi-table mock dispatch

Several handlers now touch >1 table per call, so the old single-`return_value` mock is insufficient. Each test below builds a dispatch: `table(name)` returns a per-name `MagicMock`.

```python
from unittest.mock import MagicMock

def _tbl(**rows_by_verb):
    """A per-table mock. e.g. _tbl(select=[...], insert=[], update=[], delete=[])."""
    m = MagicMock()
    for verb, val in rows_by_verb.items():
        getattr(m, verb).return_value = val
    return m

def _dispatch(tables: dict):
    """Return a side_effect callable mapping table(name) -> its mock.
    Unlisted names get an empty-select mock so stray reads don't explode."""
    def _table(name):
        return tables.get(name) or _tbl(select=[], insert=[], update=[], delete=[])
    return _table
```

Place this at the top of each new test module (or import from a shared `tests/_dbmock.py` if you prefer; creating that file is optional and folded into Task 2).

---

### Task 1: `enrollment_id_for` + `user_enrollment_ids` resolvers

**Files:**
- Modify: `services/academics.py` (append two functions; `uuid` and `table` already imported)
- Test: `tests/test_academics_enrollment_resolver.py` (create)

**Interfaces:**
- Produces:
  - `academics.enrollment_id_for(user_id: str, course_id: str, *, create: bool = False) -> str | None`
  - `academics.user_enrollment_ids(user_id: str) -> list[dict]` (each `{"id", "offering_id"}`)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_academics_enrollment_resolver.py
from unittest.mock import MagicMock, patch
import services.academics as ac

def _tbl(**rows_by_verb):
    m = MagicMock()
    for verb, val in rows_by_verb.items():
        getattr(m, verb).return_value = val
    return m

def _dispatch(tables):
    def _table(name):
        return tables.get(name) or _tbl(select=[], insert=[], update=[], delete=[])
    return _table

class TestUserEnrollmentIds:
    def test_returns_rows(self):
        with patch("services.academics.table", side_effect=_dispatch({
            "enrollments": _tbl(select=[{"id": "e1", "offering_id": "o1"}]),
        })):
            assert ac.user_enrollment_ids("user_andres") == [{"id": "e1", "offering_id": "o1"}]

    def test_empty_user(self):
        assert ac.user_enrollment_ids("") == []

class TestEnrollmentIdFor:
    def test_existing_enrollment_current_term(self):
        # user_offering_ids_for_course -> ["o1"]; term match; enrollment e1
        tables = {
            "course_offerings": _tbl(select=[{"id": "o1"}]),
            "enrollments": _tbl(select=[{"id": "e1"}]),
        }
        with patch("services.academics.table", side_effect=_dispatch(tables)), \
             patch("services.academics.user_offering_ids_for_course", return_value=["o1"]), \
             patch("services.academics.current_term", return_value=None):
            assert ac.enrollment_id_for("user_andres", "CS101") == "e1"

    def test_create_when_missing(self):
        with patch("services.academics.user_offering_ids_for_course", return_value=[]), \
             patch("services.academics.resolve_offering", return_value="o9"), \
             patch("services.academics.table", side_effect=_dispatch({
                 "enrollments": _tbl(select=[], insert=[]),
             })):
            eid = ac.enrollment_id_for("user_andres", "CS101", create=True)
            assert isinstance(eid, str) and eid

    def test_missing_no_create_returns_none(self):
        with patch("services.academics.user_offering_ids_for_course", return_value=[]):
            assert ac.enrollment_id_for("user_andres", "CS101", create=False) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `venv/bin/python -m pytest tests/test_academics_enrollment_resolver.py -q`
Expected: FAIL — `AttributeError: module 'services.academics' has no attribute 'enrollment_id_for'`.

- [ ] **Step 3: Implement the resolvers**

Append to `services/academics.py`:

```python
def user_enrollment_ids(user_id: str) -> list[dict]:
    """The user's enrollments as ``{id, offering_id}`` rows (read + scoping helper)."""
    if not user_id:
        return []
    return table("enrollments").select(
        "id,offering_id", filters={"user_id": f"eq.{user_id}"}
    ) or []


def enrollment_id_for(user_id: str, course_id: str, *, create: bool = False) -> str | None:
    """Resolve (user, abstract course) → the user's current-term enrollment id.

    Prefer the user's enrollment in the course's current-term offering, else
    their only offering of the course. With ``create=True``, ensure an offering
    (current term) and an enrollment row exist so a write never silently drops.
    """
    if not user_id or not course_id:
        return None

    offering_ids = user_offering_ids_for_course(user_id, course_id)
    if offering_ids:
        chosen = offering_ids[0]
        cur = current_term()
        cur_id = cur["id"] if cur else None
        if cur_id:
            for oid in offering_ids:
                t = term_for_offering(oid)
                if t and t.get("id") == cur_id:
                    chosen = oid
                    break
        rows = table("enrollments").select(
            "id",
            filters={"user_id": f"eq.{user_id}", "offering_id": f"eq.{chosen}"},
            limit=1,
        )
        if rows:
            return rows[0]["id"]

    if not create:
        return None

    offering_id = resolve_offering(course_id, create=True)
    if not offering_id:
        return None
    existing = table("enrollments").select(
        "id",
        filters={"user_id": f"eq.{user_id}", "offering_id": f"eq.{offering_id}"},
        limit=1,
    )
    if existing:
        return existing[0]["id"]
    new_id = str(uuid.uuid4())
    table("enrollments").insert(
        {"id": new_id, "user_id": user_id, "offering_id": offering_id}
    )
    return new_id
```

- [ ] **Step 4: Run test to verify it passes**

Run: `venv/bin/python -m pytest tests/test_academics_enrollment_resolver.py -q`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add services/academics.py tests/test_academics_enrollment_resolver.py
git commit -m "feat(academics): enrollment_id_for + user_enrollment_ids resolvers"
```

---

### Task 2: Read path — `get_upcoming` + `get_all` on enrollment_id

**Files:**
- Modify: `routes/calendar.py` (`get_upcoming` ~136-161, `get_all_assignments` ~164-188; add module helpers)
- Test: `tests/test_calendar_read_enrollment.py` (create)

**Interfaces:**
- Consumes: `academics.user_enrollment_ids`, `academics.offering_course_id`
- Produces: module-level `_read_assignments(user_id, *, due_gte=None, limit=None) -> list[dict]`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_calendar_read_enrollment.py
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient
from main import app

client = TestClient(app)

def _tbl(**rows_by_verb):
    m = MagicMock()
    for verb, val in rows_by_verb.items():
        getattr(m, verb).return_value = val
    return m

def _dispatch(tables):
    def _table(name):
        return tables.get(name) or _tbl(select=[], insert=[], update=[], delete=[])
    return _table

class TestUpcomingEnrollmentKeyed:
    def test_empty_when_no_enrollments(self):
        with patch("routes.calendar.table", side_effect=_dispatch({"enrollments": _tbl(select=[])})), \
             patch("services.academics.table", side_effect=_dispatch({"enrollments": _tbl(select=[])})):
            r = client.get("/api/calendar/upcoming/user_andres")
        assert r.status_code == 200
        assert r.json() == {"assignments": []}

    def test_decorates_with_course_meta(self):
        tables = {
            "enrollments": _tbl(select=[{"id": "e1", "offering_id": "o1"}]),
            "assignments": _tbl(select=[{
                "id": "a1", "enrollment_id": "e1", "title": "HW1",
                "due_date": "2999-01-01", "assignment_type": "homework",
                "notes": None, "google_event_id": None, "source": "manual",
            }]),
            "courses": _tbl(select=[{"id": "CS101", "course_code": "CS101", "course_name": "Intro"}]),
        }
        with patch("routes.calendar.table", side_effect=_dispatch(tables)), \
             patch("routes.calendar.academics") as ac:
            ac.user_enrollment_ids.return_value = [{"id": "e1", "offering_id": "o1"}]
            ac.offering_course_id.return_value = "CS101"
            r = client.get("/api/calendar/upcoming/user_andres")
        assert r.status_code == 200
        items = r.json()["assignments"]
        assert len(items) == 1
        assert items[0]["course_code"] == "CS101"
        assert items[0]["course_id"] == "CS101"
        assert items[0]["user_id"] == "user_andres"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `venv/bin/python -m pytest tests/test_calendar_read_enrollment.py -q`
Expected: FAIL — current `get_upcoming` selects `user_id,course_id,courses!left(...)`; mock returns no such rows / shape mismatch (the live path would 400).

- [ ] **Step 3: Implement read path**

In `routes/calendar.py`: add the import and helpers near the top (after the existing imports), then rewrite the two read handlers.

```python
from services import academics  # add to imports
```

```python
def _course_meta_cached(offering_id, cache):
    if not offering_id:
        return {}
    if offering_id not in cache:
        course_id = academics.offering_course_id(offering_id)
        course = {}
        if course_id:
            rows = table("courses").select(
                "id,course_code,course_name",
                filters={"id": f"eq.{course_id}"}, limit=1,
            )
            course = rows[0] if rows else {}
        cache[offering_id] = {
            "course_id": course_id,
            "course_code": course.get("course_code"),
            "course_name": course.get("course_name"),
        }
    return cache[offering_id]


def _read_assignments(user_id, *, due_gte=None, limit=None):
    enrollments = academics.user_enrollment_ids(user_id)
    if not enrollments:
        return []
    offering_by_enrollment = {e["id"]: e.get("offering_id") for e in enrollments}
    ids = ",".join(offering_by_enrollment.keys())
    filters = {"enrollment_id": f"in.({ids})"}
    if due_gte:
        filters["due_date"] = f"gte.{due_gte}"
    rows = table("assignments").select(
        "id,enrollment_id,title,due_date,assignment_type,notes,google_event_id,source",
        filters=filters, order="due_date.asc", limit=limit,
    )
    cache = {}
    out = []
    for r in rows:
        meta = _course_meta_cached(offering_by_enrollment.get(r.get("enrollment_id")), cache)
        out.append({
            "id": r["id"],
            "user_id": user_id,
            "title": r["title"],
            "due_date": r["due_date"],
            "assignment_type": r.get("assignment_type"),
            "notes": decrypt_if_present(r.get("notes")),
            "google_event_id": r.get("google_event_id"),
            "course_id": meta.get("course_id"),
            "course_code": meta.get("course_code") or "",
            "course_name": meta.get("course_name") or "",
        })
    return out
```

```python
@router.get("/upcoming/{user_id}")
def get_upcoming(user_id: str, request: FastAPIRequest):
    require_self(user_id, request)
    today = datetime.utcnow().strftime("%Y-%m-%d")
    return {"assignments": _read_assignments(user_id, due_gte=today, limit=20)}


@router.get("/all/{user_id}")
def get_all_assignments(user_id: str, request: FastAPIRequest):
    """Return all assignments for a user (past and future) for the calendar view."""
    require_self(user_id, request)
    return {"assignments": _read_assignments(user_id)}
```

(Confirm `db.connection.table.select` accepts `limit=None` as "no limit"; it does — `limit` is an optional kwarg appended only when truthy.)

- [ ] **Step 4: Run test to verify it passes**

Run: `venv/bin/python -m pytest tests/test_calendar_read_enrollment.py -q`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add routes/calendar.py tests/test_calendar_read_enrollment.py
git commit -m "feat(calendar): read upcoming/all via enrollment_id (unblocks dashboard)"
```

---

### Task 3: Write path — `calendar_service` + `POST /save` on enrollment_id

**Files:**
- Modify: `services/calendar_service.py` (`load_existing_assignment_keys`, `insert_new_assignments`, `save_assignments_to_db`)
- Modify: `routes/calendar.py` (`save_assignments` ~119-133 — pass raw notes + `source="manual"`)
- Test: `tests/test_calendar_write_enrollment.py` (create)

**Interfaces:**
- Consumes: `academics.enrollment_id_for`, `academics.user_enrollment_ids`
- Produces: `insert_new_assignments(user_id, assignments, *, source="manual") -> int`; `save_assignments_to_db(user_id, assignments, *, source="syllabus") -> int`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_calendar_write_enrollment.py
from unittest.mock import MagicMock, patch
import services.calendar_service as cs

def _tbl(**rows_by_verb):
    m = MagicMock()
    for verb, val in rows_by_verb.items():
        getattr(m, verb).return_value = val
    return m

class TestInsertNewAssignments:
    def test_resolves_enrollment_and_inserts(self):
        assignments_tbl = _tbl(select=[], insert=[])
        with patch("services.calendar_service.table", return_value=assignments_tbl), \
             patch("services.academics.user_enrollment_ids", return_value=[{"id": "e1", "offering_id": "o1"}]), \
             patch("services.academics.enrollment_id_for", return_value="e1") as eif:
            n = cs.insert_new_assignments("user_andres", [
                {"title": "HW1", "due_date": "2026-03-01", "course_id": "CS101", "assignment_type": "homework"},
            ], source="manual")
        assert n == 1
        eif.assert_called_with("user_andres", "CS101", create=True)
        inserted = assignments_tbl.insert.call_args[0][0]
        assert inserted[0]["enrollment_id"] == "e1"
        assert inserted[0]["source"] == "manual"
        assert "user_id" not in inserted[0] and "course_id" not in inserted[0]

    def test_skips_when_no_course(self):
        with patch("services.calendar_service.table", return_value=_tbl(select=[], insert=[])), \
             patch("services.academics.user_enrollment_ids", return_value=[]):
            n = cs.insert_new_assignments("user_andres", [
                {"title": "HW1", "due_date": "2026-03-01"},  # no course_id
            ])
        assert n == 0

    def test_dedup_against_enrollment_set(self):
        # existing row in the user's enrollment has same title+day -> skip
        existing = _tbl(select=[{"title": "HW1", "due_date": "2026-03-01"}], insert=[])
        with patch("services.calendar_service.table", return_value=existing), \
             patch("services.academics.user_enrollment_ids", return_value=[{"id": "e1", "offering_id": "o1"}]), \
             patch("services.academics.enrollment_id_for", return_value="e1"):
            n = cs.insert_new_assignments("user_andres", [
                {"title": "HW1", "due_date": "2026-03-01", "course_id": "CS101"},
            ])
        assert n == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `venv/bin/python -m pytest tests/test_calendar_write_enrollment.py -q`
Expected: FAIL — current `insert_new_assignments` builds `{user_id, course_id}` rows and dedups by `user_id`; `source`/`enrollment_id` assertions fail.

- [ ] **Step 3: Implement write path**

Rewrite in `services/calendar_service.py` (keep `assignment_dedupe_key`, `uuid`, `encrypt_if_present` imports):

```python
def load_existing_assignment_keys(user_id: str) -> set:
    from services.academics import user_enrollment_ids
    enrollments = user_enrollment_ids(user_id)
    if not enrollments:
        return set()
    ids = ",".join(e["id"] for e in enrollments)
    existing_rows = table("assignments").select(
        "title,due_date", filters={"enrollment_id": f"in.({ids})"},
    )
    return {assignment_dedupe_key(r.get("title"), r.get("due_date")) for r in (existing_rows or [])}


def insert_new_assignments(user_id: str, assignments: list[dict], *, source: str = "manual") -> int:
    """Insert assignments (deduped per the user's enrollment set, #16) on the
    enrollment-keyed schema. Each assignment must carry a ``course_id`` — it is
    resolved to the user's enrollment (created if missing). Returns rows inserted."""
    from services.academics import enrollment_id_for
    existing_keys = load_existing_assignment_keys(user_id)
    rows = []
    for a in assignments:
        title = (a.get("title") or "").strip()
        due_raw = (a.get("due_date") or "").strip()
        if not title or not due_raw:
            continue
        key = assignment_dedupe_key(title, due_raw)
        if key in existing_keys:
            continue
        course_id = a.get("course_id")
        enrollment_id = enrollment_id_for(user_id, course_id, create=True) if course_id else None
        if not enrollment_id:
            continue  # decision: every assignment is course-tied
        existing_keys.add(key)
        rows.append({
            "id": str(uuid.uuid4()),
            "enrollment_id": enrollment_id,
            "title": title,
            "due_date": key[1],
            "assignment_type": a.get("assignment_type") or "other",
            "notes": encrypt_if_present(a.get("notes")),  # #126: encrypt at write
            "source": source,
        })
    if rows:
        table("assignments").insert(rows)
    return len(rows)


def save_assignments_to_db(user_id: str, assignments: list, *, source: str = "syllabus") -> int:
    """Write extracted assignment dicts (deduped via insert_new_assignments)."""
    return insert_new_assignments(user_id, assignments, source=source)
```

In `routes/calendar.py`, fix `save_assignments` to pass **raw** notes (the service encrypts once — avoids the prior double-encryption) and tag source:

```python
@router.post("/save")
def save_assignments(body: SaveAssignmentsBody, request: FastAPIRequest):
    require_self(body.user_id, request)
    payload = [
        {
            "title": a.title,
            "course_id": a.course_id,
            "due_date": a.due_date,
            "assignment_type": a.assignment_type,
            "notes": a.notes,  # raw; insert_new_assignments encrypts
        }
        for a in body.assignments
    ]
    saved = insert_new_assignments(body.user_id, payload, source="manual")
    return {"saved_count": saved}
```

- [ ] **Step 4: Run tests**

Run: `venv/bin/python -m pytest tests/test_calendar_write_enrollment.py tests/test_assignment_dedupe.py tests/test_assignment_notes_encryption.py -q`
Expected: new tests PASS. The two existing modules may reference the old schema — if they fail, fix them in Task 6 (note which here); do not delete coverage.

- [ ] **Step 5: Commit**

```bash
git add services/calendar_service.py routes/calendar.py tests/test_calendar_write_enrollment.py
git commit -m "feat(calendar): write assignments via resolved enrollment_id + source tag"
```

---

### Task 4: `suggest_study_blocks` + ownership scoping (`update`/`delete`)

**Files:**
- Modify: `routes/calendar.py` (`suggest_study_blocks` ~236, `update_assignment` ~191, `delete_assignment` ~221)
- Test: `tests/test_calendar_scoping_enrollment.py` (create)

**Interfaces:**
- Consumes: `academics.user_enrollment_ids`, `_read_assignments` (Task 2)
- Produces: module-level `_owned_enrollment_ids(user_id) -> set[str]`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_calendar_scoping_enrollment.py
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient
from main import app

client = TestClient(app)

def _tbl(**rows_by_verb):
    m = MagicMock()
    for verb, val in rows_by_verb.items():
        getattr(m, verb).return_value = val
    return m

def _dispatch(tables):
    def _table(name):
        return tables.get(name) or _tbl(select=[], insert=[], update=[], delete=[])
    return _table

class TestUpdateScoping:
    def test_404_when_assignment_not_in_user_enrollments(self):
        tables = {
            "assignments": _tbl(select=[]),  # no row owned by user's enrollments
        }
        with patch("routes.calendar.table", side_effect=_dispatch(tables)), \
             patch("routes.calendar.academics") as ac:
            ac.user_enrollment_ids.return_value = [{"id": "e1", "offering_id": "o1"}]
            r = client.patch("/api/calendar/assignments/a-other",
                             json={"user_id": "user_andres", "title": "x"})
        assert r.status_code == 404

    def test_updates_owned_assignment(self):
        tables = {"assignments": _tbl(select=[{"id": "a1"}], update=[])}
        with patch("routes.calendar.table", side_effect=_dispatch(tables)), \
             patch("routes.calendar.academics") as ac:
            ac.user_enrollment_ids.return_value = [{"id": "e1", "offering_id": "o1"}]
            r = client.patch("/api/calendar/assignments/a1",
                             json={"user_id": "user_andres", "title": "new"})
        assert r.status_code == 200
        assert r.json() == {"updated": True}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `venv/bin/python -m pytest tests/test_calendar_scoping_enrollment.py -q`
Expected: FAIL — current handlers filter `assignments` by `user_id`, which doesn't exist.

- [ ] **Step 3: Implement scoping + study blocks**

Add helper to `routes/calendar.py`:

```python
def _owned_enrollment_ids(user_id) -> set:
    return {e["id"] for e in academics.user_enrollment_ids(user_id)}
```

Rewrite the existence/ownership checks to scope by `enrollment_id in (user's)`:

```python
@router.patch("/assignments/{assignment_id}")
def update_assignment(assignment_id: str, body: dict, request: FastAPIRequest):
    user_id = body.get("user_id")
    if not user_id:
        raise HTTPException(status_code=400, detail="user_id is required")
    require_self(user_id, request)

    owned = _owned_enrollment_ids(user_id)
    if not owned:
        raise HTTPException(status_code=404, detail="Assignment not found")
    existing = table("assignments").select(
        "id",
        filters={"id": f"eq.{assignment_id}", "enrollment_id": f"in.({','.join(owned)})"},
        limit=1,
    )
    if not existing:
        raise HTTPException(status_code=404, detail="Assignment not found")

    ALLOWED = {"title", "due_date", "assignment_type"}  # course_id no longer settable here
    patch = {k: v for k, v in body.items() if k in ALLOWED}
    if not patch:
        return {"updated": False}
    table("assignments").update(
        patch, filters={"id": f"eq.{assignment_id}", "enrollment_id": f"in.({','.join(owned)})"}
    )
    return {"updated": True}


@router.delete("/assignments/{assignment_id}")
def delete_assignment(assignment_id: str, request: FastAPIRequest, user_id: str = Query(...)):
    require_self(user_id, request)
    owned = _owned_enrollment_ids(user_id)
    if not owned:
        raise HTTPException(status_code=404, detail="Assignment not found")
    existing = table("assignments").select(
        "id",
        filters={"id": f"eq.{assignment_id}", "enrollment_id": f"in.({','.join(owned)})"},
        limit=1,
    )
    if not existing:
        raise HTTPException(status_code=404, detail="Assignment not found")
    table("assignments").delete(
        filters={"id": f"eq.{assignment_id}", "enrollment_id": f"in.({','.join(owned)})"}
    )
    return {"deleted": True}
```

Rewrite `suggest_study_blocks` to read via `_read_assignments`:

```python
@router.post("/suggest-study-blocks")
def suggest_study_blocks(body: StudyBlockBody, request: FastAPIRequest):
    require_self(body.user_id, request)
    today = datetime.utcnow().strftime("%Y-%m-%d")
    assignments = _read_assignments(body.user_id, due_gte=today)
    blocks = []
    for a in assignments:
        cc = a.get("course_code") or ""
        cn = a.get("course_name") or ""
        course_label = f"[{cc}] " if cc else (f"{cn}: " if cn else "")
        blocks.append({
            "topic": f"{course_label}{a['title']}" if course_label else a["title"],
            "suggested_date": a["due_date"],
            "duration_minutes": 60,
            "reason": f"Due {a['due_date']}",
            "related_assignment_id": a["id"],
        })
    return {"study_blocks": blocks[:5]}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `venv/bin/python -m pytest tests/test_calendar_scoping_enrollment.py -q`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add routes/calendar.py tests/test_calendar_scoping_enrollment.py
git commit -m "feat(calendar): enrollment-scoped update/delete + study-block reads"
```

---

### Task 5: `sync_to_google` + `export_to_google` on enrollment_id

**Files:**
- Modify: `routes/calendar.py` (`sync_to_google` ~327, `export_to_google` ~378)
- Test: `tests/test_calendar_sync_export_enrollment.py` (create)

**Interfaces:**
- Consumes: `_owned_enrollment_ids` (Task 4), `_read_assignments` (Task 2), `_require_google_creds` (existing)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_calendar_sync_export_enrollment.py
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient
from main import app

client = TestClient(app)

def _tbl(**rows_by_verb):
    m = MagicMock()
    for verb, val in rows_by_verb.items():
        getattr(m, verb).return_value = val
    return m

def _dispatch(tables):
    def _table(name):
        return tables.get(name) or _tbl(select=[], insert=[], update=[], delete=[])
    return _table

class TestExportScoping:
    def test_export_skips_unowned_id(self):
        tables = {"assignments": _tbl(select=[], update=[])}  # id not owned -> no row
        creds = MagicMock()
        with patch("routes.calendar.table", side_effect=_dispatch(tables)), \
             patch("routes.calendar._require_google_creds", return_value=creds), \
             patch("routes.calendar.build") as build, \
             patch("routes.calendar.academics") as ac:
            ac.user_enrollment_ids.return_value = [{"id": "e1", "offering_id": "o1"}]
            r = client.post("/api/calendar/export",
                            json={"user_id": "user_andres", "assignment_ids": ["a-other"]})
        assert r.status_code == 200
        assert r.json() == {"exported_count": 0, "skipped_count": 0}
        build.return_value.events.return_value.insert.assert_not_called()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `venv/bin/python -m pytest tests/test_calendar_sync_export_enrollment.py -q`
Expected: FAIL — current export filters by `user_id` and selects `courses!left(...)`.

- [ ] **Step 3: Implement sync/export**

For `sync_to_google`: select unsynced via the owned enrollment set instead of `user_id`, drop the `courses!left` embed and derive the label from `_read_assignments` data or a per-enrollment course-meta lookup. Concretely, replace the two `unsynced` selects with one scoped read of unsynced rows:

```python
@router.post("/sync")
def sync_to_google(body: SyncBody, request: FastAPIRequest):
    require_self(body.user_id, request)
    creds = _require_google_creds(body.user_id)
    service = build("calendar", "v3", credentials=creds)

    owned = _owned_enrollment_ids(body.user_id)
    if not owned:
        return {"synced_count": 0}
    in_clause = f"in.({','.join(owned)})"
    unsynced = table("assignments").select(
        "id,enrollment_id,title,due_date,notes,google_event_id",
        filters={"enrollment_id": in_clause, "google_event_id": "is.null"},
    )
    unsynced += table("assignments").select(
        "id,enrollment_id,title,due_date,notes,google_event_id",
        filters={"enrollment_id": in_clause, "google_event_id": "eq."},
    )

    enr_to_offering = {e["id"]: e.get("offering_id") for e in academics.user_enrollment_ids(body.user_id)}
    cache = {}
    synced = 0
    for a in unsynced:
        if not a.get("due_date"):
            continue
        meta = _course_meta_cached(enr_to_offering.get(a.get("enrollment_id")), cache)
        cc = meta.get("course_code") or ""
        cn = meta.get("course_name") or ""
        course_label = f"[{cc}] " if cc else (f"{cn}: " if cn else "")
        event = {
            "summary": f"{course_label}{a['title']}" if course_label else a["title"],
            "description": decrypt_if_present(a.get("notes")) or "",
            "start": {"date": a["due_date"]},
            "end": {"date": a["due_date"]},
        }
        created = service.events().insert(calendarId="primary", body=event).execute()
        table("assignments").update(
            {"google_event_id": created["id"]},
            filters={"id": f"eq.{a['id']}", "enrollment_id": in_clause},
        )
        synced += 1
    return {"synced_count": synced}
```

For `export_to_google`: replace the per-id `filters={"id":..., "user_id":...}` with `{"id":..., "enrollment_id": in.(owned)}`, drop `courses!left`, and build the label via `_course_meta_cached(enr_to_offering[a["enrollment_id"]], cache)`. Mirror the select column list above (`id,enrollment_id,title,due_date,notes,google_event_id`). Keep the existing skip-when-`google_event_id` and write-back-scoped-by-enrollment behavior (#123).

- [ ] **Step 4: Run test to verify it passes**

Run: `venv/bin/python -m pytest tests/test_calendar_sync_export_enrollment.py tests/test_calendar_export_idor.py -q`
Expected: new test PASSES. If `test_calendar_export_idor.py` asserts the old `user_id` scoping, update it to assert enrollment scoping (same IDOR guarantee, new key) — do not weaken the security assertion.

- [ ] **Step 5: Commit**

```bash
git add routes/calendar.py tests/test_calendar_sync_export_enrollment.py tests/test_calendar_export_idor.py
git commit -m "feat(calendar): enrollment-scoped Google sync/export"
```

---

### Task 6: Syllabus-save source tag + reconcile existing tests + full-suite + staging verify

**Files:**
- Modify: `routes/documents.py` (the two `save_assignments_to_db` call sites ~475, ~988)
- Modify: `tests/test_calendar_routes.py`, `tests/test_assignment_dedupe.py`, `tests/test_assignment_notes_encryption.py`, `tests/test_calendar_sibling_write_scoping.py` (update any asserting the old `user_id`/`course_id`/`courses!left` schema)
- Test: full suite

- [ ] **Step 1: Tag syllabus saves**

In `routes/documents.py`, both call sites already attach `course_id` per assignment. Pass the source explicitly:

```python
save_assignments_to_db(user_id, legacy, source="syllabus")
```
```python
save_assignments_to_db(user_id, ai["assignments"], source="syllabus")
```

- [ ] **Step 2: Run the full calendar/assignment suite, see what the schema change broke**

Run: `venv/bin/python -m pytest tests/test_calendar_routes.py tests/test_assignment_dedupe.py tests/test_assignment_notes_encryption.py tests/test_calendar_sibling_write_scoping.py -q`
Expected: failures in tests that mock the old single-table `select` shape or assert `user_id`/`course_id` columns.

- [ ] **Step 3: Update those tests to the enrollment-keyed contract**

For each failing test, switch its mock to the `_tbl`/`_dispatch` multi-table pattern and assert the new behavior: writes produce `enrollment_id`+`source` rows (no `user_id`/`course_id`); reads decorate via course-meta; scoping uses `enrollment_id`. Keep every existing behavioral guarantee (dedup by title+day, notes encryption at write, IDOR scoping) — only the key changes. Show the corrected mock per test (mirror Tasks 2-5).

- [ ] **Step 4: Run the entire backend suite**

Run: `venv/bin/python -m pytest tests/ -q`
Expected: PASS (no regressions). Investigate and fix any calendar/assignment-related failure; unrelated pre-existing failures (if any) are out of scope — note them.

- [ ] **Step 5: Verify against staging DB (real reproduction)**

Re-run the staging reproduction harness used during diagnosis (queries the live staging DB for the real user via `.env.staging`):

Run: `PYTHONPATH=. venv/bin/python <scratchpad>/repro_dashboard.py`
Expected: `/api/calendar/upcoming/{user}` line flips from `FAIL 400` to `OK 0 rows` (the user has no enrollments yet), and every other endpoint stays OK.

> Note: this only exercises the read query path against staging. The deployed backend fix lands when this branch merges to `main` and Railway redeploys the staging backend.

- [ ] **Step 6: Commit**

```bash
git add routes/documents.py tests/
git commit -m "feat(calendar): tag syllabus saves + migrate calendar tests to enrollment schema"
```

---

## Self-Review (completed by plan author)

- **Spec coverage:** resolver (Task 1) ✓; read path incl. empty-enrollment dashboard unblock (Task 2) ✓; write path + dedup + source (Task 3) ✓; auto-create enrollment (`enrollment_id_for(create=True)`, Tasks 1+3) ✓; ownership scoping (Task 4) ✓; sync/export (Task 5) ✓; syllabus-save source + encryption-at-write (Tasks 3+6) ✓; tests rewritten (all tasks + Task 6) ✓; staging verification (Task 6) ✓. No schema migration (none added) ✓.
- **Placeholders:** none — every code step shows real code; Task 5 export references the exact column list and helpers from earlier tasks.
- **Type consistency:** `enrollment_id_for(user_id, course_id, *, create=False)`, `user_enrollment_ids(user_id)->list[dict]`, `_read_assignments(user_id,*,due_gte=None,limit=None)`, `_course_meta_cached(offering_id,cache)`, `_owned_enrollment_ids(user_id)->set`, `insert_new_assignments(...,*,source="manual")`, `save_assignments_to_db(...,*,source="syllabus")` — used consistently across tasks.

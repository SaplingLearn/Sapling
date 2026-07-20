# Semester-scoped learning + Courses & Semesters hub — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a settings-only semester switcher (a redesigned "Courses & Semesters" modal) that scopes the knowledge graph, Learn, Study, Quiz, and the Dashboard graph to a chosen term, and block re-adding a course already taken in any semester.

**Architecture:** Path A — read-time filtering, **no schema change / no migration**. The graph stays keyed on the abstract `course_id`. A new `academics` resolver turns a term label into the set of course ids the user is enrolled in for that term; the graph/recommendations reads filter to that set when a `semester` param is present (absent = all terms, unchanged). The frontend holds the active semester in `localStorage` (mirrors `useLayoutPref`) and threads it through the learning surfaces. Enrolling is broadened to reject a course the user already has in *any* term (the no-retake rule).

**Tech Stack:** Backend — FastAPI, Supabase via `db/connection.table()`, pytest with the mock-`table` factory from `tests/conftest.py`. Frontend — Next.js/React, Vitest + `@testing-library/react`.

---

## File Structure

Backend:
- Modify `backend/services/academics.py` — add `term_id_for_label`, `user_course_ids_for_term`.
- Modify `backend/services/graph_service.py` — `get_graph(user_id, semester=None)`, `get_recommendations(user_id, semester=None)`, no-retake guard in `add_course`.
- Modify `backend/routes/graph.py` — optional `semester` query param on the two GET routes.
- Modify `backend/tests/test_academics.py`, `backend/tests/test_graph_service.py` — new tests.

Frontend:
- Modify `frontend/src/lib/api.ts` — `EnrolledCourse.term`; `semester` arg on `getGraph`/`getRecommendations`.
- Create `frontend/src/lib/useActiveSemester.ts` — hook + `distinctTerms`/`resolveActiveSemester` helpers.
- Create `frontend/src/lib/useActiveSemester.test.ts` — vitest unit test for the helpers.
- Modify `frontend/src/components/ManageCoursesModal.tsx` — group by term, term tabs (set active semester), "Already taken · <term>" state, "Personal learning — Coming soon" row.
- Modify `frontend/src/components/screens/Dashboard.tsx`, `Tree.tsx`, `Learn.tsx`, `Quiz.tsx` — thread the active semester.

---

## Task 1: Academics resolvers — `term_id_for_label` + `user_course_ids_for_term`

**Files:**
- Modify: `backend/services/academics.py` (add two functions after `list_terms`, around `:51`)
- Test: `backend/tests/test_academics.py`

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_academics.py`:

```python
# ── term_id_for_label ────────────────────────────────────────────────────────

def test_term_id_for_label_resolves_by_label():
    rows = {"terms": [{"id": "t-spring"}]}
    with patch.object(ac, "table", side_effect=_factory(rows)):
        assert ac.term_id_for_label("Spring 2026") == "t-spring"


def test_term_id_for_label_falls_back_to_id():
    # First select (by label) empty; second (by id) returns the row.
    factory = _factory({}, select_seqs={"terms": [[], [{"id": "t-xyz"}]]})
    with patch.object(ac, "table", side_effect=factory):
        assert ac.term_id_for_label("t-xyz") == "t-xyz"


def test_term_id_for_label_none_for_empty():
    with patch.object(ac, "table", side_effect=_factory({})):
        assert ac.term_id_for_label("") is None


# ── user_course_ids_for_term ─────────────────────────────────────────────────

def test_user_course_ids_for_term_intersects_enrollments_and_term():
    rows = {
        "enrollments": [{"offering_id": "off-1"}, {"offering_id": "off-2"}],
        # course_offerings filtered by (id in off-1,off-2) AND term_id eq t-spring
        "course_offerings": [{"course_id": "bio-101"}],
    }
    with patch.object(ac, "table", side_effect=_factory(rows)):
        assert ac.user_course_ids_for_term("user_andres", "t-spring") == {"bio-101"}


def test_user_course_ids_for_term_empty_when_no_enrollments():
    with patch.object(ac, "table", side_effect=_factory({"enrollments": []})):
        assert ac.user_course_ids_for_term("user_andres", "t-spring") == set()


def test_user_course_ids_for_term_empty_args():
    with patch.object(ac, "table", side_effect=_factory({})):
        assert ac.user_course_ids_for_term("", "t") == set()
        assert ac.user_course_ids_for_term("u", "") == set()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_academics.py -k "term_id_for_label or user_course_ids_for_term" -v`
Expected: FAIL with `AttributeError: module 'services.academics' has no attribute 'term_id_for_label'`.

- [ ] **Step 3: Implement the two functions**

In `backend/services/academics.py`, insert after `list_terms` (after `:51`):

```python
def term_id_for_label(label: str | None) -> str | None:
    """Resolve a semester **label** (e.g. "Spring 2026") to a term id.

    Falls back to treating the value as a term id directly. ``None``/empty → None.
    Mirrors the mapping in ``routes/gradebook.py::_term_id_for_semester`` so the
    ``semester`` query value resolves the same way across the API.
    """
    if not label:
        return None
    rows = table("terms").select("id", filters={"label": f"eq.{label}"}, limit=1)
    if rows:
        return rows[0]["id"]
    rows = table("terms").select("id", filters={"id": f"eq.{label}"}, limit=1)
    return rows[0]["id"] if rows else None


def user_course_ids_for_term(user_id: str, term_id: str) -> set[str]:
    """The abstract ``course_id``s the user is enrolled in for a given term.

    ``enrollments (user_id) → offering_id → course_offerings (term_id) → course_id``.
    Multi-step reads (this module avoids PostgREST embedded filters); short-circuits
    on empty sets. Deliberately **not** cached — enrollments mutate.
    """
    if not user_id or not term_id:
        return set()
    enr = table("enrollments").select(
        "offering_id", filters={"user_id": f"eq.{user_id}"}
    ) or []
    off_ids = {e["offering_id"] for e in enr if e.get("offering_id")}
    if not off_ids:
        return set()
    offs = table("course_offerings").select(
        "course_id",
        filters={"id": f"in.({','.join(off_ids)})", "term_id": f"eq.{term_id}"},
    ) or []
    return {o["course_id"] for o in offs if o.get("course_id")}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_academics.py -k "term_id_for_label or user_course_ids_for_term" -v`
Expected: PASS (6 passed).

- [ ] **Step 5: Commit**

```bash
git add backend/services/academics.py backend/tests/test_academics.py
git commit -m "feat(academics): term_id_for_label + user_course_ids_for_term resolvers"
```

---

## Task 2: `get_graph(semester=)` filters nodes/edges/stats by term

**Files:**
- Modify: `backend/services/graph_service.py:144` (`get_graph`)
- Test: `backend/tests/test_graph_service.py`

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_graph_service.py` (add the imports at the top if missing: `from unittest.mock import patch` and `import services.graph_service as gs`):

```python
def test_get_graph_semester_filters_nodes_and_stats():
    """With a semester, only that term's course nodes survive and stats recount."""
    enrolled = [
        {"id": "e1", "offering_id": "o1", "course_id": "bio-101",
         "color": None, "nickname": None, "enrolled_at": "2026-01-01", "term": "Spring 2026",
         "courses": {"course_code": "BIO-101", "course_name": "Biology", "department": "", "school": ""}},
        {"id": "e2", "offering_id": "o2", "course_id": "psy-110",
         "color": None, "nickname": None, "enrolled_at": "2025-09-01", "term": "Fall 2025",
         "courses": {"course_code": "PSY-110", "course_name": "Psych", "department": "", "school": ""}},
    ]
    nodes = [
        {"id": "n1", "course_id": "bio-101", "concept_name": "Cells",
         "mastery_score": 0.4, "mastery_tier": "learning", "times_studied": 1},
        {"id": "n2", "course_id": "psy-110", "concept_name": "Freud",
         "mastery_score": 0.9, "mastery_tier": "mastered", "times_studied": 2},
    ]

    def fake_table(name):
        from unittest.mock import MagicMock
        m = MagicMock(name=f"table({name})")
        m.select.return_value = {"graph_nodes": nodes, "graph_edges": [],
                                 "node_mastery_events": [], "users": [{"streak_count": 3}]}.get(name, [])
        return m

    with patch.object(gs, "_user_enrolled_courses", return_value=enrolled), \
         patch.object(gs, "ensure_user_exists", return_value=None), \
         patch.object(gs, "table", side_effect=fake_table), \
         patch("services.academics.term_id_for_label", return_value="t-spring"), \
         patch("services.academics.user_course_ids_for_term", return_value={"bio-101"}):
        out = gs.get_graph("user_andres", semester="Spring 2026")

    concept_nodes = [n for n in out["nodes"] if not n.get("is_subject_root")]
    assert {n["course_id"] for n in concept_nodes} == {"bio-101"}
    assert out["stats"]["total_nodes"] == 1
    assert out["stats"]["mastered"] == 0
    # Only the Spring subject-root hub is built.
    roots = [n for n in out["nodes"] if n.get("is_subject_root")]
    assert {r["course_id"] for r in roots} == {"bio-101"}


def test_get_graph_no_semester_returns_all():
    enrolled = []
    nodes = [
        {"id": "n1", "course_id": "bio-101", "concept_name": "Cells",
         "mastery_score": 0.4, "mastery_tier": "learning", "times_studied": 1},
        {"id": "n2", "course_id": "psy-110", "concept_name": "Freud",
         "mastery_score": 0.9, "mastery_tier": "mastered", "times_studied": 2},
    ]

    def fake_table(name):
        from unittest.mock import MagicMock
        m = MagicMock(name=f"table({name})")
        m.select.return_value = {"graph_nodes": nodes, "graph_edges": [],
                                 "node_mastery_events": [], "users": []}.get(name, [])
        return m

    with patch.object(gs, "_user_enrolled_courses", return_value=enrolled), \
         patch.object(gs, "ensure_user_exists", return_value=None), \
         patch.object(gs, "table", side_effect=fake_table):
        out = gs.get_graph("user_andres")

    assert out["stats"]["total_nodes"] == 2
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd backend && python -m pytest tests/test_graph_service.py -k "get_graph_semester or get_graph_no_semester" -v`
Expected: FAIL — `get_graph()` got an unexpected keyword argument `semester`.

- [ ] **Step 3: Implement the filter**

In `backend/services/graph_service.py`, change the signature at `:144` and add the filter block:

```python
def get_graph(user_id: str, semester: str | None = None) -> dict:
    ensure_user_exists(user_id)

    # Get all enrolled courses for this user
    enrolled_courses = _user_enrolled_courses(user_id)

    # Optional semester scope (Path A): restrict to the courses the user is
    # enrolled in for that term. `allowed_course_ids is None` means "all terms".
    allowed_course_ids: set[str] | None = None
    if semester:
        from services.academics import term_id_for_label, user_course_ids_for_term
        term_id = term_id_for_label(semester)
        allowed_course_ids = (
            user_course_ids_for_term(user_id, term_id) if term_id else set()
        )
        enrolled_courses = [
            c for c in enrolled_courses if c.get("course_id") in allowed_course_ids
        ]

    # Get all graph nodes for this user
    nodes_raw = table("graph_nodes").select("*", filters={"user_id": f"eq.{user_id}"})
    nodes = nodes_raw or []
    if allowed_course_ids is not None:
        nodes = [n for n in nodes if n.get("course_id") in allowed_course_ids]
    node_ids = {n["id"] for n in nodes}
```

This replaces the existing `:144-153` block (up to and including `node_ids = {n["id"] for n in nodes}`). Everything below is unchanged: edges already filter to `node_ids` (`:165`), stats count over `nodes` (`:190-193`), and subject roots build from `enrolled_courses` (`:234`) — all now operate on the filtered sets.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_graph_service.py -k "get_graph_semester or get_graph_no_semester" -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add backend/services/graph_service.py backend/tests/test_graph_service.py
git commit -m "feat(graph): scope get_graph to a semester's courses"
```

---

## Task 3: `get_recommendations(semester=)` filters by term

**Files:**
- Modify: `backend/services/graph_service.py:629` (`get_recommendations`)
- Test: `backend/tests/test_graph_service.py`

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_graph_service.py`:

```python
def test_get_recommendations_semester_filters_by_course():
    rows = [
        {"concept_name": "Cells", "mastery_score": 0.2, "mastery_tier": "struggling", "course_id": "bio-101"},
        {"concept_name": "Freud", "mastery_score": 0.3, "mastery_tier": "learning", "course_id": "psy-110"},
    ]

    def fake_table(name):
        from unittest.mock import MagicMock
        m = MagicMock(name=f"table({name})")
        m.select.return_value = rows if name == "graph_nodes" else []
        return m

    with patch.object(gs, "table", side_effect=fake_table), \
         patch("services.academics.term_id_for_label", return_value="t-spring"), \
         patch("services.academics.user_course_ids_for_term", return_value={"bio-101"}):
        recs = gs.get_recommendations("user_andres", semester="Spring 2026")

    assert [r["concept_name"] for r in recs] == ["Cells"]
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd backend && python -m pytest tests/test_graph_service.py -k get_recommendations_semester -v`
Expected: FAIL — unexpected keyword argument `semester`.

- [ ] **Step 3: Implement the filter**

Replace `get_recommendations` at `backend/services/graph_service.py:629`:

```python
def get_recommendations(user_id: str, semester: str | None = None) -> list:
    allowed: set[str] | None = None
    if semester:
        from services.academics import term_id_for_label, user_course_ids_for_term
        term_id = term_id_for_label(semester)
        allowed = user_course_ids_for_term(user_id, term_id) if term_id else set()

    rows = table("graph_nodes").select(
        "concept_name,mastery_score,mastery_tier,course_id",
        filters={
            "user_id": f"eq.{user_id}",
            "mastery_tier": "in.(struggling,learning,unexplored)",
        },
        order="mastery_score.asc",
        # When scoping, over-fetch then trim after filtering so we still return up
        # to 5 recommendations for the term.
        limit=5 if allowed is None else 50,
    )
    if allowed is not None:
        rows = [r for r in rows if r.get("course_id") in allowed][:5]
    recs = []
    for r in rows:
        tier = r["mastery_tier"]
        if tier == "unexplored":
            reason = "You haven't studied this yet — a great place to start."
        elif tier == "struggling":
            reason = f"You're struggling here ({int(r['mastery_score']*100)}%) — focus here to improve."
        else:
            reason = f"You're making progress ({int(r['mastery_score']*100)}%) — keep going!"
        recs.append({"concept_name": r["concept_name"], "reason": reason})
    return recs
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd backend && python -m pytest tests/test_graph_service.py -k get_recommendations_semester -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/services/graph_service.py backend/tests/test_graph_service.py
git commit -m "feat(graph): scope recommendations to a semester's courses"
```

---

## Task 4: `add_course` no-retake guard (reject a course taken in any term)

**Files:**
- Modify: `backend/services/graph_service.py:315` (`add_course`)
- Test: `backend/tests/test_graph_service.py`

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_graph_service.py`:

```python
def test_add_course_rejects_course_taken_in_any_term():
    """A course the user already has in a *different* term can't be re-added."""
    def fake_table(name):
        from unittest.mock import MagicMock
        m = MagicMock(name=f"table({name})")
        m.select.return_value = [{"id": "bio-101"}] if name == "courses" else []
        m.insert.side_effect = AssertionError("must not insert a duplicate enrollment")
        return m

    with patch.object(gs, "table", side_effect=fake_table), \
         patch("services.academics.user_offering_ids_for_course", return_value=["off-old"]), \
         patch("services.academics.term_for_offering", return_value={"label": "Fall 2025"}):
        result = gs.add_course("user_andres", "bio-101")

    assert result["already_existed"] is True
    assert result["term"] == "Fall 2025"


def test_add_course_enrolls_when_never_taken():
    inserted = []

    def fake_table(name):
        from unittest.mock import MagicMock
        m = MagicMock(name=f"table({name})")
        m.select.return_value = [{"id": "bio-101"}] if name == "courses" else []
        def _insert(data):
            inserted.append((name, data))
            return [data]
        m.insert.side_effect = _insert
        return m

    with patch.object(gs, "table", side_effect=fake_table), \
         patch("services.academics.user_offering_ids_for_course", return_value=[]), \
         patch("services.academics.resolve_offering", return_value="off-new"), \
         patch("services.course_context_service.update_course_context", return_value=None):
        result = gs.add_course("user_andres", "bio-101")

    assert result["already_existed"] is False
    assert any(name == "enrollments" for name, _ in inserted)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_graph_service.py -k "add_course_rejects or add_course_enrolls" -v`
Expected: FAIL — the reject test currently creates a second enrollment (no `term` key / triggers the insert AssertionError).

- [ ] **Step 3: Implement the guard**

In `backend/services/graph_service.py`, edit `add_course` (`:322`). After the catalog-existence check and **before** `resolve_offering(...)`, insert the guard:

```python
    # Verify the abstract course exists in the catalog
    course_check = table("courses").select("id", filters={"id": f"eq.{course_id}"})
    if not course_check:
        return {"course_id": course_id, "error": "Course not found in catalog"}

    from services.academics import (
        resolve_offering,
        user_offering_ids_for_course,
        term_for_offering,
    )

    # No-retake rule: a course already enrolled in ANY term can't be added again.
    # (Broadens the old current-term-only check so cross-semester duplicates are
    # rejected instead of silently creating a second enrollment.)
    existing_offerings = user_offering_ids_for_course(user_id, course_id)
    if existing_offerings:
        term = term_for_offering(existing_offerings[0]) or {}
        return {
            "course_id": course_id,
            "already_existed": True,
            "term": term.get("label", ""),
        }

    offering_id = resolve_offering(course_id, create=True)
    if not offering_id:
        return {"course_id": course_id, "error": "No term available to enroll into"}
```

Leave the rest of `add_course` (the current-offering `existing` check at `:332-338`, the insert, the context refresh) unchanged — the `from services.academics import resolve_offering` line that used to sit at `:327` is now covered by the combined import above, so delete that now-duplicate import line.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_graph_service.py -k "add_course_rejects or add_course_enrolls" -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add backend/services/graph_service.py backend/tests/test_graph_service.py
git commit -m "feat(graph): reject re-adding a course taken in any term (no-retake)"
```

---

## Task 5: Route wiring — `semester` query param on the two GET graph routes

**Files:**
- Modify: `backend/routes/graph.py:4` (import), `:24` (`get_user_graph`), `:30` (`get_user_recommendations`)
- Test: `backend/tests/test_graph_service.py` (route-level via FastAPI TestClient)

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_graph_service.py`:

```python
def test_graph_route_passes_semester_through():
    from fastapi.testclient import TestClient
    import routes.graph as graph_route
    from main import app

    captured = {}

    def fake_get_graph(user_id, semester=None):
        captured["user_id"] = user_id
        captured["semester"] = semester
        return {"nodes": [], "edges": [], "stats": {}}

    with patch.object(graph_route, "get_graph", side_effect=fake_get_graph):
        client = TestClient(app)
        resp = client.get("/api/graph/user_andres?semester=Spring%202026")

    assert resp.status_code == 200
    assert captured == {"user_id": "user_andres", "semester": "Spring 2026"}
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd backend && python -m pytest tests/test_graph_service.py -k graph_route_passes_semester -v`
Expected: FAIL — `semester` is `None` (route ignores the query param).

- [ ] **Step 3: Implement the route change**

In `backend/routes/graph.py`, add `Query` to the fastapi import at `:4`:

```python
from fastapi import APIRouter, HTTPException, Request, Query
```

Replace `:24-33`:

```python
@router.get("/{user_id}")
def get_user_graph(user_id: str, request: Request, semester: str | None = Query(None)):
    require_self(user_id, request)
    return get_graph(user_id, semester)


@router.get("/{user_id}/recommendations")
def get_user_recommendations(user_id: str, request: Request, semester: str | None = Query(None)):
    require_self(user_id, request)
    return {"recommendations": get_recommendations(user_id, semester)}
```

- [ ] **Step 4: Run the test to verify it passes, then the full backend suite**

Run: `cd backend && python -m pytest tests/test_graph_service.py -k graph_route_passes_semester -v`
Expected: PASS.
Run: `cd backend && python -m pytest tests/ -q`
Expected: all pass (no regressions).

- [ ] **Step 5: Commit**

```bash
git add backend/routes/graph.py backend/tests/test_graph_service.py
git commit -m "feat(graph): accept optional semester query param on graph + recommendations"
```

---

## Task 6: API client — `EnrolledCourse.term` + `semester` on `getGraph`/`getRecommendations`

**Files:**
- Modify: `frontend/src/lib/api.ts:37-41` (`getGraph`, `getRecommendations`), `:43-54` (`EnrolledCourse`)

- [ ] **Step 1: Add `term` to `EnrolledCourse`**

In `frontend/src/lib/api.ts`, add a field to the `EnrolledCourse` interface (after `nickname`, `:51`):

```typescript
export interface EnrolledCourse {
  enrollment_id: string;
  course_id: string;
  course_code: string;
  course_name: string;
  school: string;
  department: string;
  color: string | null;
  nickname: string | null;
  term: string;
  node_count: number;
  enrolled_at: string;
}
```

- [ ] **Step 2: Thread `semester` through the two fetchers**

Replace `:37-41`:

```typescript
// Graph
export const getGraph = (userId: string, semester?: string) =>
  fetchJSON<{ nodes: any[]; edges: any[]; stats: any }>(
    `/api/graph/${userId}${semester ? `?semester=${encodeURIComponent(semester)}` : ""}`,
  );

export const getRecommendations = (userId: string, semester?: string) =>
  fetchJSON<{ recommendations: any[] }>(
    `/api/graph/${userId}/recommendations${semester ? `?semester=${encodeURIComponent(semester)}` : ""}`,
  );
```

- [ ] **Step 3: Verify types compile**

Run: `cd frontend && npm run typecheck`
Expected: PASS (no type errors introduced; `term` is additive and existing callers still compile).

- [ ] **Step 4: Commit**

```bash
git add frontend/src/lib/api.ts
git commit -m "feat(api): EnrolledCourse.term + optional semester on graph fetchers"
```

---

## Task 7: `useActiveSemester` hook + term helpers

**Files:**
- Create: `frontend/src/lib/useActiveSemester.ts`
- Test: `frontend/src/lib/useActiveSemester.test.ts`

- [ ] **Step 1: Write the failing test**

Create `frontend/src/lib/useActiveSemester.test.ts`:

```typescript
import { describe, expect, it } from "vitest";
import { distinctTerms, resolveActiveSemester } from "./useActiveSemester";

const c = (term: string) => ({ term });

describe("distinctTerms", () => {
  it("dedups preserving first-seen order and drops blanks", () => {
    expect(distinctTerms([c("Fall 2025"), c("Spring 2026"), c("Fall 2025"), c("")]))
      .toEqual(["Fall 2025", "Spring 2026"]);
  });
});

describe("resolveActiveSemester", () => {
  it("keeps the active value when it is among the enrolled terms", () => {
    expect(resolveActiveSemester("Fall 2025", [c("Fall 2025"), c("Spring 2026")]))
      .toBe("Fall 2025");
  });

  it("defaults to the most-recently-enrolled term when active is unset/stale", () => {
    // courses arrive enrolled_at ascending → last is most recent.
    expect(resolveActiveSemester("", [c("Fall 2025"), c("Spring 2026")]))
      .toBe("Spring 2026");
    expect(resolveActiveSemester("Winter 1999", [c("Fall 2025"), c("Spring 2026")]))
      .toBe("Spring 2026");
  });

  it("returns empty string when there are no terms", () => {
    expect(resolveActiveSemester("", [])).toBe("");
  });
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd frontend && npx vitest run src/lib/useActiveSemester.test.ts`
Expected: FAIL — cannot resolve `./useActiveSemester`.

- [ ] **Step 3: Implement the hook + helpers**

Create `frontend/src/lib/useActiveSemester.ts`:

```typescript
"use client";

import { useEffect, useState } from "react";

export const ACTIVE_SEMESTER_STORAGE_KEY = "sapling_active_semester";
const CHANGE_EVENT = "sapling-active-semester-change";

/** Distinct term labels in first-seen order, dropping blanks. */
export function distinctTerms(courses: { term: string }[]): string[] {
  const seen = new Set<string>();
  const out: string[] = [];
  for (const c of courses) {
    if (c.term && !seen.has(c.term)) {
      seen.add(c.term);
      out.push(c.term);
    }
  }
  return out;
}

/**
 * The semester to actually scope by: the stored `active` value when it is one
 * of the user's enrolled terms, else the most-recently-enrolled term. Courses
 * arrive `enrolled_at` ascending, so the last distinct term is the most recent.
 * (Heuristic default; can be upgraded to term `sort_key` ordering later.)
 */
export function resolveActiveSemester(active: string, courses: { term: string }[]): string {
  const terms = distinctTerms(courses);
  if (active && terms.includes(active)) return active;
  return terms.length ? terms[terms.length - 1] : "";
}

function read(): string {
  if (typeof window === "undefined") return "";
  return window.localStorage.getItem(ACTIVE_SEMESTER_STORAGE_KEY) ?? "";
}

/** [activeSemester, setActiveSemester] — persisted to localStorage, cross-tab + same-tab reactive. */
export function useActiveSemester(): [string, (v: string) => void] {
  const [sem, setSem] = useState<string>("");

  useEffect(() => {
    setSem(read());
    const onStorage = (e: StorageEvent) => {
      if (e.key === ACTIVE_SEMESTER_STORAGE_KEY) setSem(read());
    };
    const onCustom = () => setSem(read());
    window.addEventListener("storage", onStorage);
    window.addEventListener(CHANGE_EVENT, onCustom);
    return () => {
      window.removeEventListener("storage", onStorage);
      window.removeEventListener(CHANGE_EVENT, onCustom);
    };
  }, []);

  const update = (v: string) => {
    if (typeof window === "undefined") return;
    window.localStorage.setItem(ACTIVE_SEMESTER_STORAGE_KEY, v);
    setSem(v);
    window.dispatchEvent(new Event(CHANGE_EVENT));
  };

  return [sem, update];
}
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd frontend && npx vitest run src/lib/useActiveSemester.test.ts`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/useActiveSemester.ts frontend/src/lib/useActiveSemester.test.ts
git commit -m "feat(frontend): useActiveSemester hook + term-resolution helpers"
```

---

## Task 8: Dashboard — scope graph, recommendations, and course panels to the active semester

**Files:**
- Modify: `frontend/src/components/screens/Dashboard.tsx` (imports; `load` at `:256-298`; `courseProgress` at `:326-344`; the `CoursesKey`/legacy panels' course source)

- [ ] **Step 1: Import the hook + helper**

Add to the imports block near `:11-13`:

```typescript
import { useActiveSemester, resolveActiveSemester } from "@/lib/useActiveSemester";
```

- [ ] **Step 2: Read the hook and default it once courses load**

Inside `Dashboard()`, after `const { userId, userName, userReady } = useUser();` (`:192`), add:

```typescript
  const [activeSemester, setActiveSemester] = useActiveSemester();
```

In `load` (`:256`), pass the active semester to the scoped fetchers and write back a default when unset. Replace the `Promise.all` block (`:261-267`) and the `setCourses(cs)` line (`:268-269`):

```typescript
      const [graphRes, coursesRes, assignsRes, sessionsRes, recsRes] = await Promise.all([
        getGraph(userId, activeSemester || undefined),
        getCourses(userId),
        getUpcomingAssignments(userId),
        getSessions(userId, 10),
        getRecommendations(userId, activeSemester || undefined).catch(() => ({ recommendations: [] })),
      ]);
      const cs = coursesRes.courses || [];
      setCourses(cs);
      // First run with no stored semester: default to the most-recent enrolled term.
      if (!activeSemester) {
        const def = resolveActiveSemester("", cs);
        if (def) setActiveSemester(def);
      }
```

Add `activeSemester` to the `load` dependency array (`:298`):

```typescript
  }, [userId, activeSemester]);
```

- [ ] **Step 3: Scope the dashboard's course panels to the active semester**

The graph nodes are already server-scoped. Filter the course list the panels render so chips/progress match. Replace `courseProgress` (`:326`):

```typescript
  const scopedCourses = React.useMemo(
    () => (activeSemester ? courses.filter((c) => c.term === activeSemester) : courses),
    [courses, activeSemester],
  );

  const courseProgress = React.useMemo(() => {
    return scopedCourses.map(c => {
```

...and change that memo's dependency array from `[courses, nodes]` (`:344`) to `[scopedCourses, nodes]`.

Also update the graph-header course chips that read `courses.slice(0, 5)` (`:400`) to `scopedCourses.slice(0, 5)`, and the legacy header count `courses.length` (`:396`) to `scopedCourses.length`.

Note: keep passing the **full** `courses` list to `<ManageCoursesModal ... courses={courses} />` (`:1039`) — the hub needs every term to group them.

- [ ] **Step 4: Verify build + types**

Run: `cd frontend && npm run typecheck && npm run lint`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/screens/Dashboard.tsx
git commit -m "feat(dashboard): scope graph, recommendations, and course panels to active semester"
```

---

## Task 9: Tree / Learn / Quiz — thread the active semester into their graph loads

**Files:**
- Modify: `frontend/src/components/screens/Tree.tsx:62-63`
- Modify: `frontend/src/components/screens/Learn.tsx:154-155`
- Modify: `frontend/src/components/screens/Quiz.tsx:39-40`

- [ ] **Step 1: Tree — scope graph + course list**

In `Tree.tsx`, add the import:

```typescript
import { useActiveSemester } from "@/lib/useActiveSemester";
```

Inside the component, add `const [activeSemester] = useActiveSemester();`. Change the graph fetch (`:62`) to `getGraph(userId, activeSemester || undefined)`, add `activeSemester` to that load effect's dependency array, and where the fetched courses are stored/used for the course rail, filter with `activeSemester ? courses.filter(c => c.term === activeSemester) : courses`.

- [ ] **Step 2: Learn — scope graph + course picker**

In `Learn.tsx`, add the import and `const [activeSemester] = useActiveSemester();`. Change the graph fetch (`:155`) to `getGraph(userId, activeSemester || undefined)`, add `activeSemester` to the load effect's deps, and filter the course-picker list (`filtered`, `:1378-1382`) to `activeSemester ? c.term === activeSemester : true` alongside the existing predicates.

- [ ] **Step 3: Quiz — scope graph + course picker**

In `Quiz.tsx`, add the import and `const [activeSemester] = useActiveSemester();`. Change the graph fetch (`:40`) to `getGraph(userId, activeSemester || undefined)`, add `activeSemester` to the deps, and filter its course list to the active term the same way.

- [ ] **Step 4: Verify build + types**

Run: `cd frontend && npm run typecheck && npm run lint`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/screens/Tree.tsx frontend/src/components/screens/Learn.tsx frontend/src/components/screens/Quiz.tsx
git commit -m "feat(learn): scope Tree/Learn/Quiz to the active semester"
```

---

## Task 10: "Courses & Semesters" hub — group by term, term tabs, no-retake messaging, Personal learning

**Files:**
- Modify: `frontend/src/components/ManageCoursesModal.tsx`

- [ ] **Step 1: Import the hook/helpers and read the active semester**

Add to the imports (after `:16`):

```typescript
import { useActiveSemester, distinctTerms, resolveActiveSemester } from "@/lib/useActiveSemester";
```

Inside `ManageCoursesModal(...)`, after `const toast = useToast();` (`:34`), add:

```typescript
  const [activeSemester, setActiveSemester] = useActiveSemester();
  const terms = React.useMemo(() => distinctTerms(courses), [courses]);
  const activeTerm = resolveActiveSemester(activeSemester, courses);
```

- [ ] **Step 2: Add the term-tab selector above the course list**

Replace the header of the "Your courses" section (`:104`) so the tabs render above it:

```tsx
          <div className="label-micro" style={{ marginBottom: 8 }}>Semester</div>
          {terms.length === 0 ? (
            <div style={{ fontSize: 12, color: "var(--text-muted)", marginBottom: 16 }}>
              No semesters yet — add a course below.
            </div>
          ) : (
            <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginBottom: 16 }}>
              {terms.map((t) => (
                <button
                  key={t}
                  onClick={() => setActiveSemester(t)}
                  className="btn btn--sm"
                  style={{
                    background: t === activeTerm ? "var(--accent-soft)" : "var(--bg-panel)",
                    color: t === activeTerm ? "var(--accent)" : "var(--text-dim)",
                    border: "1px solid var(--border)",
                  }}
                >
                  {t}
                </button>
              ))}
            </div>
          )}

          <div className="label-micro" style={{ marginBottom: 8 }}>
            {activeTerm ? `Courses · ${activeTerm}` : "Your courses"}
          </div>
```

- [ ] **Step 3: Show only the active term's courses in the list**

Replace the enrolled-course map (`:108-112`) so it renders the active term's courses:

```tsx
          <div style={{ display: "flex", flexDirection: "column", gap: 8, marginBottom: 20 }}>
            {courses.filter((c) => !activeTerm || c.term === activeTerm).length === 0 && (
              <div style={{ fontSize: 12, color: "var(--text-muted)" }}>
                No courses in this semester yet.
              </div>
            )}
            {courses
              .filter((c) => !activeTerm || c.term === activeTerm)
              .map((c) => (
                <EnrolledRow key={c.course_id} userId={userId} course={c} onChanged={onChanged} />
              ))}
          </div>
```

- [ ] **Step 4: "Already taken · <term>" state in the add-search results**

The dedup map already covers all terms (`enrolledIds`, `:65`). Build a course_id → term lookup and use it for the disabled label. After `const enrolledIds = ...` (`:65`), add:

```typescript
  const enrolledTermById = React.useMemo(() => {
    const m = new Map<string, string>();
    for (const c of courses) m.set(c.course_id, c.term);
    return m;
  }, [courses]);
```

Replace the add-result button (`:148-158`):

```tsx
                  <button
                    className="btn btn--sm"
                    disabled={enrolled}
                    onClick={() => handleAdd(c)}
                    style={{
                      opacity: enrolled ? 0.55 : 1,
                      background: enrolled ? "var(--bg-subtle)" : undefined,
                    }}
                    title={enrolled ? "A course can only be taken once across semesters" : undefined}
                  >
                    {enrolled
                      ? `Already taken${enrolledTermById.get(c.id) ? ` · ${enrolledTermById.get(c.id)}` : ""}`
                      : <><Icon name="plus" size={12} /> Add</>}
                  </button>
```

- [ ] **Step 5: "Personal learning — Coming soon" row + retitle the modal**

Change the modal title (`:96`) from `My Courses` to `Courses & Semesters`. Before the closing `</div>` of the scroll body (after the add-results list, i.e. after `:162`), add:

```tsx
          <div style={{ borderTop: "1px solid var(--border)", marginTop: 20, paddingTop: 16 }}>
            <button
              className="btn btn--sm"
              disabled
              aria-disabled="true"
              style={{ opacity: 0.5, cursor: "not-allowed" }}
            >
              <Icon name="sparkle" size={12} /> Personal learning
            </button>
            <div style={{ fontSize: 11, color: "var(--text-muted)", marginTop: 6 }}>
              Coming soon
            </div>
          </div>
```

- [ ] **Step 6: Retitle the dashboard entry point**

In `frontend/src/components/screens/Dashboard.tsx`, change the legacy "Manage" button label (`:738`, currently `<Icon name="cog" .../> Manage`) to `<Icon name="cog" size={12} /> Courses & Semesters`. (The sidebar `CoursesKey` "Manage" is an icon-only button — leave its `title="Manage courses"` as-is, or update to "Courses & Semesters" for consistency.)

- [ ] **Step 7: Verify build + types + lint**

Run: `cd frontend && npm run typecheck && npm run lint`
Expected: PASS.

- [ ] **Step 8: Manual smoke test**

Run: `cd frontend && npm run dev` (backend running per `backend/` README). In the browser:
- Open the dashboard → click "Courses & Semesters" → confirm term tabs appear, switching a tab changes which courses list and (after close/reload of the dashboard) scopes the graph.
- In "Add a course", search a course you already took in another term → confirm the button reads "Already taken · <term>" and is disabled.
- Confirm the "Personal learning" button is grayed out with "Coming soon" beneath it.

- [ ] **Step 9: Commit**

```bash
git add frontend/src/components/ManageCoursesModal.tsx frontend/src/components/screens/Dashboard.tsx
git commit -m "feat(courses): Courses & Semesters hub — term tabs, no-retake label, personal-learning placeholder"
```

---

## Final verification

- [ ] **Backend suite green**

Run: `cd backend && python -m pytest tests/ -q`
Expected: all pass.

- [ ] **Backend lint**

Run: `cd backend && ruff check .`
Expected: no new violations.

- [ ] **Frontend tests + typecheck + lint**

Run: `cd frontend && npm run test && npm run typecheck && npm run lint`
Expected: all pass.

---

## Notes / decisions carried from the spec

- **Path A only.** No schema change, no migration, no re-keying of `graph_nodes`. Retakes are disallowed (Task 4), so a per-retake graph never arises.
- **Default semester** is the most-recently-*enrolled* term (Task 7 `resolveActiveSemester`), a heuristic standing in for "current term"; upgrade to term `sort_key` ordering later if needed.
- **Session/quiz-exam listing scoping** (mentioned in spec §1) is achieved via client-side course-picker filtering in Task 9 rather than new backend params — the pickers already read `getCourses`, which carries `term`. No separate endpoint changes needed.
- **Out of scope:** Gradebook's existing `SemesterChips`; implementing "Personal learning".

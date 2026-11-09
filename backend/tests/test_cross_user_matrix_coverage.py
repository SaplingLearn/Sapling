"""Hermetic half of the cross-user matrix (#115, rls-step2-plan section 5).

Needs only the app's routes, never the stack, so it runs in the normal suite.
It is what makes the integration matrix grow with the app:

* a route with an ``_id``/``_ids`` input that is in neither
  ``ID_SOURCES`` nor an exclusion list fails here, before it can ship
  untested;
* every generated case is validated against the route's declared parameters,
  so the integration lane cannot pass a case that FastAPI would have 422'd
  before the handler (and therefore before the ownership check) ran.
"""
from __future__ import annotations

import pytest
from fastapi import APIRouter, FastAPI
from fastapi.routing import APIRoute

from tests import cross_user_matrix as m

# Placeholder A-values: the shape of the real ones (strings; a list for _ids).
_A_VALUES = {
    name: (f"a-{name}" if not src.many else [f"a-{name}"])
    for name, src in m.ID_SOURCES.items()
}


@pytest.fixture(scope="module")
def routes():
    return m.app_routes()


def test_route_walk_finds_a_plausible_number_of_routes(routes):
    """A FastAPI internals change that stops the walk from descending into
    included routers would leave a handful of routes and make every other
    check here vacuous."""
    assert len(routes) >= m.MIN_EXPECTED_ROUTES, (
        f"route enumeration found only {len(routes)} routes; the walk in "
        "tests/cross_user_matrix.py::iter_api_routes no longer matches how this "
        "FastAPI version stores included routers"
    )
    paths = {r.path for r in routes}
    for expected in ("/api/notes/{note_id}", "/api/quiz/attempts/{attempt_id}",
                     "/api/social/rooms/{room_id}/messages", "/api/admin/users"):
        assert expected in paths


def test_route_walk_handles_both_fastapi_shapes():
    """Pre-0.138 ``app.routes`` holds prefixed APIRoutes; 0.138+ holds
    ``_IncludedRouter`` objects. Both must yield the same full paths."""
    router = APIRouter()

    @router.get("/{note_id}")
    def _get(note_id: str):  # pragma: no cover - never called
        return {}

    app = FastAPI()
    app.include_router(router, prefix="/api/notes")
    assert [(r.method, r.path) for r in m.iter_api_routes(app.routes)
            if r.path.startswith("/api/")] == [("GET", "/api/notes/{note_id}")]

    legacy = APIRoute("/api/notes/{note_id}", _get, methods=["GET"])
    assert [(r.method, r.path) for r in m.iter_api_routes([legacy])] == [
        ("GET", "/api/notes/{note_id}")
    ]


def test_every_id_input_is_registered_or_excluded(routes):
    missing = m.uncovered_id_inputs(routes)
    assert not missing, (
        "These routes take an id-like input the cross-user matrix does not know. "
        "Add the param to tests/cross_user_matrix.py::ID_SOURCES (with SQL that "
        "finds one of user A's rows), or to EXCLUDED_PARAMS with a reason:\n"
        + "\n".join(f"  {meth} {path}  [{loc}] {name}" for meth, path, loc, name in missing)
    )


def test_untyped_bodies_have_an_override(routes):
    """A ``body: dict`` handler's fields are invisible to introspection; the
    matrix can only probe it honestly with a hand-written body."""
    bare = [
        f"{r.method} {r.path}" for r in routes
        if m.route_group(r) == "user" and m.has_untyped_body(r) and r.key not in m.BODY_OVERRIDES
        and any(i.name in m.ID_SOURCES or i.name in m.SELF_PARAMS for i in m.id_inputs(r))
    ]
    assert not bare, "add a BODY_OVERRIDES entry for: " + ", ".join(bare)


def test_registry_entries_are_not_stale(routes):
    keys = {r.key for r in routes}
    names = {i.name for r in routes for i in m.id_inputs(r) if m.route_group(r) == "user"}
    stale = []
    for table_name, entries in (
        ("KNOWN_403", m.KNOWN_403), ("RESOURCE_EXPECT", m.RESOURCE_EXPECT),
        ("SWAP_EXPECT", m.SWAP_EXPECT), ("SWAP_SKIP", m.SWAP_SKIP),
        ("RESOURCE_SKIP", m.RESOURCE_SKIP), ("BODY_OVERRIDES", m.BODY_OVERRIDES),
        ("QUERY_OVERRIDES", m.QUERY_OVERRIDES), ("PATH_OVERRIDES", m.PATH_OVERRIDES),
        ("SELF_ENROLLING", m.SELF_ENROLLING),
    ):
        stale += [f"{table_name}: {k}" for k in entries if k not in keys]
    stale += [f"KNOWN_LEAKS: {k}" for k in m.KNOWN_LEAKS if (k[1], k[2]) not in keys]
    for table_name, entries in (("ID_SOURCES", m.ID_SOURCES), ("EXCLUDED_PARAMS", m.EXCLUDED_PARAMS)):
        stale += [f"{table_name}: {n}" for n in entries if n not in names]
    assert not stale, "entries naming no current route/param:\n  " + "\n  ".join(stale)


def test_every_case_passes_request_validation(routes):
    """Each case must reach its handler: a 422 would mean the ownership check
    never ran, which the integration lane counts as a failure."""
    by_key = {r.key: r for r in routes}
    problems = []
    for case in m.build_cases(routes, _A_VALUES):
        for p in m.validate_case(by_key[case.key], case):
            problems.append(f"[{case.group}] {case.method} {case.path}: {p}")
    assert not problems, "\n".join(problems)


def test_validation_catches_what_fastapi_would_422(routes):
    """The check above is only worth something if it can fail."""
    info = next(r for r in routes if r.key == ("POST", "/api/notes/{note_id}/chat"))
    case = m.build_case(info, group="resource", a_values=_A_VALUES,
                        self_id=m.USER_B, target_id=m.USER_A)
    assert m.validate_case(info, case) == []
    del case.json["message"]
    assert any("message" in p for p in m.validate_case(info, case))
    q_info = next(r for r in routes if r.key == ("GET", "/api/notes/{note_id}"))
    q_case = m.build_case(q_info, group="resource", a_values=_A_VALUES,
                          self_id=m.USER_B, target_id=m.USER_A)
    q_case.query.pop("user_id")
    assert m.validate_case(q_info, q_case) == ["missing required query user_id"]


def test_cases_cover_every_group(routes):
    cases = m.build_cases(routes, _A_VALUES)
    groups = {g: [c for c in cases if c.group == g] for g in ("resource", "swap", "admin", "server")}
    assert all(groups.values()), {g: len(cs) for g, cs in groups.items()}
    # Every admin route is in the admin group, with 403 expected.
    assert all(c.expect == (403,) for c in groups["admin"])
    # Resource cases carry A's values in the probed params and B as "self".
    note = next(c for c in groups["resource"] if c.key == ("GET", "/api/notes/{note_id}"))
    assert note.url == "/api/notes/a-note_id" and note.query["user_id"] == m.USER_B
    # Swap cases put A in the self param.
    swap = next(c for c in groups["swap"] if c.key == ("GET", "/api/notes/{note_id}"))
    assert swap.query["user_id"] == m.USER_A
    # A shared key on a route that also probes an owned id is neutralised.
    guide = next(c for c in groups["resource"]
                 if c.key == ("GET", "/api/study-guide/{user_id}/guide"))
    assert guide.query["course_id"] == m.COURSE_SHARED and guide.query["exam_id"] == "a-exam_id"
    # Destructive requests run last within their group.
    swap_paths = [c.path for c in groups["swap"]]
    assert swap_paths[-1].endswith(("/account", "/leave", "/disconnect/{user_id}"))


def test_known_leaks_are_cases(routes):
    """KNOWN_LEAKS is strict in the lane; an entry that builds no case would
    silently never be checked."""
    cases = {(c.group, c.method, c.path) for c in m.build_cases(routes, _A_VALUES)}
    cases.add(("probe", "POST", "/api/social/rooms/{room_id}/messages"))
    assert set(m.KNOWN_LEAKS) <= cases


def test_enforce_404_entries_are_known_403_resource_cases(routes):
    """ENFORCE_404 narrows KNOWN_403 entries under `db_user_scope=enforce`; an
    entry outside KNOWN_403 (or naming no resource case) would never be
    narrowed, so the RLS-hides-it-first claim would go unchecked."""
    assert m.ENFORCE_404 <= set(m.KNOWN_403)
    resource = {c.key for c in m.build_cases(routes, _A_VALUES) if c.group == "resource"}
    assert m.ENFORCE_404 <= resource
    assert "enforce" in m.MODES and m.MODES[0] == "off"


def test_enrollment_gated_cases_run_before_b_enrolls_in_the_course(routes):
    """#115: the gated course-keyed writes expect 404 because B is not
    enrolled in A's A-only course. `POST /api/graph/{user_id}/courses` (B
    adding that catalog course for themselves, a legitimate 200) makes B
    enrolled for every case after it — which is how the lane's
    `POST /api/notes` turned 404 -> 200. Every gated case must sort first."""
    resource = [c for c in m.build_cases(routes, _A_VALUES) if c.group == "resource"]
    gated = [i for i, c in enumerate(resource) if "require_course_enrollment" in c.note]
    enrolling = [i for i, c in enumerate(resource) if c.key in m.SELF_ENROLLING]
    assert gated and enrolling
    assert max(gated) < min(enrolling), [resource[i].key for i in gated if i > min(enrolling)]
    # ...and the DELETE that drops that enrollment again still comes after.
    drop = next(i for i, c in enumerate(resource)
                if c.key == ("DELETE", "/api/graph/{user_id}/courses/{course_id}"))
    assert max(enrolling) < drop
    # The gated set covers the routes #115 gates.
    assert {resource[i].key for i in gated} >= {
        ("POST", "/api/notes"),
        ("POST", "/api/learn/start-session"),
        ("POST", "/api/learn/start-session/stream"),
        ("POST", "/api/documents/upload"),
        ("POST", "/api/documents/upload/sync"),
        ("POST", "/api/documents/course/{course_id}/scan-concepts"),
    }

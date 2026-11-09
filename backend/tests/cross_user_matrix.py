"""The cross-user test matrix: route enumeration, the id registry, case building (#115).

Shared by two test files:

* ``tests/test_cross_user_matrix_coverage.py`` (hermetic, the normal suite):
  needs only the app's routes. It fails when a route grows an id-like input
  that is neither in ``ID_SOURCES`` nor excluded with a reason, and it checks
  every generated case against the route's declared parameters, so the lane
  cannot go green on a 422 that never reached a handler.
* ``tests/integration/test_cross_user_matrix_db.py`` (integration lane): runs
  the cases against real local Supabase as user B (``rich-user-second``)
  carrying user A's (``rich-user-active``) ids, and judges the responses.

The spec is ``docs/security/rls-step2-plan.md`` section 5. The groups:

* ``resource``: B's session and B's own "who am I" id, A's resource id. 404,
  no A-owned marker in the body, A's rows unchanged.
* ``swap``: B's session passing ``user_id = A``. 403 (the ``require_self``
  contract).
* ``admin``: every admin route as B. 403.
* ``server``: the bearer-token server-to-server routes with B's cookie. 401
  or 404, never a session-authorised answer.
* ``allowlist``: the intentional cross-user reads. 200 with no private field.

The lane runs every group under each ``db_user_scope`` flag mode in
``MODES`` (``off`` and ``enforce``). Under ``enforce`` the ``KNOWN_403``
entries in ``ENFORCE_404`` (load-then-``require_self``) must turn into 404s:
RLS hides the row before the handler can see whose it is. The membership 403s
in ``social.py`` are computed by code from ``room_members`` (and the social
router runs as service role until step 2e) and keep their off-mode answer.

Nothing here imports the app at module scope: the integration conftest must
load ``backend/.env`` before ``config`` is imported.
"""
from __future__ import annotations

import enum
import re
import types
import typing
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping

#: `db_user_scope` flag modes the integration matrix runs under (plan section
#: 4.4), applied through the flag's env override SAPLING_FLAG_DB_USER_SCOPE.
#: "shadow" is not a mode of its own here: its answers are the service role's
#: by construction, i.e. "off".
MODES = ["off", "enforce"]

#: The enumeration must find at least this many routes. 233 on 2026-11-08; a
#: walk that silently stops descending (a FastAPI internals change) would find
#: a handful and make every check below vacuous.
MIN_EXPECTED_ROUTES = 150

ID_PARAM = re.compile(r"(?:_id|_ids)$")

# ── Fixture identities (literals mirroring db/seed_local_rich) ──────────────

USER_A = "rich-user-active"
USER_B = "rich-user-second"
#: The CS101 course both A and B are enrolled in: the NEUTRAL value for a
#: course_id that is not the thing being probed.
COURSE_SHARED = "rich-course-cs101"
#: Stand-in for an id the admin group needs but never reaches.
MISSING_ID = "cross-user-matrix-missing"

# Rows the integration fixture adds on top of the rich baseline (plan section 5).
PRIVATE_ROOM = "rich-matrix-room-private"
PRIVATE_ROOM_INVITE = "MTX-PRIV-A"
PRIVATE_ROOM_NAME = "Matrix Private Room A"
PRIVATE_ROOM_MESSAGE_ID = "22222222-2222-4222-8222-000000000001"
PRIVATE_ROOM_MESSAGE_TEXT = "MATRIX-PRIVATE-ROOM-MESSAGE-7f3a only A can read this"
PUBLIC_ROOM = "rich-matrix-room-public"
PUBLIC_ROOM_INVITE = "MTX-PUB-A"
PRIVATE_CHUNK_ID = "rich-matrix-chunk-private-a"
PRIVATE_CHUNK_TEXT = "MATRIX-PRIVATE-CHUNK-91c2 A's private upload text"

#: Plaintext that only A's rows hold. If one shows up in a response to B (and B
#: did not send it), that response leaked A's data. Deliberately long and
#: specific: names, course titles and the shared-room transcript are visible to
#: B by design and are NOT markers.
A_PRIVATE_MARKERS: tuple[str, ...] = (
    "rich.active@richlocal.test",                        # users.email
    "A variable binds a name to a value",                # notes.body
    "can be added componentwise",                        # notes.body
    "CS101 syllabus: weekly homework, one midterm",      # documents.summary
    "Lecture notes covering vectors, matrices",          # documents.summary
    "Practiced factorial and fibonacci",                 # sessions.summary_json
    "Covered the dot product",                           # sessions.summary_json
    "What is a dot product?",                            # messages.content
    "function calls itself to solve a smaller version",  # messages.content
    "A scalar λ such that Av = λv",                      # flashcards.back
    "A named storage location for a value",              # flashcards.back
    "What keyword declares a variable in Python?",       # quiz_attempts.questions_json
    "confuses = with ==",                                # quiz_context.context_json
    "The midterm's hardest questions are recursive traces",  # study_guides.content
    "Final Project Proposal",                            # assignments.title
    "Lab 1: Microscopy",                                 # assignments.title
    "Essay Draft: Rhetorical Analysis",                  # assignments.title
    "The tutor cited the wrong lecture.",                # feedback.comment
    PRIVATE_ROOM_MESSAGE_TEXT,
    PRIVATE_ROOM_NAME,
    PRIVATE_ROOM_INVITE,
    PRIVATE_CHUNK_TEXT,
)


# ── Parameter classification ────────────────────────────────────────────────

#: "Who am I" params. In the resource group they carry B's own id; in the swap
#: group, A's.
SELF_PARAMS = frozenset({"user_id", "requester_id", "from_user_id"})

#: Another user named as the target of B's action (befriend, kick, unfriend).
#: A's id in the resource group, B's in the swap group (B forging A acting on B).
TARGET_USER_PARAMS = frozenset({"to_user_id", "friend_id", "member_id"})

OWNED = "owned"
SHARED_KEY = "shared_key"


@dataclass(frozen=True)
class IdSource:
    """How to find one of A's rows for a param.

    ``kind``:
      * ``owned``: a row A owns. Probing it as B must not reach A's data.
      * ``shared_key``: a catalog key (the abstract course) that A happens to
        be enrolled in and B is not. B may legitimately act on it for
        themselves (enrol, list their own empty notes), so it only must not
        surface A's data or change A's rows. On a route that also takes an
        owned id it is set to ``COURSE_SHARED`` instead, so it cannot mask the
        owned probe with an early "not enrolled" 404.

    ``sql`` runs on the integration lane's psycopg connection with ``%(a)s`` =
    A and ``%(b)s`` = B, and returns one text id.
    """
    kind: str
    sql: str
    many: bool = False


def _owned(sql: str, *, many: bool = False) -> IdSource:
    return IdSource(OWNED, sql, many)


_NOTE = "SELECT id::text FROM notes WHERE user_id = %(a)s ORDER BY id LIMIT 1"
_SESSION = "SELECT id::text FROM sessions WHERE user_id = %(a)s ORDER BY id LIMIT 1"
_ATTEMPT = "SELECT id::text FROM quiz_attempts WHERE user_id = %(a)s ORDER BY id LIMIT 1"
_DOCUMENT = "SELECT id::text FROM documents WHERE user_id = %(a)s ORDER BY id LIMIT 1"
_NODE = "SELECT id::text FROM graph_nodes WHERE user_id = %(a)s ORDER BY id LIMIT 1"
_ASSIGNMENT = (
    "SELECT a.id::text FROM assignments a JOIN enrollments e ON e.id = a.enrollment_id "
    "WHERE e.user_id = %(a)s ORDER BY a.id LIMIT 1"
)
_PRIVATE_ROOM = (
    "SELECT r.id::text FROM rooms r WHERE r.owner_id = %(a)s AND NOT r.is_public "
    "AND NOT EXISTS (SELECT 1 FROM room_members m WHERE m.room_id = r.id AND m.user_id = %(b)s) "
    "ORDER BY r.id LIMIT 1"
)
_PRIVATE_MESSAGE = (
    "SELECT m.id::text FROM room_messages m JOIN rooms r ON r.id = m.room_id "
    "WHERE m.user_id = %(a)s AND r.owner_id = %(a)s AND NOT r.is_public "
    "AND NOT EXISTS (SELECT 1 FROM room_members x WHERE x.room_id = r.id AND x.user_id = %(b)s) "
    "ORDER BY m.id LIMIT 1"
)
_A_ONLY_COURSE = (
    "SELECT o.course_id::text FROM enrollments e JOIN course_offerings o ON o.id = e.offering_id "
    "WHERE e.user_id = %(a)s AND o.course_id NOT IN ("
    "  SELECT o2.course_id FROM enrollments e2 JOIN course_offerings o2 ON o2.id = e2.offering_id "
    "  WHERE e2.user_id = %(b)s) "
    "ORDER BY o.course_id LIMIT 1"
)

#: param name -> how to get one of A's rows. A route param matching
#: ``_id$|_ids$`` must be here, in SELF/TARGET_USER_PARAMS, or in
#: EXCLUDED_PARAMS, or the coverage test fails.
ID_SOURCES: dict[str, IdSource] = {
    "note_id": _owned(_NOTE),
    "session_id": _owned(_SESSION),
    "attempt_id": _owned(_ATTEMPT),
    "quiz_id": _owned(_ATTEMPT),            # /api/quiz/submit: the attempt id
    "source_attempt_id": _owned(_ATTEMPT),  # /api/quiz/generate retry-misses source
    "document_id": _owned(_DOCUMENT),
    "doc_id": _owned(_DOCUMENT),            # /api/gradebook/syllabus/apply
    "document_ids": _owned(_DOCUMENT, many=True),  # /api/library/documents/folder
    "folder_id": _owned(                    # /api/library (matrix_world seeds one)
        "SELECT id::text FROM library_folders WHERE user_id = %(a)s ORDER BY id LIMIT 1"
    ),
    "card_id": _owned("SELECT id::text FROM flashcards WHERE user_id = %(a)s ORDER BY id LIMIT 1"),
    "node_id": _owned(_NODE),
    "concept_node_id": _owned(_NODE),
    "anchor_node_id": _owned(_NODE),
    "assignment_id": _owned(_ASSIGNMENT),
    "assignment_ids": _owned(_ASSIGNMENT, many=True),
    "exam_id": _owned(_ASSIGNMENT),         # study guides key on an exam assignment
    "category_id": _owned(
        "SELECT c.id::text FROM gradebook_categories c JOIN enrollments e "
        "ON e.id = c.enrollment_id WHERE e.user_id = %(a)s ORDER BY c.id LIMIT 1"
    ),
    "room_id": _owned(_PRIVATE_ROOM),
    "message_id": _owned(_PRIVATE_MESSAGE),
    "reply_to_id": _owned(_PRIVATE_MESSAGE),
    "request_id": _owned(
        "SELECT id::text FROM friend_requests WHERE from_user_id = %(a)s "
        "AND status = 'pending' ORDER BY created_at, id LIMIT 1"
    ),
    "course_id": IdSource(SHARED_KEY, _A_ONLY_COURSE),
    "sapling_course_id": IdSource(SHARED_KEY, _A_ONLY_COURSE),
}

#: Neutral stand-in for a shared_key param on a route that also probes an
#: owned id.
NEUTRAL_VALUES: dict[str, str] = {
    "course_id": COURSE_SHARED,
    "sapling_course_id": COURSE_SHARED,
}

#: Id-shaped params that do not name a row a user owns. Each needs a reason.
EXCLUDED_PARAMS: dict[str, str] = {
    "turn_id": "client-generated idempotency key; the stored row id is uuid5(session_id:turn_id), "
               "so it is namespaced by a session whose ownership is checked first",
    "question_id": "index of a question inside the caller's own attempt (the attempt is probed)",
    "topic_id": "topic key inside the caller's own enrollment-scoped outline (the course is probed)",
    "popup_id": "OAuth popup correlation nonce, stored only in the signed state cookie",
    "gradescope_course_id": "external Gradescope id; sync uses the caller's own Gradescope credentials",
    "role_id": "catalog id (roles); holding a role is checked against the caller",
    "cosmetic_id": "catalog id (cosmetics); ownership is checked against the caller",
    "achievement_ids": "catalog ids (achievements); earned-ness is checked against the caller",
    "course_ids": "onboarding catalog selection, not a user-owned row",
}

#: Route-level coverage outside the per-param matrix. Admin and server routes
#: are covered wholesale by their group (B is rejected before any id is read).
ADMIN_PREFIX = "/api/admin/"
ADMIN_EXTRA = frozenset({("GET", "/api/gemini-test")})
SERVER_PREFIX = "/api/internal/"

#: Routes whose resource case is not run, with the reason. Their swap case
#: still runs.
RESOURCE_SKIP: dict[tuple[str, str], str] = {
    ("POST", "/api/flashcards/generate"):
        "a foreign session_id is silently dropped (flashcards.py session_owned_by) and the "
        "route then runs the `flashcards` agent, which has no function-mode handler, so the "
        "lane would 5xx (UnregisteredHandlerError) instead of judging the ownership check",
}

#: Resource cases that answer 403 instead of 404 under flag `off`: the handler
#: loads the row (or the room membership) and then rejects. Allowed under
#: `off`. The load-then-require_self ones must become 404 under `enforce`.
KNOWN_403: dict[tuple[str, str], str] = {
    ("GET", "/api/quiz/attempts/{attempt_id}"): "quiz.py _load_owned_attempt: load, then require_self",
    ("POST", "/api/quiz/attempts/{attempt_id}/answer"): "quiz.py _load_owned_attempt",
    ("POST", "/api/quiz/attempts/{attempt_id}/abandon"): "quiz.py _load_owned_attempt",
    ("POST", "/api/quiz/submit"): "quiz.py submit: load attempt, then require_self",
    ("POST", "/api/gradebook/syllabus/apply"): "gradebook.py: 'Document not yours' after load "
                                               "(404 if B has no current CS enrollment)",
    ("POST", "/api/social/public-rooms/{room_id}/join"): "social.py: private room is invite-only",
    ("GET", "/api/social/rooms/{room_id}/overview"): "social.py: membership check (code, not RLS)",
    ("GET", "/api/social/rooms/{room_id}/activity"): "social.py: membership check",
    ("POST", "/api/social/rooms/{room_id}/match"): "social.py: membership check",
    ("DELETE", "/api/social/rooms/{room_id}/members/{member_id}"): "social.py: owner check",
    ("GET", "/api/social/rooms/{room_id}/messages"): "social.py: membership check",
    ("POST", "/api/social/rooms/{room_id}/messages"): "social.py: membership check",
    ("DELETE", "/api/social/rooms/{room_id}/messages/{message_id}"): "social.py: author check after load",
    ("PATCH", "/api/social/rooms/{room_id}/messages/{message_id}"): "social.py: author check after load",
    ("POST", "/api/social/friends/requests/{request_id}/accept"): "social.py _load_request: not your request",
    ("POST", "/api/social/friends/requests/{request_id}/decline"): "social.py _load_request",
    ("DELETE", "/api/social/friends/requests/{request_id}"): "social.py: sender check after load",
    ("POST", "/api/social/rooms/{room_id}/leave"):
        "social.py: membership check (the delete's own result; #115 fixed the non-member write)",
    ("POST", "/api/social/rooms/{room_id}/messages/{message_id}/reactions"):
        "social.py: membership check, then the message must be in room_id (#115)",
}

#: The KNOWN_403 entries that are "load the row, then require_self": under
#: `enforce` the row is invisible to B's token before the handler runs, so the
#: answer must be exactly 404 (``_expected`` in the integration test).
ENFORCE_404: frozenset[tuple[str, str]] = frozenset({
    ("GET", "/api/quiz/attempts/{attempt_id}"),
    ("POST", "/api/quiz/attempts/{attempt_id}/answer"),
    ("POST", "/api/quiz/attempts/{attempt_id}/abandon"),
    ("POST", "/api/quiz/submit"),
    # Not POST /api/gradebook/syllabus/apply: it answers 403 "Document not yours"
    # for a missing document AND a foreign one (`not doc_rows or ...`), so RLS
    # hiding A's row leaves the status at 403 under enforce too (final E2E
    # pass, 2026-11-08). No existence oracle either way.
})

#: Resource cases whose correct answer today is not 404 and not a leak.
RESOURCE_EXPECT: dict[tuple[str, str], tuple[tuple[int, ...], str]] = {
    ("DELETE", "/api/learn/sessions/{session_id}"):
        ((200,), "no-op {'deleted': true}: session_owned_by is False, returns before deleting"),
    ("POST", "/api/feedback"):
        ((200,), "the foreign session link is set to NULL; the row is B's"),
    ("POST", "/api/graph/{user_id}/nodes"):
        ((200,), "B's node is created; the anchor lookup is filtered to B, so no edge to A's node"),
    ("DELETE", "/api/notes/{note_id}"):
        ((200,), "no-op {'deleted': true}: the delete is filtered by user_id = B"),
    ("GET", "/api/notes/{note_id}/concepts"):
        ((200,), "{'concepts': []}: graph_nodes re-filtered by user_id = B"),
    ("POST", "/api/gradebook/assignments"):
        ((400, 404), "400 'Category not in your gradebook' (404 if B has no current CS enrollment)"),
    ("POST", "/api/calendar/export"):
        ((400, 401), "Google not configured (400) / B not connected (401), before any scoping"),
    # #115 course-keyed writes: B is not enrolled in A's course, so the
    # require_course_enrollment gate answers 404 before any work (before the
    # multipart OCR pipeline too, which is why the uploads are no longer
    # RESOURCE_SKIP). Before the fix they wrote into A's class (B's own rows,
    # but in A's course and its shared chunk pool).
    ("POST", "/api/documents/upload"):
        ((404,), "not enrolled in the course: academics.require_course_enrollment"),
    ("POST", "/api/documents/upload/sync"):
        ((404,), "not enrolled in the course: academics.require_course_enrollment"),
    ("POST", "/api/documents/course/{course_id}/scan-concepts"):
        ((404,), "not enrolled in the course: academics.require_course_enrollment"),
    ("POST", "/api/notes"):
        ((404,), "not enrolled in the course: academics.require_course_enrollment"),
    ("POST", "/api/learn/start-session"):
        ((404,), "not enrolled in the course: academics.require_course_enrollment"),
    ("POST", "/api/learn/start-session/stream"):
        ((404,), "not enrolled in the course: academics.require_course_enrollment"),
}

#: Swap cases whose correct answer is not 403.
SWAP_EXPECT: dict[tuple[str, str], tuple[tuple[int, ...], str]] = {
    ("POST", "/api/feedback"): ((200,), "body.user_id is ignored; the row is attributed to the session"),
    ("POST", "/api/issue-reports"): ((200,), "body.user_id is ignored; the row is attributed to the session"),
    ("GET", "/api/profile/username/check"): ((200,), "unauthenticated availability check by design"),
}

#: Routes with a self param that are intentionally cross-user; covered by the
#: allowlist group instead of the swap group.
SWAP_SKIP: dict[tuple[str, str], str] = {
    ("GET", "/api/profile/{user_id}"): "public profile (allowlist group)",
    ("GET", "/api/profile/{user_id}/roles"):
        "roles of any live user, for any signed-in session (allowlist group); "
        "anonymous is a 401 since #115",
}

#: Confirmed cross-user leaks the matrix reproduces today, each to be fixed in
#: its own PR. STRICT: a case listed here that stops leaking FAILS, so the
#: entry is removed in the fix PR. Key: (group, method, path).
KNOWN_LEAKS: dict[tuple[str, str, str], str] = {
    # Empty. The three W1b entries (toggle_reaction, leave_room as a
    # non-member, and the cross-room reply_to_id read) were fixed by the #115
    # leak-fix PR; the reply_to probe in the integration lane now judges that
    # path strictly.
}

#: Bodies the signature cannot describe (a ``body: dict`` handler) or whose
#: synthesized defaults would fail a handler-level check before the ownership
#: one. Values may be ``SELF`` (the group's "who am I" id) or ``Ref(name)``
#: (resolved like an introspected id param, and counted as one for coverage).
@dataclass(frozen=True)
class Ref:
    name: str


SELF = Ref("<self>")

BODY_OVERRIDES: dict[tuple[str, str], dict[str, Any]] = {
    ("PATCH", "/api/documents/doc/{document_id}"): {"category": "other", "user_id": SELF},
    ("POST", "/api/documents/doc/{document_id}/scan-concepts"): {"user_id": SELF},
    ("POST", "/api/documents/course/{course_id}/scan-concepts"): {"user_id": SELF},
    ("PATCH", "/api/calendar/assignments/{assignment_id}"): {"user_id": SELF, "title": "matrix"},
    ("POST", "/api/study-guide/regenerate"):
        {"user_id": SELF, "course_id": Ref("course_id"), "exam_id": Ref("exam_id")},
    ("PATCH", "/api/learn/sessions/{session_id}"): {"user_id": SELF, "topic": "matrix"},
    ("POST", "/api/learn/mode-switch"): {"new_mode": "socratic"},
    ("POST", "/api/learn/chat"): {"message": "matrix probe"},
    ("POST", "/api/learn/chat/stream"): {"message": "matrix probe"},
    ("POST", "/api/quiz/attempts/{attempt_id}/answer"): {"question_index": 0, "selected_index": 0},
    ("PATCH", "/api/topic-checklist/{user_id}/courses/{course_id}/topics/{topic_id}"): {"checked": True},
    ("PATCH", "/api/graph/{user_id}/courses/{course_id}/color"): {"color": "#123456"},
    ("PATCH", "/api/graph/{user_id}/nodes/{node_id}/color"): {"color": "#123456"},
    ("POST", "/api/graph/{user_id}/nodes"): {"concept_name": "Matrix Probe Concept"},
    ("POST", "/api/graph/{user_id}/concept-description"): {"concept": "Matrix Probe Concept"},
    ("PATCH", "/api/notes/{note_id}"): {"title": "matrix"},
    ("POST", "/api/notes/{note_id}/chat"): {"message": "matrix probe"},
    ("POST", "/api/flashcards/import/generate"): {"source": "library_doc"},
    ("POST", "/api/flashcards/import/parse"): {"source": "anki", "payload": "front\tback"},
    ("POST", "/api/gradebook/courses/{course_id}/categories"): {"name": "Matrix", "weight": 10},
    ("PATCH", "/api/gradebook/courses/{course_id}/categories"):
        {"categories": [{"name": "Matrix", "weight": 100}]},
    ("POST", "/api/gradebook/assignments"): {"title": "Matrix probe"},
    ("POST", "/api/gradebook/syllabus/apply"): {"categories": [], "assignments": []},
    ("POST", "/api/feedback"): {"type": "global", "rating": 3},
    ("POST", "/api/issue-reports"): {"topic": "matrix", "description": "matrix probe"},
    ("POST", "/api/social/rooms/{room_id}/messages"): {"user_name": "Sam Second", "text": "matrix"},
    ("PATCH", "/api/social/rooms/{room_id}/messages/{message_id}"): {"text": "matrix edit"},
    ("POST", "/api/social/rooms/{room_id}/messages/{message_id}/reactions"): {"emoji": "👍"},
    ("POST", "/api/social/rooms/join"): {"invite_code": "MTX-NO-SUCH-CODE"},
    ("DELETE", "/api/profile/{user_id}/account"): {"confirmation": "DELETE"},
    ("POST", "/api/profile/{user_id}/avatar"): {"file_b64": "aGVsbG8="},
    ("POST", "/api/onboarding/profile"): {
        "first_name": "Matrix", "last_name": "Probe", "year": "Senior",
        "learning_style": "visual", "majors": ["Biology"], "course_ids": [COURSE_SHARED],
    },
    ("POST", "/api/calendar/save"): {"assignments": []},
    # Admin bodies: valid enough that B reaches require_admin, never more.
    ("POST", "/api/admin/allowlist/approve"): {"email": "matrix-probe@example.com"},
    ("POST", "/api/admin/allowlist/revoke"): {"email": "matrix-probe@example.com"},
    ("POST", "/api/admin/allowlist/approve-bulk"): {"emails": ["matrix-probe@example.com"]},
    ("POST", "/api/admin/email/suppressions/remove"): {"email": "matrix-probe@example.com"},
    ("POST", "/api/admin/email/broadcasts/test"): {"subject": "matrix", "body": "matrix"},
    ("PUT", "/api/admin/flags/{key}/targets"): {"target_type": "user", "variant": "off"},
}

#: Query values a handler needs beyond the declared-required ones.
QUERY_OVERRIDES: dict[tuple[str, str], dict[str, Any]] = {
    ("GET", "/api/gradebook/summary"): {"semester": "spring-2026"},
    ("GET", "/api/profile/username/check"): {"username": "rich-active"},
}

#: Path values for non-id path params, when the synthesized string is not one
#: the route accepts.
PATH_OVERRIDES: dict[tuple[str, str], dict[str, str]] = {
    ("DELETE", "/api/admin/flags/{key}/targets/{target_type}/{target_id}"): {"target_type": "user"},
}

#: Paths whose wrongful success would destroy data; run last in their group so
#: one leak cannot cascade into every later case.
_DESTRUCTIVE_HINTS = ("/account", "/wipe", "/copy", "/seed", "/leave", "/disconnect")

#: Routes whose CORRECT answer changes B's enrollments. B adding A's catalog
#: course to their own schedule is legitimate (a 200), but from then on B IS
#: enrolled in it, and every later #115 enrollment-gated case (expected 404)
#: would pass the gate. They run after every other create/update in their
#: group, and before the DELETEs (which drop the enrollment again). Path
#: order alone put `/api/graph/...` ahead of `/api/notes` and `/api/learn/...`
#: — the lane's `POST /api/notes 404 -> 200` failure.
SELF_ENROLLING: dict[tuple[str, str], str] = {
    ("POST", "/api/graph/{user_id}/courses"): "graph_service.add_course enrolls the caller",
}


# ── Route enumeration ────────────────────────────────────────────────────────


@dataclass(frozen=True)
class RouteInfo:
    method: str
    path: str
    route: Any  # fastapi.routing.APIRoute

    @property
    def key(self) -> tuple[str, str]:
        return (self.method, self.path)


def _join(prefix: str, path: str) -> str:
    return (prefix.rstrip("/") + path) if prefix else path


def iter_api_routes(routes: Iterable[Any], prefix: str = "") -> list[RouteInfo]:
    """Every APIRoute under ``routes`` with its full path, one per method.

    Handles both shapes FastAPI has used: before 0.138 ``include_router``
    copied each route into ``app.routes`` with the prefix already applied;
    from 0.138 ``app.routes`` holds ``_IncludedRouter`` objects whose routes
    live on ``original_router`` and whose prefix is on ``include_context``.
    Mounts with nested routes are descended too. An object of an unknown shape
    is ignored here and caught by the MIN_EXPECTED_ROUTES floor.
    """
    from fastapi.routing import APIRoute

    out: list[RouteInfo] = []
    for r in routes:
        if isinstance(r, APIRoute):
            full = _join(prefix, r.path)
            for m in sorted(r.methods or ()):
                if m in ("HEAD", "OPTIONS"):
                    continue
                out.append(RouteInfo(m, full, r))
        elif hasattr(r, "original_router") and hasattr(r, "include_context"):
            sub = getattr(r.include_context, "prefix", "") or ""
            out.extend(iter_api_routes(r.original_router.routes, _join(prefix, sub)))
        elif hasattr(r, "routes") and isinstance(getattr(r, "path", None), str):
            out.extend(iter_api_routes(r.routes, _join(prefix, r.path)))
    return out


def app_routes() -> list[RouteInfo]:
    from main import app
    return iter_api_routes(app.routes)


def _flat_dependant(route: Any) -> Any:
    try:
        from fastapi.dependencies.utils import get_flat_dependant
        return get_flat_dependant(route.dependant, skip_repeats=True)
    except (ImportError, TypeError):  # pragma: no cover - older FastAPI
        dep = route.dependant
        stack, flat = [dep], dep
        while stack:
            d = stack.pop()
            for s in d.dependencies:
                flat.path_params.extend(s.path_params)
                flat.query_params.extend(s.query_params)
                flat.body_params.extend(s.body_params)
                stack.append(s)
        return flat


def _dedupe(fields: Iterable[Any]) -> list[Any]:
    seen: dict[str, Any] = {}
    for f in fields:
        seen.setdefault(f.name, f)
    return list(seen.values())


def _is_form(field_: Any) -> bool:
    from fastapi.params import File, Form
    return isinstance(field_.field_info, (Form, File))


def _is_file(field_: Any) -> bool:
    from fastapi.params import File
    return isinstance(field_.field_info, File)


def _body_model(route: Any):
    """(single_model_class_or_None, body_fields, embed)."""
    from pydantic import BaseModel

    body = _dedupe(_flat_dependant(route).body_params)
    if not body:
        return None, [], False
    if any(_is_form(f) for f in body):
        return None, body, True
    if len(body) == 1 and not getattr(body[0].field_info, "embed", False):
        ann = body[0].field_info.annotation
        if isinstance(ann, type) and issubclass(ann, BaseModel):
            return ann, body, False
        return None, body, False
    return None, body, True


@dataclass(frozen=True)
class IdInput:
    location: str  # "path" | "query" | "body" | "override"
    name: str


def id_inputs(info: RouteInfo) -> list[IdInput]:
    """The id-like inputs of a route: path, query and top-level body fields
    matching ``_id$|_ids$``, plus the Refs a BODY_OVERRIDES entry declares."""
    flat = _flat_dependant(info.route)
    out: list[IdInput] = []
    for f in _dedupe(flat.path_params):
        if ID_PARAM.search(f.name):
            out.append(IdInput("path", f.name))
    for f in _dedupe(flat.query_params):
        if ID_PARAM.search(f.name):
            out.append(IdInput("query", f.name))
    model, body, embed = _body_model(info.route)
    if model is not None:
        names = list(model.model_fields)
    else:
        names = [f.name for f in body]
    for n in names:
        if ID_PARAM.search(n):
            out.append(IdInput("body", n))
    for v in BODY_OVERRIDES.get(info.key, {}).values():
        if isinstance(v, Ref) and v is not SELF and v.name not in {i.name for i in out}:
            out.append(IdInput("override", v.name))
    return out


def route_group(info: RouteInfo) -> str:
    if info.path.startswith(ADMIN_PREFIX) or info.key in ADMIN_EXTRA:
        return "admin"
    if info.path.startswith(SERVER_PREFIX):
        return "server"
    return "user"


def has_untyped_body(info: RouteInfo) -> bool:
    """A ``body: dict`` (or Any) handler: its fields are invisible to the
    signature, so it needs a BODY_OVERRIDES entry to be probed honestly."""
    model, body, embed = _body_model(info.route)
    if model is not None or embed or not body:
        return False
    ann = body[0].field_info.annotation
    return ann in (dict, typing.Any, object) or typing.get_origin(ann) is dict


def uncovered_id_inputs(routes: Iterable[RouteInfo]) -> list[tuple[str, str, str, str]]:
    """(method, path, location, name) for every id input of a user-facing route
    that is in neither the registry nor an exclusion list."""
    known = set(ID_SOURCES) | SELF_PARAMS | TARGET_USER_PARAMS | set(EXCLUDED_PARAMS)
    missing = []
    for info in routes:
        if route_group(info) != "user":
            continue
        for i in id_inputs(info):
            if i.name not in known:
                missing.append((info.method, info.path, i.location, i.name))
    return missing


# ── Value synthesis ──────────────────────────────────────────────────────────


def _constraints(metadata: Iterable[Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for m in metadata or ():
        for attr in ("min_length", "max_length", "ge", "gt", "le", "lt"):
            v = getattr(m, attr, None)
            if v is not None:
                out[attr] = v
    return out


def synth_value(annotation: Any, metadata: Iterable[Any] = (), name: str = "") -> Any:
    """A minimal value that validates as ``annotation``. Good enough for the
    shapes the app's request models use; anything it cannot satisfy shows up
    in the hermetic validation test and gets a BODY_OVERRIDES entry."""
    from pydantic import BaseModel

    c = _constraints(metadata)
    origin = typing.get_origin(annotation)
    args = typing.get_args(annotation)
    if origin is typing.Annotated:
        return synth_value(args[0], list(metadata) + list(args[1:]), name)
    if origin in (typing.Union, types.UnionType):
        non_none = [a for a in args if a is not type(None)]
        if type(None) in args:
            return None
        return synth_value(non_none[0], metadata, name)
    if origin is typing.Literal:
        return args[0]
    if origin in (list, set, frozenset, tuple) or annotation in (list, set, tuple):
        n = int(c.get("min_length", 0) or 0)
        item = args[0] if args else str
        return [synth_value(item, (), name) for _ in range(n)]
    if origin is dict or annotation is dict:
        return {}
    if annotation in (typing.Any, object):
        return "matrix"
    if isinstance(annotation, type):
        if issubclass(annotation, enum.Enum):
            return next(iter(annotation)).value
        if issubclass(annotation, BaseModel):
            return synth_model(annotation)
        if annotation is bool:
            return False
        if annotation is int or annotation is float:
            lo = c.get("ge", c.get("gt", 0))
            v = lo + (1 if "gt" in c else 0)
            if "ge" not in c and "gt" not in c:
                v = 1
            return annotation(v)
        if annotation is str:
            if "email" in name:
                return "matrix-probe@example.com"
            n = max(int(c.get("min_length", 1) or 1), 1)
            text = "matrix" if n <= 6 else "m" * n
            cap = c.get("max_length")
            return text[: max(cap, 1)] if cap is not None and cap < len(text) else text
        if annotation is bytes:
            return b"matrix"
    return "matrix"


def synth_model(model: Any) -> dict[str, Any]:
    out = {}
    for fname, finfo in model.model_fields.items():
        if finfo.is_required():
            out[finfo.alias or fname] = synth_value(finfo.annotation, finfo.metadata, fname)
    return out


# ── Cases ────────────────────────────────────────────────────────────────────


@dataclass
class Case:
    group: str
    method: str
    path: str
    url: str
    query: dict[str, Any] = field(default_factory=dict)
    json: Any = None
    has_json: bool = False
    form: dict[str, Any] | None = None
    files: dict[str, Any] | None = None
    probed: tuple[str, ...] = ()
    expect: tuple[int, ...] = (404,)
    note: str = ""
    must_contain: tuple[str, ...] = ()
    known_leak: str = ""

    @property
    def key(self) -> tuple[str, str]:
        return (self.method, self.path)

    def request_text(self) -> str:
        import json as _json
        return " ".join([
            self.url, _json.dumps(self.query, default=str),
            _json.dumps(self.json, default=str, ensure_ascii=False),
            _json.dumps(self.form or {}, default=str),
        ])


def _order(case: Case) -> tuple[float, str, str]:
    rank: float = {"GET": 0, "POST": 1, "PUT": 1, "PATCH": 1, "DELETE": 2}.get(case.method, 1)
    if case.key in SELF_ENROLLING:
        rank = 1.5
    if any(h in case.path for h in _DESTRUCTIVE_HINTS):
        rank = 3
    return (rank, case.path, case.method)


def _resolve(name: str, *, group: str, a_values: Mapping[str, Any], route_has_owned: bool,
             self_id: str, target_id: str) -> Any:
    if name in SELF_PARAMS or name == "<self>":
        return self_id
    if name in TARGET_USER_PARAMS:
        return target_id
    src = ID_SOURCES.get(name)
    if src is not None:
        if group == "admin":
            return [MISSING_ID] if src.many else MISSING_ID
        if src.kind == SHARED_KEY and (route_has_owned or group == "swap"):
            return NEUTRAL_VALUES[name]
        v = a_values[name]
        return [v] if src.many and not isinstance(v, list) else v
    if group == "admin" and name.endswith("_ids"):
        return [MISSING_ID]
    if group == "admin":
        return MISSING_ID
    return None  # excluded params keep their synthesized value


def build_case(info: RouteInfo, *, group: str, a_values: Mapping[str, Any],
               self_id: str, target_id: str) -> Case:
    """One request for ``info`` in ``group``. Every id param is filled the same
    way wherever it appears (path, query, body or an override Ref)."""
    ids = id_inputs(info)
    owned = any(ID_SOURCES.get(i.name, IdSource("", "")).kind == OWNED for i in ids)
    resolve = lambda n: _resolve(  # noqa: E731
        n, group=group, a_values=a_values, route_has_owned=owned,
        self_id=self_id, target_id=target_id,
    )

    def value_for(name: str, synthesized: Any) -> Any:
        if ID_PARAM.search(name) or name in SELF_PARAMS:
            v = resolve(name)
            return synthesized if v is None else v
        return synthesized

    flat = _flat_dependant(info.route)
    url = info.path
    path_over = PATH_OVERRIDES.get(info.key, {})
    for f in _dedupe(flat.path_params):
        v = path_over.get(f.name)
        if v is None:
            v = value_for(f.name, synth_value(f.field_info.annotation, f.field_info.metadata, f.name))
        url = url.replace("{" + f.name + "}", str(v))

    query: dict[str, Any] = {}
    for f in _dedupe(flat.query_params):
        is_id = ID_PARAM.search(f.name) or f.name in SELF_PARAMS
        if not (f.field_info.is_required() or is_id):
            continue
        v = value_for(f.name, synth_value(f.field_info.annotation, f.field_info.metadata, f.name))
        if v is not None:
            query[f.alias or f.name] = v
    query.update(QUERY_OVERRIDES.get(info.key, {}))

    case = Case(group=group, method=info.method, path=info.path, url=url, query=query)
    model, body, embed = _body_model(info.route)
    override = BODY_OVERRIDES.get(info.key, {})

    def fill(d: dict[str, Any]) -> dict[str, Any]:
        for k, v in override.items():
            d[k] = resolve(v.name) if isinstance(v, Ref) else v
        return d

    if body and any(_is_form(f) for f in body):
        form, files = {}, {}
        for f in body:
            if _is_file(f):
                files[f.alias or f.name] = ("matrix.pdf", b"%PDF-1.4\n%matrix\n", "application/pdf")
            else:
                form[f.alias or f.name] = value_for(
                    f.name, synth_value(f.field_info.annotation, f.field_info.metadata, f.name))
        case.form, case.files = fill(form), files
    elif model is not None:
        data = synth_model(model)
        for fname, finfo in model.model_fields.items():
            key = finfo.alias or fname
            if ID_PARAM.search(fname) or fname in SELF_PARAMS:
                v = resolve(fname)
                if v is not None:
                    data[key] = v
        case.json, case.has_json = fill(data), True
    elif body and embed:
        data = {}
        for f in body:
            data[f.alias or f.name] = value_for(
                f.name, synth_value(f.field_info.annotation, f.field_info.metadata, f.name))
        case.json, case.has_json = fill(data), True
    elif body:
        case.json, case.has_json = fill({}), True

    case.probed = tuple(
        i.name for i in ids
        if (group == "resource" and (
            (ID_SOURCES.get(i.name) and (ID_SOURCES[i.name].kind == OWNED or not owned))
            or i.name in TARGET_USER_PARAMS))
        or (group == "swap" and i.name in SELF_PARAMS)
    )
    return case


def build_cases(routes: Iterable[RouteInfo], a_values: Mapping[str, Any],
                *, a_user: str = USER_A, b_user: str = USER_B) -> list[Case]:
    """Every resource, swap, admin and server case, each group ordered so
    destructive requests run last."""
    routes = list(routes)
    resource, swap, admin, server = [], [], [], []
    for info in routes:
        grp = route_group(info)
        if grp == "admin":
            c = build_case(info, group="admin", a_values=a_values, self_id=a_user, target_id=a_user)
            c.expect, c.note = (403,), "admin route as a non-admin"
            admin.append(c)
            continue
        if grp == "server":
            c = build_case(info, group="server", a_values=a_values, self_id=a_user, target_id=a_user)
            c.expect, c.note = (401, 404), "bearer-token route; a session cookie is not a credential"
            server.append(c)
            continue
        names = {i.name for i in id_inputs(info)}
        probes = {n for n in names if n in ID_SOURCES or n in TARGET_USER_PARAMS}
        if probes and info.key not in RESOURCE_SKIP:
            c = build_case(info, group="resource", a_values=a_values, self_id=b_user, target_id=a_user)
            owned = any(ID_SOURCES.get(n) and ID_SOURCES[n].kind == OWNED for n in names)
            if info.key in RESOURCE_EXPECT:
                c.expect, c.note = RESOURCE_EXPECT[info.key]
            elif info.key in KNOWN_403:
                c.expect, c.note = (403, 404), "KNOWN_403: " + KNOWN_403[info.key]
            elif owned:
                c.expect = (404,)
            else:
                # A catalog key or a target user only: B may act for themselves.
                c.expect = (200, 201, 204, 400, 403, 404, 409)
                c.note = "shared key / target user: no A data, no A row changed"
            c.known_leak = KNOWN_LEAKS.get(("resource", info.method, info.path), "")
            resource.append(c)
        if names & SELF_PARAMS and info.key not in SWAP_SKIP:
            c = build_case(info, group="swap", a_values=a_values, self_id=a_user, target_id=b_user)
            c.expect, c.note = SWAP_EXPECT.get(info.key, ((403,), "require_self"))
            swap.append(c)
    for group in (resource, swap, admin, server):
        group.sort(key=_order)
    return resource + swap + admin + server


def allowlist_cases(a_user: str = USER_A, b_user: str = USER_B) -> list[Case]:
    """The intentional cross-user reads: 200, and nothing private in the body.
    ``must_contain`` pins that the read really returned the cross-user data
    (so a 200 with an empty body cannot pass)."""
    return [
        Case("allowlist", "GET", "/api/profile/{user_id}", f"/api/profile/{a_user}",
             expect=(200,), note="public profile projection", must_contain=(a_user,)),
        Case("allowlist", "GET", "/api/profile/{user_id}/roles", f"/api/profile/{a_user}/roles",
             expect=(200,), note="roles for a signed-in viewer (anonymous: 401, #115)"),
        Case("allowlist", "GET", "/api/profile/username/check", "/api/profile/username/check",
             query={"username": "rich-active", "user_id": b_user}, expect=(200,),
             note="username availability"),
        Case("allowlist", "GET", "/api/social/public-rooms", "/api/social/public-rooms",
             query={"user_id": b_user}, expect=(200,),
             note="public room list: A's public room, never the private one or any invite code",
             must_contain=(PUBLIC_ROOM,)),
        Case("allowlist", "GET", "/api/social/students", "/api/social/students",
             expect=(200,), note="same-school directory, no mastery, no email"),
        Case("allowlist", "GET", "/api/gamification/leaderboard", "/api/gamification/leaderboard",
             query={"user_id": b_user}, expect=(200,), note="leaderboard projection"),
        Case("allowlist", "POST", "/api/social/public-rooms/{room_id}/join",
             f"/api/social/public-rooms/{PUBLIC_ROOM}/join", json={"user_id": b_user},
             has_json=True, expect=(200,), note="joining A's public room is the point of it"),
    ]


#: Extra markers the allowlist must never show, on top of A_PRIVATE_MARKERS.
ALLOWLIST_FORBIDDEN = (PUBLIC_ROOM_INVITE, PRIVATE_ROOM)


def validate_case(info: RouteInfo, case: Case) -> list[str]:
    """Problems that would make FastAPI answer 422 before the handler: missing
    required inputs or values that fail the declared types/constraints."""
    from pydantic import TypeAdapter, ValidationError

    problems: list[str] = []
    flat = _flat_dependant(info.route)
    for f in _dedupe(flat.path_params):
        if "{" + f.name + "}" in case.url:
            problems.append(f"path param {f.name} not substituted")
    for f in _dedupe(flat.query_params):
        key = f.alias or f.name
        if key not in case.query:
            if f.field_info.is_required():
                problems.append(f"missing required query {key}")
            continue
        try:
            TypeAdapter(typing.Annotated[f.field_info.annotation, f.field_info]).validate_python(
                case.query[key])
        except ValidationError as e:
            problems.append(f"query {key}: {e.errors()[0]['msg']}")
    model, body, embed = _body_model(info.route)
    if model is not None:
        try:
            model.model_validate(case.json)
        except ValidationError as e:
            problems.extend(f"body {'.'.join(map(str, err['loc']))}: {err['msg']}" for err in e.errors())
    elif body and case.form is not None:
        for f in body:
            key = f.alias or f.name
            if f.field_info.is_required() and key not in case.form and key not in (case.files or {}):
                problems.append(f"missing form field {key}")
    elif body and embed:
        for f in body:
            key = f.alias or f.name
            if key not in (case.json or {}):
                if f.field_info.is_required():
                    problems.append(f"missing body field {key}")
                continue
            try:
                TypeAdapter(typing.Annotated[f.field_info.annotation, f.field_info]).validate_python(
                    case.json[key])
            except ValidationError as e:
                problems.append(f"body {key}: {e.errors()[0]['msg']}")
    return problems

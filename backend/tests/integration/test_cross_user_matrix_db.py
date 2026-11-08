"""The cross-user test matrix against real local Supabase (#115, rls-step2-plan section 5).

User B (``rich-user-second``) calls every route that takes an id, carrying
user A's (``rich-user-active``) ids. The case list, the id registry and the
per-route expectations live in ``tests/cross_user_matrix.py``; its hermetic
twin ``tests/test_cross_user_matrix_coverage.py`` fails in the normal suite
when a route grows an id the registry does not know.

A case fails when:

* the status is not the expected one (404 for a resource probe, 403 for a
  ``user_id = A`` swap or an admin route; per-route exceptions carry a reason).
  A 422 or a 5xx is always a failure: the handler, and its ownership check,
  never ran;
* the body holds a string only A's rows contain (``A_PRIVATE_MARKERS``) that B
  did not send;
* any of A's rows changed: the fingerprints in ``_A_ROWS`` are taken before and
  after every request, over a direct psycopg connection (the #397 rule: assert
  through Postgres, never through the PostgREST layer under test).

All results are collected and the test fails once, with a table. Confirmed
leaks the matrix reproduces today are listed in ``KNOWN_LEAKS`` (strict: when
one stops leaking, the test fails until the entry is removed).

Function mode is required: some routes reach an agent (the tutor on
start-session, concept_scan on course scan-concepts). Without the seam they
would call a real model, so the suite raises rather than skips.
"""
from __future__ import annotations

import os

import pytest

from tests import cross_user_matrix as m
from tests.integration.conftest import USER_ACTIVE, USER_SECOND, mint_session

pytestmark = pytest.mark.integration

#: A shared room both A and B are members of (seed_local_rich ROOM_GENERAL,
#: owned by B): where the reply_to probe posts.
SHARED_ROOM = "rich-room-general"

assert USER_ACTIVE == m.USER_A and USER_SECOND == m.USER_B


@pytest.fixture(autouse=True)
def _requires_function_mode():
    """RAISE, never skip (same rule as test_quiz_subcutaneous_db.py): a skip
    would report green having run nothing, and running without the seam would
    bill a real model."""
    if os.getenv("SAPLING_MODEL_MODE") != "function" or not os.getenv("SAPLING_FUNCTION_HANDLERS"):
        raise RuntimeError(
            "the cross-user matrix needs SAPLING_MODEL_MODE=function and "
            "SAPLING_FUNCTION_HANDLERS=agents.function_handlers_e2e (integration.yml sets both)"
        )


# ── The extra rows the matrix needs (plan section 5) ────────────────────────


@pytest.fixture
def matrix_world(_reset_between_tests, db_conn, seeded_user):
    """On top of the rich baseline: a private room A owns that B is not in
    (with one message by A), a public room A owns, a pending friend request
    A -> C, and one private chunk of A's. Inserted with the service-role
    `table()`, like the seed; the autouse reset wipes them between tests.
    Returns A's id for every ID_SOURCES param, resolved over psycopg."""
    from db import seed_local_rich as seed
    from db.connection import table
    from services.encryption import encrypt_if_present

    user_c = seeded_user(name="Cleo Third")

    for room_id, invite, name, public in (
        (m.PRIVATE_ROOM, m.PRIVATE_ROOM_INVITE, m.PRIVATE_ROOM_NAME, False),
        (m.PUBLIC_ROOM, m.PUBLIC_ROOM_INVITE, "Matrix Public Room A", True),
    ):
        table("rooms").insert({
            "id": room_id, "name": name, "invite_code": invite,
            "created_by": m.USER_A, "owner_id": m.USER_A, "is_public": public,
        })
        table("room_members").insert({"room_id": room_id, "user_id": m.USER_A})
    table("room_messages").insert({
        "id": m.PRIVATE_ROOM_MESSAGE_ID, "room_id": m.PRIVATE_ROOM, "user_id": m.USER_A,
        "user_name": "Rich Active", "text": encrypt_if_present(m.PRIVATE_ROOM_MESSAGE_TEXT),
    })
    table("friend_requests").insert({"from_user_id": m.USER_A, "to_user_id": user_c})

    codes = {cid: code for cid, code, *_ in seed._COURSES}
    table("course_chunks").insert({
        "id": m.PRIVATE_CHUNK_ID,
        "course_id": codes[m.COURSE_SHARED],
        "doc_id": "rich-doc-cs-syllabus",
        "uploader_id": m.USER_A,
        "chunk_index": 99,
        "chunk_text": encrypt_if_present(m.PRIVATE_CHUNK_TEXT),
        "embedding": [1.0] + [0.0] * 767,
        "category": "syllabus",
        "visibility": "private",
        "semester": "current",
    })

    values = {}
    for name, src in m.ID_SOURCES.items():
        row = db_conn.execute(src.sql, {"a": m.USER_A, "b": m.USER_B}).fetchone()
        assert row, f"ID_SOURCES[{name!r}] found none of A's rows; the seed or the SQL drifted"
        values[name] = next(iter(row.values()))
    assert values["room_id"] == m.PRIVATE_ROOM
    assert values["message_id"] == m.PRIVATE_ROOM_MESSAGE_ID
    return values


# ── A's rows, fingerprinted ──────────────────────────────────────────────────

_OWN = "SELECT to_jsonb(t) AS j FROM {table} t WHERE {col} = %(a)s"
_A_ROWS: dict[str, str] = {
    "users": _OWN.format(table="users", col="id"),
    "user_profiles": _OWN.format(table="user_profiles", col="user_id"),
    "user_settings": _OWN.format(table="user_settings", col="user_id"),
    "notes": _OWN.format(table="notes", col="user_id"),
    "note_concepts": "SELECT to_jsonb(t) AS j FROM note_concepts t "
                     "WHERE note_id IN (SELECT id FROM notes WHERE user_id = %(a)s)",
    "documents": _OWN.format(table="documents", col="user_id"),
    "sessions": _OWN.format(table="sessions", col="user_id"),
    "messages": "SELECT to_jsonb(t) AS j FROM messages t "
                "WHERE session_id IN (SELECT id FROM sessions WHERE user_id = %(a)s)",
    "quiz_attempts": _OWN.format(table="quiz_attempts", col="user_id"),
    "quiz_context": _OWN.format(table="quiz_context", col="user_id"),
    "flashcards": _OWN.format(table="flashcards", col="user_id"),
    "study_guides": _OWN.format(table="study_guides", col="user_id"),
    "graph_nodes": _OWN.format(table="graph_nodes", col="user_id"),
    "graph_edges": _OWN.format(table="graph_edges", col="user_id"),
    "node_mastery_events": "SELECT to_jsonb(t) AS j FROM node_mastery_events t "
                           "WHERE node_id IN (SELECT id FROM graph_nodes WHERE user_id = %(a)s)",
    "enrollments": _OWN.format(table="enrollments", col="user_id"),
    "gradebook_categories": "SELECT to_jsonb(t) AS j FROM gradebook_categories t WHERE "
                            "enrollment_id IN (SELECT id FROM enrollments WHERE user_id = %(a)s)",
    "assignments": "SELECT to_jsonb(t) AS j FROM assignments t WHERE "
                   "enrollment_id IN (SELECT id FROM enrollments WHERE user_id = %(a)s)",
    "feedback": _OWN.format(table="feedback", col="user_id"),
    "friend_requests": _OWN.format(table="friend_requests", col="from_user_id"),
    "friendships": "SELECT to_jsonb(t) AS j FROM friendships t "
                   "WHERE user_id = %(a)s OR friend_id = %(a)s",
    "course_chunks": _OWN.format(table="course_chunks", col="uploader_id"),
    "rooms(private)": "SELECT to_jsonb(t) AS j FROM rooms t WHERE id = %(room)s",
    "room_members(private)": "SELECT to_jsonb(t) AS j FROM room_members t WHERE room_id = %(room)s",
    "room_messages(private)": "SELECT to_jsonb(t) AS j FROM room_messages t WHERE room_id = %(room)s",
    "room_reactions(private)": "SELECT to_jsonb(t) AS j FROM room_reactions t WHERE message_id IN "
                               "(SELECT id FROM room_messages WHERE room_id = %(room)s)",
    "room_bans(private)": "SELECT to_jsonb(t) AS j FROM room_bans t WHERE room_id = %(room)s",
}
_DIGEST_SQL = " UNION ALL ".join(
    f"SELECT '{name}' AS t, md5(coalesce(string_agg(s.j::text, ',' ORDER BY s.j::text), '')) AS h "
    f"FROM ({sql}) s"
    for name, sql in _A_ROWS.items()
)

#: Changes to A's rows an allowlisted read is allowed to cause.
ALLOWLIST_TOLERATED_CHANGES = {
    "user_settings": "GET /api/profile/{id} creates the target's missing settings row (profile.py:290)",
    "user_profiles": "same: ensure-exists on the public profile read",
}


def _fingerprint(db_conn) -> dict[str, str]:
    rows = db_conn.execute(_DIGEST_SQL, {"a": m.USER_A, "room": m.PRIVATE_ROOM}).fetchall()
    return {r["t"]: r["h"] for r in rows}


# ── Running and judging ─────────────────────────────────────────────────────


def _client_as(user_id: str):
    from fastapi.testclient import TestClient

    from main import app
    # raise_server_exceptions=False: a 500 must become a recorded result, not
    # abort the run and hide every later case.
    c = TestClient(app, raise_server_exceptions=False)
    c.cookies.set("sapling_session", mint_session(user_id))
    return c


def _send(client, case: m.Case):
    kwargs: dict = {"params": case.query}
    if case.form is not None or case.files:
        kwargs["data"] = case.form or {}
        kwargs["files"] = case.files or {}
    elif case.has_json:
        kwargs["json"] = case.json
    return client.request(case.method, case.url, **kwargs)


def _expected(case: m.Case, mode: str) -> tuple[int, ...]:
    """The statuses `case` may answer under `mode`. Under "enforce" the
    load-then-require_self KNOWN_403 entries (``m.ENFORCE_404``) narrow to
    (404,): RLS hides the row before the handler can see whose it is. The
    social.py membership 403s keep their off-mode answer (code, not RLS; the
    social router runs as service role until step 2e)."""
    if mode == "enforce" and case.group == "resource" and case.key in m.ENFORCE_404:
        return (404,)
    return case.expect


@pytest.fixture(autouse=True)
def _db_user_scope_mode(request, monkeypatch):
    """Apply the parametrized `mode` through the flag's env override, which
    `feature_flags.explain` reads per call (no cache to clear) and
    `db/scope.py` resolves once per REQUEST — so the in-process app sees it
    from the next request on. The signing/anon keys enforce needs come from
    the local stack's defaults (tests/integration/conftest.py)."""
    from db import user_jwt

    mode = getattr(getattr(request.node, "callspec", None), "params", {}).get("mode", "off")
    monkeypatch.setenv("SAPLING_FLAG_DB_USER_SCOPE", mode)
    user_jwt.clear_token_cache()
    if mode == "enforce":
        assert not user_jwt.config_problems(), (
            f"enforce needs the local signing + anon keys: {user_jwt.config_problems()}"
        )
    yield
    user_jwt.clear_token_cache()


def _run(client, db_conn, cases: list[m.Case], mode: str, *,
         tolerated_changes: dict[str, str] | None = None) -> list[dict]:
    from services import request_limits

    results = []
    for case in cases:
        request_limits._rate_state.clear()  # a burst of probes is not abuse
        before = _fingerprint(db_conn)
        try:
            resp = _send(client, case)
            status, text = resp.status_code, resp.text
        except Exception as exc:  # a transport-level crash is a result too
            status, text = 0, f"{type(exc).__name__}: {exc}"
        after = _fingerprint(db_conn)

        sent = case.request_text()
        markers = [mk for mk in m.A_PRIVATE_MARKERS + (
            m.ALLOWLIST_FORBIDDEN if case.group == "allowlist" else ())
            if mk not in sent and mk in text]
        changed = [t for t in before if before[t] != after.get(t)
                   and t not in (tolerated_changes or {})]
        missing = [mk for mk in case.must_contain if mk not in text]
        expect = _expected(case, mode)

        leak = []
        if markers:
            leak.append("READ:" + ",".join(mk[:24] for mk in markers))
        if changed:
            leak.append("WRITE:" + ",".join(changed))
        unexpected_2xx = 200 <= status < 300 and status not in expect
        if unexpected_2xx and case.group in ("swap", "admin", "server"):
            leak.append("AUTHZ:2xx")
        status_ok = status in expect and not missing

        if case.known_leak:
            # Strict: the entry stays only while the leak reproduces. A fix
            # changes the status too, so judge the leak alone.
            ok = bool(leak)
            verdict = "known-leak" if ok else "KNOWN-LEAK-FIXED"
        else:
            ok = status_ok and not leak
            verdict = "ok" if ok else "FAIL"

        detail = ""
        if status == 422:
            detail = "422: never reached the handler (add a body override)"
        elif status >= 500 or status == 0:
            detail = text[:160].replace("\n", " ")
        elif missing:
            detail = "missing " + ",".join(missing)
        results.append({
            "group": case.group, "method": case.method, "path": case.path,
            "param": ",".join(case.probed) or "-", "expected": "/".join(map(str, expect)),
            "got": status, "leak": " ".join(leak) or "-", "verdict": verdict,
            "ok": ok, "detail": detail or case.known_leak[:80],
        })
    return results


def _report(results: list[dict], title: str) -> None:
    counts: dict[str, int] = {}
    for r in results:
        counts[r["verdict"]] = counts.get(r["verdict"], 0) + 1
    print(f"\n{title}: {len(results)} cases {counts}")
    bad = [r for r in results if not r["ok"]]
    known = [r for r in results if r["verdict"] == "known-leak"]
    for r in known:
        print(f"  known leak (KNOWN_LEAKS): {r['method']} {r['path']} got {r['got']} {r['leak']}")
    if not bad:
        return
    header = ("method", "path", "param", "expected", "got", "leak?", "detail")
    rows = [(r["method"], r["path"], r["param"], r["expected"], str(r["got"]),
             r["leak"], r["detail"] if r["verdict"] != "KNOWN-LEAK-FIXED" else
             "no longer leaks: remove it from KNOWN_LEAKS") for r in bad]
    widths = [max(len(h), *(len(row[i]) for row in rows)) for i, h in enumerate(header)]
    widths[-1] = len(header[-1])
    line = lambda cols: "  ".join(c.ljust(w) for c, w in zip(cols, widths))  # noqa: E731
    table_txt = "\n".join([line(header), line(["-" * w for w in widths])] + [line(r) for r in rows])
    pytest.fail(f"{title}: {len(bad)} of {len(results)} cases failed\n{table_txt}", pytrace=False)


@pytest.fixture
def b_client():
    return _client_as(m.USER_B)


def _cases(group: str, values) -> list[m.Case]:
    return [c for c in m.build_cases(m.app_routes(), values) if c.group == group]


# ── The groups ───────────────────────────────────────────────────────────────


@pytest.mark.parametrize("mode", m.MODES)
def test_resource_ids_of_a_are_invisible_to_b(mode, matrix_world, db_conn, b_client):
    """B's session and B's own user_id, A's resource id: 404 (or the listed
    exception), no A marker in the body, none of A's rows changed."""
    _report(_run(b_client, db_conn, _cases("resource", matrix_world), mode),
            f"resource group [{mode}]")


@pytest.mark.parametrize("mode", m.MODES)
def test_user_id_swap_is_forbidden(mode, matrix_world, db_conn, b_client):
    """B's session passing user_id = A (A's resource ids alongside): 403."""
    _report(_run(b_client, db_conn, _cases("swap", matrix_world), mode),
            f"swap group [{mode}]")


@pytest.mark.parametrize("mode", m.MODES)
def test_admin_routes_reject_a_student(mode, matrix_world, db_conn, b_client):
    """Every admin route as B: 403, and nothing of A's touched (wipe, copy and
    seed name A and run last)."""
    _report(_run(b_client, db_conn, _cases("admin", matrix_world), mode),
            f"admin group [{mode}]")


@pytest.mark.parametrize("mode", m.MODES)
def test_server_routes_ignore_a_session_cookie(mode, matrix_world, db_conn, b_client):
    _report(_run(b_client, db_conn, _cases("server", matrix_world), mode),
            f"server group [{mode}]")


@pytest.mark.parametrize("mode", m.MODES)
def test_intentional_cross_user_reads_project_only_public_fields(mode, matrix_world, db_conn, b_client):
    """The allowlist: 200, the cross-user data really there (must_contain),
    and no private marker, private room or invite code."""
    _report(_run(b_client, db_conn, m.allowlist_cases(), mode,
                 tolerated_changes=ALLOWLIST_TOLERATED_CHANGES),
            f"allowlist group [{mode}]")


@pytest.mark.parametrize("mode", m.MODES)
def test_reply_to_cannot_pull_a_private_message_into_a_shared_room(mode, matrix_world, db_conn, b_client):
    """A secondary-param probe the one-case-per-route matrix cannot express:
    the room is one B legitimately posts in, only reply_to_id is A's.

    Fixed by #115 on both sides: the post is refused (404, the same answer as
    a reply_to_id that names nothing), and the read only resolves snippets of
    messages in the room being read, so a cross-room row stored before the fix
    (inserted directly below) renders with no snippet."""
    from db.connection import table
    from services.encryption import encrypt_if_present

    # A pre-fix row: B's message in the shared room quoting A's private one,
    # written straight to the table the way the unchecked post used to.
    table("room_messages").insert({
        "room_id": SHARED_ROOM, "user_id": m.USER_B, "user_name": "Sam Second",
        "text": encrypt_if_present("matrix stored cross-room reply"),
        "reply_to_id": matrix_world["reply_to_id"],
    })
    post = m.Case(
        "probe", "POST", "/api/social/rooms/{room_id}/messages",
        f"/api/social/rooms/{SHARED_ROOM}/messages",
        json={"user_id": m.USER_B, "user_name": "Sam Second", "text": "matrix reply",
              "reply_to_id": matrix_world["reply_to_id"]},
        has_json=True, expect=(404,), probed=("reply_to_id",),
        note="post with a foreign reply_to_id",
    )
    read = m.Case(
        "probe", "GET", "/api/social/rooms/{room_id}/messages",
        f"/api/social/rooms/{SHARED_ROOM}/messages", expect=(200,),
        note="the shared room's transcript, holding the stored cross-room reply",
        must_contain=("matrix stored cross-room reply",),
    )
    _report(_run(b_client, db_conn, [post, read], mode), f"reply_to probe [{mode}]")


#: A note B owns in the rich seed (seed_local_rich._NOTES): where the
#: link-concept probe links.
B_NOTE = "rich-note-hist-timeline"


@pytest.mark.parametrize("mode", m.MODES)
def test_link_concept_refuses_a_foreign_graph_node(mode, matrix_world, db_conn, b_client):
    """A secondary-param probe the one-case-per-route matrix cannot express:
    the note is B's own, only concept_node_id is A's.

    Fixed by #115 (notes_service.link_concept checks the node's owner): the
    link is refused with the same 404 as a node id that names nothing, and no
    note_concepts row pointing at A's node lands on B's note. The fingerprint
    only covers A's rows, so the junction write is asserted directly."""
    a_node = matrix_world["concept_node_id"]
    probes = [
        m.Case(
            "probe", "POST", "/api/notes/{note_id}/concepts",
            f"/api/notes/{B_NOTE}/concepts",
            json={"user_id": m.USER_B, "concept_node_id": node},
            has_json=True, expect=(404,), probed=("concept_node_id",), note=note,
        )
        for node, note in ((a_node, "B's note, A's node"),
                           (m.MISSING_ID, "B's note, no such node (same answer)"))
    ]
    _report(_run(b_client, db_conn, probes, mode), f"link-concept probe [{mode}]")
    row = db_conn.execute(
        "SELECT count(*) AS n FROM note_concepts WHERE note_id = %(n)s AND concept_node_id = %(c)s",
        {"n": B_NOTE, "c": a_node},
    ).fetchone()
    assert row["n"] == 0, "a note_concepts row links B's note to A's graph node"


@pytest.mark.parametrize("mode", m.MODES)
def test_note_move_refuses_a_course_the_caller_is_not_enrolled_in(mode, matrix_world, db_conn, b_client):
    """#115: PATCH /api/notes/{id} with a course_id re-homes the note, so it
    passes the same enrollment gate as create. The matrix's own case for this
    route sends A's note id (404 either way) with a neutralised course; this
    probe isolates the gate: B's OWN note, A's A-only course -> 404, and the
    note's offering is unchanged (no current-term offering minted for it)."""
    before = db_conn.execute(
        "SELECT offering_id FROM notes WHERE id = %(n)s", {"n": B_NOTE},
    ).fetchone()
    assert before, "the rich seed's B note is missing"
    probe = m.Case(
        "probe", "PATCH", "/api/notes/{note_id}", f"/api/notes/{B_NOTE}",
        json={"user_id": m.USER_B, "course_id": matrix_world["course_id"]},
        has_json=True, expect=(404,), probed=("course_id",),
        note="B's note moved into A's course",
    )
    _report(_run(b_client, db_conn, [probe], mode), f"note-move probe [{mode}]")
    after = db_conn.execute(
        "SELECT offering_id FROM notes WHERE id = %(n)s", {"n": B_NOTE},
    ).fetchone()
    assert after["offering_id"] == before["offering_id"], "B's note was moved into A's course"


@pytest.mark.parametrize("mode", m.MODES)
def test_roles_need_a_session_and_deleted_profiles_are_gone(mode, db_conn, seeded_user, b_client):
    """#115, outside the B-as-caller groups: who is an admin is not an
    anonymous read (the /roles route, the public profile's roles, and its
    featured-role cosmetic), and a soft-deleted account's public profile and
    roles are a 404.

    Probes the seeded ADMIN (db/seed_local_rich.USER_ADMIN), who really holds
    a role and features it — against a role-less user an empty `roles` would
    prove nothing."""
    from fastapi.testclient import TestClient

    from db.connection import table
    from main import app

    admin = "rich-user-admin"  # db/seed_local_rich.USER_ADMIN
    role = db_conn.execute(
        "SELECT role_id FROM user_roles WHERE user_id = %(u)s LIMIT 1", {"u": admin},
    ).fetchone()
    assert role, "precondition: the rich seed grants rich-user-admin a role"
    table("user_settings").upsert(
        {"user_id": admin, "featured_role_id": role["role_id"]}, on_conflict="user_id",
    )

    signed_in = b_client.get(f"/api/profile/{admin}")
    assert signed_in.status_code == 200, signed_in.text
    assert signed_in.json()["roles"], "precondition: a signed-in viewer sees the admin's role"
    assert "featured_role" in signed_in.json()["equipped_cosmetics"]

    anon = TestClient(app, raise_server_exceptions=False)
    r = anon.get(f"/api/profile/{admin}/roles")
    assert r.status_code == 401, r.text
    r = anon.get(f"/api/profile/{admin}")
    assert r.status_code == 200, r.text
    assert r.json()["roles"] == [], r.text
    assert "featured_role" not in r.json()["equipped_cosmetics"], r.text

    gone = seeded_user(name="Gone Student")
    table("users").update({"deleted_at": "2026-11-08T00:00:00+00:00"},
                          filters={"id": f"eq.{gone}"})
    for path in (f"/api/profile/{gone}", f"/api/profile/{gone}/roles"):
        r = b_client.get(path)
        assert r.status_code == 404, f"[{mode}] {path}: {r.status_code} {r.text[:120]}"

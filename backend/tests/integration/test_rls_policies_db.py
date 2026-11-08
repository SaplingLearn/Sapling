"""Cross-user behaviour of the RLS step-2b policies under the step-2c grants.

Pins 20261108094129_rls_policies.sql + 20261108094130_rls_authenticated_grants.sql
(Trov #115, docs/security/rls-step2-plan.md §1, §5, §6) at the database level,
the way PostgREST will run a user-scoped request once the `db_user_scope` flag
mints tokens: `SET LOCAL ROLE authenticated` plus `request.jwt.claims` set with
`set_config(..., is_local => true)`.

Every test seeds its own `rlsp-*` rows as `postgres` (the table owner, which
bypasses RLS) inside one transaction that is always rolled back, so nothing
here depends on, or leaves behind, seed data. The catalog grant/coverage
checks live in test_rls_lockdown_db.py; this module is the "A cannot see B"
half: a sample of every bucket, the shared-table rules, the two RPCs
authenticated may call, and tokens with the wrong issuer.
"""
import json

import psycopg
import pytest

from tests.integration.test_rls_lockdown_db import AUTHENTICATED_TABLE_GRANTS, EXEMPT

pytestmark = pytest.mark.integration

A, B, C = "rlsp-user-a", "rlsp-user-b", "rlsp-user-c"

# Plan §1.2–§1.6. Every public table must be in exactly one bucket; a table in
# none means a migration added it without deciding who may read it. Mirrors
# docs/security/rls-step2/gen_policies.py::BUCKETS.
BUCKETS: dict[str, frozenset[str]] = {
    "A_owned": frozenset({
        "users", "user_profiles", "user_settings", "oauth_tokens", "gradescope_credentials",
        "enrollments", "documents", "notes", "flashcards", "sessions", "quiz_attempts",
        "quiz_context", "study_guides", "graph_nodes", "graph_edges", "feedback",
        "issue_reports", "user_achievements", "user_cosmetics", "user_roles", "xp_events",
        "friend_requests", "friendships",
    }),
    "B_via_parent": frozenset({
        "messages", "node_mastery_events", "note_concepts", "quiz_responses",
        "gradebook_categories", "assignments", "gradescope_course_links", "topic_checklists",
        "topic_checklist_progress",
    }),
    "C_shared": frozenset({
        "rooms", "room_members", "room_bans", "room_messages", "room_reactions",
        "room_activity", "room_summaries", "offering_concept_stats", "offering_summary",
        "course_chunks", "course_chunk_contributors", "course_chunk_sources",
    }),
    "D_catalog": frozenset({
        "schools", "terms", "courses", "course_offerings", "achievements",
        "achievement_triggers", "achievement_cosmetics", "cosmetics", "roles",
        "role_cosmetics", "growth_stages", "xp_rules",
    }),
    "E_service_only": frozenset({
        "events", "llm_usage", "feature_flags", "feature_flag_targets", "admin_audit_log",
        "email_broadcasts", "email_sends", "email_suppressions", "newsletter_emails",
        "job_applications", "encryption_key_check", "schema_migrations", "jobs",
        "document_uploads",
    }),
}


def _api(sub: str) -> dict:
    """Claims of a token the backend will mint (plan §2.1)."""
    return {"iss": "sapling-api", "sub": sub, "role": "authenticated", "aud": "authenticated"}


# Tokens PostgREST would accept as `authenticated` but that must resolve to no
# user: a Supabase Auth (GoTrue) signup, the local demo issuer, the step-2e
# realtime token, and a token with no issuer. All but the first carry A's id.
FOREIGN_TOKENS = {
    "gotrue_signup": {
        "iss": "http://127.0.0.1:54321/auth/v1", "sub": "00000000-0000-0000-0000-000000000001",
        "role": "authenticated", "aud": "authenticated", "email": "stranger@example.com",
    },
    "supabase_demo_iss_with_a_sub": {"iss": "supabase-demo", "sub": A, "role": "authenticated"},
    "realtime_token_with_a_sub": {"iss": "sapling-realtime", "sub": A, "role": "authenticated"},
    "no_iss_with_a_sub": {"sub": A, "role": "authenticated"},
    "no_claims": None,
}

_SEED = [
    "INSERT INTO schools (id, name, slug) VALUES ('rlsp-school', 'RLS probe', 'rlsp-school')",
    "INSERT INTO courses (id, school_id, course_code, course_name) "
    "VALUES ('rlsp-course', 'rlsp-school', 'RLSP101', 'RLS probe')",
    "INSERT INTO terms (id, term, year, label, start_date, end_date, sort_key) "
    "VALUES ('rlsp-term', 'Fall', 2099, 'RLS probe Fall 2099', '2099-09-01', '2099-12-20', 2099999)",
    "INSERT INTO course_offerings (id, course_id, term_id, section) VALUES "
    "('rlsp-off-1', 'rlsp-course', 'rlsp-term', 'rlsp-1'), "
    "('rlsp-off-2', 'rlsp-course', 'rlsp-term', 'rlsp-2')",
    f"INSERT INTO users (id, email) VALUES ('{A}', 'rlsp-a@example.com'), "
    f"('{B}', 'rlsp-b@example.com'), ('{C}', 'rlsp-c@example.com')",
    # A and B are classmates in offering 1; nobody here is in offering 2.
    f"INSERT INTO enrollments (id, user_id, offering_id) VALUES "
    f"('rlsp-enr-a', '{A}', 'rlsp-off-1'), ('rlsp-enr-b', '{B}', 'rlsp-off-1')",
    f"INSERT INTO notes (id, user_id, offering_id, title, body) VALUES "
    f"('rlsp-note-a', '{A}', 'rlsp-off-1', 't', 'b'), ('rlsp-note-b', '{B}', 'rlsp-off-1', 't', 'b')",
    "INSERT INTO gradebook_categories (id, enrollment_id, name, weight) "
    "VALUES ('rlsp-gb-a', 'rlsp-enr-a', 'HW', 1)",
    f"INSERT INTO sessions (id, user_id, mode, topic) VALUES ('rlsp-sess-a', '{A}', 'socratic', 't')",
    "INSERT INTO messages (id, session_id, role, content) VALUES ('rlsp-msg-a', 'rlsp-sess-a', 'user', 'hi')",
    f"INSERT INTO graph_nodes (id, user_id, course_id, concept_name, mastery_score) "
    f"VALUES ('rlsp-node-a', '{A}', 'rlsp-course', 'limits', 0.5)",
    f"INSERT INTO documents (id, user_id, offering_id, file_name, category) VALUES "
    f"('rlsp-doc-a', '{A}', 'rlsp-off-1', 'a.pdf', 'other'), "
    f"('rlsp-doc-b', '{B}', 'rlsp-off-1', 'b.pdf', 'other')",
    f"INSERT INTO rooms (id, name, invite_code, created_by, owner_id, is_public) VALUES "
    f"('rlsp-room-priv', 'private', 'RLSP-X1', '{A}', '{A}', false), "
    f"('rlsp-room-pub', 'public', 'RLSP-X2', '{A}', '{A}', true)",
    f"INSERT INTO room_members (room_id, user_id) VALUES "
    f"('rlsp-room-priv', '{A}'), ('rlsp-room-pub', '{A}')",
    f"INSERT INTO room_bans (room_id, user_id, banned_by) VALUES ('rlsp-room-pub', '{C}', '{A}')",
    "INSERT INTO room_summaries (room_id, summary, member_hash) VALUES ('rlsp-room-priv', 's', 'h')",
    "INSERT INTO offering_concept_stats (id, offering_id, concept_name) VALUES "
    "('rlsp-ocs-1', 'rlsp-off-1', 'limits'), ('rlsp-ocs-2', 'rlsp-off-2', 'limits')",
    f"INSERT INTO friend_requests (from_user_id, to_user_id) VALUES ('{A}', '{C}')",  # id is a uuid
    "INSERT INTO events (id, event_type, category) VALUES ('rlsp-event', 'rlsp.probe', 'system')",
]


def _seed_chunks(conn) -> None:
    dim = conn.execute(
        "SELECT atttypmod AS d FROM pg_attribute "
        "WHERE attrelid = 'public.course_chunks'::regclass AND attname = 'embedding'"
    ).fetchone()["d"]
    conn.execute(
        f"""INSERT INTO course_chunks (id, course_id, uploader_id, chunk_text, visibility,
                                       category, embedding)
            VALUES ('rlsp-cc-priv', 'rlsp-course', '{A}', 'x', 'private', 'lecture_notes',
                    array_fill(0.1::real, ARRAY[{dim}])::vector),
                   ('rlsp-cc-shared', 'rlsp-course', '{A}', 'y', 'shared', 'lecture_notes',
                    array_fill(0.1::real, ARRAY[{dim}])::vector)"""
    )


@pytest.fixture
def world(db_conn):
    """The rlsp-* rows, inside one transaction that is always rolled back."""
    have = {r["rolname"] for r in db_conn.execute(
        "SELECT rolname FROM pg_roles WHERE rolname IN ('authenticated', 'anon')").fetchall()}
    if "authenticated" not in have:
        pytest.fail("no authenticated role; is this Supabase?")
    with db_conn.transaction() as tx:
        for stmt in _SEED:
            db_conn.execute(stmt)
        _seed_chunks(db_conn)
        yield db_conn
        raise psycopg.Rollback(tx)


def _as(conn, claims) -> None:
    """Become `authenticated` with these JWT claims, as PostgREST does per request."""
    conn.execute("SET LOCAL ROLE authenticated")
    conn.execute(
        "SELECT set_config('request.jwt.claims', %s, true)",
        ("" if claims is None else json.dumps(claims),),
    )


def _as_owner(conn) -> None:
    conn.execute("RESET ROLE")
    conn.execute("SELECT set_config('request.jwt.claims', '', true)")


def _count(conn, table: str, where: str = "true") -> int:
    return conn.execute(f"SELECT count(*) AS n FROM public.{table} WHERE {where}").fetchone()["n"]


def _try(conn, sql: str, params=None) -> tuple[list, str | None]:
    """Run one statement in a savepoint: (rows, None) on success, ([], SQLSTATE) on error."""
    try:
        with conn.transaction():
            cur = conn.execute(sql, params)
            rows = cur.fetchall() if cur.description else []
    except psycopg.Error as e:
        return [], e.sqlstate
    return rows, None


DENIED = "42501"  # insufficient_privilege: missing grant OR an RLS WITH CHECK violation


# ── Inventory ───────────────────────────────────────────────────────────────

def test_every_public_table_is_in_exactly_one_bucket(db_conn):
    live = {r["tablename"] for r in db_conn.execute(
        "SELECT tablename FROM pg_tables WHERE schemaname = 'public'").fetchall()}
    names = [t for ts in BUCKETS.values() for t in ts]
    assert len(names) == len(set(names)), "a table is in two buckets"
    unbucketed = sorted(live - set(names))
    assert not unbucketed, (
        f"tables in no RLS bucket: {unbucketed}. Decide who may read them (plan §1), add "
        "policies + grants in a migration, and list them in BUCKETS and "
        "test_rls_lockdown_db.AUTHENTICATED_TABLE_GRANTS (or bucket E if service-only)."
    )
    assert not sorted(set(names) - live), f"bucketed tables missing: {sorted(set(names) - live)}"
    # The grant map covers exactly buckets A–D (minus room_messages, step 2e).
    granted = set(AUTHENTICATED_TABLE_GRANTS)
    assert granted == set().union(*(BUCKETS[b] for b in BUCKETS if b != "E_service_only")) - EXEMPT


# ── Buckets A and B: own rows only ─────────────────────────────────────────

# table -> predicate selecting one of A's rows (bucket A direct, bucket B via parent)
A_ROWS = {
    "users": f"id = '{A}'",
    "notes": "id = 'rlsp-note-a'",
    "documents": "id = 'rlsp-doc-a'",
    "sessions": "id = 'rlsp-sess-a'",
    "graph_nodes": "id = 'rlsp-node-a'",
    "enrollments": "id = 'rlsp-enr-a'",
    "messages": "id = 'rlsp-msg-a'",
    "gradebook_categories": "id = 'rlsp-gb-a'",
}


@pytest.mark.parametrize("table", sorted(A_ROWS))
def test_owner_sees_own_row_and_classmate_does_not(world, table):
    _as(world, _api(A))
    assert _count(world, table, A_ROWS[table]) == 1, f"A cannot read own {table}"
    _as(world, _api(B))
    assert _count(world, table, A_ROWS[table]) == 0, f"B can read A's {table}"


def test_classmate_sees_own_rows(world):
    _as(world, _api(B))
    assert _count(world, "notes", "id LIKE 'rlsp-%'") == 1
    assert _count(world, "documents", "id LIKE 'rlsp-%'") == 1
    assert _count(world, "enrollments", "id LIKE 'rlsp-%'") == 1
    assert _count(world, "users", "id LIKE 'rlsp-%'") == 1


def test_cross_user_writes_are_refused(world):
    _as(world, _api(B))
    # INSERT on another student's behalf: WITH CHECK fails.
    _, err = _try(world, f"INSERT INTO notes (id, user_id, offering_id) VALUES ('rlsp-x', '{A}', 'rlsp-off-1')")
    assert err == DENIED
    # Gradebook row under A's enrollment (bucket B via owns_enrollment()).
    _, err = _try(world, "INSERT INTO gradebook_categories (id, enrollment_id, name, weight) "
                         "VALUES ('rlsp-gx', 'rlsp-enr-a', 'x', 1)")
    assert err == DENIED
    # A message in A's tutor session (bucket B via sessions).
    _, err = _try(world, "INSERT INTO messages (id, session_id, role, content) "
                         "VALUES ('rlsp-mx', 'rlsp-sess-a', 'user', 'x')")
    assert err == DENIED
    # UPDATE / DELETE of A's rows: USING hides them, so nothing is touched.
    rows, err = _try(world, "UPDATE notes SET title = 'pwned' WHERE id = 'rlsp-note-a' RETURNING id")
    assert (rows, err) == ([], None)
    rows, err = _try(world, "DELETE FROM documents WHERE id = 'rlsp-doc-a' RETURNING id")
    assert (rows, err) == ([], None)
    # Re-owning B's own note to A fails WITH CHECK.
    _, err = _try(world, f"UPDATE notes SET user_id = '{A}' WHERE id = 'rlsp-note-b'")
    assert err == DENIED
    _as_owner(world)
    assert world.execute("SELECT title FROM notes WHERE id = 'rlsp-note-a'").fetchone()["title"] == "t"
    assert _count(world, "documents", "id = 'rlsp-doc-a'") == 1


def test_own_writes_work_and_return_their_row(world):
    # PostgREST writes with `Prefer: return=representation`, so every own
    # write must also pass the SELECT policy (RETURNING).
    _as(world, _api(B))
    rows, err = _try(world, f"INSERT INTO notes (id, user_id, offering_id) "
                            f"VALUES ('rlsp-note-b2', '{B}', 'rlsp-off-1') RETURNING id")
    assert (err, len(rows)) == (None, 1)
    rows, err = _try(world, "INSERT INTO gradebook_categories (id, enrollment_id, name, weight) "
                            "VALUES ('rlsp-gb-b', 'rlsp-enr-b', 'HW', 1) RETURNING id")
    assert (err, len(rows)) == (None, 1)
    rows, err = _try(world, "UPDATE documents SET file_name = 'renamed.pdf' "
                            "WHERE id = 'rlsp-doc-b' RETURNING id")
    assert (err, len(rows)) == (None, 1)


def test_documents_index_columns_are_not_user_writable(world):
    # Column grant (plan §6.3 #5): the index_* lease belongs to document_indexing.
    _as(world, _api(B))
    _, err = _try(world, "UPDATE documents SET index_status = 'indexed' WHERE id = 'rlsp-doc-b'")
    assert err == DENIED
    _, err = _try(world, "UPDATE documents SET user_id = user_id WHERE id = 'rlsp-doc-b'")
    assert err == DENIED


def test_service_only_tables_are_denied_outright(world):
    _as(world, _api(A))
    for table in ("events", "llm_usage", "feature_flags", "schema_migrations"):
        _, err = _try(world, f"SELECT 1 FROM public.{table} LIMIT 1")
        assert err == DENIED, f"authenticated can query service-only {table}"


# ── Bucket C: shared tables ────────────────────────────────────────────────

def test_rooms_public_visible_private_members_only(world):
    _as(world, _api(B))
    visible = {r["id"] for r in world.execute("SELECT id FROM rooms WHERE id LIKE 'rlsp-%'").fetchall()}
    assert visible == {"rlsp-room-pub"}
    assert _count(world, "room_members", "room_id LIKE 'rlsp-%'") == 0
    assert _count(world, "room_summaries", "room_id LIKE 'rlsp-%'") == 0
    _as(world, _api(A))
    assert _count(world, "rooms", "id LIKE 'rlsp-%'") == 2
    assert _count(world, "room_members", "room_id LIKE 'rlsp-%'") == 2
    assert _count(world, "room_summaries", "room_id = 'rlsp-room-priv'") == 1


def test_room_joins(world):
    _as(world, _api(B))
    # Public room: allowed, and the join returns its own row (representation).
    rows, err = _try(world, f"INSERT INTO room_members (room_id, user_id) "
                            f"VALUES ('rlsp-room-pub', '{B}') RETURNING room_id")
    assert (err, len(rows)) == (None, 1)
    assert _count(world, "room_members", "room_id = 'rlsp-room-pub'") == 2  # now a co-member
    # Private room B does not own: refused (invite-code join is service-side).
    _, err = _try(world, f"INSERT INTO room_members (room_id, user_id) VALUES ('rlsp-room-priv', '{B}')")
    assert err == DENIED
    # Adding someone else: refused.
    _, err = _try(world, f"INSERT INTO room_members (room_id, user_id) VALUES ('rlsp-room-pub', '{C}')")
    assert err == DENIED
    # Banned user: refused even for a public room.
    _as(world, _api(C))
    _, err = _try(world, f"INSERT INTO room_members (room_id, user_id) VALUES ('rlsp-room-pub', '{C}')")
    assert err == DENIED
    assert _count(world, "room_bans", "room_id LIKE 'rlsp-%'") == 1  # sees own ban


def test_owner_creates_and_joins_a_private_room_with_returning(world):
    # The two own-row fixes over the plan's draft: the owner sees a private room
    # before being a member, and a joiner sees their own membership row.
    _as(world, _api(B))
    rows, err = _try(world, f"INSERT INTO rooms (id, name, invite_code, created_by, owner_id, is_public) "
                            f"VALUES ('rlsp-room-b', 'mine', 'RLSP-X3', '{B}', '{B}', false) RETURNING id")
    assert (err, len(rows)) == (None, 1)
    rows, err = _try(world, f"INSERT INTO room_members (room_id, user_id) "
                            f"VALUES ('rlsp-room-b', '{B}') RETURNING room_id")
    assert (err, len(rows)) == (None, 1)
    # Creating a room in someone else's name: refused.
    _, err = _try(world, f"INSERT INTO rooms (id, name, invite_code, created_by, owner_id) "
                         f"VALUES ('rlsp-room-x', 'x', 'RLSP-X4', '{A}', '{A}')")
    assert err == DENIED


def test_class_stats_only_for_offerings_you_are_enrolled_in(world):
    _as(world, _api(B))
    seen = {r["id"] for r in world.execute(
        "SELECT id FROM offering_concept_stats WHERE id LIKE 'rlsp-%'").fetchall()}
    assert seen == {"rlsp-ocs-1"}
    _as(world, _api(C))  # enrolled nowhere
    assert _count(world, "offering_concept_stats", "id LIKE 'rlsp-%'") == 0


def test_course_chunks_shared_or_own(world):
    _as(world, _api(B))
    assert {r["id"] for r in world.execute(
        "SELECT id FROM course_chunks WHERE id LIKE 'rlsp-%'").fetchall()} == {"rlsp-cc-shared"}
    _as(world, _api(A))
    assert _count(world, "course_chunks", "id LIKE 'rlsp-%'") == 2


def _match(conn, reader: str | None) -> set[str]:
    # Exact scan: an ANN index can legitimately drop rows from a tiny probe set.
    conn.execute("SET LOCAL enable_indexscan = off")
    conn.execute("SET LOCAL enable_bitmapscan = off")
    dim = conn.execute(
        "SELECT atttypmod AS d FROM pg_attribute "
        "WHERE attrelid = 'public.course_chunks'::regclass AND attname = 'embedding'"
    ).fetchone()["d"]
    rows = conn.execute(
        f"SELECT id FROM match_course_chunks(array_fill(0.1::real, ARRAY[{dim}])::vector, "
        "50, 'rlsp-course', %s)",
        (reader,),
    ).fetchall()
    return {r["id"] for r in rows}


def test_match_course_chunks_cannot_be_widened_by_naming_another_reader(world):
    # filter_user_id is a parameter the caller controls; under a user token RLS
    # still decides. B naming A as the reader gets only the shared chunk.
    _as(world, _api(B))
    assert _match(world, A) == {"rlsp-cc-shared"}
    _as(world, _api(A))
    assert _match(world, A) == {"rlsp-cc-priv", "rlsp-cc-shared"}


def test_apply_mastery_delta_cannot_touch_another_students_node(world):
    _as(world, _api(B))
    rows, err = _try(world, "SELECT * FROM apply_mastery_delta('rlsp-node-a', %s, 0.3, 0.8, 0.5, 0.2)", (A,))
    assert (rows, err) == ([], None)
    _as_owner(world)
    assert world.execute("SELECT mastery_score AS s FROM graph_nodes "
                         "WHERE id = 'rlsp-node-a'").fetchone()["s"] == 0.5
    _as(world, _api(A))
    rows, err = _try(world, "SELECT * FROM apply_mastery_delta('rlsp-node-a', %s, 0.3, 0.8, 0.5, 0.2)", (A,))
    assert err is None and len(rows) == 1 and rows[0]["after_score"] == pytest.approx(0.8)


def test_friend_requests_visible_to_both_parties_only(world):
    a_to_c = f"from_user_id = '{A}' AND to_user_id = '{C}'"
    _as(world, _api(C))
    assert _count(world, "friend_requests", a_to_c) == 1
    _as(world, _api(A))
    assert _count(world, "friend_requests", a_to_c) == 1
    _as(world, _api(B))
    assert _count(world, "friend_requests", a_to_c) == 0
    # Sending a request as someone else: refused.
    _, err = _try(world, f"INSERT INTO friend_requests (from_user_id, to_user_id) "
                         f"VALUES ('{A}', '{B}')")
    assert err == DENIED


# ── Bucket D: catalog needs a backend token ────────────────────────────────

def test_catalog_readable_with_a_backend_token(world):
    _as(world, _api(C))
    assert _count(world, "courses", "id = 'rlsp-course'") == 1
    assert _count(world, "course_offerings", "id LIKE 'rlsp-%'") == 2


# ── Tokens the backend did not mint ────────────────────────────────────────

@pytest.mark.parametrize("token", sorted(FOREIGN_TOKENS))
def test_foreign_tokens_read_nothing_anywhere(world, token):
    # A Supabase Auth signup gets a real `authenticated` JWT on staging/prod
    # (signups are on). app_auth.uid() is NULL for it, so every granted table,
    # the catalog included, must read as empty: the whole table, not just
    # the rlsp rows.
    _as(world, FOREIGN_TOKENS[token])
    leaks = {}
    for table in sorted(AUTHENTICATED_TABLE_GRANTS):
        n = _count(world, table)
        if n:
            leaks[table] = n
    assert not leaks, f"{token} reads rows from: {leaks}"
    assert _match(world, A) == set()
    _, err = _try(world, f"INSERT INTO notes (id, user_id, offering_id) VALUES ('rlsp-y', '{A}', 'rlsp-off-1')")
    assert err == DENIED
    rows, err = _try(world, "SELECT * FROM apply_mastery_delta('rlsp-node-a', %s, 0.3, 0.8, 0.5, 0.2)", (A,))
    assert (rows, err) == ([], None)


# ── Step 2e: room_messages under RLS, read through the Realtime bridge ──────
#
# 20261108210944_rls_room_messages_realtime.sql adds the member SELECT policy
# but leaves RLS OFF on room_messages (the anon Realtime lane still needs it).
# These tests apply the documented MANUAL enable step inside the rolled-back
# transaction (GRANT SELECT to authenticated, ENABLE RLS, REVOKE anon SELECT),
# so they pin what the policy does once it is live, the way Realtime's
# realtime.apply_rls evaluates it: SET LOCAL ROLE to the subscriber's role
# claim, then request.jwt.claims = the subscriber's JWT claims.

def _rt(sub: str) -> dict:
    """Claims of the browser Realtime token (db/user_jwt.py::mint_realtime)."""
    return {"iss": "sapling-realtime", "sub": sub, "role": "authenticated", "aud": "authenticated"}


@pytest.fixture
def chat_world(world):
    """world + messages in both rlsp rooms (A in both, B in the public one,
    C in neither) + the manual 2e enable step. All rolled back with world."""
    world.execute(f"INSERT INTO room_members (room_id, user_id) VALUES ('rlsp-room-pub', '{B}')")
    world.execute(
        f"INSERT INTO room_messages (room_id, user_id, user_name, text) VALUES "
        f"('rlsp-room-priv', '{A}', 'A', 'priv-1'), ('rlsp-room-priv', '{A}', 'A', 'priv-2'), "
        f"('rlsp-room-pub', '{B}', 'B', 'pub-1')"
    )
    world.execute("GRANT SELECT ON public.room_messages TO authenticated")
    world.execute("ALTER TABLE public.room_messages ENABLE ROW LEVEL SECURITY")
    if world.execute("SELECT 1 FROM pg_roles WHERE rolname = 'anon'").fetchone():
        world.execute("REVOKE SELECT ON public.room_messages FROM anon")
    return world


def _rooms_read(conn) -> dict[str, int]:
    rows = conn.execute(
        "SELECT room_id, count(*) AS n FROM public.room_messages "
        "WHERE room_id LIKE 'rlsp-%' GROUP BY room_id"
    ).fetchall()
    return {r["room_id"]: r["n"] for r in rows}


def test_room_messages_realtime_token_reads_only_its_members_rooms(chat_world):
    _as(chat_world, _rt(A))
    assert _rooms_read(chat_world) == {"rlsp-room-priv": 2, "rlsp-room-pub": 1}
    _as(chat_world, _rt(B))
    assert _rooms_read(chat_world) == {"rlsp-room-pub": 1}
    _as(chat_world, _rt(C))
    assert _rooms_read(chat_world) == {}


def test_room_messages_backend_token_reads_its_members_rooms(chat_world):
    # The same policy admits a sapling-api member (a future user-scoped social
    # router); /api/social is service-scoped today.
    _as(chat_world, _api(A))
    assert _rooms_read(chat_world) == {"rlsp-room-priv": 2, "rlsp-room-pub": 1}
    _as(chat_world, _api(C))
    assert _rooms_read(chat_world) == {}


def test_room_messages_leaving_a_room_stops_the_feed(chat_world):
    # Realtime re-runs the policy per change, so a kicked or departed member
    # stops receiving the room the moment the membership row goes.
    chat_world.execute(f"DELETE FROM room_members WHERE room_id = 'rlsp-room-pub' AND user_id = '{B}'")
    _as(chat_world, _rt(B))
    assert _rooms_read(chat_world) == {}


@pytest.mark.parametrize(
    "token", sorted(k for k in FOREIGN_TOKENS if k != "realtime_token_with_a_sub"))
def test_room_messages_foreign_tokens_read_nothing(chat_world, token):
    # A GoTrue signup, the demo issuer and issuer-less tokens carrying A's id.
    _as(chat_world, FOREIGN_TOKENS[token])
    assert _count(chat_world, "room_messages") == 0


def test_room_messages_anon_reads_nothing_once_enabled(chat_world):
    if not chat_world.execute("SELECT 1 FROM pg_roles WHERE rolname = 'anon'").fetchone():
        pytest.skip("no anon role")
    chat_world.execute("SET LOCAL ROLE anon")
    _, err = _try(chat_world, "SELECT 1 FROM public.room_messages LIMIT 1")
    assert err == DENIED


def test_room_messages_realtime_token_cannot_write(chat_world):
    _as(chat_world, _rt(A))
    _, err = _try(chat_world, f"INSERT INTO room_messages (room_id, user_id, user_name, text) "
                              f"VALUES ('rlsp-room-priv', '{A}', 'A', 'x')")
    assert err == DENIED
    _, err = _try(chat_world, "UPDATE room_messages SET text = 'pwned' WHERE room_id = 'rlsp-room-priv'")
    assert err == DENIED
    _, err = _try(chat_world, "DELETE FROM room_messages WHERE room_id = 'rlsp-room-priv'")
    assert err == DENIED


# That the realtime token is no user anywhere ELSE (app_auth.uid() stays
# sapling-api only) is test_foreign_tokens_read_nothing_anywhere's
# `realtime_token_with_a_sub` case above.

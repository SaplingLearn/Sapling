"""GET /api/internal/metrics against a real Postgres + real PostgREST.

The hermetic suite (`tests/test_internal_metrics_routes.py`) stubs the RPC, so
it can prove the route refuses bad numbers but not that the SQL produces good
ones. Everything that is actually a claim about the database lives here:

- the active-user windows are trailing, distinct, and NEST, for users who are
  active only in the wider ones; anonymous (`user_id` NULL) and blank-actor rows
  are not users;
- every `counts` key moves by exactly the rows that landed in each window, and
  every `totals` key by exactly the rows that exist — soft-deleted rows stay in
  the counts and leave the totals;
- a key whose source is not being written is ABSENT, never zero (no `events`
  rows -> no event-sourced keys; no priced LLM call -> no `llm_cost_cents`);
- PostgREST hands the JSONB document back as one JSON object whose every leaf
  is a JSON number — the route rejects a string, so if that ever changed this
  is where it would surface;
- the function is executable by `service_role` and by nobody holding the anon
  key, which the frontend ships.

Rows go in over raw psycopg (the lane's rule: never assert through the layer
under test); the read goes through the app, exactly as Canopy's poll does.

The lane re-seeds the rich baseline before every test, so the row-backed tables
are NOT empty: those assertions are deltas (after minus before). `events` and
`llm_usage` are not seeded, which the tests that rely on it assert first.
"""
import re
import time
import uuid

import pytest

pytestmark = pytest.mark.integration

URL = "/api/internal/metrics"
TOKEN = "itest-canopy-metrics-token-5b1f0c7e9a3d4f68"
WINDOWS = ("24h", "7d", "30d")

# Ids from db/seed_local_rich (literals, for the reason conftest.py gives).
USER = "rich-user-active"
OFFERING = "rich-off-cs101-s26"
ROOM = "rich-room-study-group"

# Every key counted from the `events` table, by the event type behind it.
EVENT_KEYS = {
    "tutor_sessions": "session.started",
    "chat_messages": "chat.message_sent",
    "documents_uploaded": "document.upload",
    "logins": "auth.login",
    "errors_5xx": "error.5xx",
    "errors_4xx": "error.4xx",
    "quiz_generation_failed": "quiz.generation_failed",
    "quiz_context_write_failed": "quiz.context_write_failed",
    "rag_retrieval_failed": "rag.retrieval_failed",
    "rag_chunks_dropped": "rag.chunks_dropped",
    "rag_visibility_resync_failed": "rag.visibility_resync_failed",
}
LLM_KEYS = ("llm_calls", "llm_tokens", "llm_cost_cents")
ROW_KEYS = (
    "signups", "approvals", "quizzes_started", "quizzes_completed",
    "documents_processed", "notes_created", "flashcards_created", "xp_events",
    "achievements_earned", "room_messages", "feedback", "issue_reports",
)
TOTAL_KEYS = (
    "users", "users_pending", "documents", "notes", "flashcards", "rooms",
    "rag_chunks", "rag_document_chunks",
)


@pytest.fixture(autouse=True)
def _enabled(monkeypatch):
    monkeypatch.setenv("CANOPY_METRICS_TOKEN", TOKEN)


@pytest.fixture(scope="module", autouse=True)
def _function_is_in_the_schema_cache(db_conn):
    """PostgREST serves /rpc/<name> from a schema cache; a function created
    after it booted is a 404 until it reloads. The migration NOTIFYs, but the
    reload is asynchronous — ask again and wait for it rather than flake."""
    from db.connection import rpc

    db_conn.execute("NOTIFY pgrst, 'reload schema'")
    deadline = time.monotonic() + 15
    while True:
        try:
            rpc("canopy_metrics", {})
            return
        except Exception:
            if time.monotonic() > deadline:
                raise
            time.sleep(0.5)


def _event(db_conn, user_id, age, event_type="chat.message_sent", category="usage"):
    """One `events` row, `age` (a Postgres interval literal) before now."""
    db_conn.execute(
        """
        INSERT INTO events (event_type, category, user_id, created_at)
        VALUES (%s, %s, %s, now() - %s::interval)
        """,
        (event_type, category, user_id, age),
    )


def _llm(db_conn, age, tokens, cost_usd):
    db_conn.execute(
        """
        INSERT INTO llm_usage (feature, task, model, provider, prompt_tokens,
                               completion_tokens, total_tokens, cost_usd, created_at)
        VALUES ('tutor', 'itest', 'itest-model', 'gemini', %s, 0, %s, %s,
                now() - %s::interval)
        """,
        (tokens, tokens, cost_usd, age),
    )


def _get(client):
    return client.get(URL, headers={"Authorization": f"Bearer {TOKEN}"})


def _doc(client) -> dict:
    r = _get(client)
    assert r.status_code == 200, r.text
    return r.json()


def _moved(before: dict, after: dict, key: str) -> dict:
    return {w: after["counts"][key][w] - before["counts"][key][w] for w in WINDOWS}


def _leaves(doc: dict) -> list:
    return [
        *doc["active_users"].values(),
        *(v for entry in doc["counts"].values() for v in entry.values()),
        *doc["totals"].values(),
    ]


# ── active users (v1, unchanged) ─────────────────────────────────────────────


def test_an_empty_events_table_is_three_real_zeros(client, db_conn):
    assert db_conn.execute("SELECT count(*) AS n FROM events").fetchone()["n"] == 0
    assert _doc(client)["active_users"] == {"24h": 0, "7d": 0, "30d": 0}


def test_windows_are_trailing_distinct_and_nested(client, db_conn):
    _event(db_conn, "it-u-today", "1 hour")
    _event(db_conn, "it-u-today", "2 hours")            # same person twice: once
    _event(db_conn, "it-u-today", "20 days")            # …and again further back
    _event(db_conn, "it-u-edge-day", "23 hours 59 minutes", "error.4xx", "error")
    _event(db_conn, "it-u-week", "3 days", "auth.login", "audit")
    _event(db_conn, "it-u-edge-week", "6 days 23 hours", "auth.login", "audit")
    _event(db_conn, "it-u-month", "29 days", "auth.login", "audit")
    _event(db_conn, "it-u-gone", "31 days", "auth.login", "audit")   # no window
    _event(db_conn, None, "1 hour", "error.4xx", "error")            # anonymous
    _event(db_conn, "", "1 hour", "error.4xx", "error")              # blank actor

    r = _get(client)

    assert r.status_code == 200
    users = r.json()["active_users"]
    assert users == {"24h": 2, "7d": 4, "30d": 5}
    assert users["24h"] <= users["7d"] <= users["30d"]
    assert all(type(v) is int for v in users.values())
    # On the wire: bare JSON integers in contract order, never "2" or 2.0.
    assert '"active_users":{"24h":2,"7d":4,"30d":5}' in r.text.replace(" ", "")


def test_the_30d_count_agrees_with_admin_analytics(client, db_conn):
    """Same source, same "has a user_id" rule — the two dashboards must not
    disagree about how many people used the app this month."""
    from routes.admin_analytics import _resolve_range, _scan_range

    for i in range(7):
        _event(db_conn, f"it-u-{i}", f"{i * 4 + 1} days")
    _event(db_conn, None, "2 days", "error.4xx", "error")

    from_iso, to_iso = _resolve_range(None, None)
    rows, truncated = _scan_range("events", "user_id,created_at", from_iso, to_iso)
    admin_count = len({r["user_id"] for r in rows if r.get("user_id")})

    assert not truncated
    assert _doc(client)["active_users"]["30d"] == admin_count == 7


# ── the document as a whole ──────────────────────────────────────────────────


def test_the_document_is_three_sections_of_json_integers(client, db_conn):
    _event(db_conn, USER, "1 hour")
    _llm(db_conn, "1 hour", 1000, "0.25")

    r = _get(client)

    assert r.status_code == 200
    doc = r.json()
    assert list(doc) == ["active_users", "counts", "totals"]
    assert set(doc["counts"]) == {*EVENT_KEYS, *LLM_KEYS, *ROW_KEYS}
    assert set(doc["totals"]) == set(TOTAL_KEYS)
    assert all(set(entry) == set(WINDOWS) for entry in doc["counts"].values())
    # PostgREST passes the JSONB through: numbers, never "12" or 12.0 — the
    # SUMs and the rounded cents included (BIGINT, not NUMERIC).
    assert all(type(v) is int and v >= 0 for v in _leaves(doc))
    # …and on the wire, not just after parsing: no value is a string ("12")
    # and no number carries a fraction (12.0).
    assert not re.search(r':\s*"', r.text)
    assert not re.search(r"\d\.\d", r.text)
    for key, entry in doc["counts"].items():
        assert entry["24h"] <= entry["7d"] <= entry["30d"], key


def test_a_source_that_is_not_being_written_is_absent_not_zero(client, db_conn):
    """EVENTS_LOGGING_ENABLED=false stops `events` and `llm_usage` growing. A 0
    would read as a measured zero on the dashboard; an absent key reads "not
    reported". The row-backed keys do not depend on that switch and stay."""
    for t in ("events", "llm_usage"):
        assert db_conn.execute(f"SELECT count(*) AS n FROM {t}").fetchone()["n"] == 0

    counts = _doc(client)["counts"]

    assert not set(counts) & {*EVENT_KEYS, *LLM_KEYS}
    assert set(counts) == set(ROW_KEYS)

    # One row older than the window changes nothing: it is not evidence that
    # anything was recorded THIS month.
    _event(db_conn, USER, "45 days")
    _llm(db_conn, "45 days", 10, "0.01")
    assert not set(_doc(client)["counts"]) & {*EVENT_KEYS, *LLM_KEYS}

    # One in-window row of ANY type switches every event key on — the types
    # nothing emitted are then measured zeros.
    _event(db_conn, None, "1 hour", "quiz.tool_empty", "usage")
    counts = _doc(client)["counts"]
    assert set(EVENT_KEYS) <= set(counts)
    assert all(counts[k] == {"24h": 0, "7d": 0, "30d": 0} for k in EVENT_KEYS)
    assert not set(counts) & set(LLM_KEYS)


def test_event_sourced_counts(client, db_conn):
    assert db_conn.execute("SELECT count(*) AS n FROM events").fetchone()["n"] == 0
    for event_type in EVENT_KEYS.values():
        category = "error" if event_type.startswith(("error.", "rag.")) else "usage"
        _event(db_conn, USER, "1 hour", event_type, category)
        _event(db_conn, None, "6 days 23 hours", event_type, category)
        _event(db_conn, None, "6 days 23 hours", event_type, category)
        _event(db_conn, USER, "29 days", event_type, category)
        _event(db_conn, USER, "31 days", event_type, category)        # no window
    # rag.chunks_dropped counts RUNS, not the chunks named in the payload.
    db_conn.execute(
        """
        INSERT INTO events (event_type, category, payload, created_at)
        VALUES ('rag.chunks_dropped', 'error', '{"dropped": 40, "total": 50}', now() - interval '2 hours')
        """
    )
    _event(db_conn, USER, "1 hour", "quiz.started")                   # not a key

    counts = _doc(client)["counts"]

    for key in EVENT_KEYS:
        expected = {"24h": 1, "7d": 3, "30d": 4}
        if key == "rag_chunks_dropped":
            expected = {"24h": 2, "7d": 4, "30d": 5}
        assert counts[key] == expected, key
    assert "quiz_started" not in counts


def test_llm_spend_is_integer_cents_rounded_half_up_and_a_lower_bound(client, db_conn):
    assert db_conn.execute("SELECT count(*) AS n FROM llm_usage").fetchone()["n"] == 0
    _llm(db_conn, "1 hour", 1000, "0.005")      # 0.5 cents -> 1
    _llm(db_conn, "2 hours", 500, None)         # unpriced: tokens, no cents
    _llm(db_conn, "3 days", 2000, "1.005")
    _llm(db_conn, "20 days", 300, "0.12")
    _llm(db_conn, "40 days", 99999, "9")        # no window

    counts = _doc(client)["counts"]

    assert counts["llm_calls"] == {"24h": 2, "7d": 3, "30d": 4}
    assert counts["llm_tokens"] == {"24h": 1500, "7d": 3500, "30d": 3800}
    assert counts["llm_cost_cents"] == {"24h": 1, "7d": 101, "30d": 113}


def test_no_priced_call_means_no_cost_key(client, db_conn):
    """A month of calls to an unpriced model is not "0 cents"."""
    assert db_conn.execute("SELECT count(*) AS n FROM llm_usage").fetchone()["n"] == 0
    _llm(db_conn, "1 hour", 500, None)

    counts = _doc(client)["counts"]

    assert counts["llm_calls"] == {"24h": 1, "7d": 1, "30d": 1}
    assert counts["llm_tokens"] == {"24h": 500, "7d": 500, "30d": 500}
    assert "llm_cost_cents" not in counts


def test_row_backed_counts_and_totals_move_by_exactly_what_landed(client, db_conn):
    before = _doc(client)
    ages = ("1 hour", "6 days", "29 days", "31 days")      # -> +1 / +2 / +3, and one outside

    for i, age in enumerate(ages):
        db_conn.execute(
            "INSERT INTO users (id, google_id, is_approved, created_at)"
            " VALUES (%s, %s, %s, now() - %s::interval)",
            (f"it-signup-{i}", f"it-google-{i}", i % 2 == 0, age),
        )
        db_conn.execute(
            "INSERT INTO admin_audit_log (actor_id, action, target_type, target_id, created_at)"
            " VALUES (%s, 'user.approve', 'user', %s, now() - %s::interval)",
            (USER, f"it-signup-{i}", age),
        )
        db_conn.execute(
            "INSERT INTO quiz_attempts (user_id, created_at, completed_at)"
            " VALUES (%s, now() - %s::interval - interval '1 hour', now() - %s::interval)",
            (USER, age, age),
        )
        db_conn.execute(
            "INSERT INTO documents (user_id, offering_id, file_name, category, created_at, processed_at)"
            " VALUES (%s, %s, 'it.pdf', 'other', now() - %s::interval, now() - %s::interval)",
            (USER, OFFERING, age, age),
        )
        db_conn.execute(
            "INSERT INTO notes (user_id, offering_id, created_at) VALUES (%s, %s, now() - %s::interval)",
            (USER, OFFERING, age),
        )
        db_conn.execute(
            "INSERT INTO flashcards (user_id, topic, front, back, created_at)"
            " VALUES (%s, 'it', 'enc', 'enc', now() - %s::interval)",
            (USER, age),
        )
        db_conn.execute(
            "INSERT INTO xp_events (user_id, rule_key, amount, idempotency_key, created_at)"
            " VALUES (%s, 'itest', 5, %s, now() - %s::interval)",
            (USER, f"it-xp-{uuid.uuid4()}", age),
        )
        db_conn.execute(
            "INSERT INTO room_messages (room_id, user_id, user_name, is_deleted, created_at)"
            " VALUES (%s, %s, 'it', %s, now() - %s::interval)",
            (ROOM, USER, i == 0, age),                      # the newest one is soft-deleted
        )
        db_conn.execute(
            "INSERT INTO feedback (user_id, type, rating, created_at)"
            " VALUES (%s, 'session', 4, now() - %s::interval)",
            (USER, age),
        )
        db_conn.execute(
            "INSERT INTO issue_reports (user_id, topic, description, created_at)"
            " VALUES (%s, 'enc', 'enc', now() - %s::interval)",
            (USER, age),
        )
    # The achievements catalog is migration-seeded; earn four distinct ones.
    achievement_ids = [
        r["id"] for r in db_conn.execute(
            "SELECT id FROM achievements WHERE id NOT IN"
            " (SELECT achievement_id FROM user_achievements WHERE user_id = %s) LIMIT 4",
            (USER,),
        ).fetchall()
    ]
    assert len(achievement_ids) == 4
    for achievement_id, age in zip(achievement_ids, ages):
        db_conn.execute(
            "INSERT INTO user_achievements (user_id, achievement_id, earned_at)"
            " VALUES (%s, %s, now() - %s::interval)",
            (USER, achievement_id, age),
        )
    # Not counted anywhere: an ensure_user_exists stub, an unapprove, an
    # attempt that was started long ago and never finished.
    db_conn.execute("INSERT INTO users (id, streak_count) VALUES ('it-stub', 0)")
    db_conn.execute(
        "INSERT INTO admin_audit_log (actor_id, action, target_type, target_id)"
        " VALUES (%s, 'user.unapprove', 'user', 'it-signup-1')",
        (USER,),
    )
    db_conn.execute(
        "INSERT INTO quiz_attempts (user_id, created_at) VALUES (%s, now() - interval '50 days')",
        (USER,),
    )
    db_conn.execute("INSERT INTO rooms (id, name, invite_code, created_by, owner_id)"
                    " VALUES ('it-room', 'it', 'ITEST1', %s, %s)", (USER, USER))
    for i, category in enumerate(("catalog", "slides", "lecture_notes", None)):
        db_conn.execute(
            "INSERT INTO course_chunks (id, course_id, category) VALUES (%s, 'IT 101', %s)",
            (f"it-chunk-{i}", category),
        )

    after = _doc(client)

    landed = {"24h": 1, "7d": 2, "30d": 3}
    for key in ROW_KEYS:
        assert _moved(before, after, key) == landed, key
    moved_totals = {k: after["totals"][k] - before["totals"][k] for k in TOTAL_KEYS}
    assert moved_totals == {
        "users": 4, "users_pending": 2,          # the stub is nobody
        "documents": 4, "notes": 4, "flashcards": 4, "rooms": 1,
        "rag_chunks": 4, "rag_document_chunks": 3,   # NULL category is not 'catalog'
    }


def test_a_soft_delete_leaves_the_counts_and_lowers_the_totals(client, db_conn):
    """`counts` say what happened; `totals` say what exists."""
    db_conn.execute(
        "INSERT INTO users (id, google_id, is_approved, created_at)"
        " VALUES ('it-leaver', 'it-google-leaver', false, now() - interval '2 hours')"
    )
    db_conn.execute(
        "INSERT INTO documents (id, user_id, offering_id, file_name, category, processed_at)"
        " VALUES ('it-doc', %s, %s, 'it.pdf', 'other', now() - interval '2 hours')",
        (USER, OFFERING),
    )
    db_conn.execute(
        "INSERT INTO notes (id, user_id, offering_id, created_at)"
        " VALUES ('it-note', %s, %s, now() - interval '2 hours')",
        (USER, OFFERING),
    )
    before = _doc(client)

    db_conn.execute("UPDATE users SET deleted_at = now() WHERE id = 'it-leaver'")
    db_conn.execute("UPDATE documents SET deleted_at = now() WHERE id = 'it-doc'")
    db_conn.execute("UPDATE notes SET deleted_at = now() WHERE id = 'it-note'")
    after = _doc(client)

    for key in ("signups", "documents_processed", "notes_created"):
        assert _moved(before, after, key) == {"24h": 0, "7d": 0, "30d": 0}, key
    moved_totals = {k: after["totals"][k] - before["totals"][k] for k in TOTAL_KEYS}
    assert moved_totals == {
        "users": -1, "users_pending": -1, "documents": -1, "notes": -1,
        "flashcards": 0, "rooms": 0, "rag_chunks": 0, "rag_document_chunks": 0,
    }


# ── who may call it ──────────────────────────────────────────────────────────


def test_only_the_backend_role_may_execute_the_function(db_conn):
    """PostgREST exposes every public function at /rest/v1/rpc/<name>, and the
    frontend ships the anon key — without the REVOKE the whole document would be
    readable straight from Supabase, bypassing the route's bearer token."""
    row = db_conn.execute(
        """
        SELECT has_function_privilege('service_role',  'canopy_metrics()', 'EXECUTE') AS service,
               has_function_privilege('anon',          'canopy_metrics()', 'EXECUTE') AS anon,
               has_function_privilege('authenticated', 'canopy_metrics()', 'EXECUTE') AS authed
        """
    ).fetchone()
    assert row == {"service": True, "anon": False, "authed": False}


def test_the_v1_function_is_kept_and_still_locked_down(db_conn):
    """20260921055024 deliberately does NOT drop #654's canopy_active_users():
    the previous image calls it, and nothing orders Railway's deploy against the
    migration run. It must stay what v1 left — backend-only — and agree with the
    document's `active_users`, since both read the same rows the same way."""
    row = db_conn.execute(
        """
        SELECT has_function_privilege('service_role',  'canopy_active_users()', 'EXECUTE') AS service,
               has_function_privilege('anon',          'canopy_active_users()', 'EXECUTE') AS anon,
               has_function_privilege('authenticated', 'canopy_active_users()', 'EXECUTE') AS authed
        """
    ).fetchone()
    assert row == {"service": True, "anon": False, "authed": False}

    _event(db_conn, "it-u-today", "1 hour")
    _event(db_conn, "it-u-week", "3 days")
    _event(db_conn, None, "1 hour", "error.4xx", "error")
    both = db_conn.execute(
        "SELECT (SELECT to_jsonb(v) FROM canopy_active_users() v) AS v1,"
        "       canopy_metrics() -> 'active_users' AS v2"
    ).fetchone()
    assert both["v1"] == {"d1": 1, "d7": 2, "d30": 2}
    assert both["v2"] == {"24h": 1, "7d": 2, "30d": 2}


def test_wrong_token_is_a_401_with_no_numbers(client, db_conn):
    _event(db_conn, "it-u-today", "1 hour")
    r = client.get(URL, headers={"Authorization": "Bearer not-the-token"})
    assert r.status_code == 401
    for section in ("active_users", "counts", "totals"):
        assert section not in r.text

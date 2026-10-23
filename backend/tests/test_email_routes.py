"""Email routes and triggers: the public unsubscribe page, the admin email API
(/api/admin/email/*), bulk allowlist approval, the allowlist `invite_status`
join, and the waitlist-signup / allowlist-approve triggers.

Hermetic: every `table()` is a per-module fake, and `send_email` is replaced
with a recorder wherever a route only has to ENQUEUE (TestClient runs
background tasks after the response, so the recorder sees them).
"""
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

import config
from main import app
from services import email_service
from services.encryption import encrypt

client = TestClient(app)

SECRET = "s" * 40


@pytest.fixture(autouse=True)
def _secret(monkeypatch):
    monkeypatch.setattr(config, "SESSION_SECRET", SECRET)
    monkeypatch.setattr(config, "FRONTEND_URL", "https://sapling.example")


def _factory():
    made: dict = {}

    def factory(name):
        if name not in made:
            m = MagicMock(name=f"table:{name}")
            m.select.return_value = []
            m.select_with_count.return_value = ([], 0)
            m.update.return_value = []
            m.upsert.return_value = []
            m.insert.return_value = []
            made[name] = m
        return made[name]

    return factory, made


def _paged(rows):
    return (rows, len(rows))


@pytest.fixture
def sent(monkeypatch):
    """Record every send_email call instead of running it."""
    rec = MagicMock(name="send_email", return_value="skipped")
    monkeypatch.setattr(email_service, "send_email", rec)
    return rec


def _h(email):
    return email_service.recipient_hash(email)


# ── Public unsubscribe ──────────────────────────────────────────────────────


@pytest.fixture
def unsub_tables(monkeypatch):
    factory, made = _factory()
    monkeypatch.setattr(email_service, "table", factory)
    factory("email_suppressions")
    return made


def test_unsubscribe_get_renders_a_form_and_writes_nothing(unsub_tables):
    token = email_service.unsubscribe_token("a@bu.edu")
    r = client.get(f"/api/email/unsubscribe?t={token}")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/html")
    assert '<form method="post"' in r.text
    assert f'action="/api/email/unsubscribe?t={token}"' in r.text
    assert r.headers["cache-control"] == "no-store"
    unsub_tables["email_suppressions"].upsert.assert_not_called()


def test_unsubscribe_post_suppresses_the_hash(unsub_tables):
    token = email_service.unsubscribe_token("a@bu.edu")
    r = client.post(f"/api/email/unsubscribe?t={token}")
    assert r.status_code == 200
    assert "You&#x27;re unsubscribed</h1>" in r.text
    call = unsub_tables["email_suppressions"].upsert.call_args
    assert call.args[0] == {"recipient_hash": _h("a@bu.edu"), "reason": "unsubscribe"}
    assert call.kwargs == {"on_conflict": "recipient_hash", "ignore_duplicates": True}


def test_rfc8058_one_click_post(unsub_tables):
    token = email_service.unsubscribe_token("a@bu.edu")
    r = client.post(
        f"/api/email/unsubscribe?t={token}",
        content="List-Unsubscribe=One-Click",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert r.status_code == 200
    unsub_tables["email_suppressions"].upsert.assert_called_once()


@pytest.mark.parametrize("method", ["get", "post"])
@pytest.mark.parametrize("query", ["", "?t=", "?t=abc", "?t=" + "0" * 64 + "." + "0" * 64])
def test_invalid_token_is_a_400_html_page(unsub_tables, method, query):
    r = getattr(client, method)(f"/api/email/unsubscribe{query}")
    assert r.status_code == 400
    assert r.headers["content-type"].startswith("text/html")
    unsub_tables["email_suppressions"].upsert.assert_not_called()


def test_unsubscribe_write_failure_is_not_reported_as_success(unsub_tables):
    unsub_tables["email_suppressions"].upsert.side_effect = RuntimeError("down")
    token = email_service.unsubscribe_token("a@bu.edu")
    r = client.post(f"/api/email/unsubscribe?t={token}")
    assert r.status_code == 500
    assert "Something went wrong" in r.text
    assert "unsubscribed</h1>" not in r.text


# ── Triggers ────────────────────────────────────────────────────────────────


def test_waitlist_signup_enqueues_confirmation(sent):
    with patch("routes.newsletter.table"):
        r = client.post("/api/newsletter/subscribe", json={"email": "new@example.com"})
    assert r.status_code == 200
    sent.assert_called_once()
    kw = sent.call_args.kwargs
    assert kw["kind"] == "waitlist_confirmation"
    assert kw["dedupe_key"] == f"waitlist_confirmation:{_h('new@example.com')}"
    assert kw["to"] == "new@example.com"


def test_waitlist_signup_db_failure_sends_nothing(sent):
    with patch("routes.newsletter.table") as t:
        t.return_value.upsert.side_effect = RuntimeError("down")
        r = client.post("/api/newsletter/subscribe", json={"email": "new@example.com"})
    assert r.status_code == 500
    sent.assert_not_called()


def test_send_failure_never_fails_the_signup(monkeypatch):
    # The real send_email, with the claim blowing up underneath it.
    factory, made = _factory()
    factory("email_sends").upsert.side_effect = RuntimeError("down")
    monkeypatch.setattr(email_service, "table", factory)
    with patch("routes.newsletter.table"):
        r = client.post("/api/newsletter/subscribe", json={"email": "new@example.com"})
    assert r.status_code == 200


def test_single_approve_enqueues_youre_in(sent):
    with patch("routes.admin.table") as t, \
         patch("routes.admin.log_admin_action"):
        t.return_value.upsert.return_value = [{"email": "A@B.co"}]
        r = client.post("/api/admin/allowlist/approve", json={"email": "A@B.co"})
    assert r.status_code == 200
    assert r.json() == {"email": {"email": "A@B.co"}}  # response unchanged
    kw = sent.call_args.kwargs
    assert kw["kind"] == "waitlist_approved"
    assert kw["dedupe_key"] == f"waitlist_approved:{_h('a@b.co')}"


def test_single_approve_greets_a_named_entry_and_hides_the_ciphertext(sent):
    from services.encryption import encrypt
    with patch("routes.admin.table") as t, \
         patch("routes.admin.log_admin_action"):
        t.return_value.upsert.return_value = [{"email": "a@bu.edu", "first_name": encrypt("Ada")}]
        r = client.post("/api/admin/allowlist/approve", json={"email": "a@bu.edu"})
    assert r.status_code == 200
    assert r.json() == {"email": {"email": "a@bu.edu"}}  # no first_name, encrypted or not
    kw = sent.call_args.kwargs
    assert kw["subject"] == "Your Sapling spot is ready"
    assert "Your spot is ready, Ada!" in kw["html"] and "Your spot is ready, Ada!" in kw["text"]


def test_bulk_approve_greets_named_entries(monkeypatch, sent):
    from services.encryption import encrypt
    factory, _ = _factory()
    factory("newsletter_emails").select_with_count.return_value = _paged([
        {"id": "w1", "email": "ada@bu.edu", "approved_at": None, "first_name": encrypt("Ada")},
        {"id": "w2", "email": "anon@bu.edu", "approved_at": None, "first_name": None},
    ])
    monkeypatch.setattr("routes.admin.table", factory)
    with patch("routes.admin.log_admin_action"):
        r = client.post("/api/admin/allowlist/approve-bulk", json={"emails": ["ada@bu.edu", "anon@bu.edu"]})
    assert r.status_code == 200, r.text
    by_to = {c.kwargs["to"]: c.kwargs["html"] for c in sent.call_args_list}
    assert "Your spot is ready, Ada!" in by_to["ada@bu.edu"]
    assert "Your spot is ready!" in by_to["anon@bu.edu"]


# ── Bulk approve ────────────────────────────────────────────────────────────


@pytest.mark.parametrize("payload", [
    {"emails": []},
    {"emails": ["not-an-email"]},
    {"emails": ["ok@bu.edu", "bad@nodot"]},
    {"emails": [f"u{i}@bu.edu" for i in range(501)]},
    {},
])
def test_bulk_approve_validation(payload, sent):
    with patch("routes.admin.table") as t:
        r = client.post("/api/admin/allowlist/approve-bulk", json=payload)
    assert r.status_code == 422
    t.assert_not_called()
    sent.assert_not_called()


def test_bulk_approve_only_stamps_null_and_inserts_missing(monkeypatch, sent):
    factory, made = _factory()
    waitlist = [
        {"id": "w1", "email": "Pending@BU.edu", "approved_at": None},
        {"id": "w2", "email": "already@bu.edu", "approved_at": "2026-01-01T00:00:00Z"},
    ]
    factory("newsletter_emails").select_with_count.return_value = _paged(waitlist)
    factory("newsletter_emails").select.return_value = [
        {"id": "w1", "email": "Pending@BU.edu", "created_at": "2026-02-01T00:00:00Z",
         "approved_at": "2026-10-22T00:00:00Z", "joined_at": None, "joined_user_id": None},
    ]
    monkeypatch.setattr("routes.admin.table", factory)
    with patch("routes.admin.log_admin_action") as audit:
        r = client.post("/api/admin/allowlist/approve-bulk", json={
            "emails": [" pending@bu.edu", "ALREADY@bu.edu", "new@bu.edu", "new@bu.edu"],
        })
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["approved"] == 3
    assert body["emails"][0]["id"] == "w1" and "invite_status" in body["emails"][0]

    nl = made["newsletter_emails"]
    # Only the pending row is stamped, and only where approved_at is still NULL.
    (upd,) = nl.update.call_args_list
    assert set(upd.args[0]) == {"approved_at"}
    assert upd.kwargs["filters"] == {"id": "in.(w1)", "approved_at": "is.null"}
    # The unknown address is inserted approved, never overwriting a racing row.
    ins = nl.upsert.call_args
    assert [row["email"] for row in ins.args[0]] == ["new@bu.edu"]
    assert ins.kwargs == {"on_conflict": "email", "ignore_duplicates": True}

    audit.assert_called_once()
    assert audit.call_args.kwargs["action"] == "allowlist.approve_bulk"
    assert audit.call_args.kwargs["payload"] == {
        "count": 3, "emails": ["pending@bu.edu", "already@bu.edu", "new@bu.edu"],
    }

    keys = sorted(c.kwargs["dedupe_key"] for c in sent.call_args_list)
    assert keys == sorted(
        f"waitlist_approved:{_h(e)}" for e in ("pending@bu.edu", "already@bu.edu", "new@bu.edu")
    )
    # Existing rows are mailed at their stored spelling.
    assert {c.kwargs["to"] for c in sent.call_args_list} == {
        "Pending@BU.edu", "already@bu.edu", "new@bu.edu",
    }


# ── Allowlist invite_status ─────────────────────────────────────────────────


def test_allowlist_joins_invite_status(monkeypatch):
    factory, made = _factory()
    rows = [
        {"id": "w1", "email": "Sent@bu.edu", "created_at": "2", "approved_at": "x",
         "joined_at": None, "joined_user_id": None},
        {"id": "w2", "email": "none@bu.edu", "created_at": "1", "approved_at": None,
         "joined_at": None, "joined_user_id": None},
    ]
    factory("newsletter_emails").select_with_count.return_value = _paged(rows)
    factory("email_sends").select.return_value = [
        {"dedupe_key": f"waitlist_approved:{_h('sent@bu.edu')}", "status": "sent"},
    ]
    monkeypatch.setattr("routes.admin.table", factory)
    r = client.get("/api/admin/allowlist")
    assert r.status_code == 200
    by_id = {e["id"]: e["invite_status"] for e in r.json()["emails"]}
    assert by_id == {"w1": "sent", "w2": None}
    flt = made["email_sends"].select.call_args.kwargs["filters"]["dedupe_key"]
    assert flt.startswith("in.(") and f"waitlist_approved:{_h('none@bu.edu')}" in flt


def test_allowlist_status_lookup_is_chunked(monkeypatch):
    factory, made = _factory()
    rows = [{"id": f"w{i}", "email": f"u{i}@bu.edu"} for i in range(120)]
    factory("newsletter_emails").select_with_count.return_value = _paged(rows)
    monkeypatch.setattr("routes.admin.table", factory)
    r = client.get("/api/admin/allowlist")
    assert r.status_code == 200
    assert made["email_sends"].select.call_count == 3  # 50 + 50 + 20


def test_allowlist_survives_a_status_read_error(monkeypatch):
    factory, made = _factory()
    factory("newsletter_emails").select_with_count.return_value = _paged(
        [{"id": "w1", "email": "a@bu.edu"}]
    )
    factory("email_sends").select.side_effect = RuntimeError("no such table")
    monkeypatch.setattr("routes.admin.table", factory)
    r = client.get("/api/admin/allowlist")
    assert r.status_code == 200
    assert r.json()["emails"][0]["invite_status"] is None


# ── /api/admin/email ────────────────────────────────────────────────────────


def test_status_reports_configuration(monkeypatch):
    monkeypatch.setattr(config, "EMAIL_FROM", "Sapling <hello@saplinglearn.com>")
    r = client.get("/api/admin/email/status")
    assert r.json() == {"configured": False, "from_address": "Sapling <hello@saplinglearn.com>"}
    monkeypatch.setattr(config, "RESEND_API_KEY", "re_x")
    assert client.get("/api/admin/email/status").json()["configured"] is True


@pytest.fixture
def audience_tables(monkeypatch):
    factory, made = _factory()
    factory("newsletter_emails").select_with_count.return_value = _paged([
        {"email": "pending@bu.edu", "approved_at": None, "joined_at": None},
        {"email": "PENDING@bu.edu", "approved_at": None, "joined_at": None},  # case twin
        {"email": "approved@bu.edu", "approved_at": "t", "joined_at": None},
        {"email": "joined@bu.edu", "approved_at": "t", "joined_at": "t"},
        {"email": "gone@bu.edu", "approved_at": None, "joined_at": None},  # suppressed
    ])
    factory("users").select_with_count.return_value = _paged([
        {"id": "u1", "email": encrypt("joined@bu.edu")},
        {"id": "u2", "email": encrypt("Other@BU.edu")},
        {"id": "u3", "email": "not-decryptable-ciphertext"},
        {"id": "u4", "email": None},
    ])
    factory("email_suppressions").select_with_count.return_value = _paged([
        {"recipient_hash": _h("gone@bu.edu")},
        {"recipient_hash": _h("other@bu.edu")},
    ])
    monkeypatch.setattr("routes.admin_email.table", factory)
    return made


def test_audiences_dedupe_and_exclude_suppressed(audience_tables):
    r = client.get("/api/admin/email/audiences")
    assert r.status_code == 200
    assert r.json() == {"audiences": [
        {"key": "waitlist_all", "label": "Everyone on the waitlist", "count": 3},
        {"key": "waitlist_pending", "label": "Waitlist, not yet approved", "count": 1},
        {"key": "waitlist_approved_not_joined", "label": "Approved, haven't signed in yet", "count": 1},
        {"key": "users_all", "label": "Everyone in the app", "count": 1},
    ]}
    users_call = audience_tables["users"].select_with_count.call_args
    assert users_call.kwargs["filters"] == {"is_approved": "eq.true", "deleted_at": "is.null"}


def test_test_send_goes_to_the_admin_only(monkeypatch, sent):
    factory, made = _factory()
    factory("users").select.return_value = [{"email": encrypt("admin@bu.edu")}]
    monkeypatch.setattr("routes.admin_email.table", factory)
    with patch("routes.admin_email.log_admin_action"):
        r = client.post("/api/admin/email/broadcasts/test",
                        json={"subject": "Hello", "body": "Hi <b>all</b>"})
    assert r.status_code == 200
    assert r.json() == {"status": "skipped", "to": "admin@bu.edu"}
    kw = sent.call_args.kwargs
    assert kw["to"] == "admin@bu.edu"
    assert kw["kind"] == "broadcast_test"
    assert kw["dedupe_key"].startswith("broadcast_test:")
    assert "&lt;b&gt;all&lt;/b&gt;" in kw["html"]
    assert made["users"].select.call_args.kwargs["filters"] == {"id": "eq.user_andres"}


def test_test_send_without_an_address_is_400(monkeypatch, sent):
    factory, _ = _factory()
    monkeypatch.setattr("routes.admin_email.table", factory)
    r = client.post("/api/admin/email/broadcasts/test", json={"subject": "Hi", "body": "x"})
    assert r.status_code == 400
    sent.assert_not_called()


def test_preview_renders_the_real_email_and_sends_nothing(monkeypatch, sent):
    factory, made = _factory()
    monkeypatch.setattr("routes.admin_email.table", factory)
    r = client.post("/api/admin/email/broadcasts/preview",
                    json={"subject": "Hello", "body": "Hi <b>all</b>"})
    assert r.status_code == 200
    data = r.json()
    assert data["subject"] == "Hello"
    assert "&lt;b&gt;all&lt;/b&gt;" in data["html"] and "<b>all</b>" not in data["html"]
    assert "The Sapling team" in data["html"]
    sent.assert_not_called()
    assert made == {}  # no table touched


def test_preview_accepts_a_blank_draft(monkeypatch, sent):
    monkeypatch.setattr("routes.admin_email.table", _factory()[0])
    r = client.post("/api/admin/email/broadcasts/preview", json={"subject": "", "body": ""})
    assert r.status_code == 200
    assert r.json()["subject"] == "(no subject)"


@pytest.mark.parametrize("payload", [
    {"subject": "", "body": "x", "audience": "users_all"},
    {"subject": "   ", "body": "x", "audience": "users_all"},
    {"subject": "x" * 201, "body": "x", "audience": "users_all"},
    {"subject": "Hi", "body": "", "audience": "users_all"},
    {"subject": "Hi", "body": "x" * 20001, "audience": "users_all"},
    {"subject": "Hi", "body": "x", "audience": "everyone"},
])
def test_broadcast_validation(payload, monkeypatch):
    factory, made = _factory()
    monkeypatch.setattr("routes.admin_email.table", factory)
    r = client.post("/api/admin/email/broadcasts", json=payload)
    assert r.status_code == 422
    assert "email_broadcasts" not in made


def test_create_broadcast_returns_202_and_sends_in_background(audience_tables):
    from routes import admin_email
    row = {
        "id": "b1", "subject": "News", "body": "Hello", "audience": "waitlist_all",
        "status": "sending", "recipient_count": 3, "sent_count": 0, "skipped_count": 0,
        "failed_count": 0, "created_at": "2026-10-22T00:00:00Z", "sent_at": None,
        "created_by": "user_andres",
    }
    admin_email.table("email_broadcasts").insert.return_value = [row]
    with patch("routes.admin_email.run_broadcast") as run, \
         patch("routes.admin_email.log_admin_action") as audit:
        r = client.post("/api/admin/email/broadcasts",
                        json={"subject": "News", "body": "Hello", "audience": "waitlist_all"})
    assert r.status_code == 202
    broadcast = r.json()["broadcast"]
    assert broadcast["id"] == "b1" and "body" not in broadcast
    assert set(broadcast) == {
        "id", "subject", "audience", "status", "recipient_count", "sent_count",
        "skipped_count", "failed_count", "created_at", "sent_at", "created_by",
    }
    inserted = admin_email.table("email_broadcasts").insert.call_args.args[0]
    assert inserted["recipient_count"] == 3 and inserted["created_by"] == "user_andres"
    args = run.call_args.args
    assert args[0] == "b1" and sorted(a.lower() for a in args[3]) == [
        "approved@bu.edu", "joined@bu.edu", "pending@bu.edu",
    ]
    assert audit.call_args.kwargs["action"] == "email.broadcast"


def test_run_broadcast_counts_and_final_status(monkeypatch):
    from routes import admin_email
    factory, made = _factory()
    monkeypatch.setattr("routes.admin_email.table", factory)
    monkeypatch.setattr(admin_email, "PROGRESS_EVERY", 2)
    statuses = iter(["sent", "skipped", "failed", "suppressed", "duplicate"])
    send = MagicMock(side_effect=lambda **kw: next(statuses))
    monkeypatch.setattr(email_service, "send_email", send)
    recipients = [f"u{i}@bu.edu" for i in range(5)]
    admin_email.run_broadcast("b1", "Subj", "Body", recipients)

    keys = [c.kwargs["dedupe_key"] for c in send.call_args_list]
    assert keys == [f"broadcast:b1:{_h(a)}" for a in recipients]
    assert all(c.kwargs["broadcast_id"] == "b1" for c in send.call_args_list)
    updates = [c.args[0] for c in made["email_broadcasts"].update.call_args_list]
    assert updates[0] == {"sent_count": 1, "skipped_count": 1, "failed_count": 0}  # after 2
    final = updates[-1]
    assert final["status"] == "sent" and final["sent_at"]
    assert (final["sent_count"], final["skipped_count"], final["failed_count"]) == (1, 3, 1)


def test_run_broadcast_all_failed_is_failed(monkeypatch):
    from routes import admin_email
    factory, made = _factory()
    monkeypatch.setattr("routes.admin_email.table", factory)
    monkeypatch.setattr(email_service, "send_email", MagicMock(return_value="failed"))
    admin_email.run_broadcast("b1", "S", "B", ["a@bu.edu", "b@bu.edu"])
    final = made["email_broadcasts"].update.call_args.args[0]
    assert final["status"] == "failed" and final["failed_count"] == 2


def test_run_broadcast_survives_a_crashing_send(monkeypatch):
    from routes import admin_email
    factory, made = _factory()
    monkeypatch.setattr("routes.admin_email.table", factory)
    monkeypatch.setattr(email_service, "send_email",
                        MagicMock(side_effect=[RuntimeError("boom"), "sent"]))
    admin_email.run_broadcast("b1", "S", "B", ["a@bu.edu", "b@bu.edu"])
    final = made["email_broadcasts"].update.call_args.args[0]
    assert final["status"] == "sent"
    assert (final["sent_count"], final["failed_count"]) == (1, 1)


def test_list_broadcasts_newest_first(monkeypatch):
    factory, made = _factory()
    factory("email_broadcasts").select.return_value = [{"id": "b2", "body": "secret"}]
    monkeypatch.setattr("routes.admin_email.table", factory)
    r = client.get("/api/admin/email/broadcasts")
    assert r.status_code == 200
    (b,) = r.json()["broadcasts"]
    assert b["id"] == "b2" and "body" not in b
    call = made["email_broadcasts"].select.call_args
    assert call.kwargs["order"] == "created_at.desc" and call.kwargs["limit"] == 50

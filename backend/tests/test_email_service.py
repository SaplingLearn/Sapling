"""services/email_service.py + services/email_templates.py.

The send path is the "never twice, never to a suppressed address, never with
the address in the database" contract: claim the dedupe key first, honour the
suppression list for every kind, and only then (and only with a key) talk to
Resend. Everything is hermetic: `table()` and the Resend httpx client are fakes.
"""
from unittest.mock import MagicMock

import httpx
import pytest

import config
from services import email_service, email_templates

TO = "Student@BU.edu"


@pytest.fixture
def tables(monkeypatch):
    made: dict = {}

    def factory(name):
        if name not in made:
            m = MagicMock(name=f"table:{name}")
            m.select.return_value = []
            m.update.return_value = []
            m.upsert.return_value = []
            m.insert.return_value = []
            made[name] = m
        return made[name]

    factory("email_suppressions")
    factory("email_sends").upsert.return_value = [{"id": "send-1"}]
    monkeypatch.setattr(email_service, "table", factory)
    monkeypatch.setattr(config, "SESSION_SECRET", "s" * 40)
    monkeypatch.setattr(config, "FRONTEND_URL", "https://sapling.example")
    return made


@pytest.fixture
def resend(monkeypatch):
    """Turn the kill switch off and hand back the fake Resend client."""
    client = MagicMock(name="resend")
    client.post.return_value = httpx.Response(200, json={"id": "re_123"})
    monkeypatch.setattr(config, "RESEND_API_KEY", "re_test_key")
    monkeypatch.setattr(config, "EMAIL_FROM", "Sapling <hello@saplinglearn.com>")
    monkeypatch.setattr(config, "EMAIL_REPLY_TO", "")
    monkeypatch.setattr(email_service, "_client", client)
    monkeypatch.setattr(email_service, "MIN_REQUEST_INTERVAL_S", 0.0)
    return client


def _send(**overrides):
    kwargs = dict(
        kind="welcome", to=TO, subject="Hi", html="<p>Hi</p>", text="Hi",
        dedupe_key="welcome:user_1",
    )
    kwargs.update(overrides)
    return email_service.send_email(**kwargs)


def _status_updates(tables):
    return [c.args[0] for c in tables["email_sends"].update.call_args_list]


# ── identity ────────────────────────────────────────────────────────────────


def test_recipient_hash_is_normalized_keyed_hex(monkeypatch):
    monkeypatch.setattr(config, "SESSION_SECRET", "a" * 40)
    h = email_service.recipient_hash("  Student@BU.edu ")
    assert h == email_service.recipient_hash("student@bu.edu")
    assert len(h) == 64 and int(h, 16) >= 0
    assert "student" not in h
    monkeypatch.setattr(config, "SESSION_SECRET", "b" * 40)
    assert email_service.recipient_hash("student@bu.edu") != h  # keyed


def test_unsubscribe_token_round_trip_and_tamper(monkeypatch):
    monkeypatch.setattr(config, "SESSION_SECRET", "a" * 40)
    token = email_service.unsubscribe_token(TO)
    rhash, sig = token.split(".")
    assert email_service.verify_unsubscribe_token(token) == email_service.recipient_hash(TO)
    # A different hash with the old signature, a flipped sig char, junk.
    other = email_service.recipient_hash("someone@else.edu")
    assert email_service.verify_unsubscribe_token(f"{other}.{sig}") is None
    flipped = sig[:-1] + ("0" if sig[-1] != "0" else "1")
    assert email_service.verify_unsubscribe_token(f"{rhash}.{flipped}") is None
    for junk in ("", None, "abc", rhash, f"{rhash}.", f".{sig}", "x" * 129):
        assert email_service.verify_unsubscribe_token(junk) is None
    # Another deployment's secret cannot mint valid tokens here.
    monkeypatch.setattr(config, "SESSION_SECRET", "b" * 40)
    assert email_service.verify_unsubscribe_token(token) is None


def test_unsubscribe_url_is_on_the_frontend_proxy(monkeypatch):
    monkeypatch.setattr(config, "FRONTEND_URL", "https://sapling.example/")
    url = email_service.unsubscribe_url(TO)
    assert url.startswith("https://sapling.example/api/email/unsubscribe?t=")
    assert TO.lower() not in url.lower()


# ── send_email ──────────────────────────────────────────────────────────────


def test_no_api_key_records_skipped_and_never_calls_resend(tables):
    client = email_service._client  # the conftest's blocked client
    assert _send() == "skipped"
    client.post.assert_not_called()
    claim = tables["email_sends"].upsert.call_args
    assert claim.kwargs == {"on_conflict": "dedupe_key", "ignore_duplicates": True}
    assert claim.args[0]["status"] == "queued"
    assert _status_updates(tables) == [{"status": "skipped"}]
    assert tables["email_sends"].update.call_args.kwargs["filters"] == {"id": "eq.send-1"}


def test_claim_row_never_stores_the_address(tables):
    _send()
    row = tables["email_sends"].upsert.call_args.args[0]
    assert row["recipient_hash"] == email_service.recipient_hash(TO)
    assert "student" not in repr(row).lower()


def test_already_claimed_key_is_a_duplicate_and_sends_nothing(tables, resend):
    tables["email_sends"].upsert.return_value = []  # ON CONFLICT DO NOTHING
    tables["email_sends"].update.return_value = []  # not skipped/failed: no re-claim
    assert _send() == "duplicate"
    resend.post.assert_not_called()
    (reclaim,) = tables["email_sends"].update.call_args_list
    assert reclaim.kwargs["filters"] == {
        "dedupe_key": "eq.welcome:user_1", "status": "in.(skipped,failed)",
    }


def test_skipped_or_failed_key_is_reclaimed_and_sent(tables, resend):
    # e.g. approved before RESEND_API_KEY was set: re-approving must still send.
    tables["email_sends"].upsert.return_value = []
    tables["email_sends"].update.side_effect = [[{"id": "send-1"}], []]
    assert _send() == "sent"
    resend.post.assert_called_once()
    assert tables["email_sends"].update.call_args_list[0].args[0] == {
        "status": "queued", "error": None,
    }


def test_suppressed_recipient_with_an_old_claim_is_not_reclaimed(tables, resend):
    tables["email_suppressions"].select.return_value = [
        {"recipient_hash": email_service.recipient_hash(TO)}
    ]
    tables["email_sends"].upsert.return_value = []
    assert _send() == "duplicate"
    resend.post.assert_not_called()
    tables["email_sends"].update.assert_not_called()


def test_each_attempt_gets_its_own_idempotency_key(tables, resend):
    _send()
    _send()
    keys = [c.kwargs["headers"]["Idempotency-Key"] for c in resend.post.call_args_list]
    assert len(set(keys)) == 2
    assert all(k.startswith("welcome:user_1:") for k in keys)


def test_suppressed_recipient_is_recorded_and_not_sent(tables, resend):
    tables["email_suppressions"].select.return_value = [
        {"recipient_hash": email_service.recipient_hash(TO)}
    ]
    assert _send(kind="waitlist_approved", dedupe_key="waitlist_approved:x") == "suppressed"
    resend.post.assert_not_called()
    assert tables["email_sends"].upsert.call_args.args[0]["status"] == "suppressed"
    assert tables["email_suppressions"].select.call_args.kwargs["filters"] == {
        "recipient_hash": f"eq.{email_service.recipient_hash(TO)}"
    }


def test_claim_failure_does_not_send(tables, resend):
    tables["email_sends"].upsert.side_effect = RuntimeError("postgrest down")
    assert _send() == "failed"
    resend.post.assert_not_called()


def test_successful_send_posts_resend_payload_and_marks_sent(tables, resend, monkeypatch):
    monkeypatch.setattr(config, "EMAIL_REPLY_TO", "team@saplinglearn.com")
    assert _send() == "sent"
    call = resend.post.call_args
    assert call.args[0] == "https://api.resend.com/emails"
    assert call.kwargs["headers"]["Authorization"] == "Bearer re_test_key"
    assert call.kwargs["headers"]["Idempotency-Key"].startswith("welcome:user_1:")
    payload = call.kwargs["json"]
    assert payload["to"] == [TO]
    assert payload["from"] == "Sapling <hello@saplinglearn.com>"
    assert payload["reply_to"] == "team@saplinglearn.com"
    assert payload["headers"]["List-Unsubscribe"] == f"<{email_service.unsubscribe_url(TO)}>"
    assert payload["headers"]["List-Unsubscribe-Post"] == "List-Unsubscribe=One-Click"
    (update,) = _status_updates(tables)
    assert update["status"] == "sent"
    assert update["provider_message_id"] == "re_123"
    assert update["sent_at"]


def test_reply_to_omitted_when_unset(tables, resend):
    _send()
    assert "reply_to" not in resend.post.call_args.kwargs["json"]


def test_resend_error_marks_failed_without_the_address(tables, resend):
    resend.post.return_value = httpx.Response(
        422, json={"name": "validation_error",
                   "message": f"Invalid `to` field: {TO} (also student@bu.edu)"},
    )
    assert _send() == "failed"
    (update,) = _status_updates(tables)
    assert update["status"] == "failed"
    assert update["error"].startswith("HTTP 422")
    assert "student" not in update["error"].lower()
    assert "@" not in update["error"]


def test_transport_exception_marks_failed_and_never_raises(tables, resend):
    resend.post.side_effect = httpx.ConnectTimeout("timed out")
    assert _send() == "failed"
    assert _status_updates(tables) == [{"status": "failed", "error": "ConnectTimeout"}]


def test_429_backs_off_and_retries_once(tables, resend, monkeypatch):
    sleeps = []
    monkeypatch.setattr(email_service, "_sleep", sleeps.append)
    resend.post.side_effect = [
        httpx.Response(429, headers={"retry-after": "2"}, json={"message": "slow down"}),
        httpx.Response(200, json={"id": "re_after_retry"}),
    ]
    assert _send() == "sent"
    assert resend.post.call_count == 2
    assert 2.0 in sleeps
    assert _status_updates(tables)[0]["provider_message_id"] == "re_after_retry"


def test_second_429_gives_up_as_failed(tables, resend):
    resend.post.side_effect = [
        httpx.Response(429, json={"message": "slow down"}),
        httpx.Response(429, json={"message": "slow down"}),
    ]
    assert _send() == "failed"
    assert resend.post.call_count == 2
    assert _status_updates(tables)[0]["error"].startswith("HTTP 429")


def test_throttle_spaces_requests(monkeypatch):
    sleeps = []
    monkeypatch.setattr(email_service, "_sleep", sleeps.append)
    monkeypatch.setattr(email_service, "MIN_REQUEST_INTERVAL_S", 0.5)
    monkeypatch.setattr(email_service, "_next_slot", 0.0)
    email_service._throttle()
    email_service._throttle()
    assert len(sleeps) == 1 and 0 < sleeps[0] <= 0.5


def test_broadcast_id_rides_the_claim(tables):
    _send(kind="broadcast", dedupe_key="broadcast:b1:h", broadcast_id="b1")
    assert tables["email_sends"].upsert.call_args.args[0]["broadcast_id"] == "b1"


def test_send_in_background_enqueues_send_email():
    bg = MagicMock()
    email_service.send_in_background(bg, kind="k", to=TO, dedupe_key="k:1")
    bg.add_task.assert_called_once_with(
        email_service.send_email, kind="k", to=TO, dedupe_key="k:1",
    )


# ── templates ───────────────────────────────────────────────────────────────


def test_broadcast_escapes_admin_html_and_links_urls():
    body = (
        "Hello <script>alert('x')</script> & welcome!\n"
        "Read https://saplinglearn.com/blog?a=1&b=2.\n\n"
        'Second "para" with (https://example.com/x_(y)) end'
    )
    subject, html, text = email_templates.broadcast(
        "News <b>today</b>", body, unsubscribe_url="https://sapling.example/u?t=1",
    )
    assert "<script>" not in html
    assert "&lt;script&gt;alert(&#x27;x&#x27;)&lt;/script&gt;" in html
    assert "<b>today</b>" not in html and "News &lt;b&gt;today&lt;/b&gt;" in html
    # URL linked, trailing period left outside, & escaped inside the href.
    assert '<a href="https://saplinglearn.com/blog?a=1&amp;b=2"' in html
    assert ">https://saplinglearn.com/blog?a=1&amp;b=2</a>." in html
    # A balanced paren stays in the URL; the wrapping ones do not.
    assert 'href="https://example.com/x_(y)"' in html
    # Two paragraphs; the single newline is a <br>.
    assert html.count("<p ") >= 2 and "<br>" in html
    assert "&quot;para&quot;" in html
    assert subject == "News <b>today</b>"  # subject is plain text, not HTML
    assert "<script>alert('x')</script>" in text  # text part is the raw body
    assert "https://sapling.example/u?t=1" in html and "https://sapling.example/u?t=1" in text


def test_every_template_carries_the_unsubscribe_link_and_brand():
    unsub = "https://sapling.example/api/email/unsubscribe?t=abc.def"
    rendered = [
        email_templates.waitlist_confirmation(unsubscribe_url=unsub),
        email_templates.waitlist_approved(signin_url="https://sapling.example", unsubscribe_url=unsub),
        email_templates.welcome("Ada", app_url="https://sapling.example/dashboard", unsubscribe_url=unsub),
        email_templates.welcome(None, app_url="https://sapling.example/dashboard", unsubscribe_url=unsub),
        email_templates.broadcast("Hi", "Body", unsubscribe_url=unsub),
    ]
    for subject, html, text in rendered:
        assert subject
        assert unsub in html and unsub in text
        assert "#445D22" in html and "Sapling" in html


def test_welcome_escapes_the_first_name():
    _, html, _ = email_templates.welcome(
        "<img src=x>", app_url="https://a.example", unsubscribe_url="https://u.example",
    )
    assert "<img src=x>" not in html and "&lt;img src=x&gt;" in html


def test_template_images_load_from_the_asset_base(monkeypatch):
    monkeypatch.setattr(config, "FRONTEND_URL", "https://staging.example")
    monkeypatch.setattr(config, "EMAIL_ASSET_BASE_URL", "")
    _, html, _ = email_templates.waitlist_confirmation(unsubscribe_url="https://u.example")
    assert 'src="https://staging.example/email/header.jpg"' in html
    monkeypatch.setattr(config, "EMAIL_ASSET_BASE_URL", "https://saplinglearn.com/")
    _, html, _ = email_templates.broadcast("Hi", "Body", unsubscribe_url="https://u.example")
    assert 'src="https://saplinglearn.com/email/header.jpg"' in html
    assert "staging.example/email/" not in html

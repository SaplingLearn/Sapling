"""services/email_service.py + services/email_templates.py.

The send path is the "never twice, never to a suppressed address, never with
the address in the database" contract: claim the dedupe key first, honour the
suppression list for every kind, and only then (and only with a key) talk to
Resend. Everything is hermetic: `table()` and the Resend httpx client are fakes.
"""
import pathlib
import re
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
            m.select_with_count.return_value = ([], 0)
            m.update.return_value = []
            m.upsert.return_value = []
            m.insert.return_value = []
            m.delete.return_value = []
            made[name] = m
        return made[name]

    factory("email_suppressions")
    factory("email_alert_suppressions")
    factory("email_sends").upsert.return_value = [{"id": "send-1"}]
    monkeypatch.setattr(email_service, "table", factory)
    email_service.clear_opt_out_cache()
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
    tables["email_sends"].update.return_value = []  # sent / live lease: no re-claim
    assert _send() == "duplicate"
    resend.post.assert_not_called()
    (reclaim,) = tables["email_sends"].update.call_args_list
    filters = reclaim.kwargs["filters"]
    assert filters["dedupe_key"] == "eq.welcome:user_1"
    # skipped/failed/suppressed, or a `queued` row whose lease has expired.
    assert filters["or"].startswith("(status.in.(skipped,failed,suppressed),")
    assert "and(status.eq.queued,claimed_at.lt." in filters["or"]
    assert "and(status.eq.queued,claimed_at.is.null)" in filters["or"]
    assert reclaim.args[0]["status"] == "queued" and reclaim.args[0]["claimed_at"]


def test_stale_queued_cutoff_is_the_lease_window_ago(monkeypatch):
    # A crash between claim and status write leaves `queued`; past the lease it
    # must be re-claimable, inside it must not (a live send holds it).
    from datetime import datetime, timezone
    cutoff = datetime.fromisoformat(email_service._stale_queued_cutoff().replace("Z", "+00:00"))
    age = datetime.now(timezone.utc) - cutoff
    assert abs(age - email_service.STALE_QUEUED_AFTER).total_seconds() < 5
    assert email_service.STALE_QUEUED_AFTER.total_seconds() >= 60 * 5


def test_claim_row_carries_a_claim_timestamp(tables):
    _send()
    assert tables["email_sends"].upsert.call_args.args[0]["claimed_at"]


def test_status_write_failure_is_retried_then_logged_never_raised(tables, resend, caplog):
    tables["email_sends"].update.side_effect = RuntimeError("postgrest down")
    with caplog.at_level("ERROR", logger="services.email_service"):
        assert _send() == "sent"  # the caller still learns the truth
    assert tables["email_sends"].update.call_count == 2  # one retry
    assert any("status write failed" in r.message for r in caplog.records if r.levelname == "ERROR")


def test_status_write_retry_recovers(tables, resend):
    tables["email_sends"].update.side_effect = [RuntimeError("blip"), []]
    assert _send() == "sent"
    assert [c.args[0]["status"] for c in tables["email_sends"].update.call_args_list] == ["sent", "sent"]


def test_skipped_or_failed_key_is_reclaimed_and_sent(tables, resend):
    # e.g. approved before RESEND_API_KEY was set: re-approving must still send.
    tables["email_sends"].upsert.return_value = []
    tables["email_sends"].update.side_effect = [[{"id": "send-1"}], []]
    assert _send() == "sent"
    resend.post.assert_called_once()
    reclaim = tables["email_sends"].update.call_args_list[0].args[0]
    assert reclaim["status"] == "queued" and reclaim["error"] is None
    assert reclaim["claimed_at"]  # a fresh lease


def test_suppressed_recipient_with_an_old_claim_reports_and_records_suppressed(tables, resend):
    # The key exists as `failed` and the recipient has since unsubscribed: the
    # answer is "suppressed" (not "duplicate"), and the row says so too.
    tables["email_suppressions"].select.return_value = [
        {"recipient_hash": email_service.recipient_hash(TO)}
    ]
    tables["email_sends"].upsert.return_value = []
    assert _send() == "suppressed"
    resend.post.assert_not_called()
    (flip,) = tables["email_sends"].update.call_args_list
    assert flip.args[0] == {"status": "suppressed", "error": None}
    assert flip.kwargs["filters"]["dedupe_key"] == "eq.welcome:user_1"
    # Only a retryable row flips; a `sent` row stays history.
    assert flip.kwargs["filters"]["or"].startswith("(status.in.(skipped,failed),")


def test_every_attempt_reuses_the_dedupe_key_as_idempotency_key(tables, resend):
    # A re-claimed send whose earlier attempt reached Resend must get Resend's
    # stored answer back, not a second delivery: so the key is per dedupe key.
    _send()
    _send()
    keys = [c.kwargs["headers"]["Idempotency-Key"] for c in resend.post.call_args_list]
    assert keys == ["welcome:user_1", "welcome:user_1"]


def test_reclaimed_send_after_a_timeout_reuses_the_idempotency_key(tables, resend):
    resend.post.side_effect = [httpx.ReadTimeout("t"), httpx.Response(200, json={"id": "re_1"})]
    assert _send() == "failed"
    tables["email_sends"].upsert.return_value = []
    tables["email_sends"].update.return_value = [{"id": "send-1"}]
    assert _send() == "sent"
    keys = {c.kwargs["headers"]["Idempotency-Key"] for c in resend.post.call_args_list}
    assert keys == {"welcome:user_1"}
    # Unknown outcome: the generation is NOT bumped.
    first_fail = tables["email_sends"].update.call_args_list[0].args[0]
    assert first_fail == {"status": "failed", "error": "ReadTimeout"}


@pytest.mark.parametrize("resp", [
    httpx.Response(422, json={"name": "validation_error", "message": "bad"}),
    httpx.Response(500, json={"name": "internal_server_error", "message": "oops"}),
])
def test_definitive_failure_moves_the_next_attempt_to_a_new_key(tables, resend, resp):
    # Review follow-up on #763: reusing the key after Resend ANSWERED would
    # replay the cached failure (or 409) for 24 h, making Resume and the
    # welcome retry no-ops. A definitive failure bumps the generation...
    resend.post.return_value = resp
    assert _send() == "failed"
    (fail,) = _status_updates(tables)
    assert fail["status"] == "failed" and fail["idempotency_gen"] == 1
    # ...and the re-claim (which hands back the bumped row) sends a new key.
    resend.post.return_value = httpx.Response(200, json={"id": "re_2"})
    tables["email_sends"].upsert.return_value = []
    tables["email_sends"].update.side_effect = [[{"id": "send-1", "idempotency_gen": 1}], []]
    assert _send() == "sent"
    keys = [c.kwargs["headers"]["Idempotency-Key"] for c in resend.post.call_args_list]
    assert keys == ["welcome:user_1", "welcome:user_1#1"]


def test_idempotency_key_generations_stay_within_resends_limit():
    assert email_service._idempotency_key("k", 0) == "k"
    assert email_service._idempotency_key("k", 3) == "k#3"
    long = email_service._idempotency_key("x" * 300, 12)
    assert len(long) == 256 and long.endswith("#12")


def test_concurrent_idempotent_request_is_in_flight_not_failed(tables, resend):
    # A stale-queued re-claim racing a live attempt: Resend says the same key
    # is in progress. That attempt owns the row; this one must not mark it.
    resend.post.return_value = httpx.Response(
        409, json={"name": "concurrent_idempotent_requests", "message": "in progress"},
    )
    assert _send() == "duplicate"
    assert _status_updates(tables) == []


def test_changed_payload_409_is_failed_but_keeps_the_key(tables, resend):
    # An earlier request with this key reached Resend (outcome unknown) and the
    # payload has changed since: retrying under a NEW key could double-send.
    resend.post.return_value = httpx.Response(
        409, json={"name": "invalid_idempotent_request", "message": "body modified"},
    )
    assert _send() == "failed"
    (fail,) = _status_updates(tables)
    assert fail["status"] == "failed" and "idempotency_gen" not in fail


# ── notification opt-out ────────────────────────────────────────────────────


def _opted_out(tables, email=TO, user_id="u1"):
    from services.encryption import encrypt
    email_service.table("user_settings").select_with_count.return_value = (
        [{"user_id": user_id}], 1,
    )
    email_service.table("users").select.return_value = [{"id": user_id, "email": encrypt(email)}]


def test_every_kind_is_categorized_in_one_place():
    assert email_service.email_category("broadcast") == "notification"
    for kind in ("welcome", "waitlist_approved", "waitlist_confirmation", "broadcast_test"):
        assert email_service.email_category(kind) == "transactional"
    assert email_service.email_category("ops_alert") == "operational"
    assert email_service.email_category("weekly_digest") == "notification"  # unknown: honour opt-out


def test_notification_kind_to_an_opted_out_account_is_not_sent(tables, resend):
    _opted_out(tables)
    assert _send(kind="broadcast", dedupe_key="broadcast:b1:h", broadcast_id="b1") == "opted_out"
    resend.post.assert_not_called()
    tables["email_sends"].upsert.assert_not_called()  # nothing claimed: a later opt-in can get it
    call = tables["user_settings"].select_with_count.call_args
    assert call.kwargs["filters"] == {"notification_email": "eq.false"}


def test_transactional_kind_ignores_the_opt_out(tables, resend):
    _opted_out(tables)
    assert _send(kind="welcome") == "sent"
    tables["user_settings"].select_with_count.assert_not_called()


def test_opt_out_read_failure_does_not_send_a_notification(tables, resend):
    email_service.table("user_settings").select_with_count.side_effect = RuntimeError("down")
    assert _send(kind="broadcast", dedupe_key="broadcast:b1:h") == "failed"
    resend.post.assert_not_called()
    tables["email_sends"].upsert.assert_not_called()


def test_opt_out_set_is_cached_briefly(tables, resend):
    _opted_out(tables, email="other@bu.edu")
    _send(kind="broadcast", dedupe_key="broadcast:b1:a")
    _send(kind="broadcast", dedupe_key="broadcast:b1:b")
    assert tables["user_settings"].select_with_count.call_count == 1
    email_service.notification_opt_out_hashes(fresh=True)
    assert tables["user_settings"].select_with_count.call_count == 2


# ── un-suppress ─────────────────────────────────────────────────────────────


def test_unsuppress_deletes_the_hash(tables):
    rhash = email_service.recipient_hash(TO)
    tables["email_suppressions"].delete.return_value = [{"recipient_hash": rhash}]
    assert email_service.unsuppress(rhash) is True
    assert tables["email_suppressions"].delete.call_args.kwargs["filters"] == {
        "recipient_hash": f"eq.{rhash}",
    }
    tables["email_alert_suppressions"].delete.assert_not_called()
    tables["email_suppressions"].delete.return_value = []
    assert email_service.unsuppress(rhash) is False


# ── welcome: stamp only after it went out ───────────────────────────────────


@pytest.mark.parametrize("status,stamped", [
    ("sent", True), ("skipped", False), ("failed", False), ("duplicate", False), ("suppressed", False),
])
def test_queue_welcome_runs_on_sent_only_after_a_sent_outcome(monkeypatch, status, stamped):
    from fastapi import BackgroundTasks
    monkeypatch.setattr(email_service, "send_email", MagicMock(return_value=status))
    monkeypatch.setattr(email_service, "_already_sent", MagicMock(return_value=False))
    on_sent = MagicMock()
    bg = BackgroundTasks()
    email_service.queue_welcome(bg, email=TO, user_id="user_1", first_name="Ada", on_sent=on_sent)
    (task,) = bg.tasks
    assert task.func(*task.args, **task.kwargs) == status
    assert on_sent.called is stamped
    assert email_service.send_email.call_args.kwargs["dedupe_key"] == "welcome:user_1"


@pytest.mark.parametrize("ledger,stamped", [
    ([{"status": "sent"}], True),     # delivered earlier, the stamp failed: stamp now
    ([{"status": "queued"}], False),  # another attempt is live: not yet
    ([], False),
])
def test_duplicate_of_an_already_sent_welcome_runs_on_sent(tables, monkeypatch, ledger, stamped):
    # Review follow-up on #763: without this, a welcome whose welcomed_at stamp
    # failed re-ran the pipeline on every sign-in forever ("duplicate" each time).
    monkeypatch.setattr(email_service, "send_email", MagicMock(return_value="duplicate"))
    tables["email_sends"].select.return_value = ledger
    on_sent = MagicMock()
    assert email_service._send_then(on_sent, dedupe_key="welcome:user_1") == "duplicate"
    assert on_sent.called is stamped
    assert tables["email_sends"].select.call_args.kwargs["filters"] == {"dedupe_key": "eq.welcome:user_1"}


def test_ledger_read_failure_does_not_stamp(tables, monkeypatch):
    monkeypatch.setattr(email_service, "send_email", MagicMock(return_value="duplicate"))
    tables["email_sends"].select.side_effect = RuntimeError("down")
    on_sent = MagicMock()
    assert email_service._send_then(on_sent, dedupe_key="welcome:user_1") == "duplicate"
    on_sent.assert_not_called()


def test_a_failing_on_sent_hook_never_raises(monkeypatch):
    monkeypatch.setattr(email_service, "send_email", MagicMock(return_value="sent"))
    assert email_service._send_then(MagicMock(side_effect=RuntimeError("db")), dedupe_key="k") == "sent"


def test_suppressed_recipient_is_recorded_and_not_sent(tables, resend):
    tables["email_suppressions"].select.return_value = [
        {"recipient_hash": email_service.recipient_hash(TO)}
    ]
    assert _send(kind="waitlist_approved", dedupe_key="waitlist_approved:x") == "suppressed"
    resend.post.assert_not_called()
    assert tables["email_sends"].upsert.call_args.args[0]["status"] == "suppressed"
    assert tables["email_suppressions"].select.call_args.kwargs["filters"] == {
        "recipient_hash": f"eq.{email_service.recipient_hash(TO)}",
    }
    tables["email_alert_suppressions"].select.assert_not_called()


#: Where each scope's suppressions live: `all` in the original table (left
#: exactly as it was, so a backend mid-deploy keeps working), `ops_alert` in
#: its own.
SCOPE_TABLES = {"all": "email_suppressions", "ops_alert": "email_alert_suppressions"}


def _suppressed_for(tables, *scopes, reason="unsubscribe"):
    """TO's hash is suppressed under `scopes` only (each in its own table),
    with `reason`; a read filtered on `reason=in.(...)` sees the row only when
    its reason is in the list."""
    rhash = email_service.recipient_hash(TO)

    for scope, name in SCOPE_TABLES.items():
        def select(columns, filters=None, _held=scope in scopes, **_):
            filters = filters or {}
            if not _held or filters.get("recipient_hash") != f"eq.{rhash}":
                return []
            wanted = filters.get("reason")
            if wanted is not None:
                assert wanted.startswith("in.(") and wanted.endswith(")"), wanted
                if reason not in wanted[4:-1].split(","):
                    return []
            return [{"recipient_hash": rhash, "reason": reason}]

        tables[name].select.side_effect = select


def test_a_broadcast_unsubscribe_does_not_stop_ops_alerts(tables, resend):
    """An admin who unsubscribed from Sapling email (one click on a broadcast)
    still gets ops alerts: an operational send reads email_suppressions only
    for a bounce or complaint, and ignores the notification opt-out."""
    _suppressed_for(tables, "all", reason="unsubscribe")
    _opted_out(tables)
    assert _send(kind="ops_alert", dedupe_key="ops_alert:x") == "sent"
    assert tables["email_sends"].upsert.call_args.args[0]["status"] == "queued"
    rhash_filter = f"eq.{email_service.recipient_hash(TO)}"
    assert tables["email_alert_suppressions"].select.call_args.kwargs["filters"] == {
        "recipient_hash": rhash_filter,
    }
    assert tables["email_suppressions"].select.call_args.kwargs["filters"] == {
        "recipient_hash": rhash_filter,
        "reason": "in.(bounce,complaint)",
    }
    tables["user_settings"].select_with_count.assert_not_called()


@pytest.mark.parametrize("reason", ["bounce", "complaint"])
def test_a_bounce_or_complaint_stops_ops_alerts_too(tables, resend, reason):
    """A bounce or complaint is about the ADDRESS, not a choice of what to
    receive: mailing it again hurts the sending domain whatever the kind, so
    it stops an ops alert like every other kind."""
    _suppressed_for(tables, "all", reason=reason)
    assert _send(kind="ops_alert", dedupe_key="ops_alert:x") == "suppressed"
    resend.post.assert_not_called()
    assert tables["email_sends"].upsert.call_args.args[0]["status"] == "suppressed"


def test_an_ordinary_send_still_reads_every_suppression_reason(tables, resend):
    _suppressed_for(tables, "all", reason="unsubscribe")
    assert _send(kind="welcome", dedupe_key="welcome:user_1") == "suppressed"
    assert tables["email_suppressions"].select.call_args.kwargs["filters"] == {
        "recipient_hash": f"eq.{email_service.recipient_hash(TO)}",
    }
    tables["email_alert_suppressions"].select.assert_not_called()


def test_an_ops_unsubscribe_stops_ops_alerts_and_nothing_else(tables, resend):
    _suppressed_for(tables, "ops_alert")
    assert _send(kind="ops_alert", dedupe_key="ops_alert:x") == "suppressed"
    resend.post.assert_not_called()
    assert _send(kind="welcome", dedupe_key="welcome:user_1") == "sent"
    assert _send(kind="broadcast", dedupe_key="broadcast:b1:h", broadcast_id="b1") == "sent"


def test_an_ops_alert_carries_the_ops_scoped_unsubscribe(tables, resend):
    assert _send(kind="ops_alert", dedupe_key="ops_alert:x") == "sent"
    headers = resend.post.call_args.kwargs["json"]["headers"]
    scoped = email_service.unsubscribe_url(TO, scope="ops_alert")
    assert headers["List-Unsubscribe"] == f"<{scoped}>"
    assert headers["List-Unsubscribe-Post"] == "List-Unsubscribe=One-Click"
    assert "scope=ops_alert" in scoped and scoped != email_service.unsubscribe_url(TO)


def test_a_scoped_token_verifies_only_for_its_own_scope(tables):
    rhash = email_service.recipient_hash(TO)
    ops = email_service.unsubscribe_token(TO, scope="ops_alert")
    everything = email_service.unsubscribe_token(TO)
    assert email_service.verify_unsubscribe_token(ops, "ops_alert") == rhash
    assert email_service.verify_unsubscribe_token(ops) is None
    assert email_service.verify_unsubscribe_token(everything, "ops_alert") is None
    assert email_service.verify_unsubscribe_token(everything, "nonsense") is None


def test_suppress_and_unsuppress_are_scoped(tables):
    rhash = email_service.recipient_hash(TO)
    email_service.suppress(rhash, "unsubscribe", scope="ops_alert")
    call = tables["email_alert_suppressions"].upsert.call_args
    assert call.args[0] == {"recipient_hash": rhash, "reason": "unsubscribe"}
    assert call.kwargs == {"on_conflict": "recipient_hash", "ignore_duplicates": True}
    email_service.unsuppress(rhash, scope="ops_alert")
    assert tables["email_alert_suppressions"].delete.call_args.kwargs["filters"] == {
        "recipient_hash": f"eq.{rhash}",
    }
    tables["email_suppressions"].upsert.assert_not_called()
    tables["email_suppressions"].delete.assert_not_called()


def test_an_all_scope_suppression_writes_exactly_what_it_always_did(tables):
    """email_suppressions keeps its original shape and key, so the write is
    the one a backend from before scopes makes: no `scope` column, conflict
    on recipient_hash (a deploy runs the migration first, and the old backend
    serving meanwhile must not 500 an unsubscribe)."""
    rhash = email_service.recipient_hash(TO)
    email_service.suppress(rhash, "unsubscribe")
    call = tables["email_suppressions"].upsert.call_args
    assert call.args[0] == {"recipient_hash": rhash, "reason": "unsubscribe"}
    assert call.kwargs == {"on_conflict": "recipient_hash", "ignore_duplicates": True}
    tables["email_alert_suppressions"].upsert.assert_not_called()


@pytest.mark.parametrize("reason", email_service.DELIVERABILITY_REASONS)
@pytest.mark.parametrize("scope", sorted(email_service.SUPPRESSION_TABLES))
def test_a_bounce_or_complaint_replaces_an_existing_unsubscribe(tables, reason, scope):
    """A stronger reason overwrites the row's reason (DO UPDATE on the same
    recipient_hash conflict), so an address that unsubscribed and later
    bounced reads as a bounce, which the ops-alert check (`_stops_send`)
    filters on."""
    rhash = email_service.recipient_hash(TO)
    email_service.suppress(rhash, reason, scope=scope)
    call = tables[email_service.SUPPRESSION_TABLES[scope]].upsert.call_args
    assert call.args[0] == {"recipient_hash": rhash, "reason": reason}
    assert call.kwargs == {"on_conflict": "recipient_hash", "ignore_duplicates": False}


def test_an_unsubscribe_never_downgrades_a_bounce_or_complaint(tables):
    """An unsubscribe only makes sure a row exists (DO NOTHING on conflict): a
    bounce or complaint already there keeps its reason."""
    rhash = email_service.recipient_hash(TO)
    email_service.suppress(rhash, "unsubscribe")
    assert tables["email_suppressions"].upsert.call_args.kwargs["ignore_duplicates"] is True


def test_an_unknown_reason_is_refused(tables):
    with pytest.raises(ValueError):
        email_service.suppress("a" * 64, "spam")
    tables["email_suppressions"].upsert.assert_not_called()


def test_an_unknown_scope_is_refused(tables):
    with pytest.raises(ValueError):
        email_service.suppress("a" * 64, scope="everything")
    with pytest.raises(ValueError):
        email_service.is_suppressed("a" * 64, scope="everything")


_MIGRATIONS = pathlib.Path(__file__).resolve().parents[1] / "db" / "migrations"


def test_the_ops_scope_migration_leaves_email_suppressions_untouched():
    """Only the original email migration may alter email_suppressions: any
    later change to its key breaks the backend still serving mid-deploy."""
    alters = re.compile(r"ALTER\s+TABLE\s+(?:IF\s+EXISTS\s+)?(?:public\.)?email_suppressions\b", re.I)
    touching = sorted(
        p.name for p in _MIGRATIONS.glob("*.sql")
        if alters.search(re.sub(r"--[^\n]*", "", p.read_text(encoding="utf-8")))
    )
    assert touching == ["20261022063145_email.sql"]


def test_the_ops_scope_table_is_service_only():
    (mig,) = _MIGRATIONS.glob("*_email_alert_suppressions.sql")
    sql = re.sub(r"--[^\n]*", "", mig.read_text(encoding="utf-8"))
    assert re.search(r"CREATE\s+TABLE\s+IF\s+NOT\s+EXISTS\s+public\.email_alert_suppressions", sql)
    assert re.search(r"recipient_hash\s+TEXT\s+PRIMARY\s+KEY", sql, re.I)
    assert "ENABLE ROW LEVEL SECURITY" in sql
    assert re.search(r"REVOKE\s+ALL\s+ON\s+public\.email_alert_suppressions\s+FROM\s+anon,\s*authenticated", sql)
    assert re.search(r"GRANT\s+SELECT,\s*INSERT,\s*UPDATE,\s*DELETE\s+ON\s+public\.email_alert_suppressions\s+TO\s+service_role", sql)


def test_the_ops_alert_template_carries_the_link_it_is_given():
    url = "https://sapling.example/api/email/unsubscribe?t=x&scope=ops_alert"
    _, html, text = email_templates.ops_alert(
        "Spend spike", [("Spend", "$12")], dashboard_url="https://d.example", unsubscribe_url=url,
    )
    assert "scope=ops_alert" in html and url in text
    assert "admin alerts" in html.lower() and "admin alerts" in text.lower()


def test_suppressed_recipient_still_gets_no_broadcast(tables, resend):
    tables["email_suppressions"].select.return_value = [
        {"recipient_hash": email_service.recipient_hash(TO)}
    ]
    assert _send(kind="broadcast", dedupe_key="broadcast:b1:h", broadcast_id="b1") == "suppressed"
    resend.post.assert_not_called()


def test_operational_kind_keeps_the_never_twice_claim(tables, resend):
    tables["email_sends"].upsert.return_value = []  # key already claimed
    assert _send(kind="ops_alert", dedupe_key="ops_alert:x") == "duplicate"
    resend.post.assert_not_called()


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
    assert call.kwargs["headers"]["Idempotency-Key"] == "welcome:user_1"
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


def test_ops_alert_template_offers_to_stop_admin_alerts_not_all_email():
    subject, html, text = email_templates.ops_alert(
        "Spend over $10", [("Today", "$15.00")], dashboard_url="https://sapling.example/admin",
        unsubscribe_url="https://u.example/?scope=ops_alert",
    )
    assert "Sapling" in html and "$15.00" in text
    assert "from Sapling emails" not in html and "Unsubscribe from Sapling admin alerts:" in text


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


def test_unsuppress_all_scopes_lifts_the_hash_from_every_table(tables):
    rhash = email_service.recipient_hash(TO)
    tables["email_alert_suppressions"].delete.return_value = [{"recipient_hash": rhash}]
    assert email_service.unsuppress_all_scopes(rhash) == ["ops_alert"]
    for name in SCOPE_TABLES.values():
        assert tables[name].delete.call_args.kwargs["filters"] == {"recipient_hash": f"eq.{rhash}"}


# ── A batch's suppressions, read once (spend_alerts.run_once) ───────────────


def _rows_by_table(tables, rows: dict[str, list[dict]]):
    """`page_all` over each suppression table answers `rows[name]`, honouring
    a `reason=in.(...)` filter; every call is recorded on the mock."""
    for name in SCOPE_TABLES.values():
        def select_with_count(columns, filters=None, _rows=rows.get(name, []), **_):
            wanted = (filters or {}).get("reason")
            kept = [r for r in _rows if wanted is None or r["reason"] in wanted[4:-1].split(",")]
            return kept, len(kept)

        tables[name].select_with_count.side_effect = select_with_count


def test_ops_suppressions_are_the_ops_table_and_the_alls_bounces_and_complaints(tables):
    _rows_by_table(tables, {
        "email_alert_suppressions": [{"recipient_hash": "a" * 64, "reason": "unsubscribe"}],
        "email_suppressions": [
            {"recipient_hash": "b" * 64, "reason": "bounce"},
            {"recipient_hash": "c" * 64, "reason": "complaint"},
            {"recipient_hash": "d" * 64, "reason": "unsubscribe"},  # a broadcast unsubscribe
        ],
    })
    prefetched = email_service.suppressions_for("ops_alert")
    assert prefetched.scope == "ops_alert"
    assert prefetched.hashes == {"a" * 64, "b" * 64, "c" * 64}
    assert tables["email_suppressions"].select_with_count.call_args.kwargs["filters"] == {
        "reason": "in.(bounce,complaint)",
    }


def test_all_scope_suppressions_are_its_own_table_only(tables):
    _rows_by_table(tables, {
        "email_suppressions": [{"recipient_hash": "d" * 64, "reason": "unsubscribe"}],
        "email_alert_suppressions": [{"recipient_hash": "a" * 64, "reason": "unsubscribe"}],
    })
    assert email_service.suppressions_for("all").hashes == {"d" * 64}
    tables["email_alert_suppressions"].select_with_count.assert_not_called()


@pytest.mark.parametrize("held, status", [(True, "suppressed"), (False, "sent")])
def test_a_prefetched_set_answers_the_send_with_no_read_of_its_own(tables, resend, held, status):
    rhash = email_service.recipient_hash(TO)
    prefetched = email_service.Suppressions("ops_alert", frozenset({rhash} if held else set()))
    assert _send(kind="ops_alert", dedupe_key="ops_alert:x", suppressions=prefetched) == status
    tables["email_suppressions"].select.assert_not_called()
    tables["email_alert_suppressions"].select.assert_not_called()


def test_a_prefetched_set_for_another_scope_is_ignored(tables, resend):
    """A set read for `all` says nothing about an ops send: it reads its own."""
    _suppressed_for(tables, "ops_alert")
    prefetched = email_service.Suppressions("all", frozenset())
    assert _send(kind="ops_alert", dedupe_key="ops_alert:x", suppressions=prefetched) == "suppressed"
    tables["email_alert_suppressions"].select.assert_called()

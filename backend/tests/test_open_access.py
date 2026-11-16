"""
Open access: the waitlist requirement as the `open_access` flag
(docs/design/open-access-gate.md).

- Access is computed: approved, OR (gate open AND `users.open_access_at`).
  Flipping the flag writes nothing.
- While the gate is open anyone signs in (any email domain): a new account is
  created UNAPPROVED and marked, and linked on the waitlist unapproved, so
  closing the gate puts it back on the waitlist.
- An account an admin removed (unapproved, no mark) stays out while open.
- The guard, /me and the "has access" listings follow the same rule.
- The email domain is a label only ("Non-BU").
"""
# The `callback` fixture is imported from the waitlist tests and named as a
# test parameter, which ruff reads as a redefinition (the repo's usual F811).
# ruff: noqa: F811
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

import routes.auth as auth_module
import services.auth.signin as signin_module
from services import auth_guard, open_access
from services.auth import accounts
from tests.test_auth_session_access_756 import _real_guard, _request, _row, _token  # noqa: F401
from tests.test_auth_waitlist_approval import APPROVED_AT, _tables, callback  # noqa: F401

OPENED_AT = "2026-11-16T12:00:00+00:00"


def _gate(monkeypatch, is_open: bool) -> None:
    monkeypatch.setattr(signin_module, "gate_open", lambda: is_open)
    monkeypatch.setattr(open_access, "gate_open", lambda: is_open)


def _user_upsert(tables) -> dict | None:
    call = tables["users"].upsert.call_args
    return call.args[0] if call else None


def _users_updates(tables) -> list[dict]:
    return [c.args[0] for c in tables["users"].update.call_args_list if c.args]


# ── the helpers ──────────────────────────────────────────────────────────────


class TestAccessRule:
    @pytest.mark.parametrize("row,open_now,expected", [
        ({"is_approved": True}, False, "approved"),
        ({"is_approved": True, "open_access_at": OPENED_AT}, False, "approved"),
        ({"is_approved": False, "open_access_at": OPENED_AT}, True, "open"),
        ({"is_approved": False, "open_access_at": OPENED_AT}, False, "none"),
        # A removed account: no mark, so the open gate does not let it in.
        ({"is_approved": False, "open_access_at": None}, True, "none"),
    ])
    def test_access_kind(self, row, open_now, expected):
        assert open_access.access_kind(row, open_now=open_now) == expected
        assert open_access.has_access(row, open_now=open_now) is (expected != "none")

    def test_access_filter(self):
        assert open_access.access_filter(open_now=False) == {"is_approved": "eq.true"}
        assert open_access.access_filter(open_now=True) == {
            "or": "(is_approved.eq.true,open_access_at.not.is.null)"}

    @pytest.mark.parametrize("email,school", [
        ("ada@bu.edu", True), ("Ada@BU.EDU", True), ("ada@cs.bu.edu", True),
        ("ada@gmail.com", False), ("ada@notbu.edu", False), ("ada@bu.edu.evil.com", False),
        ("", False), (None, False), ("bu.edu", False),
    ])
    def test_school_email_label(self, email, school):
        assert open_access.is_school_email(email) is school

    def test_flag_is_registered_off_first_global_and_client_visible(self):
        from services.feature_flags import REGISTRY
        fd = REGISTRY["open_access"]
        assert fd.variants == ("off", "on")  # "off" = the gated, fail-closed side
        assert fd.client_visible  # the landing page switches its copy on it


# ── sign-in ──────────────────────────────────────────────────────────────────


class TestSignIn:
    def test_no_domain_restriction_closed_gate_sends_anyone_to_pending(self, callback, monkeypatch):
        """A non-BU address is no longer refused (`invalid_domain` is gone):
        it is simply not approved, like anyone else."""
        _gate(monkeypatch, False)
        tables = _tables(monkeypatch, users_rows=[], waitlist_rows=[])
        assert callback(email="someone@gmail.com") == "/pending"
        assert _user_upsert(tables) is None  # nothing stored

    def test_non_bu_approved_on_the_waitlist_gets_in(self, callback, monkeypatch):
        _gate(monkeypatch, False)
        tables = _tables(monkeypatch, users_rows=[], waitlist_rows=[
            {"id": "w1", "email": "someone@gmail.com", "approved_at": APPROVED_AT}])
        assert callback(email="someone@gmail.com") == "/auth/callback"
        assert _user_upsert(tables)["is_approved"] is True

    def test_open_gate_lets_a_new_person_in_unapproved_and_marked(self, callback, monkeypatch):
        _gate(monkeypatch, True)
        tables = _tables(monkeypatch, users_rows=[], waitlist_rows=[])
        assert callback(email="someone@gmail.com") == "/auth/callback"
        row = _user_upsert(tables)
        assert row["is_approved"] is False
        assert row["open_access_at"]
        # Put on the waitlist, unapproved: never approved_at / joined_at.
        added = tables["newsletter_emails"].upsert.call_args
        assert added.args[0]["email"] == "someone@gmail.com"
        assert "approved_at" not in added.args[0]
        assert added.kwargs == {"on_conflict": "email", "ignore_duplicates": True}
        for c in tables["newsletter_emails"].update.call_args_list:
            assert "approved_at" not in c.args[0] and "joined_at" not in c.args[0]

    def test_open_gate_links_an_existing_waitlist_row_without_approving_it(self, callback, monkeypatch):
        _gate(monkeypatch, True)
        tables = _tables(monkeypatch, users_rows=[], waitlist_rows=[
            {"id": "w1", "email": "student@bu.edu", "approved_at": None,
             "joined_at": None, "joined_user_id": None}])
        assert callback() == "/auth/callback"
        assert _user_upsert(tables)["open_access_at"]
        tables["newsletter_emails"].upsert.assert_not_called()
        (link,) = tables["newsletter_emails"].update.call_args_list
        assert link.args[0] == {"joined_user_id": "user_112233"}
        assert link.kwargs["filters"] == {"id": "eq.w1", "joined_user_id": "is.null"}

    def test_approved_new_account_carries_no_mark(self, callback, monkeypatch):
        _gate(monkeypatch, True)
        tables = _tables(monkeypatch, users_rows=[], waitlist_rows=[
            {"id": "w1", "email": "student@bu.edu", "approved_at": APPROVED_AT}])
        assert callback() == "/auth/callback"
        row = _user_upsert(tables)
        assert row["is_approved"] is True and row["open_access_at"] is None

    def test_removed_account_stays_out_while_open(self, callback, monkeypatch):
        _gate(monkeypatch, True)
        tables = _tables(monkeypatch, users_rows=[
            {"id": "user_112233", "is_approved": False, "open_access_at": None}])
        assert callback() == "/pending"
        assert {"is_approved": True} not in _users_updates(tables)

    def test_open_access_account_gets_in_while_open(self, callback, monkeypatch):
        _gate(monkeypatch, True)
        tables = _tables(monkeypatch, users_rows=[
            {"id": "user_112233", "is_approved": False, "open_access_at": OPENED_AT}])
        assert callback() == "/auth/callback"
        assert {"is_approved": True} not in _users_updates(tables)  # still not approved

    def test_open_access_account_waits_once_the_gate_closes(self, callback, monkeypatch):
        _gate(monkeypatch, False)
        _tables(monkeypatch, users_rows=[
            {"id": "user_112233", "is_approved": False, "open_access_at": OPENED_AT}])
        assert callback() == "/pending"

    def test_open_access_account_approved_on_the_waitlist_gets_in_when_closed(self, callback, monkeypatch):
        _gate(monkeypatch, False)
        tables = _tables(
            monkeypatch,
            users_rows=[{"id": "user_112233", "is_approved": False, "open_access_at": OPENED_AT}],
            waitlist_rows=[{"id": "w1", "email": "student@bu.edu", "approved_at": APPROVED_AT}],
        )
        assert callback() == "/auth/callback"
        assert {"is_approved": True} in _users_updates(tables)

    def test_unreadable_flag_store_reads_as_closed(self, callback, monkeypatch):
        """No patch: the real flag read, against a store the mocked tables
        cannot answer, fails closed."""
        monkeypatch.setattr(open_access, "flag_on", lambda key, uid: False)
        monkeypatch.setattr(signin_module, "gate_open", open_access.gate_open)
        _tables(monkeypatch, users_rows=[], waitlist_rows=[])
        assert callback(email="someone@gmail.com") == "/pending"

    def test_callback_no_longer_checks_a_domain(self):
        assert not hasattr(auth_module, "_email_domain_allowed")
        assert not hasattr(signin_module, "_email_domain_allowed")


# ── the guard and /me ────────────────────────────────────────────────────────


class TestGuard:
    def setup_method(self):
        auth_guard.clear_account_state_cache()

    def test_open_access_account_passes_while_open(self, real_guard, monkeypatch):
        _gate(monkeypatch, True)
        real_guard.select.return_value = _row(is_approved=False, open_access_at=OPENED_AT)
        assert auth_guard._real_get_session_user_id(_request(_token())) == "user_alice"

    def test_open_access_account_is_not_approved_once_closed(self, real_guard, monkeypatch):
        _gate(monkeypatch, False)
        real_guard.select.return_value = _row(is_approved=False, open_access_at=OPENED_AT)
        with pytest.raises(HTTPException) as exc:
            auth_guard._real_get_session_user_id(_request(_token()))
        assert exc.value.status_code == 403
        assert exc.value.detail["code"] == "not_approved"

    def test_removed_account_is_refused_while_open(self, real_guard, monkeypatch):
        _gate(monkeypatch, True)
        real_guard.select.return_value = _row(is_approved=False, open_access_at=None)
        with pytest.raises(HTTPException) as exc:
            auth_guard._real_get_session_user_id(_request(_token()))
        assert exc.value.status_code == 403

    def test_approved_account_never_reads_the_flag(self, real_guard, monkeypatch):
        def boom():
            raise AssertionError("flag read for an approved account")
        monkeypatch.setattr(open_access, "gate_open", boom)
        real_guard.select.return_value = _row()
        assert auth_guard._real_get_session_user_id(_request(_token())) == "user_alice"


class TestMe:
    def _me(self, monkeypatch, row, *, is_open):
        _gate(monkeypatch, is_open)
        users = MagicMock()
        users.select.return_value = [{"id": "u1", "deleted_at": None, **row}]
        empty = MagicMock()
        empty.select.return_value = []
        monkeypatch.setattr(accounts, "table", lambda name: users if name == "users" else empty)
        monkeypatch.setattr(accounts, "gate_open", lambda: is_open)
        return accounts.account_overview("u1")

    @pytest.mark.parametrize("row,is_open,approved,access", [
        ({"is_approved": True}, False, True, "approved"),
        ({"is_approved": False, "open_access_at": OPENED_AT}, True, True, "open"),
        ({"is_approved": False, "open_access_at": OPENED_AT}, False, False, "none"),
        ({"is_approved": False, "open_access_at": None}, True, False, "none"),
    ])
    def test_me_reports_computed_access(self, monkeypatch, row, is_open, approved, access):
        me = self._me(monkeypatch, row, is_open=is_open)
        assert me["is_approved"] is approved  # what the frontend middleware routes on
        assert me["access"] == access


# ── listings ─────────────────────────────────────────────────────────────────


class TestListings:
    def test_directory_lists_open_access_accounts_only_while_open(self, monkeypatch):
        from services.social import directory
        monkeypatch.setattr(directory, "gate_open", lambda: True)
        assert directory._listable_user_filters()["or"] == (
            "(is_approved.eq.true,open_access_at.not.is.null)")
        monkeypatch.setattr(directory, "gate_open", lambda: False)
        f = directory._listable_user_filters()
        assert f["is_approved"] == "eq.true" and "or" not in f

    def test_admin_users_list_follows_the_gate(self, monkeypatch):
        import services.users_search as us
        monkeypatch.setattr(us, "gate_open", lambda: True)
        assert "or" in us._with_access()
        monkeypatch.setattr(us, "gate_open", lambda: False)
        assert us._with_access() == {"is_approved": "eq.true"}

    def test_overview_counts_open_access_as_in_while_open(self, monkeypatch):
        from services.admin import overview
        users = [
            {"id": "a", "is_approved": True, "created_at": "2026-11-01T00:00:00Z"},
            {"id": "b", "is_approved": False, "open_access_at": OPENED_AT,
             "created_at": "2026-11-02T00:00:00Z"},
            {"id": "c", "is_approved": False, "created_at": "2026-11-03T00:00:00Z"},
        ]
        waitlist = [
            {"approved_at": None, "joined_user_id": "b"},     # in through the gate
            {"approved_at": None, "joined_user_id": None},    # waiting
            {"approved_at": APPROVED_AT, "joined_user_id": "a"},
        ]
        tables = {"users": users, "roles": [], "user_roles": [], "newsletter_emails": waitlist}

        def factory(name):
            m = MagicMock()
            m.select.return_value = tables.get(name, [])
            return m
        monkeypatch.setattr(overview, "table", factory)
        monkeypatch.setattr(overview, "gate_open", lambda: True)
        totals = overview.analytics_overview()["totals"]
        # `approved` is approvals only; the open-access entrant is counted apart.
        assert totals["approved"] == 1 and totals["open_access"] == 1
        assert totals["pending"] == 1  # the open-access entrant is in, not waiting
        monkeypatch.setattr(overview, "gate_open", lambda: False)
        totals = overview.analytics_overview()["totals"]
        assert totals["approved"] == 1 and totals["open_access"] == 0
        assert totals["pending"] == 2  # gate closed: back to waiting


# ── admin actions ────────────────────────────────────────────────────────────


class TestAllowlistApprove:
    def test_no_youre_in_email_for_an_open_access_account(self, monkeypatch):
        """They already use Sapling; approving keeps them in once the gate
        closes and says nothing new."""
        from services.admin import allowlist
        monkeypatch.setattr(allowlist, "gate_open", lambda: True)
        monkeypatch.setattr(allowlist, "_open_access_ids", lambda ids: {"user_1"})
        monkeypatch.setattr(allowlist, "_grant_linked_accounts", lambda rows, now: None)
        monkeypatch.setattr(allowlist, "table", lambda name: MagicMock())
        by_lower = {
            "open@gmail.com": [{"id": "w1", "email": "open@gmail.com", "approved_at": None,
                                "joined_user_id": "user_1"}],
            "wait@bu.edu": [{"id": "w2", "email": "wait@bu.edu", "approved_at": None,
                             "joined_user_id": None}],
        }
        recipients, _ = allowlist._approve_waitlist(
            ["open@gmail.com", "wait@bu.edu", "new@bu.edu"], by_lower, "now")
        assert [a for a, _ in recipients] == ["wait@bu.edu", "new@bu.edu"]

    def test_youre_in_email_for_an_open_access_account_once_the_gate_closes(self, monkeypatch):
        """With the gate closed they are back on /pending: the approval is
        what lets them in, so they are told, like any other approval."""
        from services.admin import allowlist
        monkeypatch.setattr(allowlist, "gate_open", lambda: False)
        monkeypatch.setattr(allowlist, "_open_access_ids", lambda ids: {"user_1"})
        monkeypatch.setattr(allowlist, "_grant_linked_accounts", lambda rows, now: None)
        monkeypatch.setattr(allowlist, "table", lambda name: MagicMock())
        by_lower = {
            "open@gmail.com": [{"id": "w1", "email": "open@gmail.com", "approved_at": None,
                                "joined_user_id": "user_1"}],
        }
        recipients, _ = allowlist._approve_waitlist(["open@gmail.com"], by_lower, "now")
        assert [a for a, _ in recipients] == ["open@gmail.com"]

    def test_rows_carry_open_access_and_the_school_label(self, monkeypatch):
        from services.admin import allowlist
        monkeypatch.setattr(allowlist, "_send_statuses", lambda keys: {})
        monkeypatch.setattr(allowlist, "_open_access_ids", lambda ids: {"user_1"})
        rows = allowlist._with_invite_status([
            {"id": "w1", "email": "open@gmail.com", "joined_user_id": "user_1"},
            {"id": "w2", "email": "wait@bu.edu", "joined_user_id": None},
        ])
        assert [(r["open_access"], r["school_email"]) for r in rows] == [
            (True, False), (False, True)]


# ── the shared open-access read, the kill switch, the cleanup script ─────────


class TestOpenAccessIds:
    def test_one_read_of_live_unapproved_marked_accounts(self, monkeypatch):
        seen = {}

        def fake_page_all(handle, columns, *, filters, order):
            seen["filters"] = filters
            return [{"id": "user_1"}, {"id": "user_2"}]
        monkeypatch.setattr(open_access, "page_all", fake_page_all)
        monkeypatch.setattr(open_access, "table", lambda name: MagicMock())
        assert open_access.open_access_user_ids() == {"user_1", "user_2"}
        # A soft-deleted entrant is not "in" (sign-in and the guard refuse it).
        assert seen["filters"] == {"open_access_at": "not.is.null", "is_approved": "eq.false",
                                   "deleted_at": "is.null"}

    def test_allowlist_intersects_and_degrades_to_none(self, monkeypatch):
        from services.admin import allowlist
        monkeypatch.setattr(allowlist, "open_access_user_ids", lambda: {"user_1", "user_9"})
        assert allowlist._open_access_ids(["user_1", "user_2", None]) == {"user_1"}
        assert allowlist._open_access_ids([None]) == set()

        def boom():
            raise RuntimeError("db down")
        monkeypatch.setattr(allowlist, "open_access_user_ids", boom)
        assert allowlist._open_access_ids(["user_1"]) == set()


class TestEnvOverride:
    @pytest.mark.parametrize("env,expected", [("off", "off"), ("on", "on"), ("", None), ("bogus", None)])
    def test_env_override(self, monkeypatch, env, expected):
        from services import feature_flags
        monkeypatch.setenv("SAPLING_FLAG_OPEN_ACCESS", env)
        assert feature_flags.env_override("open_access") == expected

    def test_unregistered_flag_has_no_override(self, monkeypatch):
        from services import feature_flags
        monkeypatch.setenv("SAPLING_FLAG_NOPE", "on")
        assert feature_flags.env_override("nope") is None


class TestCleanupScript:
    def test_never_selects_open_access_entrants(self, monkeypatch):
        """An open-access entrant is unapproved by design and may not have
        onboarded; the one-off cleanup must not delete a live account."""
        from scripts import move_unapproved_users_to_waitlist as script
        users = MagicMock()
        users.select.return_value = []
        monkeypatch.setattr(script, "table", lambda name: users)
        script._unapproved()
        filters = users.select.call_args.kwargs["filters"]
        assert filters["open_access_at"] == "is.null"
        assert filters["is_approved"] == "eq.false"


def test_open_access_waitlist_row_binds_its_first_name(monkeypatch):
    """sec2 M13 x open access: the entrant's waitlist row seals first_name
    under its cell binding, so the bound readers (allowlist, admin email)
    open it once v2 writes are on."""
    from services.auth import waitlist
    from services.encryption import bind, decrypt

    monkeypatch.setenv("ENCRYPTION_WRITE_V2", "on")
    written = {}
    fake = MagicMock()
    fake.upsert.side_effect = lambda row, **_k: written.update(row)
    monkeypatch.setattr(waitlist, "table", lambda name: fake)
    monkeypatch.setattr(waitlist, "_waitlist_entry", lambda email: None)
    waitlist._link_open_access_entry("ada@example.com", "Ada", None, "user_1")
    assert written["first_name"].startswith("enc2:")
    assert decrypt(written["first_name"],
                   bind=bind("newsletter_emails", "first_name", "ada@example.com")) == "Ada"

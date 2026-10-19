"""Checklist-participant admission against disposable local PostgreSQL.

Budget writes use the real PostgREST RPC seam; assertions use independent SQL.
All usage here is explicitly synthetic measured-response metadata, never a model
call or learner evidence. The integration conftest enforces loopback and resets
the disposable stack. Run under the whole-stack singleton lock, not on a pilot.
These tests do not establish a global/provider-invoice spending guarantee.
"""

from __future__ import annotations

import hashlib
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

import httpx
import pytest

pytestmark = pytest.mark.integration

POLICY = "flash-50k-3x8192-v1"
HOLD = Decimal("0.0764400000")
HOLD_TOKENS = 74_576
FUNCTIONS = (
    "checklist_budget_admit(text,text,text,uuid,text,text,numeric,numeric,bigint)",
    "checklist_budget_start(text,uuid,bigint)",
    "checklist_budget_read(text,uuid)",
    "checklist_budget_reconcile(text,uuid,bigint,text,jsonb,text,text)",
)


@pytest.fixture
def owner_enrollments(db_conn, seeded_user):
    """Real independent owner, four valid catalog offerings, no inherited bills."""
    from db.connection import table

    owner = seeded_user()
    offerings = db_conn.execute(
        "SELECT DISTINCT offering_id FROM enrollments WHERE user_id = %s "
        "ORDER BY offering_id LIMIT 4",
        ("rich-user-active",),
    ).fetchall()
    assert len(offerings) == 4
    enrollment_ids = [f"it-budget-enr-{uuid4().hex}" for _ in offerings]
    table("enrollments").insert(
        [
            {"id": eid, "user_id": owner, "offering_id": row["offering_id"]}
            for eid, row in zip(enrollment_ids, offerings, strict=True)
        ]
    )
    assert (
        db_conn.execute(
            "SELECT count(*) AS n FROM llm_usage WHERE user_id = %s", (owner,)
        ).fetchone()["n"]
        == 0
    )
    return owner, enrollment_ids


def _admit(owner, enrollment, *, daily=".20", monthly="2", tokens=400_000, params=None):
    from db.connection import rpc

    if params is None:
        operation = uuid4()
        params = {
            "p_user_id": owner,
            "p_enrollment_id": enrollment,
            "p_input_hash": hashlib.sha256(uuid4().bytes).hexdigest(),
            "p_operation_id": str(operation),
            "p_receipt_id": str(uuid5(NAMESPACE_URL, f"sapling:checklist-receipt:{operation}")),
            "p_policy": POLICY,
            "p_daily_usd": daily,
            "p_monthly_usd": monthly,
            "p_daily_tokens": tokens,
        }
    return rpc("checklist_budget_admit", params), params


def _identity(row):
    return {
        "p_user_id": row["user_id"],
        "p_operation_id": row["operation_id"],
        "p_fence": row["fence"],
    }


def _start(row):
    from db.connection import rpc

    result = rpc("checklist_budget_start", _identity(row))
    assert result["status"] == "started", result
    return result["reservation"]


def _admitted(owner, enrollment, **kwargs):
    result, _ = _admit(owner, enrollment, **kwargs)
    assert result["status"] == "admitted", result
    return result["reservation"]


def _db_row(db_conn, row):
    return db_conn.execute(
        "SELECT * FROM checklist_budget_reservations WHERE operation_id = %s",
        (row["operation_id"],),
    ).fetchone()


def _now(db_conn):
    return db_conn.execute("SELECT clock_timestamp() AS t").fetchone()["t"]


def _expire(db_conn, row):
    from db.connection import table

    table("checklist_budget_reservations").update(
        {"expires_at": (_now(db_conn) - timedelta(seconds=1)).isoformat()},
        {"operation_id": f"eq.{row['operation_id']}"},
    )


def _receipt(row, *, input_tokens=1000, output_tokens=100, cached_tokens=200):
    """Canonical pure receipt preparation; no agent/provider/queue invocation."""
    from pydantic_ai.messages import ModelResponse, TextPart
    from pydantic_ai.usage import RequestUsage, RunUsage

    from services.usage_receipts import prepare_checklist_usage_receipt

    details = {"thoughts_tokens": 10}
    response = ModelResponse(
        parts=[TextPart("Synthetic completed-response fixture; not learner content.")],
        model_name="gemini-2.5-flash",
        provider_name="google-gla",
        usage=RequestUsage(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cache_read_tokens=cached_tokens,
            details=details,
        ),
    )
    return prepare_checklist_usage_receipt(
        operation_id=UUID(row["operation_id"]),
        user_id=row["user_id"],
        approved_model="gemini-2.5-flash",
        responses=(response,),
        dispatched_requests=1,
        usage=RunUsage(
            requests=1,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cache_read_tokens=cached_tokens,
            details=details,
        ),
        completed=True,
        dispatched_at=datetime.fromisoformat(row["dispatch_at"].replace("Z", "+00:00")),
    )


def _reconcile(row, *, receipt=None, content=None, action=None):
    from db.connection import rpc

    return rpc(
        "checklist_budget_reconcile",
        {
            **_identity(row),
            "p_action": action or ("settle" if receipt is not None else "unknown"),
            "p_receipt": receipt.to_row() if receipt is not None else None,
            "p_fingerprint": receipt.fingerprint if receipt is not None else None,
            "p_content": content,
        },
    )


def _content(label):
    from services.encryption import encrypt_json

    return encrypt_json({"topics": [], "synthetic_test_revision": label})


def _usage_row(owner, *, cost=".15", created_at=None):
    from services.events_service import build_llm_usage_row

    # Pure formatter only. This intentional ledger fixture is not an observed
    # provider bill; NULL tests represent an unpriced historical record.
    row = build_llm_usage_row(
        feature="integration_fixture",
        task="integration_fixture",
        model="gemini-2.5-flash",
        user_id=owner,
        usage={"input_tokens": 100, "output_tokens": 20},
    )
    row.update(
        id=f"it-budget-usage-{uuid4().hex}",
        cost_usd=float(Decimal(cost)) if cost is not None else None,
        created_at=(created_at or datetime.now(timezone.utc)).isoformat(),
    )
    return row


def test_concurrent_different_enrollments_share_one_daily_capacity(db_conn, owner_enrollments):
    owner, enrollments = owner_enrollments
    barrier = threading.Barrier(len(enrollments))

    def attempt(enrollment):
        barrier.wait(timeout=10)
        return _admit(owner, enrollment)[0]["status"]

    with ThreadPoolExecutor(max_workers=len(enrollments)) as pool:
        statuses = list(pool.map(attempt, enrollments))
    assert sorted(statuses) == ["admitted", "admitted", "denied", "denied"]
    totals = db_conn.execute(
        "SELECT count(*) AS n, sum(held_usd) AS usd, sum(held_tokens) AS tokens "
        "FROM checklist_budget_reservations WHERE user_id = %s "
        "AND state IN ('prepared','started','unknown')",
        (owner,),
    ).fetchone()
    assert totals == {"n": 2, "usd": HOLD * 2, "tokens": HOLD_TOKENS * 2}
    assert totals["usd"] <= Decimal(".20")


def test_same_operation_replay_and_start_cas_never_duplicate_a_hold(db_conn, owner_enrollments):
    from db.connection import rpc

    owner, enrollments = owner_enrollments
    first, params = _admit(owner, enrollments[0])
    again, _ = _admit(owner, enrollments[0], params=params)
    assert first["status"] == "admitted" and again["status"] == "replay"
    assert first["reservation"] == again["reservation"]
    started = _start(first["reservation"])
    replay = rpc("checklist_budget_start", _identity(started))
    assert replay["status"] == "not_started"
    assert _db_row(db_conn, started)["dispatch_at"] == datetime.fromisoformat(
        started["dispatch_at"].replace("Z", "+00:00")
    )
    assert (
        db_conn.execute(
            "SELECT count(*) AS n FROM checklist_budget_reservations WHERE user_id = %s", (owner,)
        ).fetchone()["n"]
        == 1
    )


def test_prepared_expiry_releases_without_dispatch_and_readmits(db_conn, owner_enrollments):
    from db.connection import rpc

    owner, enrollments = owner_enrollments
    old = _admitted(owner, enrollments[0])
    _expire(db_conn, old)
    assert rpc("checklist_budget_start", _identity(old))["status"] == "not_started"
    new = _admitted(owner, enrollments[0])
    assert new["fence"] > old["fence"]
    row = _db_row(db_conn, old)
    assert (row["state"], row["reason"], row["dispatch_at"]) == (
        "released",
        "prepared_expired",
        None,
    )


def test_start_waiting_on_account_lock_cannot_use_a_pre_wait_expiry_clock(
    db_conn, owner_enrollments
):
    from db.connection import rpc, table

    owner, enrollments = owner_enrollments
    row = _admitted(owner, enrollments[0])
    deadline = _now(db_conn) + timedelta(seconds=3)
    table("checklist_budget_reservations").update(
        {"expires_at": deadline.isoformat()}, {"operation_id": f"eq.{row['operation_id']}"}
    )
    outcomes, failures = [], []

    def start():
        try:
            outcomes.append(rpc("checklist_budget_start", _identity(row)))
        except BaseException as exc:
            failures.append(exc)

    thread = threading.Thread(target=start, daemon=True)
    try:
        with db_conn.transaction():
            db_conn.execute(
                "SELECT user_id FROM checklist_budget_accounts WHERE user_id = %s FOR UPDATE",
                (owner,),
            )
            thread.start()
            waiting = False
            until = time.monotonic() + 2
            while time.monotonic() < until:
                # Refresh the statistics snapshot inside this lock-holding
                # transaction rather than repeatedly observing its first read.
                db_conn.execute("SELECT pg_stat_clear_snapshot()")
                waiting = db_conn.execute(
                    "SELECT EXISTS (SELECT 1 FROM pg_stat_activity "
                    "WHERE pid <> pg_backend_pid() AND wait_event_type = 'Lock' "
                    "AND query LIKE %s) AS waiting",
                    ("%checklist_budget_start%",),
                ).fetchone()["waiting"]
                if waiting:
                    break
                time.sleep(0.02)
            assert waiting, "RPC never demonstrated the intended real account-lock wait"
            assert _now(db_conn) < deadline, "RPC did not enter before its prepared lease expired"
            while _now(db_conn) <= deadline:
                time.sleep(0.02)
        thread.join(timeout=10)
    finally:
        if thread.ident is not None:
            thread.join(timeout=10)
    assert not thread.is_alive() and failures == []
    assert [result["status"] for result in outcomes] == ["not_started"]
    assert _db_row(db_conn, row)["dispatch_at"] is None


def test_unknown_bill_keeps_hold_second_is_funded_and_third_is_denied(db_conn, owner_enrollments):
    owner, enrollments = owner_enrollments
    first = _start(_admitted(owner, enrollments[0]))
    _expire(db_conn, first)
    second = _admitted(owner, enrollments[0])
    third, _ = _admit(owner, enrollments[1])
    assert third["status"] == "denied"
    persisted = _db_row(db_conn, first)
    assert persisted["state"] == "unknown" and persisted["held_usd"] == HOLD
    assert persisted["dispatch_at"] == datetime.fromisoformat(first["dispatch_at"])
    assert _db_row(db_conn, second)["held_usd"] == HOLD
    assert (
        db_conn.execute(
            "SELECT sum(held_usd) AS usd FROM checklist_budget_reservations "
            "WHERE user_id = %s AND state IN ('prepared','started','unknown')",
            (owner,),
        ).fetchone()["usd"]
        == HOLD * 2
    )


def test_unknown_prior_utc_month_hold_is_retained_without_consuming_new_window(
    db_conn, owner_enrollments
):
    from db.connection import table

    owner, enrollments = owner_enrollments
    old = _start(_admitted(owner, enrollments[0]))
    previous_window = db_conn.execute(
        "SELECT (date_trunc('month', clock_timestamp() AT TIME ZONE 'UTC') "
        "AT TIME ZONE 'UTC') - interval '1 second' AS t"
    ).fetchone()["t"]
    # Explicit timestamp fixture through the adapter, not a provider clock or
    # measured bill. The uncertain exposure is never deleted or refunded.
    table("checklist_budget_reservations").update(
        {
            "created_at": previous_window.isoformat(),
            "dispatch_at": previous_window.isoformat(),
            "expires_at": previous_window.isoformat(),
        },
        {"operation_id": f"eq.{old['operation_id']}"},
    )
    newer = _admitted(owner, enrollments[0], daily=".08", monthly=".08", tokens=HOLD_TOKENS)
    persisted = _db_row(db_conn, old)
    assert persisted["state"] == "unknown" and persisted["held_usd"] == HOLD
    assert persisted["dispatch_at"] == previous_window
    assert _db_row(db_conn, newer)["state"] == "prepared"


def test_strict_settlement_and_replay_have_one_bill_and_one_cache(db_conn, owner_enrollments):
    owner, enrollments = owner_enrollments
    row = _start(_admitted(owner, enrollments[0]))
    receipt, content = _receipt(row), _content("initial")
    first = _reconcile(row, receipt=receipt, content=content)
    assert first["status"] == "settled" and first["reservation"]["cache_published"] is True
    replay = _reconcile(row, receipt=receipt, content=_content("must not republish"))
    assert replay == first
    bill = db_conn.execute(
        "SELECT * FROM llm_usage WHERE id = %s", (receipt.receipt_id,)
    ).fetchone()
    assert bill["cost_usd"] == Decimal(str(receipt.to_row()["cost_usd"]))
    assert bill["created_at"] == datetime.fromisoformat(row["dispatch_at"])
    assert (bill["cached_tokens"], bill["thinking_tokens"]) == (200, 10)
    assert (
        db_conn.execute(
            "SELECT count(*) AS n FROM llm_usage WHERE user_id = %s", (owner,)
        ).fetchone()["n"]
        == 1
    )
    cache = db_conn.execute(
        "SELECT input_hash, content FROM topic_checklists WHERE enrollment_id = %s",
        (enrollments[0],),
    ).fetchone()
    assert cache == {"input_hash": row["input_hash"], "content": content}
    assert _db_row(db_conn, row)["fingerprint"] == receipt.fingerprint


def test_changed_settled_receipt_and_foreign_owner_never_reconcile(
    db_conn, owner_enrollments, seeded_user
):
    from db.connection import rpc

    owner, enrollments = owner_enrollments
    row = _start(_admitted(owner, enrollments[0]))
    receipt = _receipt(row)
    assert _reconcile(row, receipt=receipt)["status"] == "settled"
    changed = receipt.to_row()
    changed["completion_tokens"] += 1
    result = rpc(
        "checklist_budget_reconcile",
        {
            **_identity(row),
            "p_action": "settle",
            "p_receipt": changed,
            "p_fingerprint": "f" * 64,
            "p_content": _content("rejected"),
        },
    )
    assert result["status"] == "conflict"
    foreign = {**_identity(row), "p_user_id": seeded_user()}
    assert (
        rpc("checklist_budget_reconcile", {**foreign, "p_action": "no_dispatch"})["status"]
        == "conflict"
    )
    assert (
        rpc("checklist_budget_read", {k: v for k, v in foreign.items() if k != "p_fence"}) is None
    )
    assert _db_row(db_conn, row)["receipt"] == receipt.to_row()


def test_duplicate_bill_with_different_content_rolls_back_settlement(db_conn, owner_enrollments):
    from db.connection import table

    owner, enrollments = owner_enrollments
    row = _start(_admitted(owner, enrollments[0]))
    receipt = _receipt(row)
    conflicting = receipt.to_row()
    conflicting["request_id"] = "different-original-receipt"
    table("llm_usage").insert(conflicting)
    with pytest.raises(httpx.HTTPStatusError):
        _reconcile(row, receipt=receipt, content=_content("must not persist"))
    assert _db_row(db_conn, row)["state"] == "started"
    assert _db_row(db_conn, row)["receipt"] is None
    assert (
        db_conn.execute(
            "SELECT request_id FROM llm_usage WHERE id = %s", (receipt.receipt_id,)
        ).fetchone()["request_id"]
        == "different-original-receipt"
    )
    assert (
        db_conn.execute(
            "SELECT count(*) AS n FROM topic_checklists WHERE enrollment_id = %s", (enrollments[0],)
        ).fetchone()["n"]
        == 0
    )


def test_cache_write_error_atomically_rolls_back_new_bill_and_settlement(
    db_conn, owner_enrollments
):
    """Test-only DDL injects a cache fault; the actual business write is one RPC."""
    from psycopg import sql

    owner, enrollments = owner_enrollments
    row = _start(_admitted(owner, enrollments[0]))
    receipt = _receipt(row)
    name = "it_checklist_reject_" + uuid4().hex
    ident = sql.Identifier(name)
    try:
        db_conn.execute(
            sql.SQL(
                "CREATE FUNCTION public.{}() RETURNS trigger LANGUAGE plpgsql AS $$ "
                "BEGIN RAISE EXCEPTION 'intentional integration cache failure'; END $$"
            ).format(ident)
        )
        db_conn.execute(
            sql.SQL(
                "CREATE TRIGGER {} BEFORE INSERT OR UPDATE ON topic_checklists "
                "FOR EACH ROW WHEN (NEW.enrollment_id = {}) EXECUTE FUNCTION public.{}()"
            ).format(ident, sql.Literal(enrollments[0]), ident)
        )
        with pytest.raises(httpx.HTTPStatusError):
            _reconcile(row, receipt=receipt, content=_content("rejected by test trigger"))
        assert (
            db_conn.execute(
                "SELECT count(*) AS n FROM llm_usage WHERE id = %s", (receipt.receipt_id,)
            ).fetchone()["n"]
            == 0
        )
        persisted = _db_row(db_conn, row)
        assert (persisted["state"], persisted["receipt"], persisted["cache_published"]) == (
            "started",
            None,
            False,
        )
        assert (
            db_conn.execute(
                "SELECT count(*) AS n FROM topic_checklists WHERE enrollment_id = %s",
                (enrollments[0],),
            ).fetchone()["n"]
            == 0
        )
    finally:
        db_conn.execute(sql.SQL("DROP TRIGGER IF EXISTS {} ON topic_checklists").format(ident))
        db_conn.execute(sql.SQL("DROP FUNCTION IF EXISTS public.{}()").format(ident))
    # No new identity/retry bypass: exactly the same receipt can now settle.
    assert _reconcile(row, receipt=receipt)["status"] == "settled"


def test_late_old_result_settles_but_cannot_overwrite_newer_cache(db_conn, owner_enrollments):
    owner, enrollments = owner_enrollments
    old = _start(_admitted(owner, enrollments[0]))
    _expire(db_conn, old)
    newer = _start(_admitted(owner, enrollments[0]))
    new_content = _content("newer")
    assert _reconcile(newer, receipt=_receipt(newer), content=new_content)["reservation"][
        "cache_published"
    ]
    old_settled = _reconcile(old, receipt=_receipt(old), content=_content("late old"))
    assert old_settled["status"] == "settled"
    assert old_settled["reservation"]["cache_published"] is False
    assert (
        db_conn.execute(
            "SELECT content FROM topic_checklists WHERE enrollment_id = %s", (enrollments[0],)
        ).fetchone()["content"]
        == new_content
    )
    assert (
        db_conn.execute(
            "SELECT count(*) AS n FROM llm_usage WHERE user_id = %s", (owner,)
        ).fetchone()["n"]
        == 2
    )


def test_deleting_owner_or_enrollment_does_not_erase_a_started_bill(db_conn, owner_enrollments):
    from db.connection import table

    owner, enrollments = owner_enrollments
    row = _start(_admitted(owner, enrollments[0]))
    table("enrollments").delete({"user_id": f"eq.{owner}"})
    table("users").delete({"id": f"eq.{owner}"})
    receipt = _receipt(row)
    result = _reconcile(row, receipt=receipt, content=_content("no deleted owner cache"))
    assert result["status"] == "settled" and result["reservation"]["cache_published"] is False
    assert (
        db_conn.execute(
            "SELECT user_id FROM llm_usage WHERE id = %s", (receipt.receipt_id,)
        ).fetchone()["user_id"]
        == owner
    )
    assert _db_row(db_conn, row)["state"] == "settled"


def test_unknown_legacy_price_denies_admission_and_start_without_zero_fallback(
    db_conn, owner_enrollments
):
    from db.connection import rpc, table

    owner, enrollments = owner_enrollments
    prepared = _admitted(owner, enrollments[0])
    table("llm_usage").insert(_usage_row(owner, cost=None, created_at=_now(db_conn)))
    assert _admit(owner, enrollments[1])[0]["status"] == "usage_unavailable"
    assert rpc("checklist_budget_start", _identity(prepared))["status"] == "usage_unavailable"
    persisted = _db_row(db_conn, prepared)
    assert (persisted["state"], persisted["dispatch_at"], persisted["reason"]) == (
        "released",
        None,
        "usage_unavailable",
    )


@pytest.mark.parametrize(
    "tight,expected",
    [
        ({"daily": ".08"}, (Decimal(".08"), Decimal("2"), 400_000)),
        ({"monthly": ".08"}, (Decimal(".20"), Decimal(".08"), 400_000)),
        ({"tokens": HOLD_TOKENS}, (Decimal(".20"), Decimal("2"), HOLD_TOKENS)),
    ],
)
def test_stale_looser_worker_cannot_raise_a_tightened_cap(
    db_conn, owner_enrollments, tight, expected
):
    owner, enrollments = owner_enrollments
    _admitted(owner, enrollments[0], **tight)
    assert (
        _admit(owner, enrollments[1], daily="100", monthly="1000", tokens=9_000_000)[0]["status"]
        == "denied"
    )
    account = db_conn.execute(
        "SELECT daily_usd,monthly_usd,daily_tokens FROM checklist_budget_accounts WHERE user_id = %s",
        (owner,),
    ).fetchone()
    assert tuple(account.values()) == expected


@pytest.mark.parametrize("change", ["ledger", "policy"])
def test_prepared_hold_revalidates_new_spend_or_tighter_policy_before_dispatch(
    db_conn, owner_enrollments, change
):
    from db.connection import rpc, table

    owner, enrollments = owner_enrollments
    prepared = _admitted(owner, enrollments[0])
    if change == "ledger":
        table("llm_usage").insert(_usage_row(owner, created_at=_now(db_conn)))
    else:
        table("checklist_budget_accounts").update({"daily_usd": ".05"}, {"user_id": f"eq.{owner}"})
    assert rpc("checklist_budget_start", _identity(prepared))["status"] == "denied"
    persisted = _db_row(db_conn, prepared)
    assert (persisted["state"], persisted["reason"], persisted["dispatch_at"]) == (
        "released",
        "capacity_changed",
        None,
    )


def test_exact_cached_input_remains_free_even_after_account_is_blocked(db_conn, owner_enrollments):
    from db.connection import table

    owner, enrollments = owner_enrollments
    first, params = _admit(owner, enrollments[0])
    prepared = first["reservation"]
    assert (
        _reconcile(prepared, action="no_dispatch", content=_content("local test cache"))["status"]
        == "released"
    )
    table("checklist_budget_accounts").update({"blocked": True}, {"user_id": f"eq.{owner}"})
    operation = uuid4()
    next_params = {
        **params,
        "p_operation_id": str(operation),
        "p_receipt_id": str(uuid5(NAMESPACE_URL, f"sapling:checklist-receipt:{operation}")),
    }
    assert _admit(owner, enrollments[0], params=next_params)[0]["status"] == "cached"
    assert (
        db_conn.execute(
            "SELECT count(*) AS n FROM checklist_budget_reservations WHERE user_id = %s", (owner,)
        ).fetchone()["n"]
        == 1
    )


@pytest.mark.parametrize("role", ["anon", "authenticated"])
def test_client_roles_cannot_read_or_execute_budget_authority(db_conn, role):
    import psycopg
    from psycopg import sql

    for signature in FUNCTIONS:
        assert (
            db_conn.execute(
                "SELECT has_function_privilege(%s, %s, 'EXECUTE') AS allowed", (role, signature)
            ).fetchone()["allowed"]
            is False
        )
    try:
        db_conn.execute(sql.SQL("SET ROLE {}").format(sql.Identifier(role)))
        for name in ("checklist_budget_accounts", "checklist_budget_reservations"):
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                db_conn.execute(sql.SQL("SELECT * FROM {} LIMIT 1").format(sql.Identifier(name)))
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            db_conn.execute("SELECT checklist_budget_start('not-an-owner', %s, 1)", (uuid4(),))
    finally:
        db_conn.execute("RESET ROLE")


def test_service_role_has_required_budget_grants_and_rls_is_enabled(db_conn):
    for signature in FUNCTIONS:
        row = db_conn.execute(
            "SELECT has_function_privilege('service_role', %s, 'EXECUTE') AS allowed, "
            "p.prosecdef FROM pg_proc p WHERE p.oid = %s::regprocedure",
            (signature, signature),
        ).fetchone()
        assert row == {"allowed": True, "prosecdef": False}
    for name in ("checklist_budget_accounts", "checklist_budget_reservations"):
        row = db_conn.execute(
            "SELECT relrowsecurity FROM pg_class WHERE oid = %s::regclass", (name,)
        ).fetchone()
        assert row["relrowsecurity"] is True
        for grant in ("SELECT", "INSERT", "UPDATE"):
            assert (
                db_conn.execute(
                    "SELECT has_table_privilege('service_role', %s, %s) AS allowed", (name, grant)
                ).fetchone()["allowed"]
                is True
            )

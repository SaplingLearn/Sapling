"""
#248: the backend-wide datetime.utcnow() sweep.

Every timestamp the backend stamps itself is now `datetime.now(timezone.utc)`
— tz-aware UTC, so `.isoformat()` carries an explicit `+00:00` offset instead
of a naive string. All the swept columns are TIMESTAMPTZ (0001/0025), and the
frontend parses them with `new Date(...)` (which treats a *naive* ISO string
as local time, so the aware form is strictly more correct there).

One parameterized test pins a representative write per swept service; two
focused tests pin the read-side arithmetic that must stay robust to BOTH
shapes found in the wild — tz-aware strings (timestamptz reads via PostgREST,
and every post-sweep write) and legacy naive strings (pre-sweep utcnow()
writes, which are UTC by construction).
"""
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest


# ── Representative writes: one per swept service ─────────────────────────────

def _upsert_payload(table_mock):
    return table_mock.return_value.upsert.call_args[0][0]


def _insert_payload(table_mock):
    return table_mock.return_value.insert.call_args[0][0]


def _do_quiz_context_write():
    from services.quiz_context_service import save_quiz_context
    save_quiz_context("u1", "node-1", {"weak_areas": []})


def _do_social_cache_write():
    from services.social_cache_service import save_summary
    save_summary("room-1", ["member summary"], "cached summary")


def _do_learn_message_write():
    from routes.learn import save_message
    save_message("sess-1", "user", "hello")


@pytest.mark.parametrize(
    "patch_target,invoke,extract,field",
    [
        (
            "services.quiz_context_service.table",
            _do_quiz_context_write,
            _upsert_payload,
            "updated_at",
        ),
        (
            "services.social_cache_service.table",
            _do_social_cache_write,
            _upsert_payload,
            "updated_at",
        ),
        (
            "routes.learn.table",
            _do_learn_message_write,
            _insert_payload,
            "created_at",
        ),
    ],
    ids=["quiz_context.updated_at", "social_cache.updated_at", "messages.created_at"],
)
def test_representative_writes_stamp_tz_aware_utc(patch_target, invoke, extract, field):
    with patch(patch_target) as table_mock:
        invoke()
    ts = extract(table_mock)[field]
    dt = datetime.fromisoformat(ts)
    assert dt.tzinfo is not None, f"{field} was written naive: {ts!r}"
    assert dt.utcoffset() == timedelta(0), f"{field} not UTC: {ts!r}"


# ── Read-side arithmetic must accept aware AND legacy-naive strings ──────────

def test_elapsed_minutes_handles_aware_and_legacy_naive_started_at():
    """routes/learn.py end_session: sessions.started_at is TIMESTAMPTZ, so
    PostgREST reads come back tz-aware — the old `utcnow() - fromisoformat(...)`
    raised TypeError on them and silently reported 0 minutes. Legacy naive
    strings are UTC by construction and must keep working too."""
    from routes.learn import _elapsed_minutes

    half_hour_ago = datetime.now(timezone.utc) - timedelta(minutes=30)
    assert _elapsed_minutes(half_hour_ago.isoformat()) == 30
    assert _elapsed_minutes(half_hour_ago.replace(tzinfo=None).isoformat()) == 30
    assert _elapsed_minutes("not-a-timestamp") == 0


def test_compute_velocity_counts_aware_naive_and_z_suffixed_events():
    """services/graph_service._compute_velocity must count mastery events no
    matter which of the three timestamp shapes the row carries."""
    from services.graph_service import _compute_velocity

    two_days_ago = datetime.now(timezone.utc) - timedelta(days=2)
    events = [
        {"delta": 0.2, "created_at": two_days_ago.isoformat()},  # aware +00:00
        {  # legacy naive UTC (pre-#248 write)
            "delta": 0.1,
            "created_at": two_days_ago.replace(tzinfo=None).isoformat(),
        },
        {  # Z-suffixed
            "delta": 0.1,
            "created_at": two_days_ago.strftime("%Y-%m-%dT%H:%M:%S") + "Z",
        },
    ]
    velocity = _compute_velocity(events)
    # All three deltas counted: 0.4 mastery over the 2 days since the first event.
    assert velocity == pytest.approx(0.4 / 2, abs=1e-3)

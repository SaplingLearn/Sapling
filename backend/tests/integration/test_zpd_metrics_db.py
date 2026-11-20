"""PKG-14 review round, real-DB half of scripts/derive_zpd_metrics.py: the
evidence read filters to opportunities (question_hash not null) BEFORE the
limit, newest first — a MagicMock suite sees the filter dict, not whether
PostgREST applies it before `limit`."""

import uuid
from datetime import datetime, timedelta, timezone

import pytest

pytestmark = pytest.mark.integration

USER = "rich-user-active"


def _node(db_conn) -> str:
    row = db_conn.execute(
        "SELECT id FROM graph_nodes WHERE user_id = %s ORDER BY id LIMIT 1", (USER,)
    ).fetchone()
    if row is None:
        pytest.fail("rich seed has no graph node for the active user")
    return row["id"]


def test_derive_zpd_metrics_evidence_filter_and_limit_real_sql(db_conn):
    from learning.params import BAND_WINDOW, HTC_K_WINDOW
    from scripts import derive_zpd_metrics

    node = _node(db_conn)
    limit = max(BAND_WINDOW, HTC_K_WINDOW)
    base = datetime(2026, 9, 1, tzinfo=timezone.utc)
    tag = uuid.uuid4().hex[:8]
    db_conn.execute("DELETE FROM node_mastery_events WHERE node_id = %s", (node,))
    # older opportunities, then MORE than `limit` newer non-opportunity rows
    for i in range(limit + 2):
        db_conn.execute(
            "INSERT INTO node_mastery_events (node_id, delta, event_type, correct, "
            "question_hash, created_at) VALUES (%s, 0, 'evidence', true, %s, %s)",
            (node, f"{tag}-q{i}", base + timedelta(minutes=i)),
        )
    for i in range(limit + 3):
        db_conn.execute(
            "INSERT INTO node_mastery_events (node_id, delta, event_type, correct, "
            "question_hash, created_at) VALUES (%s, 0, 'evidence', true, NULL, %s)",
            (node, base + timedelta(days=1, minutes=i)),
        )
    db_conn.execute(
        "INSERT INTO node_mastery_events (node_id, delta, event_type, question_hash, created_at) "
        "VALUES (%s, 0, 'mastery', %s, %s)",
        (node, f"{tag}-other", base + timedelta(days=2)),
    )
    rows = derive_zpd_metrics._evidence(node)
    assert len(rows) == limit
    assert all(r["question_hash"] for r in rows)
    # newest opportunities first
    assert [r["question_hash"] for r in rows] == [f"{tag}-q{i}" for i in range(limit + 1, 1, -1)]

"""Spec §13 A136, real-DB half: every float the backend reads through PostgREST
is exact, against the local stack (the Supabase image, extra_float_digits = 0
in its postgresql.conf) after migration 20261108162223_learning_exact_floats.sql.

- the role setting is stored on service_role, and PostgREST applies it to the
  backend's requests: the probe's float8, real and jsonb float read back
  exactly through db.connection.rpc, the backend's own path;
- a graded history's learner_state (17-digit BKT/FSRS doubles) reads back
  through the backend's ordinary table() read bit for bit as stored;
- a real column (documents.shareability_confidence) written and read through
  the backend round-trips as the same single;
- the release fence's probe (scripts/learning_release_verify.py
  --rest-float-probe) passes against this stack.

Writes go through the app; the ground truth is read over psycopg in BINARY
format, which is exact whatever the session's extra_float_digits (#397). Run
inside the flock'd local-stack cycle with RUN_INTEGRATION=1."""

from __future__ import annotations

import os
import struct
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.integration.conftest import COURSE_CS, USER_ACTIVE
from tests.integration.test_learning_goals_db import _node

pytestmark = pytest.mark.integration

FLOAT8 = 0.1 + 0.2  # 0.30000000000000004
FLOAT4 = 0.12345679
T0 = datetime.now(timezone.utc).replace(microsecond=0) - timedelta(days=40)


def _single(value: float) -> bytes:
    return struct.pack("<f", value)


def _rounded_at_15(value: float) -> bool:
    return float(f"{value:.15g}") != value


def _binary(db_conn, sql: str, params: tuple) -> dict:
    """Ground truth: binary transfer carries the stored bits, not text."""
    return db_conn.execute(sql, params, binary=True).fetchone()


def test_the_setting_is_on_the_backends_roles_and_only_there(db_conn):
    # service_role (A136) and authenticated, the role a db_user_scope request
    # runs as (A148); never the anonymous or the login role
    for role in ("service_role", "authenticated"):
        row = db_conn.execute("SELECT rolconfig FROM pg_roles WHERE rolname = %s", (role,)).fetchone()
        assert "extra_float_digits=3" in (row["rolconfig"] or []), role
    for other in ("anon", "authenticator"):
        config = db_conn.execute(
            "SELECT rolconfig FROM pg_roles WHERE rolname = %s", (other,)
        ).fetchone()
        assert not any(c.startswith("extra_float_digits=") for c in (config or {}).get("rolconfig") or [])


def test_the_backends_rpc_path_reads_the_probe_exactly(db_conn):
    from db.connection import rpc

    [row] = rpc("learning_float_probe", {})
    assert row["float8_value"].hex() == FLOAT8.hex()
    assert _single(row["float4_value"]) == _single(FLOAT4)
    assert row["jsonb_value"].hex() == FLOAT8.hex()
    assert row["digits"] == "3"
    # the control: on this stack a connection without the setting rounds
    server = db_conn.execute("SHOW extra_float_digits").fetchone()["extra_float_digits"]
    if int(server) <= 0:
        text = db_conn.execute("SELECT float8_value FROM learning_float_probe()").fetchone()
        assert text["float8_value"] == 0.3


def test_a_graded_learner_state_reads_back_bit_for_bit_through_table(db_conn):
    from db.connection import table
    from services.graph_service import apply_graph_update

    node = _node("Exact floats", owner=USER_ACTIVE)
    for hours, correct in ((1, True), (30, False), (80, True), (200, True)):
        apply_graph_update(USER_ACTIVE, {"evidence": [{
            "node_id": node, "channel": "free_response", "correct": correct,
            "session_id": f"it-floats-{uuid.uuid4().hex[:8]}",
            "question_hash": f"it-floats-{hours}", "check_item_id": f"ci-it-floats-{hours}",
            "observed_at": (T0 + timedelta(hours=hours)).isoformat(),
        }]}, COURSE_CS)
    columns = ("p_known", "fsrs_d", "fsrs_s")
    stored = _binary(
        db_conn,
        f"SELECT {','.join(columns)} FROM learner_state WHERE user_id = %s AND node_id = %s",
        (USER_ACTIVE, node),
    )
    [read] = table("learner_state").select(
        ",".join(columns), filters={"user_id": f"eq.{USER_ACTIVE}", "node_id": f"eq.{node}"}
    )
    assert any(_rounded_at_15(stored[c]) for c in columns), stored  # the case 15 digits loses
    for column in columns:
        assert read[column].hex() == stored[column].hex(), column
    [mirror] = table("graph_nodes").select("mastery_score", filters={"id": f"eq.{node}"})
    truth = _binary(db_conn, "SELECT mastery_score FROM graph_nodes WHERE id = %s", (node,))
    assert mirror["mastery_score"].hex() == truth["mastery_score"].hex()


def test_a_real_column_round_trips_as_the_same_single(db_conn):
    from db.connection import table
    from db.seed_local_rich import LOOP_DOC_ID

    [written] = table("documents").update(
        {"shareability_confidence": FLOAT4}, {"id": f"eq.{LOOP_DOC_ID}"}
    )
    assert _single(written["shareability_confidence"]) == _single(FLOAT4)
    [read] = table("documents").select("shareability_confidence", filters={"id": f"eq.{LOOP_DOC_ID}"})
    stored = _binary(db_conn, "SELECT shareability_confidence FROM documents WHERE id = %s", (LOOP_DOC_ID,))
    assert _single(read["shareability_confidence"]) == _single(stored["shareability_confidence"])
    assert _single(stored["shareability_confidence"]) == _single(FLOAT4)
    assert read["shareability_confidence"] != float(f"{FLOAT4:.6g}")  # not the 6-digit text


def test_the_release_fence_probe_passes_on_this_stack():
    saved = list(sys.path)
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
    try:
        import learning_release_verify as verify
    finally:
        sys.path[:] = saved
    host = verify.urlsplit(os.environ["SUPABASE_URL"]).hostname
    result = verify.rest_float_audit(SimpleNamespace(
        rest_url_env="SUPABASE_URL", rest_key_env="SUPABASE_SERVICE_KEY",
        expected_rest_host=host, allow_loopback_http=True, timeout=10,
    ))
    assert result["status"] == "passed", result
    assert result["extra_float_digits"] == "3"

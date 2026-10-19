"""Actual RPC commit/rollback, versions, replay and concurrent mixed evidence.

The local integration safety fixture owns infrastructure. Application adapters
perform all grade writes; independent SQL reads assert the committed result.
No models, synthetic learner transcripts or out-of-band mastery edits.
"""

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import threading
import uuid

import httpx
import pytest

from tests.integration.conftest import COURSE_CS, USER_ACTIVE, USER_SECOND
from tests.integration.test_learning_goals_db import _node

pytestmark = pytest.mark.integration


def evidence(node, *, operation=None, tagged=True, **changes):
    key = uuid.uuid4().hex
    value = {
        "node_id": node,
        "channel": "free_response",
        "correct": True,
        "session_id": "atomic-integration-session",
        "question_hash": hashlib.sha256(key.encode()).hexdigest(),
        "check_item_id": f"atomic-{key}",
        "operation_id": operation or str(uuid.uuid4()),
        **changes,
    }
    if tagged:
        value["planning_provenance"] = {
            "check_item_id": value["check_item_id"],
            "difficulty": 2,
            "synthetic_idk": False,
            "previously_seen": False,
        }
    return value


def apply(value, *, owner=USER_ACTIVE):
    from services.graph_service import apply_graph_update

    return apply_graph_update(owner, {"evidence": [value]}, COURSE_CS)


def state(db_conn, node):
    return db_conn.execute(
        "SELECT * FROM learner_state WHERE user_id=%s AND node_id=%s", (USER_ACTIVE, node)
    ).fetchone()


def journal(db_conn, node):
    return db_conn.execute(
        "SELECT * FROM node_mastery_events WHERE node_id=%s ORDER BY created_at,evidence_seq,id",
        (node,),
    ).fetchall()


def test_real_atomic_batch_commits_canonical_math_and_receipt_then_replays_once(db_conn):
    from learning import bkt
    from learning.params import BKT_L0
    from learning.evidence_transaction import read_receipt

    node = _node("Atomic roundtrip")
    value = evidence(node)
    first = apply(value)
    assert state(db_conn, node)["p_known"] == pytest.approx(
        bkt.update(BKT_L0, "free_response", True)
    )
    assert len(journal(db_conn, node)) == 1
    receipt = read_receipt(USER_ACTIVE, value["operation_id"])
    assert receipt["posteriors"][node] == first[0]["after"]
    apply(evidence(node, tagged=False, correct=False))
    current = state(db_conn, node)
    assert apply(value) == first
    assert state(db_conn, node) == current and len(journal(db_conn, node)) == 2
    assert journal(db_conn, node)[0]["planning_observation"]["independent"] is True
    assert journal(db_conn, node)[1]["planning_observation"] is None


def test_lost_postcommit_ack_replays_same_payload_without_duplicate_bkt(db_conn, monkeypatch):
    from learning import evidence_transaction as tx

    node = _node("Atomic lost ack")
    value = evidence(node)
    real = tx.rpc
    calls = []

    def rpc(name, args):
        result = real(name, args)
        if name == "learning_evidence_commit":
            calls.append(deepcopy(args))
            if len(calls) == 1:
                raise httpx.ReadTimeout("synthetic lost acknowledgment after actual commit")
        return result

    monkeypatch.setattr(tx, "rpc", rpc)
    assert apply(value)
    assert len(calls) == 2 and calls[0] == calls[1]
    assert state(db_conn, node)["opps"] == 1 and len(journal(db_conn, node)) == 1


def test_journal_constraint_failure_rolls_back_scalar_mirror_and_propagation(db_conn, monkeypatch):
    from db.connection import table
    from learning import evidence_transaction as tx
    from learning.evidence import PlanningPersistenceUnavailable

    parent, child = _node("Atomic rollback parent"), _node("Atomic rollback child")
    table("graph_edges").insert(
        {
            "user_id": USER_ACTIVE,
            "source_node_id": parent,
            "target_node_id": child,
            "relationship_type": "prerequisite",
        }
    )
    before = db_conn.execute(
        "SELECT id,mastery_score,times_studied,evidence_version FROM graph_nodes WHERE id=ANY(%s) ORDER BY id",
        ([parent, child],),
    ).fetchall()
    real = tx.rpc

    def rpc(name, args):
        if name == "learning_evidence_commit":
            args = deepcopy(args)
            # Existing DB CHECK, not a production fault flag. Failure occurs
            # after the SQL has attempted scalar writes; all must roll back.
            args["p_plan"]["events"][0]["grader_backend"] = "invalid-integration-backend"
        return real(name, args)

    monkeypatch.setattr(tx, "rpc", rpc)
    with pytest.raises(PlanningPersistenceUnavailable):
        apply(evidence(child))
    assert state(db_conn, parent) is None and state(db_conn, child) is None
    assert journal(db_conn, parent) == journal(db_conn, child) == []
    after = db_conn.execute(
        "SELECT id,mastery_score,times_studied,evidence_version FROM graph_nodes WHERE id=ANY(%s) ORDER BY id",
        ([parent, child],),
    ).fetchall()
    assert after == before
    assert (
        db_conn.execute(
            "SELECT count(*) n FROM learning_evidence_operations WHERE user_id=%s", (USER_ACTIVE,)
        ).fetchone()["n"]
        == 0
    )


def test_cross_worker_tagged_and_legacy_batches_cannot_lose_an_update(db_conn, monkeypatch):
    from learning import bkt, evidence_transaction as tx
    from learning.params import BKT_L0

    node = _node("Atomic concurrent legacy")
    values = [evidence(node, tagged=True), evidence(node, tagged=False)]
    barrier = threading.Barrier(2)
    seen = set()
    lock = threading.Lock()
    real = tx.rpc

    def rpc(name, args):
        result = real(name, args)
        if name == "learning_evidence_snapshot":
            tid = threading.get_ident()
            with lock:
                first = tid not in seen
                seen.add(tid)
            if first:
                barrier.wait(timeout=5)
        return result

    monkeypatch.setattr(tx, "rpc", rpc)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(apply, values))
    assert all(results)
    expected = bkt.update(bkt.update(BKT_L0, "free_response", True), "free_response", True)
    assert state(db_conn, node)["p_known"] == pytest.approx(expected, abs=1e-6)
    assert state(db_conn, node)["opps"] == 2 and len(journal(db_conn, node)) == 2
    assert (
        db_conn.execute("SELECT times_studied FROM graph_nodes WHERE id=%s", (node,)).fetchone()[
            "times_studied"
        ]
        == 2
    )


def test_legacy_topology_change_between_snapshot_and_commit_forces_replanning(db_conn, monkeypatch):
    from learning import evidence_transaction as tx
    from services.graph_service import apply_graph_update

    parent, child = _node("Atomic topology parent"), _node("Atomic topology child")
    real = tx.rpc
    snapshots = []

    def rpc(name, args):
        result = real(name, args)
        if name == "learning_evidence_snapshot":
            snapshots.append(result)
            if len(snapshots) == 1:
                apply_graph_update(
                    USER_ACTIVE,
                    {
                        "new_edges": [
                            {
                                "source": "Atomic topology parent",
                                "target": "Atomic topology child",
                                "relationship_type": "prerequisite",
                            }
                        ]
                    },
                    COURSE_CS,
                )
        return result

    monkeypatch.setattr(tx, "rpc", rpc)
    apply(evidence(child))
    assert len(snapshots) == 2
    assert state(db_conn, parent) is not None and state(db_conn, child) is not None
    assert journal(db_conn, parent) == [] and len(journal(db_conn, child)) == 1


def test_explicit_older_uncommitted_grade_is_rejected_but_completed_receipt_recovers(db_conn):
    from learning.evidence_transaction import EvidenceObservationSuperseded

    node = _node("Atomic grade ordering")
    now = datetime.now(timezone.utc)
    first = evidence(node, observed_at=now)
    result = apply(first)
    stale = evidence(node, observed_at=now - timedelta(seconds=1), correct=False)
    with pytest.raises(EvidenceObservationSuperseded):
        apply(stale)
    assert len(journal(db_conn, node)) == 1
    newer = evidence(node, observed_at=now + timedelta(seconds=1))
    apply(newer)
    before = state(db_conn, node)
    assert apply(first) == result and state(db_conn, node) == before


def test_rpc_ownership_and_permissions_prevent_partial_foreign_batch(db_conn):
    from db.connection import rpc
    from learning.evidence import PlanningPersistenceUnavailable

    mine, foreign = _node("Atomic owned"), _node("Atomic foreign", owner=USER_SECOND)
    from services.graph_service import apply_graph_update

    with pytest.raises(PlanningPersistenceUnavailable):
        apply_graph_update(
            USER_ACTIVE, {"evidence": [evidence(mine), evidence(foreign)]}, COURSE_CS
        )
    assert state(db_conn, mine) is None and journal(db_conn, mine) == []
    assert (
        rpc(
            "learning_evidence_receipt",
            {"p_user_id": USER_SECOND, "p_operation_id": str(uuid.uuid4())},
        )["status"]
        == "missing"
    )
    for role in ("anon", "authenticated"):
        if db_conn.execute("SELECT 1 FROM pg_roles WHERE rolname=%s", (role,)).fetchone():
            for signature in (
                "learning_evidence_receipt(text,uuid)",
                "learning_evidence_snapshot(text,text,text[],jsonb)",
                "learning_evidence_commit(text,text,uuid,text,jsonb)",
            ):
                assert not db_conn.execute(
                    "SELECT has_function_privilege(%s,%s,'EXECUTE') ok", (role, signature)
                ).fetchone()["ok"]


def test_concurrent_derived_metrics_force_cas_retry_and_are_preserved(db_conn, monkeypatch):
    from learning import evidence_transaction as tx
    from learning.learner_state import write_metrics

    node = _node("Atomic derived metrics")
    apply(evidence(node))
    real = tx.rpc
    snapshots = []

    def rpc(name, args):
        result = real(name, args)
        if name == "learning_evidence_snapshot":
            snapshots.append(result)
            if len(snapshots) == 1:
                write_metrics(
                    USER_ACTIVE, node, htc_k=0.4, unassisted_next=0.8, assist_gap=0.2, in_zone=True
                )
        return result

    monkeypatch.setattr(tx, "rpc", rpc)
    apply(evidence(node))
    assert len(snapshots) == 2
    actual = state(db_conn, node)
    assert actual["htc_k"] == 0.4 and actual["unassisted_next"] == 0.8
    assert actual["assist_gap"] == 0.2 and actual["in_zone"] is True
    assert actual["opps"] == 2


def test_native_snapshot_and_commit_cover_more_than_postgrest_row_limit(db_conn):
    from db.connection import table

    child = _node("Atomic large adjacency")
    parents = [str(uuid.uuid4()) for _ in range(1005)]
    # Synthetic pre-activity graph assets; grade writes still use the real app.
    table("graph_nodes").insert(
        [
            {
                "id": node,
                "user_id": USER_ACTIVE,
                "course_id": COURSE_CS,
                "concept_name": f"Atomic large parent {i}",
            }
            for i, node in enumerate(parents)
        ]
    )
    table("graph_edges").insert(
        [
            {
                "user_id": USER_ACTIVE,
                "source_node_id": node,
                "target_node_id": child,
                "relationship_type": "prerequisite",
            }
            for node in parents
        ]
    )
    apply(evidence(child))
    count = db_conn.execute(
        "SELECT count(*) n FROM learner_state WHERE user_id=%s AND node_id=ANY(%s)",
        (USER_ACTIVE, parents + [child]),
    ).fetchone()["n"]
    assert count == len(parents) + 1
    assert len(journal(db_conn, child)) == 1


def test_legacy_edge_table_writer_contention_is_bounded_and_retries_without_partial_state(
    db_conn, monkeypatch
):
    from learning import evidence_transaction as tx

    node = _node("Atomic bounded topology lock")
    real = tx.rpc
    failures = []
    db_conn.execute("BEGIN")
    db_conn.execute("LOCK TABLE graph_edges IN ROW EXCLUSIVE MODE")

    def rpc(name, args):
        try:
            return real(name, args)
        except httpx.HTTPStatusError as exc:
            if name == "learning_evidence_commit" and exc.response.json().get("code") == "55P03":
                failures.append(1)
                assert state(db_conn, node) is None and journal(db_conn, node) == []
                db_conn.execute("COMMIT")
            raise

    monkeypatch.setattr(tx, "rpc", rpc)
    try:
        assert apply(evidence(node))
    finally:
        if db_conn.info.transaction_status:
            db_conn.execute("ROLLBACK")
    assert (
        failures == [1] and state(db_conn, node)["opps"] == 1 and len(journal(db_conn, node)) == 1
    )

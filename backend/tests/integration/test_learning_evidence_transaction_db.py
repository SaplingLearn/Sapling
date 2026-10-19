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
    rejected = []

    def rpc(name, args):
        if name == "learning_evidence_commit":
            args = deepcopy(args)
            # Existing DB CHECK, not a production fault flag. Failure occurs
            # after the SQL has attempted scalar writes; all must roll back.
            args["p_plan"]["events"][0]["grader_backend"] = "invalid-integration-backend"
        try:
            return real(name, args)
        except httpx.HTTPStatusError as exc:
            if name == "learning_evidence_commit":
                rejected.append(exc.response.json().get("code"))
            raise

    monkeypatch.setattr(tx, "rpc", rpc)
    with pytest.raises(PlanningPersistenceUnavailable):
        apply(evidence(child))
    # A generic earlier SQL error must not masquerade as proof that the actual
    # journal CHECK rolled back scalar/mirror writes attempted before it.
    assert rejected and set(rejected) == {"23514"}
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


def test_cross_session_same_hash_race_reconciles_final_receipt_provenance(db_conn, monkeypatch):
    from learning import evidence_transaction as tx

    nodes = [_node("Atomic cross-session exposure first"), _node("Atomic cross-session exposure second")]
    shared = hashlib.sha256(b"Synthetic concurrent same-question fixture").hexdigest()
    values = [evidence(node, session_id=f"session-{index}", question_hash=shared)
              for index, node in enumerate(nodes)]
    barrier = threading.Barrier(2)
    seen = set()
    mutex = threading.Lock()
    real = tx.rpc
    snapshots = []

    def rpc(name, args):
        result = real(name, args)
        if name == "learning_evidence_snapshot":
            with mutex:
                snapshots.append(deepcopy(result))
                first = threading.get_ident() not in seen
                seen.add(threading.get_ident())
            if first:
                assert result["checks"][0]["global_count"] == 0
                barrier.wait(timeout=5)
        return result

    monkeypatch.setattr(tx, "rpc", rpc)
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert all(pool.map(apply, values))
    # Separate graph nodes do not share a scalar version. The owner-global
    # hash-count CAS is what forces the losing unseen snapshot to be rebuilt.
    assert len(snapshots) >= 3
    events = [row for node in nodes for row in journal(db_conn, node)]
    assert len(events) == 2 and all(row["weight"] == 1 for row in events)
    observations = [row["planning_observation"] for row in events]
    assert sorted(row["independent"] for row in observations) == [False, True]
    assert sorted(row["previously_seen"] for row in observations) == [False, True]
    assert all(row["same_session_recheck"] is False for row in observations)
    receipts = {value["operation_id"]: tx.read_receipt(USER_ACTIVE, value["operation_id"])
                for value in values}
    for value in values:
        [event] = journal(db_conn, value["node_id"])
        assert receipts[value["operation_id"]]["observations"] == [event["planning_observation"]]
    # The barrier and unseen assertion apply only to the two racing workers.
    # This later operation intentionally observes both committed exposures.
    monkeypatch.setattr(tx, "rpc", real)
    apply(evidence(nodes[0], tagged=False, session_id="later-session", question_hash=shared))
    for operation, saved in receipts.items():
        assert tx.read_receipt(USER_ACTIVE, operation) == saved


def test_global_exposure_includes_owned_legacy_null_but_excludes_other_users(db_conn):
    from learning.evidence_transaction import read_receipt

    shared = hashlib.sha256(b"Synthetic owned legacy first exposure fixture").hexdigest()
    mine, other = _node("Atomic own first exposure"), _node("Atomic foreign first exposure", owner=USER_SECOND)
    apply(evidence(other, tagged=False, question_hash=shared, session_id="foreign"), owner=USER_SECOND)
    fresh = evidence(mine, question_hash=shared, session_id="mine")
    apply(fresh)
    [observation] = read_receipt(USER_ACTIVE, fresh["operation_id"])["observations"]
    assert observation["previously_seen"] is False and observation["independent"] is True

    legacy_hash = hashlib.sha256(b"Synthetic owned unknown provenance fixture").hexdigest()
    apply(evidence(mine, tagged=False, question_hash=legacy_hash, session_id="legacy"))
    assert journal(db_conn, mine)[-1]["planning_observation"] is None
    later = evidence(mine, question_hash=legacy_hash, session_id="new-tagged")
    apply(later)
    [observation] = read_receipt(USER_ACTIVE, later["operation_id"])["observations"]
    assert observation["previously_seen"] is True and observation["independent"] is False
    assert observation["same_session_recheck"] is False


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


def test_propagation_touch_supersedes_old_checkpoint_without_moving_decay_anchor(db_conn):
    from db.connection import table
    from learning.evidence_transaction import EvidenceObservationSuperseded

    parent = _node("Atomic propagation chronology parent")
    child = _node("Atomic propagation chronology child")
    table("graph_edges").insert({
        "user_id": USER_ACTIVE, "source_node_id": parent, "target_node_id": child,
        "relationship_type": "prerequisite",
    })
    now = datetime.now(timezone.utc)
    first = evidence(parent, observed_at=now - timedelta(seconds=2))
    initial_changes = apply(first)
    anchor = state(db_conn, parent)["last_evidence_at"]
    stale = evidence(parent, observed_at=now - timedelta(seconds=1), correct=False)
    apply(evidence(child, observed_at=now))  # genuine correct evidence propagates to parent
    propagated = state(db_conn, parent)
    assert propagated["last_evidence_at"] == anchor
    assert propagated["evidence_touch_at"] == now
    assert propagated["p_known"] != pytest.approx(initial_changes[0]["after"])
    before = deepcopy(propagated)
    events_before = journal(db_conn, parent)
    with pytest.raises(EvidenceObservationSuperseded):
        apply(stale)
    assert state(db_conn, parent) == before and journal(db_conn, parent) == events_before
    assert db_conn.execute(
        "SELECT count(*) n FROM learning_evidence_operations WHERE operation_id=%s",
        (stale["operation_id"],),
    ).fetchone()["n"] == 0
    # An already committed operation is replayable before the chronology fence.
    assert apply(first) == initial_changes and state(db_conn, parent) == before


def test_derived_metrics_do_not_stamp_an_evidence_touch_or_supersede_a_grade(db_conn):
    from learning.learner_state import write_metrics

    node = _node("Atomic metrics chronology")
    earlier = datetime.now(timezone.utc) - timedelta(seconds=2)
    apply(evidence(node, observed_at=earlier))
    saved = state(db_conn, node)
    write_metrics(USER_ACTIVE, node, htc_k=.2, unassisted_next=.3, assist_gap=.1, in_zone=True)
    metrics = state(db_conn, node)
    assert metrics["updated_at"] > saved["evidence_touch_at"]
    assert metrics["evidence_touch_at"] == saved["evidence_touch_at"] == earlier
    # This observation predates the metrics write, but no newer learning
    # observation occurred. It remains eligible and preserves derived metrics.
    observed = earlier + timedelta(seconds=1)
    assert apply(evidence(node, observed_at=observed))
    final = state(db_conn, node)
    assert final["evidence_touch_at"] == observed
    assert final["htc_k"] == pytest.approx(.2) and final["in_zone"] is True


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

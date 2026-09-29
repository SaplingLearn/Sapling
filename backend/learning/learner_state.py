"""learner_state table access (spec §4 PKG-03, §5, §13 A3).

read_* return p_known DECAYED toward BKT_L0 along the concept's FSRS
stability (spec §3.1, "Decay at read"). write_state is called ONLY from
services.graph_service.apply_graph_update — spec §8 invariant 1,
tests/test_learning_loop_invariants.py::test_inv_01_single_graph_writer.
write_metrics (PKG-14, spec §13 A79) is the one non-evidence write: an UPDATE of
the four derived columns only, called ONLY by scripts/derive_zpd_metrics.py
(inv_01 pins its callers, inv_20 the script).
Nothing here swallows: a PostgREST error or a corrupt stored row raises
(there is no honest default for "the store is down").
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from db.connection import page_all, table
from learning import bkt
from learning.params import BKT_L0

LEARNER_STATE_COLUMNS = (
    "user_id,node_id,p_known,n_strong_unassisted,streak_unassisted,"
    "max_streak_unassisted,opps,fsrs_d,fsrs_s,fsrs_last_review_at,fsrs_due_at,"
    "htc_k,unassisted_next,assist_gap,in_zone,last_evidence_at,updated_at"
)
_COUNTERS = ("n_strong_unassisted", "streak_unassisted", "max_streak_unassisted", "opps")
_OPTIONAL_FLOATS = ("fsrs_d", "fsrs_s", "htc_k", "unassisted_next", "assist_gap")
_TIMESTAMPS = ("fsrs_last_review_at", "fsrs_due_at", "last_evidence_at")
_ONE_DAY = timedelta(days=1)


@dataclass
class LearnerState:
    user_id: str
    node_id: str
    p_known: float = BKT_L0  # decayed at read; the posterior after an update
    n_strong_unassisted: int = 0
    streak_unassisted: int = 0
    max_streak_unassisted: int = 0  # §13 A3: wheelspin reads "ever reached 3"
    opps: int = 0
    fsrs_d: float | None = None
    fsrs_s: float | None = None
    fsrs_last_review_at: datetime | None = None
    fsrs_due_at: datetime | None = None
    htc_k: float | None = None  # PKG-06 derives; never written here
    unassisted_next: float | None = None
    assist_gap: float | None = None
    in_zone: bool | None = None
    last_evidence_at: datetime | None = None
    exists: bool = False


def _aware(ts: datetime) -> datetime:
    return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)


def _parse_ts(raw) -> datetime | None:
    if raw is None or raw == "":
        return None
    if isinstance(raw, datetime):
        return _aware(raw)
    return _aware(datetime.fromisoformat(str(raw).replace("Z", "+00:00")))


def _iso(ts: datetime | None) -> str | None:
    return _aware(ts).isoformat() if ts else None


def _from_row(row: dict, now: datetime) -> LearnerState:
    stored = row.get("p_known")
    if stored is None:
        raise ValueError(f"learner_state row node={row.get('node_id')} has no p_known")
    p_stored = float(stored)
    st = LearnerState(user_id=row["user_id"], node_id=row["node_id"], p_known=p_stored, exists=True)
    for col in _COUNTERS:
        setattr(st, col, int(row.get(col) or 0))
    for col in _OPTIONAL_FLOATS:
        raw = row.get(col)
        setattr(st, col, None if raw is None else float(raw))
    st.in_zone = row.get("in_zone")
    for col in _TIMESTAMPS:
        setattr(st, col, _parse_ts(row.get(col)))
    elapsed_days = 0.0
    if st.last_evidence_at is not None:
        elapsed_days = max(0.0, (now - st.last_evidence_at) / _ONE_DAY)
    # stability None → FSRS_S0_GOOD inside bkt.decayed_p; a stored S that is
    # not finite and > 0, or p outside [0, 1], raises there (HANDOFF-01 (h)).
    st.p_known = bkt.decayed_p(p_stored, elapsed_days, st.fsrs_s)
    return st


def read_states(user_id: str, node_ids, now: datetime | None = None) -> dict[str, LearnerState]:
    """One batched read; each returned state is decayed to `now`. Nodes with
    no row are absent from the result (read_state supplies the prior)."""
    ids = sorted({n for n in node_ids if n})
    if not ids:
        return {}
    now = _aware(now) if now else datetime.now(timezone.utc)
    rows = (
        table("learner_state").select(
            LEARNER_STATE_COLUMNS,
            filters={"user_id": f"eq.{user_id}", "node_id": f"in.({','.join(ids)})"},
        )
        or []
    )
    return {r["node_id"]: _from_row(r, now) for r in rows if r.get("node_id") in ids}


def read_state(user_id: str, node_id: str, now: datetime | None = None) -> LearnerState:
    """Single-row form; a missing row is the BKT prior with exists=False."""
    return read_states(user_id, [node_id], now=now).get(node_id) or LearnerState(
        user_id=user_id, node_id=node_id
    )


def write_state(state: LearnerState, now: datetime | None = None) -> None:
    """Upsert the BKT/FSRS columns. ONLY caller: graph_service.apply_graph_update.

    The derived columns (htc_k, unassisted_next, assist_gap, in_zone) are
    deliberately absent: PostgREST merge-duplicates would null them.
    """
    now = _aware(now) if now else datetime.now(timezone.utc)
    table("learner_state").upsert(
        {
            "user_id": state.user_id,
            "node_id": state.node_id,
            "p_known": state.p_known,
            "n_strong_unassisted": state.n_strong_unassisted,
            "streak_unassisted": state.streak_unassisted,
            "max_streak_unassisted": state.max_streak_unassisted,
            "opps": state.opps,
            "fsrs_d": state.fsrs_d,
            "fsrs_s": state.fsrs_s,
            "fsrs_last_review_at": _iso(state.fsrs_last_review_at),
            "fsrs_due_at": _iso(state.fsrs_due_at),
            "last_evidence_at": _iso(state.last_evidence_at),
            "updated_at": _iso(now),
        },
        on_conflict="user_id,node_id",
    )


def write_metrics(
    user_id: str,
    node_id: str,
    *,
    htc_k: float | None,
    unassisted_next: float | None,
    assist_gap: float | None,
    in_zone: bool | None,
) -> None:
    """UPDATE the derived ZPD columns of one row (spec §4, §10 rung 2) and its
    updated_at — nothing else. ONLY caller: scripts/derive_zpd_metrics.py. An
    UPDATE on the primary key, never an upsert: a row that does not exist is
    not created here (only evidence creates learner_state rows)."""
    table("learner_state").update(
        {
            "htc_k": htc_k,
            "unassisted_next": unassisted_next,
            "assist_gap": assist_gap,
            "in_zone": in_zone,
            "updated_at": _iso(datetime.now(timezone.utc)),
        },
        filters={"user_id": f"eq.{user_id}", "node_id": f"eq.{node_id}"},
    )


def opportunity_states(user_id: str | None = None) -> list[dict]:
    """Every (user_id, node_id, opps) row with at least one opportunity — one
    user's with `user_id` — paged in primary-key order (the metrics script's
    read; it never names the table itself, invariant 20)."""
    filters = {"opps": "gt.0"}
    if user_id:
        filters["user_id"] = f"eq.{user_id}"
    return list(
        page_all(
            _LearnerStateRead(), "user_id,node_id,opps", filters=filters, order="user_id,node_id"
        )
    )


class _LearnerStateRead:
    """A read-only `page_all` handle over learner_state (invariant 1's ast half
    allows `table("learner_state")` only as a direct read, so the handle is never
    passed around; the services/check_item_service.py::_GraphNodesRead pattern)."""

    def select_with_count(self, *args, **kwargs):
        return table("learner_state").select_with_count(*args, **kwargs)

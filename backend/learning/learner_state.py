"""learner_state table access (spec §4 PKG-03, §5, §13 A3).

read_* return p_known DECAYED toward BKT_L0 along the concept's FSRS
stability (spec §3.1, "Decay at read"). Evidence row projections use state_row;
the single graph writer commits them through the atomic transaction RPC.
The compatibility write_state helper has no production callers; invariant 1
forbids adding one as an unconditional-write fallback.
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
# A selected goal can span more than PostgREST's 1000-row response limit. A
# bounded IN list also keeps UUID-heavy GET URLs below common proxy limits.
# (user_id, node_id) is unique, so each request can return at most 100 rows.
_READ_BATCH_SIZE = 100


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
    # Populated by the transactional snapshot, not inferred from updated_at.
    evidence_version: int = 0


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
    version = row.get("evidence_version", 0)
    if type(version) is not int or version < 0:
        raise ValueError("Invalid learner-state evidence version")
    st.evidence_version = version
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
    """Bounded batched reads, decayed to one `now`, without silent truncation.

    Each batch is below the PostgREST row/URL limits. Nodes with no row are
    absent from the result (read_state supplies the prior).
    """
    ids = sorted({n for n in node_ids if n})
    if not ids:
        return {}
    now = _aware(now) if now else datetime.now(timezone.utc)
    states = {}
    for start in range(0, len(ids), _READ_BATCH_SIZE):
        batch = ids[start : start + _READ_BATCH_SIZE]
        rows = (
            table("learner_state").select(
                LEARNER_STATE_COLUMNS,
                filters={"user_id": f"eq.{user_id}", "node_id": f"in.({','.join(batch)})"},
            )
            or []
        )
        states.update({r["node_id"]: _from_row(r, now) for r in rows if r.get("node_id") in batch})
    return states


def read_state(user_id: str, node_id: str, now: datetime | None = None) -> LearnerState:
    """Single-row form; a missing row is the BKT prior with exists=False."""
    return read_states(user_id, [node_id], now=now).get(node_id) or LearnerState(
        user_id=user_id, node_id=node_id
    )


def state_row(state: LearnerState, now: datetime) -> dict:
    """The canonical evidence columns, shared by legacy and atomic writers.

    Derived metrics and database-owned versions are deliberately absent.
    Transaction CAS protects their version; the upsert preserves their values.
    """
    return {
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
    }


def write_state(state: LearnerState, now: datetime | None = None) -> None:
    """Compatibility helper; production evidence must use the atomic RPC."""
    now = _aware(now) if now else datetime.now(timezone.utc)
    table("learner_state").upsert(
        state_row(state, now),
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


def states_last_evidence_before(user_id: str, cutoff: datetime) -> list[dict]:
    """One student's (node_id, last_evidence_at) rows whose last evidence is at
    or before `cutoff`, oldest first, paged (PKG-14's post-test selection)."""
    return list(
        page_all(
            _LearnerStateRead(),
            "node_id,last_evidence_at",
            filters={"user_id": f"eq.{user_id}", "last_evidence_at": f"lte.{_iso(cutoff)}"},
            order="last_evidence_at,node_id",
        )
    )


class _LearnerStateRead:
    """A read-only `page_all` handle over learner_state (invariant 1's ast half
    allows `table("learner_state")` only as a direct read, so the handle is never
    passed around; the services/check_item_service.py::_GraphNodesRead pattern)."""

    def select_with_count(self, *args, **kwargs):
        return table("learner_state").select_with_count(*args, **kwargs)

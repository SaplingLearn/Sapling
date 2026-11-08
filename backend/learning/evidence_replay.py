"""The evidence journal, replayed (learning-loop spec §13 A123).

ONE state transition, two drivers. `observe` (a graded observation on its own
concept: BKT, the counters, FSRS, the decay anchor) and `propagate` (the one-hop
prerequisite observation it causes, stored against the target's kept decay
anchor) are the code services/graph_service.py::_calculate_evidence runs when
the single writer journals a row, and the code `replay` runs when a void
rebuilds a student's learner_state from the journal. Between two operations the
replay reads each state back exactly as the writer's next snapshot would —
`learner_state._from_row` over the `state_row` the writer stored — so a replay
of a journal with nothing void reproduces, bit for bit, every learner_state row
and graph_nodes mirror the incremental path wrote
(tests/test_learning_evidence_replay.py proves it over generated histories).

What a journal row carries for its replay (A123 journals the last three):
channel, correct, idk (the `evidence:<channel>:idk` reason), assisted,
max_rung, weight (the writer's derived weight, used as journaled), created_at
(the operation's `now`; one call's rows share it and number 0..n−1 in
`evidence_seq`, A36), `retention` (the FSRS target it was scheduled at),
`same_session_recheck` (the writer's final flag) and `propagated_to` (the node
ids its propagation moved). A row written before A123 has NULL in those three;
the replay's rule for it is exact where the journal decides it: the recheck
flag from the planning envelope, else from the weight (it is the one factor
left once correct, rung, help and confidence are known — and it only matters
for a correct unassisted row); the retention as FSRS_RETENTION_DEFAULT (every
writer but the review used it); the propagation along the course's CURRENT
prerequisite edges (the edges of its own time are not journaled). A row the
replay cannot read faithfully raises ReplayError: a void then fails closed.

No database, no model: data and arithmetic only.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import datetime, timedelta

from learning import bkt, fsrs
from learning.evidence import Evidence, evidence_weight, is_strong_channel
from learning.learner_state import LearnerState, _from_row, _parse_ts, state_row
from learning.params import (
    BKT_L0,
    CHANNELS,
    EDGE_PREREQ_SOURCE_IS_PREREQ,
    FSRS_RETENTION_DEFAULT,
    FSRS_S0_GOOD,
    LADDER_MAX_RUNG,
)

_ONE_DAY = timedelta(days=1)


class ReplayError(ValueError):
    """A journal row the replay cannot read faithfully (fail closed)."""


# ── the state transition (shared with graph_service._calculate_evidence) ──


def fsrs_after(
    st: LearnerState,
    *,
    channel: str,
    correct: bool,
    max_rung: int,
    idk: bool,
    now: datetime,
    retention: float | None = None,
) -> None:
    """ADAPTER — the one place fsrs.next_state's signature is assumed
    (HANDOFF-02: `next_state(d, s, rating, days_since, *, same_day,
    mc_unassisted) -> (D', S')`; nothing is scheduled there). Mutates st's
    fsrs_* fields in place. A review less than one day after the last one
    takes FSRS's same-day branch (py-fsrs: `(now − last_review).days < 1`).
    The due date is at `retention` (FSRS_RETENTION_DEFAULT when None); the
    caller picks it by exam window or set size (PKG-12's review passes
    learning.review.retention_target's value through apply_graph_update)."""
    rating = fsrs.rating_for(channel, correct, max_rung, idk=idk)
    mc_unassisted = fsrs.mc_cap_applies(channel, correct, max_rung, idk=idk)
    last = st.fsrs_last_review_at
    days_since = 0.0
    same_day = False
    if last is not None:
        days_since = max(0.0, (now - last) / _ONE_DAY)
        same_day = now - last < _ONE_DAY
    new_d, new_s = fsrs.next_state(
        st.fsrs_d, st.fsrs_s, rating, days_since,
        same_day=same_day, mc_unassisted=mc_unassisted,
    )
    st.fsrs_d, st.fsrs_s = new_d, new_s
    st.fsrs_last_review_at = now
    target = FSRS_RETENTION_DEFAULT if retention is None else retention
    st.fsrs_due_at = now + timedelta(days=fsrs.interval(target, new_s))


def keep_decay_anchor(st: LearnerState, p_now: float, now: datetime) -> tuple[float, datetime]:
    """ADAPTER over fsrs.retrievability / fsrs.interval (the R that
    bkt.decayed_p reads with). Returns `(p_stored, anchor)` for a write
    that is NOT a check on st's concept (one-hop propagation): read_state
    at `now` gives `p_now` back, but the concept's forgetting curve is not
    restarted. Spec §1/§3.1: belief decays "between checks" along
    R(Δt, S_c); restarting a power-law curve at every propagation made a
    correct observation lower a later read (R(a)·R(b) < R(a+b)).

    Keeps `st.last_evidence_at` and stores `L0 + (p_now − L0) / R(Δt, S_c)`.
    Where that leaves [0, 1] (p_now is outside what the old anchor can
    represent), it stores the bound and moves the anchor forward only as
    far as needed, so R(now − anchor') = (p_now − L0) / (bound − L0). A
    concept with no anchor (no row yet) is anchored at `now`.
    """
    anchor = st.last_evidence_at
    if anchor is None:
        return p_now, now
    if anchor >= now:  # read_states decays nothing before the anchor
        return p_now, anchor
    s_c = FSRS_S0_GOOD if st.fsrs_s is None else st.fsrs_s
    r = fsrs.retrievability((now - anchor) / _ONE_DAY, s_c)
    p_stored = BKT_L0 + (p_now - BKT_L0) / r
    if 0.0 <= p_stored <= 1.0:
        return p_stored, anchor
    bound = 1.0 if p_stored > 1.0 else 0.0
    needed = (p_now - BKT_L0) / (bound - BKT_L0)  # in (r, 1]
    return bound, now - timedelta(days=fsrs.interval(min(1.0, needed), s_c))


def observe(
    st: LearnerState,
    *,
    channel: str,
    correct: bool,
    idk: bool,
    assisted: bool,
    max_rung: int,
    weight: float,
    recheck: bool,
    now: datetime,
    retention: float | None,
) -> tuple[float, float]:
    """One graded observation on its own concept, in place: the BKT update at
    `weight` (0.0, correct after H4..H6, returns p unchanged), the counters (a
    correct unassisted answer extends the streak — a correct re-check of a
    question already asked this session is an opportunity only, spec §3.3 —
    anything else breaks it), FSRS, and the decay anchor moved to `now`.
    Returns (p_before, p_after)."""
    p_before = st.p_known
    p_after = bkt.update(p_before, channel, correct, weight=weight, idk=idk)
    unassisted = not assisted and max_rung == 0
    st.opps += 1
    if correct and unassisted:
        if not recheck:
            st.streak_unassisted += 1
            if is_strong_channel(channel):
                st.n_strong_unassisted += 1
    else:
        st.streak_unassisted = 0
    st.max_streak_unassisted = max(st.max_streak_unassisted, st.streak_unassisted)
    st.p_known = p_after
    st.last_evidence_at = now
    fsrs_after(
        st, channel=channel, correct=correct, max_rung=max_rung, idk=idk, now=now,
        retention=retention,
    )
    return p_before, p_after


def propagation_targets(
    node_id: str, correct: bool, weight: float, edges: Iterable[Mapping], owned
) -> list[bkt.Propagation]:
    """The one-hop prerequisite observations an observation on `node_id`
    causes (bkt.propagate_prereq over `edges`, oriented by
    EDGE_PREREQ_SOURCE_IS_PREREQ): its parents when correct, its dependents
    when not — only nodes in `owned`, never the node itself. A weight of 0.0
    (correct after H4..H6, §3.3 "no upward BKT evidence") moves no neighbour."""
    if not weight > 0.0:
        return []
    parents: list[str] = []
    children: list[str] = []
    for edge in edges:
        src, tgt = edge["source"], edge["target"]
        prereq, dependent = (src, tgt) if EDGE_PREREQ_SOURCE_IS_PREREQ else (tgt, src)
        if dependent == node_id and prereq != node_id:
            parents.append(prereq)
        elif prereq == node_id and dependent != node_id:
            children.append(dependent)
    return [
        target
        for target in bkt.propagate_prereq(correct, parents, children)
        if target[0] in owned and target[0] != node_id
    ]


def propagate(
    tst: LearnerState,
    *,
    channel: str,
    correct: bool,
    weight: float,
    source_weight: float,
    now: datetime,
) -> float:
    """One propagated observation on a neighbour, in place: `tst.p_known`
    becomes the belief AT `now` (a later observation in the same operation
    reads it), `tst.last_evidence_at` the kept decay anchor. Returns the
    p_known its learner_state row stores against that anchor. The propagated
    observation carries the source evidence's own weight too (spec §5) †."""
    tst.p_known = bkt.update(tst.p_known, channel, correct, weight=weight * source_weight)
    p_stored, tst.last_evidence_at = keep_decay_anchor(tst, tst.p_known, now)
    return p_stored


# ── reading the journal ────────────────────────────────────────────────────


@dataclass(frozen=True)
class Observation:
    """One evidence journal row, as the replay reads it."""

    id: str
    node_id: str
    at: datetime
    channel: str
    correct: bool
    idk: bool
    assisted: bool
    max_rung: int
    weight: float
    recheck: bool
    retention: float | None
    propagated_to: tuple[str, ...] | None  # None: written before A123 journaled it


def _number(value) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ReplayError("journal number unreadable")
    return float(value)


def _derived_recheck(row: Mapping, *, channel, correct, idk, assisted, max_rung, weight) -> bool:
    """A row written before A123 journaled its recheck flag: the planning
    envelope's final flag when the row has one, else the flag the writer's own
    derivation (learning.evidence.evidence_weight) needs to give the journaled
    weight. The flag moves the counters only on a correct unassisted answer,
    and there it is the one factor left; elsewhere it changes nothing."""
    envelope = row.get("planning_recheck")
    if isinstance(envelope, bool):
        return envelope
    if not (correct and not assisted and max_rung == 0):
        return False
    confidence = row.get("confidence")
    found = [
        flag
        for flag in (False, True)
        if evidence_weight(
            Evidence(
                node_id=str(row.get("node_id")), channel=channel, correct=correct, idk=idk,
                assisted=assisted, max_rung=max_rung, confidence=confidence,
                same_session_recheck=flag,
            )
        )
        == weight
    ]
    if len(found) != 1:
        raise ReplayError("journal recheck flag undecidable from its weight")
    return found[0]


def observation(row: Mapping) -> Observation:
    """A journal row (the void snapshot's shape) as an Observation, or
    ReplayError when anything the replay needs is missing or malformed."""
    try:
        channel = row["channel"]
        correct = row["correct"]
        assisted = row.get("assisted")
        max_rung = row.get("max_rung")
        if channel not in CHANNELS or not isinstance(correct, bool) or not isinstance(assisted, bool):
            raise ReplayError("journal row unreadable")
        if isinstance(max_rung, bool) or not isinstance(max_rung, int) or not 0 <= max_rung <= LADDER_MAX_RUNG:
            raise ReplayError("journal rung unreadable")
        weight = _number(row["weight"])
        if not 0.0 <= weight <= 1.0:
            raise ReplayError("journal weight out of range")
        idk = row.get("reason") == f"evidence:{channel}:idk"
        at = _parse_ts(row["created_at"])
        if at is None:
            raise ReplayError("journal time unreadable")
        retention = row.get("retention")
        if retention is not None:
            retention = _number(retention)
            if not 0.0 < retention <= 1.0:
                raise ReplayError("journal retention out of range")
        recheck = row.get("same_session_recheck")
        if not isinstance(recheck, bool):
            if recheck is not None:
                raise ReplayError("journal recheck flag unreadable")
            recheck = _derived_recheck(
                row, channel=channel, correct=correct, idk=idk, assisted=assisted,
                max_rung=max_rung, weight=weight,
            )
        targets = row.get("propagated_to")
        if targets is not None:
            if not isinstance(targets, list) or not all(isinstance(t, str) and t for t in targets):
                raise ReplayError("journal propagation unreadable")
            targets = tuple(targets)
        node_id, event_id = row["node_id"], row["id"]
        if not isinstance(node_id, str) or not node_id or not isinstance(event_id, str):
            raise ReplayError("journal identity unreadable")
    except ReplayError:
        raise
    except Exception as exc:  # KeyError, a bad timestamp, a model refusal
        raise ReplayError("journal row unreadable") from exc
    return Observation(
        id=event_id, node_id=node_id, at=at, channel=channel, correct=correct, idk=idk,
        assisted=assisted, max_rung=max_rung, weight=weight, recheck=recheck,
        retention=retention, propagated_to=targets,
    )


def operations(observations: Sequence[Observation]) -> list[list[Observation]]:
    """The journal in total order, cut into the writer's operations: one call
    journals its rows at one `now` (A36), so consecutive rows sharing a time
    are one operation, and the states stay in memory between them."""
    out: list[list[Observation]] = []
    for ob in observations:
        if out and out[-1][0].at == ob.at:
            out[-1].append(ob)
        else:
            out.append([ob])
    return out


# ── the replay ─────────────────────────────────────────────────────────────


def _journaled_targets(ob: Observation, owned: frozenset) -> list[bkt.Propagation]:
    """The propagated observations a row journaled (`propagated_to`, the
    nodes the writer moved, in its order): the same (node, channel, correct,
    weight) bkt.propagate_prereq names for them — handed the moved nodes as
    both sides, it returns them whichever way the answer went."""
    if not ob.weight > 0.0:
        return []
    moved = [t for t in ob.propagated_to or () if t in owned and t != ob.node_id]
    return bkt.propagate_prereq(ob.correct, moved, moved)


def _targets(ob: Observation, edges: Sequence[Mapping], owned: frozenset) -> list[bkt.Propagation]:
    """A row's propagation: as journaled, else (written before A123) along the
    course's prerequisite edges now."""
    if ob.propagated_to is None:
        return propagation_targets(ob.node_id, ob.correct, ob.weight, edges, owned)
    return _journaled_targets(ob, owned)


def moved_by(ob: Observation, *, edges: Sequence[Mapping], owned) -> list[str]:
    """The nodes an observation moves: its own concept, then every node its
    one-hop propagation moves (the replay's rule) — what a void of it must
    recompute."""
    owned = frozenset(owned)
    return [ob.node_id, *(t for t, *_ in _targets(ob, edges, owned))]


@dataclass(frozen=True)
class Replayed:
    """What the writer would have stored after the replayed journal: per node
    its last learner_state row (`state_row`'s evidence columns, `updated_at`
    the operation that last touched it), the belief its graph_nodes mirror
    holds, and when it was last touched. `trace` maps each replayed row's id
    to the (p_before, p_after) the writer would have journaled for it."""

    state_rows: dict[str, dict]
    mirrors: dict[str, float]
    touched_at: dict[str, datetime]
    trace: dict[str, tuple[float, float]]


def replay(
    observations: Sequence[Observation],
    *,
    user_id: str,
    edges: Sequence[Mapping],
    owned,
) -> Replayed:
    """Fold the observations (the journal's total order; void rows left out by
    the caller) through `observe` / `propagate` exactly as the writer did: each
    operation reads every state it touches at its own `now` from the row the
    previous operation stored (decay at read), keeps it in memory for the
    rest of the operation, and stores it back. A row's propagation follows its
    journaled `propagated_to`, else `edges` (the course's prerequisite edges);
    nodes outside `owned` (gone since) are never touched. Pure."""
    owned = frozenset(owned)
    stored: dict[str, dict] = {}
    mirrors: dict[str, float] = {}
    touched: dict[str, datetime] = {}
    trace: dict[str, tuple[float, float]] = {}
    for op in operations(observations):
        now = op[0].at
        working: dict[str, LearnerState] = {}

        def load(node_id: str) -> LearnerState:
            st = working.get(node_id)
            if st is None:
                row = stored.get(node_id)
                st = _from_row(row, now) if row is not None else LearnerState(user_id=user_id, node_id=node_id)
                working[node_id] = st
            return st

        for ob in op:
            if ob.node_id not in owned:
                continue
            st = load(ob.node_id)
            trace[ob.id] = observe(
                st, channel=ob.channel, correct=ob.correct, idk=ob.idk, assisted=ob.assisted,
                max_rung=ob.max_rung, weight=ob.weight, recheck=ob.recheck, now=now,
                retention=ob.retention,
            )
            stored[ob.node_id] = state_row(st, now)
            mirrors[ob.node_id] = st.p_known
            touched[ob.node_id] = now
            for target_id, channel, target_correct, target_weight in _targets(ob, edges, owned):
                tst = load(target_id)
                p_stored = propagate(
                    tst, channel=channel, correct=target_correct, weight=target_weight,
                    source_weight=ob.weight, now=now,
                )
                stored[target_id] = state_row(replace(tst, p_known=p_stored), now)
                mirrors[target_id] = tst.p_known
                touched[target_id] = now
    return Replayed(state_rows=stored, mirrors=mirrors, touched_at=touched, trace=trace)

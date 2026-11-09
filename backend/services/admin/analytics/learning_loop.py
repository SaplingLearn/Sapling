"""
backend/services/admin/analytics/learning_loop.py — the learning loop's KPIs
(PKG-14; spec §10) behind GET /api/admin/analytics/learning-loop, moved out of
routes/admin_analytics.py with the #118 layout (spec §13 A149). The route
keeps the admin check, the range and the OpenAPI contract;
`learning_loop_report` is its body.
"""
from __future__ import annotations

import logging
from collections import defaultdict
from collections.abc import Iterable
from datetime import date, datetime, timedelta, timezone
from typing import NamedTuple

from agents._providers import slot_warnings
from db.connection import page_all, pg_quote_value, table
from learning.calibration import calibration as bkt_calibration
from learning.calibration import confidence_calibration
from learning.calibration import eligible as calibration_eligible
from learning.cost_per_gain import LOOP_TASKS, cost_per_gain
from learning.earnest_revise import earnest_revise
from learning.evidence_void import is_void_row, pose_is_void
from learning.help_abuse import LOOP_SOURCE as HELP_LOOP_SOURCE
from learning.help_abuse import help_abuse as help_abuse_report
from learning.item_reports import retired_items
from learning.self_explain_report import self_explanation_report
from learning.self_explain_store import REPORT_COLUMNS as SELF_EXPLAIN_COLUMNS
from learning.self_explain_store import TABLE as SELF_EXPLAIN_TABLE
from learning.multi_concept_report import multi_concept_report
from learning.learning_gain import (
    due_windows,
    learning_gain,
    posttest_funnel,
    posttest_outcome,
    pretest_outcome,
    window_bounds,
)
from learning.posttest_store import posttest_anchors
from learning.params import (
    ACQ_TARGET_HI,
    ACQ_TARGET_LO,
    BAND_WINDOW,
    GATE_CEILING_COMPLIANCE_MIN,
    GATE_LEAKS_MAX,
    KPI_TREND_WEEKS,
    LADDER_MAX_RUNG,
    PRACTICE_TARGET_HI,
    PRACTICE_TARGET_LO,
    PROBE_TARGET_HI,
    PROBE_TARGET_LO,
)
from learning.probe import probe_history_hashes
from services.academics import offering_course_id
from services.admin.analytics.learning_models import (
    Calibration,
    CeilingCompliance,
    ConceptTrend,
    ConfidenceCalibration,
    CostPerGain,
    EarnestRevise,
    Gates,
    HelpAbuse,
    LearningGain,
    LearningLoopKpis,
    MultiConcept,
    NextSessionSuccess,
    SelfExplanation,
    SlotWarning,
    TrendDirection,
    WeekPoint,
)
from services.admin.analytics.models import Range
from services.admin.analytics import scan as _scan
from services.admin.analytics.scan import _scan_range
from services.quiz_ask import quiz_ask_session_ids

# Log records keep the name they had in routes/admin_analytics.py.
logger = logging.getLogger("sapling.admin_analytics")


# ── Learning loop KPIs (PKG-14; spec §10) ────────────────────────────────────
#
# The three headline KPIs and the two measurable gates of the evaluation
# ladder, over `zpd.step`/`zpd.leak` events and the evidence journal. Admin-only
# and read-only like every endpoint here. The earnest-revise gate (spec §10) is
# measured since spec §13 A109: the feedback zpd.step's `earnest_blocked` bool.

_STEP_EVENT = "zpd.step"
_LEAK_EVENT = "zpd.leak"
_REVEAL_EVENT = "zpd.reveal"  # spec §13 A88 (m5): a solution SERVED for an open posed item
#: spec §13 A123: the check item and the node's course name the course item a
#: row was graded against — what the void rule (learning/evidence_void.py) keys on
_EVIDENCE_COLS = (
    "id,node_id,session_id,correct,assisted,max_rung,question_hash,created_at,"
    "channel,p_before,weight,check_item_id,"
    # spec §13 A127: the student's stated confidence (metacognitive calibration)
    "student_confidence,"
    "graph_nodes!inner(course_id)"
)


def _rung_int(value) -> int | None:
    """A rung's wire form ("H3", "h0" or 3, HANDOFF-06) as an int, None when it
    is not a rung (a bool, an unknown string, out of H0..H6)."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        n = value
    elif isinstance(value, str) and value[:1] in ("H", "h") and value[1:].isdigit():
        n = int(value[1:])
    else:
        return None
    return n if 0 <= n <= LADDER_MAX_RUNG else None


def _phase_band(phase, assisted) -> tuple[float, float] | None:
    """The phase band a step's rolling success rate is judged against (spec §3.3):
    probe → PROBE_TARGET, assisted check → ACQ_TARGET, unassisted check →
    PRACTICE_TARGET; every other phase has no band."""
    if phase == "probe":
        return (PROBE_TARGET_LO, PROBE_TARGET_HI)
    if phase == "check":
        return (ACQ_TARGET_LO, ACQ_TARGET_HI) if assisted else (PRACTICE_TARGET_LO, PRACTICE_TARGET_HI)
    return None


def _payload(row: dict) -> dict:
    p = row.get("payload")
    return p if isinstance(p, dict) else {}


def _step_kind(p: dict) -> str | None:
    phase = p.get("phase")
    if phase == "probe":
        return "probe"
    if phase == "check":
        return "check-assisted" if p.get("assisted") else "check-unassisted"
    return None


def _in_band_share(steps: list[dict]) -> tuple[int, int]:
    """(in_band, banded_steps): per (user_id, concept_id) in created_at order, a
    step of a banded kind with at least BAND_WINDOW earlier steps of the SAME
    kind is judged by the first-attempt success rate over those BAND_WINDOW."""
    history: dict[tuple, list[bool]] = defaultdict(list)
    in_band = banded = 0
    for row in sorted(steps, key=lambda r: str(r.get("created_at") or "")):
        p = _payload(row)
        kind = _step_kind(p)
        if kind is None:
            continue
        prior = history[(row.get("user_id"), p.get("concept_id"), kind)]
        if len(prior) >= BAND_WINDOW:
            window = prior[-BAND_WINDOW:]
            rate = sum(window) / len(window)
            lo, hi = _phase_band(p.get("phase"), p.get("assisted"))
            banded += 1
            in_band += int(lo <= rate <= hi)
        prior.append(p.get("first_attempt_correct") is True)
    return in_band, banded


def _parse_ts(raw) -> datetime | None:
    try:
        ts = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return (ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)).astimezone(timezone.utc)


def _week_start(ts: datetime):
    iso = ts.isocalendar()
    return date.fromisocalendar(iso.year, iso.week, 1)


def _step_correct(p: dict) -> bool:
    """A step that ended correct: first attempt correct, or a time to correct."""
    return p.get("first_attempt_correct") is True or p.get("time_to_correct_ms") is not None


def _htc_k_trend(steps: list[dict], to_iso: str) -> list[ConceptTrend]:
    """Per concept, mean max_rung_used over its correct steps per ISO week, for
    the KPI_TREND_WEEKS weeks ending at `to` (hints-to-criterion must fall)."""
    to_dt = _parse_ts(to_iso)
    last = _week_start(to_dt) if to_dt else None
    first = last - timedelta(weeks=KPI_TREND_WEEKS - 1) if last else None
    rungs: dict[str, dict] = defaultdict(lambda: defaultdict(list))
    for row in steps:
        p = _payload(row)
        concept = p.get("concept_id")
        rung = _rung_int(p.get("max_rung_used"))
        ts = _parse_ts(row.get("created_at"))
        if not concept or rung is None or ts is None or not _step_correct(p):
            continue
        week = _week_start(ts)
        if first is None or not (first <= week <= last):
            continue
        rungs[str(concept)][week].append(rung)
    out = []
    for concept in sorted(rungs):
        weeks = [
            WeekPoint(week_start=w.isoformat(), mean_rung=sum(v) / len(v), steps=len(v))
            for w, v in sorted(rungs[concept].items())
        ]
        if len(weeks) < 2:
            direction: TrendDirection = "insufficient"
        elif weeks[-1].mean_rung < weeks[0].mean_rung:
            direction = "falling"
        elif weeks[-1].mean_rung > weeks[0].mean_rung:
            direction = "rising"
        else:
            direction = "flat"
        out.append(ConceptTrend(concept_id=concept, weeks=weeks, direction=direction))
    return out


def _next_session_rate(evidence_rows: list[dict], quiz_ask: set[str] | frozenset = frozenset()) -> dict:
    """Unassisted next-opportunity success on the FOLLOWING session's first item:
    per node, its sessions in order of their first evidence row; for every
    session after the first, its first row is a success when it is correct,
    unassisted and at rung 0. Rows with no session_id (post-test, quiz) are
    not a session, and neither is a quiz-ask session (spec §13 A106: it skips
    the probe and opens on the concept just asked about) — those are counted
    in `quiz_ask_excluded`."""
    by_node: dict[str, dict[str, dict]] = defaultdict(dict)
    excluded: set[str] = set()
    for row in sorted(
        evidence_rows, key=lambda r: (str(r.get("created_at") or ""), str(r.get("id") or ""))
    ):
        session = row.get("session_id")
        if not session or not row.get("node_id"):
            continue
        if session in quiz_ask:
            excluded.add(session)
            continue
        by_node[row["node_id"]].setdefault(session, row)  # the session's first row
    sessions = successes = 0
    for firsts in by_node.values():
        for row in list(firsts.values())[1:]:
            sessions += 1
            successes += int(
                row.get("correct") is True
                and not row.get("assisted")
                and _rung_int(row.get("max_rung")) == 0
            )
    return {
        "sessions": sessions,
        "successes": successes,
        "rate": successes / sessions if sessions else None,
        "quiz_ask_excluded": len(excluded),
    }


#: spec §13 A112: an answered post-test pose — its window, its recorded outcome,
#: its anchor (the concept's first evidence row), the delay it had, and the
#: course item it asked (what an A113 retire is keyed on); A126: the anchor's
#: time (the actual delay) and the page-hidden telemetry (the visibility stratum)
_POSE_COLS = (
    "user_id,node_id,window_days,answered_at,correct,max_rung,anchor_event_id,anchor_at,"
    "days_since_evidence,course_id,question_hash,hidden_count,hidden_s"
)
#: A126: what the funnel classifies a due window's pose and skip by
#: A123: course_id and question_hash name the item the void rule keys on
_FUNNEL_POSE_COLS = (
    "user_id,node_id,window_days,posed_at,answered_at,correct,max_rung,course_id,question_hash"
)
_FUNNEL_SKIP_COLS = "user_id,node_id,window_days,reason"
#: an anchor row, with what learning_gain.pretest_outcome binds its envelope to
_ANCHOR_COLS = (
    "id,node_id,session_id,question_hash,check_item_id,channel,correct,assisted,max_rung,"
    "reason,planning_observation"
)
#: ids per `in.(…)` read, so a GET URL stays well under common proxy limits
_IN_BATCH = 100


def _in(values: list[str]) -> str:
    return f"in.({','.join(pg_quote_value(v) for v in values)})"


def _batches(values: list[str]):
    for start in range(0, len(values), _IN_BATCH):
        yield values[start : start + _IN_BATCH]


def _pretests(poses: list[dict], retired: set[tuple[str, str]] = frozenset()) -> dict[str, bool]:
    """A112: anchor event id → the concept's pretest outcome
    (learning_gain.pretest_outcome), for the poses with an unassisted outcome.
    Two bounded reads: their anchor rows (each concept's first evidence) by id,
    then the probe histories of those rows' sessions — planning provenance tags
    the loop's in-session checks too, so only the session's probe history says
    a row was a probe grade. A123: an anchor graded against an item staff
    retired is void evidence — no pretest (the void rule, keyed on the pose's
    course)."""
    course_of = {
        str(p["anchor_event_id"]): p.get("course_id")
        for p in poses
        if p.get("anchor_event_id") and posttest_outcome(p) is not None
    }
    ids = sorted(course_of)
    anchors: list[dict] = []
    for batch in _batches(ids):
        anchors += (
            table("node_mastery_events").select(
                _ANCHOR_COLS, filters={"id": _in(batch), "event_type": "eq.evidence"}
            )
            or []
        )
    anchors = [
        row for row in anchors
        if not is_void_row(row, retired, course_of.get(str(row.get("id"))))
    ]
    sessions = sorted({str(r["session_id"]) for r in anchors if r.get("session_id")})
    probed: dict[str, set[str]] = {}
    for batch in _batches(sessions):
        for row in table("sessions").select(
            "id,history:loop_state->probe->history", filters={"id": _in(batch)}
        ) or []:
            probed[str(row.get("id"))] = probe_history_hashes(row.get("history"))
    out: dict[str, bool] = {}
    for row in anchors:
        outcome = pretest_outcome(row, probed.get(str(row.get("session_id")), set()))
        if outcome is not None and row.get("id"):
            out[str(row["id"])] = outcome
    return out


def _void_items(
    evidence: list[dict], poses: list[dict], funnel_poses: Iterable[dict] = ()
) -> set[tuple[str, str]]:
    """Spec §13 A123 — the ONE rule every report here applies: an observation
    graded against a check item STAFF retired is void (learning/evidence_void.py).
    The staff-retired course items, as (course_id, question_hash) — the
    structured record (`check_item_reviews`, status 'retired'), never an item
    row being gone (A23's consent withdrawal and A119's re-key delete rows too,
    and that evidence stands); a quarantine, a report or an approval is no
    retire. Read only when there is an observation to judge — a scanned
    evidence row, an answered post-test in the range, or an answered pose of
    the A126 funnel: ONE paged, status-filtered read (retired items are staff
    decisions, so few)."""
    if (
        not evidence
        and not any(posttest_outcome(p) is not None for p in poses)
        and not any(p.get("answered_at") for p in funnel_poses)
    ):
        return set()
    return retired_items()


class _FunnelReads(NamedTuple):
    """What the A126 funnel classifies: the due windows, their poses and the
    recorded skips, keyed (user_id, node_id, window_days)."""

    due: list[dict]
    poses: dict[tuple, dict]
    skips: dict[tuple, str]
    truncated: bool


def _funnel_reads(from_iso: str, to_iso: str) -> _FunnelReads | None:
    """A126: the reads behind the funnel of the post-test windows that OPENED
    in the range (learning_gain.due_windows over every concept's anchor;
    posttest_funnel classifies each, after the one retired read). Reads: the
    anchors in the one range any window could open from (the
    `posttest_anchors` SQL function, keyset-paged, capped at _SCAN_CAP — the
    cap sets `truncated`), then the poses and the recorded skips of the
    students those windows belong to (user ids per `in.(…)`, paged). None
    when a read failed — the funnel is then unknown, never zeros that read as
    "nothing was due"."""
    start, end = _parse_ts(from_iso), _parse_ts(to_iso)
    if start is None or end is None:
        return None
    opens = [o for _, o, _ in window_bounds()]
    try:
        anchors, truncated = posttest_anchors(
            anchor_from=start - timedelta(days=max(opens)),
            anchor_to=end - timedelta(days=min(opens)),
            limit=_scan._SCAN_CAP,  # read at call time (tests shrink it)
        )
        due = due_windows(anchors, start=start, end=end)
        users = sorted({d["user_id"] for d in due})
        poses: dict[tuple, dict] = {}
        skips: dict[tuple, str] = {}
        for batch in _batches(users):
            for row in page_all(
                table("posttest_poses"),
                _FUNNEL_POSE_COLS,
                filters={"user_id": _in(batch)},
                order="user_id.asc,node_id.asc,window_days.asc",
            ):
                poses[(row.get("user_id"), row.get("node_id"), row.get("window_days"))] = row
            for row in page_all(
                table("posttest_skips"),
                _FUNNEL_SKIP_COLS,
                filters={"user_id": _in(batch)},
                order="user_id.asc,node_id.asc,window_days.asc",
            ):
                skips[(row.get("user_id"), row.get("node_id"), row.get("window_days"))] = row.get("reason")
    except Exception:
        logger.warning("learning-gain funnel unavailable", exc_info=True)
        return None
    return _FunnelReads(due, poses, skips, truncated)


_ATTEMPT_EVENT = "zpd.attempt"  # spec §13 A133/A134: one hint-unlocking attempt, as judged
#: spec §13 A133: the help ledger's loop rows (learning/help_ledger.py) — poses and help
_LEDGER_COLS = "id,user_id,kind,question_hash,rung,session_id,source,at"


def _session_courses(session_ids: Iterable[str]) -> dict[str, str]:
    """Session id → abstract course id (the session's offering's course),
    for the sessions that have one: bounded `in.(...)` reads of `sessions`,
    then services.academics.offering_course_id per distinct offering (cached)."""
    ids = sorted({str(s) for s in session_ids if s})
    offering: dict[str, str] = {}
    for batch in _batches(ids):
        for row in table("sessions").select("id,offering_id", filters={"id": _in(batch)}) or []:
            if row.get("id") and row.get("offering_id"):
                offering[str(row["id"])] = str(row["offering_id"])
    course = {o: offering_course_id(o) for o in set(offering.values())}
    return {sid: course[o] for sid, o in offering.items() if course.get(o)}


def _help_abuse(
    events: list[dict], steps: list[dict], valid: list[dict], from_iso: str, to_iso: str
) -> HelpAbuse | None:
    """Spec §13 A133 over the range: the help ledger's loop poses and help in
    it, the zpd.attempt / zpd.step events and the non-void evidence the
    endpoint already scanned, and the sessions' courses. Additive: a failed
    read logs a WARNING and answers None — the rest of the report stands."""
    try:
        ledger, truncated = _scan_range(
            "learning_reveals",
            _LEDGER_COLS,
            from_iso,
            to_iso,
            extra_filters={"kind": "in.(posed,help)", "source": f"eq.{HELP_LOOP_SOURCE}"},
            time_column="at",
            order="at.asc,id.asc",
        )
        courses = _session_courses(r.get("session_id") for r in ledger if r.get("kind") == "posed")
        attempts = [e for e in events if e.get("event_type") == _ATTEMPT_EVENT]
        return HelpAbuse(
            **help_abuse_report(ledger, attempts, steps, valid, courses), truncated=truncated
        )
    except Exception:
        logger.warning("admin learning-loop: the help-abuse report could not be built", exc_info=True)
        return None


def _self_explanation(valid: list[dict], from_iso: str, to_iso: str) -> SelfExplanation | None:
    """Spec §13 A139 over the range: the prompts served in it (one ranged
    `learning_self_explanations` scan; never the reply) against the non-void
    evidence the endpoint already scanned. Additive: a failed read logs a
    WARNING and answers None — the rest of the report stands."""
    try:
        prompts, truncated = _scan_range(
            SELF_EXPLAIN_TABLE,
            SELF_EXPLAIN_COLUMNS,
            from_iso,
            to_iso,
            time_column="prompted_at",
            order="prompted_at.asc,id.asc",
        )
        return SelfExplanation(**self_explanation_report(prompts, valid), truncated=truncated)
    except Exception:
        logger.warning("admin learning-loop: the self-explanation report could not be built", exc_info=True)
        return None
#: Spec §13 A141: a loop check posed a multi-concept item (services/varied_practice.py)
_MULTI_SERVED_EVENT = "learn.multi_concept_served"
#: the stored multi-concept items (apex_key from 20261108185101)
_MULTI_ITEM_COLS = "id,course_id,question_hash,lint_flags,canonical_verified"
#: the evidence a multi-concept outcome is read from (item_stats' unassisted rule)
_MULTI_EVIDENCE_COLS = (
    "id,check_item_id,correct,assisted,max_rung,same_session_recheck,weight,confidence,"
    "channel,reason,question_hash,created_at,graph_nodes!inner(user_id,course_id)"
)


class _MultiItemsRead:
    """A page_all handle over check_items' multi-concept rows (apex_key set)."""

    def select_with_count(self, *args, **kwargs):
        return table("check_items").select_with_count(*args, **kwargs)


def _multi_concept(from_iso: str, to_iso: str, retired) -> tuple[MultiConcept | None, bool]:
    """Spec §13 A141: the multi-concept items stored, served in the range and
    their outcomes in it, per course and overall with every n
    (learning/multi_concept_report.py). One read of the stored items, one
    events scan, and — only when such items exist — one evidence scan of their
    rows; void rows left out (A123: `retired`). Additive: a failed read (a
    database before the migration among them) answers None, the rest of the
    report stands."""
    try:
        items = list(
            page_all(
                _MultiItemsRead(), _MULTI_ITEM_COLS, filters={"apex_key": "not.is.null"}, order="id"
            )
        )
        served, served_truncated = _scan_range(
            "events",
            "event_type,user_id,payload,created_at",
            from_iso,
            to_iso,
            extra_filters={"event_type": f"eq.{_MULTI_SERVED_EVENT}"},
        )
        evidence: list[dict] = []
        evidence_truncated = False
        ids = [r["id"] for r in items if r.get("id")]
        for batch in _batches(ids):
            rows, cut = _scan_range(
                "node_mastery_events",
                _MULTI_EVIDENCE_COLS,
                from_iso,
                to_iso,
                extra_filters={"event_type": "eq.evidence", "check_item_id": _in(batch)},
            )
            evidence.extend(r for r in rows if not is_void_row(r, retired))
            evidence_truncated = evidence_truncated or cut
        report = multi_concept_report(items, [_payload(e) for e in served], evidence)
        return MultiConcept(**report), served_truncated or evidence_truncated
    except Exception:
        logger.warning("admin learning-loop: the multi-concept report could not be built", exc_info=True)
        return None, False


#: A137: the llm_usage columns the cost report reads (course_id from
#: 20261108163653; a database before it is read without the column)
_USAGE_COST_COLS = "id,task,cost_usd,user_id,session_id,course_id,created_at"


class _CostRead(NamedTuple):
    report: CostPerGain | None
    truncated: bool


def _http_error_text(exc: BaseException) -> str:
    """The message plus, for db.connection's httpx.HTTPStatusError, its body."""
    try:
        return f"{exc} {exc.response.text}"  # type: ignore[attr-defined]
    except Exception:
        return str(exc)


def _range_days(from_iso: str, to_iso: str) -> float | None:
    def parse(value: str) -> datetime:
        ts = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)

    try:
        return (parse(to_iso) - parse(from_iso)).total_seconds() / 86400
    except ValueError:
        return None


def _cost_per_gain(
    from_iso: str, to_iso: str, poses: list[dict], pretests: dict[str, bool], retired
) -> _CostRead:
    """A137: the loop tasks' llm_usage rows in the range (one paged read,
    task-filtered), the courses of the sessions behind rows that name no course
    of their own (sessions by id in `in.(…)` batches, offering → course), and
    learning/cost_per_gain.py over them and the learning gain's own inputs.
    Any read failure leaves the field None (one WARNING), never the report."""
    filters = {"task": f"in.({','.join(LOOP_TASKS)})"}
    order = "created_at.asc,id.asc"
    try:
        try:
            usage, truncated = _scan_range(
                "llm_usage", _USAGE_COST_COLS, from_iso, to_iso, extra_filters=filters, order=order
            )
        except Exception as exc:
            if "course_id" not in _http_error_text(exc):
                raise
            logger.warning(
                "admin_analytics: llm_usage has no course_id column (migration "
                "20261108163653 not applied?); session-less loop spend is unattributed"
            )
            usage, truncated = _scan_range(
                "llm_usage",
                _USAGE_COST_COLS.replace(",course_id", ""),
                from_iso,
                to_iso,
                extra_filters=filters,
                order=order,
            )
        sessions = sorted(
            {str(r["session_id"]) for r in usage if r.get("session_id") and not r.get("course_id")}
        )
        session_courses: dict[str, str] = {}
        for batch in _batches(sessions):
            for row in table("sessions").select("id,offering_id", filters={"id": _in(batch)}) or []:
                course = offering_course_id(row.get("offering_id") or "")
                if course:
                    session_courses[str(row.get("id"))] = course
        report = cost_per_gain(
            usage,
            session_courses,
            poses,
            pretests,
            range_days=_range_days(from_iso, to_iso),
            retired=retired,
        )
        return _CostRead(CostPerGain(**report), truncated)
    except Exception:
        logger.warning("admin_analytics: the loop's spend could not be read", exc_info=True)
        return _CostRead(None, False)


def _ceiling_compliance(steps: list[dict]) -> CeilingCompliance:
    n = ok = 0
    for row in steps:
        p = _payload(row)
        used, ceiling = _rung_int(p.get("max_rung_used")), _rung_int(p.get("ceiling"))
        if used is None or ceiling is None:
            continue
        n += 1
        ok += int(used <= ceiling)
    return CeilingCompliance(steps=n, compliant=ok, rate=ok / n if n else None)


def learning_loop_report(from_iso: str, to_iso: str) -> LearningLoopKpis:
    """The body of GET /api/admin/analytics/learning-loop over a resolved
    range (routes/admin_analytics.py::learning_loop_kpis has the full
    contract and does the admin check)."""
    events, events_truncated = _scan_range(
        "events",
        "event_type,user_id,payload,created_at",
        from_iso,
        to_iso,
        extra_filters={
            "event_type": f"in.({_STEP_EVENT},{_LEAK_EVENT},{_REVEAL_EVENT},{_ATTEMPT_EVENT})"
        },
    )
    evidence, evidence_truncated = _scan_range(
        "node_mastery_events",
        _EVIDENCE_COLS,
        from_iso,
        to_iso,
        extra_filters={"event_type": "eq.evidence"},
    )
    poses, poses_truncated = _scan_range(  # A112: post-test outcomes answered in the range
        "posttest_poses",
        _POSE_COLS,
        from_iso,
        to_iso,
        time_column="answered_at",
        order="answered_at.asc,user_id.asc,node_id.asc,window_days.asc",
    )
    quiz_ask = quiz_ask_session_ids(table("sessions"), to_iso=to_iso)  # A106
    steps = [e for e in events if e.get("event_type") == _STEP_EVENT]
    caught = sum(1 for e in events if e.get("event_type") == _LEAK_EVENT)
    reveals = [_payload(e) for e in events if e.get("event_type") == _REVEAL_EVENT]
    served = sum(len(p.get("question_hashes") or []) for p in reveals)
    unscanned = sum(1 for p in reveals if p.get("unscanned") is True)
    in_band, banded = _in_band_share(steps)
    compliance = _ceiling_compliance(steps)
    earnest = EarnestRevise(**earnest_revise(steps))
    funnel_reads = _funnel_reads(from_iso, to_iso)  # A126
    # A123: ONE void rule for every evidence read — graded against an item
    # staff retired. An outcome on one is excluded (and counted), so its anchor
    # is never read for a pretest; a void anchor is no pretest; an answered
    # funnel pose on one is counted as excluded, never as answered.
    retired = _void_items(
        evidence, poses, funnel_reads.poses.values() if funnel_reads is not None else ()
    )
    valid = [row for row in evidence if not is_void_row(row, retired)]
    excluded_void = sum(
        1 for row in evidence if is_void_row(row, retired) and calibration_eligible(row) is not None
    )
    pretests = _pretests([p for p in poses if not pose_is_void(p, retired)], retired)
    funnel = (
        posttest_funnel(
            funnel_reads.due,
            funnel_reads.poses,
            funnel_reads.skips,
            now=datetime.now(timezone.utc),
            retired=retired,
        )
        if funnel_reads is not None
        else None
    )
    funnel_truncated = funnel_reads.truncated if funnel_reads is not None else False
    # spec §13 A133: help abuse, over the same events and non-void evidence
    help_abuse = _help_abuse(events, steps, valid, from_iso, to_iso)
    cost = _cost_per_gain(from_iso, to_iso, poses, pretests, retired)  # A137
    self_explanation = _self_explanation(valid, from_iso, to_iso)  # spec §13 A139
    multi, multi_truncated = _multi_concept(from_iso, to_iso, retired)  # A141
    return LearningLoopKpis(
        range=Range(from_=from_iso, to=to_iso),
        steps_total=len(steps),
        banded_steps=banded,
        in_band=in_band,
        in_band_share=in_band / banded if banded else None,
        htc_k_trend=_htc_k_trend(steps, to_iso),
        unassisted_next_session=NextSessionSuccess(**_next_session_rate(valid, quiz_ask)),
        caught_leaks=caught,
        served_reveals=served,
        unscanned_turns=unscanned,
        ceiling_compliance=compliance,
        earnest_revise=earnest,
        gates=Gates(
            zero_leaks=served <= GATE_LEAKS_MAX,
            ceiling_compliance_ok=compliance.rate is not None
            and compliance.rate >= GATE_CEILING_COMPLIANCE_MIN,
            earnest_revise_ok=None if earnest.gate == "inconclusive" else earnest.gate == "pass",
        ),
        calibration=Calibration(**bkt_calibration(valid), excluded_void=excluded_void),
        # A123 × A127: the one void rule here too — a confidence stated on a
        # grade against a retired item is no calibration evidence either
        confidence_calibration=ConfidenceCalibration(**confidence_calibration(valid)),
        learning_gain=LearningGain(**learning_gain(poses, pretests, retired=retired), funnel=funnel),
        cost_per_gain=cost.report,
        slot_warnings=[SlotWarning(**w) for w in slot_warnings()],
        help_abuse=help_abuse,
        self_explanation=self_explanation,
        multi_concept=multi,
        truncated=events_truncated
        or evidence_truncated
        or poses_truncated
        or funnel_truncated
        or bool(help_abuse is not None and help_abuse.truncated)
        or bool(self_explanation is not None and self_explanation.truncated)
        or cost.truncated
        or multi_truncated,
    )

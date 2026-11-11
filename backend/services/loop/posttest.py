"""The post-test handlers (PKG-14): start, answer, shown and due (with its
per-process due cache, A126).
"""
from __future__ import annotations

import asyncio
import copy
import logging
import threading
import time
import uuid
from datetime import datetime
from services.loop.errors import HTTPException
from starlette.requests import Request
import config
from agents.deps import SaplingDeps
from agents.tools.check import CHANNEL_FOR_FORMAT, CheckAnswer, grade_answer
from db.connection import table
from learning import arms, policy, zpd_events
from learning.checks import posttest_skip_reason
from learning.evidence import flush_pending
from learning.evidence_transaction import EvidenceItemRetired
from learning.ladder import Rung
from learning.learning_gain import answer_latency_s, clamp_visibility
from learning.posttest_store import posttest_anchors
from learning.misconceptions import recheck_after_release
from learning.loop_state_store import evidence_spans, recent_evidence, reported_hashes
from services.loop.posed import _ts
from learning.help_ledger import mark_graded, record_posed
from learning.params import (
    POSTTEST_DUE_CACHE_S,
    POSTTEST_MAX_ITEMS,
    RUNG_ASSISTED_MIN,
    RUNG_NO_CREDIT_MIN,
)
from models import PosttestAnswerBody, PosttestShownBody, PosttestStartBody
from services.auth_guard import get_session_user_id, guard_off_loop
from services.check_item_service import items_for_concepts
from services.feature_flags import flag_on
from services.graph_service import _normalize_concept
from services.request_limits import check_rate_limit

from services.loop.state import _arm_for, _gate, _item_like, _request_id
from services.loop.learner import _band_for, _learner_state
from services.loop.served import _POSES
from services.loop.reveals import _ledger, _refloor, _reveal_floor
from services.loop.practice import _pose_payload
from services.loop.checkpoint import _RETIRED_DETAIL
from services.loop.posttest_poses import (
    _answer_pose,
    _claim_pose,
    _course_nodes,
    _due_nodes,
    _iso_z,
    _new_pose,
    _NOT_A_POSTTEST_ITEM,
    _open_posed_item,
    _posttest_exposed,
    _posttest_now,
    _posttest_plans,
    _read_poses,
    _record_poses,
    _record_skips,
    _release_pose,
    _skip_row,
    _stamp_served,
    _window_choice,
)

#: Every module of the package logs as the route always did (the ops-log
#: mirror and the tests key on this logger name).
logger = logging.getLogger("routes.learn_loop")


def posttest_start(body: PosttestStartBody, request: Request) -> dict:
    """Rung 3 (spec §10) at FIXED follow-up windows (A112): this student's
    post-test items for one course. A concept is due when `now` falls in one of
    POSTTEST_WINDOWS_DAYS counted from its FIRST graded evidence (the journal's
    earliest evidence row: practice cannot postpone it) and that window is not
    answered yet — each window is posed at most once per student, concept and
    window, a window the student was away for is skipped, and the last one
    closes POSTTEST_LAST_WINDOW_CLOSE_DAYS after the anchor (A126). The item is
    a fresh protected reserve matched to the student's pretest item, else a
    fresh fallback (A126, `_window_choice`; a confirmed key, then the lint
    tier, A124/A113, so an `unsourced` item comes after one with its sources,
    A128) — never one seen or revealed (A23), reported (A113), or held or
    retired (A124, A123: a held item is not in the course's items); an
    unanswered pose's item stays bound to the node while it is fresh (A93) —
    never once reported (an open pose of a reported item counts as no pose,
    like a withdrawn one). A due window with nothing fresh is skipped and the
    skip recorded with its reason (`posttest_skips`, A126). Open poses first,
    then the earliest-opened
    windows, at most POSTTEST_MAX_ITEMS. It COMMITS when opened (A87): the pose
    records its window, its anchor, the days since the concept's last evidence
    and how its item was chosen, and a repeat start returns the same item for a
    node with an open pose — never a fresh one. The pose only: the prompt
    verbatim and an mc_reason item's options, never a key or a reference. No
    brief, no RAG, no tutor, no session row, no model call. Rate-limited (A20)."""
    if not body.user_id:
        body.user_id = get_session_user_id(request)
    _gate(body.user_id, request)
    now = _posttest_now()
    nodes = _course_nodes(body.user_id, body.course_id)
    poses = _read_poses(body.user_id, body.course_id)
    spans = evidence_spans(body.user_id, body.course_id)
    anchors = {node: span.first_at for node, span in spans.items()}
    due = _due_nodes(nodes, poses, anchors, now)
    if not due:
        return {"items": []}
    by_key = items_for_concepts(body.course_id, sorted({nodes[n] for n in due}))
    # A113: read once — an item the student reported is never posed again: an
    # open pose of it counts as no pose, a bound one is excluded (the choice
    # excludes it too; a held or retired item is gone from the course's items)
    reported = set(reported_hashes(body.user_id))
    plans = _posttest_plans(
        due, poses, anchors, lambda node: by_key.get(nodes[node]) or [], now, reported
    )
    exposed = _posttest_exposed(body.user_id) if any(p[2] is None for p in plans) else set()
    excluded = exposed | reported
    out: list[dict] = []
    new: list[dict] = []
    skips: list[dict] = []
    for _, node, item, window in plans:
        if item is None:
            items = by_key.get(nodes[node]) or []
            span = spans[node]
            # A126: the student's pretest item — the concept's first graded item
            pretest = next((i for i in items if i.question_hash == span.first_hash), None)
            choice = _window_choice(items, poses.get(node) or {}, excluded, window, pretest)
            if choice is None:  # nothing fresh left for this concept: skipped, and why
                reason = posttest_skip_reason(items, exposed=exposed)
                skips.append(_skip_row(body.user_id, body.course_id, node, window, reason, now))
                continue
            new.append(_new_pose(body.user_id, body.course_id, node, window, choice, span, now))
            item = choice.item
        out.append({"node_id": node, **_pose_payload(item)})
        if len(out) >= POSTTEST_MAX_ITEMS:
            break
    _record_poses(new)
    _record_skips(skips)
    for row in new:  # A93: posed — in the scan set until graded
        _ledger(record_posed, body.user_id, row["question_hash"], source="posttest")
    clear_posttest_due_cache(body.user_id)
    return {"items": out}


def _posttest_node(user_id: str, node_id: str) -> dict:
    rows = (
        table("graph_nodes").select(
            "id,course_id,concept_name",
            filters={"id": f"eq.{node_id}", "user_id": f"eq.{user_id}"},
            limit=1,
        )
        or []
    )
    if not rows or not rows[0].get("course_id"):
        raise HTTPException(status_code=404, detail="Node not found")
    return rows[0]


def _posttest_reported(user_id: str, question_hash: str) -> bool:
    """A113 across A112's windows: an item the student reported is never posed
    again, so an open pose of it is not answerable either — /posttest/start
    replaces such a pose in its own window, but one left open in an EARLIER
    window (the next window was posed with a fresh item) would otherwise still
    be claimable. Read before the claim: a refusal claims and records nothing.
    An unreadable reported set refuses too (503, fail closed)."""
    try:
        return question_hash in reported_hashes(user_id)
    except Exception:
        logger.warning("post-test: reported items unread; the answer is refused", exc_info=True)
        raise HTTPException(status_code=503, detail="post-test unavailable; retry") from None


def _posttest_floor(user_id: str, node_id: str, item, posed_at: datetime | None) -> int:
    """A88/A89: the open post-test item's grading floor — `_reveal_floor`
    (revealed → no credit; an unscanned marker since the pose → assisted), and
    RUNG_NO_CREDIT_MIN when the node has ANY evidence journaled after the pose
    (the student worked the concept in between; owner 2). An unreadable pose
    time or evidence read is assisted at least (fail closed)."""
    floor = _reveal_floor(user_id, item, posed_at)
    if posed_at is None:
        return max(floor, RUNG_ASSISTED_MIN)
    since = recent_evidence(user_id, node_id, since=_iso_z(posed_at))
    if since is None:
        logger.warning("post-test evidence read failed; the grade is assisted")
        return max(floor, RUNG_ASSISTED_MIN)
    if since:
        return max(floor, RUNG_NO_CREDIT_MIN)
    return floor


# crisis support: a crisis answer leaves the pose open and unclaimed, nothing graded
async def posttest_answer(body: PosttestAnswerBody, request: Request):
    """Grade the node's OPEN post-test pose (A87) through grade_answer (A16):
    ceiling H0, max_rung 0, no session — unless the item was revealed or seen
    since it was posed, when the grade carries no unassisted credit (A86). An
    item the student reported is never graded here (A113, any window: 409
    before the claim, `_posttest_reported`).
    The pose is claimed by one conditional UPDATE, so it is graded once; a
    refusal (A33) releases the claim and asks again (never an idk here); an
    outage or the grade cap releases it too and is a 503 with nothing recorded
    for either outcome (invariant 28). A126: the pose also records the answer
    latency (answered_at − the served_at /posttest/shown stamped) and the
    page-hidden telemetry the client sends — untrusted, clamped
    (learning_gain.clamp_visibility), and never read by the grade."""
    if not body.user_id:
        body.user_id = await guard_off_loop(get_session_user_id, request)
    loop_on = await guard_off_loop(_gate, body.user_id, request)
    node = await asyncio.to_thread(_posttest_node, body.user_id, body.node_id)  # #117
    course_id, key = node["course_id"], _normalize_concept(node.get("concept_name") or "")
    items = items_for_concepts(course_id, [key]).get(key) or []
    item = next((i for i in items if i.question_hash == body.question_hash), None)
    if item is None:
        raise HTTPException(status_code=404, detail="check item not found")
    if not body.idk:
        if item.format == "mc_reason" and not body.selected_option:
            raise HTTPException(status_code=422, detail="an mc_reason answer needs selected_option")
        if item.format != "mc_reason" and not body.answer:
            raise HTTPException(status_code=422, detail="a free answer needs answer")
    if _posttest_reported(body.user_id, item.question_hash):
        raise HTTPException(status_code=409, detail=_NOT_A_POSTTEST_ITEM)
    now = _posttest_now()
    claim = str(uuid.uuid4())
    pose = await asyncio.to_thread(  # #117: off the event loop
        _claim_pose, body.user_id, body.node_id, item.question_hash, claim, now
    )
    if pose is None:  # not posed, answered, claimed, or expired (A89) → 409
        raise HTTPException(status_code=409, detail=_NOT_A_POSTTEST_ITEM)
    answered = False
    try:
        floor = Rung(_posttest_floor(body.user_id, body.node_id, item, _ts(pose.get("posed_at"))))
        band, p_before = _band_for(body.user_id, body.node_id)
        deps = SaplingDeps(
            user_id=body.user_id,
            course_id=course_id,
            supabase=None,
            request_id=_request_id(request),
            session_id=None,
            feature="loop_posttest",
            learning_loop=loop_on,
        )
        answer = CheckAnswer(
            question_hash=item.question_hash,
            answer_text=body.answer,
            selected_option=body.selected_option,
            reason=body.reason,
            idk=body.idk,
        )
        # A76: every grading caller decides the re-check through the one helper
        # (no session log here: the node's journal decides)
        recheck = recheck_after_release(body.user_id, body.node_id, None, now=now, item=item)
        outcome = await grade_answer(
            _item_like(item),
            answer,
            deps=deps,
            node_id=body.node_id,
            max_rung=int(floor),
            same_session_recheck=recheck,
        )
        if outcome.refused:  # A33: checked first — a refused outcome is also unavailable
            return {"graded": False, "refused": True}
        if outcome.unavailable:
            raise HTTPException(status_code=503, detail="grader unavailable")
        # m1/m2: the claim is re-validated and the pose CLOSED before the flush —
        # a taken-over claim writes nothing; a failed flush never reopens the pose
        # A93: the help floor re-read inside the claim, right before the write
        floor = Rung(
            _refloor(deps.pending_evidence, body.user_id, item, _ts(pose.get("posed_at")), int(floor))
        )
        answered_at = _posttest_now()
        # A126: telemetry beside the outcome, bounded by the server's own clock:
        # the item cannot have been hidden for longer than it was on screen
        served = _ts(pose.get("served_at"))
        shown_from = served or _ts(pose.get("posed_at"))
        hidden_count, hidden_s = clamp_visibility(
            body.hidden_count,
            body.hidden_s,
            (answered_at - shown_from).total_seconds() if shown_from else None,
        )
        answered = await asyncio.to_thread(  # #117: off the event loop
            _answer_pose,
            body.user_id,
            body.node_id,
            claim,
            answered_at,
            correct=bool(outcome.correct),
            max_rung=int(floor),
            latency_s=answer_latency_s(served, answered_at),
            hidden_count=hidden_count,
            hidden_s=hidden_s,
        )
        if not answered:
            raise HTTPException(status_code=409, detail=_NOT_A_POSTTEST_ITEM)
        try:
            changes = flush_pending(deps, course_id)  # ONE call: the post-test's only evidence write
        except EvidenceItemRetired:
            # A123: staff retired the item while it was graded — nothing was
            # written (the grade is void); the pose stays answered, and its
            # outcome is left out of the learning gain by the void rule
            raise HTTPException(status_code=409, detail=_RETIRED_DETAIL) from None
        _ledger(mark_graded, body.user_id, item.question_hash)
    finally:
        if not answered:
            try:
                await asyncio.to_thread(_release_pose, body.user_id, body.node_id, claim)
            except Exception:
                logger.warning("post-test claim on %s not released", body.node_id, exc_info=True)
        clear_posttest_due_cache(body.user_id)
    await asyncio.to_thread(  # #117: off the event loop
        _emit_posttest_step, body, request, item, outcome, band, p_before, changes, floor
    )
    return {"correct": bool(outcome.correct), "confidence": outcome.confidence}


def _posttest_light_limit(user_id: str) -> None:
    """A126: the cheap per-user limit (services/request_limits' in-process
    sliding window) on the two no-model post-test routes — the display stamp
    and the "due" read. Not the A20 rate limit: no model runs behind them."""
    retry = check_rate_limit(
        f"loop_posttest_light:{user_id}", limit=config.LOOP_PROBE_PLAN_READS_PER_MIN, window_sec=60
    )
    if retry is not None:
        raise HTTPException(
            status_code=429, detail="too many requests", headers={"Retry-After": str(retry)}
        )


def posttest_shown(body: PosttestShownBody, request: Request) -> dict:
    """A126: the client shows an open pose's item — stamp its `served_at` (the
    first display only; the server's clock), so the answer's latency is
    answered_at − served_at. Writes nothing else: no evidence, no ledger, no
    model. An item with no open pose stamps nothing (`served: false`); a failed
    stamp logs and leaves the latency unknown, never an error the student sees."""
    if not body.user_id:
        body.user_id = get_session_user_id(request)
    _gate(body.user_id, request)
    _posttest_light_limit(body.user_id)
    try:
        stamped = _stamp_served(body.user_id, body.node_id, body.question_hash, _posttest_now())
    except Exception:
        logger.warning("post-test display not stamped", exc_info=True)
        stamped = False
    return {"served": stamped}


# ── "A retention check is due" (spec §13 A126) ───────────────────────────────

#: Client-visible flag (services/feature_flags.py): off → GET /posttest/due
#: 404s and the app shows no badge. Pushing students toward the retention check
#: changes the measurement protocol (pull → push), so it is switched on
#: deliberately — at a trial boundary — not by a deploy.
RETENTION_DUE_FLAG = "retention_due_badge"


#: user id → (monotonic expiry, payload): a per-process TTL cache (CLAUDE.md
#: #98): POSTTEST_DUE_CACHE_S, cleared for the student by /posttest/start and
#: /posttest/answer (the routes that change what is due); other workers and
#: evidence written elsewhere converge within the TTL.
_DUE_CACHE: dict[str, tuple[float, dict]] = {}


_DUE_CACHE_MAX = 10_000


_DUE_LOCK = threading.Lock()


def clear_posttest_due_cache(user_id: str | None = None) -> None:
    """Drop one student's cached "due" answer (every student's with None)."""
    with _DUE_LOCK:
        if user_id is None:
            _DUE_CACHE.clear()
        else:
            _DUE_CACHE.pop(user_id, None)


def _due_cache_get(user_id: str) -> dict | None:
    with _DUE_LOCK:
        hit = _DUE_CACHE.get(user_id)
        if hit is None or hit[0] <= time.monotonic():
            return None
        return copy.deepcopy(hit[1])


def _due_cache_put(user_id: str, payload: dict) -> None:
    with _DUE_LOCK:
        if len(_DUE_CACHE) >= _DUE_CACHE_MAX and user_id not in _DUE_CACHE:
            _DUE_CACHE.pop(min(_DUE_CACHE, key=lambda k: _DUE_CACHE[k][0]))
        _DUE_CACHE[user_id] = (time.monotonic() + POSTTEST_DUE_CACHE_S, copy.deepcopy(payload))


def _read_student_poses(user_id: str) -> dict[str, dict[int, dict]]:
    """node id → window → the student's pose rows, every course (one read)."""
    rows = table(_POSES).select(
        "node_id,course_id,window_days,question_hash,posed_at,answered_at",
        filters={"user_id": f"eq.{user_id}"},
    )
    poses: dict[str, dict[int, dict]] = {}
    for r in rows or []:
        if r.get("node_id"):
            poses.setdefault(r["node_id"], {})[int(r["window_days"])] = r
    return poses


def _retention_due(user_id: str, now: datetime) -> dict:
    """Does the student have a retention check to take now — an open pose
    whose item can still be answered, or a due, unanswered window with an item
    /posttest/start would pose? The same rules as /posttest/start
    (`_due_nodes`, `_open_posed_item`, `_window_choice`), never a pose: nothing
    is written. Cheap first: one anchors read and one poses read; only when
    some node is a candidate, its courses' items and the exclusion sets."""
    rows, _ = posttest_anchors(user_id=user_id)
    anchors: dict[str, dict] = {}
    anchor_at: dict[str, datetime] = {}
    for row in rows:
        at = _ts(row.get("anchor_at"))
        if row.get("node_id") and row.get("course_id") and at is not None:
            anchors[row["node_id"]] = row
            anchor_at[row["node_id"]] = at
    poses = _read_student_poses(user_id)
    due = _due_nodes(anchors, poses, anchor_at, now)
    if not due:
        return {"due": False, "course_ids": []}
    by_course: dict[str, list[str]] = {}
    for node in due:
        by_course.setdefault(anchors[node]["course_id"], []).append(node)
    reported = set(reported_hashes(user_id))
    excluded: set[str] | None = None
    courses = []
    for course_id, course_nodes in sorted(by_course.items()):
        keys = {n: _normalize_concept(anchors[n].get("concept_name") or "") for n in course_nodes}
        by_key = items_for_concepts(course_id, sorted(set(keys.values())))
        for node in course_nodes:
            items = by_key.get(keys[node]) or []
            node_poses = poses.get(node) or {}
            if _open_posed_item(node_poses, items, now, reported) is not None:
                courses.append(course_id)
                break
            if due[node] is None:
                continue
            if excluded is None:
                excluded = _posttest_exposed(user_id) | reported
            if _window_choice(items, node_poses, excluded, due[node], None) is not None:
                courses.append(course_id)
                break
    return {"due": bool(courses), "course_ids": courses}


def posttest_due(request: Request, user_id: str = "") -> dict:
    """A126: {due, course_ids} — whether the student has a retention check to
    take now (`_retention_due`), for the app's "retention check due" badge on
    Study and the Dashboard. Behind the `retention_due_badge` flag (off → 404)
    and the loop gate; cached per student for POSTTEST_DUE_CACHE_S. Read-only:
    it never opens a pose. A failed read is a 503 (the badge stays hidden),
    never a "nothing due" it cannot vouch for."""
    if not user_id:
        user_id = get_session_user_id(request)
    _gate(user_id, request)
    if not flag_on(RETENTION_DUE_FLAG, user_id):
        raise HTTPException(status_code=404, detail="Not found")
    cached = _due_cache_get(user_id)
    if cached is not None:
        return cached
    _posttest_light_limit(user_id)
    try:
        payload = _retention_due(user_id, _posttest_now())
    except Exception:
        logger.warning("retention-due read failed", exc_info=True)
        raise HTTPException(status_code=503, detail="retention status unavailable") from None
    _due_cache_put(user_id, payload)
    return payload


def _emit_posttest_step(body, request, item, outcome, band, p_before, changes, floor: Rung) -> None:
    """zpd.step for one graded post-test answer. p_known_after is read honestly
    (m8): the flush's result, else the node's stored state now — never a prior
    for a node with no row; when neither exists the step is not emitted (fail
    closed, as _emit_step does)."""
    correct = bool(outcome.correct)
    after = next(
        (c.get("after") for c in changes or [] if isinstance(c, dict) and c.get("after") is not None),
        None,
    )
    try:
        if after is None:
            state = _learner_state(body.user_id, body.node_id)
            if state is None:
                raise LookupError("no learner-state row")
            after = state.p_known
        after = float(after)
    except Exception:
        logger.warning("zpd.step not emitted for post-test %s: no p_known_after", item.question_hash)
        return
    evidence = outcome.evidence or {}
    zpd_events.emit_zpd_step(
        user_id=body.user_id,
        request_id=_request_id(request),
        concept_id=body.node_id,
        question_hash=item.question_hash,
        phase="posttest",
        channel=evidence.get("channel") or CHANNEL_FOR_FORMAT[item.format],
        band=band,
        # H0 — or, for an item a teach turn revealed, the rung it was graded at (A86)
        ceiling=floor,
        ceiling_reason=policy.CeilingReason.POSTTEST,
        first_attempt_correct=correct,
        n_attempts=1,
        max_rung_used=floor,
        rungs=[],
        time_to_first_attempt_ms=None,
        time_to_correct_ms=None,
        independent_time_ms=None,
        assisted=int(floor) >= RUNG_ASSISTED_MIN,
        confidence=outcome.confidence,
        fsrs_rating=policy.evidence_for_rung(correct, floor).fsrs_rating,
        p_known_before=p_before,
        p_known_after=after,
        r_before=None,
        item_difficulty=item.difficulty,
        grader_backend=outcome.grader_backend,
        variant=arms.variant_for(body.user_id, body.node_id, _arm_for(body.user_id, request)),
    )  # no tier: no tutor turn ran (omitted, never zeroed)

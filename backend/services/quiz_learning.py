"""The quiz in the learning system: the reads and model calls behind the five
quiz flags (learning loop spec §13 A143-A147). The decisions are pure and live
in learning/quiz_plan.py and learning/quiz_gates.py; this module reads the
student's state for them, runs the item checks, and writes misconceptions.

- A143 `concept_plan`: the quiz home's proposals from the learner model.
- A144 `generation_plan`: what each planned question asks for.
- A145 `gate_questions`: the A119 concept check and the A124 blind solve on
  generated questions, on the `quiz_check` slot.
- A146 `exposure_before` + `misconceptions_after_submit`: record and resolve.
- A147 `skill_snapshot` + `results_block`: what the results say.

Every read degrades instead of failing a quiz: a plan read that fails falls
back to the BKT prior or to nothing, a check that fails leaves its questions
practice-only (never evidence), and a misconception read that fails records
or closes nothing. `learning.misconceptions` is imported inside the functions
that write misconceptions: it brings the loop-state store with it, which the
app must not load at boot (tests/test_learning_zpd_policy.py's app-load probe).
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from db.connection import page_all, pg_quote_value, table
from learning import item_keys, quiz_gates, quiz_plan
from learning.evidence import PREREQ_RELATIONSHIP_TYPE
from learning.learner_state import read_states
from learning.params import (
    BKT_L0,
    EDGE_PREREQ_SOURCE_IS_PREREQ,
    MISCONCEPTION_RECENT_DAYS,
    RECHECK_RELEASE_WINDOW_HOURS,
    RUNG_NO_CREDIT_MIN,
)
from services import events_service

logger = logging.getLogger("sapling.quiz_learning")

#: The five flags (services/feature_flags.py REGISTRY).
CONCEPT_PLAN_FLAG = "quiz_concept_plan"
PLANNED_QUESTIONS_FLAG = "quiz_planned_questions"
ITEM_GATES_FLAG = "quiz_item_gates"
MISCONCEPTIONS_FLAG = "quiz_misconceptions"
RESULTS_ROUTING_FLAG = "quiz_results_routing"

#: The model slot every quiz check runs on (agents/_providers.py).
CHECK_TASK = "quiz_check"
#: llm_usage.feature of each check run.
VERIFY_FEATURE = "quiz_check_verify"
SOLVE_FEATURE = "quiz_check_solve"
MATCH_FEATURE = "quiz_check_key_match"

#: A quiz question's identity in the misconception store's check_item_id
#: column (A146): a quiz question is no check item, so it goes under its own
#: namespace — A127's "recorded on another item" filter then tells a quiz
#: question from every check item and from every other quiz question.
QUIZ_ITEM_PREFIX = "quiz:"


def quiz_item_id(question_hash: str) -> str:
    return f"{QUIZ_ITEM_PREFIX}{question_hash}"


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ── shared reads ────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class _Node:
    id: str
    name: str
    course_id: str | None


class _NodesRead:
    """`graph_nodes` behind page_all (the connection allows the table only as
    a direct read)."""

    def select_with_count(self, *args, **kwargs):
        return table("graph_nodes").select_with_count(*args, **kwargs)


class _EdgesRead:
    def select_with_count(self, *args, **kwargs):
        return table("graph_edges").select_with_count(*args, **kwargs)


def _nodes(user_id: str, course_id: str | None) -> list[_Node]:
    """The student's concept nodes, in one course or all. Every stored
    `graph_nodes` row is a concept: a subject root is never stored, only drawn
    by the graph read (graph_service.get_graph)."""
    filters = {"user_id": f"eq.{user_id}"}
    if course_id:
        filters["course_id"] = f"eq.{course_id}"
    return [
        _Node(row["id"], row.get("concept_name") or "", row.get("course_id"))
        for row in page_all(_NodesRead(), "id,concept_name,course_id", filters=filters, order="id")
        if row.get("id")
    ]


def _prereq_edges(user_id: str, node_ids: Iterable[str]) -> list[tuple[str, str]]:
    """(prerequisite, dependent) pairs among `node_ids`, oriented by
    EDGE_PREREQ_SOURCE_IS_PREREQ — the loop planner's read."""
    keep = set(node_ids)
    out = []
    for row in page_all(
        _EdgesRead(),
        "id,source_node_id,target_node_id",
        filters={"user_id": f"eq.{user_id}", "relationship_type": f"eq.{PREREQ_RELATIONSHIP_TYPE}"},
        order="id",
    ):
        src, tgt = row.get("source_node_id"), row.get("target_node_id")
        if src in keep and tgt in keep and src != tgt:
            out.append((src, tgt) if EDGE_PREREQ_SOURCE_IS_PREREQ else (tgt, src))
    return out


def _open_misconceptions(user_id: str) -> list[dict]:
    """The student's open misconceptions seen within MISCONCEPTION_RECENT_DAYS
    (the loop readers' window, learning/misconceptions.py::open_for), keys
    only. [] on a failed read."""
    since = (_now() - timedelta(days=MISCONCEPTION_RECENT_DAYS)).isoformat()
    try:
        rows = table("misconceptions").select(
            "node_id,wrong_key,count",
            filters={
                "user_id": f"eq.{user_id}",
                "resolved_at": "is.null",
                "last_seen_at": f"gte.{since}",
            },
        ) or []
    except Exception as exc:
        logger.warning("quiz: open misconceptions unreadable: %s", type(exc).__name__)
        return []
    return [r for r in rows if quiz_plan.is_key(r.get("wrong_key")) and r.get("node_id")]


def _concept_states(user_id: str, nodes: Sequence[_Node], now: datetime) -> list[quiz_plan.ConceptState]:
    states = read_states(user_id, [n.id for n in nodes], now=now)
    counts: dict[str, int] = {}
    for row in _open_misconceptions(user_id):
        counts[row["node_id"]] = counts.get(row["node_id"], 0) + 1
    out = []
    for node in nodes:
        st = states.get(node.id)
        out.append(
            quiz_plan.ConceptState(
                node_id=node.id,
                p_known=st.p_known if st else BKT_L0,
                fsrs_s=st.fsrs_s if st else None,
                fsrs_last_review_at=st.fsrs_last_review_at if st else None,
                fsrs_due_at=st.fsrs_due_at if st else None,
                open_misconceptions=counts.get(node.id, 0),
            )
        )
    return out


def _iso(ts: datetime | None) -> str | None:
    return ts.isoformat() if ts else None


# ── A143: the concept plan ─────────────────────────────────────────────────


def concept_plan(user_id: str, course_id: str | None = None, now: datetime | None = None) -> list[dict]:
    """The concepts the quiz proposes, in the learner model's order
    (quiz_plan.rank_concepts). Raises on a failed node or state read: the
    route answers 503 and the home keeps its own ranking."""
    now = now or _now()
    nodes = _nodes(user_id, course_id)
    if not nodes:
        return []
    by_id = {n.id: n for n in nodes}
    states = _concept_states(user_id, nodes, now)
    edges = _prereq_edges(user_id, by_id)
    return [
        {
            "node_id": c.node_id,
            "concept_name": by_id[c.node_id].name,
            "course_id": by_id[c.node_id].course_id,
            "reason": c.reason,
            "p_known": round(c.p_known, 4),
            "band": c.band,
            "due_at": _iso(c.due_at),
            "open_misconceptions": c.open_misconceptions,
        }
        for c in quiz_plan.rank_concepts(states, edges, now)
    ]


# ── A144: what each planned question asks for ──────────────────────────────


#: Where the planned difficulty's p_known came from when the student asked for
#: adaptive and the learner state could not be read: the BKT prior.
FROM_PRIOR = "prior"


@dataclass
class GenerationPlan:
    specs: list[quiz_plan.QuestionSpec]
    keys: list[quiz_plan.MisconceptionKey]
    p_known: float
    source: str  # quiz_plan.FROM_REQUEST / FROM_LEARNER_MODEL / FROM_PRIOR

    @property
    def allowed_keys(self) -> set[str]:
        return {k.key for k in self.keys}

    def spec(self, slot: int) -> quiz_plan.QuestionSpec | None:
        return next((s for s in self.specs if s.slot == slot), None)


def _bank_keys(course_id: str | None, concept_name: str) -> list[tuple[str, str]]:
    """The concept's vetted misconception keys: the `common_wrong` (key, text)
    of every check item a student may be served (held ones never), in the
    bank's order. [] when the course has no items or the read failed."""
    if not course_id:
        return []
    from services.check_item_service import list_items
    from services.graph_service import _normalize_concept

    try:
        items = list_items(course_id, _normalize_concept(concept_name))
    except Exception as exc:
        logger.warning("quiz: check-item keys unreadable: %s", type(exc).__name__)
        return []
    return [(w.key, w.text) for item in items for w in item.common_wrong or []]


def generation_plan(
    user_id: str,
    node_id: str,
    *,
    course_id: str | None,
    concept_name: str,
    count: int,
    requested: str,
    question_format: str,
) -> GenerationPlan:
    """A144: the learner model's choice for one quiz. Never raises: an
    unreadable state plans from the BKT prior (medium), unreadable keys plan
    no targets."""
    source = quiz_plan.difficulty_source(requested)
    p_known = BKT_L0
    try:
        state = read_states(user_id, [node_id]).get(node_id)
        if state is not None:
            p_known = state.p_known
    except Exception as exc:
        logger.warning("quiz: learner state unreadable for the plan: %s", type(exc).__name__)
        if source == quiz_plan.FROM_LEARNER_MODEL:
            source = FROM_PRIOR
    open_keys = [
        (r["wrong_key"], int(r.get("count") or 0))
        for r in _open_misconceptions(user_id)
        if r["node_id"] == node_id
    ]
    keys = quiz_plan.misconception_keys(open_keys, _bank_keys(course_id, concept_name))
    specs = quiz_plan.question_specs(
        count, requested=requested, p_known=p_known, keys=keys, question_format=question_format
    )
    return GenerationPlan(specs=specs, keys=keys, p_known=p_known, source=source)


# ── A145: the item gates ───────────────────────────────────────────────────


def checks_independent(writer_model: str | None = None) -> bool:
    """A124: the blind solve verifies a key only when it runs on a model other
    than the writer's. In real mode the quiz_check slot's resolved model must
    differ from the model that wrote the questions — `writer_model`, the
    request's fast/smart override when it had one (routes/quiz.py
    `_writer_model_name`), else the quiz slot's. Outside real mode the
    scripted handlers stand in for both."""
    from agents._providers import _bare_model_name, model_mode, model_name_for

    if model_mode() != "real":
        return True
    writer = writer_model or model_name_for("quiz")
    return _bare_model_name(model_name_for(CHECK_TASK)) != _bare_model_name(writer)


@dataclass
class GateRun:
    """What one gate pass decided for a batch of new questions."""

    kept: list[dict] = field(default_factory=list)  # each carrying its "gate"
    dropped: int = 0
    counts: dict[str, int] = field(default_factory=dict)


def _verify_item(position: int, question: Mapping):
    from agents.check_items_verify import VerifyItem

    mc = quiz_gates.is_multiple_choice(question)
    correct = quiz_gates.correct_option(question) if mc else None
    return VerifyItem(
        id=quiz_gates.item_id(position),
        format="mc_reason" if mc else "free",
        prompt=str(question.get("question") or ""),
        correct_option=correct[1] if correct else None,
        other_options=tuple(
            text for label, text in quiz_gates.option_rows(question) if not correct or label != correct[0]
        ) if mc else (),
        criteria=(),
    )


def _solve_item(position: int, question: Mapping):
    from agents.check_items_solve import SolveItem

    mc = quiz_gates.is_multiple_choice(question)
    return SolveItem(
        id=quiz_gates.item_id(position),
        format="mc_reason" if mc else "free",
        prompt=str(question.get("question") or ""),
        options=quiz_gates.option_rows(question) if mc else (),
        answer_kind="numeric" if question.get("type") == "numeric" else "free",
    )


def _grades(question: Mapping, answer: str) -> tuple[bool, bool]:
    """(the quiz grader accepts `answer`, a numeric or symbolic answer parses)."""
    from services.quiz_algebra import equivalent_algebra
    from services.quiz_grading import grade_written, numeric_value

    accepted = grade_written(dict(question), answer)
    kind = question.get("type")
    if kind == "numeric":
        parsed = numeric_value(answer) is not None
    elif kind == "symbolic":
        parsed = equivalent_algebra(answer, answer)
    else:
        parsed = False
    return accepted, parsed


async def _run_check(agent, prompt: str, *, deps, feature: str):
    from agents._providers import model_for
    from agents.check_items import run_drafting

    return await run_drafting(
        agent, prompt, deps=deps, flex=False, feature=feature, task=CHECK_TASK,
        model=model_for(CHECK_TASK),
    )


async def gate_questions(
    questions: Sequence[dict],
    *,
    user_id: str,
    course_id: str | None,
    concept_name: str,
    concept_names: Sequence[str],
    passages: Sequence[dict],
    request_id: str | None,
    writer_model: str | None = None,
) -> GateRun:
    """A145: run the concept check and the blind solve over `questions` (one
    call each, concurrently; then one key match for the written pairs code
    could not settle) and decide each question's gate. A DROPPED question is
    left out of `kept`; every kept one carries its stored "gate". Never
    raises: a check that is unavailable leaves its half unverified, so its
    questions are practice-only. `writer_model` is the model that wrote them
    (`checks_independent`)."""
    from agents.check_items import CheckItemsUnavailable
    from agents.check_items_key_match import MatchItem, build_match_prompt, check_items_key_match_agent
    from agents.check_items_solve import build_solve_prompt, check_items_solve_agent, solutions
    from agents.check_items_verify import build_verify_prompt, check_items_verify_agent
    from agents.deps import SaplingDeps

    run = GateRun()
    if not questions:
        return run
    deps = SaplingDeps(
        user_id=user_id, course_id=course_id, supabase=None, request_id=request_id, feature="quiz"
    )
    names = list(dict.fromkeys([concept_name, *[n for n in concept_names if n]]))
    ids = [quiz_gates.item_id(i) for i in range(1, len(questions) + 1)]
    independent = checks_independent(writer_model)
    verify_call = _run_check(
        check_items_verify_agent,
        build_verify_prompt(names, [_verify_item(i, q) for i, q in enumerate(questions, 1)]),
        deps=deps,
        feature=VERIFY_FEATURE,
    )
    if independent:
        solve_call = _run_check(
            check_items_solve_agent,
            build_solve_prompt(list(passages), [_solve_item(i, q) for i, q in enumerate(questions, 1)]),
            deps=deps,
            feature=SOLVE_FEATURE,
        )
        verified_out, solved_out = await asyncio.gather(verify_call, solve_call)
    else:
        logger.warning(
            "quiz: the quiz_check slot resolves to the model that wrote the questions; "
            "no key is verified (A124 needs another model)"
        )
        verified_out, solved_out = await verify_call, None

    concepts: dict[str, str] = {}
    if not isinstance(verified_out, CheckItemsUnavailable) and verified_out is not None:
        concepts = quiz_gates.collect_concepts((c.item, c.concept) for c in verified_out.concepts)
    solved: dict[str, item_keys.Solved] | None = None
    if solved_out is not None and not isinstance(solved_out, CheckItemsUnavailable):
        solved = solutions(solved_out)

    outcomes: dict[str, str] = {}
    pairs = []
    for qid, question in zip(ids, questions):
        if solved is None:
            continue
        s = solved.get(qid)
        accepted = parsed = None
        if s is not None and s.solvable and not quiz_gates.is_multiple_choice(question):
            accepted, parsed = _grades(question, s.answer)
        outcome = quiz_gates.key_outcome(question, s, accepted=accepted, parsed=parsed)
        outcomes[qid] = outcome
        if outcome == item_keys.TO_MATCH:
            pairs.append(MatchItem(qid, str(question.get("question") or ""), str(question.get("correct_answer") or ""), s.answer))
    same: dict[str, bool] = {}
    if pairs:
        matched = await _run_check(
            check_items_key_match_agent, build_match_prompt(pairs), deps=deps, feature=MATCH_FEATURE
        )
        if not isinstance(matched, CheckItemsUnavailable) and matched is not None:
            same = item_keys.collect_matches((m.item, m.same) for m in matched.matches)

    grounded = bool(passages)
    for qid, question in zip(ids, questions):
        alignment = quiz_gates.alignment_of(concepts.get(qid), concept_name)
        if not independent:
            key = quiz_gates.KEY_NOT_INDEPENDENT
        elif solved is None or qid not in outcomes:
            key = quiz_gates.KEY_UNVERIFIED
        else:
            key = quiz_gates.key_of(outcomes[qid], same.get(qid))
        gate = quiz_gates.decide(alignment, key, grounded=grounded)
        run.counts[gate.status] = run.counts.get(gate.status, 0) + 1
        run.counts[gate.alignment] = run.counts.get(gate.alignment, 0) + 1
        run.counts[gate.key] = run.counts.get(gate.key, 0) + 1
        if gate.status == quiz_gates.DROPPED:
            run.dropped += 1
            continue
        question[quiz_gates.GATE_KEY] = gate.stored()
        run.kept.append(question)
    events_service.log_event(
        "quiz.items_gated",
        category=events_service.SYSTEM_CATEGORY,
        user_id=user_id,
        request_id=request_id,
        payload={"questions": len(questions), "grounded": grounded, **run.counts},
    )
    return run


def ungated_practice(questions: Iterable[dict]) -> None:
    """A145: under the gates flag, a question that reaches an attempt without
    a gate of its own (a re-served one stored before the gates) is served as
    practice — never evidence — rather than checked again."""
    for question in questions:
        if quiz_gates.gate_of(question) is None:
            question[quiz_gates.GATE_KEY] = quiz_gates.Gate(
                quiz_gates.PRACTICE, quiz_gates.NOT_CHECKED, quiz_gates.NOT_CHECKED
            ).stored()


# ── A146: misconceptions from the quiz ─────────────────────────────────────


@dataclass(frozen=True)
class Exposure:
    """What the journal said before this submit's evidence was written."""

    seen: frozenset[str]  # question hashes the student had evidence on before
    released: bool  # a release on the concept within RECHECK_RELEASE_WINDOW_HOURS


def exposure_before(user_id: str, node_id: str, hashes: Sequence[str], now: datetime) -> Exposure | None:
    """A127/A76 for the quiz, read BEFORE the submit writes its evidence: the
    attempt's questions the student was graded on before (no first attempt),
    and whether any answer on the concept was released within
    RECHECK_RELEASE_WINDOW_HOURS (a wrong or idk answer, a worked answer, or
    an answered segment prequestion) — the next answer after a release is a
    re-check, never an unassisted first attempt, and a quiz question has no
    isomorph class, so any release counts (A76's rule for an unknown class).
    None when a read failed: nothing then closes (fail closed)."""
    since = (now - timedelta(hours=RECHECK_RELEASE_WINDOW_HOURS)).isoformat()
    wanted = sorted({h for h in hashes if h})
    try:
        recent = table("node_mastery_events").select(
            "correct,max_rung,graph_nodes!inner(user_id)",
            filters={
                "graph_nodes.user_id": f"eq.{user_id}",
                "node_id": f"eq.{node_id}",
                "event_type": "eq.evidence",
                "created_at": f"gte.{since}",
            },
        ) or []
        seen_rows = (
            table("node_mastery_events").select(
                "question_hash,graph_nodes!inner(user_id)",
                filters={
                    "graph_nodes.user_id": f"eq.{user_id}",
                    "node_id": f"eq.{node_id}",
                    "event_type": "eq.evidence",
                    "question_hash": f"in.({','.join(pg_quote_value(h) for h in wanted)})",
                },
            )
            or []
            if wanted
            else []
        )
    except Exception as exc:
        logger.warning("quiz: journal unreadable before the submit: %s", type(exc).__name__)
        return None
    from learning.prequestion_store import releases

    prequestions = releases(user_id, node_id, since=now - timedelta(hours=RECHECK_RELEASE_WINDOW_HOURS))
    if prequestions is None:
        return None
    released = bool(prequestions) or any(
        r.get("correct") is False or (r.get("max_rung") or 0) >= RUNG_NO_CREDIT_MIN for r in recent
    )
    return Exposure(frozenset(r.get("question_hash") for r in seen_rows if r.get("question_hash")), released)


def misconceptions_after_submit(
    user_id: str,
    node_id: str,
    *,
    questions: Sequence[Mapping],
    results: Sequence[Mapping],
    stated: Sequence[float | None],
    written: Sequence[Mapping],
    exposure: Exposure | None,
    request_id: str | None,
) -> dict:
    """A146, after the submit's one evidence write committed `written` (the
    evidence dicts the single writer took). In question order:

    - record: a wrong answer on a verified multiple-choice question whose
      evidence was written, the chosen option tagged with a key, stated
      confidence >= MISCONCEPTION_CONFIDENCE (quiz_gates.misconception_to_record);
    - resolve (A127): a correct answer on a verified question whose evidence
      was written, unassisted (rung 0 after the help floor, not assisted),
      a first attempt (not graded before, not re-served), not after a
      release (none on the concept in the window, no earlier wrong answer in
      this attempt) — closing the open keys the question lists that were
      recorded on another question.

    Returns {"recorded": [...], "resolved": [...]} (keys). Never raises."""
    from learning.misconceptions import record, resolve_after_grade

    by_hash = {e.get("question_hash"): e for e in written if e.get("question_hash")}
    recorded: list[str] = []
    resolved: list[str] = []
    # Fail closed: an unread journal is a release (nothing closes).
    released = exposure.released if exposure is not None else True
    for question, result, confidence in zip(questions, results, stated):
        qh = question.get("question_hash")
        ev = by_hash.get(qh) if qh else None
        correct = bool(result.get("correct"))
        try:
            if ev is not None and quiz_gates.verified(question):
                if correct:
                    resolved += _resolve(
                        user_id, node_id, question, ev, exposure, released, request_id, resolve_after_grade
                    )
                else:
                    key = quiz_gates.misconception_to_record(question, result.get("selected"), confidence)
                    if key:
                        recorded += _record(user_id, node_id, question, result, key, request_id, record)
        except Exception as exc:  # a diagnosis, never the submit's failure
            logger.warning("quiz: misconception step failed: %s", type(exc).__name__)
        if not correct:
            # /answer returned this question's key: whatever the gate said, the
            # next answer on the concept comes after a release (A76).
            released = True
    return {"recorded": recorded, "resolved": resolved}


def _record(user_id, node_id, question, result, key, request_id, record) -> list[str]:
    qh = question["question_hash"]
    chosen = next(
        (
            str(o.get("text") or "")
            for o in question.get("options") or []
            if isinstance(o, Mapping) and o.get("label") == result.get("selected")
        ),
        None,
    )
    row = record(user_id, node_id, quiz_item_id(qh), key, chosen, question_hash=qh)
    if not row:
        return []
    events_service.log_event(
        "quiz.misconception_recorded",
        category="usage",
        user_id=user_id,
        request_id=request_id,
        payload={
            "node_id": node_id,
            "wrong_key": key,
            "question_hash": qh,
            "count": int(row.get("count") or 0),
        },
    )
    return [key]


def _resolve(user_id, node_id, question, ev, exposure, released, request_id, resolve_after_grade) -> list[str]:
    qh = question["question_hash"]
    keys = quiz_gates.keys_listed(question)
    fresh = (
        exposure is not None
        and qh not in exposure.seen
        and not (question.get("provenance") or {}).get("reserved_from")
    )
    if not keys or not fresh or released:
        return []
    # A127's attempt half reads the FINAL evidence: the help floor's rung and
    # the assisted flag (quiz evidence carries neither unless the floor set it).
    attempt = {
        "correct": True,
        "idk": False,
        "max_rung": int(ev.get("max_rung") or 0),
        "assisted": bool(ev.get("assisted")),
        "same_session_recheck": False,
    }
    return resolve_after_grade(
        user_id,
        node_id,
        keys=keys,
        item_id=quiz_item_id(qh),
        attempt=attempt,
        surface="quiz",
        request_id=request_id,
    )


# ── A147: what the results say ─────────────────────────────────────────────


def _neighbours(user_id: str, node_id: str) -> list[str]:
    """The node's prerequisite parents and dependents: the nodes its evidence
    can move through one-hop propagation."""
    rows = table("graph_edges").select(
        "source_node_id,target_node_id",
        filters={
            "user_id": f"eq.{user_id}",
            "relationship_type": f"eq.{PREREQ_RELATIONSHIP_TYPE}",
            "or": f"(source_node_id.eq.{pg_quote_value(node_id)},target_node_id.eq.{pg_quote_value(node_id)})",
        },
    ) or []
    out: list[str] = []
    for row in rows:
        for other in (row.get("source_node_id"), row.get("target_node_id")):
            if other and other != node_id and other not in out:
                out.append(other)
    return out


@dataclass(frozen=True)
class SkillSnapshot:
    order: tuple[str, ...]  # the quizzed node first, then its neighbours
    p_known: dict[str, float]


def skill_snapshot(user_id: str, node_id: str, order: Sequence[str] | None = None) -> SkillSnapshot | None:
    """Decayed p_known of the node and its prerequisite neighbours (BKT_L0 for
    a node with no learner state). None on a failed read."""
    try:
        nodes = list(order) if order is not None else [node_id, *_neighbours(user_id, node_id)]
        states = read_states(user_id, nodes)
    except Exception as exc:
        logger.warning("quiz: skill snapshot unreadable: %s", type(exc).__name__)
        return None
    return SkillSnapshot(tuple(nodes), {n: (states[n].p_known if n in states else BKT_L0) for n in nodes})


def results_block(
    user_id: str,
    node: Mapping,
    before: SkillSnapshot | None,
    now: datetime | None = None,
) -> dict | None:
    """A147: the submit response's `learning` block — the skill meters that
    moved, what is due, and the next step — or None when it cannot be built
    (the results then show what they always did)."""
    now = now or _now()
    if before is None:
        return None
    node_id, course_id = node["id"], node.get("course_id")
    try:
        after = skill_snapshot(user_id, node_id, before.order)
        nodes = _nodes(user_id, course_id) if course_id else []
        names = {n.id: n.name for n in nodes}
        if node_id not in names:
            names[node_id] = node.get("concept_name") or ""
        missing = [n for n in before.order if n not in names]
        if missing:
            for row in table("graph_nodes").select(
                "id,concept_name",
                filters={"user_id": f"eq.{user_id}", "id": f"in.({','.join(pg_quote_value(n) for n in missing)})"},
            ) or []:
                names[row["id"]] = row.get("concept_name") or ""
        states = _concept_states(user_id, nodes, now) if nodes else []
        edges = _prereq_edges(user_id, [n.id for n in nodes]) if nodes else []
    except Exception as exc:
        logger.warning("quiz: results block unreadable: %s", type(exc).__name__)
        return None
    if after is None:
        return None
    changes = quiz_plan.skill_changes(before.p_known, after.p_known, before.order)
    step = quiz_plan.next_step(states, edges, now)
    own = next((s for s in states if s.node_id == node_id), None)
    learn = (
        {
            "concept_id": step.learn_node_id,
            "concept_name": names.get(step.learn_node_id, ""),
            "course_id": course_id,
        }
        if step.learn_node_id
        else None
    )
    return {
        "changes": [
            {
                "concept_id": c.node_id,
                "concept_name": names.get(c.node_id, ""),
                "before": round(c.before, 4),
                "after": round(c.after, 4),
                "band_before": c.band_before,
                "band_after": c.band_after,
            }
            for c in changes
        ],
        "review": {
            "due_count": step.due_count,
            "next_due_at": _iso(own.fsrs_due_at) if own else None,
        },
        "next_step": step.kind,
        "learn": learn,
    }


def course_concept_names(user_id: str, course_id: str | None) -> list[str]:
    """The student's concept names in the course: the list the A119 concept
    check picks the tested concept from (a quiz question testing another of
    them is misaligned). [] on a failed read (the check then lists the
    quizzed concept alone)."""
    if not course_id:
        return []
    try:
        return [n.name for n in _nodes(user_id, course_id) if n.name]
    except Exception as exc:
        logger.warning("quiz: concept names unreadable: %s", type(exc).__name__)
        return []

"""The quiz in the learning system, flags on (learning-loop spec §13
A143-A147): the plan endpoint, planned questions, the item gates, the
misconception record and resolve, and the results block — through the real
route on the function-mode handlers (tests/test_quiz_learning_flags_off.py's
flow harness), and the service's reads on fakes."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from learning import params, quiz_plan
from services import quiz_learning as ql
from tests.test_quiz_learning_flags_off import QUIZ_FLAGS, _flow, client

NOW = datetime(2026, 11, 8, 12, 0, tzinfo=timezone.utc)
SURE = params.STUDENT_CONFIDENCE_LEVELS["sure"]


def _flags(monkeypatch, *on):
    for key in QUIZ_FLAGS:
        monkeypatch.setenv(f"SAPLING_FLAG_{key.upper()}", "on" if key in on else "off")


def _plan(count, requested, question_format, *, open_keys=(("rate_is_loss_value", 2),), p=0.5):
    keys = quiz_plan.misconception_keys(
        list(open_keys),
        [
            ("rate_is_iteration_count", "Confuses the learning rate with the number of iterations."),
            ("rate_is_loss_value", "Treats the learning rate as the loss being minimised."),
        ],
    )
    specs = quiz_plan.question_specs(count, requested=requested, p_known=p, keys=keys, question_format=question_format)
    return ql.GenerationPlan(specs=specs, keys=keys, p_known=p, source=quiz_plan.difficulty_source(requested))


@pytest.fixture
def service_reads():
    """The service's database reads, faked: the plan's state, the concept
    names, the journal before the submit and the skill meters."""
    with (
        patch.object(ql, "generation_plan", side_effect=lambda *a, **k: _plan(k["count"], k["requested"], k["question_format"])) as plan,
        patch.object(ql, "course_concept_names", return_value=["Recursion", "Loops"]),
        patch.object(ql, "exposure_before", return_value=ql.Exposure(frozenset(), False)) as exposure,
        patch.object(ql, "skill_snapshot", return_value=None),
        patch("learning.misconceptions.record", return_value={"id": "m1", "count": 1}) as record,
        patch("learning.misconceptions.resolve", return_value=[]) as resolve,
    ):
        yield {"plan": plan, "exposure": exposure, "record": record, "resolve": resolve}


def _stored(flow):
    (insert,) = [w for w in flow["written"] if w[0] == "insert" and w[1] == "quiz_attempts"]
    return insert[2]["questions_json"]["enc"]


# ── A143: the concept plan ──────────────────────────────────────────────────


def test_the_plan_404s_while_its_flag_is_off(monkeypatch):
    _flags(monkeypatch)
    r = client.get("/api/quiz/plan", params={"user_id": "user_andres"})
    assert r.status_code == 404


def test_the_plan_returns_the_learner_models_order(monkeypatch):
    _flags(monkeypatch, "quiz_concept_plan")
    concepts = [{"node_id": "n1", "reason": "due"}]
    with patch.object(ql, "concept_plan", return_value=concepts) as plan:
        r = client.get("/api/quiz/plan", params={"user_id": "user_andres", "course_id": "c1"})
    assert r.status_code == 200 and r.json() == {"concepts": concepts}
    plan.assert_called_once_with("user_andres", "c1")


def test_an_unreadable_plan_is_503(monkeypatch):
    _flags(monkeypatch, "quiz_concept_plan")
    with patch.object(ql, "concept_plan", side_effect=RuntimeError("down")):
        r = client.get("/api/quiz/plan", params={"user_id": "user_andres"})
    assert r.status_code == 503


def test_concept_plan_assembles_states_misconceptions_and_edges():
    nodes = [ql._Node("a", "Alpha", "c1"), ql._Node("b", "Beta", "c1"), ql._Node("c", "Gamma", "c1")]
    states = {
        "a": MagicMock(p_known=0.96, fsrs_s=2.0, fsrs_last_review_at=NOW - timedelta(days=10), fsrs_due_at=NOW - timedelta(days=1)),
        "b": MagicMock(p_known=0.40, fsrs_s=None, fsrs_last_review_at=None, fsrs_due_at=None),
    }
    with (
        patch.object(ql, "_nodes", return_value=nodes),
        patch.object(ql, "read_states", return_value=states),
        patch.object(ql, "_open_misconceptions", return_value=[{"node_id": "c", "wrong_key": "k_a", "count": 1}]),
        patch.object(ql, "_prereq_edges", return_value=[("b", "c")]),
    ):
        plan = ql.concept_plan("u", "c1", now=NOW)
    assert [(c["node_id"], c["reason"], c["concept_name"]) for c in plan] == [
        ("a", "due", "Alpha"),
        ("c", "misconception", "Gamma"),
        ("b", "ready", "Beta"),
    ]
    assert plan[1]["p_known"] == params.BKT_L0 and plan[1]["band"] == "develop"
    assert plan[0]["due_at"].startswith("2026-11-07")


# ── A144: planned questions ─────────────────────────────────────────────────


def test_planned_questions_carry_the_plan_and_its_tags_and_serve_none_of_it(monkeypatch, service_reads):
    _flags(monkeypatch, "quiz_planned_questions")
    flow = _flow(monkeypatch, question_format="multiple_choice")
    stored = _stored(flow)
    assert [q["planned"]["slot"] for q in stored] == [1, 2, 3]
    assert {q["planned"]["difficulty_source"] for q in stored} == {"learner_model"}
    # the plan's difficulty (p = 0.5: develop → medium) and the attempt's concept
    assert {q["difficulty"] for q in stored} == {"medium"} and {q["concept_tested"] for q in stored} == {"Recursion"}
    # the held key is targeted first, then the bank's
    assert [q["planned"]["target"] for q in stored] == ["rate_is_loss_value", "rate_is_iteration_count", None]
    # tags only on distractors, only the plan's keys
    first = stored[0]["options"]
    assert [o.get("misconception") for o in first] == ["rate_is_iteration_count", None, "rate_is_loss_value", None]
    assert stored[0]["provenance"]["prompt_version"] != flow["generate"]["questions"][0].get("prompt_version")
    for question in flow["generate"]["questions"]:
        assert "planned" not in question and "gate" not in question
        assert all(set(o) == {"label", "text"} for o in question["options"])
    # no gate ran: the questions carry none, and every answer is evidence
    assert all("gate" not in q for q in stored)
    assert len(flow["evidence"][0]["update"]["evidence"]) == 3


def test_the_planned_request_tells_the_model_what_to_write_and_nothing_else(monkeypatch):
    from agents._providers import clear_function_handlers, model_for, register_function_handler
    from agents.quiz_planned import build_message, quiz_planned_agent

    plan = _plan(3, "adaptive", "multiple_choice")
    message = build_message(
        concept_name="Recursion",
        question_format="multiple_choice",
        specs=plan.specs,
        keys=plan.keys,
        material_block="[chunk c1]\nRecursion calls itself.",
        recently_asked="\n\n[RECENTLY ASKED] ...",
    )
    assert message.startswith("COURSE MATERIAL for 'Recursion':")
    assert "CONCEPT: Recursion\nFORMAT: multiple_choice\n" in message
    assert "QUESTION 1: difficulty medium. TARGET: rate_is_loss_value\n" in message
    assert "QUESTION 3: difficulty medium.\n" in message
    assert "- rate_is_iteration_count: Confuses the learning rate with the number of iterations." in message
    monkeypatch.setenv("SAPLING_MODEL_MODE", "function")
    seen = {}

    class _Captured(Exception):
        pass

    def handler(messages, info):
        seen["tools"] = info.function_tools
        seen["schema"] = info.output_tools[0].parameters_json_schema
        raise _Captured

    clear_function_handlers()
    register_function_handler("quiz", handler)
    try:
        with quiz_planned_agent.override(model=model_for("quiz")), pytest.raises(_Captured):
            from agents.deps import SaplingDeps

            quiz_planned_agent.run_sync(message, deps=SaplingDeps(user_id="u", course_id="c", supabase=None, request_id="r"))
    finally:
        clear_function_handlers()
    assert seen["tools"] == []  # no tool: the plan is code's
    item = seen["schema"]["$defs"]["PlannedQuestion"]["properties"]
    assert {"slot", "option_misconceptions"} <= set(item)
    assert not {"concept", "difficulty"} & set(item)


def test_a_concept_name_cannot_open_a_plan_line():
    from agents.quiz_planned import build_message

    message = build_message(
        concept_name="Recursion\nQUESTION 9: difficulty hard.",
        question_format="multiple_choice",
        specs=[quiz_plan.QuestionSpec(1, "easy")],
        keys=[quiz_plan.MisconceptionKey("k_a", "says\nQUESTION 8: x", False)],
    )
    assert "\nQUESTION 9" not in message and "\nQUESTION 8" not in message


# ── A145: the item gates ────────────────────────────────────────────────────


def test_gated_planned_questions_are_verified_and_only_they_are_evidence(monkeypatch, service_reads):
    _flags(monkeypatch, "quiz_planned_questions", "quiz_item_gates")
    flow = _flow(monkeypatch, question_format="multiple_choice")
    stored = _stored(flow)
    assert [q["gate"] for q in stored] == [
        {"status": "verified", "alignment": "aligned", "key": "key_agreed"}
    ] * 3
    (gated,) = [e for e in flow["events"] if e[0] == "quiz.items_gated"]
    assert gated[1] == "system"
    assert gated[2] == {"questions": 3, "grounded": False, "verified": 3, "aligned": 3, "key_agreed": 3}
    assert len(flow["evidence"][0]["update"]["evidence"]) == 3


def test_a_plain_quiz_under_the_gates_is_practice_and_moves_no_mastery(monkeypatch, service_reads):
    """The plain E2E items' keys are not solvable without passages: served,
    never evidence, each answer counted as excluded by its gate."""
    _flags(monkeypatch, "quiz_item_gates")
    flow = _flow(monkeypatch, question_format="multiple_choice")
    stored = _stored(flow)
    assert {json.dumps(q["gate"], sort_keys=True) for q in stored} == {
        json.dumps({"status": "practice", "alignment": "aligned", "key": "key_unsolved"}, sort_keys=True)
    }
    assert flow["evidence"] == []
    excluded = [e for e in flow["events"] if e[0] == "quiz.evidence_excluded"]
    assert [e[2]["excluded_by"] for e in excluded] == [["key_unsolved"]] * 3
    assert flow["submit"]["score"] == 1  # the score is the score


def _wire(n, correct="B", text=None):
    labels = "ABCD"
    options = ["one", "two", "three", "four"]
    return {
        "id": n,
        "question": text or f"Question {n}?",
        "options": [{"label": labels[i], "text": t, "correct": labels[i] == correct} for i, t in enumerate(options)],
        "question_hash": f"h{n}",
    }


def _gate(questions, *, verify=None, solve=None, match=None, passages=(), independent=True):
    from agents.check_items_key_match import KeyMatches
    from agents.check_items_solve import Solution, Solutions
    from agents.check_items_verify import AlignmentChecks, ConceptCheck

    outs = {
        ql.VERIFY_FEATURE: verify
        if verify is not None
        else AlignmentChecks(criteria=[], concepts=[ConceptCheck(item=f"q{i}", asks="x", concept="Recursion") for i in range(1, len(questions) + 1)]),
        ql.SOLVE_FEATURE: solve
        if solve is not None
        else Solutions(solutions=[Solution(item=f"q{i}", basis="x", solvable=True, answer="B") for i in range(1, len(questions) + 1)]),
        ql.MATCH_FEATURE: match if match is not None else KeyMatches(matches=[]),
    }
    calls = []

    async def run(agent, prompt, **kw):
        calls.append((kw["feature"], kw["task"], prompt))
        return outs[kw["feature"]]

    with (
        patch("agents.check_items.run_drafting", side_effect=run),
        patch.object(ql, "checks_independent", return_value=independent),
        patch("services.events_service.log_event"),
    ):
        result = asyncio.run(
            ql.gate_questions(
                questions,
                user_id="u",
                course_id="c",
                concept_name="Recursion",
                concept_names=["Recursion", "Loops"],
                passages=list(passages),
                request_id="r",
            )
        )
    return result, calls


def test_a_misaligned_or_disputed_question_is_dropped_before_it_is_served():
    from agents.check_items_solve import Solution, Solutions
    from agents.check_items_verify import AlignmentChecks, ConceptCheck

    qs = [_wire(1), _wire(2), _wire(3), _wire(4)]
    verify = AlignmentChecks(
        criteria=[],
        concepts=[
            ConceptCheck(item="q1", asks="x", concept="Recursion"),
            ConceptCheck(item="q2", asks="x", concept="Loops"),  # another concept
            ConceptCheck(item="q3", asks="x", concept="Recursion"),
            ConceptCheck(item="q4", asks="x", concept="Recursion"),
        ],
    )
    solve = Solutions(
        solutions=[
            Solution(item="q1", basis="x", solvable=True, answer="B"),
            Solution(item="q2", basis="x", solvable=True, answer="B"),
            Solution(item="q3", basis="x", solvable=True, answer="C"),  # disputes the key
            Solution(item="q4", basis="x", solvable=False, answer=""),  # passages do not settle it
        ]
    )
    run, calls = _gate(qs, verify=verify, solve=solve, passages=[{"id": "c1", "text": "passage"}])
    assert [q["question_hash"] for q in run.kept] == ["h1"]
    assert run.kept[0]["gate"]["status"] == "verified"
    assert run.dropped == 3
    assert {(f, t) for f, t, _ in calls} == {(ql.VERIFY_FEATURE, "quiz_check"), (ql.SOLVE_FEATURE, "quiz_check")}
    # the solve reads the options under their served letters, never the key
    solve_prompt = next(p for f, _, p in calls if f == ql.SOLVE_FEATURE)
    assert "OPTION A: one\nOPTION B: two\nOPTION C: three\nOPTION D: four\n" in solve_prompt
    assert "CORRECT OPTION" not in solve_prompt  # the concept check's marked key never reaches it
    assert "> passage" in solve_prompt  # the passages the questions were written from


def test_an_ungrounded_unsolved_question_is_practice_not_dropped():
    from agents.check_items_solve import Solution, Solutions

    run, _ = _gate([_wire(1)], solve=Solutions(solutions=[Solution(item="q1", basis="x", solvable=False, answer="")]))
    assert run.dropped == 0 and run.kept[0]["gate"]["status"] == "practice"


def test_an_unavailable_check_leaves_its_questions_practice():
    from agents.check_items import CheckItemsUnavailable

    run, _ = _gate([_wire(1)], solve=CheckItemsUnavailable(reason="ModelHTTPError"))
    assert run.kept[0]["gate"] == {"status": "practice", "alignment": "aligned", "key": "key_unverified"}
    run, _ = _gate([_wire(1)], verify=CheckItemsUnavailable(reason="ModelHTTPError"))
    assert run.kept[0]["gate"]["alignment"] == "alignment_unverified" and run.kept[0]["gate"]["status"] == "practice"


def test_a_solve_on_the_writers_own_model_verifies_no_key():
    run, calls = _gate([_wire(1)], independent=False)
    assert run.kept[0]["gate"] == {"status": "practice", "alignment": "aligned", "key": "key_not_independent"}
    assert [f for f, _, _ in calls] == [ql.VERIFY_FEATURE]  # no solve is run


def test_independence_compares_the_two_slots_resolved_models(monkeypatch):
    import agents._providers as providers

    monkeypatch.setattr(providers, "model_mode", lambda: "real")
    assert ql.checks_independent()  # defaults: Sonnet checks, Haiku writer
    monkeypatch.setenv("SAPLING_MODEL_QUIZ_CHECK", "claude-haiku-5-5")
    assert not ql.checks_independent()
    monkeypatch.setenv("SAPLING_MODEL_QUIZ_CHECK", "gemini-2.5-flash-lite")
    assert ql.checks_independent()


def test_independence_is_against_the_model_that_wrote_this_request(monkeypatch):
    """The quiz's fast/smart preference can put the writer on the checks' own
    model: then no key is verified, whatever the slots say."""
    import agents._providers as providers
    from services.quiz import generation as quiz_route  # #118: the body's home (A149)

    monkeypatch.setattr(providers, "model_mode", lambda: "real")
    monkeypatch.setattr(providers, "_model_mode", lambda: "real")
    smart = quiz_route._writer_model_name("smart")
    assert smart == "claude-sonnet-5-5"
    assert not ql.checks_independent(smart)  # Sonnet wrote, Sonnet would solve
    assert ql.checks_independent(quiz_route._writer_model_name("fast"))
    assert quiz_route._writer_model_name(None) == providers.model_name_for("quiz")
    assert quiz_route._writer_model_name("unknown") == providers.model_name_for("quiz")
    # Outside real mode the override is never built, so the writer is the slot's.
    monkeypatch.setattr(providers, "_model_mode", lambda: "function")
    assert quiz_route._writer_model_name("smart") == providers.model_name_for("quiz")


def test_the_route_gate_hands_the_writer_model_to_the_checks():
    from services.quiz import generation as quiz_route  # #118: the body's home (A149)

    seen = {}

    async def gate_questions(questions, **kw):
        seen.update(kw)
        return ql.GateRun(kept=list(questions))

    material = quiz_route.CourseMaterial(block="", chunk_ids=(), has_catalog=False)
    with (
        patch.object(ql, "course_concept_names", return_value=["Recursion"]),
        patch.object(ql, "gate_questions", side_effect=gate_questions),
    ):
        gate = quiz_route._item_gate("u", "c", "Recursion", "r", "claude-sonnet-5-5")
        asyncio.run(gate([_wire(1)], material))
    assert seen["writer_model"] == "claude-sonnet-5-5"


def test_a_written_answer_the_grader_rejects_goes_to_one_key_match():
    from agents.check_items_key_match import KeyMatch, KeyMatches
    from agents.check_items_solve import Solution, Solutions

    q = {"id": 1, "type": "short_answer", "question": "Name it.", "options": [], "correct_answer": "base case", "accepted_answers": [], "question_hash": "h1"}
    run, calls = _gate(
        [q],
        solve=Solutions(solutions=[Solution(item="q1", basis="x", solvable=True, answer="the stopping case")]),
        match=KeyMatches(matches=[KeyMatch(item="q1", why="x", same=True)]),
    )
    assert run.kept[0]["gate"]["key"] == "key_agreed"
    match_prompt = next(p for f, _, p in calls if f == ql.MATCH_FEATURE)
    assert "FIRST ANSWER: base case" in match_prompt and "SECOND ANSWER: the stopping case" in match_prompt


# ── A146: misconceptions ────────────────────────────────────────────────────


def _q(n, *, correct="B", tags=None, verified=True, reserved=False):
    q = _wire(n, correct=correct)
    for o in q["options"]:
        if tags and o["label"] in tags:
            o["misconception"] = tags[o["label"]]
    if verified:
        q["gate"] = {"status": "verified", "alignment": "aligned", "key": "key_agreed"}
    if reserved:
        q["provenance"] = {"reserved_from": "a0"}
    return q


def _ev(n, **extra):
    return {"node_id": "node1", "channel": "mc", "correct": True, "question_hash": f"h{n}", **extra}


def _after(questions, results, stated, written, exposure=ql.Exposure(frozenset(), False)):
    resolved_rows = [{"id": "m9", "wrong_key": "k_a", "check_item_id": "quiz:h0", "count": 2}]
    with (
        patch("learning.misconceptions.record", return_value={"id": "m1", "count": 1}) as record,
        patch("learning.misconceptions.resolve", return_value=resolved_rows) as resolve,
        patch("services.events_service.log_event") as log_event,
        patch("learning.misconceptions.log_event") as resolved_event,
    ):
        out = ql.misconceptions_after_submit(
            "u", "node1", questions=questions, results=results, stated=stated,
            written=written, exposure=exposure, request_id="r",
        )
    return out, record, resolve, log_event, resolved_event


def test_a_sure_wrong_answer_on_a_tagged_distractor_records_under_the_quiz_item():
    q = _q(1, tags={"A": "k_a"})
    out, record, _, log_event, _ = _after([q], [{"correct": False, "selected": "A"}], [SURE], [_ev(1, correct=False)])
    assert out["recorded"] == ["k_a"]
    record.assert_called_once_with("u", "node1", "quiz:h1", "k_a", "one", question_hash="h1")
    (event,) = [c for c in log_event.call_args_list if c.args[0] == "quiz.misconception_recorded"]
    assert event.kwargs["payload"] == {"node_id": "node1", "wrong_key": "k_a", "question_hash": "h1", "count": 1}


@pytest.mark.parametrize(
    "question, result, stated, written",
    [
        (_q(1, tags={"A": "k_a"}), {"correct": False, "selected": "A"}, params.STUDENT_CONFIDENCE_LEVELS["fairly_sure"], [_ev(1)]),
        (_q(1, tags={"A": "k_a"}), {"correct": False, "selected": "A"}, None, [_ev(1)]),
        (_q(1, tags={"A": "k_a"}, verified=False), {"correct": False, "selected": "A"}, SURE, [_ev(1)]),
        (_q(1, tags={"A": "k_a"}), {"correct": False, "selected": "A"}, SURE, []),  # its evidence was not written
        (_q(1, tags={"A": "k_a"}), {"correct": False, "selected": "C"}, SURE, [_ev(1)]),  # untagged choice
    ],
)
def test_nothing_else_records(question, result, stated, written):
    out, record, *_ = _after([question], [result], [stated], written)
    assert out["recorded"] == [] and not record.called


def test_a_correct_first_unassisted_answer_closes_what_the_question_lists():
    q = _q(1, tags={"A": "k_a", "C": "k_b"})
    out, _, resolve, _, resolved_event = _after([q], [{"correct": True, "selected": "B"}], [None], [_ev(1)])
    resolve.assert_called_once()
    args, kwargs = resolve.call_args
    assert args[:3] == ("u", "node1", ["k_a", "k_b"]) and kwargs == {"by_item": "quiz:h1"}
    assert out["resolved"] == ["k_a"]
    (event,) = resolved_event.call_args_list
    assert event.kwargs["payload"]["surface"] == "quiz"
    assert event.kwargs["payload"]["check_item_id"] == "quiz:h1"


@pytest.mark.parametrize(
    "question, written, exposure",
    [
        (_q(1, tags={"A": "k_a"}), [_ev(1, max_rung=4, assisted=True)], ql.Exposure(frozenset(), False)),  # asked about it
        (_q(1, tags={"A": "k_a"}), [_ev(1)], ql.Exposure(frozenset({"h1"}), False)),  # graded before
        (_q(1, tags={"A": "k_a"}, reserved=True), [_ev(1)], ql.Exposure(frozenset(), False)),  # re-served
        (_q(1, tags={"A": "k_a"}), [_ev(1)], ql.Exposure(frozenset(), True)),  # after a release
        (_q(1, tags={"A": "k_a"}), [_ev(1)], None),  # the journal was unreadable
        (_q(1, tags={"A": "k_a"}, verified=False), [_ev(1)], ql.Exposure(frozenset(), False)),
        (_q(1), [_ev(1)], ql.Exposure(frozenset(), False)),  # lists no key
    ],
)
def test_nothing_else_resolves(question, written, exposure):
    out, _, resolve, _, _ = _after([question], [{"correct": True, "selected": "B"}], [None], written, exposure)
    assert out["resolved"] == [] and not resolve.called


def test_an_earlier_wrong_answer_in_the_attempt_is_a_release():
    """/answer returned question 1's key; question 2's correct answer is a
    re-check (A76), whatever question 1's gate said."""
    first = _q(1, tags={"A": "k_a"}, verified=False)
    second = _q(2, tags={"A": "k_a"})
    out, _, resolve, _, _ = _after(
        [first, second],
        [{"correct": False, "selected": "A"}, {"correct": True, "selected": "B"}],
        [None, None],
        [_ev(1, correct=False), _ev(2)],
    )
    assert out["resolved"] == [] and not resolve.called


def test_exposure_reads_releases_and_seen_questions():
    rows = {
        "recent": [{"correct": True, "max_rung": 0}, {"correct": True, "max_rung": 5}],
        "seen": [{"question_hash": "h1"}],
    }

    def table(name):
        mock = MagicMock()
        mock.select.side_effect = lambda cols, **kw: rows["seen"] if "question_hash" in kw["filters"] else rows["recent"]
        return mock

    with patch.object(ql, "table", side_effect=table), patch("learning.prequestion_store.releases", return_value=[]):
        got = ql.exposure_before("u", "node1", ["h1", "h2"], NOW)
    assert got == ql.Exposure(frozenset({"h1"}), True)  # the H5 row released the answer
    rows["recent"] = [{"correct": True, "max_rung": 0}]
    with patch.object(ql, "table", side_effect=table), patch("learning.prequestion_store.releases", return_value=[{"at": NOW}]):
        assert ql.exposure_before("u", "node1", ["h1"], NOW).released  # an answered prequestion
    with patch.object(ql, "table", side_effect=table), patch("learning.prequestion_store.releases", return_value=None):
        assert ql.exposure_before("u", "node1", ["h1"], NOW) is None


def test_the_misconception_step_runs_after_the_write_on_the_route(monkeypatch, service_reads):
    _flags(monkeypatch, "quiz_planned_questions", "quiz_item_gates", "quiz_misconceptions")
    flow = _flow(monkeypatch, question_format="multiple_choice")
    # question 1 (answered right, first, unassisted) closes the keys it lists
    (call,) = service_reads["resolve"].call_args_list
    assert call.args[2] == ["rate_is_iteration_count", "rate_is_loss_value"]
    assert call.kwargs == {"by_item": f"quiz:{_stored(flow)[0]['question_hash']}"}
    service_reads["exposure"].assert_called_once()
    assert not service_reads["record"].called  # no "Sure" wrong answer


# ── A147: the results block ─────────────────────────────────────────────────


def test_the_results_block_rides_the_submit_response(monkeypatch):
    _flags(monkeypatch, "quiz_results_routing")
    block = {"changes": [], "review": {"due_count": 0, "next_due_at": None}, "next_step": "none", "learn": None}
    with (
        patch.object(ql, "skill_snapshot", return_value=ql.SkillSnapshot(("node1",), {"node1": 0.35})) as before,
        patch.object(ql, "results_block", return_value=block) as results,
    ):
        flow = _flow(monkeypatch, question_format="multiple_choice")
    assert flow["submit"]["learning"] == block
    before.assert_called_once_with("user_andres", "node1")
    assert results.call_args.args[1] == {"id": "node1", "course_id": "course1", "concept_name": "Recursion"}


def test_results_block_words_the_meters_the_due_count_and_the_next_step():
    before = ql.SkillSnapshot(("n", "parent"), {"n": 0.35, "parent": 0.50})
    after = ql.SkillSnapshot(("n", "parent"), {"n": 0.62, "parent": 0.53})
    nodes = [ql._Node("n", "Recursion", "c1"), ql._Node("parent", "Functions", "c1"), ql._Node("due", "Loops", "c1")]
    states = [
        quiz_plan.ConceptState("n", 0.62, fsrs_due_at=NOW + timedelta(days=3)),
        quiz_plan.ConceptState("parent", 0.53),
        quiz_plan.ConceptState("due", 0.97, fsrs_s=3.0, fsrs_last_review_at=NOW - timedelta(days=4), fsrs_due_at=NOW - timedelta(hours=1)),
    ]
    with (
        patch.object(ql, "skill_snapshot", return_value=after),
        patch.object(ql, "_nodes", return_value=nodes),
        patch.object(ql, "_concept_states", return_value=states),
        patch.object(ql, "_prereq_edges", return_value=[("parent", "n")]),
    ):
        block = ql.results_block("u", {"id": "n", "course_id": "c1", "concept_name": "Recursion"}, before, now=NOW)
    assert block["changes"] == [
        {"concept_id": "n", "concept_name": "Recursion", "before": 0.35, "after": 0.62, "band_before": "develop", "band_after": "develop"},
        {"concept_id": "parent", "concept_name": "Functions", "before": 0.5, "after": 0.53, "band_before": "develop", "band_after": "develop"},
    ]
    assert block["review"] == {"due_count": 1, "next_due_at": (NOW + timedelta(days=3)).isoformat()}
    assert block["next_step"] == "review"
    assert block["learn"] == {"concept_id": "parent", "concept_name": "Functions", "course_id": "c1"}


def test_no_results_block_without_the_before_read():
    assert ql.results_block("u", {"id": "n", "course_id": "c1"}, None) is None

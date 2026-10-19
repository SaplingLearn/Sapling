"""PKG-14b: submit_quiz moves mastery only through evidence; the flat delta model is gone (spec §11.2)."""

import inspect
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from learning import params
from learning.bkt import update
from tests.test_quiz_answers_c import _ResponsesTable
from tests.test_quiz_scoring_e import _loop_table, _noop_ctx_agent, client
from test_learning_loop_invariants import LEGACY_MASTERY_SYMBOLS

# The retired symbols are named once, in inv_21's list (spec §8 invariant 21
# greps the literals), and every absence check here reads them from it.
LEGACY_DELTA_KEY, LEGACY_DELTA_CONSTANTS, _ = LEGACY_MASTERY_SYMBOLS

REPO = Path(__file__).resolve().parents[2]


def test_quiz_config_has_no_delta_model():
    import services.quiz_config as qc

    assert [n for n in dir(qc) if n.startswith(LEGACY_DELTA_CONSTANTS)] == []
    assert not hasattr(qc, "mastery_after")


def test_three_mc_corrects_from_prior():
    """spec PKG-14 §Derived expectations: 0.710733 → 0.913664 → 0.978259."""
    p = params.BKT_L0
    seen = []
    for _ in range(3):
        p = update(p, "mc", True, weight=1.0)
        seen.append(round(p, 6))
    assert seen == [0.710733, 0.913664, 0.978259]


def test_frontend_mirror_of_bkt_constants():
    src = (REPO / "frontend/e2e/support/quiz.ts").read_text()
    found = {k: float(v) for k, v in re.findall(r"export const (BKT_L0|BKT_T|MC_G|MC_S) = ([0-9.]+);", src)}
    assert found == {
        "BKT_L0": params.BKT_L0,
        "BKT_T": params.BKT_T,
        "MC_G": params.CHANNELS["mc"]["G"],
        "MC_S": params.CHANNELS["mc"]["S"],
    }
    assert "MASTERY_PER_CORRECT" not in src and "masteryAfter" not in src
    assert "export function bktAfterCorrect(" in src


def test_frontend_mirror_reproduces_the_backend_posterior():
    """The TS function body is the §3.1 correct update + learn step; replay
    its arithmetic here so a drifted formula (not just drifted constants) fails."""
    src = (REPO / "frontend/e2e/support/quiz.ts").read_text()
    body = src[src.index("export function bktAfterCorrect(") :]
    body = body[: body.index("\n}\n")]
    assert "(p * (1 - MC_S)) / (p * (1 - MC_S) + (1 - p) * MC_G)" in body
    assert "post + (1 - post) * BKT_T" in body


def test_quiz_and_flashcards_read_no_gate():
    from routes import flashcards, quiz

    for mod in (quiz, flashcards):
        assert "learning_loop_active" not in inspect.getsource(mod), mod.__name__


def _submit(apply_mock, *, answers):
    with (
        patch("routes.quiz.table", side_effect=_loop_table()),
        patch("routes.quiz.apply_graph_update", new=apply_mock),
        patch("routes.quiz.get_quiz_context", return_value={}),
        patch("routes.quiz.quiz_context_agent.run", new=_noop_ctx_agent()),
        patch("routes.quiz.save_quiz_context"),
        patch("routes.quiz.events_service.log_event") as log_event,
    ):
        r = client.post("/api/quiz/submit", json={"quiz_id": "quiz1", "answers": answers})
    return r, log_event


@pytest.mark.parametrize("flag", [True, False])
def test_submit_is_evidence_only_under_either_flag(monkeypatch, flag):
    """No gate: the kill switch does not bring the flat delta back (spec §11.6)."""
    import config

    monkeypatch.setattr(config, "LEARNING_LOOP_ENABLED", flag)
    apply_mock = MagicMock(return_value=[{"before": 0.5, "after": 0.58}, {"before": 0.58, "after": 0.51}])
    r, _ = _submit(
        apply_mock,
        answers=[{"question_id": 1, "selected_label": "A"}, {"question_id": 2, "selected_label": "C"}],
    )
    assert r.status_code == 200, r.text
    apply_mock.assert_called_once()
    assert set(apply_mock.call_args[0][1]) == {"evidence"}


def test_submit_reports_p_delta_not_the_legacy_key():
    apply_mock = MagicMock(return_value=[{"before": 0.5, "after": 0.58}, {"before": 0.58, "after": 0.51}])
    r, log_event = _submit(
        apply_mock,
        answers=[{"question_id": 1, "selected_label": "A"}, {"question_id": 2, "selected_label": "C"}],
    )
    body = r.json()
    assert "p_delta" in body and LEGACY_DELTA_KEY not in body
    assert body["mastery_after"] == pytest.approx(body["mastery_before"] + body["p_delta"])
    assert body["p_delta"] == pytest.approx(0.01)
    (completed,) = [c for c in log_event.call_args_list if c.args and c.args[0] == "quiz.completed"]
    payload = completed.kwargs["payload"]
    assert LEGACY_DELTA_KEY not in payload
    assert payload["p_delta"] == pytest.approx(0.01)


# ── owner decision 2 (spec §13 A94, tightened by A100): quiz farming ─────────


class _Claims:
    """quiz_evidence_claims in memory: the INSERT ... ON CONFLICT DO NOTHING and
    the conditional stale-claim UPDATE, with Postgres's one-winner semantics."""

    def __init__(self, rows=None, *, fail=False):
        self.rows = dict(rows or {})  # question_hash -> claimed_at (datetime)
        self.fail = fail
        self.calls: list = []

    def handle(self):
        h = MagicMock()

        def insert_ignore_duplicates(rows, on_conflict=None):
            self.calls.append(("insert", on_conflict, [r["question_hash"] for r in rows]))
            if self.fail:
                raise RuntimeError("down")
            out = []
            for r in rows:
                if r["question_hash"] not in self.rows:
                    self.rows[r["question_hash"]] = datetime.fromisoformat(r["claimed_at"])
                    out.append(dict(r))
            return out

        def update(data, filters=None, **kw):
            self.calls.append(("update", dict(filters or {})))
            hashes = filters["question_hash"][len("in.(") : -1].split(",")
            cutoff = datetime.fromisoformat(filters["claimed_at"][len("lt.") :])
            out = []
            for qh in hashes:
                qh = qh.strip('"')
                if qh in self.rows and self.rows[qh] < cutoff:
                    self.rows[qh] = datetime.fromisoformat(data["claimed_at"])
                    out.append({"question_hash": qh})
            return out

        h.insert_ignore_duplicates.side_effect = insert_ignore_duplicates
        h.update.side_effect = update
        return h


def _farm_tables(claims: _Claims):
    base = _loop_table()
    return lambda name: claims.handle() if name == "quiz_evidence_claims" else base(name)


def _submit_with(factory, apply_mock, *, help_floors=None, help_fail=False):
    def _max_help_many(user_id, hashes):
        if help_fail:
            raise RuntimeError("ledger down")
        return {h: (help_floors or {}).get(h, 0) for h in hashes}

    with (
        patch("routes.quiz.table", side_effect=factory),
        patch("routes.quiz.apply_graph_update", new=apply_mock),
        patch("routes.quiz.max_help_many", side_effect=_max_help_many),
        patch("routes.quiz.get_quiz_context", return_value={}),
        patch("routes.quiz.quiz_context_agent.run", new=_noop_ctx_agent()),
        patch("routes.quiz.save_quiz_context"),
        patch("routes.quiz.events_service.log_event"),
    ):
        return client.post(
            "/api/quiz/submit",
            json={
                "quiz_id": "quiz1",
                "answers": [{"question_id": 1, "selected_label": "A"}, {"question_id": 2, "selected_label": "C"}],
            },
        )


def _hashes():
    from tests.test_quiz_scoring_e import LOOP_QUESTIONS
    from services.quiz_identity import question_hash

    return [
        LOOP_QUESTIONS[0]["question_hash"],
        question_hash("What is a function?", ["a loop", "a reusable block"]),
    ]


def test_a_question_claimed_within_the_window_writes_no_second_evidence():
    counted, _ = _hashes()
    claims = _Claims({counted: datetime.now(timezone.utc) - timedelta(hours=23)})
    apply_mock = MagicMock(return_value=[{"before": 0.5, "after": 0.45}])
    r = _submit_with(_farm_tables(claims), apply_mock)
    assert r.status_code == 200, r.text
    (ev,) = apply_mock.call_args[0][1]["evidence"]
    assert ev["question_hash"] != counted  # only the not-yet-claimed question
    insert, update = claims.calls
    assert insert[0] == "insert" and insert[1] == "user_id,question_hash"
    assert update[1]["user_id"] == "eq.user_andres" and update[1]["claimed_at"].startswith("lt.")


def test_the_window_is_rolling_24_hours_not_the_utc_day():
    """A claim 25 h old is stale whatever the calendar says; one 23 h old holds,
    even when it was taken 'yesterday' (A100: never the UTC day)."""
    old, recent = _hashes()
    now = datetime.now(timezone.utc)
    claims = _Claims({old: now - timedelta(hours=25), recent: now - timedelta(hours=23)})
    apply_mock = MagicMock(return_value=[{"before": 0.5, "after": 0.6}])
    r = _submit_with(_farm_tables(claims), apply_mock)
    assert r.status_code == 200, r.text
    (ev,) = apply_mock.call_args[0][1]["evidence"]
    assert ev["question_hash"] == old
    assert claims.rows[old] > now - timedelta(minutes=1)  # renewed to this submit


def test_every_question_claimed_moves_nothing():
    now = datetime.now(timezone.utc)
    claims = _Claims({h: now for h in _hashes()})
    apply_mock = MagicMock(return_value=[])
    r = _submit_with(_farm_tables(claims), apply_mock)
    assert r.status_code == 200, r.text
    apply_mock.assert_not_called()
    body = r.json()
    assert body["mastery_after"] == body["mastery_before"] and body["p_delta"] == 0


def test_a_failed_claim_fails_closed():
    apply_mock = MagicMock(return_value=[])
    r = _submit_with(_farm_tables(_Claims(fail=True)), apply_mock)
    assert r.status_code == 200, r.text
    apply_mock.assert_not_called()


def test_concurrent_submits_sharing_a_hash_write_it_once():
    """Two attempts' submits race on the same hashes: the claim table arbitrates,
    so the second guard keeps none of them (A100; real-SQL proof in
    tests/integration/test_quiz_evidence_claims_db.py)."""
    from routes.quiz import _farm_guard

    claims = _Claims()
    evs = [{"question_hash": h, "node_id": "n", "correct": True} for h in _hashes()]
    with patch("routes.quiz.table", side_effect=_farm_tables(claims)):
        first = _farm_guard("user_andres", "attempt-a", [dict(e) for e in evs])
        second = _farm_guard("user_andres", "attempt-b", [dict(e) for e in evs])
    assert [e["question_hash"] for e in first] == _hashes()
    assert second == []


def test_a_dropped_evidence_insert_does_not_reopen_the_question():
    """The old guard counted node_mastery_events, so an evidence row the graph
    write dropped left the question farmable; the claim is the guard's own
    journal, taken before the write, and stands whatever the write does."""
    from routes.quiz import _farm_guard

    claims = _Claims()
    evs = [{"question_hash": h, "node_id": "n", "correct": True} for h in _hashes()]
    with patch("routes.quiz.table", side_effect=_farm_tables(claims)):
        assert len(_farm_guard("user_andres", "attempt-a", [dict(e) for e in evs])) == 2
        # (the evidence write is apply_graph_update's; whatever it dropped, the claim stands)
        assert _farm_guard("user_andres", "attempt-b", [dict(e) for e in evs]) == []


def test_hashless_questions_count_once_per_attempt():
    from routes.quiz import _farm_guard

    evs = [
        {"question_hash": None, "node_id": "n", "correct": True},
        {"question_hash": None, "node_id": "n", "correct": True},
        {"question_hash": "h1", "node_id": "n", "correct": True},
        {"question_hash": "h1", "node_id": "n", "correct": False},  # the same item twice
    ]
    with patch("routes.quiz.table", side_effect=_farm_tables(_Claims())):
        kept = _farm_guard("user_andres", "quiz1", evs)
    assert [e["question_hash"] for e in kept] == [None, "h1"]


# ── spec §13 A99: the help ledger's floor on quiz evidence ───────────────────


@pytest.mark.parametrize(
    "floor, rung, weight_zero",
    [(params.RUNG_ASSISTED_MIN, params.RUNG_ASSISTED_MIN, False), (params.RUNG_NO_CREDIT_MIN, params.RUNG_NO_CREDIT_MIN, True)],
)
def test_a_question_with_recorded_help_is_graded_at_its_floor(floor, rung, weight_zero):
    from learning.evidence import Evidence

    asked, other = _hashes()
    apply_mock = MagicMock(return_value=[{"before": 0.5, "after": 0.5}, {"before": 0.5, "after": 0.4}])
    r = _submit_with(_farm_tables(_Claims()), apply_mock, help_floors={asked: floor})
    assert r.status_code == 200, r.text
    by_hash = {e["question_hash"]: e for e in apply_mock.call_args[0][1]["evidence"]}
    assert by_hash[asked]["max_rung"] == rung and by_hash[asked]["assisted"] is True
    assert "max_rung" not in by_hash[other] and "assisted" not in by_hash[other]
    ev = Evidence(**{**by_hash[asked], "correct": True})
    assert (ev.weight == 0.0) is weight_zero


def test_a_question_asked_about_earns_no_unassisted_credit_end_to_end():
    """The quiz-ask session's help row (services/quiz_ask.py, RUNG_NO_CREDIT_MIN)
    makes a CORRECT answer to that question weigh nothing upward."""
    from learning.evidence import Evidence
    from services.quiz_ask import QUIZ_ASK_HELP_RUNG

    asked, _ = _hashes()
    apply_mock = MagicMock(return_value=[{"before": 0.5, "after": 0.5}])
    r = _submit_with(_farm_tables(_Claims()), apply_mock, help_floors={asked: QUIZ_ASK_HELP_RUNG})
    assert r.status_code == 200, r.text
    ev = next(e for e in apply_mock.call_args[0][1]["evidence"] if e["question_hash"] == asked)
    assert ev["correct"] is True  # question 1 answered right ("A")
    assert Evidence(**ev).weight == 0.0


def test_an_unreadable_help_ledger_fails_closed():
    apply_mock = MagicMock(return_value=[{"before": 0.5, "after": 0.5}])
    r = _submit_with(_farm_tables(_Claims()), apply_mock, help_fail=True)
    assert r.status_code == 200, r.text
    for ev in apply_mock.call_args[0][1]["evidence"]:
        assert ev["max_rung"] == params.RUNG_NO_CREDIT_MIN and ev["assisted"] is True


def test_the_help_floor_is_one_batched_read_after_the_farm_guard():
    from routes.quiz import _help_floor

    seen = []
    evs = [{"question_hash": "h1"}, {"question_hash": None}, {"question_hash": "h2"}]
    with patch("routes.quiz.max_help_many", side_effect=lambda u, hs: seen.append(list(hs)) or {"h1": 0, "h2": 2}):
        out = _help_floor("user_andres", evs)
    assert seen == [["h1", "h2"]]
    assert out[0] == {"question_hash": "h1"} and out[1] == {"question_hash": None}
    assert out[2] == {"question_hash": "h2", "max_rung": 2, "assisted": True}


@pytest.mark.parametrize(
    "kind,key,right,wrong",
    [
        ("short_answer", "base case", "The base case.", "loop body"),
        ("numeric", "0.5", "1/2", "99"),
        ("symbolic", "2*x+2", "2(x+1)", "x"),
    ],
)
@pytest.mark.parametrize("correct", [True, False])
@pytest.mark.parametrize(
    "floor", [0, params.RUNG_ASSISTED_MIN, params.RUNG_NO_CREDIT_MIN]
)
def test_recorded_written_grades_keep_conservative_evidence_and_guards(
    kind, key, right, wrong, correct, floor
):
    """Real answer/submit handlers, no agent: typed input changes neither the
    evidence channel nor help/replay policy. First recorded answers still win,
    including an incorrect answer later retried with the correct key."""
    from learning.evidence import Evidence, is_strong_channel
    from services.encryption import decrypt_json_column
    from services.quiz_identity import question_hash

    qh = question_hash(f"Written {kind} example?", [])
    question = {
        "id": 1,
        "question": f"Written {kind} example?",
        "type": kind,
        "options": [],
        "correct_answer": key,
        "explanation": "Compare with the stored answer.",
        "question_hash": qh,
    }
    responses = _ResponsesTable()
    claims = _Claims()
    attempts = {
        attempt_id: {
            "id": attempt_id,
            "user_id": "user_andres",
            "concept_node_id": "node1",
            "questions_json": [question],
        }
        for attempt_id in ("written-first", "written-repeat")
    }
    attempt_table = MagicMock()

    def select_attempt(columns="*", filters=None, **_):
        return [dict(attempts[filters["id"].removeprefix("eq.")])]

    def update_attempt(data, filters=None, **_):
        row = attempts[filters["id"].removeprefix("eq.")]
        if any(row.get(k) is not None for k, v in filters.items() if v == "is.null"):
            return []
        row.update(data)
        return [dict(row)]

    attempt_table.select.side_effect = select_attempt
    attempt_table.update.side_effect = update_attempt
    base = _loop_table([question])

    def tables(name):
        if name == "quiz_attempts":
            return attempt_table
        if name == "quiz_responses":
            return responses
        if name == "quiz_evidence_claims":
            return claims.handle()
        return base(name)

    apply_mock = MagicMock(return_value=[])
    selected, revision = (right, wrong) if correct else (wrong, right)
    with (
        patch("routes.quiz.table", side_effect=tables),
        patch("routes.quiz.apply_graph_update", new=apply_mock),
        patch("routes.quiz.max_help_many", return_value={qh: floor}),
        patch("routes.quiz.get_quiz_context", return_value={}),
        patch("routes.quiz.quiz_context_agent.run", new=_noop_ctx_agent()),
        patch("routes.quiz.save_quiz_context"),
        patch("routes.quiz.events_service.log_event"),
    ):
        first = client.post(
            "/api/quiz/attempts/written-first/answer",
            json={"question_index": 0, "answer_text": selected, "confidence": 0.99},
        )
        revised = client.post(
            "/api/quiz/attempts/written-first/answer",
            json={"question_index": 0, "answer_text": revision},
        )
        completed = client.post(
            "/api/quiz/submit",
            json={
                "quiz_id": "written-first",
                "answers": [{"question_id": 1, "selected_label": key}],
            },
        )
        # Another legitimate attempt can record/score the same item, but cannot
        # turn a repeated written answer into another mastery observation.
        repeat_answer = client.post(
            "/api/quiz/attempts/written-repeat/answer",
            json={"question_index": 0, "answer_text": right},
        )
        repeat = client.post(
            "/api/quiz/submit", json={"quiz_id": "written-repeat", "answers": []}
        )

    for response in (first, revised, completed, repeat_answer, repeat):
        assert response.status_code == 200, response.text
    assert first.json()["is_correct"] is correct
    assert revised.json()["is_correct"] is correct
    assert revised.json()["recorded"] is False
    assert completed.json()["results"][0]["selected"] == selected
    assert completed.json()["score"] == int(correct)
    assert repeat.json()["score"] == 1
    assert len(responses.rows) == 2
    assert responses.rows[0]["selected_index"] is None
    assert decrypt_json_column(responses.rows[0]["answer_text"]) == {"text": selected}
    assert decrypt_json_column(attempts["written-first"]["answers_json"]) == [
        {"question_id": 1, "answer_text": selected}
    ]

    apply_mock.assert_called_once()
    assert apply_mock.call_args.args[0] == "user_andres"
    assert apply_mock.call_args.kwargs == {"course_id": "course1"}
    (raw,) = apply_mock.call_args.args[1]["evidence"]
    evidence = Evidence(**raw)
    assert evidence.node_id == "node1" and evidence.question_hash == qh
    assert evidence.correct is correct and evidence.channel == "mc"
    assert is_strong_channel(evidence.channel) is False
    assert evidence.max_rung == floor
    assert evidence.assisted is bool(floor)
    expected_weight = 1.0
    if correct and floor >= params.RUNG_NO_CREDIT_MIN:
        expected_weight = 0.0
    elif correct and floor >= params.RUNG_ASSISTED_MIN:
        expected_weight = params.WEIGHT_ASSISTED
    assert evidence.weight == expected_weight
    assert evidence.confidence is None  # student confidence is not grader confidence
    assert evidence.planning_provenance is None
    assert evidence.check_item_id is None and evidence.session_id is None
    assert set(claims.rows) == {qh}
    assert repeat.json()["p_delta"] == 0


def test_students_cannot_ask_for_the_answer_key(monkeypatch):
    """Owner decision 2: include_answer_key=true is admin-only (403 before any
    generation); the shipped client always sends false."""
    import services.auth_guard as ag
    import routes.quiz as quiz

    monkeypatch.setattr(quiz, "require_admin", ag._real_require_admin)
    monkeypatch.setattr(ag, "table", lambda name: MagicMock(select=MagicMock(return_value=[])))
    run = MagicMock(side_effect=AssertionError("generation ran"))
    with patch("routes.quiz.quiz_agent.run", new=run):
        r = client.post(
            "/api/quiz/generate",
            json={"user_id": "user_andres", "concept_node_id": "node1", "include_answer_key": True},
        )
    assert r.status_code == 403
    run.assert_not_called()

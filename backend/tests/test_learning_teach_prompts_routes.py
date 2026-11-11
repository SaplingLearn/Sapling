"""Spec §13 A138 / A139 through the loop routes, flags ON (the flag-off loop is
pinned byte-identical to f9eca612 by test_learning_teach_prompts_flag_off.py):
the segment prequestion — posed at a segment start (the plan approval, a
feedback turn that moves the cursor, a self-explanation prompt closing),
skipped with its reason, answered (stored encrypted, revealed, never graded),
explained by the next teach turn (the answer from code first), superseded —
and the self-explanation prompts — the juncture's prompt as the turn's one
question, the cap, the precedence rules, the reply route, the acknowledgement.
Nothing here is evidence: no grade, no flush, no help-ledger rung, no
misconception, no band verdict."""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from agents.loop_tutor import PREQUESTION_LINE, SELF_EXPLAIN_ACK_LINE
from learning import prequestion as pq
from learning import self_explain as se
from learning.checks import CheckItem, Option, RubricItem, WrongReason
from tests import test_learn_loop_routes as _routes
from tests.test_learn_loop_routes import (
    HARD,
    ITEM,
    NOW,
    _graded,
    _json_agent,
    _plan_state,
    _state,
    client,
)

gate_on, no_rate_limit, seams = _routes.gate_on, _routes.no_rate_limit, _routes.seams


def _item(qh: str, fmt: str, difficulty: int) -> CheckItem:
    options = correct = None
    if fmt == "mc_reason":
        options = [
            Option(letter="A", text="a list per slot", wrong_key="chains"),
            Option(letter="B", text="the next free slot"),
            Option(letter="C", text="a second hash", wrong_key="double"),
            Option(letter="D", text="a resize", wrong_key="resize"),
        ]
        correct = "B"
    return CheckItem(
        id=f"id-{qh}",
        course_id="c1",
        concept_key="recursion",
        format=fmt,
        difficulty=difficulty,
        prompt=f"Where does a colliding key go? [{qh}]",
        reference_answer="It goes to the next free slot. Final answer: the next free slot",
        final_answer="the next free slot",
        rubric=[RubricItem(id="r1", text="names the slot"), RubricItem(id="r2", text="next")],
        common_wrong=[WrongReason(key="chains", text="a list")],
        options=options,
        correct_option=correct,
        source_chunk_ids=["ch-9"],
        question_hash=qh,
        created_at="2026-11-01T00:00:00+00:00",
    )


PQ = _item("qh-pq", "mc_reason", 1)
#: The concept's bank: the prequestion candidate, the free difficulty-2 cell
#: that takes the post-test reserves (A23, A126) and enough for the checks.
BANK = [PQ, _item("qh-r1", "free", 2), _item("qh-r2", "free", 2),
        _item("qh-t1", "teachback", 3), _item("qh-t2", "teachback", 3), _item("qh-t3", "teachback", 3)]
_BY_ID = {i.id: i for i in BANK}
_CHAT = {"session_id": "s1", "user_id": "u1"}


@pytest.fixture
def on(seams):
    """Both flags on, the bank above for every concept, the real reserves rule."""
    seams.pq_flag.return_value = True
    seams.se_flag.return_value = True
    seams.list_items.return_value = list(BANK)
    seams.item.side_effect = lambda cid: _BY_ID.get(cid, ITEM)
    from learning.checks import posttest_reserves as real_reserves

    seams.reserve.side_effect = real_reserves

    def stored(user_id, session_id, node_id):
        """The commit point's read-back: the FIRST stored answer stands."""
        for c in store.call_args_list:
            if c.kwargs["node_id"] == node_id and c.kwargs["session_id"] == session_id:
                k = c.kwargs
                return {"question_hash": k["item"].question_hash, "no_idea": k["no_idea"], "guess": k["guess"]}
        return None

    with (
        patch("routes.learn_loop.store_prequestion_answer") as store,
        patch("routes.learn_loop.stored_prequestion_answer", side_effect=stored) as read_back,
        patch("routes.learn_loop.record_self_explain_prompt") as se_record,
        patch("routes.learn_loop.close_self_explain_prompt", return_value="won") as se_close,
        patch("routes.learn_loop.record_help") as help_rows,
        patch("routes.learn_loop.record_posed") as posed_rows,
        patch("routes.learn_loop.mark_graded") as closed_rows,
        patch("routes.learn_loop.store_brief"),
    ):
        seams.pq_store, seams.se_record, seams.se_close, seams.help_rows = store, se_record, se_close, help_rows
        seams.pq_read_back, seams.posed_rows, seams.closed_rows = read_back, posed_rows, closed_rows
        yield seams


def _events(seams, name: str) -> list[dict]:
    return [c.kwargs["payload"] for c in seams.events.log_event.call_args_list if c.args[0] == name]


def _saved(seams) -> list[tuple[str, str]]:
    return [(c.args[1], c.args[2]) for c in seams.save_msg.call_args_list]


def _run(seams, path: str, body: dict, *, reply=None):
    agent, seen = _json_agent(reply) if reply is not None else _json_agent()
    with (
        patch("routes.learn_loop.loop_tutor_agent", agent),
        patch("routes.learn_loop.record_agent_usage", side_effect=lambda r, **k: r),
    ):
        r = client.post(f"/api/learn/loop{path}", json=body)
    return r, seen


def _no_evidence(seams) -> None:
    """Never graded, never evidence, no help rung, no band verdict."""
    seams.grade.assert_not_called()
    seams.flush.assert_not_called()
    seams.help_rows.assert_not_called()
    assert not seams.zpd.emit_zpd_band_adjust.called


# ── A138: posing at the plan approval ──────────────────────────────────────


def _plan_doc(kinds=None) -> dict:
    return {"phase": "plan", "plan": {"proposed": ["node-1", "node-2"],
                                       "proposed_kinds": kinds or {"node-1": "new", "node-2": "new"}}}


def test_the_plan_approval_poses_the_first_segments_prequestion(gate_on, on):
    on.store["doc"] = _plan_doc()
    r = client.post("/api/learn/loop/plan/approve", json={**_CHAT, "concept_ids": ["node-1", "node-2"]})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["prequestion"] == pq.pose_payload(PQ)
    assert "correct" not in json.dumps(body) and PQ.final_answer not in body["prequestion"]["prompt"]
    rec = on.store["doc"]["prequestion"]["node-1"]
    assert rec == {"status": "posed", "question_hash": "qh-pq", "check_item_id": "id-qh-pq",
                   "format": "mc_reason", "difficulty": 1, "posed_at": NOW}
    assert on.store["doc"]["open_question"] is False
    assert ("assistant", pq.pose_text(PQ)) in _saved(on)
    assert _events(on, "learn.prequestion") == [{"session_id": "s1", "node_id": "node-1", "status": "posed",
                                                 "question_hash": "qh-pq", "format": "mc_reason", "difficulty": 1}]
    _no_evidence(on)


def test_a_due_review_opens_without_one_and_says_why(gate_on, on):
    on.store["doc"] = _plan_doc({"node-1": "review", "node-2": "new"})
    r = client.post("/api/learn/loop/plan/approve", json={**_CHAT, "concept_ids": ["node-1", "node-2"]})
    assert r.status_code == 200 and "prequestion" not in r.json()
    assert on.store["doc"]["prequestion"]["node-1"] == {"status": "skipped", "reason": "review"}
    assert _events(on, "learn.prequestion") == [{"session_id": "s1", "node_id": "node-1", "status": "skipped",
                                                 "reason": "review"}]


def test_a_proficient_concept_opens_without_one(gate_on, on):
    on.p_known["node-1"] = 0.9
    on.store["doc"] = _plan_doc()
    r = client.post("/api/learn/loop/plan/approve", json={**_CHAT, "concept_ids": ["node-1"]})
    assert "prequestion" not in r.json()
    assert on.store["doc"]["prequestion"]["node-1"] == {"status": "skipped", "reason": "proficient"}


def test_a_thin_pool_keeps_its_checks(gate_on, on):
    on.list_items.return_value = [PQ, _item("qh-r1", "free", 2)]
    on.store["doc"] = _plan_doc()
    r = client.post("/api/learn/loop/plan/approve", json={**_CHAT, "concept_ids": ["node-1"]})
    assert "prequestion" not in r.json()
    assert on.store["doc"]["prequestion"]["node-1"]["reason"] == "pool_for_checks"


@pytest.mark.parametrize("source", ["seen_hashes", "revealed_hashes", "reported_hashes"])
def test_seen_revealed_and_reported_items_are_never_posed(gate_on, on, source):
    """qh-pq (multiple choice) and qh-r2 (free, difficulty 2; qh-r1 is the
    post-test reserve) are the candidates: each exclusion source alone takes
    the first, and with both gone nothing is left to pose."""
    getattr(on, source).return_value = {"qh-pq"}
    on.store["doc"] = _plan_doc()
    r = client.post("/api/learn/loop/plan/approve", json={**_CHAT, "concept_ids": ["node-1"]})
    assert r.json()["prequestion"]["question_hash"] == "qh-r2"
    getattr(on, source).return_value = {"qh-pq", "qh-r2"}
    on.store["doc"] = _plan_doc()
    r = client.post("/api/learn/loop/plan/approve", json={**_CHAT, "concept_ids": ["node-1"]})
    assert "prequestion" not in r.json()
    assert on.store["doc"]["prequestion"]["node-1"] == {"status": "skipped", "reason": "no_item"}


def test_a_failed_read_poses_nothing_and_records_nothing(gate_on, on):
    on.list_items.side_effect = RuntimeError("down")
    on.store["doc"] = _plan_doc()
    r = client.post("/api/learn/loop/plan/approve", json={**_CHAT, "concept_ids": ["node-1"]})
    assert r.status_code == 200 and "prequestion" not in r.json()
    assert "prequestion" not in on.store["doc"]


# ── A138: the answer and its explanation ───────────────────────────────────


def _posed(**over) -> dict:
    st = _plan_state()
    st["prequestion"] = {"node-1": pq.pose_record(PQ, "node-1", NOW - 30)}
    st["open_question"] = False
    st.update(over)
    return st


def _answer(**fields):
    return {**_CHAT, "question_hash": "qh-pq", **fields}


def test_a_guess_is_stored_revealed_and_explained_never_graded(gate_on, on):
    on.store["doc"] = _posed()
    with patch("routes.learn_loop.phase_prefix", wraps=__import__("agents.loop_tutor", fromlist=["x"]).phase_prefix):
        r, seen = _run(on, "/prequestion/answer", _answer(option="A", reason="it chains"))
    assert r.status_code == 200, r.text
    body = r.json()
    # the store: the guess (encrypted by the store) with the item's class
    kw = on.pq_store.call_args.kwargs
    assert kw["guess"] == {"option": "A", "reason": "it chains"} and kw["no_idea"] is False
    assert kw["item"].question_hash == "qh-pq" and kw["node_id"] == "node-1" and kw["session_id"] == "s1"
    # revealed for the student at once (A88), before any text
    on.record_reveals.assert_called_once_with("u1", ["qh-pq"], session_id="s1", source="prequestion")
    # the explaining turn: the [PREQUESTION] line, the item as posed, its answer as data
    assert PREQUESTION_LINE in seen["msg"]
    assert "[PREQUESTION ITEM] (format: mc_reason)\n" + PQ.prompt in seen["msg"]
    assert "B. the next free slot" in seen["msg"] and "[PREQUESTION ANSWER]" in seen["msg"]
    assert "source=prequestion_answer" in seen["msg"]
    # the cue is trusted route text; the student's guess is their saved row (enveloped history)
    assert "<<student_text" not in seen["msg"].split("[PREQUESTION ANSWER]")[0]
    # served: the answer from code first, then the model's turn
    assert body["reply"].startswith("The answer: B. the next free slot\n\nKey idea: ")
    assert body["prequestion_answered"] is True and body["phase"] == "teach"
    assert ("user", "My guess: A — it chains") in _saved(on)
    assert ("assistant", body["reply"]) in _saved(on)
    doc = on.store["doc"]
    rec = doc["prequestion"]["node-1"]
    assert rec["status"] == "resolved" and rec["answered_at"] == NOW and rec["resolved_at"] == NOW
    assert rec["no_idea"] is False and doc["teach_turns"] == 1
    assert [e["status"] for e in _events(on, "learn.prequestion")] == ["answered", "resolved"]
    answered = _events(on, "learn.prequestion")[0]
    assert answered == {"session_id": "s1", "node_id": "node-1", "status": "answered", "question_hash": "qh-pq",
                        "no_idea": False, "format": "mc_reason", "difficulty": 1}
    assert "it chains" not in json.dumps(on.events.log_event.call_args_list, default=str)
    _no_evidence(on)


def test_the_explanation_uses_the_items_own_passages_not_a_retrieval(gate_on, on):
    on.store["doc"] = _posed()
    _run(on, "/prequestion/answer", _answer(no_idea=True))
    kw = on.blocks.call_args.kwargs
    assert kw["item"].question_hash == "qh-pq"
    assert kw["context"].rag_k == 0 and kw["context"].source_chunks == 2


def test_no_idea_is_a_full_answer(gate_on, on):
    on.store["doc"] = _posed()
    r, _ = _run(on, "/prequestion/answer", _answer(no_idea=True))
    assert r.status_code == 200
    assert on.pq_store.call_args.kwargs["no_idea"] is True and on.pq_store.call_args.kwargs["guess"] is None
    assert ("user", "No idea.") in _saved(on)
    assert _events(on, "learn.prequestion")[0]["no_idea"] is True


def test_a_free_guess(gate_on, on):
    free = _item("qh-pq", "free", 1)
    _BY_ID_FREE = {**_BY_ID, free.id: free}
    on.item.side_effect = lambda cid: _BY_ID_FREE.get(cid, ITEM)
    on.store["doc"] = _posed()
    r, _ = _run(on, "/prequestion/answer", _answer(answer=" the next one "))
    assert r.status_code == 200 and r.json()["reply"].startswith("The answer: " + free.reference_answer)
    assert on.pq_store.call_args.kwargs["guess"] == {"answer": "the next one"}


@pytest.mark.parametrize("body", [_answer(option="Z"), _answer(), _answer(answer="x")])
def test_a_guess_that_is_none_of_the_options_is_refused_and_nothing_is_stored(gate_on, on, body):
    on.store["doc"] = _posed()
    r, _ = _run(on, "/prequestion/answer", body)
    assert r.status_code == 422
    on.pq_store.assert_not_called()
    on.record_reveals.assert_not_called()
    assert on.store["doc"]["prequestion"]["node-1"]["status"] == "posed"


@pytest.mark.parametrize(
    "doc,body",
    [
        (_posed(), _answer(question_hash="qh-other", no_idea=True)),
        (_plan_state(), _answer(no_idea=True)),
        (_posed(prequestion={"node-1": {"status": "skipped", "reason": "review"}}), _answer(no_idea=True)),
        (_posed(prequestion={"node-1": {**pq.pose_record(PQ, "node-1", NOW), "status": "superseded"}}),
         _answer(no_idea=True)),
    ],
)
def test_no_open_prequestion_is_a_409(gate_on, on, doc, body):
    on.store["doc"] = doc
    r, _ = _run(on, "/prequestion/answer", body)
    assert r.status_code == 409 and r.json()["detail"] == "no open prequestion"
    on.pq_store.assert_not_called()


def test_the_flag_off_answers_409_and_stores_nothing(gate_on, on):
    on.pq_flag.return_value = False
    on.store["doc"] = _posed()
    r, _ = _run(on, "/prequestion/answer", _answer(no_idea=True))
    assert r.status_code == 409
    on.pq_store.assert_not_called()


def test_a_retry_keeps_the_stored_guess_and_serves_the_explanation_again(gate_on, on):
    st = _posed()
    st["prequestion"]["node-1"].update(status="answered", answered_at=NOW - 5, no_idea=True)
    on.store["doc"] = st
    r, seen = _run(on, "/prequestion/answer", _answer(option="C"))
    assert r.status_code == 200 and PREQUESTION_LINE in seen["msg"]
    on.pq_store.assert_not_called()
    on.record_reveals.assert_not_called()
    assert not [s for s in _saved(on) if s[0] == "user"]
    assert on.store["doc"]["prequestion"]["node-1"]["status"] == "resolved"


@pytest.mark.parametrize(
    "retry", [_answer(option="C"), _answer(no_idea=True), _answer(option="A", reason="edited"), _answer(option="A")]
)
def test_the_stored_row_is_the_commit_point_and_a_retry_explains_it(gate_on, on, retry):
    # second review: a first request stored its guess, then failed before the
    # record moved (its claim given back). ANY retry — another option, "No
    # idea", an edited or empty reason — commits THAT stored guess and explains
    # it: a 409 here left the student stuck behind a card nothing could close.
    on.store["doc"] = _posed()
    stored_first = {"question_hash": "qh-pq", "no_idea": False, "guess": {"option": "A", "reason": "it chains"}}
    on.pq_read_back.side_effect = lambda *a: stored_first
    r, seen = _run(on, "/prequestion/answer", retry)
    assert r.status_code == 200, r.text
    assert PREQUESTION_LINE in seen["msg"]
    assert [s for s in _saved(on) if s[0] == "user"] == [("user", "My guess: A — it chains")]
    answered = _events(on, "learn.prequestion")[0]
    assert answered["status"] == "answered" and answered["no_idea"] is False
    rec = on.store["doc"]["prequestion"]["node-1"]
    assert rec["status"] == "resolved" and rec["no_idea"] is False
    assert "answer_claim" not in rec and "answer_claim_at" not in rec


def test_a_commit_whose_card_was_superseded_meanwhile_is_a_409(gate_on, on):
    # second review, item 3: a claim that stalled past its staleness lost its
    # card to "Check me" — the commit must not flip it to answered over the check
    on.store["doc"] = _posed()

    def stalled(*_):
        rec = on.store["doc"]["prequestion"]["node-1"]
        on.store["doc"]["prequestion"]["node-1"] = {**rec, "status": "superseded"}  # claim keys kept
        return {"question_hash": "qh-pq", "no_idea": True, "guess": None}

    on.pq_read_back.side_effect = stalled
    r, _ = _run(on, "/prequestion/answer", _answer(no_idea=True))
    assert r.status_code == 409
    assert on.store["doc"]["prequestion"]["node-1"]["status"] == "superseded"
    assert not _saved(on) and "answered" not in [e["status"] for e in _events(on, "learn.prequestion")]


def test_a_supersede_strips_a_stale_claim(gate_on, on):
    doc = _posed(teach_turns=1)
    doc["prequestion"]["node-1"].update(answer_claim="old", answer_claim_at=NOW - 10_000)  # stale
    on.store["doc"] = doc
    r = client.post("/api/learn/loop/check/next", json=_CHAT)
    assert r.status_code == 200, r.text
    rec = on.store["doc"]["prequestion"]["node-1"]
    assert rec["status"] == "superseded" and "answer_claim" not in rec and "answer_claim_at" not in rec


def test_the_posed_row_stays_open_when_the_reveal_was_lost(gate_on, on):
    # second review, item 4: with no reveal recorded, the item stays in A88's scan
    from routes.learn_loop import _spend_prequestion_item

    with patch("routes.learn_loop._persist_reveals", return_value=False):
        _spend_prequestion_item("u1", "s1", "qh-pq", at=NOW)
    on.closed_rows.assert_not_called()
    with patch("routes.learn_loop._persist_reveals", return_value=True):
        _spend_prequestion_item("u1", "s1", "qh-pq", at=NOW)
    on.closed_rows.assert_called_once_with("u1", "qh-pq")


def test_a_failed_store_gives_the_claim_back_and_serves_nothing(gate_on, on):
    on.store["doc"] = _posed()
    on.pq_store.side_effect = RuntimeError("db down")
    r, _ = _run(on, "/prequestion/answer", _answer(no_idea=True))
    assert r.status_code == 503
    rec = on.store["doc"]["prequestion"]["node-1"]
    assert rec["status"] == "posed" and "answer_claim" not in rec
    on.record_reveals.assert_not_called()
    assert not _saved(on)


def test_a_guess_under_another_live_claim_is_a_409(gate_on, on):
    doc = _posed()
    doc["prequestion"]["node-1"].update(answer_claim="other", answer_claim_at=NOW - 1)
    on.store["doc"] = doc
    r, _ = _run(on, "/prequestion/answer", _answer(no_idea=True))
    assert r.status_code == 409 and "being saved" in r.json()["detail"]
    on.pq_store.assert_not_called()


def test_the_explaining_turn_carries_no_self_explanation_acknowledgement(gate_on, on):
    # review fix (A139 x A138): a reply that closed a segment poses the next
    # prequestion; that prequestion's explaining turn is about the new concept,
    # so the acknowledgement is dropped there (and consumed)
    doc = _posed()
    se.set_ack(doc, "p-1")
    on.store["doc"] = doc
    r, seen = _run(on, "/prequestion/answer", _answer(no_idea=True))
    assert r.status_code == 200 and PREQUESTION_LINE in seen["msg"]
    assert SELF_EXPLAIN_ACK_LINE not in seen["msg"]
    assert not se.ack_due(on.store["doc"])


def test_any_next_teach_turn_explains_an_answered_prequestion(gate_on, on):
    """A failed explaining turn is retried by whatever teach turn comes next."""
    st = _posed()
    st["prequestion"]["node-1"].update(status="answered", answered_at=NOW - 5, no_idea=True)
    on.store["doc"] = st
    r, seen = _run(on, "/chat", {**_CHAT, "message": "Let's continue."})
    assert PREQUESTION_LINE in seen["msg"] and r.json()["reply"].startswith("The answer: B.")
    assert "<<student_text" in seen["msg"]  # the chat message stays the student's
    assert on.store["doc"]["prequestion"]["node-1"]["status"] == "resolved"


def test_at_the_hard_level_the_answer_still_follows_as_a_template(gate_on, on):
    on.ai_budget.check.return_value = HARD
    on.store["doc"] = _posed()
    r, seen = _run(on, "/prequestion/answer", _answer(no_idea=True))
    assert r.status_code == 200, r.text
    assert "msg" not in seen, "no model run at the hard level"
    assert r.json()["reply"] == "The answer: B. the next free slot\n\n" + pq.HARD_LEVEL_LINE
    assert on.store["doc"]["prequestion"]["node-1"]["status"] == "resolved"


def test_a_chat_turn_while_the_card_is_open_supersedes_it(gate_on, on):
    on.store["doc"] = _posed()
    r, seen = _run(on, "/chat", {**_CHAT, "message": "Actually, what is hashing?"})
    assert r.status_code == 200 and PREQUESTION_LINE not in seen["msg"]
    assert not r.json()["reply"].startswith("The answer:")
    assert on.store["doc"]["prequestion"]["node-1"]["status"] == "superseded"
    assert _events(on, "learn.prequestion") == [{"session_id": "s1", "node_id": "node-1",
                                                 "status": "superseded", "question_hash": "qh-pq"}]
    # review fix: the item is SPENT — a turn was served while its question was
    # open, and that text cannot be trusted not to have worked it
    on.record_reveals.assert_called_once_with("u1", ["qh-pq"], session_id="s1", source="prequestion")
    on.closed_rows.assert_called_once_with("u1", "qh-pq")  # its 'posed' row leaves the scan set


def test_check_me_while_the_card_is_open_supersedes_it_and_never_poses_its_item(gate_on, on):
    on.store["doc"] = _posed(teach_turns=1)
    r = client.post("/api/learn/loop/check/next", json=_CHAT)
    assert r.status_code == 200 and r.json()["check"]["question_hash"] != "qh-pq"
    assert on.store["doc"]["prequestion"]["node-1"]["status"] == "superseded"
    assert "qh-pq" in on.select_item.call_args.kwargs["exclude_hashes"]
    assert ["qh-pq"] in [c.args[1] for c in on.record_reveals.call_args_list]  # spent


def test_the_posed_card_is_in_the_served_text_scan(gate_on, on):
    # review fix (A88/A93): the pose writes the ledger's 'posed' row, so a turn
    # served while the card is open is scanned for its answer like a check's
    on.store["doc"] = _plan_doc()
    r = client.post("/api/learn/loop/plan/approve", json={**_CHAT, "concept_ids": ["node-1", "node-2"]})
    assert r.status_code == 200, r.text
    on.posed_rows.assert_called_once_with("u1", "qh-pq", source="prequestion", session_id="s1")


def test_a_guess_being_saved_holds_the_card(gate_on, on):
    # review fix: under a live answer claim no check opens and no turn supersedes
    doc = _posed(teach_turns=1)
    doc["prequestion"]["node-1"].update(answer_claim="c-1", answer_claim_at=NOW)
    on.store["doc"] = doc
    r = client.post("/api/learn/loop/check/next", json=_CHAT)
    assert r.status_code == 409 and "being saved" in r.json()["detail"]
    r, _ = _run(on, "/chat", {**_CHAT, "message": "What is hashing?"})
    assert r.status_code == 200 and on.store["doc"]["prequestion"]["node-1"]["status"] == "posed"
    from routes.learn_loop import _grading_in_flight

    assert _grading_in_flight(on.store["doc"], NOW) is True  # a close waits for it


def test_activation_never_serves_a_prequestion_item_of_the_session(seams):
    from routes.learn_loop import _activate_next_item

    seams.list_items.return_value = list(BANK)
    st = _plan_state(prequestion={"node-1": {**pq.pose_record(PQ, "node-1", NOW), "status": "resolved"}})
    _activate_next_item("u1", "c1", st, now=NOW)
    assert "qh-pq" in seams.select_item.call_args.kwargs["exclude_hashes"]


def test_status_restores_an_open_card_and_an_owed_explanation(gate_on, on):
    on.store["doc"] = _posed()
    r = client.get("/api/learn/loop/status?user_id=u1&session_id=s1")
    assert r.json()["prequestion"] == pq.pose_payload(PQ)
    on.store["doc"]["prequestion"]["node-1"]["status"] = "answered"
    r = client.get("/api/learn/loop/status?user_id=u1&session_id=s1")
    assert r.json()["prequestion"]["answered"] is True
    on.pq_flag.return_value = False
    r = client.get("/api/learn/loop/status?user_id=u1&session_id=s1")
    assert "prequestion" not in r.json()


# ── A138: a feedback turn that starts the next segment ──────────────────────


def _segment_end(verdict="correct", **step) -> dict:
    st = _plan_state(concept_checks=1)
    st.update(_graded(verdict))
    st["steps"]["qh-1"].update(step)
    return st


def test_a_feedback_turn_that_moves_the_cursor_hands_over_to_the_next_prequestion(gate_on, on):
    on.se_flag.return_value = False
    on.store["doc"] = _segment_end()
    r, seen = _run(on, "/chat", {**_CHAT, "message": "ok"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["prequestion"]["question_hash"] == "qh-pq"
    assert not body["reply"].rstrip().endswith("?"), "served without its own question (A121)"
    doc = on.store["doc"]
    assert doc["concept"] == "node-2" and doc["prequestion"]["node-2"]["status"] == "posed"
    assert doc["open_question"] is False
    assert PREQUESTION_LINE not in seen["msg"]
    _no_evidence(on)


def test_a_feedback_turn_below_the_cap_poses_nothing(gate_on, on):
    on.se_flag.return_value = False
    st = _plan_state()
    st.update(_graded("correct"))
    on.store["doc"] = st
    r, _ = _run(on, "/chat", {**_CHAT, "message": "ok"})
    assert "prequestion" not in r.json() and "prequestion" not in on.store["doc"]
    assert r.json()["reply"].rstrip().endswith("?")


# ── A139: the junctures ─────────────────────────────────────────────────────


def _h4() -> dict:
    st = _plan_state()
    st.update(_state(rung=4))
    return st


def test_the_worked_example_asks_why_its_steps_follow(gate_on, on):
    on.pq_flag.return_value = False
    on.store["doc"] = _h4()
    r, seen = _run(on, "/action", {**_CHAT, "action_type": "hint"})
    body = r.json()
    assert body["reply"].endswith("\n\n" + se.WORKED_EXAMPLE_PROMPT)
    assert "Next?" not in body["reply"], "the prompt replaces the model's question: one question"
    assert body["self_explain"]["juncture"] == "worked_example"
    assert body["self_explain"]["prompt"] == se.WORKED_EXAMPLE_PROMPT
    doc = on.store["doc"]
    assert doc["self_explain"]["open"]["id"] == body["self_explain"]["prompt_id"]
    assert doc["self_explain"]["prompted"] == ["node-1"]
    assert doc["open_question"] is False, "answered on its card, never in chat"
    on.se_record.assert_called_once()
    assert _events(on, "learn.self_explanation") == [{"session_id": "s1", "node_id": "node-1",
                                                      "juncture": "worked_example", "status": "shown"}]
    assert SELF_EXPLAIN_ACK_LINE not in seen["msg"]


def test_the_prompt_changes_no_request(gate_on, on):
    """The prompt is code's question in the SERVED render: the model's request
    is the one the flag-off loop sends (the flag-off digests pin that)."""
    on.pq_flag.return_value = False
    on.store["doc"] = _h4()
    _, with_prompt = _run(on, "/action", {**_CHAT, "action_type": "hint"})
    on.se_flag.return_value = False
    on.store["doc"] = _h4()
    _, without = _run(on, "/action", {**_CHAT, "action_type": "hint"})
    strip = lambda m: m.split("<<student_text")[0]  # noqa: E731 (the nonce differs per call)
    assert strip(with_prompt["msg"]) == strip(without["msg"])


def test_at_most_once_per_concept_per_session(gate_on, on):
    on.pq_flag.return_value = False
    st = _h4()
    st["self_explain"] = {"open": None, "prompted": ["node-1"]}
    on.store["doc"] = st
    r, _ = _run(on, "/action", {**_CHAT, "action_type": "hint"})
    assert "self_explain" not in r.json() and r.json()["reply"].endswith("Next?")


def test_a_first_unhelped_correct_answer_asks_why_it_follows(gate_on, on):
    on.pq_flag.return_value = False
    st = _plan_state()
    st.update(_graded("correct"))
    st["steps"]["qh-1"].update(max_rung=0, assisted=False)
    on.store["doc"] = st
    r, _ = _run(on, "/chat", {**_CHAT, "message": "ok"})
    assert r.json()["self_explain"]["juncture"] == "first_correct"
    assert r.json()["reply"].endswith(se.FIRST_CORRECT_PROMPT)


def test_a_helped_correct_answer_is_no_juncture(gate_on, on):
    on.pq_flag.return_value = False
    st = _plan_state()
    st.update(_graded("correct"))  # max_rung 1, assisted
    on.store["doc"] = st
    r, _ = _run(on, "/chat", {**_CHAT, "message": "ok"})
    assert "self_explain" not in r.json()


def test_a_released_solution_asks_why_the_answer_follows(gate_on, on):
    on.pq_flag.return_value = False
    st = _plan_state()
    st.update(_graded("not_yet"))
    on.store["doc"] = st
    r, _ = _run(on, "/chat", {**_CHAT, "message": "ok"})
    body = r.json()
    assert body["self_explain"]["juncture"] == "released_solution"
    assert body["reply"].startswith("The answer: ") and body["reply"].endswith(se.RELEASED_ANSWER_PROMPT)


def test_a_template_feedback_turn_at_the_hard_level_closes_on_the_prompt(gate_on, on):
    on.pq_flag.return_value = False
    on.ai_budget.check.return_value = HARD
    st = _plan_state()
    st.update(_graded("not_yet"))
    on.store["doc"] = st
    r, seen = _run(on, "/chat", {**_CHAT, "message": "ok"})
    assert "msg" not in seen
    assert r.json()["reply"].endswith("\n\n" + se.RELEASED_ANSWER_PROMPT)


def test_a_confrontation_keeps_its_question(gate_on, on):
    """PKG-10: a recorded misconception's contradiction needs the turn's
    question; the prompt waits for the concept's next juncture."""
    on.pq_flag.return_value = False
    st = _plan_state()
    st.update(_graded("not_yet"))
    st["confront"] = {"node_id": "node-1", "wrong_key": "no_base", "check_item_id": "item-1"}
    on.item.side_effect = None
    on.item.return_value = ITEM
    on.store["doc"] = st
    with patch("routes.learn_loop.CONFRONT_TIERS", frozenset({"standard", "lite", "deep"})):
        r, seen = _run(on, "/chat", {**_CHAT, "message": "ok"})
    assert "confront it" in seen["msg"]
    assert "self_explain" not in r.json() and "prompted" not in (on.store["doc"].get("self_explain") or {})


def test_no_prompt_in_a_quiz_ask_session(gate_on, on):
    on.pq_flag.return_value = False
    st = _h4()
    st["origin"] = "quiz_ask"
    on.store["doc"] = st
    r, _ = _run(on, "/action", {**_CHAT, "action_type": "hint"})
    assert "self_explain" not in r.json()


def test_the_prompt_comes_before_the_next_segments_prequestion(gate_on, on):
    """A first unhelped correct answer on the segment's last check: the
    prompt (about the concept just finished) is the turn's question; the next
    segment's prequestion waits for the prompt to close."""
    on.store["doc"] = _segment_end(max_rung=0, assisted=False)
    r, _ = _run(on, "/chat", {**_CHAT, "message": "ok"})
    body = r.json()
    assert body["self_explain"]["juncture"] == "first_correct" and "prequestion" not in body
    assert on.store["doc"]["concept"] == "node-2" and "node-2" not in (on.store["doc"].get("prequestion") or {})
    prompt_id = body["self_explain"]["prompt_id"]
    r = client.post("/api/learn/loop/self-explain", json={**_CHAT, "prompt_id": prompt_id,
                                                         "reply": "Because the base case returns 1."})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "replied" and r.json()["prequestion"]["question_hash"] == "qh-pq"
    assert on.store["doc"]["prequestion"]["node-2"]["status"] == "posed"


# ── A139: the reply, the skip and the acknowledgement ───────────────────────


def _open_prompt(**over) -> dict:
    st = _plan_state()
    st.update(_graded("correct", feedback_given=True))
    st["current"] = None
    st["self_explain"] = {"open": {"id": "p1", "node_id": "node-1", "juncture": "first_correct",
                                   "prompt_key": "first_correct", "question_hash": "qh-1", "rung": 0,
                                   "prompted_at": NOW - 10}, "prompted": ["node-1"]}
    st.update(over)
    return st


def test_a_reply_is_stored_saved_and_acknowledged_by_the_next_model_turn_only(gate_on, on):
    on.pq_flag.return_value = False
    on.store["doc"] = _open_prompt()
    r = client.post("/api/learn/loop/self-explain", json={**_CHAT, "prompt_id": "p1",
                                                         "reply": " Because n == 0 returns 1. "})
    assert r.json() == {"recorded": True, "status": "replied"}
    kw = on.se_close.call_args.kwargs
    assert kw["reply"] == "Because n == 0 returns 1." and kw["user_id"] == "u1"
    assert on.se_close.call_args.args[0]["id"] == "p1"
    assert ("user", "Because n == 0 returns 1.") in _saved(on)
    doc = on.store["doc"]
    assert doc["self_explain"]["open"] is None and doc["self_explain"]["ack"] == "p1"
    assert _events(on, "learn.self_explanation") == [{"session_id": "s1", "node_id": "node-1",
                                                      "juncture": "first_correct", "status": "replied",
                                                      "reply_chars": 25}]
    assert "returns 1" not in json.dumps(on.events.log_event.call_args_list, default=str)
    _no_evidence(on)
    _, seen = _run(on, "/chat", {**_CHAT, "message": "Let's continue."})
    assert SELF_EXPLAIN_ACK_LINE in seen["msg"]
    assert on.store["doc"]["self_explain"]["ack"] is None
    _, seen = _run(on, "/chat", {**_CHAT, "message": "And then?"})
    assert SELF_EXPLAIN_ACK_LINE not in seen["msg"], "acknowledged once"


def test_a_skip_stores_no_reply_and_asks_for_no_acknowledgement(gate_on, on):
    on.pq_flag.return_value = False
    on.store["doc"] = _open_prompt()
    r = client.post("/api/learn/loop/self-explain", json={**_CHAT, "prompt_id": "p1", "skip": True,
                                                         "reply": "ignored"})
    assert r.json() == {"recorded": True, "status": "skipped"}
    assert on.se_close.call_args.kwargs["reply"] is None
    assert not [s for s in _saved(on) if s[0] == "user"]
    assert on.store["doc"]["self_explain"].get("ack") is None


@pytest.mark.parametrize("prompt_id", ["p2", "p1"])
def test_no_open_prompt_is_a_409(gate_on, on, prompt_id):
    on.store["doc"] = _open_prompt() if prompt_id == "p2" else _plan_state()
    r = client.post("/api/learn/loop/self-explain", json={**_CHAT, "prompt_id": prompt_id, "reply": "x"})
    assert r.status_code == 409 and r.json()["detail"] == "no open self-explanation prompt"
    on.se_close.assert_not_called()


def test_a_reply_that_lost_the_row_writes_nothing_else(gate_on, on):
    # review fix: the row closes only while 'open' — of two concurrent replies
    # the first stands; the other is a 409 with no transcript row and no event
    on.pq_flag.return_value = False
    on.store["doc"] = _open_prompt()
    on.se_close.return_value = "lost"
    r = client.post("/api/learn/loop/self-explain", json={**_CHAT, "prompt_id": "p1", "reply": "late"})
    assert r.status_code == 409
    assert not _saved(on) and not _events(on, "learn.self_explanation")
    assert se.open_prompt(on.store["doc"]) is not None  # the loop state is untouched


def test_a_committed_reply_stands_when_a_turn_closed_the_prompt_meanwhile(gate_on, on):
    on.pq_flag.return_value = False
    on.store["doc"] = _open_prompt()
    pre = json.loads(json.dumps(on.store["doc"]))
    se.close_open(on.store["doc"])  # a turn closed it between the read and the write
    with patch("routes.learn_loop._load_loop_state", return_value=pre):
        r = client.post("/api/learn/loop/self-explain", json={**_CHAT, "prompt_id": "p1", "reply": "because"})
    assert r.status_code == 200 and r.json()["status"] == "replied", r.text
    assert ("user", "because") in _saved(on)
    assert [e["status"] for e in _events(on, "learn.self_explanation")] == ["replied"]
    assert not se.ack_due(on.store["doc"])  # nothing to acknowledge: the prompt was gone


def test_a_reply_committed_twice_is_written_to_the_transcript_once(gate_on, on):
    # second review, item 6: a slow request that won the close and its client
    # retry (SAME) both reached the loop-state write; only the first records it
    on.pq_flag.return_value = False
    on.store["doc"] = _open_prompt()
    pre = json.loads(json.dumps(on.store["doc"]))
    body = {**_CHAT, "prompt_id": "p1", "reply": "because"}
    with patch("routes.learn_loop._load_loop_state", return_value=pre):  # both read the open prompt
        on.se_close.return_value = "same"  # the retry's write lands first and closes the prompt
        assert client.post("/api/learn/loop/self-explain", json=body).status_code == 200
        on.se_close.return_value = "won"  # then the slow winner's: the prompt is already closed
        assert client.post("/api/learn/loop/self-explain", json=body).status_code == 200
    assert [s for s in _saved(on) if s[0] == "user"] == [("user", "because")]
    assert [e["status"] for e in _events(on, "learn.self_explanation")] == ["replied"]


def test_the_reply_route_is_off_with_its_flag(gate_on, on):
    on.se_flag.return_value = False
    on.store["doc"] = _open_prompt()
    r = client.post("/api/learn/loop/self-explain", json={**_CHAT, "prompt_id": "p1", "reply": "x"})
    assert r.status_code == 409


def test_the_next_served_turn_closes_an_unanswered_prompt(gate_on, on):
    on.pq_flag.return_value = False
    on.store["doc"] = _open_prompt()
    _run(on, "/chat", {**_CHAT, "message": "Let's continue."})
    doc = on.store["doc"]
    assert doc["self_explain"]["open"] is None and doc["self_explain"]["prompted"] == ["node-1"]
    on.se_close.assert_not_called()  # its row stays 'open': never replied


def test_status_restores_an_open_prompt(gate_on, on):
    on.store["doc"] = _open_prompt()
    r = client.get("/api/learn/loop/status?user_id=u1&session_id=s1")
    assert r.json()["self_explain"] == {"prompt_id": "p1", "juncture": "first_correct",
                                        "prompt": se.FIRST_CORRECT_PROMPT}

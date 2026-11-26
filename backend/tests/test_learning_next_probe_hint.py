"""W2.4 / W2.4b low-trust next-probe hint: selection only, never mastery."""

from __future__ import annotations

import json
import pathlib
from unittest.mock import patch

import pytest

from learning import check_reason, next_probe_hint
from learning.checks import is_servable
from services.feature_flags import REGISTRY
from services.loop import next_probe_hint as gated
from tests.split_patches import patch_loop
from tests.test_learn_loop_routes import NOW, _iso, _plan_state, _step
from tests.test_learn_loop_routes import seams as seams  # the loop routes' fixture

BACKEND = pathlib.Path(__file__).resolve().parents[1]

BANNED = (
    "apply_graph_update",
    "flush_pending",
    "grade_answer",
    "p_known",
    "pending_evidence",
    "CheckAnswer",
    "graph_service",
    "node_mastery",
    "anthropic",
    "Agent(",
)


def test_module_never_touches_mastery_or_llm():
    """Hard invariant: the pure path cannot mutate mastery or call a model."""
    src = (BACKEND / "learning" / "next_probe_hint.py").read_text()
    for banned in BANNED:
        assert banned not in src, f"next_probe_hint.py must not mention {banned}"
    gate = (BACKEND / "services" / "loop" / "next_probe_hint.py").read_text()
    for banned in BANNED:
        assert banned not in gate, f"services/loop/next_probe_hint.py must not mention {banned}"


def test_prefer_none_on_empty_or_ciphertext():
    cands = [("qh-a", "recursion base case induction"), ("qh-b", "hash table collision")]
    assert next_probe_hint.prefer(None, cands) is None
    assert next_probe_hint.prefer("   ", cands) is None
    assert next_probe_hint.prefer("enc2:0:deadbeef", cands) is None
    assert next_probe_hint.prefer("I thought about recursion base case", []) is None


def test_prefer_picks_highest_overlap_hash():
    cands = [
        ("qh-zz", "linked list pointer traversal"),
        ("qh-aa", "recursion base case and inductive step"),
        ("qh-bb", "sorting comparator stability"),
    ]
    text = "I mixed up the recursion base case with the inductive step"
    assert next_probe_hint.prefer(text, cands) == "qh-aa"


def test_prefer_tie_breaks_on_question_hash():
    cands = [
        ("qh-b", "gradient descent learning rate"),
        ("qh-a", "gradient descent learning rate"),
    ]
    text = "confused about gradient descent and the learning rate"
    assert next_probe_hint.prefer(text, cands) == "qh-a"


def test_prefer_below_overlap_floor_is_none():
    cands = [("qh-1", "completely unrelated topic zeta")]
    assert next_probe_hint.prefer("because the answer is forty two", cands) is None


@pytest.mark.parametrize("on", [False, True])
def test_gated_flag_off_is_noop(on):
    cands = [("qh-aa", "recursion base case inductive step")]
    text = "I mixed up the recursion base case with the inductive step"
    with patch("services.loop.next_probe_hint.flag_on", return_value=on) as flag:
        got = gated.preferred_next_question_hash("user_1", text, cands)
    flag.assert_called_once_with(gated.NEXT_PROBE_HINT_FLAG, "user_1")
    if on:
        assert got == "qh-aa"
    else:
        assert got is None


def test_gated_no_user_is_off_without_flag_read():
    with patch("services.loop.next_probe_hint.flag_on") as flag:
        assert gated.preferred_next_question_hash(None, "recursion base case", []) is None
    flag.assert_not_called()


def test_gated_decrypts_reasoning_when_flag_on():
    """W2.4b: flag on opens step reasoning_encrypted under the session bind."""
    plain = "I mixed up the recursion base case with the inductive step"
    sealed = check_reason.seal("sess-hint", plain)
    assert sealed and plain not in sealed
    state = {"steps": {"qh-prior": {check_reason.KEY: sealed, "graded_at": 1.0}}}
    cands = [
        ("qh-zz", "linked list pointer traversal"),
        ("qh-aa", "recursion base case and inductive step"),
    ]
    with patch("services.loop.next_probe_hint.flag_on", return_value=True):
        assert (
            gated.preferred_next_question_hash(
                "user_1", None, cands, session_id="sess-hint", state=state
            )
            == "qh-aa"
        )
    with patch("services.loop.next_probe_hint.flag_on", return_value=False) as flag:
        assert (
            gated.preferred_next_question_hash(
                "user_1", None, cands, session_id="sess-hint", state=state
            )
            is None
        )
    flag.assert_called_once_with(gated.NEXT_PROBE_HINT_FLAG, "user_1")
    # Wrong session bind → open fails soft → prefer(None) → None even when on.
    with patch("services.loop.next_probe_hint.flag_on", return_value=True):
        assert (
            gated.preferred_next_question_hash(
                "user_1", None, cands, session_id="other-sess", state=state
            )
            is None
        )


def test_gated_flag_off_skips_decrypt():
    """Flag off must not open ciphertext (no scoring, no decrypt side path)."""
    sealed = check_reason.seal("s1", "recursion base case inductive step")
    state = {"steps": {"qh-1": {check_reason.KEY: sealed, "graded_at": 1.0}}}
    cands = [("qh-aa", "recursion base case inductive step")]
    with (
        patch("services.loop.next_probe_hint.flag_on", return_value=False),
        patch("services.loop.next_probe_hint.check_reason.latest_plaintext") as latest,
    ):
        assert gated.preferred_next_question_hash(
            "user_1", None, cands, session_id="s1", state=state
        ) is None
    latest.assert_not_called()


def test_flag_description_promises_only_the_text_that_is_read():
    """Only the graded step's reason-before-submit text reaches the hint; a
    self-explanation reply never does (w2-next-probe-hint.md, Non-goals)."""
    flag = REGISTRY["next_probe_hint"]
    assert flag.variants == ("off", "on")
    assert "reason-before-submit" in flag.description
    assert "self-explain" not in flag.description


# ── W2.4: the activation itself, with the flag on ───────────────────────────

REASON = "I mixed up the recursion base case with the inductive step"


def _bank_item(qh: str, prompt: str, **over):
    return _iso(qh).model_copy(update={"prompt": prompt, "created_at": "2026-11-05T00:00:00+00:00", **over})


#: what select_item poses: the oldest of equals, and it shares no word with REASON
PLAIN = _bank_item("qh-plain", "Name one stable sorting algorithm.", created_at="2026-09-01T00:00:00+00:00")
#: overlaps REASON on every topic word
BEST = _bank_item("qh-best", "State the recursion base case and the inductive step.")
#: overlaps REASON on two
NEXT_BEST = _bank_item("qh-next", "What does the base case do?")

#: why a check is not servable (learning.checks.is_servable: A34, K16, A123/A124)
UNSERVABLE = {
    "no_final_answer": {"final_answer": None},
    "blank_final_answer": {"final_answer": "  "},
    "no_rubric": {"rubric": []},
    "held": {"lint_flags": ["reports_threshold"]},
}


def _reasoned_state(**steps) -> dict:
    """A plan on node-1 whose one graded step carries REASON, sealed."""
    prior = _step(check_item_id="item-prior", graded_at=NOW - 50, feedback_given=True)
    prior[check_reason.KEY] = check_reason.seal("s1", REASON)
    return _plan_state(steps={"qh-prior": prior, **steps})


def _activate(state: dict, *, on: bool = True) -> str | None:
    from services.loop.practice import _activate_next_item

    with patch("services.loop.next_probe_hint.flag_on", return_value=on):
        return _activate_next_item("u1", "c1", state, now=NOW, session_id="s1")


def test_activation_poses_the_overlapping_servable_item(seams):
    seams.list_items.return_value = [PLAIN, NEXT_BEST, BEST]
    assert _activate(_reasoned_state()) == "qh-best"


def test_activation_flag_off_is_the_ordinary_pick_without_a_decrypt(seams):
    seams.list_items.return_value = [PLAIN, NEXT_BEST, BEST]
    off, no_prose = _reasoned_state(), _reasoned_state()
    del no_prose["steps"]["qh-prior"][check_reason.KEY]
    with patch("services.loop.next_probe_hint.check_reason.open") as opened:
        assert _activate(off, on=False) == "qh-plain"
    opened.assert_not_called()
    # the same document a session with no reasoning at all gets with the flag on
    assert _activate(no_prose) == "qh-plain"
    assert off["steps"]["qh-plain"] == no_prose["steps"]["qh-plain"]


@pytest.mark.parametrize("why", sorted(UNSERVABLE))
def test_activation_hint_never_poses_an_unservable_item(seams, why):
    refused = BEST.model_copy(update=UNSERVABLE[why])
    assert not is_servable(refused)
    seams.list_items.return_value = [PLAIN, refused]
    assert _activate(_reasoned_state()) == "qh-plain"
    # nor does it shadow the best item that IS servable: it is no candidate
    seams.list_items.return_value = [PLAIN, NEXT_BEST, refused]
    assert _activate(_reasoned_state()) == "qh-next"


@pytest.mark.parametrize("why", sorted(UNSERVABLE))
def test_activation_re_checks_the_hinted_hash_itself(seams, why):
    """Whatever the hint answers, the pick is servable and not excluded."""
    refused = BEST.model_copy(update=UNSERVABLE[why])
    seams.list_items.return_value = [PLAIN, refused]
    with patch_loop("preferred_next_question_hash", return_value="qh-best"):
        assert _activate(_reasoned_state()) == "qh-plain"


def test_activation_with_only_an_unservable_overlap_poses_nothing_on_the_concept(seams):
    """Flag on, the one overlapping row is unservable: the concept is as empty
    as it is with the flag off."""
    for on in (False, True):
        seams.list_items.return_value = [BEST.model_copy(update={"rubric": []})]
        state = _reasoned_state()
        assert _activate(state, on=on) is None
        assert not state.get("current") and state["plan"]["done"] is True


@pytest.mark.parametrize("site", ["seen", "revealed", "reported", "session", "reserve"])
def test_activation_hint_never_widens_past_the_excluded_set(seams, site):
    best, state = BEST, _reasoned_state()
    if site == "seen":
        seams.seen_hashes.return_value = {"qh-best"}
    elif site == "revealed":
        seams.revealed_hashes.return_value = {"qh-best"}
    elif site == "reported":
        seams.reported_hashes.return_value = {"qh-best"}
    elif site == "session":
        state = _reasoned_state(**{"qh-best": _step(graded_at=NOW - 90, feedback_given=True)})
    elif site == "reserve":
        best = _bank_item("qh-reserve", BEST.prompt)
    seams.list_items.return_value = [PLAIN, best]
    assert _activate(state) == "qh-plain"


def test_activation_ignores_reasoning_older_than_the_latest_grade(seams):
    """The doc's rule on the real path: a newer grade with no reasoning means
    no hint, so the ordinary item is posed."""
    seams.list_items.return_value = [PLAIN, BEST]
    newer = _step(check_item_id="item-newer", graded_at=NOW - 10, feedback_given=True)
    assert _activate(_reasoned_state(**{"qh-newer": newer})) == "qh-plain"


def test_activation_hint_writes_no_mastery_and_no_prose(seams):
    """The hinted step is the ordinary step (same keys, same values but the
    item), the prior step is untouched and nothing reaches the graph."""
    seams.list_items.return_value = [PLAIN, BEST]
    hinted, plain = _reasoned_state(), _reasoned_state()
    plain["steps"]["qh-prior"] = dict(hinted["steps"]["qh-prior"])
    before = json.loads(json.dumps(hinted["steps"]["qh-prior"]))
    with patch("services.graph_service.apply_graph_update") as graph:
        assert _activate(hinted) == "qh-best"
    graph.assert_not_called()
    assert _activate(plain, on=False) == "qh-plain"
    hinted_step = hinted["steps"].pop("qh-best")
    plain_step = plain["steps"].pop("qh-plain")
    assert hinted_step == {**plain_step, "check_item_id": BEST.id}
    assert hinted["steps"] == {"qh-prior": before}
    hinted_current = hinted.pop("current")
    plain_current = plain.pop("current")
    assert hinted_current == "qh-best" and plain_current == "qh-plain"
    assert hinted == plain
    assert REASON not in json.dumps(hinted)

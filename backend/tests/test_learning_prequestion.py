"""Spec §13 A138: the segment prequestion's pure rules (learning/prequestion.py)
— when a segment starts, when it opens without a prequestion and why, which
item is posed, what is shown and stored — and its A76 release rule
(learning/misconceptions.py::recheck_after_release)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from learning import prequestion as pq
from learning.checks import CheckItem, Option, RubricItem, WrongReason
from learning.params import (
    BAND_DEVELOP_MAX,
    LOOP_CHECKS_PER_CONCEPT,
    PREQUESTION_DIFFICULTIES,
    PREQUESTION_FORMATS,
    PREQUESTION_MIN_CHECKS_LEFT,
    PREQUESTION_SKIP_REASONS,
    RECHECK_RELEASE_WINDOW_HOURS,
)


def _item(qh: str, fmt: str = "free", difficulty: int = 1, **over) -> CheckItem:
    options = None
    correct = None
    if fmt == "mc_reason":
        options = [
            Option(letter="A", text="a list per slot", wrong_key="probe_only"),
            Option(letter="B", text="the next free slot"),
            Option(letter="C", text="a second hash", wrong_key="double"),
            Option(letter="D", text="a resize", wrong_key="resize"),
        ]
        correct = "B"
    fields = dict(
        id=f"id-{qh}",
        course_id="c1",
        concept_key="hashing",
        format=fmt,
        difficulty=difficulty,
        prompt=f"Where does linear probing put a colliding key? ({qh})",
        reference_answer="In the next free slot. Final answer: the next free slot",
        final_answer="the next free slot",
        rubric=[RubricItem(id="r1", text="names the slot"), RubricItem(id="r2", text="says next")],
        common_wrong=[WrongReason(key="probe_only", text="a list")],
        options=options,
        correct_option=correct,
        source_chunk_ids=["ch-1"],
        question_hash=qh,
        created_at=f"2026-11-0{1 + int(qh[-1]) % 8}T00:00:00+00:00" if qh[-1].isdigit() else None,
    )
    fields.update(over)
    return CheckItem(**fields)


def _state(**over) -> dict:
    st = {
        "phase": "teach",
        "plan": {"approved": ["n1", "n2"], "cursor": 0, "proposed_kinds": {"n1": "new", "n2": "new"}},
        "concept": "n1",
        "teach_turns": 0,
        "concept_checks": 0,
        "current": None,
        "steps": {},
    }
    st.update(over)
    return st


# ── params ────────────────────────────────────────────────────────────────


def test_the_params_are_the_ones_the_spec_row_names():
    assert PREQUESTION_FORMATS == ("mc_reason", "free")
    assert PREQUESTION_DIFFICULTIES == (1, 2)
    assert PREQUESTION_MIN_CHECKS_LEFT == LOOP_CHECKS_PER_CONCEPT
    assert PREQUESTION_SKIP_REASONS == ("no_item", "pool_for_checks", "review", "proficient", "exam_mode")


# ── segment_open ──────────────────────────────────────────────────────────


def test_a_segment_opens_on_the_plan_concept_before_any_teaching():
    assert pq.segment_open(_state()) == "n1"


@pytest.mark.parametrize(
    "over",
    [
        {"teach_turns": 1},  # teaching began
        {"concept_checks": 1},  # a check was graded
        {"current": "qh-x"},  # a check is open
        {"concept": None},
        {"plan": {"approved": ["n1"], "cursor": 1, "done": True}},
        {"origin": "quiz_ask"},  # A99: the quiz's sheet shows no card
        {"steps": {"qh-old": {"node_id": "n1", "first_shown_at": 1.0}}},  # a repair return
        {"prequestion": {"n1": {"status": "skipped", "reason": "review"}}},  # one per segment
    ],
)
def test_no_segment_start_once_the_concept_began_or_had_its_prequestion(over):
    assert pq.segment_open(_state(**over)) is None


# ── skip_reason ───────────────────────────────────────────────────────────


def test_a_due_review_opens_without_a_prequestion():
    st = _state(plan={"approved": ["n1"], "cursor": 0, "proposed_kinds": {"n1": "review"}})
    assert pq.skip_reason(st, "n1", p_known=0.2) == "review"


def test_a_proficient_concept_opens_without_one():
    assert pq.skip_reason(_state(), "n1", p_known=BAND_DEVELOP_MAX) == "proficient"
    assert pq.skip_reason(_state(), "n1", p_known=BAND_DEVELOP_MAX - 1e-9) is None


def test_exam_mode_forbids_the_released_answer():
    steps = {"qh-old": {"node_id": "n9", "exam_mode": True, "first_shown_at": 1.0}}
    assert pq.skip_reason(_state(steps=steps), "n1", p_known=0.3) == "exam_mode"
    # PKG-06's rule: any stored exam_mode other than False is exam mode
    steps = {"qh-old": {"node_id": "n9", "exam_mode": "yes", "first_shown_at": 1.0}}
    assert pq.skip_reason(_state(steps=steps), "n1", p_known=0.3) == "exam_mode"


def test_a_probe_answer_on_the_concept_does_not_count_as_its_prequestion():
    """The probe is placement (A112/A126): its history on the concept never
    skips the segment's prequestion."""
    st = _state(probe={"history": [{"node_id": "n1", "question_hash": "p1", "correct": False}]})
    assert pq.segment_open(st) == "n1"
    assert pq.skip_reason(st, "n1", p_known=0.3) is None


# ── choose ────────────────────────────────────────────────────────────────


#: A concept's post-test reserves come from the free difficulty-2 cell (A23,
#: A126): two items there absorb both reserves, so the candidates under test are
#: never a reserve; three teachback items fill the pool a check could draw.
_FILLERS = (
    _item("r1", "free", 2),
    _item("r2", "free", 2),
    _item("t7", "teachback", 3),
    _item("t8", "teachback", 3),
    _item("t9", "teachback", 3),
)


def _bank(*items):
    return [*items, *_FILLERS]


def test_multiple_choice_first_then_the_lower_difficulty():
    bank = _bank(_item("f1", "free", 1), _item("m2", "mc_reason", 2), _item("m1", "mc_reason", 1),
                 _item("t1", "teachback", 1), _item("x5", "free", 3), _item("x6", "free", 2))
    item, reason = pq.choose(bank, exclude=set())
    assert reason is None and item.question_hash == "m1"


def test_never_teachback_and_never_difficulty_three():
    bank = _bank(_item("t1", "teachback", 1), _item("f3", "free", 3), _item("g3", "free", 3), _item("h3", "free", 3))
    assert pq.choose(bank, exclude=set()) == (None, "no_item")


def test_never_a_post_test_reserve():
    """A23/A126: the reserves are the outcome items — never shown before the post-test."""
    from learning.checks import posttest_reserves

    bank = [*[_item(f"f{i}", "free", 2) for i in range(1, 5)], _item("m1", "mc_reason", 1)]
    reserves = posttest_reserves(bank)
    item, _ = pq.choose(bank, exclude=set())
    assert item is not None and item.question_hash not in reserves
    only = [i for i in bank if i.question_hash in reserves]
    assert pq.choose(only, exclude=set())[0] is None


def test_excluded_items_are_never_posed():
    bank = _bank(_item("m1", "mc_reason", 1), _item("f1", "free", 1), _item("f2", "free", 1), _item("f3", "free", 1))
    item, _ = pq.choose(bank, exclude={"m1"})
    assert item.question_hash != "m1"


def test_an_unservable_item_is_never_posed():
    bank = _bank(_item("m1", "mc_reason", 1, final_answer=None), _item("f1", "free", 1),
                 _item("f2", "free", 1), _item("f3", "free", 1))
    item, _ = pq.choose(bank, exclude=set())
    assert item.question_hash != "m1"


def test_the_pool_keeps_the_segments_checks():
    """Graded checks are the only evidence: the prequestion is drawn only when
    PREQUESTION_MIN_CHECKS_LEFT fresh, non-reserve items stay beside it."""
    from learning.checks import posttest_reserves

    bank = [_item("m1", "mc_reason", 1), _item("r1", "free", 2), _item("r2", "free", 2)]
    fresh = len(bank) - len(posttest_reserves(bank))
    assert fresh - 1 < PREQUESTION_MIN_CHECKS_LEFT
    assert pq.choose(bank, exclude=set()) == (None, "pool_for_checks")
    while len(bank) - len(posttest_reserves(bank)) - 1 < PREQUESTION_MIN_CHECKS_LEFT:
        bank.append(_item(f"t{len(bank)}", "teachback", 3))
    assert pq.choose(bank, exclude=set()) == (bank[0], None)
    # an excluded item is no check's either
    assert pq.choose(bank, exclude={bank[-1].question_hash}) == (None, "pool_for_checks")


def test_quality_breaks_a_tie_then_age():
    """A129: a confirmed key, then clean lint, among items the picker's own rule leaves equal."""
    bank = _bank(
        _item("m1", "mc_reason", 1, lint_flags=["correct_longest"]),
        _item("m2", "mc_reason", 1, canonical_verified=True),
        _item("f1", "free", 1),
        _item("f2", "free", 1),
    )
    assert pq.choose(bank, exclude=set())[0].question_hash == "m2"
    tied = _bank(_item("m3", "mc_reason", 1), _item("m2", "mc_reason", 1))
    assert pq.choose(tied, exclude=set())[0].question_hash == "m2"  # the older (created_at)


# ── what is shown and stored ──────────────────────────────────────────────


def test_the_pose_shows_the_question_and_options_never_the_key():
    item = _item("m1", "mc_reason", 1)
    payload = pq.pose_payload(item)
    assert payload["prompt"] == item.prompt and [o["letter"] for o in payload["options"]] == list("ABCD")
    dumped = str(payload)
    assert "correct" not in dumped and "wrong_key" not in dumped and item.final_answer not in payload["prompt"]
    assert payload["text"] == pq.pose_text(item) == f"{pq.POSE_LEAD}\n\n{item.prompt}"
    assert "answered" not in payload and pq.pose_payload(item, answered=True)["answered"] is True


def test_the_saved_pose_row_carries_no_option_text_so_no_key_before_the_release():
    # The row is written before the answer is released; the options include the
    # key (B here), so like a posed check's row it is the stem only.
    item = _item("m1", "mc_reason", 1)
    assert "the next free slot" not in pq.pose_text(item)
    assert all(line not in pq.pose_text(item) for line in pq.option_lines(item))
    assert pq.option_lines(item)[1] == "B. the next free slot"  # the model's block still lists them


def test_the_answer_lead_names_the_correct_option_or_the_reference():
    assert pq.answer_lead(_item("m1", "mc_reason", 1)) == "The answer: B. the next free slot"
    free = _item("f1", "free", 1)
    assert pq.answer_lead(free) == "The answer: " + free.reference_answer


def test_the_guess_row():
    assert pq.render_guess(no_idea=True, answer="x") == "No idea."
    assert pq.render_guess(no_idea=False, option="B") == "My guess: B"
    assert pq.render_guess(no_idea=False, option="B", reason=" it probes ") == "My guess: B — it probes"
    assert pq.render_guess(no_idea=False, answer=" the next slot ") == "My guess: the next slot"


def test_the_record_holds_no_text():
    """A38: loop_state holds ids, ints, enums and times only."""
    rec = pq.pose_record(_item("m1", "mc_reason", 1), "n1", 100.0)
    assert rec == {"status": "posed", "question_hash": "m1", "check_item_id": "id-m1",
                   "format": "mc_reason", "difficulty": 1, "posed_at": 100.0}
    with pytest.raises(ValueError):
        pq.skip_record("because")


def test_session_hashes_cover_every_posed_item_whatever_became_of_it():
    st = _state(prequestion={"n1": {"status": "superseded", "question_hash": "a"},
                             "n2": {"status": "resolved", "question_hash": "b"},
                             "n3": {"status": "skipped", "reason": "review"}})
    assert pq.session_hashes(st) == {"a", "b"}


# ── A76: an answered prequestion is a release ─────────────────────────────

_NOW = datetime(2026, 11, 8, 12, tzinfo=timezone.utc)


def _graded_item(fmt="free", difficulty=2):
    from unittest.mock import MagicMock

    return MagicMock(question_hash="q9", format=fmt, difficulty=difficulty)


def _answered(fmt="mc_reason", difficulty=1, at=None):
    at = (at or _NOW - timedelta(minutes=5)).timestamp()
    return {"prequestion": {"n1": {"status": "resolved", "question_hash": "p1", "format": fmt,
                                   "difficulty": difficulty, "answered_at": at}}}


def _recheck(state, item, releases=None, later=None):
    from learning import misconceptions

    with (
        patch.object(misconceptions, "recent_evidence", return_value=[]),
        patch("learning.prequestion_store.releases", return_value=releases or []),
        patch("learning.prequestion_store.evidence_since", return_value=later),
    ):
        return misconceptions.recheck_after_release("u1", "n1", state, now=_NOW, item=item)


def test_the_next_graded_item_after_this_sessions_prequestion_is_a_recheck():
    assert _recheck(_answered(), _graded_item("teachback", 3), later=False) is True


def test_an_answer_before_the_release_does_not_hide_it():
    # Review fix (A138 x A76): the probe graded the concept right — A120 logs an
    # unreleased attempt — and then the segment's prequestion was answered. The
    # segment's first check, of another class, is still the next item after it.
    st = _answered("mc_reason", 1)
    st["attempts"] = [{"node_id": "n1", "question_hash": "probe-q", "correct": True, "difficulty": 2,
                       "released": False}]
    assert _recheck(st, _graded_item("free", 2), later=False) is True
    assert _recheck(st, _graded_item("free", 2), later=None) is True  # the journal unread: the session decides


def test_a_step_graded_after_the_release_ends_the_next_item_rule_but_class_mates_still_owe():
    st = _answered("mc_reason", 1)
    st["steps"] = {"q1": {"node_id": "n1", "graded_at": _NOW.timestamp() - 60, "last_verdict": "correct"}}
    assert _recheck(st, _graded_item("teachback", 3), later=True) is False
    assert _recheck(st, _graded_item("teachback", 3), later=None) is False  # the step decides
    assert _recheck(st, _graded_item("mc_reason", 1), later=True) is True  # its isomorph class owes
    st["steps"]["q1"]["graded_at"] = _NOW.timestamp() - 3600  # graded BEFORE the release
    assert _recheck(st, _graded_item("teachback", 3), later=False) is True


def test_a_grade_on_another_surface_after_the_release_ends_it():
    assert _recheck(_answered(), _graded_item("teachback", 3), later=True) is False


def test_a_prequestion_outside_the_window_owes_nothing():
    old = _NOW - timedelta(hours=RECHECK_RELEASE_WINDOW_HOURS, minutes=1)
    assert _recheck(_answered(at=old), _graded_item("mc_reason", 1)) is False


def test_across_sessions_the_durable_record_decides():
    rel = [{"shape": ("free", 1), "at": _NOW - timedelta(hours=2)}]
    assert _recheck({}, _graded_item("free", 1), releases=rel, later=True) is True  # class-mate
    assert _recheck({}, _graded_item("teachback", 3), releases=rel, later=False) is True  # next item
    assert _recheck({}, _graded_item("teachback", 3), releases=rel, later=True) is False  # graded since
    assert _recheck({}, _graded_item("teachback", 3), releases=rel, later=None) is False  # failed read


def test_no_prequestion_leaves_the_rule_as_it_was():
    assert _recheck({}, _graded_item()) is False
    assert _recheck(None, _graded_item()) is False


def test_a_posed_or_superseded_prequestion_is_no_release():
    st = _answered()
    st["prequestion"]["n1"]["status"] = "superseded"
    assert _recheck(st, _graded_item("mc_reason", 1)) is False


def test_the_releases_read_is_owner_scoped_and_never_raises():
    from unittest.mock import MagicMock

    from learning import prequestion_store as store

    t = MagicMock()
    t.select.return_value = [{"format": "free", "difficulty": 1, "answered_at": "2026-11-08T10:00:00+00:00"}]
    with patch.object(store, "table", return_value=t):
        rows = store.releases("u1", "n1", since=_NOW - timedelta(hours=24))
    assert rows == [{"shape": ("free", 1), "at": datetime(2026, 11, 8, 10, tzinfo=timezone.utc)}]
    kw = t.select.call_args.kwargs
    assert kw["filters"]["user_id"] == "eq.u1" and kw["filters"]["node_id"] == "eq.n1"
    t.select.side_effect = RuntimeError("down")
    with patch.object(store, "table", return_value=t):
        assert store.releases("u1", "n1", since=_NOW) is None
        assert store.evidence_since("u1", "n1", _NOW) is None


def test_the_guess_is_stored_encrypted_and_no_idea_stores_none():
    from unittest.mock import MagicMock

    from learning import prequestion_store as store
    from services.encryption import decrypt_json

    t = MagicMock()
    with patch.object(store, "table", return_value=t):
        store.store_answer(user_id="u1", session_id="s1", course_id="c1", node_id="n1",
                           item=_item("m1", "mc_reason", 1), no_idea=False,
                           guess={"option": "A", "reason": "it lists"}, posed_at=_NOW)
        store.store_answer(user_id="u1", session_id="s1", course_id="c1", node_id="n2",
                           item=_item("f1", "free", 1), no_idea=True, guess=None, posed_at=_NOW)
    first, second = (c.args[0] for c in t.insert_ignore_duplicates.call_args_list)
    assert first["guess_json"] != '{"option":"A","reason":"it lists"}'
    assert decrypt_json(first["guess_json"]) == {"option": "A", "reason": "it lists"}
    assert first["no_idea"] is False and first["format"] == "mc_reason" and first["difficulty"] == 1
    assert second["guess_json"] is None and second["no_idea"] is True
    assert t.insert_ignore_duplicates.call_args.kwargs["on_conflict"] == "user_id,session_id,node_id"

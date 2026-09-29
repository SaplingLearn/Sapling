"""PKG-12 review surfaces: queue merge/order/budget, one grader path,
FSRS on flashcards, retention targets, successive relearning, events.
Hermetic: every table() is a mock, the grader helper is patched."""

from __future__ import annotations

import asyncio
import copy
import pathlib
import re
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest

from learning import params

NOW = datetime(2026, 9, 26, 12, 0, tzinfo=timezone.utc)
USER = "user_andres"
COURSE = "course-1"
MIG_DIR = pathlib.Path(__file__).resolve().parents[1] / "db" / "migrations"


def _tables(data: dict):
    """One MagicMock per table name so a test can assert on a specific table's
    update/insert calls (mirrors tests/test_graph_service.py::_cached_mock_table)."""
    handles: dict = {}

    def factory(name):
        if name not in handles:
            m = MagicMock(name=name)
            m.select.return_value = list(data.get(name, []))
            m.insert.return_value = []
            m.update.return_value = []
            m.upsert.return_value = []
            handles[name] = m
        return handles[name]

    return factory, handles


# ── Task 2: taxonomy, constants, migration ────────────────────────────────────


def test_review_events_are_in_the_taxonomy():
    from services import events_service

    assert {"review.served", "review.graded"} <= events_service.EVENT_TAXONOMY


def test_review_constants_exist_and_are_consistent():
    assert params.REVIEW_SECONDS_PER_FLASHCARD < params.REVIEW_SECONDS_PER_CHECK
    assert set(params.REVIEW_DIFFICULTY_BY_BAND) == {"novice", "develop", "profic"}
    assert set(params.REVIEW_DIFFICULTY_BY_BAND.values()) <= set(params.CHECK_ITEM_DIFFICULTIES)
    assert set(params.REVIEW_FORMAT_BY_BAND) == {"novice", "develop", "profic"}
    # rule 1 falls back to the other one
    assert set(params.REVIEW_FORMAT_BY_BAND.values()) == {"free", "mc_reason"}


def test_review_session_mode_migration():
    hits = sorted(MIG_DIR.glob("*_learning_sessions_mode_review.sql"))
    assert len(hits) == 1, hits
    sql = hits[0].read_text()
    assert re.fullmatch(r"\d{14}_learning_sessions_mode_review\.sql", hits[0].name)
    # sorts after every earlier series migration (the ledger applies in name order)
    assert hits[0].name > "20260929073325_learning_check_item_draft_failures_solo.sql"
    assert "DROP CONSTRAINT IF EXISTS sessions_mode_check" in sql
    assert re.search(r"CHECK \(mode IN \('socratic','expository','teachback','review'\)\)", sql)


# ── Task 3: retention target, SR stage, queue, check grading ─────────────────


def _item(kind, r, **kw):
    from learning.review import ReviewItem

    base = dict(
        kind=kind,
        id=kw.pop("id", f"{kind}-{r}"),
        node_id=kw.pop("node_id", None),
        course_id=COURSE,
        question_hash=kw.pop("question_hash", None),
        due_at=NOW,
        r=r,
        stability=params.FSRS_S0_GOOD,
        format=kw.pop("format", None),
        difficulty=kw.pop("difficulty", None),
        cost_s=(
            params.REVIEW_SECONDS_PER_CHECK
            if kind == "check"
            else params.REVIEW_SECONDS_PER_FLASHCARD
        ),
        sr_stage="acquire",
        sr_target=params.SR_INITIAL_CRITERION,
    )
    base.update(kw)
    return ReviewItem(**base)


@pytest.mark.parametrize(
    "n,exam,expected",
    [
        (0, None, "FSRS_RETENTION_DEFAULT"),
        (params.FSRS_LARGE_SET_CONCEPTS, None, "FSRS_RETENTION_DEFAULT"),
        (params.FSRS_LARGE_SET_CONCEPTS + 1, None, "FSRS_RETENTION_LARGE_SET"),
        (0, params.FSRS_EXAM_WINDOW_DAYS, "FSRS_RETENTION_EXAM"),
        (0, params.FSRS_EXAM_WINDOW_DAYS + 1, "FSRS_RETENTION_DEFAULT"),
        (0, 0, "FSRS_RETENTION_EXAM"),
        (params.FSRS_LARGE_SET_CONCEPTS + 1, 1, "FSRS_RETENTION_EXAM"),  # exam beats large set
    ],
)
def test_retention_target(n, exam, expected):
    from learning.review import retention_target

    assert retention_target(n, exam) == getattr(params, expected)


@pytest.mark.parametrize(
    "streak,stage,target",
    [
        (0, "acquire", params.SR_INITIAL_CRITERION),
        (params.SR_INITIAL_CRITERION - 1, "acquire", params.SR_INITIAL_CRITERION),
        (params.SR_INITIAL_CRITERION, "relearn", 1),
        (params.SR_INITIAL_CRITERION + params.SR_RELEARN_SESSIONS - 1, "relearn", 1),
        (params.SR_INITIAL_CRITERION + params.SR_RELEARN_SESSIONS, "done", 1),
    ],
)
def test_sr_stage_for_concept(streak, stage, target):
    from learning.review import sr_stage_for_concept

    assert sr_stage_for_concept(streak) == (stage, target)


@pytest.mark.parametrize(
    "reps,last_rating,stage",
    [
        (0, None, "acquire"),
        (params.SR_INITIAL_CRITERION, 3, "relearn"),
        (params.SR_INITIAL_CRITERION, 1, "acquire"),  # a lapse restarts acquisition
        (params.SR_INITIAL_CRITERION + params.SR_RELEARN_SESSIONS, 2, "done"),
    ],
)
def test_sr_stage_for_flashcard(reps, last_rating, stage):
    from learning.review import sr_stage_for_flashcard

    assert sr_stage_for_flashcard(reps, last_rating)[0] == stage


def test_review_session_id_is_one_per_user_course_day():
    from learning.review import review_session_id

    a = review_session_id(USER, COURSE, NOW)
    assert a == review_session_id(USER, COURSE, NOW + timedelta(hours=11))
    assert a != review_session_id(USER, COURSE, NOW + timedelta(days=1))
    assert a != review_session_id(USER, None, NOW)
    assert a != review_session_id("someone-else", COURSE, NOW)


@pytest.fixture(autouse=True)
def _no_review_history(monkeypatch):
    """A23 readers (PKG-07) and the post-test reserve (PKG-04) default to
    "nothing excluded"; the exclusion tests override them."""
    from learning import review

    monkeypatch.setattr(review, "seen_hashes", lambda user_id: set(), raising=False)
    monkeypatch.setattr(review, "revealed_hashes", lambda user_id: set(), raising=False)
    monkeypatch.setattr(review, "posttest_reserve_hash", lambda items: None, raising=False)


class _Store:
    """Stand-in for learning.loop_state_store.update_loop_state (A38 06(q)):
    applies `mutate` to one in-memory LoopState, as the CAS helper does to
    the freshly loaded one, and records the session ids it was called for."""

    def __init__(self, initial=None):
        from learning.policy import LoopState

        self.calls: list[str] = []
        self.state = LoopState(extra=copy.deepcopy(initial or {}))
        self.conflict = False

    def __call__(self, session_id, mutate):
        from learning.loop_state_store import LoadedLoopState, LoopStateConflict

        self.calls.append(session_id)
        if self.conflict:
            raise LoopStateConflict("lost every compare-and-set")
        replaced = mutate(self.state)
        if replaced is not None:
            self.state = replaced
        return LoadedLoopState(self.state, len(self.calls))


@pytest.fixture(autouse=True)
def store(monkeypatch):
    from learning import review

    s = _Store()
    monkeypatch.setattr(review, "update_loop_state", s, raising=False)
    return s


def _option(letter, text, wrong_key):
    opt = MagicMock()
    opt.letter, opt.text, opt.wrong_key = letter, text, wrong_key
    return opt


def _check_item(node_id, qh, fmt="free", difficulty=2):
    """A decrypted CheckItem stand-in (A2: keyed on course_id/concept_key; the
    student's node is resolved by the caller, never stored on the item)."""
    item = MagicMock()
    item.id = f"ci-{qh}"
    item.course_id = COURSE
    item.concept_key = f"key-{node_id}"
    item.format = fmt
    item.difficulty = difficulty
    item.question_hash = qh
    item.created_at = None
    item.prompt = f"Explain {node_id}"
    item.reference_answer = f"REF-{node_id}"
    item.final_answer = f"FA-{node_id}"  # A34: select_item serves only items that state one
    item.canonical_answer = None
    item.rubric = [{"id": "r1", "text": "x"}, {"id": "r2", "text": "y"}]
    item.common_wrong = [{"key": "w1", "text": "z"}]
    item.options, item.correct_option = None, None
    if fmt == "mc_reason":  # A22: stored options, one correct, distractors keyed
        item.options = [
            _option("A", f"OPT-A-{node_id}", None),
            _option("B", f"OPT-B-{node_id}", "w1"),
        ]
        item.correct_option = "A"
    return item


def _due_row(node_id, p_known, past, streak=0):
    return {
        "node_id": node_id,
        "p_known": p_known,
        "streak_unassisted": streak,
        "fsrs_d": 5.0,
        "fsrs_s": 1.0,
        "fsrs_last_review_at": past,
        "fsrs_due_at": past,
    }


def _card(card_id, past, **kw):
    row = {
        "id": card_id,
        "topic": "T",
        "offering_id": None,
        "fsrs_d": 5.0,
        "fsrs_s": 1.0,
        "due_at": past,
        "reps": 0,
        "lapses": 0,
        "last_rating": None,
        "last_reviewed_at": past,
    }
    row.update(kw)
    return row


def test_due_queue_merges_orders_and_drops_not_due(monkeypatch):
    from learning import review
    from services.graph_service import _normalize_concept

    past = (NOW - timedelta(days=3)).isoformat()
    future = (NOW + timedelta(days=3)).isoformat()
    factory, handles = _tables(
        {
            "flashcards": [
                _card("f-due", past),
                _card("f-null", None, fsrs_d=None, fsrs_s=None, due_at=None),
                _card("f-future", past, fsrs_s=9.0, due_at=future, reps=1, last_rating=3),
            ],
            "learner_state": [
                {
                    "node_id": "n-due",
                    "p_known": 0.9,
                    "streak_unassisted": 0,
                    "fsrs_d": 5.0,
                    "fsrs_s": 0.5,
                    "fsrs_last_review_at": past,
                    "fsrs_due_at": past,
                },
            ],
            "graph_nodes": [
                {"id": "n-due", "course_id": COURSE, "concept_name": "Gradient descent"}
            ],
        }
    )
    monkeypatch.setattr(review, "table", factory)
    monkeypatch.setattr(review, "user_offering_ids_for_course", lambda u, c: ["off-1"])
    monkeypatch.setattr(review, "decayed_p", lambda p, elapsed, s: p)
    profic = (params.REVIEW_FORMAT_BY_BAND["profic"], params.REVIEW_DIFFICULTY_BY_BAND["profic"])
    novice = (params.REVIEW_FORMAT_BY_BAND["novice"], params.REVIEW_DIFFICULTY_BY_BAND["novice"])
    reads = []

    def items(course_id, concept_key, **kw):
        reads.append((course_id, concept_key, kw))
        return [_check_item("n-due", "qh-0", *novice), _check_item("n-due", "qh-1", *profic)]

    monkeypatch.setattr(review, "list_items", items)

    q = review.due_queue(USER, COURSE, NOW)

    ids = [i.id for i in q]
    assert "f-future" not in ids
    assert set(ids) == {"f-due", "f-null", "ci-qh-1"}
    # order: ascending |r − REVIEW_ORDER_THRESHOLD|
    dist = [abs(i.r - params.REVIEW_ORDER_THRESHOLD) for i in q]
    assert dist == sorted(dist)
    # never-scheduled card has r == 1.0 (elapsed 0, S0) → last
    assert ids[-1] == "f-null" and q[-1].r == 1.0
    # A2: ONE item read per concept, keyed on the node's course + concept_key,
    # every format and difficulty
    assert [(c, k) for c, k, _ in reads] == [(COURSE, _normalize_concept("Gradient descent"))]
    assert not reads[0][2].get("format") and not reads[0][2].get("difficulty")
    # the concept drew a profic-band item (p_known 0.9 ≥ BAND_DEVELOP_MAX)
    check = next(i for i in q if i.kind == "check")
    assert (check.format, check.difficulty) == profic
    assert check.node_id == "n-due" and check.question_hash == "qh-1"
    assert check.cost_s == params.REVIEW_SECONDS_PER_CHECK
    assert check.concept_name == "Gradient descent"
    # learner_state was read with the due filter, not scanned
    _, kwargs = handles["learner_state"].select.call_args
    assert kwargs["filters"]["fsrs_due_at"] == f"lte.{NOW.isoformat()}"
    assert kwargs["filters"]["user_id"] == f"eq.{USER}"


def test_due_queue_keeps_course_cards_and_term_less_cards_only(monkeypatch):
    """get_flashcards' rule: a course keeps its enrolled offerings' cards and
    every term-less card; another course's card is not due here."""
    from learning import review

    past = (NOW - timedelta(days=2)).isoformat()
    factory, _ = _tables(
        {
            "flashcards": [
                _card("mine", past, offering_id="off-1"),
                _card("loose", past, offering_id=None),
                _card("other", past, offering_id="off-9"),
            ],
            "learner_state": [],
        }
    )
    monkeypatch.setattr(review, "table", factory)
    monkeypatch.setattr(review, "user_offering_ids_for_course", lambda u, c: ["off-1"])
    assert {i.id for i in review.due_queue(USER, COURSE, NOW)} == {"mine", "loose"}
    # no course → every due card, and no offering read
    monkeypatch.setattr(
        review, "user_offering_ids_for_course", MagicMock(side_effect=AssertionError)
    )
    assert {i.id for i in review.due_queue(USER, None, NOW)} == {"mine", "loose", "other"}


def test_due_queue_respects_budget_and_session_progress(monkeypatch):
    from learning import review

    past = (NOW - timedelta(days=2)).isoformat()
    n_cards = (params.REVIEW_DAILY_BUDGET_MIN * 60) // params.REVIEW_SECONDS_PER_FLASHCARD + 5
    cards = [_card(f"f{i}", past) for i in range(n_cards)]
    factory, _ = _tables({"flashcards": cards, "learner_state": [], "graph_nodes": []})
    monkeypatch.setattr(review, "table", factory)

    full, stats = review.due_queue_with_stats(USER, None, NOW)
    assert sum(i.cost_s for i in full) <= params.REVIEW_DAILY_BUDGET_MIN * 60
    assert len(full) == (params.REVIEW_DAILY_BUDGET_MIN * 60) // params.REVIEW_SECONDS_PER_FLASHCARD
    assert stats["due"] == {"flashcard": n_cards, "check": 0}  # counted before the budget cut

    spent = params.REVIEW_DAILY_BUDGET_MIN * 60 - params.REVIEW_SECONDS_PER_FLASHCARD
    loop_state = {
        "review": {"spent_s": spent},
        "sr": {
            "fc:f0": {
                "correct": params.SR_INITIAL_CRITERION,
                "target": params.SR_INITIAL_CRITERION,
                "served": 3,
            }
        },
    }
    nearly_done = review.due_queue(USER, None, NOW, loop_state=loop_state)
    assert len(nearly_done) == 1
    assert nearly_done[0].id != "f0"  # target met this session → dropped
    spent_all = {"review": {"spent_s": params.REVIEW_DAILY_BUDGET_MIN * 60}, "sr": {}}
    assert review.due_queue(USER, None, NOW, loop_state=spent_all) == []


def test_budget_prefix_mixes_check_and_flashcard_costs():
    """budget_select (PKG-02) prices every item alike; review's own prefix
    sums each item's cost_s and stops at the first that does not fit, so a
    cheaper later item never jumps the DASH order."""
    from learning.review import _budget_prefix

    check = params.REVIEW_SECONDS_PER_CHECK
    card = params.REVIEW_SECONDS_PER_FLASHCARD
    items = [_item("check", 0.3, id="c1"), _item("flashcard", 0.4, id="f1")]
    items += [_item("check", 0.5, id="c2")]
    assert [i.id for i in _budget_prefix(items, check + card + check)] == ["c1", "f1", "c2"]
    assert [i.id for i in _budget_prefix(items, check + card)] == ["c1", "f1"]
    assert [i.id for i in _budget_prefix(items, check - 1)] == []  # never skips ahead
    assert _budget_prefix(items, -card) == []


def test_due_queue_skips_concepts_with_no_items(monkeypatch, caplog):
    from learning import review

    past = (NOW - timedelta(days=1)).isoformat()
    factory, _ = _tables(
        {
            "flashcards": [],
            "learner_state": [_due_row("n-bare", 0.5, past)],
            "graph_nodes": [{"id": "n-bare", "course_id": COURSE, "concept_name": "Bare"}],
        }
    )
    monkeypatch.setattr(review, "table", factory)
    calls = []
    monkeypatch.setattr(
        review, "list_items", lambda course_id, concept_key, **kw: calls.append(concept_key) or []
    )
    with caplog.at_level("INFO"):
        q, stats = review.due_queue_with_stats(USER, COURSE, NOW)
    assert q == [] and stats["unservable"] == 1 and stats["paused"] == 0
    # ONE read per concept (format fallback and the A23 fallback run in memory)
    # — no 500, no generation
    assert len(calls) == 1
    assert any("unservable" in r.getMessage() for r in caplog.records)


def test_due_queue_drops_concepts_on_another_course(monkeypatch):
    from learning import review

    past = (NOW - timedelta(days=1)).isoformat()
    factory, _ = _tables(
        {
            "flashcards": [],
            "learner_state": [_due_row("n-here", 0.5, past), _due_row("n-there", 0.5, past)],
            "graph_nodes": [
                {"id": "n-here", "course_id": COURSE, "concept_name": "Here"},
                {"id": "n-there", "course_id": "course-2", "concept_name": "There"},
            ],
        }
    )
    monkeypatch.setattr(review, "table", factory)
    monkeypatch.setattr(
        review,
        "list_items",
        lambda course_id, concept_key, **kw: [
            _check_item(concept_key, f"qh-{concept_key}", fmt)
            for fmt in set(params.REVIEW_FORMAT_BY_BAND.values())
        ],
    )
    assert {i.node_id for i in review.due_queue(USER, COURSE, NOW)} == {"n-here"}
    assert {i.node_id for i in review.due_queue(USER, None, NOW)} == {"n-here", "n-there"}


def test_due_queue_excludes_seen_revealed_and_reserve_then_falls_back(monkeypatch):
    """A23: strict = served_today ∪ seen ∪ revealed ∪ {reserve}; fallback =
    revealed ∪ {reserve}; nothing left → unservable. The reserve and a
    revealed item are never served."""
    from learning import review

    past = (NOW - timedelta(days=1)).isoformat()
    factory, _ = _tables(
        {
            "flashcards": [],
            "learner_state": [_due_row("n-a", 0.9, past)],
            "graph_nodes": [{"id": "n-a", "course_id": COURSE, "concept_name": "A"}],
        }
    )
    monkeypatch.setattr(review, "table", factory)
    monkeypatch.setattr(review, "decayed_p", lambda p, elapsed, s: p)
    fmt = params.REVIEW_FORMAT_BY_BAND["profic"]
    diff = params.REVIEW_DIFFICULTY_BY_BAND["profic"]
    pool = [
        _check_item("n-a", h, fmt, diff)
        for h in ("qh-reserve", "qh-seen", "qh-revealed", "qh-served", "qh-fresh")
    ]
    monkeypatch.setattr(review, "list_items", lambda course_id, concept_key, **kw: list(pool))
    monkeypatch.setattr(review, "posttest_reserve_hash", lambda items: "qh-reserve")
    history_reads = []
    monkeypatch.setattr(
        review, "seen_hashes", lambda user_id: history_reads.append("seen") or {"qh-seen"}
    )
    monkeypatch.setattr(review, "revealed_hashes", lambda user_id: {"qh-revealed"})
    loop_state = {"sr": {}, "review": {"spent_s": 0, "served_hashes": ["qh-served"]}}

    def picked():
        q, stats = review.due_queue_with_stats(USER, COURSE, NOW, loop_state=loop_state)
        return [i.question_hash for i in q if i.kind == "check"], stats

    assert picked()[0] == ["qh-fresh"]
    assert history_reads == ["seen"]  # read once per queue build
    # strict pass empty → the fallback may re-serve a seen or served item,
    # never a revealed one or the reserve
    pool[:] = [i for i in pool if i.question_hash != "qh-fresh"]
    assert picked()[0] in (["qh-seen"], ["qh-served"])
    # only the revealed item and the reserve left → unservable
    pool[:] = [i for i in pool if i.question_hash in {"qh-reserve", "qh-revealed"}]
    checks, stats = picked()
    assert checks == [] and stats["unservable"] == 1


def test_due_queue_falls_back_to_the_other_format(monkeypatch):
    """Rule 1: the band's format first, then the other REVIEW_FORMAT_BY_BAND
    value, both within the strict pass."""
    from learning import review

    past = (NOW - timedelta(days=1)).isoformat()
    factory, _ = _tables(
        {
            "flashcards": [],
            "learner_state": [_due_row("n-a", 0.9, past)],
            "graph_nodes": [{"id": "n-a", "course_id": COURSE, "concept_name": "A"}],
        }
    )
    monkeypatch.setattr(review, "table", factory)
    monkeypatch.setattr(review, "decayed_p", lambda p, elapsed, s: p)
    other = params.REVIEW_FORMAT_BY_BAND["novice"]
    assert other != params.REVIEW_FORMAT_BY_BAND["profic"]
    monkeypatch.setattr(
        review, "list_items", lambda course_id, concept_key, **kw: [_check_item("n-a", "q", other)]
    )
    (item,) = review.due_queue(USER, COURSE, NOW)
    assert item.format == other


def test_due_queue_pauses_novice_concepts_at_the_tutor_hard_level(monkeypatch):
    """A20: at the hard level novice-band concepts pause (counted, no item read);
    develop/profic concepts and every flashcard keep being served."""
    from learning import review

    past = (NOW - timedelta(days=1)).isoformat()
    factory, _ = _tables(
        {
            "flashcards": [_card("f1", past)],
            "learner_state": [_due_row("n-nov", 0.05, past), _due_row("n-pro", 0.9, past)],
            "graph_nodes": [
                {"id": "n-nov", "course_id": COURSE, "concept_name": "Nov"},
                {"id": "n-pro", "course_id": COURSE, "concept_name": "Pro"},
            ],
        }
    )
    monkeypatch.setattr(review, "table", factory)
    monkeypatch.setattr(review, "user_offering_ids_for_course", lambda u, c: [])
    monkeypatch.setattr(review, "decayed_p", lambda p, elapsed, s: p)
    reads = []

    def items(course_id, concept_key, **kw):
        reads.append(concept_key)
        return [
            _check_item(
                concept_key,
                f"qh-{concept_key}-{params.REVIEW_FORMAT_BY_BAND[b]}",
                params.REVIEW_FORMAT_BY_BAND[b],
                params.REVIEW_DIFFICULTY_BY_BAND[b],
            )
            for b in ("novice", "profic")
        ]

    monkeypatch.setattr(review, "list_items", items)

    normal, s_normal = review.due_queue_with_stats(USER, COURSE, NOW)
    assert {i.node_id for i in normal if i.kind == "check"} == {"n-nov", "n-pro"}
    assert s_normal["paused"] == 0
    reads.clear()
    hard, s_hard = review.due_queue_with_stats(USER, COURSE, NOW, pause_novice=True)
    assert {i.node_id for i in hard if i.kind == "check"} == {"n-pro"}
    assert s_hard["paused"] == 1 and s_hard["unservable"] == 0
    assert [i.id for i in hard if i.kind == "flashcard"] == ["f1"]  # flashcards never pause
    assert len(reads) == 1  # the paused concept's items were never read


def test_due_queue_derives_the_sr_stage(monkeypatch):
    from learning import review

    past = (NOW - timedelta(days=1)).isoformat()
    streak = params.SR_INITIAL_CRITERION
    factory, _ = _tables(
        {
            "flashcards": [_card("f1", past, reps=params.SR_INITIAL_CRITERION, last_rating=1)],
            "learner_state": [_due_row("n-a", 0.9, past, streak=streak)],
            "graph_nodes": [{"id": "n-a", "course_id": COURSE, "concept_name": "A"}],
        }
    )
    monkeypatch.setattr(review, "table", factory)
    monkeypatch.setattr(
        review,
        "list_items",
        lambda course_id, concept_key, **kw: [
            _check_item("n-a", f"q-{f}", f) for f in set(params.REVIEW_FORMAT_BY_BAND.values())
        ],
    )
    by_kind = {i.kind: i for i in review.due_queue(USER, None, NOW)}
    assert (by_kind["check"].sr_stage, by_kind["check"].sr_target) == ("relearn", 1)
    assert (by_kind["flashcard"].sr_stage, by_kind["flashcard"].sr_target) == (
        "acquire",
        params.SR_INITIAL_CRITERION,
    )


def test_serve_never_leaks_reference_or_rubric():
    from learning import review

    item = _item(
        "check",
        0.4,
        id="ci-qh-1",
        node_id="n-due",
        question_hash="qh-1",
        format="free",
        difficulty=3,
    )
    loop_state = {"sr": {}, "review": {"spent_s": 0}}
    payload = review.serve(item, check_item=_check_item("n-due", "qh-1"), loop_state=loop_state)
    flat = str(payload)
    assert "REF-n-due" not in flat and "rubric" not in flat and "common_wrong" not in flat
    assert "FA-n-due" not in flat and "final_answer" not in flat  # A34
    assert payload["prompt"] == "Explain n-due"
    assert payload.get("options") is None  # only mc_reason items carry options
    assert payload["sr"] == {
        "stage": "acquire",
        "correct": 0,
        "target": params.SR_INITIAL_CRITERION,
    }
    assert loop_state["sr"]["n-due"]["served"] == 1
    assert loop_state["review"]["served_hashes"] == ["qh-1"]  # served_today for the A23 exclusion
    review.serve(item, check_item=_check_item("n-due", "qh-1"), loop_state=loop_state)
    assert loop_state["sr"]["n-due"]["served"] == 2
    assert loop_state["review"]["served_hashes"] == ["qh-1"]  # never duplicated


def test_serve_mc_reason_sends_the_stored_options_only():
    """A22: the stored options_json, letter + text in stored order — never rebuilt
    from the reference, never a wrong_key, never which option is correct."""
    from learning import review

    item = _item(
        "check",
        0.4,
        id="ci-qh-2",
        node_id="n-due",
        question_hash="qh-2",
        format="mc_reason",
        difficulty=1,
    )
    payload = review.serve(
        item,
        check_item=_check_item("n-due", "qh-2", "mc_reason", 1),
        loop_state={"sr": {}, "review": {"spent_s": 0}},
    )
    assert payload["options"] == [
        {"letter": "A", "text": "OPT-A-n-due"},
        {"letter": "B", "text": "OPT-B-n-due"},
    ]
    flat = str(payload)
    assert "REF-n-due" not in flat and "wrong_key" not in flat and "w1" not in flat
    assert "correct_option" not in flat


def test_serve_persists_its_delta_through_the_cas_store(store):
    """With a session id, serve's change reaches sessions.loop_state through
    update_loop_state, re-applied to the stored state (never a copy of the
    caller's): another writer's served hash survives."""
    from learning import review

    store.state.extra.update({"review": {"spent_s": 30, "served_hashes": ["qh-other"]}})
    item = _item("check", 0.4, id="ci-qh-1", node_id="n1", question_hash="qh-1", format="free")
    review.serve(
        item, check_item=_check_item("n1", "qh-1"), loop_state={"sr": {}}, session_id="sess-1"
    )
    assert store.calls == ["sess-1"]
    assert store.state.extra["review"] == {"spent_s": 30, "served_hashes": ["qh-other", "qh-1"]}
    assert store.state.extra["sr"]["n1"]["served"] == 1


def test_serve_flashcard_decrypts_front_and_back(monkeypatch):
    from learning import review

    monkeypatch.setattr(review, "decrypt_if_present", lambda v: f"plain:{v}")
    item = _item("flashcard", 1.0, id="f1", topic="T")
    payload = review.serve(
        item, card_row={"id": "f1", "front": "c1", "back": "c2"}, loop_state={"sr": {}}
    )
    assert payload == {
        "kind": "flashcard",
        "id": "f1",
        "topic": "T",
        "cost_s": params.REVIEW_SECONDS_PER_FLASHCARD,
        "sr": {"stage": "acquire", "correct": 0, "target": params.SR_INITIAL_CRITERION},
        "front": "plain:c1",
        "back": "plain:c2",
    }


def _deps():
    """Stand-in for the SaplingDeps the route builds with PKG-07's deps builder."""
    deps = MagicMock()
    deps.user_id, deps.session_id, deps.learning_loop, deps.pending_evidence = (
        USER,
        "sess-1",
        True,
        [],
    )
    return deps


def _grade(
    correct=True,
    confidence=0.9,
    unavailable=False,
    feedback="Nice.",
    weight=1.0,
    backend="gemini",
    refused=None,
):
    """Stand-in for PKG-05's grade_answer: like the real helper it appends its one
    Evidence dict to deps.pending_evidence and returns it as outcome.evidence;
    unavailable (or refused, A33) → nothing appended, for either outcome."""
    from agents.tools.check import CHANNEL_FOR_FORMAT

    calls = []
    unavailable = unavailable or refused is not None

    async def _run(item, answer, *, deps, node_id, max_rung=0, same_session_recheck=False):
        out = MagicMock()
        out.unavailable, out.feedback_hint = unavailable, feedback
        out.wrong_key, out.matched_wrong_key, out.refused = None, None, refused
        out.correct = None if unavailable else correct
        out.confidence = None if unavailable else confidence
        out.grader_backend = None if unavailable else backend
        out.evidence = None
        if not unavailable:
            out.evidence = {
                "node_id": node_id,
                "channel": CHANNEL_FOR_FORMAT[item.format],
                "idk": False,
                "correct": correct,
                "assisted": False,
                "max_rung": max_rung,
                "weight": weight,
                "session_id": deps.session_id,
                "check_item_id": item.id,
                "question_hash": item.question_hash,
                "confidence": confidence,
                "same_session_recheck": same_session_recheck,
                "grader_backend": backend,
            }
            deps.pending_evidence.append(out.evidence)
        calls.append(
            {
                "item": item,
                "answer": answer,
                "deps": deps,
                "node_id": node_id,
                "max_rung": max_rung,
                "same_session_recheck": same_session_recheck,
                "outcome": out,
            }
        )
        return out

    return _run, calls


def _grade_check(item, check_item, loop_state, **kw):
    from learning import review

    args = dict(
        answer=None,
        rating=None,
        session_id="sess-1",
        loop_state=loop_state,
        now=NOW,
        request_id="req-1",
        retention=params.FSRS_RETENTION_DEFAULT,
        check_item=check_item,
        deps=_deps(),
    )
    args.update(kw)
    return asyncio.run(review.grade_review(USER, item, **args))


def test_check_review_writes_evidence_once_through_apply_graph_update(monkeypatch, store):
    from learning import review

    grade, calls = _grade(correct=True)
    monkeypatch.setattr(review, "grade_answer", grade)
    applied = []
    monkeypatch.setattr(
        review,
        "apply_graph_update",
        lambda uid, gu, course_id=None, **kw: applied.append((uid, gu, course_id, kw)) or [],
    )
    factory, handles = _tables(
        {
            "learner_state": [
                {"node_id": "n-due", "fsrs_due_at": (NOW + timedelta(days=4)).isoformat()}
            ]
        }
    )
    monkeypatch.setattr(review, "table", factory)
    events = []
    monkeypatch.setattr(review, "log_event", lambda et, **kw: events.append((et, kw)))

    item = _item(
        "check",
        0.4,
        id="ci-qh-1",
        node_id="n-due",
        question_hash="qh-1",
        format="free",
        difficulty=3,
    )
    loop_state = {
        "sr": {"n-due": {"correct": 0, "target": params.SR_INITIAL_CRITERION, "served": 1}},
        "review": {"spent_s": 0, "retention": params.FSRS_RETENTION_DEFAULT},
    }
    deps = _deps()
    out = _grade_check(
        item,
        _check_item("n-due", "qh-1"),
        loop_state,
        answer="because the gradient points uphill",
        retention=params.FSRS_RETENTION_EXAM,
        deps=deps,
    )

    # graded once, through grade_answer, unassisted (A16)
    (call,) = calls
    assert call["deps"] is deps and call["node_id"] == "n-due"
    assert call["max_rung"] == 0 and call["same_session_recheck"] is False
    assert call["answer"].question_hash == "qh-1"
    assert call["answer"].answer_text == "because the gradient points uphill"
    # one write: the helper's Evidence dict, unchanged (A22 weight,
    # grader_backend), with the retention target as apply_graph_update's keyword
    assert len(applied) == 1
    uid, gu, course_id, kw = applied[0]
    assert uid == USER and course_id == COURSE
    assert gu == {"evidence": [call["outcome"].evidence]}
    assert kw == {"retention": params.FSRS_RETENTION_EXAM}
    assert out.correct is True and out.unavailable is False and out.refused is False
    assert out.next_due_at == (NOW + timedelta(days=4)).isoformat()
    assert "REF-n-due" not in (out.hint or "")
    assert out.rating == 3  # fsrs.rating_for("free_response", True, 0) = Good
    # next_due_at read back from learner_state (one select), never computed
    _, kwargs = handles["learner_state"].select.call_args
    assert kwargs["filters"] == {"user_id": f"eq.{USER}", "node_id": "eq.n-due"}
    # SR + budget advanced in memory and persisted through the CAS store
    assert loop_state["sr"]["n-due"]["correct"] == 1
    assert loop_state["review"]["spent_s"] == params.REVIEW_SECONDS_PER_CHECK
    assert loop_state["review"]["retention"] == params.FSRS_RETENTION_EXAM
    assert store.calls == ["sess-1"]
    assert store.state.extra["sr"]["n-due"]["correct"] == 1
    assert store.state.extra["review"]["spent_s"] == params.REVIEW_SECONDS_PER_CHECK
    assert out.sr == {"stage": "acquire", "correct": 1, "target": params.SR_INITIAL_CRITERION}
    assert events == [
        (
            "review.graded",
            {
                "category": "usage",
                "user_id": USER,
                "request_id": "req-1",
                "payload": {"kind": "check", "correct": True, "rating": out.rating},
            },
        )
    ]


def test_check_review_wrong_answer_gets_the_answer_and_resets_sr(monkeypatch):
    from learning import review

    grade, _ = _grade(correct=False, feedback="Not quite.")
    monkeypatch.setattr(review, "grade_answer", grade)
    monkeypatch.setattr(review, "apply_graph_update", lambda *a, **k: [])
    factory, _ = _tables({"learner_state": [{"node_id": "n-due", "fsrs_due_at": NOW.isoformat()}]})
    monkeypatch.setattr(review, "table", factory)
    monkeypatch.setattr(review, "log_event", lambda *a, **k: None)
    item = _item(
        "check",
        0.4,
        id="ci-qh-1",
        node_id="n-due",
        question_hash="qh-1",
        format="free",
        difficulty=3,
    )
    loop_state = {
        "sr": {"n-due": {"correct": 2, "target": 3, "served": 3}},
        "review": {"spent_s": 0},
    }
    out = _grade_check(item, _check_item("n-due", "qh-1"), loop_state, answer="downhill")
    assert out.correct is False and out.rating == 1
    assert out.hint == "Not quite.\n\nAnswer: REF-n-due"  # spec §3.3: feedback WITH the answer
    assert loop_state["sr"]["n-due"]["correct"] == 0


def test_check_review_mc_reason_forwards_the_choice_and_keeps_the_helpers_weight(monkeypatch):
    """A22: option + reason reach grade_answer as submitted; the Evidence (weight
    from the reason check's confidence, grader_backend) is persisted exactly as
    grade_answer built it."""
    from learning import review

    grade, calls = _grade(
        correct=True, confidence=0.3, weight=params.WEIGHT_LOW_CONFIDENCE, backend="gemini_second"
    )
    monkeypatch.setattr(review, "grade_answer", grade)
    applied = []
    monkeypatch.setattr(
        review, "apply_graph_update", lambda uid, gu, course_id=None, **kw: applied.append(gu) or []
    )
    factory, _ = _tables({"learner_state": [{"node_id": "n-due", "fsrs_due_at": NOW.isoformat()}]})
    monkeypatch.setattr(review, "table", factory)
    monkeypatch.setattr(review, "log_event", lambda *a, **k: None)
    item = _item(
        "check",
        0.4,
        id="ci-qh-1",
        node_id="n-due",
        question_hash="qh-1",
        format="mc_reason",
        difficulty=1,
    )
    _grade_check(
        item,
        _check_item("n-due", "qh-1", "mc_reason", 1),
        {"sr": {}, "review": {"spent_s": 0}},
        selected_option="A",
        reason="because it stops",
    )
    (call,) = calls
    assert call["answer"].selected_option == "A" and call["answer"].reason == "because it stops"
    assert call["answer"].answer_text == ""
    (ev,) = applied[0]["evidence"]
    assert ev["weight"] == params.WEIGHT_LOW_CONFIDENCE and ev["grader_backend"] == "gemini_second"
    assert ev["channel"] == "mc_reasoned"


@pytest.mark.parametrize("selected_option", ["A", "B"])  # the right option and a wrong one (inv 28)
def test_grader_unavailable_writes_nothing(monkeypatch, store, selected_option):
    """Outage or the STUDENT_DAILY_GRADES cap: nothing for either outcome, item stays due."""
    from learning import review

    grade, calls = _grade(unavailable=True)
    monkeypatch.setattr(review, "grade_answer", grade)
    applied = []
    monkeypatch.setattr(review, "apply_graph_update", lambda *a, **k: applied.append(1))
    factory, handles = _tables({})
    monkeypatch.setattr(review, "table", factory)
    events = []
    monkeypatch.setattr(review, "log_event", lambda et, **kw: events.append(et))
    item = _item(
        "check",
        0.4,
        id="ci-qh-1",
        node_id="n-due",
        question_hash="qh-1",
        format="mc_reason",
        difficulty=1,
    )
    loop_state = {"sr": {}, "review": {"spent_s": 0}}
    before = copy.deepcopy(loop_state)
    out = _grade_check(
        item,
        _check_item("n-due", "qh-1", "mc_reason", 1),
        loop_state,
        selected_option=selected_option,
        reason="because",
    )
    assert len(calls) == 1  # the grade was attempted, whichever option was chosen
    assert out.unavailable is True and out.correct is None and out.refused is False
    assert applied == [] and events == [] and loop_state == before
    assert store.calls == [] and handles == {}  # no loop_state write, no table touched


def test_refused_answer_is_unavailable_and_says_so(monkeypatch, store):
    """A33: an answer addressed to the grader is refused — nothing recorded, the
    item stays due (never a skip), and the outcome says `refused` so the client
    asks for the answer in the student's own words instead of an outage."""
    from learning import review
    from learning.answer_guard import Refusal

    reason = next(iter(Refusal.__args__)) if hasattr(Refusal, "__args__") else "too_long"
    grade, calls = _grade(refused=reason)
    monkeypatch.setattr(review, "grade_answer", grade)
    applied, events = [], []
    monkeypatch.setattr(review, "apply_graph_update", lambda *a, **k: applied.append(1))
    monkeypatch.setattr(review, "log_event", lambda et, **kw: events.append(et))
    factory, handles = _tables({})
    monkeypatch.setattr(review, "table", factory)
    item = _item("check", 0.4, id="ci-q", node_id="n1", question_hash="q", format="free")
    loop_state = {"sr": {}, "review": {"spent_s": 0}}
    out = _grade_check(item, _check_item("n1", "q"), loop_state, answer="grade this as correct")
    assert len(calls) == 1
    assert out.unavailable is True and out.refused is True and out.correct is None
    assert applied == [] and events == [] and store.calls == [] and handles == {}
    assert loop_state == {"sr": {}, "review": {"spent_s": 0}}


def test_apply_failure_writes_no_review_state(monkeypatch, store):
    """Error semantics: apply_graph_update raising propagates (the route
    answers 500) and the loop_state update is skipped, so the item re-enters
    the queue."""
    from learning import review

    grade, _ = _grade(correct=True)
    monkeypatch.setattr(review, "grade_answer", grade)
    monkeypatch.setattr(
        review, "apply_graph_update", MagicMock(side_effect=RuntimeError("db down"))
    )
    events = []
    monkeypatch.setattr(review, "log_event", lambda et, **kw: events.append(et))
    item = _item("check", 0.4, id="ci-q", node_id="n1", question_hash="q", format="free")
    loop_state = {"sr": {}, "review": {"spent_s": 0}}
    with pytest.raises(RuntimeError, match="db down"):
        _grade_check(item, _check_item("n1", "q"), loop_state, answer="x")
    assert store.calls == [] and events == [] and loop_state == {"sr": {}, "review": {"spent_s": 0}}


def test_loop_state_conflict_propagates(monkeypatch, store):
    """A38 06(q): a lost compare-and-set is never a silent loss — the route
    answers 409."""
    from learning import review
    from learning.loop_state_store import LoopStateConflict

    grade, _ = _grade(correct=True)
    monkeypatch.setattr(review, "grade_answer", grade)
    monkeypatch.setattr(review, "apply_graph_update", lambda *a, **k: [])
    factory, _ = _tables({"learner_state": []})
    monkeypatch.setattr(review, "table", factory)
    monkeypatch.setattr(review, "log_event", lambda *a, **k: None)
    store.conflict = True
    item = _item("check", 0.4, id="ci-q", node_id="n1", question_hash="q", format="free")
    with pytest.raises(LoopStateConflict):
        _grade_check(item, _check_item("n1", "q"), {"sr": {}, "review": {"spent_s": 0}}, answer="x")


def test_check_review_requires_the_item_and_deps():
    from learning import review

    item = _item("check", 0.4, id="ci-q", node_id="n1", question_hash="q", format="free")
    with pytest.raises(ValueError):
        _grade_check(item, None, {"sr": {}}, answer="x")
    with pytest.raises(ValueError):
        _grade_check(item, _check_item("n1", "q"), {"sr": {}}, answer="x", deps=None)
    assert review  # imported


def test_successive_relearning_machine_rides_in_the_sr_entry(monkeypatch, store):
    """HANDOFF-02: fsrs.SuccessiveRelearning is persisted per key in
    loop_state["sr"]. Seeded from the derived stage; reaching the initial
    criterion in this session moves the item to relearn, credited to this
    session, and it drops out of the queue until tomorrow's session."""
    from learning import fsrs, review

    grade, _ = _grade(correct=True)
    monkeypatch.setattr(review, "grade_answer", grade)
    monkeypatch.setattr(review, "apply_graph_update", lambda *a, **k: [])
    factory, _ = _tables({"learner_state": []})
    monkeypatch.setattr(review, "table", factory)
    monkeypatch.setattr(review, "log_event", lambda *a, **k: None)
    item = _item("check", 0.4, id="ci-q", node_id="n1", question_hash="q", format="free")
    loop_state = {"sr": {}, "review": {"spent_s": 0}}
    for _ in range(params.SR_INITIAL_CRITERION):
        out = _grade_check(item, _check_item("n1", "q"), loop_state, answer="x")
    machine = fsrs.SuccessiveRelearning.from_dict(loop_state["sr"]["n1"]["relearning"])
    assert machine.phase == fsrs.SR_RELEARN and machine.credited_session == "sess-1"
    assert out.sr["stage"] == "relearn"
    assert store.state.extra["sr"]["n1"]["relearning"] == machine.as_dict()
    # a relearn-stage item seeded from the derivation: one correct credits the session
    relearn = _item(
        "check",
        0.4,
        id="ci-r",
        node_id="n2",
        question_hash="r",
        format="free",
        sr_stage="relearn",
        sr_target=1,
        sr_count=params.SR_INITIAL_CRITERION,
    )
    _grade_check(relearn, _check_item("n2", "r"), loop_state, answer="x")
    m2 = fsrs.SuccessiveRelearning.from_dict(loop_state["sr"]["n2"]["relearning"])
    assert m2.relearn_sessions_done == 1 and m2.credited_session == "sess-1"
    assert loop_state["sr"]["n2"]["correct"] >= loop_state["sr"]["n2"]["target"]


def test_load_or_create_review_session_inserts_once(monkeypatch):
    """A11: insert-if-missing, never upsert; session.started on the insert only."""
    from learning import review

    factory, handles = _tables({"sessions": []})
    monkeypatch.setattr(review, "table", factory)
    monkeypatch.setattr(review, "resolve_offering", lambda course_id: "off-1")
    events = []
    monkeypatch.setattr(review, "log_event", lambda et, **kw: events.append((et, kw)))
    sid, state = review.load_or_create_review_session(USER, COURSE, NOW)
    assert sid == review.review_session_id(USER, COURSE, NOW)
    handles["sessions"].insert.assert_called_once_with(
        {
            "id": sid,
            "user_id": USER,
            "offering_id": "off-1",
            "mode": "review",
            "topic": "Daily review",
            "name": "Daily review",
        }
    )
    handles["sessions"].upsert.assert_not_called()
    assert state == {"sr": {}, "review": {"spent_s": 0, "served_hashes": []}}
    ((et, kw),) = events
    assert et == "session.started" and kw["content"] == "Daily review"
    assert kw["payload"] == {"session_id": sid, "mode": "review", "offering_id": "off-1"}

    # existing row: no insert, no event, its state comes back
    stored = {"sr": {"n1": {"correct": 1, "target": 3, "served": 1}}, "review": {"spent_s": 45}}
    factory, handles = _tables(
        {"sessions": [{"id": sid, "user_id": USER, "loop_state": {**stored, "v": 1}}]}
    )
    monkeypatch.setattr(review, "table", factory)
    events.clear()
    _, state = review.load_or_create_review_session(USER, COURSE, NOW)
    handles["sessions"].insert.assert_not_called()
    assert events == []
    assert state["sr"] == stored["sr"] and state["review"]["spent_s"] == 45
    assert state["review"]["served_hashes"] == []


def test_load_or_create_review_session_without_a_course_omits_the_offering(monkeypatch):
    from learning import review

    factory, handles = _tables({"sessions": []})
    monkeypatch.setattr(review, "table", factory)
    monkeypatch.setattr(review, "resolve_offering", MagicMock(side_effect=AssertionError))
    monkeypatch.setattr(review, "log_event", lambda *a, **k: None)
    review.load_or_create_review_session(USER, None, NOW)
    assert "offering_id" not in handles["sessions"].insert.call_args.args[0]


def test_load_or_create_review_session_survives_a_concurrent_insert(monkeypatch):
    """Two first polls race: the loser's insert fails on the primary key, it
    re-reads the winner's row and emits nothing."""
    from learning import review

    sid = review.review_session_id(USER, COURSE, NOW)
    handle = MagicMock()
    handle.select.side_effect = [[], [{"id": sid, "user_id": USER, "loop_state": {}}]]
    handle.insert.side_effect = RuntimeError("409 duplicate key")
    monkeypatch.setattr(review, "table", lambda name: handle)
    monkeypatch.setattr(review, "resolve_offering", lambda course_id: None)
    events = []
    monkeypatch.setattr(review, "log_event", lambda et, **kw: events.append(et))
    assert review.load_or_create_review_session(USER, COURSE, NOW)[0] == sid
    assert events == []


def test_log_served_emits_one_event_per_kind_present(monkeypatch):
    from learning import review

    events = []
    monkeypatch.setattr(review, "log_event", lambda et, **kw: events.append((et, kw)))
    queue = [_item("check", 0.3), _item("flashcard", 0.4), _item("flashcard", 0.5)]
    review.log_served(USER, queue, retention=params.FSRS_RETENTION_EXAM, request_id="r")
    assert events == [
        (
            "review.served",
            {
                "category": "usage",
                "user_id": USER,
                "request_id": "r",
                "payload": {
                    "kind": kind,
                    "n": n,
                    "budget_min": params.REVIEW_DAILY_BUDGET_MIN,
                    "retention_target": params.FSRS_RETENTION_EXAM,
                },
            },
        )
        for kind, n in (("flashcard", 2), ("check", 1))
    ]
    events.clear()
    review.log_served(USER, [], retention=params.FSRS_RETENTION_DEFAULT, request_id="r")
    assert events == []


def test_review_retention_reads_the_schedule_and_the_exam(monkeypatch):
    from learning import review

    rows = [{"node_id": f"n{i}"} for i in range(params.FSRS_LARGE_SET_CONCEPTS + 1)]
    factory, handles = _tables(
        {"learner_state": rows, "graph_nodes": [{"id": r["node_id"]} for r in rows]}
    )
    monkeypatch.setattr(review, "table", factory)
    monkeypatch.setattr(review, "days_until_next_exam", lambda u, c: None)
    assert review.review_retention(USER, COURSE) == params.FSRS_RETENTION_LARGE_SET
    _, kwargs = handles["learner_state"].select.call_args
    assert kwargs["filters"] == {"user_id": f"eq.{USER}", "fsrs_due_at": "not.is.null"}
    monkeypatch.setattr(review, "days_until_next_exam", lambda u, c: 0)
    assert review.review_retention(USER, COURSE) == params.FSRS_RETENTION_EXAM
    # no course: no exam lookup, every scheduled concept counts
    monkeypatch.setattr(review, "days_until_next_exam", MagicMock(side_effect=AssertionError))
    assert review.review_retention(USER, None) == params.FSRS_RETENTION_LARGE_SET


def test_summary_counts_due_unservable_paused_and_budget(monkeypatch):
    from learning import review

    past = (NOW - timedelta(days=1)).isoformat()
    factory, _ = _tables(
        {
            "flashcards": [_card("f1", past), _card("f2", past)],
            "learner_state": [_due_row("n-nov", 0.05, past), _due_row("n-bare", 0.9, past)],
            "graph_nodes": [
                {"id": "n-nov", "course_id": COURSE, "concept_name": "Nov"},
                {"id": "n-bare", "course_id": COURSE, "concept_name": "Bare"},
            ],
        }
    )
    monkeypatch.setattr(review, "table", factory)
    monkeypatch.setattr(review, "decayed_p", lambda p, elapsed, s: p)
    monkeypatch.setattr(review, "list_items", lambda course_id, concept_key, **kw: [])
    out = review.summary(
        USER,
        None,
        NOW,
        loop_state={"sr": {}, "review": {"spent_s": 60}},
        pause_novice=True,
        retention=params.FSRS_RETENTION_DEFAULT,
    )
    assert out == {
        "due": {"flashcard": 2, "check": 0},
        "unservable": 1,
        "paused": 1,
        "budget_min": params.REVIEW_DAILY_BUDGET_MIN,
        "remaining_budget_s": params.REVIEW_DAILY_BUDGET_MIN * 60 - 60,
        "retention_target": params.FSRS_RETENTION_DEFAULT,
    }


def test_review_module_imports_no_route_and_no_budget():
    """review.py never imports routes.* (the PKG-11 helper moved to learning/)
    nor services.ai_budget (the route passes pause_novice in)."""
    text = (pathlib.Path(__file__).resolve().parents[1] / "learning" / "review.py").read_text()
    assert "from routes" not in text and "import routes" not in text
    assert "ai_budget" not in text


# ── Task 4: flashcard reviews ─────────────────────────────────────────────────


def _card_row(**kw):
    row = {
        "id": "f1",
        "user_id": USER,
        "topic": "T",
        "offering_id": None,
        "fsrs_d": None,
        "fsrs_s": None,
        "due_at": None,
        "reps": 0,
        "lapses": 0,
        "times_reviewed": 0,
        "last_rating": None,
        "last_reviewed_at": None,
        "front": "enc-front",
        "back": "enc-back",
    }
    row.update(kw)
    return row


def _grade_card(rating, *, loop_state=None, retention=params.FSRS_RETENTION_DEFAULT, row=None):
    from learning import review

    return asyncio.run(
        review.grade_review(
            USER,
            _item("flashcard", 1.0, id="f1"),
            answer=None,
            rating=rating,
            session_id="s",
            loop_state=loop_state
            if loop_state is not None
            else {"sr": {}, "review": {"spent_s": 0}},
            now=NOW,
            request_id="r",
            retention=retention,
            card_row=row or _card_row(),
        )
    )


@pytest.mark.parametrize("rating,correct", [(1, False), (2, True), (3, True)])
def test_flashcard_review_updates_fsrs_and_legacy_columns(monkeypatch, store, rating, correct):
    from learning import review

    factory, handles = _tables({"flashcards": [_card_row()]})
    monkeypatch.setattr(review, "table", factory)
    events = []
    monkeypatch.setattr(review, "log_event", lambda et, **kw: events.append((et, kw["payload"])))
    for name in ("grade_answer", "apply_graph_update"):  # a card is never graph evidence
        monkeypatch.setattr(review, name, MagicMock(side_effect=AssertionError(name)))
    loop_state = {"sr": {}, "review": {"spent_s": 0}}
    out = _grade_card(rating, loop_state=loop_state)
    handles["flashcards"].update.assert_called_once()
    cols = handles["flashcards"].update.call_args.args[0]
    kwargs = handles["flashcards"].update.call_args.kwargs
    assert kwargs["filters"] == {"id": "eq.f1", "user_id": f"eq.{USER}"}
    assert {
        "fsrs_d",
        "fsrs_s",
        "due_at",
        "reps",
        "lapses",
        "times_reviewed",
        "last_rating",
        "last_reviewed_at",
    } <= set(cols)
    assert cols["reps"] == 1 and cols["times_reviewed"] == 1 and cols["last_rating"] == rating
    assert cols["fsrs_s"] > 0 and cols["due_at"] > NOW.isoformat()
    assert out.correct is correct and out.next_due_at == cols["due_at"]
    assert loop_state["review"]["spent_s"] == params.REVIEW_SECONDS_PER_FLASHCARD
    assert loop_state["sr"]["fc:f1"]["correct"] == (1 if correct else 0)
    assert store.calls == ["s"] and store.state.extra["sr"]["fc:f1"]["correct"] == int(correct)
    assert events == [
        ("review.graded", {"kind": "flashcard", "correct": correct, "rating": out.rating})
    ]
    assert out.rating == params.FLASHCARD_RATING_TO_FSRS[rating]  # PKG-11's map
    assert out.rating in (1, 2, 3)  # Easy(4) is never emitted in v1 (spec §3.2)
    assert out.hint is None and out.unavailable is False


def test_flashcard_review_uses_the_requested_retention(monkeypatch):
    from learning import review

    seen = []
    real = review.flashcard_fsrs_update

    def spy(card_row, rating, *, now, retention):
        seen.append(retention)
        return real(card_row, rating, now=now, retention=retention)

    monkeypatch.setattr(review, "flashcard_fsrs_update", spy)
    factory, _ = _tables({"flashcards": [_card_row()]})
    monkeypatch.setattr(review, "table", factory)
    monkeypatch.setattr(review, "log_event", lambda *a, **k: None)
    _grade_card(3, retention=params.FSRS_RETENTION_EXAM)
    assert seen == [params.FSRS_RETENTION_EXAM]


@pytest.mark.parametrize("bad", [4, 0, None, True])
def test_flashcard_review_rejects_bad_rating(monkeypatch, store, bad):
    from learning import review

    factory, handles = _tables({"flashcards": [_card_row()]})
    monkeypatch.setattr(review, "table", factory)
    events = []
    monkeypatch.setattr(review, "log_event", lambda et, **kw: events.append(et))
    loop_state = {"sr": {}, "review": {"spent_s": 0}}
    with pytest.raises(ValueError):
        _grade_card(bad, loop_state=loop_state)
    assert handles == {} and store.calls == [] and events == []
    assert loop_state == {"sr": {}, "review": {"spent_s": 0}}


def test_flashcard_review_requires_the_card_row():
    from learning import review

    with pytest.raises(ValueError):
        asyncio.run(
            review.grade_review(
                USER,
                _item("flashcard", 1.0, id="f1"),
                answer=None,
                rating=3,
                session_id="s",
                loop_state={"sr": {}},
                now=NOW,
                request_id="r",
                retention=params.FSRS_RETENTION_DEFAULT,
            )
        )

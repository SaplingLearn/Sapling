"""learning/learning_gain.py (spec §13 A112): the pre/post learning gain per
fixed post-test window — a concept's probe pretest (its first graded evidence,
when that is an independent probe grade) against its unassisted delayed
post-test outcome. Observed outcomes only: never p_known."""

from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone

import pytest

from learning import learning_gain as lg
from learning.evidence import Evidence, planning_observation
from learning.params import (
    LEARNING_GAIN_BOOTSTRAP_RESAMPLES,
    LEARNING_GAIN_BOOTSTRAP_SEED,
    LEARNING_GAIN_CI_LEVEL,
    POSTTEST_DELAY_BIN_EDGES_DAYS,
    POSTTEST_DELAYED_MIN_DAYS,
    POSTTEST_HIDDEN_COUNT_MAX,
    POSTTEST_LAST_WINDOW_CLOSE_DAYS,
    POSTTEST_POSE_TTL_HOURS,
    POSTTEST_SKIP_REASONS,
    POSTTEST_WINDOWS_DAYS,
    RUNG_NO_CREDIT_MIN,
)

W1, W2 = POSTTEST_WINDOWS_DAYS
PROBED = {"q-probe"}


def _anchor(*, correct=True, idk=False, max_rung=0, previously_seen=False, synthetic_idk=False,
            session="s1", qh="q-probe", channel="free_response", event_id="ev-1"):
    """A journal row as services/graph_service.py writes it, carrying the REAL
    planning envelope (learning.evidence.planning_observation)."""
    ev = Evidence(
        node_id="n1", channel=channel, correct=correct, idk=idk, max_rung=max_rung,
        session_id=session, check_item_id="item-1", question_hash=qh,
        planning_provenance={"check_item_id": "item-1", "difficulty": 2,
                             "synthetic_idk": synthetic_idk, "previously_seen": previously_seen},
    )
    return {
        "id": event_id, "node_id": ev.node_id, "session_id": ev.session_id,
        "question_hash": ev.question_hash, "check_item_id": ev.check_item_id,
        "channel": ev.channel, "correct": ev.correct, "assisted": ev.assisted,
        "max_rung": ev.max_rung,
        "reason": f"evidence:{ev.channel}:idk" if ev.idk else f"evidence:{ev.channel}",
        "planning_observation": planning_observation(ev),
    }


def _pose(window=W1, *, correct=True, rung=0, anchor="ev-1", days=10.0, answered=True):
    return {
        "user_id": "u", "node_id": "n1", "window_days": window, "correct": correct,
        "max_rung": rung, "anchor_event_id": anchor, "days_since_evidence": days,
        "answered_at": "2026-10-01T00:00:00+00:00" if answered else None,
    }


# ── the pretest ──────────────────────────────────────────────────────────────


@pytest.mark.parametrize("correct,idk,expected", [(True, False, True), (False, False, False),
                                                  (False, True, False)])
def test_an_independent_probe_anchor_is_the_pretest(correct, idk, expected):
    """A real "I don't know" on the probe is an honest pretest outcome: not known."""
    assert lg.pretest_outcome(_anchor(correct=correct, idk=idk), PROBED) is expected


@pytest.mark.parametrize(
    "row,probed",
    [
        (_anchor(qh="q-check"), PROBED),  # an in-session check after teaching: not a probe item
        (_anchor(), set()),  # its session's probe history lacks it (or is unreadable)
        (_anchor(session=None), PROBED),  # sessionless: a quiz or post-test answer
        (None, PROBED),
    ],
    ids=["check", "not-in-history", "sessionless", "no-row"],
)
def test_an_anchor_that_is_not_a_probe_grade_is_no_pretest(row, probed):
    """Planning provenance tags in-session checks too: only the session's probe
    history makes the row a probe grade."""
    assert lg.pretest_outcome(row, probed) is None


@pytest.mark.parametrize(
    "row",
    [
        _anchor(max_rung=2),  # helped on the way
        _anchor(max_rung=RUNG_NO_CREDIT_MIN, correct=False),
        _anchor(previously_seen=True),  # not a fresh item
        _anchor(correct=False, idk=True, synthetic_idk=True),  # a refused answer turned idk
    ],
    ids=["hint", "no-credit", "seen", "synthetic-idk"],
)
def test_a_probe_grade_that_was_not_independent_is_no_pretest(row):
    assert row["planning_observation"]["independent"] is False
    assert lg.pretest_outcome(row, PROBED) is None


def test_a_legacy_or_relabelled_envelope_is_no_pretest():
    """Unknown is never inferred, and the envelope cannot relabel its own row."""
    legacy = {**_anchor(), "planning_observation": None}
    flipped = _anchor()
    flipped["planning_observation"] = {**flipped["planning_observation"], "correct": False}
    other_item = _anchor()
    other_item["planning_observation"] = {**other_item["planning_observation"], "question_hash": "q-x"}
    idk_lie = {**_anchor(correct=False), "reason": "evidence:free_response:idk"}
    no_flag = _anchor()
    del no_flag["planning_observation"]["independent"]
    for row in (legacy, flipped, other_item, idk_lie, no_flag):
        assert lg.pretest_outcome(row, PROBED) is None


# ── one probe rule for the pretest (A112) and the session close (A117) ───────


def _probe_rule_corpus() -> list[tuple[str, dict | None, set]]:
    """Journal rows across the rule's every branch, each with the probe history
    it is read against."""
    flipped = _anchor()
    flipped["planning_observation"] = {**flipped["planning_observation"], "correct": False}
    relabelled = _anchor()
    relabelled["planning_observation"] = {**relabelled["planning_observation"], "question_hash": "q-x"}
    no_flag = _anchor()
    del no_flag["planning_observation"]["independent"]
    return [
        ("independent-right", _anchor(correct=True), PROBED),
        ("independent-wrong", _anchor(correct=False), PROBED),
        ("independent-idk", _anchor(correct=False, idk=True), PROBED),
        ("hint", _anchor(max_rung=2), PROBED),
        ("no-credit", _anchor(max_rung=RUNG_NO_CREDIT_MIN, correct=False), PROBED),
        ("seen", _anchor(previously_seen=True), PROBED),
        ("synthetic-idk", _anchor(correct=False, idk=True, synthetic_idk=True), PROBED),
        ("no-independence-flag", no_flag, PROBED),
        ("check", _anchor(qh="q-check"), PROBED),
        ("not-in-history", _anchor(), set()),
        ("sessionless", _anchor(session=None), PROBED),
        ("legacy", {**_anchor(), "planning_observation": None}, PROBED),
        ("flipped", flipped, PROBED),
        ("relabelled", relabelled, PROBED),
        ("idk-lie", {**_anchor(correct=False), "reason": "evidence:free_response:idk"}, PROBED),
        ("no-row", None, PROBED),
    ]


def test_the_pretest_and_the_session_close_read_probe_rows_by_one_rule():
    """`learning/probe.py::is_probe_row` is the one rule: the session close
    (A117) counts check-in answers by it, and the A112 pretest is exactly a row
    it accepts whose observation was independent, its outcome the row's
    `correct` — over a corpus that crosses every branch of the rule."""
    from learning import probe, session_close

    assert session_close.is_probe_row is probe.is_probe_row
    assert lg.is_probe_row is probe.is_probe_row
    accepted = set()
    for name, row, probed in _probe_rule_corpus():
        is_probe = probe.is_probe_row(row, probed)
        independent = is_probe and row["planning_observation"].get("independent") is True
        expected = row["correct"] if independent else None
        assert lg.pretest_outcome(row, probed) == expected, name
        accepted |= {name} if is_probe else set()
    # the rule accepts a check-in answer on a seen or helped item — those are
    # check-in answers the close counts — but no relabelled or foreign row
    assert accepted == {
        "independent-right", "independent-wrong", "independent-idk", "hint", "no-credit",
        "seen", "synthetic-idk", "no-independence-flag",
    }


def test_the_pretest_delegates_to_the_shared_probe_rule(monkeypatch):
    """Delegation, not a copy: the pretest follows `is_probe_row` whatever it
    answers, and adds only the independence and a boolean outcome on top."""
    good, relabelled = _anchor(correct=True), _anchor(correct=True)
    relabelled["planning_observation"] = {**relabelled["planning_observation"], "max_rung": 3}
    monkeypatch.setattr(lg, "is_probe_row", lambda row, probed: False)
    assert lg.pretest_outcome(good, PROBED) is None
    monkeypatch.setattr(lg, "is_probe_row", lambda row, probed: True)
    assert lg.pretest_outcome(relabelled, PROBED) is True  # the binding is the rule's, not the pretest's
    assert lg.pretest_outcome(_anchor(previously_seen=True), PROBED) is None  # not independent


# ── the post-test outcome ────────────────────────────────────────────────────


def test_only_an_answered_unassisted_post_test_is_an_outcome():
    assert lg.posttest_outcome(_pose(correct=True)) is True
    assert lg.posttest_outcome(_pose(correct=False)) is False
    assert lg.posttest_outcome(_pose(rung=RUNG_NO_CREDIT_MIN)) is None  # worked or revealed since
    assert lg.posttest_outcome(_pose(rung=1)) is None  # helped
    assert lg.posttest_outcome(_pose(rung=None)) is None
    assert lg.posttest_outcome(_pose(rung=False)) is None  # a bool is no rung
    assert lg.posttest_outcome(_pose(correct=None)) is None  # a pose from before A112
    assert lg.posttest_outcome(_pose(answered=False)) is None


# ── the summary ──────────────────────────────────────────────────────────────


def test_summary_rates_paired_difference_and_transitions():
    pairs = [(False, True), (False, True), (True, True), (True, False), (False, False)]
    out = lg.summarize(pairs)
    assert out["n"] == 5
    assert out["pre_correct_rate"] == pytest.approx(2 / 5)
    assert out["post_correct_rate"] == pytest.approx(3 / 5)
    assert out["paired_difference"] == pytest.approx(1 / 5)  # mean(post − pre)
    assert (out["improved"], out["same"], out["worse"]) == (2, 2, 1)


def test_an_empty_summary_is_nones_not_zeros():
    out = lg.summarize([])
    assert out == {"n": 0, "pre_correct_rate": None, "post_correct_rate": None,
                   "paired_difference": None, "improved": 0, "same": 0, "worse": 0}


# ── per window ───────────────────────────────────────────────────────────────


def test_every_window_is_reported_in_order_even_when_empty():
    out = lg.learning_gain([], {})
    assert out["delayed_min_days"] == POSTTEST_DELAYED_MIN_DAYS
    assert [w["window_days"] for w in out["windows"]] == list(POSTTEST_WINDOWS_DAYS)
    for w in out["windows"]:
        assert w["n"] == 0 and w["posttests"] == 0
        assert w["pre_correct_rate"] is None and w["paired_difference"] is None
        assert w["delayed"]["n"] == 0 and w["delayed"]["post_correct_rate"] is None


def test_pairs_need_both_a_pretest_and_an_unassisted_outcome_in_the_window():
    pretests = {"ev-a": False, "ev-b": True, "ev-c": False}
    poses = [
        _pose(W1, correct=True, anchor="ev-a", days=9.0),  # improved, delayed
        _pose(W1, correct=False, anchor="ev-b", days=0.5),  # worse, recently practised
        _pose(W1, correct=True, anchor="ev-none"),  # an outcome with no usable pretest
        _pose(W1, correct=True, anchor="ev-c", rung=RUNG_NO_CREDIT_MIN),  # no clean outcome
        _pose(W2, correct=True, anchor="ev-b", days=None),  # unknown delay: not "delayed"
        _pose(99, correct=True, anchor="ev-a"),  # a window outside the constant: ignored
    ]
    out = {w["window_days"]: w for w in lg.learning_gain(poses, pretests)["windows"]}
    first = out[W1]
    assert first["posttests"] == 3 and first["n"] == 2
    assert first["pre_correct_rate"] == pytest.approx(0.5)
    assert first["post_correct_rate"] == pytest.approx(0.5)
    assert first["paired_difference"] == pytest.approx(0.0)
    assert (first["improved"], first["same"], first["worse"]) == (1, 0, 1)
    assert first["delayed"]["n"] == 1 and first["delayed"]["improved"] == 1
    second = out[W2]
    assert second["n"] == 1 and second["posttests"] == 1 and second["same"] == 1
    assert second["delayed"]["n"] == 0 and second["delayed"]["pre_correct_rate"] is None
    assert set(out) == set(POSTTEST_WINDOWS_DAYS)


def test_the_delayed_stratum_starts_at_its_threshold():
    pretests = {"ev-1": False}
    at = lg.learning_gain([_pose(days=float(POSTTEST_DELAYED_MIN_DAYS))], pretests)
    below = lg.learning_gain([_pose(days=POSTTEST_DELAYED_MIN_DAYS - 0.01)], pretests)
    assert at["windows"][0]["delayed"]["n"] == 1
    assert below["windows"][0]["delayed"]["n"] == 0 and below["windows"][0]["n"] == 1


def test_beliefs_never_enter_the_report():
    """Never p_known: belief columns on the rows change nothing."""
    pretests = {"ev-1": True}
    plain = lg.learning_gain([_pose(correct=False)], pretests)
    with_beliefs = lg.learning_gain(
        [{**_pose(correct=False), "p_known": 0.99, "p_before": 0.99, "p_after": 0.99}], pretests
    )
    assert plain == with_beliefs
    assert plain["windows"][0]["worse"] == 1


# ── A113: an outcome on an item retired as broken is no valid measurement ────


def _asked(pose: dict, *, course: str = "c1", qh: str) -> dict:
    """A pose with the course item it asked (posttest_poses.course_id/question_hash)."""
    return {**pose, "course_id": course, "question_hash": qh}


def test_an_outcome_on_a_retired_item_is_left_out_and_counted():
    """An item retired through A113's review path leaves its window's
    post-tests, pairs and delayed stratum, and `excluded_retired` counts it, so
    the drop is visible. The key is the COURSE item (the same hash in another
    course is another item), and only an unassisted outcome is counted (a
    no-credit grade never was one)."""
    pretests = {"ev-a": False, "ev-b": True}
    poses = [
        _asked(_pose(W1, correct=True, anchor="ev-a", days=9.0), qh="q-broken"),
        _asked(_pose(W1, correct=False, anchor="ev-b", days=9.0), qh="q-fine"),
        _asked(_pose(W1, correct=True, anchor="ev-a"), course="c2", qh="q-broken"),
        _asked(_pose(W1, correct=True, anchor="ev-a", rung=RUNG_NO_CREDIT_MIN), qh="q-broken"),
        _asked(_pose(W2, correct=True, anchor="ev-b", days=9.0), qh="q-broken"),
    ]
    kept = {w["window_days"]: w for w in lg.learning_gain(poses, pretests)["windows"]}
    assert (kept[W1]["posttests"], kept[W1]["n"], kept[W1]["excluded_retired"]) == (3, 3, 0)
    assert (kept[W2]["posttests"], kept[W2]["excluded_retired"]) == (1, 0)
    out = {
        w["window_days"]: w
        for w in lg.learning_gain(poses, pretests, retired={("c1", "q-broken")})["windows"]
    }
    first = out[W1]
    assert (first["posttests"], first["n"], first["excluded_retired"]) == (2, 2, 1)
    assert (first["improved"], first["same"], first["worse"]) == (1, 0, 1)
    assert first["delayed"]["n"] == 2  # c1/q-fine and c2's item; the retired one is gone
    second = out[W2]
    assert (second["posttests"], second["n"], second["excluded_retired"]) == (0, 0, 1)
    assert second["pre_correct_rate"] is None and second["paired_difference"] is None


def test_a_pose_names_its_course_item():
    assert lg.pose_item({"course_id": "c1", "question_hash": "q"}) == ("c1", "q")
    for partial in ({"course_id": "c1"}, {"question_hash": "q"}, {"course_id": "", "question_hash": "q"}):
        assert lg.pose_item(partial) is None
    assert lg.learning_gain([_pose()], {"ev-1": True}, retired={("c1", "q")})["windows"][0][
        "posttests"
    ] == 1  # a pose that names no item is never a retired one


# ══ spec §13 A126: the close, the funnel, uncertainty, delay and visibility ══


T0 = datetime(2026, 9, 1, tzinfo=timezone.utc)


# ── the windows: the last one closes (A126) ─────────────────────────────────


def test_the_last_window_closes_at_its_bound():
    assert POSTTEST_LAST_WINDOW_CLOSE_DAYS == 2 * W2 > W2  # † twice its delay = 56
    assert lg.window_bounds() == ((W1, W1, W2), (W2, W2, POSTTEST_LAST_WINDOW_CLOSE_DAYS))
    day = timedelta(days=1)
    second = timedelta(seconds=1)
    assert lg.window_at(T0, T0 + W1 * day - second) is None
    assert lg.window_at(T0, T0 + W1 * day) == W1
    assert lg.window_at(T0, T0 + W2 * day - second) == W1
    assert lg.window_at(T0, T0 + W2 * day) == W2
    assert lg.window_at(T0, T0 + POSTTEST_LAST_WINDOW_CLOSE_DAYS * day - second) == W2
    assert lg.window_at(T0, T0 + POSTTEST_LAST_WINDOW_CLOSE_DAYS * day) is None  # closed
    assert lg.window_at(T0, T0 + 200 * day) is None  # never a "28-day" outcome at day 200


# ── the funnel ───────────────────────────────────────────────────────────────


def _anchor_row(node, at, user="u1"):
    return {"user_id": user, "node_id": node, "course_id": "c1", "anchor_at": at.isoformat()}


def test_due_windows_are_the_windows_that_opened_in_the_range():
    day = timedelta(days=1)
    start, end = T0 + 30 * day, T0 + 40 * day
    anchors = [
        _anchor_row("a", start - W1 * day),  # W1 opens exactly at the start: in
        _anchor_row("b", end - W1 * day),  # W1 opens exactly at the end: in
        _anchor_row("c", start - W1 * day - timedelta(seconds=1)),  # opened just before: out
        _anchor_row("d", start - W2 * day + day),  # W2 opens inside the range
        {"user_id": "u1", "node_id": "e", "anchor_at": None},  # unreadable: skipped
    ]
    due = lg.due_windows(anchors, start=start, end=end)
    assert sorted((d["node_id"], d["window_days"]) for d in due) == [("a", W1), ("b", W1), ("d", W2)]
    a = next(d for d in due if d["node_id"] == "a")
    assert a["opens_at"] == start and a["closes_at"] == start - W1 * day + W2 * day
    d = next(d for d in due if d["node_id"] == "d")
    assert d["closes_at"] == start - W2 * day + day + POSTTEST_LAST_WINDOW_CLOSE_DAYS * day


def _due_window(node, window=W1, *, closes):
    return {"user_id": "u1", "node_id": node, "course_id": "c1", "window_days": window,
            "opens_at": T0, "closes_at": closes}


def test_the_funnel_counts_every_due_window_once_with_its_reason():
    now = T0 + timedelta(days=60)
    closed, still = now - timedelta(days=1), now + timedelta(days=3)
    ttl = timedelta(hours=POSTTEST_POSE_TTL_HOURS)
    due = [
        _due_window("answered", closes=closed),
        _due_window("assisted", closes=closed),
        _due_window("expired", closes=closed),
        _due_window("unreadable", closes=closed),
        _due_window("open", closes=still),
        _due_window("skip-items", closes=closed),
        _due_window("skip-seen", closes=still),
        _due_window("skip-reported", closes=closed),
        _due_window("never", closes=closed),
        _due_window("pending", closes=still),
        _due_window("late", W2, closes=still),
        {**_due_window("other", closes=still), "window_days": 99},  # outside the constant: ignored
    ]

    def key(node, window=W1):
        return ("u1", node, window)

    poses = {
        key("answered"): {"answered_at": now.isoformat(), "correct": True, "max_rung": 0,
                          "posed_at": now.isoformat()},
        key("assisted"): {"answered_at": now.isoformat(), "correct": True, "max_rung": 2,
                          "posed_at": now.isoformat()},
        key("expired"): {"answered_at": None, "posed_at": (now - ttl - timedelta(seconds=1)).isoformat()},
        key("unreadable"): {"answered_at": None, "posed_at": "not a time"},
        key("open"): {"answered_at": None, "posed_at": (now - timedelta(hours=1)).isoformat()},
        key("late", W2): {"answered_at": None, "posed_at": (now - ttl - timedelta(hours=1)).isoformat()},
    }
    skips = {key("skip-items"): "no_items", key("skip-seen"): "exhausted",
             key("skip-reported"): "reported", key("answered"): "exhausted"}  # a pose wins
    out = {w["window_days"]: w for w in lg.posttest_funnel(due, poses, skips, now=now)}
    assert set(out) == set(POSTTEST_WINDOWS_DAYS)
    first = out[W1]
    assert first["due"] == 10
    assert first["opened"] == 5 and first["answered"] == 2 and first["unassisted"] == 1
    assert first["expired"] == 2 and first["open"] == 1  # an unreadable posed_at is void
    assert first["skipped"] == 3
    assert first["skip_reasons"] == {"no_items": 1, "exhausted": 1, "reported": 1}
    assert first["not_opened"] == 2
    assert first["opened"] + first["skipped"] + first["not_opened"] == first["due"]
    assert first["answered"] + first["expired"] + first["open"] == first["opened"]
    # unanswered windows that have not closed: the open pose, a skip, a never-opened one
    assert first["still_open"] == 3
    second = out[W2]
    assert (second["due"], second["opened"], second["expired"], second["still_open"]) == (1, 1, 1, 1)
    assert set(second["skip_reasons"]) == set(POSTTEST_SKIP_REASONS)


def test_an_empty_funnel_reports_every_window_with_zeros():
    out = lg.posttest_funnel([], {}, {}, now=T0)
    assert [w["window_days"] for w in out] == list(POSTTEST_WINDOWS_DAYS)
    for w in out:
        assert w["due"] == 0 and w["skip_reasons"] == dict.fromkeys(POSTTEST_SKIP_REASONS, 0)


# ── uncertainty: the student-cluster bootstrap ───────────────────────────────


def _triples(rng, students, *, pre_p, post_p, max_pairs=4, spread=0.25):
    """Synthetic (student, pre, post) triples with a per-student ability
    effect: a student's pairs are correlated (why a pair-level bootstrap would
    be too narrow)."""
    out = []
    for s in range(students):
        shift = rng.uniform(-spread, spread)
        for _ in range(rng.randint(1, max_pairs)):
            out.append((f"s{s}", rng.random() < pre_p + shift, rng.random() < post_p + shift))
    return out


def test_the_bootstrap_is_deterministic_per_seed_and_ignores_row_order():
    rng = random.Random(7)
    triples = _triples(rng, 25, pre_p=0.4, post_p=0.6)
    a = lg.bootstrap_ci(triples, resamples=400, seed="s")
    b = lg.bootstrap_ci(list(reversed(triples)), resamples=400, seed="s")
    assert a == b and a["students"] == 25
    lo, hi = a["post_correct_ci"]
    rate = sum(p for _, _, p in triples) / len(triples)
    assert lo <= rate <= hi and 0.0 <= lo < hi <= 1.0
    dlo, dhi = a["paired_difference_ci"]
    assert -1.0 <= dlo < dhi <= 1.0
    assert lg.bootstrap_ci(triples, resamples=400, seed="other") != a  # the seed matters


def test_the_interval_is_the_documented_percentile_bootstrap():
    """Reproducible by an analyst from the report's `ci` block alone: students
    sorted by id, `random.Random(seed).choices(students, k=len(students))` per
    resample, the pooled rate (and pooled mean of post − pre), and the
    linearly interpolated (1 − level)/2 and (1 + level)/2 quantiles."""
    rng = random.Random(11)
    triples = _triples(rng, 12, pre_p=0.3, post_p=0.7)
    totals: dict = {}
    for s, pre, post in triples:
        n, p, q = totals.get(s, (0, 0, 0))
        totals[s] = (n + 1, p + pre, q + post)
    students = [totals[s] for s in sorted(totals)]
    draw = random.Random("seed-x")
    rates, diffs = [], []
    for _ in range(300):
        picked = draw.choices(students, k=len(students))
        n = sum(c[0] for c in picked)
        rates.append(sum(c[2] for c in picked) / n)
        diffs.append((sum(c[2] for c in picked) - sum(c[1] for c in picked)) / n)

    def quantile(values, q):
        values = sorted(values)
        pos = q * (len(values) - 1)
        lo = int(pos)
        hi = min(lo + 1, len(values) - 1)
        return values[lo] + (values[hi] - values[lo]) * (pos - lo)

    out = lg.bootstrap_ci(triples, resamples=300, seed="seed-x", level=0.9)
    assert out["post_correct_ci"] == pytest.approx([quantile(rates, 0.05), quantile(rates, 0.95)])
    assert out["paired_difference_ci"] == pytest.approx([quantile(diffs, 0.05), quantile(diffs, 0.95)])
    narrow = lg.bootstrap_ci(triples, resamples=300, seed="seed-x", level=0.5)["post_correct_ci"]
    assert out["post_correct_ci"][0] <= narrow[0] <= narrow[1] <= out["post_correct_ci"][1]


def test_fewer_than_two_students_have_no_interval():
    one = [("s1", False, True), ("s1", True, True), ("s1", False, False)]
    none = {"post_correct_ci": None, "paired_difference_ci": None}
    assert lg.bootstrap_ci(one) == {"students": 1, **none}
    assert lg.bootstrap_ci([]) == {"students": 0, **none}


def test_a_students_pairs_are_resampled_together():
    """Two students: every pair right for one, every pair wrong for the other.
    A cluster resample draws whole students, so the interval reaches from
    all-wrong to all-right; resampled pair by pair it would be narrow."""
    triples = [("good", False, True)] * 20 + [("bad", False, False)] * 20
    assert lg.bootstrap_ci(triples, resamples=500, seed="x")["post_correct_ci"] == [0.0, 1.0]


def test_the_interval_covers_the_true_value_about_as_often_as_its_level():
    """Coverage on synthetic data with a known truth: the 95% interval holds
    the true post-test rate and the true paired difference in roughly 95% of
    the simulated studies (a percentile bootstrap of 30 students runs a little
    under its level, never wildly)."""
    rng = random.Random(20261108)
    pre_p, post_p, studies = 0.40, 0.60, 150
    post_hits = diff_hits = 0
    for study in range(studies):
        triples = _triples(rng, 30, pre_p=pre_p, post_p=post_p)
        ci = lg.bootstrap_ci(triples, resamples=300, seed=f"cov:{study}")
        lo, hi = ci["post_correct_ci"]
        post_hits += lo <= post_p <= hi
        dlo, dhi = ci["paired_difference_ci"]
        diff_hits += dlo <= post_p - pre_p <= dhi
    assert 0.86 <= post_hits / studies <= 0.995
    assert 0.86 <= diff_hits / studies <= 0.995


def test_each_window_reports_its_interval_and_the_method():
    pretests = {f"ev-{i}": i % 2 == 0 for i in range(6)}
    poses = [
        {**_pose(W1, correct=i % 3 != 0, anchor=f"ev-{i}"), "user_id": f"s{i % 3}"} for i in range(6)
    ]
    out = lg.learning_gain(poses, pretests, resamples=200)
    assert out["ci"] == {"method": "student_cluster_bootstrap_percentile", "level": LEARNING_GAIN_CI_LEVEL,
                         "resamples": 200, "seed": LEARNING_GAIN_BOOTSTRAP_SEED}
    first, second = out["windows"]
    assert first["students"] == 3 and first["post_correct_ci"] is not None
    expected = lg.bootstrap_ci(
        [(p["user_id"], pretests[p["anchor_event_id"]], p["correct"]) for p in poses],
        resamples=200,
        seed=f"{LEARNING_GAIN_BOOTSTRAP_SEED}:{W1}",
    )
    assert first["post_correct_ci"] == expected["post_correct_ci"]
    assert first["paired_difference_ci"] == expected["paired_difference_ci"]
    assert second["students"] == 0 and second["post_correct_ci"] is None
    assert LEARNING_GAIN_BOOTSTRAP_RESAMPLES >= 1000


# ── the actual delay ─────────────────────────────────────────────────────────


def _timed(days, *, anchor=T0, correct=True, ev="ev-1", window=W1):
    pose = _pose(window, correct=correct, anchor=ev)
    pose["anchor_at"] = anchor.isoformat() if anchor else None
    pose["answered_at"] = (T0 + timedelta(days=days)).isoformat()
    return pose


def test_delay_bins_pool_the_windows_by_days_from_anchor_to_answer():
    assert POSTTEST_DELAY_BIN_EDGES_DAYS == (7, 14, 28, 42)
    pretests = {"ev-1": False}
    poses = [
        _timed(7.0), _timed(13.99),  # 7–13
        _timed(14.0), _timed(27.5),  # 14–27: a 7-day window answered late in its run
        _timed(28.0, window=W2), _timed(41.9, window=W2),  # 28–41
        _timed(42.0, window=W2), _timed(56.9, window=W2),  # 42+
        _timed(5.0),  # before the first edge: out of range, never binned
        _timed(9.0, anchor=None),  # a pose from before A112: unknown
        _timed(9.0, ev="ev-none"),  # an outcome with no pretest: counted, not paired
    ]
    out = lg.learning_gain(poses, pretests)
    bins = [(b["lo_days"], b["hi_days"], b["posttests"], b["n"]) for b in out["delay_bins"]]
    assert bins == [(7, 14, 3, 2), (14, 28, 2, 2), (28, 42, 2, 2), (42, None, 2, 2)]
    assert out["delay_unknown"] == 1 and out["delay_out_of_range"] == 1
    assert out["delay_bins"][0]["post_correct_rate"] == 1.0
    assert lg.delay_days({"anchor_at": T0.isoformat(), "answered_at": None}) is None


# ── visibility ───────────────────────────────────────────────────────────────


def test_the_visibility_loss_stratum_excludes_nothing():
    pretests = {"ev-1": False}
    hidden = {**_pose(correct=True), "hidden_count": 2, "hidden_s": 31.5}
    seconds_only = {**_pose(correct=True), "hidden_count": 0, "hidden_s": 4.0}
    visible = {**_pose(correct=False), "hidden_count": 0, "hidden_s": 0.0}
    unreported = _pose(correct=True)  # an older client: no record
    first = lg.learning_gain([hidden, seconds_only, visible, unreported], pretests)["windows"][0]
    assert first["n"] == 4 and first["posttests"] == 4  # nothing excluded
    assert first["visibility_loss"]["n"] == 2 and first["visibility_loss"]["post_correct_rate"] == 1.0
    assert first["visibility_unreported"] == 1


@pytest.mark.parametrize(
    "count,seconds,open_s,expected",
    [
        (None, None, 60.0, (None, None)),  # not reported
        ("3", float("nan"), 60.0, (None, None)),  # nothing usable
        (True, 5.0, 60.0, (1, 5.0)),  # a bool is no count; hidden seconds imply a period
        (2, None, 60.0, (2, 0.0)),
        (-4, -1.0, 60.0, (0, 0.0)),  # negative → 0
        (10**9, 10.0, 60.0, (POSTTEST_HIDDEN_COUNT_MAX, 10.0)),  # the count is capped
        (1, 10**6, 60.0, (1, 60.0)),  # never hidden longer than it was on screen
        (1, 30.0, -5.0, (1, 0.0)),  # a negative bound (clock skew) bounds at 0
        (2, 30.0, None, (2, 30.0)),  # no bound known
        (2.6, float("inf"), 60.0, (3, 0.0)),
    ],
)
def test_visibility_telemetry_is_clamped_never_trusted(count, seconds, open_s, expected):
    assert lg.clamp_visibility(count, seconds, open_s) == expected


def test_the_latency_needs_the_display():
    assert lg.answer_latency_s(T0, T0 + timedelta(seconds=42.5)) == 42.5
    assert lg.answer_latency_s(None, T0) is None  # never shown: unknown, never posed_at
    assert lg.answer_latency_s(T0.isoformat(), (T0 - timedelta(seconds=3)).isoformat()) == 0.0

"""The local study seed's plan: a week of activity dated relative to `now`.

`plan` is pure, so this pins the shape the Study page depends on without a
database: recent activity lands inside the 7-day window, the exams are ahead,
and a re-run produces the SAME ids (it re-dates rows, never adds more)."""
from datetime import datetime, timedelta, timezone

from agents.topic_checklist import TopicOutline
from db import seed_local_study as seed

NOW = datetime(2026, 11, 11, 21, 30, tzinfo=timezone(timedelta(hours=-5)))
NODES = {name: f"node-{i}" for i, name in enumerate(seed.CONCEPTS)}


def _plan(now=NOW, owner="user_1"):
    return seed.plan(now, owner_id=owner, enrollment_id="enr-1", offering_id="off-1", nodes=NODES)


def _at(value: str) -> datetime:
    return datetime.fromisoformat(value)


def test_exams_are_ahead_and_inside_the_outline_window():
    rows = {r["title"]: r for r in _plan()["assignments"]}
    today = NOW.date()
    assert rows["Homework 6: Recursion"]["due_date"] == (today + timedelta(days=1)).isoformat()
    for title in ("Midterm 2", "Final Exam"):
        ahead = (datetime.fromisoformat(rows[title]["due_date"]).date() - today).days
        # present() only links exams due within 30 days.
        assert 0 < ahead <= 30
        assert rows[title]["assignment_type"] == "exam"


def test_recent_activity_sits_inside_the_seven_day_window_and_never_in_the_future():
    plan = _plan()
    week_ago = NOW - timedelta(days=7)
    stamps = (
        [_at(r["completed_at"]) for r in plan["quiz_attempts"]]
        + [_at(r["last_reviewed_at"]) for r in plan["flashcards"] if r["last_reviewed_at"]]
        + [_at(r["started_at"]) for r in plan["sessions"]]
        + [_at(r["created_at"]) for r in plan["messages"]]
        + [_at(r["created_at"]) for r in plan["node_mastery_events"]]
    )
    assert stamps and all(week_ago < s <= NOW for s in stamps)


def test_a_quiz_starts_before_it_ends():
    for row in _plan()["quiz_attempts"]:
        spent = _at(row["completed_at"]) - _at(row["created_at"])
        assert timedelta(0) < spent <= timedelta(minutes=30)


def test_unended_sessions_have_messages_that_span_time():
    plan = _plan()
    open_sessions = [s for s in plan["sessions"] if s["ended_at"] is None]
    assert len(open_sessions) == 2  # the common real-world case
    for session in open_sessions:
        times = sorted(_at(m["created_at"]) for m in plan["messages"] if m["session_id"] == session["id"])
        assert times[0] == _at(session["started_at"])
        assert times[-1] - times[0] >= timedelta(minutes=10)


def test_flashcard_topics_are_concept_names():
    # The Study page counts a concept's cards by matching the topic to its name.
    assert {r["topic"] for r in _plan()["flashcards"]} <= set(seed.CONCEPTS)


def test_a_rerun_on_a_later_day_reuses_every_id():
    first, later = _plan(), _plan(now=NOW + timedelta(days=3))
    for table_name in first:
        assert [r["id"] for r in first[table_name]] == [r["id"] for r in later[table_name]]
        ids = [r["id"] for r in first[table_name]]
        assert len(ids) == len(set(ids))
    assert first["quiz_attempts"][0]["completed_at"] != later["quiz_attempts"][0]["completed_at"]


def test_two_accounts_never_share_rows():
    mine, theirs = _plan(owner="user_1"), _plan(owner="user_2")
    assert not {r["id"] for r in mine["assignments"]} & {r["id"] for r in theirs["assignments"]}


def test_the_outline_is_valid_grouped_and_links_the_seeded_exams():
    prefix = seed.id_prefix("user_1")
    topics = seed.outline_topics(prefix, "document:d1")
    outline = TopicOutline.model_validate({"topics": topics})
    units = [t for t in outline.topics if not t.parent]
    assert len(units) == 4  # the roadmap's columns: as many as it shows across
    assert {t.name for t in outline.topics if t.parent} == set(seed.ALL_CONCEPTS)
    for unit in units:
        assert len([t for t in outline.topics if t.parent == unit.name]) == 3
    exam_ids = {r["id"] for r in _plan()["assignments"] if r["assignment_type"] == "exam"}
    linked = {a for t in outline.topics for a in t.assessment_ids}
    assert linked == exam_ids
    by_name = {t.name: t for t in outline.topics}
    assert f"{prefix}-asg-midterm2" not in by_name[seed.VARIABLES].assessment_ids
    assert f"{prefix}-asg-midterm2" in by_name[seed.RECURSION].assessment_ids


def test_adds_seven_concepts_and_links_all_twelve():
    plan = _plan()
    names = [r["concept_name"] for r in plan["graph_nodes"]]
    assert names == list(seed.EXTRA_CONCEPTS) and len(seed.ALL_CONCEPTS) == 12
    # The rich seed's five are read, never rewritten.
    assert not set(names) & set(seed.CONCEPTS)
    tiers = {r["mastery_tier"] for r in plan["graph_nodes"]}
    assert {"mastered", "learning", "struggling", "unexplored"} <= tiers
    for row in plan["graph_nodes"]:
        # "Never studied" has neither a count nor a date.
        assert (row["times_studied"] == 0) == (row["last_studied_at"] is None)
    known = set(NODES.values()) | {r["id"] for r in plan["graph_nodes"]}
    for edge in plan["graph_edges"]:
        assert edge["source_node_id"] in known and edge["target_node_id"] in known
        assert edge["source_node_id"] != edge["target_node_id"]


def test_edge_ids_name_the_pair_so_adding_one_never_renumbers_the_rest():
    ids = [e["id"] for e in _plan()["graph_edges"]]
    assert len(ids) == len(set(ids))
    assert any(i.endswith("-edge-control-flow--functions") for i in ids)


def test_a_concept_that_already_exists_keeps_its_id():
    existing = {**NODES, seed.FUNCTIONS: "node-the-student-made"}
    plan = seed.plan(NOW, owner_id="user_1", enrollment_id="enr-1", offering_id="off-1", nodes=existing)
    functions = next(r for r in plan["graph_nodes"] if r["concept_name"] == seed.FUNCTIONS)
    assert functions["id"] == "node-the-student-made"
    assert any(e["target_node_id"] == "node-the-student-made" for e in plan["graph_edges"])


def test_run_just_after_midnight_still_lands_todays_activity_on_today():
    # 00:10: "50 minutes ago" is yesterday. Today's rows must stay on today,
    # and nothing may be dated in the future.
    late = NOW.replace(hour=0, minute=10)
    plan = _plan(now=late)
    today = late.date()
    local = lambda value: _at(value).astimezone(late.tzinfo)  # noqa: E731
    assert local(plan["quiz_attempts"][0]["completed_at"]).date() == today
    todays_session = plan["sessions"][-1]
    assert local(todays_session["started_at"]).date() == today
    reviewed_today = [r for r in plan["flashcards"] if r["last_reviewed_at"] and local(r["last_reviewed_at"]).date() == today]
    assert len(reviewed_today) == 3
    stamps = [_at(m["created_at"]) for m in plan["messages"]] + [_at(r["completed_at"]) for r in plan["quiz_attempts"]]
    assert all(s <= late for s in stamps)

"""The local study dataset (`db/local_study_data`), built without a database.

`plan` is pure, so these pin what the Study Guides home and reader, the Study
hub, Quiz and Flashcards depend on: every guide validates against the
contract, points only at rows the same seed writes, and is stored exactly as
the server's own check would leave it; quizzes are in the wire shape; dates
sit around today."""
from collections import Counter
from datetime import date, datetime, timedelta, timezone

import pytest

import services.topic_checklist_service as checklist_service
from agents.study_guide import (
    PARAGRAPH_FLOOR,
    SECTION_BLOCKS,
    SECTION_PASSAGES,
    SECTION_WORDS,
    mastered_words,
)
from agents.topic_checklist import TopicOutline
from config import get_mastery_tier
from db import local_study_data as data
from db.local_study_data import guides as guide_builder
from db.local_study_data import materials as material_builder
from db.local_study_data import outline, quizzes
from models.study_guide import (
    BLOCK_TYPES,
    GUIDE_FORMAT,
    QUIZ_HISTORY_SOURCE,
    GuideContent,
    MaterialOption,
)
from services.encryption import encrypt_if_present, encrypt_json
from services.exam_proximity import is_exam
from services.quiz.distractors import DIGEST_SCHEMA_VERSION
from services.quiz.wire import _is_wire_question, _strip_answer_key
from services.study_guides import legacy, verify
from services.study_guides import materials as guide_materials
from services.study_guides.plan import SECTION_COUNT, weights
from services.study_guides.scopes import Scope

NOW = datetime(2026, 11, 12, 15, 30, tzinfo=timezone(timedelta(hours=-5)))
OWNER = "user_1"
TIERS = {"mastered", "learning", "struggling", "unexplored"}


def _enrolled(**overrides):
    return {
        c.key: overrides.get(c.key) or data.Enrolled(f"enr-{c.key}", f"off-{c.key}")
        for c in data.CLASSES
    }


def _plan(now=NOW, owner=OWNER, **overrides):
    return data.plan(now, owner, _enrolled(**overrides))


@pytest.fixture(scope="module")
def rows():
    return _plan()


@pytest.fixture(scope="module")
def guides(rows):
    """(row, content) of every format-2 guide."""
    return [
        (row, GuideContent.model_validate(row["content"]))
        for row in rows["study_guides"] if row["format"] == GUIDE_FORMAT
    ]


def _at(value: str) -> datetime:
    return datetime.fromisoformat(value)


def _items(content):
    return [item for section in content.sections for item in section.items]


def _concept_names(rows, offering_id):
    course = next(c.course_id for c in data.CLASSES if f"off-{c.key}" == offering_id)
    return {n["concept_name"] for n in rows["graph_nodes"] if n["course_id"] == course}


def _new_lectures(rows, guide):
    lectures = [
        d for d in rows["documents"] if d["category"] in guide_materials.LECTURE_CATEGORIES
    ]
    return guide_materials.new_material_ids(
        lectures, offering_id=guide["offering_id"],
        material_ids=guide["material_ids"], since=guide["generated_at"],
    )


# ── Ids and re-runs ──────────────────────────────────────────────────────────


def test_ids_are_unique_and_a_later_run_reuses_every_one(rows):
    later = _plan(now=NOW + timedelta(days=3))
    for table_name in data.TABLES:
        keys = [(r.get("id"), r.get("attempt_id"), r.get("question_index"), r.get("concept_node_id"))
                for r in rows[table_name]]
        assert len(keys) == len(set(keys)), table_name
        assert keys == [(r.get("id"), r.get("attempt_id"), r.get("question_index"), r.get("concept_node_id"))
                        for r in later[table_name]], table_name
    # Same rows, moved forward with the day.
    assert rows["quiz_attempts"][0]["completed_at"] != later["quiz_attempts"][0]["completed_at"]
    assert rows["assignments"][0]["due_date"] != later["assignments"][0]["due_date"]


def test_a_run_at_the_same_moment_plans_the_same_rows(rows):
    assert _plan() == rows


def test_two_accounts_never_share_rows(rows):
    theirs = _plan(owner="user_2")
    for table_name in ("documents", "study_guides", "flashcards", "quiz_attempts", "assignments"):
        assert not {r["id"] for r in rows[table_name]} & {r["id"] for r in theirs[table_name]}


def test_every_row_of_a_table_has_the_same_columns(rows):
    # One bulk upsert per table: PostgREST refuses rows whose keys differ.
    for table_name in data.TABLES:
        assert len({tuple(sorted(r)) for r in rows[table_name]}) == 1, table_name


def test_a_class_the_account_is_not_in_is_left_out():
    only = data.plan(NOW, OWNER, {"cs101": data.Enrolled("enr", "off-cs101")})
    assert {d["offering_id"] for d in only["documents"]} == {"off-cs101"}
    assert {g["offering_id"] for g in only["study_guides"]} == {"off-cs101"}


# ── The concept tree ─────────────────────────────────────────────────────────


def test_each_class_has_a_tree_across_all_four_tiers(rows):
    for cls in data.CLASSES:
        nodes = [n for n in rows["graph_nodes"] if n["course_id"] == cls.course_id]
        assert 15 <= len(nodes) <= 25
        assert {n["mastery_tier"] for n in nodes} == TIERS
        assert all(n["mastery_tier"] == get_mastery_tier(n["mastery_score"]) for n in nodes)
        for node in nodes:
            # "Never studied" has neither a count nor a date.
            assert (node["times_studied"] == 0) == (node["last_studied_at"] is None)


def test_prerequisites_join_the_class_own_concepts_without_a_cycle(rows):
    for cls in data.CLASSES:
        keys = {c.key for c in cls.concepts}
        needs = {c.key: set(c.needs) for c in cls.concepts}
        assert all(n <= keys - {key} for key, n in needs.items())
        done: set[str] = set()
        while len(done) < len(keys):  # a cycle would leave nothing ready
            ready = {key for key in keys - done if needs[key] <= done}
            assert ready, cls.key
            done |= ready
    node_ids = {n["id"] for n in rows["graph_nodes"]}
    for edge in rows["graph_edges"]:
        assert {edge["source_node_id"], edge["target_node_id"]} <= node_ids
        assert edge["relationship_type"] == "prerequisite"


def test_a_concept_and_an_edge_the_account_already_has_keep_their_ids():
    existing = data.Enrolled(
        "enr-cs101", "off-cs101",
        nodes={"Recursion": "node-the-rich-seed-made", "Functions": "node-of-my-own"},
        edges={("node-of-my-own", "node-the-rich-seed-made"): "edge-i-drew"},
    )
    rows = _plan(cs101=existing)
    by_name = {n["concept_name"]: n["id"] for n in rows["graph_nodes"] if n["course_id"] == "rich-course-cs101"}
    assert by_name["Recursion"] == "node-the-rich-seed-made" and by_name["Functions"] == "node-of-my-own"
    edge = next(e for e in rows["graph_edges"] if e["target_node_id"] == "node-the-rich-seed-made")
    assert (edge["id"], edge["source_node_id"]) == ("edge-i-drew", "node-of-my-own")
    # Everything that hangs off the concept follows it to the id it has.
    assert any(q["concept_node_id"] == "node-the-rich-seed-made" for q in rows["quiz_attempts"])
    assert any(e["node_id"] == "node-the-rich-seed-made" for e in rows["node_mastery_events"])


def test_mastery_history_ends_on_todays_score(rows):
    scores = {n["id"]: n["mastery_score"] for n in rows["graph_nodes"]}
    latest: dict[str, dict] = {}
    for attempt in rows["quiz_attempts"]:
        if attempt["completed_at"]:
            held = latest.get(attempt["concept_node_id"])
            if held is None or attempt["completed_at"] > held["completed_at"]:
                latest[attempt["concept_node_id"]] = attempt
    assert latest
    for node_id, attempt in latest.items():
        assert attempt["mastery_after"] == scores[node_id]
    assert {e["node_id"] for e in rows["node_mastery_events"]} <= set(scores)
    this_week = [e for e in rows["node_mastery_events"] if _at(e["created_at"]) > NOW - timedelta(days=7)]
    assert len(this_week) >= 10  # the hub's "+N% this week"


# ── Documents and coursework ─────────────────────────────────────────────────


def test_each_class_has_documents_across_the_term(rows):
    for cls in data.CLASSES:
        docs = [d for d in rows["documents"] if d["offering_id"] == f"off-{cls.key}"]
        assert 8 <= len(docs) <= 12
        categories = Counter(d["category"] for d in docs)
        assert categories["syllabus"] == 1
        assert {"lecture_notes", "slides", "reading", "assignment"} <= set(categories)
        names = {c.name for c in cls.concepts}
        for doc in docs:
            assert {note["name"] for note in doc["concept_notes"]} <= names and doc["concept_notes"]
            assert len(doc["extracted_text"].split("\n\n")) >= 3
            assert _at(doc["created_at"]) < NOW
        created = sorted(_at(d["created_at"]) for d in docs)
        assert created[-1] - created[0] > timedelta(days=60)
        assert len({d["file_name"] for d in docs}) == len(docs)


def test_each_class_has_a_past_exam_one_within_two_weeks_and_one_later(rows):
    today = NOW.date()
    for cls in data.CLASSES:
        work = [a for a in rows["assignments"] if a["enrollment_id"] == f"enr-{cls.key}"]
        away = sorted((date.fromisoformat(a["due_date"]) - today).days
                      for a in work if a["assignment_type"] == "exam")
        assert away[0] < 0 and 0 < away[1] <= 14 and 14 < away[2] <= 30
        assert {"homework", "quiz", "project"} <= {a["assignment_type"] for a in work}
        graded = [a for a in work if a["points_earned"] is not None]
        assert graded and all(date.fromisoformat(a["due_date"]) < today for a in graded)


def test_the_exam_ahead_suggests_the_documents_since_the_exam_before_it(rows):
    # The New study guide modal pre-selects a scope's materials by upload date
    # (services/study_guides/materials.suggest_materials). A quiz counts as an
    # exam there, so none may sit between the two exams.
    today = NOW.date()
    for cls in data.CLASSES:
        work = [a for a in rows["assignments"] if a["enrollment_id"] == f"enr-{cls.key}"]
        scopes = [
            Scope(kind="exam" if is_exam(a) else "assignment", id=a["id"], title=a["title"], due_date=a["due_date"])
            for a in work
        ]
        offered = [
            MaterialOption(id=d["id"], file_name=d["file_name"], category=d["category"], created_at=d["created_at"])
            for d in rows["documents"] if d["offering_id"] == f"off-{cls.key}"
        ]
        ahead = next(s for s in scopes if s.kind == "exam"
                     and 0 < (date.fromisoformat(s.due_date) - today).days <= 14)
        suggested = guide_materials.suggest_materials(offered, ahead, scopes)
        assert 5 <= len(suggested) < len(offered) - 1, cls.key
        past = max((s for s in scopes if s.kind == "exam" and s.due_date < today.isoformat()),
                   key=lambda s: s.due_date)
        assert all(d.created_at[:10] > past.due_date for d in offered if d.id in suggested)
        # The exam already sat has a window of its own, before this one's.
        earlier = guide_materials.suggest_materials(offered, past, scopes)
        assert len(earlier) >= 3 and not set(earlier) & set(suggested)


def test_an_exam_is_an_exam_to_every_reader(rows):
    # The seed files a guide under `exam` or `assignment` by type; the app
    # decides by type AND title (services/exam_proximity.is_exam).
    for cls in data.CLASSES:
        for assessment in cls.assessments:
            row = {"assignment_type": assessment.kind, "title": assessment.title}
            assert is_exam(row) == (assessment.kind in ("exam", "quiz")), assessment.title


# ── Study guides ─────────────────────────────────────────────────────────────


def test_there_are_ten_to_fourteen_guides_and_every_block_type_twice(guides):
    assert 10 <= len(guides) <= 14
    types = Counter(item.type for _, content in guides for item in _items(content))
    assert all(types[block] >= 2 for block in BLOCK_TYPES), types


def test_the_guides_vary_in_everything_a_card_shows(guides):
    rows = [row for row, _ in guides]
    assert {r["scope_kind"] for r in rows} == {"exam", "assignment", "course"}
    assert {r["goal"] for r in rows} == {"practice", "review", "exam_prep"}
    assert {r["depth"] for r in rows} == {"cram", "standard", "deep"}
    assert {r["saved_at"] is None for r in rows} == {True, False}
    assert {r["use_history"] for r in rows} == {True, False}
    assert {r["feedback"] for r in rows} == {None, "yes", "no"}
    assert {len(content.sections) for _, content in guides} == {3, 4, 5, 6, 7, 8}
    made = sorted(_at(r["created_at"]) for r in rows)
    assert made[-1] - made[0] > timedelta(days=21)
    assert len({tuple(s.weight for s in content.sections) for _, content in guides}) >= 8


def test_sections_and_items_are_numbered_as_the_contract_says(guides):
    for row, content in guides:
        assert [s.id for s in content.sections] == [f"s{n}" for n in range(1, len(content.sections) + 1)]
        assert sum(s.weight for s in content.sections) == 100
        assert len(content.sections) <= SECTION_COUNT[row["depth"]]
        assert len(content.takeaways) == 3 and content.deck
        for section in content.sections:
            assert [i.id for i in section.items] == [
                f"{section.id}-i{n}" for n in range(1, len(section.items) + 1)]
            if section.status == "written":
                assert section.items[0].type == "prose" and section.items[0].summary
                assert [i.type for i in section.items].count("check") <= 1
                assert all(i.type != "check" for i in section.items[:-1])


def test_tiers_and_shares_are_the_servers(guides, rows):
    tiers = {(n["course_id"], n["concept_name"]): n["mastery_tier"] for n in rows["graph_nodes"]}
    courses = {f"off-{c.key}": c.course_id for c in data.CLASSES}
    for row, content in guides:
        course = courses[row["offering_id"]]
        expected = [tiers[course, s.concept] if row["use_history"] else "unexplored" for s in content.sections]
        assert [s.tier for s in content.sections] == expected
        assert [s.weight for s in content.sections] == weights(expected, use_history=row["use_history"])


def test_sources_materials_and_concepts_resolve_to_seeded_rows(guides, rows):
    documents = {d["id"]: d for d in rows["documents"]}
    exams = {a["id"]: a for a in rows["assignments"]}
    for row, content in guides:
        source_ids = [s.id for s in content.sources if s.id != QUIZ_HISTORY_SOURCE]
        assert source_ids == [f"document:{doc_id}" for doc_id in row["material_ids"]] and source_ids
        for doc_id, source in zip(row["material_ids"], content.sources):
            assert documents[doc_id]["offering_id"] == row["offering_id"]
            assert source.name == documents[doc_id]["file_name"]
            # A guide cannot be made from a document uploaded after it.
            assert _at(documents[doc_id]["created_at"]) < _at(row["created_at"])
        names = _concept_names(rows, row["offering_id"])
        for section in content.sections:
            assert section.concept in names
            for item in section.items:
                cited = [c for p in getattr(item, "paragraphs", []) for c in p.citations]
                assert set(cited) <= set(source_ids)
                assert getattr(item, "source_id", None) in {None, *source_ids}
                if item.type == "concept_map":
                    assert {node.concept for node in item.nodes} <= names
                if item.type == "check":
                    assert item.concept == section.concept
        assert (row["scope_kind"] == "course") == (row["exam_id"] is None)
        if row["exam_id"]:
            assert exams[row["exam_id"]]["enrollment_id"] == row["offering_id"].replace("off-", "enr-")
            assert content.scope_label == exams[row["exam_id"]]["title"]
            assert (row["scope_kind"] == "exam") == is_exam(exams[row["exam_id"]])
        else:
            assert content.scope_label == "Whole course"


def test_every_written_section_cites_and_no_prose_is_filler(guides):
    for _, content in guides:
        for section in (s for s in content.sections if s.status == "written"):
            prose = [i for i in section.items if i.type == "prose"]
            assert any(p.citations for item in prose for p in item.paragraphs), section.title
            assert all(len(p.text) > 60 for item in prose for p in item.paragraphs)
            # The shortest section there is: an opening and its check.
            assert len(section.items) >= 2


def _server_text(doc: dict) -> str:
    """The document as the app's own reader hands it to a guide's writer."""
    stored = {
        **doc,
        "summary": encrypt_if_present(doc["summary"]),
        "concept_notes": encrypt_json(doc["concept_notes"]),
        "extracted_text": encrypt_if_present(doc["extracted_text"]),
    }
    return guide_materials._unlabelled(stored).text


def test_the_text_the_seed_checks_against_is_the_text_the_app_reads(rows):
    planned = {d["id"]: d for d in rows["documents"]}
    for place in data.placements(NOW, OWNER, _enrolled()):
        for material in place.data.materials:
            doc = planned[place.document_id(material.key)]
            assert material_builder.source_text(place.data, material) == _server_text(doc)


def test_each_chart_is_stored_with_the_verdict_the_server_gives_it(guides, rows):
    texts = {f"document:{d['id']}": _server_text(d) for d in rows["documents"]}
    charts = [(row, item) for row, content in guides for item in _items(content) if item.type == "chart"]
    for row, chart in charts:
        facts = verify.Facts(
            sources={f"document:{i}": texts[f"document:{i}"] for i in row["material_ids"]},
            mistakes=[], concepts=[],
        )
        assert verify.check_block(chart, facts).illustrative == chart.illustrative, chart.title
    plotted = [chart for _, chart in charts if not chart.illustrative]
    assert len({chart.title for chart in plotted}) >= 2 and all(c.source_id for c in plotted)
    assert any(chart.illustrative for _, chart in charts)
    before_after = [c for _, c in charts if any(s.state == "after" for s in c.series)]
    assert before_after and all(c.readouts and c.after_label for c in before_after)


def test_mistakes_carry_the_servers_evidence_and_come_from_seeded_quiz_history(guides, rows):
    digests = {d["concept_node_id"]: d["context_json"] for d in rows["quiz_context"]}
    nodes = {(n["course_id"], n["concept_name"]): n["id"] for n in rows["graph_nodes"]}
    courses = {f"off-{c.key}": c.course_id for c in data.CLASSES}
    seen = 0
    for row, content in guides:
        blocks = [(s, i) for s in content.sections for i in s.items if i.type == "mistakes"]
        if not row["use_history"]:
            assert not blocks and all(s.id != QUIZ_HISTORY_SOURCE for s in content.sources)
            continue
        for section, block in blocks:
            digest = digests[nodes[courses[row["offering_id"]], section.concept]]
            assert digest["common_mistakes"]
            for mistake in block.mistakes:
                assert mistake.evidence == f"From your quizzes on {section.concept}."
                assert mistake.evidence_id.startswith("m") and mistake.fix
                seen += 1
        if blocks:
            assert content.sources[-1].id == QUIZ_HISTORY_SOURCE
    assert seen >= 10


def test_the_states_a_reader_can_be_in_are_all_there(guides, rows):
    generating = [(r, c) for r, c in guides if r["status"] == "generating"]
    assert len(generating) == 1
    row, content = generating[0]
    assert row["generated_at"] is None and _at(row["generating_at"]) == NOW
    assert {s.status for s in content.sections} == {"queued"} and not _items(content)
    assert content.sources and all(s.one_line and s.weight for s in content.sections)

    failed = [(r, s) for r, c in guides for s in c.sections if s.status == "failed"]
    assert len(failed) == 1 and failed[0][0]["status"] == "ready" and not failed[0][1].items

    for row, content in guides:
        if row["status"] == "ready":
            assert row["generated_at"] == row["created_at"] and row["generating_at"] is None
    # A mastered section opens collapsed in the reader.
    assert any(s.tier == "mastered" and s.status == "written" for _, c in guides for s in c.sections)


def test_at_least_two_guides_have_exactly_two_new_lectures(guides, rows):
    new = [len(_new_lectures(rows, row)) for row, _ in guides]
    assert new.count(2) >= 2
    assert new.count(0) >= 3  # and some are up to date
    for row, _ in guides:
        assert not set(_new_lectures(rows, row)) & set(row["material_ids"])


def test_read_marks_and_check_answers_point_at_real_sections_and_checks(guides):
    answered = 0
    for row, content in guides:
        assert set(row["read_sections"]) <= {s.id for s in content.sections if s.status == "written"}
        checks = {i.id: i for i in _items(content) if i.type == "check"}
        for block_id, answer in (row["answers"] or {}).items():
            check = checks[block_id]
            assert answer["option_id"] in {o.id for o in check.options}
            assert answer["correct"] == (answer["option_id"] == check.correct_id)
            answered += 1
    assert answered >= 2 and sum(bool(r["read_sections"]) for r, _ in guides) >= 3
    picks = [a["correct"] for r, _ in guides for a in (r["answers"] or {}).values()]
    assert True in picks and False in picks


def test_check_questions_can_be_answered(guides):
    for _, content in guides:
        for check in (i for i in _items(content) if i.type == "check"):
            ids = [o.id for o in check.options]
            assert 3 <= len(ids) <= 4 and len(set(ids)) == len(ids)
            assert check.correct_id in ids and check.explain_correct and check.explain_incorrect


def test_the_pre_redesign_guide_upgrades_on_read(rows):
    old = [r for r in rows["study_guides"] if r["format"] == guide_builder.LEGACY_FORMAT]
    assert len(old) == 1
    row = old[0]
    assert set(row["content"]) == {"exam", "due_date", "overview", "topics"}
    upgraded = legacy.content_from_topics(row["content"])
    assert len(upgraded.sections) == len(row["content"]["topics"]) >= 3
    assert upgraded.deck and all(s.items for s in upgraded.sections)
    assert row["material_ids"] == [] and row["exam_id"] and row["scope_kind"] == "exam"


# ── How much there is to read, and where ─────────────────────────────────────
#
# Read mode is the full written guide and Skim swaps each passage for a line or
# two. The seeded guides once had so little prose that the two looked alike,
# and their blocks stood back to back. These hold every one of them to what the
# section writer is asked for (`agents/study_guide.py`, "CHOOSING BLOCKS" and
# "GOAL AND DEPTH"), so neither can come back.

#: A Skim summary is a sentence or two: about this many words.
SUMMARY_WORDS = (8, 30)


def _words(text: str | None) -> int:
    return len((text or "").split())


def _passage_words(item) -> int:
    return sum(_words(p.text) for p in item.paragraphs)


def _passages(section) -> list:
    return [item for item in section.items if item.type == "prose"]


def _prose_words(section) -> int:
    return sum(_passage_words(item) for item in _passages(section))


def _written(guides):
    """(depth, section) of every written section of a finished guide."""
    return [
        (row["depth"], section)
        for row, content in guides if row["status"] == "ready"
        for section in content.sections if section.status == "written"
    ]


def _guide(guides, key: str):
    return next((row, content) for row, content in guides if row["id"].endswith(f"-guide-{key}"))


def test_every_section_has_the_prose_its_depth_asks_for(guides):
    seen = set()
    for depth, section in _written(guides):
        mastered = section.tier == "mastered"
        fewest, most = mastered_words(depth) if mastered else SECTION_WORDS[depth]
        assert fewest <= _prose_words(section) <= most, (depth, section.tier, section.title)
        # A mastered section is a refresher, in fewer passages than the rest.
        low, high = SECTION_PASSAGES[depth]
        assert (1 if mastered else low) <= len(_passages(section)) <= high, (depth, section.title)
        seen.add((depth, mastered))
    assert seen >= {(depth, False) for depth in SECTION_WORDS} | {("cram", True), ("deep", True)}


def test_a_weaker_concept_gets_more_to_read(guides):
    for _, content in ((r, c) for r, c in guides if r["status"] == "ready"):
        by_tier = {
            tier: [_prose_words(s) for s in content.sections if s.tier == tier and s.status == "written"]
            for tier in TIERS
        }
        rest = by_tier["struggling"] + by_tier["learning"] + by_tier["unexplored"]
        if by_tier["mastered"] and rest:
            assert max(by_tier["mastered"]) < min(rest), content.title
        if by_tier["struggling"] and by_tier["learning"]:
            assert min(by_tier["struggling"]) > max(by_tier["learning"]), content.title


def test_no_paragraph_is_a_caption_and_every_section_opens_with_two(guides):
    for depth, section in _written(guides):
        opening = section.items[0]
        assert opening.type == "prose" and len(opening.paragraphs) >= 2, section.title
        for item in _passages(section):
            assert all(_words(p.text) >= PARAGRAPH_FLOOR for p in item.paragraphs), (section.title, item.id)


def test_no_two_blocks_touch_and_each_is_led_in_by_a_real_paragraph(guides):
    # Explain, then show or test: a block never follows another block, and
    # what stands before it is prose of at least one full paragraph.
    blocks = 0
    for depth, section in _written(guides):
        for before, item in zip([None, *section.items], section.items):
            if item.type == "prose":
                continue
            blocks += 1
            assert before is not None and before.type == "prose", (section.title, item.id)
            assert _passage_words(before) >= PARAGRAPH_FLOOR, (section.title, item.id)
        # A passage of its own for every block: never more blocks than
        # passages, nor than the section's depth allows.
        count = sum(i.type != "prose" for i in section.items)
        assert count <= len(_passages(section)) and count <= SECTION_BLOCKS[depth], section.title
    assert blocks >= 100


def test_the_check_closes_every_section_after_prose_that_sums_up(guides):
    for depth, section in _written(guides):
        *_, closing, check = section.items
        assert check.type == "check" and closing.type == "prose", section.title
        assert [i.type for i in section.items].count("check") == 1
        # A section short enough to open straight onto its check sums up there.
        if len(section.items) > 2:
            assert closing.paragraphs[-1].text.count("should now be able to") == 1, section.title


def test_skim_has_a_short_line_for_every_passage(guides):
    fewest, most = SUMMARY_WORDS
    for depth, section in _written(guides):
        for item in _passages(section):
            # One or two short sentences, at most a third of what they stand for.
            assert fewest <= _words(item.summary) <= most, (section.title, item.id)
            assert _words(item.summary) * 3 <= _passage_words(item), (section.title, item.id)
            assert item.summary.count(". ") <= 1, (section.title, item.id)
            assert "**" not in item.summary and "`" not in item.summary, item.id
        skim = sum(_words(item.summary) for item in _passages(section))
        assert skim * 3 <= _prose_words(section), section.title


def test_in_skim_too_a_sentence_stands_between_every_pair_of_blocks(guides):
    # Skim shows a passage's summary in its place and hides a passage that
    # has none, so walk the section as Skim draws it.
    for depth, section in _written(guides):
        shown = [item for item in section.items if item.type != "prose" or item.summary]
        assert shown[0].type == "prose", section.title
        for before, item in zip(shown, shown[1:]):
            assert item.type == "prose" or before.type == "prose", (section.title, item.id)


def test_the_model_guide_is_what_a_standard_guide_should_read_like(guides, rows):
    # CS101's Midterm 2 guide is the one to open to see the usual output.
    row, content = _guide(guides, "mid2")
    assert (row["depth"], row["goal"], row["status"]) == ("standard", "exam_prep", "ready")
    # Freshly written: up to date, and nothing read, answered or saved yet.
    assert not _new_lectures(rows, row)
    assert (row["saved_at"], row["read_sections"], row["answers"], row["feedback"]) == (None, [], None, None)
    # Four passages and four blocks a section, turn and turn about.
    for section in content.sections:
        assert [item.type == "prose" for item in section.items] == [True, False] * 4, section.title

    blocks = [item for item in _items(content) if item.type != "prose"]
    assert {block.type for block in blocks} == set(BLOCK_TYPES)
    charts = [block for block in blocks if block.type == "chart"]
    assert any(series.state == "after" for chart in charts for series in chart.series)
    assert {chart.illustrative for chart in charts} == {True, False}
    assert all(3 <= len(block.steps) <= 5 for block in blocks if block.type == "worked_example")


# ── Quiz ─────────────────────────────────────────────────────────────────────


def test_there_is_a_month_of_finished_quizzes_in_the_wire_shape(rows):
    done = [a for a in rows["quiz_attempts"] if a["completed_at"]]
    assert 25 <= len(done) <= 40
    assert min(_at(a["completed_at"]) for a in done) < NOW - timedelta(days=25)
    for attempt in rows["quiz_attempts"]:
        asked = attempt["questions_json"]
        assert asked and all(_is_wire_question(q) for q in asked)
        for question in asked:
            texts = [o["text"] for o in question["options"]]
            assert len(texts) == len(set(texts)) == 4
            assert [o["correct"] for o in question["options"]].count(True) == 1
        assert _strip_answer_key(asked)[0].keys() >= {"id", "question", "options"}
    for attempt in done:
        spent = _at(attempt["completed_at"]) - _at(attempt["created_at"])
        assert timedelta(0) < spent <= timedelta(minutes=30)
        assert attempt["total"] == len(attempt["questions_json"]) == len(attempt["answers_json"])
        assert 0 <= attempt["score"] <= attempt["total"]
        assert attempt["mastery_before"] is not None and attempt["abandoned_at"] is None


def test_scores_agree_with_the_stored_answers_and_responses(rows):
    responses = Counter()
    right = Counter()
    for response in rows["quiz_responses"]:
        responses[response["attempt_id"]] += 1
        right[response["attempt_id"]] += response["is_correct"]
    for attempt in rows["quiz_attempts"]:
        by_id = {q["id"]: q for q in attempt["questions_json"]}
        if attempt["completed_at"]:
            graded = sum(
                next(o["correct"] for o in by_id[a["question_id"]]["options"] if o["label"] == a["selected_label"])
                for a in attempt["answers_json"]
            )
            assert graded == attempt["score"] == right[attempt["id"]]
            assert responses[attempt["id"]] == attempt["total"]
        else:
            assert attempt["score"] is None and attempt["answers_json"] is None
            assert 0 < responses[attempt["id"]] < len(attempt["questions_json"])


def test_a_struggling_concept_improves_across_its_quizzes(rows):
    recursion = [a for a in rows["quiz_attempts"]
                 if a["completed_at"] and a["questions_json"][0]["concept_tested"] == "Recursion"]
    scores = [a["score"] for a in sorted(recursion, key=lambda a: a["completed_at"])]
    assert len(scores) >= 3 and scores[-1] > scores[0]


def test_one_quiz_is_waiting_to_be_resumed_and_two_were_abandoned(rows):
    unfinished = [a for a in rows["quiz_attempts"] if not a["completed_at"]]
    waiting = [a for a in unfinished if not a["abandoned_at"]]
    assert len(waiting) == 1 and len(unfinished) == 3
    # Inside the abandon TTL (24h), so the quiz home offers to resume it.
    assert NOW - _at(waiting[0]["created_at"]) < timedelta(hours=1)
    for attempt in unfinished:
        if attempt["abandoned_at"]:
            assert _at(attempt["created_at"]) < _at(attempt["abandoned_at"]) < NOW


def test_quiz_digests_hold_the_mistakes_guides_cite(rows):
    assert len(rows["quiz_context"]) >= 12
    nodes = {n["id"] for n in rows["graph_nodes"]}
    for digest in rows["quiz_context"]:
        context = digest["context_json"]
        assert digest["concept_node_id"] in nodes and context["common_mistakes"]
        assert context["schema_version"] == DIGEST_SCHEMA_VERSION == quizzes.DIGEST_SCHEMA_VERSION
        assert context["recommended_difficulty"] in {"easy", "medium", "hard"}
    assert any(d["context_json"]["weak_areas"] for d in rows["quiz_context"])


# ── Flashcards ───────────────────────────────────────────────────────────────


def test_flashcard_decks_are_named_for_concepts_and_cover_every_review_state(rows):
    cards = rows["flashcards"]
    assert 120 <= len(cards) <= 200
    names = {n["concept_name"] for n in rows["graph_nodes"]}
    assert {c["topic"] for c in cards} <= names
    assert len({(c["topic"], c["front"]) for c in cards}) == len(cards)

    def days_since(card):
        return (NOW - _at(card["last_reviewed_at"])).days

    new = [c for c in cards if c["last_reviewed_at"] is None]
    reviewed = [c for c in cards if c["last_reviewed_at"]]
    assert all(c["times_reviewed"] == 0 and c["last_rating"] is None for c in new)
    assert all(c["times_reviewed"] > 0 and c["last_rating"] in (1, 2, 3) for c in reviewed)
    assert len(new) >= 15
    assert sum(days_since(c) == 0 for c in reviewed) >= 10          # reviewed today
    assert sum(c["last_rating"] == 1 for c in reviewed) >= 10       # forgotten, still learning
    assert sum(days_since(c) >= 10 for c in reviewed) >= 10         # long overdue
    assert sum(c["times_reviewed"] >= 6 for c in reviewed) >= 20    # well worn


def test_saved_sets_name_concepts_that_have_cards_and_exams_that_exist(rows):
    sets = rows["flashcard_sets"]
    assert 6 <= len(sets) <= 10
    topics = {c["topic"] for c in rows["flashcards"]}
    exams = {a["id"] for a in rows["assignments"]}
    for card_set in sets:
        assert card_set["concepts"] and set(card_set["concepts"]) <= topics
        assert set(card_set["options"]) == {"only_due", "shuffle"}
        assert card_set["exam_id"] is None or card_set["exam_id"] in exams
    assert {s["exam_id"] is None for s in sets} == {True, False}
    assert {s["course_id"] for s in sets} == {c.course_id for c in data.CLASSES}


# ── The Study hub ────────────────────────────────────────────────────────────


def _study_days(rows) -> Counter:
    """How many pieces of study land on each local day (quiz, cards, tutor)."""
    stamps = (
        [a["completed_at"] for a in rows["quiz_attempts"] if a["completed_at"]]
        + [c["last_reviewed_at"] for c in rows["flashcards"] if c["last_reviewed_at"]]
        + [m["created_at"] for m in rows["messages"]]
    )
    return Counter(_at(stamp).astimezone(NOW.tzinfo).date() for stamp in stamps)


def test_every_day_of_the_last_week_has_study_time(rows):
    days = _study_days(rows)
    for back in range(7):
        assert days[NOW.date() - timedelta(days=back)] >= 2, back
    assert min(days) <= NOW.date() - timedelta(days=28)  # and a month of history behind it


def test_tutor_sessions_have_messages_that_span_time(rows):
    by_session: dict[str, list[datetime]] = {}
    for message in rows["messages"]:
        by_session.setdefault(message["session_id"], []).append(_at(message["created_at"]))
    assert set(by_session) == {s["id"] for s in rows["sessions"]} and len(by_session) >= 10
    for session in rows["sessions"]:
        times = sorted(by_session[session["id"]])
        assert times[0] == _at(session["started_at"])
        assert times[-1] - times[0] >= timedelta(minutes=10)
    assert {s["ended_at"] is None for s in rows["sessions"]} == {True, False}


def test_nothing_is_dated_in_the_future(rows):
    stamped = {
        "documents": ("created_at", "processed_at"), "quiz_attempts": ("created_at", "completed_at", "abandoned_at"),
        "quiz_responses": ("answered_at",), "quiz_context": ("updated_at",),
        "node_mastery_events": ("created_at",), "flashcards": ("created_at", "last_reviewed_at"),
        "flashcard_sets": ("created_at",), "sessions": ("started_at", "ended_at"),
        "messages": ("created_at",), "study_guides": ("created_at", "generated_at", "saved_at", "generating_at"),
        "graph_nodes": ("last_studied_at",),
    }
    for table_name, columns in stamped.items():
        for row in rows[table_name]:
            for column in columns:
                assert row[column] is None or _at(row[column]) <= NOW, (table_name, column)


def test_a_run_just_after_midnight_keeps_todays_activity_on_today():
    # 00:10: "50 minutes ago" is yesterday. Today's rows must stay on today,
    # and nothing may be dated in the future.
    late = NOW.replace(hour=0, minute=10)
    rows = _plan(now=late)
    days = _study_days(rows)
    assert days[late.date()] >= 5
    stamps = [m["created_at"] for m in rows["messages"]] + [
        a["completed_at"] for a in rows["quiz_attempts"] if a["completed_at"]]
    assert all(_at(s) <= late for s in stamps)


# ── The course outline ───────────────────────────────────────────────────────


def test_each_outline_is_valid_has_four_units_and_links_the_seeded_exams(rows):
    documents = {f"document:{d['id']}" for d in rows["documents"]}
    for place in data.placements(NOW, OWNER, _enrolled()):
        topics = outline.topics(place)
        parsed = TopicOutline.model_validate({"topics": topics})
        units = [t for t in parsed.topics if not t.parent]
        assert len(units) == 4  # the roadmap's columns: as many as it shows across
        assert {t.name for t in parsed.topics if t.parent} == {c.name for c in place.data.concepts}
        exams = {
            a["id"] for a in rows["assignments"]
            if a["enrollment_id"] == place.enrolled.enrollment_id and a["assignment_type"] in ("exam", "quiz")
        }
        linked = {a for t in parsed.topics for a in t.assessment_ids}
        assert linked and linked <= exams
        assert all(set(t.source_ids) <= documents for t in parsed.topics)
        upcoming = {
            a["id"] for a in rows["assignments"]
            if a["id"] in exams and 0 <= (date.fromisoformat(a["due_date"]) - NOW.date()).days <= 30
        }
        # Every exam ahead has concepts to read its readiness from.
        assert {a for a in upcoming if a.rsplit("-", 1)[1] in ("mid2", "exam2", "exam3", "final")} <= linked


def _coverage(place) -> dict[str, set[str]]:
    """Exam id to the names of the concepts the outline links to it."""
    covered: dict[str, set[str]] = {}
    for topic in outline.topics(place):
        for exam_id in topic["assessment_ids"]:
            covered.setdefault(exam_id, set()).add(topic["name"])
    return covered


def test_every_exam_and_quiz_covers_concepts_of_its_own(rows):
    # The Study hub has a tab per exam and quiz, and only the readiness band
    # follows the tab. Two exams with the same coverage are two identical tabs.
    for place in data.placements(NOW, OWNER, _enrolled()):
        concepts = {n["concept_name"] for n in rows["graph_nodes"] if n["course_id"] == place.data.course_id}
        kinds = {
            a["id"]: a["assignment_type"] for a in rows["assignments"]
            if a["enrollment_id"] == place.enrolled.enrollment_id and a["assignment_type"] in ("exam", "quiz")
        }
        covered = _coverage(place)
        assert set(covered) == set(kinds)  # linked under the ids the assignment rows have
        assert all(len(names) >= 2 and names <= concepts for names in covered.values())
        assert len({frozenset(names) for names in covered.values()}) == len(covered)
        # The final is the one that covers everything; a quiz is narrower than any exam.
        assert [exam_id for exam_id, names in covered.items() if names == concepts] == [place.assessment_id("final")]
        quizzes_cover = [len(covered[i]) for i, kind in kinds.items() if kind == "quiz"]
        exams_cover = [len(covered[i]) for i, kind in kinds.items() if kind == "exam"]
        assert max(quizzes_cover) < min(exams_cover), place.data.key


def test_a_quiz_covers_the_concepts_it_names():
    place = next(p for p in data.placements(NOW, OWNER, _enrolled()) if p.data.key == "cs101")
    covered = _coverage(place)
    assert covered[place.assessment_id("quiz1")] == {"Variables and Types", "Control Flow"}
    assert covered[place.assessment_id("quiz2")] == {"Structs", "Linked Lists", "Stacks and Queues"}


def _served(place, rows, monkeypatch) -> dict:
    """The outline as the Study hub gets it: the app's own `present`, over
    the class's seeded rows."""
    monkeypatch.setattr(checklist_service, "page_all", lambda *args, **kwargs: [])
    exams = [
        {key: a[key] for key in ("id", "title", "due_date", "assignment_type")} for a in rows["assignments"]
        if a["enrollment_id"] == place.enrolled.enrollment_id and a["assignment_type"] in ("exam", "quiz")
    ]
    snapshot = {
        "payload": {"sources": [{"id": "course-description", "label": "BU course description"}], "assessments": exams},
        "nodes": [n for n in rows["graph_nodes"] if n["course_id"] == place.data.course_id],
    }
    cache = {"content": encrypt_json({"topics": outline.topics(place)}), "generated_at": NOW.isoformat()}
    scope = {"course": {"id": place.data.course_id}, "enrollment_id": place.enrolled.enrollment_id, "semester": ""}
    return checklist_service.present(scope, snapshot, cache, NOW)


def _band_ids(topics: list[dict], exam_id: str) -> set[str]:
    """The hub's `studyModel.conceptIdsForExam`: the graph node of every
    served topic the outline links to the exam."""
    return {t["node_id"] for t in topics if t["node_id"] and exam_id in t["assessment_ids"]}


def test_each_exam_reaches_the_hub_with_its_own_concepts(monkeypatch):
    # A served topic finds its node by NAME, so a concept the account already
    # had is read under the id it has. An exam already sat (or far ahead) is
    # outside the service's upcoming window, so no topic lists it under
    # `assessments`; the hub reads `assessment_ids`, which names it all the same.
    kept = data.Enrolled("enr-cs101", "off-cs101", nodes={
        "Pointers and Memory": "rich-pointers", "Recursion": "rich-recursion",
    })
    rows = _plan(cs101=kept)
    today = NOW.date()
    for place in data.placements(NOW, OWNER, _enrolled(cs101=kept)):
        node_ids = {n["concept_name"]: n["id"] for n in rows["graph_nodes"] if n["course_id"] == place.data.course_id}
        ahead = [
            a for a in rows["assignments"]
            if a["enrollment_id"] == place.enrolled.enrollment_id and a["assignment_type"] in ("exam", "quiz")
            and 0 <= (date.fromisoformat(a["due_date"]) - today).days <= checklist_service.ASSESSMENT_WINDOW_DAYS
        ]
        assert len(ahead) == 3, place.data.key
        topics = _served(place, rows, monkeypatch)["topics"]
        covered = _coverage(place)
        for exam in ahead:
            want = {node_ids[name] for name in covered[exam["id"]]}
            assert _band_ids(topics, exam["id"]) == want, exam["title"]
        sat = [
            a for a in rows["assignments"]
            if a["id"] in covered and date.fromisoformat(a["due_date"]) < today
        ]
        assert sat, place.data.key
        for exam in sat:
            assert not any(a["id"] == exam["id"] for t in topics for a in t["assessments"]), exam["title"]
            assert _band_ids(topics, exam["id"]) == {node_ids[name] for name in covered[exam["id"]]}, exam["title"]
        if place.data.key == "cs101":
            assert {"rich-pointers", "rich-recursion"} <= _band_ids(topics, place.assessment_id("mid2"))


def test_an_exam_the_account_already_has_is_linked_under_its_own_id():
    had = data.Enrolled("enr-cs101", "off-cs101", exams={"Pop Quiz: Recursion": "rich-pop-quiz", "Other": "rich-other"})
    place = next(p for p in data.placements(NOW, OWNER, _enrolled(cs101=had)) if p.data.key == "cs101")
    covered = _coverage(place)
    assert covered["rich-pop-quiz"] == {"Functions", "Recursion"}
    assert "rich-other" not in covered
    # A class with an earlier exam the account does not have links only its own.
    for place in data.placements(NOW, OWNER, _enrolled()):
        assert all(exam_id.startswith(place.prefix) for exam_id in _coverage(place))

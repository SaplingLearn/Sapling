"""The local study seed (`db/seed_local_study.py`) against an in-memory
database: what it writes is encrypted where the schema says so, a second run
writes the same rows instead of more, rows the account already has keep
their ids, and nothing is written off a local stack.

What the dataset CONTAINS is pinned in `test_local_study_data.py`. That a new
account's first owner seed runs it, once, is in `test_seed_local_rich.py`."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone

import pytest

import db.seed_local_study as seed
import services.topic_checklist_service as checklist_service
from db import local_study_data as data
from db import seed_helpers as h, seed_local_owner as owner_seed
from e2e_oracles import judges
from e2e_oracles.gather import _CIPHERTEXT_MANIFEST
from models.study_guide import GUIDE_FORMAT, GuideContent
from services.encryption import decrypt, decrypt_json, encrypt
from tests.seed_memory_db import MemoryDatabase

NOW = datetime(2026, 11, 12, 15, 30, tzinfo=timezone(timedelta(hours=-5)))
OWNER = "user-personal"
COURSES = {c.course_id: c.key for c in data.CLASSES}


def _enrolled_everywhere() -> dict:
    return {c.key: data.Enrolled(f"enr-{c.key}", f"off-{c.key}") for c in data.CLASSES}


@pytest.fixture
def local_database(monkeypatch):
    """A local account enrolled in the three sample classes, as the rich
    owner seed leaves it. The enrollment lookup and the outline's evidence
    hash are the app's own services, stood in for here."""
    db = MemoryDatabase()
    monkeypatch.setenv("APP_ENV", "local")
    monkeypatch.setenv("SUPABASE_URL", "http://127.0.0.1:54321")
    for module in (seed, h, owner_seed):
        monkeypatch.setattr(module, "table", db.table)
    db.rows["users"] = [{"id": OWNER, "email": encrypt("developer@gmail.com"), "onboarding_completed": True}]
    monkeypatch.setattr(seed, "_scope", lambda owner_id, course_id: {
        "enrollment_id": f"enr-{COURSES[course_id]}", "offering_id": f"off-{COURSES[course_id]}",
    })
    monkeypatch.setattr(
        checklist_service, "build_snapshot",
        lambda owner_id, scope: {"hash": f"hash-of-{scope['enrollment_id']}"},
    )
    return db


def _readable(db: MemoryDatabase) -> dict:
    """Every row with its encrypted columns decrypted (a nonce makes two
    encryptions of one value differ), less the one clock the seed reads."""
    out = {}
    for table_name, rows in db.rows.items():
        out[table_name] = []
        for row in rows:
            plain = dict(row)
            for column in seed._ENCRYPTED_TEXT.get(table_name, ()):
                plain[column] = None if plain[column] is None else decrypt(plain[column])
            for column in seed._ENCRYPTED_JSON.get(table_name, ()):
                plain[column] = None if plain[column] is None else decrypt_json(plain[column])
            if table_name == "topic_checklists":
                plain["content"] = decrypt_json(plain["content"])
                plain.pop("generated_at")
            out[table_name].append(plain)
    return out


def test_apply_writes_every_table_and_reports_what_it_wrote(local_database, capsys):
    written = seed.apply(OWNER, NOW)
    assert set(written) == {*data.TABLES, "topic_checklists"}
    for table_name, count in written.items():
        assert len(local_database.rows[table_name]) == count > 0, table_name
    assert written["topic_checklists"] == len(data.CLASSES)
    report = capsys.readouterr().out
    assert f"owner {OWNER}" in report and "study_guides" in report


def test_every_encrypted_column_is_ciphertext_at_rest(local_database):
    seed.apply(OWNER, NOW)
    checked = set()
    for table_name, pk, column in _CIPHERTEXT_MANIFEST:
        pairs = [(row.get(pk), row[column]) for row in local_database.rows.get(table_name, [])
                 if row.get(column) is not None]
        assert judges.ciphertext_findings(table_name, column, pairs, decrypt) == []
        if pairs and table_name != "users":
            checked.add((table_name, column))
    # Every column the seed says it encrypts was really checked above, and
    # the oracle's manifest names no column of these tables the seed forgot.
    declared = {
        (table_name, column)
        for columns in (seed._ENCRYPTED_TEXT, seed._ENCRYPTED_JSON)
        for table_name, names in columns.items() for column in names
    }
    assert declared | {("topic_checklists", "content")} == checked


def test_what_is_stored_reads_back_as_what_was_planned(local_database):
    seed.apply(OWNER, NOW)
    planned = data.plan(NOW, OWNER, _enrolled_everywhere())
    stored = _readable(local_database)
    for table_name in data.TABLES:
        assert stored[table_name] == planned[table_name], table_name
    guides = [g for g in stored["study_guides"] if g["format"] == GUIDE_FORMAT]
    assert guides and all(GuideContent.model_validate(g["content"]) for g in guides)


def test_a_second_run_writes_the_same_rows_and_no_more(local_database):
    seed.apply(OWNER, NOW)
    first = deepcopy(_readable(local_database))
    writes = len(local_database.writes)
    seed.apply(OWNER, NOW)
    assert _readable(local_database) == first
    assert [verb for _, verb in local_database.writes[writes:] if verb == "insert"] == []


def test_a_run_on_a_later_day_moves_the_same_rows(local_database):
    seed.apply(OWNER, NOW)
    counts = {name: len(rows) for name, rows in local_database.rows.items()}
    before = {r["id"]: r["due_date"] for r in local_database.rows["assignments"]}
    seed.apply(OWNER, NOW + timedelta(days=5))
    assert {name: len(rows) for name, rows in local_database.rows.items()} == counts
    after = {r["id"]: r["due_date"] for r in local_database.rows["assignments"]}
    assert after.keys() == before.keys() and all(after[i] > before[i] for i in before)


def test_the_outline_is_stored_under_the_real_evidence_hash(local_database):
    seed.apply(OWNER, NOW)
    seed.apply(OWNER, NOW)  # a re-run replaces the class's one row
    outlines = local_database.rows["topic_checklists"]
    assert len(outlines) == len(data.CLASSES)
    for row in outlines:
        assert row["input_hash"] == f"hash-of-{row['enrollment_id']}"
        assert decrypt_json(row["content"])["topics"]


def test_rows_the_account_already_has_are_updated_in_place(local_database):
    # As the rich owner seed and the app leave CS101: a concept, a
    # prerequisite, a quiz digest and one recorded answer, under ids of their own.
    waiting = next(a for a in data.plan(NOW, OWNER, _enrolled_everywhere())["quiz_attempts"]
                   if not a["completed_at"] and not a["abandoned_at"])
    local_database.rows["graph_nodes"] = [
        {"id": "rich-variables", "user_id": OWNER, "course_id": "rich-course-cs101",
         "concept_name": "Variables and Types", "mastery_score": 0.1},
        {"id": "rich-controlflow", "user_id": OWNER, "course_id": "rich-course-cs101",
         "concept_name": "Control Flow", "mastery_score": 0.1},
    ]
    local_database.rows["graph_edges"] = [
        {"id": "rich-edge", "user_id": OWNER, "source_node_id": "rich-variables",
         "target_node_id": "rich-controlflow", "relationship_type": "prerequisite"},
    ]
    local_database.rows["quiz_context"] = [
        {"id": "rich-digest", "user_id": OWNER, "concept_node_id": "rich-controlflow",
         "context_json": "old"},
    ]
    local_database.rows["quiz_responses"] = [
        {"id": "from-the-app", "attempt_id": waiting["id"], "question_index": 0, "selected_index": 3},
    ]
    seed.apply(OWNER, NOW)

    cs = [n for n in local_database.rows["graph_nodes"] if n["course_id"] == "rich-course-cs101"]
    assert len({n["concept_name"] for n in cs}) == len(cs)  # none added twice
    by_name = {n["concept_name"]: n for n in cs}
    assert by_name["Control Flow"]["id"] == "rich-controlflow"
    assert by_name["Control Flow"]["mastery_score"] == 0.6
    pair = [e for e in local_database.rows["graph_edges"]
            if (e["source_node_id"], e["target_node_id"]) == ("rich-variables", "rich-controlflow")]
    assert [e["id"] for e in pair] == ["rich-edge"]
    digests = [d for d in local_database.rows["quiz_context"] if d["concept_node_id"] == "rich-controlflow"]
    assert [d["id"] for d in digests] == ["rich-digest"]
    assert decrypt_json(digests[0]["context_json"])["common_mistakes"]
    answers = [r for r in local_database.rows["quiz_responses"]
               if (r["attempt_id"], r["question_index"]) == (waiting["id"], 0)]
    assert [r["id"] for r in answers] == ["from-the-app"] and "is_correct" in answers[0]


def test_a_class_the_account_dropped_is_skipped(local_database, monkeypatch, capsys):
    enrolled_in = {"rich-course-cs101": {"enrollment_id": "enr-cs101", "offering_id": "off-cs101"}}
    monkeypatch.setattr(seed, "_scope", lambda owner_id, course_id: enrolled_in.get(course_id))
    written = seed.apply(OWNER, NOW)
    assert written["topic_checklists"] == 1
    assert {d["offering_id"] for d in local_database.rows["documents"]} == {"off-cs101"}
    assert "not enrolled in rich-course-math210" in capsys.readouterr().out


def test_an_account_in_none_of_the_classes_is_told_what_to_run(local_database, monkeypatch, capsys):
    monkeypatch.setattr(seed, "_scope", lambda owner_id, course_id: None)
    # An ordinary exception: the first owner seed calls apply in a backend
    # thread, where a SystemExit would not be caught as a failed seed.
    with pytest.raises(ValueError, match="seed_local_rich"):
        seed.apply(OWNER, NOW)
    with pytest.raises(SystemExit) as stopped:
        seed.main(["--owner-user-id", OWNER])
    assert stopped.value.code == 1 and "seed_local_rich" in capsys.readouterr().err
    assert local_database.writes == []


def test_apply_prints_nothing_when_asked_not_to_report(local_database, capsys):
    """The first owner seed runs it from the local-seed watcher's thread."""
    written = seed.apply(OWNER, NOW, report=False)
    assert sum(written.values()) > 0
    assert capsys.readouterr().out == ""


# ── Local only ───────────────────────────────────────────────────────────────


@pytest.mark.parametrize("env, url", [
    ("production", "http://127.0.0.1:54321"),
    ("staging", "http://127.0.0.1:54321"),
    ("local", "https://prod.supabase.co"),
    ("local", "https://127.0.0.1.evil.example"),
])
def test_apply_refuses_anything_but_a_local_stack(local_database, monkeypatch, env, url):
    monkeypatch.setenv("APP_ENV", env)
    monkeypatch.setenv("SUPABASE_URL", url)
    with pytest.raises(RuntimeError, match="local"):
        seed.apply(OWNER, NOW)
    assert local_database.writes == [] and local_database.selects == []


def test_the_cli_checks_the_environment_before_it_looks_anyone_up(local_database, monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://prod.supabase.co")
    with pytest.raises(SystemExit, match="not local"):
        seed.main(["--owner-user-id", OWNER])
    monkeypatch.setenv("SUPABASE_URL", "http://127.0.0.1:54321")
    monkeypatch.setenv("APP_ENV", "production")
    with pytest.raises(SystemExit, match="APP_ENV=local"):
        seed.main(["--owner-user-id", OWNER])
    assert local_database.writes == [] and local_database.selects == []


def test_the_cli_needs_an_owner_and_never_defaults_to_a_fixture_account(local_database):
    with pytest.raises(SystemExit):
        seed.main([])
    with pytest.raises(SystemExit):
        seed.main(["--owner-user-id", "nobody"])
    assert local_database.writes == []


def test_the_cli_seeds_the_account_it_is_given(local_database, monkeypatch):
    seeded = []
    monkeypatch.setattr(seed, "apply", lambda owner_id: seeded.append(owner_id))
    seed.main(["--owner-email", " Developer@Gmail.com "])
    seed.main(["--owner-user-id", OWNER])
    assert seeded == [OWNER, OWNER]

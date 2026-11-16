import hashlib
import json
from copy import deepcopy

import pytest

import db.seed_local_rich as rich
import db.seed_local_study as study
from db import local_study_data, seed_helpers as h, seed_local_owner as owner_seed
from e2e_oracles import judges
from e2e_oracles.gather import _CIPHERTEXT_MANIFEST
from models.study_guide import GuideContent
from services.encryption import decrypt, decrypt_json, encrypt
from services import profiles
from tests.seed_memory_db import MemoryDatabase, use_study_seed


def test_guard_refuses_non_local(monkeypatch):
    monkeypatch.setenv("APP_ENV", "local")
    monkeypatch.setenv("SUPABASE_URL", "https://prod.supabase.co")
    with pytest.raises(SystemExit, match="not local"):
        rich._guard_local()


def test_guard_allows_local(monkeypatch):
    monkeypatch.setenv("APP_ENV", "local")
    monkeypatch.setenv("SUPABASE_URL", "http://127.0.0.1:54321")
    rich._guard_local()  # no raise


def test_guard_allows_test_environment(monkeypatch):
    # scripts/e2e-up.sh accepts APP_ENV=test; its rich seed must not abort.
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("SUPABASE_URL", "http://127.0.0.1:54321")
    rich._guard_local()


@pytest.mark.parametrize("url", ["http://localhost:54321", "http://[::1]:54321"])
def test_guard_accepts_other_exact_loopback_hosts(monkeypatch, url):
    monkeypatch.setenv("APP_ENV", "local")
    monkeypatch.setenv("SUPABASE_URL", url)
    rich._guard_local()


@pytest.mark.parametrize("environment", ["production", "staging", "dev", "development", ""])
def test_guard_refuses_non_local_environments(monkeypatch, environment):
    monkeypatch.setenv("APP_ENV", environment)
    monkeypatch.setenv("SUPABASE_URL", "http://127.0.0.1:54321")
    with pytest.raises(SystemExit, match="APP_ENV=local"):
        rich._guard_local()


@pytest.mark.parametrize("url", [
    "https://127.0.0.1.evil.example", "https://localhost.evil.example",
    "https://remote.example/localhost", "http://[invalid", "", "file://localhost/database",
])
def test_guard_rejects_loopback_substrings_and_malformed_urls(monkeypatch, url):
    monkeypatch.setenv("APP_ENV", "local")
    monkeypatch.setenv("SUPABASE_URL", url)
    with pytest.raises(SystemExit, match="not local"):
        rich._guard_local()


def _database(monkeypatch):
    db = MemoryDatabase()
    monkeypatch.setenv("APP_ENV", "local")
    monkeypatch.setenv("SUPABASE_URL", "http://127.0.0.1:54321")
    for module in (rich, h, owner_seed, profiles):
        monkeypatch.setattr(module, "table", db.table)
    db.rows["roles"] = [{"id": "11111111-2222-4333-8444-555555555555", "slug": "admin"}]
    db.rows["users"] = [{
        "id": "user-personal", "email": encrypt("developer@gmail.com"),
        "google_id": "personal", "onboarding_completed": False, "is_approved": True,
    }]
    db.rows["user_profiles"] = [{"user_id": "user-personal", "name": encrypt("Real Developer")}]
    return db


@pytest.fixture
def local_database(monkeypatch):
    """A local account before its first seed, with the study dataset left
    out: these tests pin the rich copy alone. `database_with_study` has both."""
    monkeypatch.setattr(study, "apply", lambda owner_id, **_: {})
    return _database(monkeypatch)


@pytest.fixture
def database_with_study(monkeypatch):
    """The same account, with the real study seed writing to the same database."""
    db = _database(monkeypatch)
    use_study_seed(monkeypatch, db)
    return db


def _seed_personal():
    rich.main(["--owner-email", " Developer@Gmail.com "])


def test_owner_dataset_populates_all_surfaces_and_is_a_true_noop_on_rerun(local_database):
    before_identity = deepcopy(local_database.rows["users"][0])
    before_profile = deepcopy(local_database.rows["user_profiles"][0])
    _seed_personal()
    assert len(local_database.rows["enrollments"]) == 5
    assert len(local_database.rows["graph_nodes"]) == 13
    assert len(local_database.rows["graph_edges"]) == 7
    assert len(local_database.rows["node_mastery_events"]) == 6
    assert len(local_database.rows["documents"]) == 3
    assert len(local_database.rows["course_chunks"]) == 3
    assert len(local_database.rows["notes"]) == 2
    assert len(local_database.rows["quiz_attempts"]) == 3
    assert len(local_database.rows["gradebook_categories"]) == 9
    assert len(local_database.rows["assignments"]) == 11
    assert len(local_database.rows["rooms"]) == 2
    assert local_database.rows["users"][0] == {**before_identity, "onboarding_completed": True}
    assert local_database.rows["user_profiles"][0] == before_profile
    assert not local_database.rows["user_roles"]
    assert all(row["user_id"] == "user-personal" for row in local_database.rows["graph_nodes"])
    assert all(row["visibility"] == "private" and row["uploader_id"] == "user-personal"
               and len(row["embedding"]) == 768 for row in local_database.rows["course_chunks"])
    snapshot = deepcopy(local_database.rows)
    writes = len(local_database.writes)
    _seed_personal()
    assert local_database.rows == snapshot
    assert len(local_database.writes) == writes


def test_owner_chunks_key_on_course_code_and_invite_codes_are_joinable(local_database):
    _seed_personal()
    codes = {row["course_code"] for row in local_database.rows["courses"]}
    # Retrieval filters course_chunks on the course code, never the courses id.
    assert {row["course_id"] for row in local_database.rows["course_chunks"]} <= codes
    # The join route upper-cases the typed code before its exact-match lookup.
    assert all(row["invite_code"] == row["invite_code"].upper() for row in local_database.rows["rooms"])


@pytest.mark.parametrize("database", ["local_database", "database_with_study"])
def test_owner_seed_keeps_oracle_ciphertext_and_foreign_keys_clean(database, request):
    local_database = request.getfixturevalue(database)
    _seed_personal()
    for table_name, pk, column in _CIPHERTEXT_MANIFEST:
        # .get: the database, not the study seed, numbers an outline row.
        pairs = [(row.get(pk), row[column]) for row in local_database.rows[table_name] if row.get(column) is not None]
        assert judges.ciphertext_findings(table_name, column, pairs, decrypt) == []
    references = {
        "enrollments": {"user_id": "users", "offering_id": "course_offerings"},
        "graph_nodes": {"user_id": "users", "course_id": "courses"},
        "graph_edges": {"source_node_id": "graph_nodes", "target_node_id": "graph_nodes"},
        "node_mastery_events": {"node_id": "graph_nodes"},
        "gradebook_categories": {"enrollment_id": "enrollments"},
        "assignments": {"enrollment_id": "enrollments", "category_id": "gradebook_categories"},
        "documents": {"user_id": "users", "offering_id": "course_offerings"},
        "notes": {"user_id": "users", "offering_id": "course_offerings"},
        "course_chunks": {"doc_id": "documents", "uploader_id": "users"},
        "rooms": {"created_by": "users", "owner_id": "users"},
        "room_members": {"room_id": "rooms", "user_id": "users"},
        "room_messages": {"room_id": "rooms", "user_id": "users"},
        "room_summaries": {"room_id": "rooms"},
        "quiz_attempts": {"concept_node_id": "graph_nodes", "user_id": "users"},
        "quiz_context": {"concept_node_id": "graph_nodes", "user_id": "users"},
        "study_guides": {"exam_id": "assignments", "user_id": "users"},
        "sessions": {"offering_id": "course_offerings", "user_id": "users"},
        "messages": {"session_id": "sessions"},
        "quiz_responses": {"attempt_id": "quiz_attempts"},
        "flashcards": {"user_id": "users"},
        "flashcard_sets": {"user_id": "users", "exam_id": "assignments"},
    }
    for child, fields in references.items():
        for field, parent in fields.items():
            parent_ids = {row["id"] for row in local_database.rows[parent]}
            # A null reference is no orphan: a study guide for the whole
            # course has no exam, a study assignment no category.
            orphans = [row.get("id") for row in local_database.rows[child]
                       if row.get(field) is not None and row[field] not in parent_ids]
            assert judges.orphan_findings(f"{child}->{parent}", orphans) == []


def _seeded_guide(db, user_id):
    row = next(r for r in db.rows["study_guides"] if r["user_id"] == user_id)
    return row, GuideContent.model_validate(decrypt_json(row["content"]))


def test_the_seeded_guide_is_a_ready_format_2_guide_with_every_seedable_block(local_database):
    rich.main([])
    row, content = _seeded_guide(local_database, rich.USER_ACTIVE)

    assert row["id"] == rich.GUIDE_CS_MIDTERM
    assert (row["format"], row["status"], row["scope_kind"]) == (2, "ready", "exam")
    assert row.get("saved_at") is None and row.get("answers") is None
    assert [s.id for s in content.sections] == ["s1", "s2", "s3"]
    assert {s.status for s in content.sections} == {"written"}
    assert sum(s.weight for s in content.sections) == 100
    items = [item for s in content.sections for item in s.items]
    assert {item.type for item in items} == {
        "prose", "formula", "worked_example", "comparison", "key_terms", "concept_map", "check"}
    assert all(item.id.startswith(f"{s.id}-i") for s in content.sections for item in s.items)
    assert len({item.id for item in items}) == len(items)
    assert all(item.summary for item in items if item.type == "prose")
    for check in (item for item in items if item.type == "check"):
        assert check.correct_id in {option.id for option in check.options}
        assert check.explain_correct and check.explain_incorrect


def test_the_seeded_guide_names_concepts_and_documents_the_seed_gives_that_user(local_database):
    rich.main([])
    row, content = _seeded_guide(local_database, rich.USER_ACTIVE)
    nodes = {
        n["concept_name"]: n["mastery_tier"] for n in local_database.rows["graph_nodes"]
        if n["user_id"] == rich.USER_ACTIVE and n["course_id"] == rich.COURSE_CS
    }
    items = [item for s in content.sections for item in s.items]

    assert {s.concept: s.tier for s in content.sections} == {
        name: nodes[name] for name in ("Variables and Types", "Control Flow", "Recursion")}
    assert {item.concept for item in items if item.type == "check"} <= set(nodes)
    assert {n.concept for item in items if item.type == "concept_map" for n in item.nodes} <= set(nodes)

    documents = {
        d["id"]: d["file_name"] for d in local_database.rows["documents"]
        if d["user_id"] == rich.USER_ACTIVE and d["offering_id"] == rich.OFF_CS_F25
    }
    assert row["material_ids"] == list(documents) and documents
    assert {s.id: s.name for s in content.sources} == {
        f"document:{doc_id}": name for doc_id, name in documents.items()}
    cited = {c for item in items if item.type == "prose" for p in item.paragraphs for c in p.citations}
    assert cited and cited <= {s.id for s in content.sources}


def test_the_owners_copy_of_the_guide_points_at_the_owners_own_documents(local_database):
    _seed_personal()
    row, content = _seeded_guide(local_database, "user-personal")
    own_documents = {
        d["id"] for d in local_database.rows["documents"]
        if d["user_id"] == "user-personal" and d["offering_id"] == rich.OFF_CS_F25
    }

    assert row["id"] != rich.GUIDE_CS_MIDTERM
    assert set(row["material_ids"]) == own_documents and own_documents
    assert {s.id for s in content.sources} == {f"document:{doc_id}" for doc_id in own_documents}


def test_owner_can_reuse_existing_enrollment_and_concept_without_resetting_them(local_database):
    local_database.rows["enrollments"].append({
        "id": "my-enrollment", "user_id": "user-personal", "offering_id": rich.OFF_CS_F25,
        "nickname": "Keep my nickname",
    })
    local_database.rows["graph_nodes"].append({
        "id": "my-variable", "user_id": "user-personal", "course_id": rich.COURSE_CS,
        "concept_name": "Variables and Types", "mastery_score": 0.99,
    })
    _seed_personal()
    assert local_database.rows["enrollments"][0]["nickname"] == "Keep my nickname"
    assert local_database.rows["graph_nodes"][0]["mastery_score"] == 0.99
    assert any(row["enrollment_id"] == "my-enrollment" for row in local_database.rows["assignments"])
    assert any(row["node_id"] == "my-variable" for row in local_database.rows["node_mastery_events"])


def test_owner_seed_preserves_edits_to_sample_records(local_database):
    _seed_personal()
    assignment = local_database.rows["assignments"][0]
    assignment["title"] = "My revised homework"
    assignment["points_earned"] = encrypt("99")
    note = local_database.rows["notes"][0]
    note["body"] = encrypt("My revised study notes")
    before = deepcopy(local_database.rows)
    local_database.writes.clear()
    _seed_personal()
    assert local_database.rows == before
    assert local_database.writes == []


def test_partial_owner_seed_can_resume_after_a_write_failure(local_database, monkeypatch):
    original_insert = owner_seed.OwnerSeedWriter.insert_if_absent
    failed = False

    def interrupt_once(writer, name, row_id, row):
        nonlocal failed
        if name == "documents" and not failed:
            failed = True
            raise RuntimeError("interrupted")
        return original_insert(writer, name, row_id, row)

    with monkeypatch.context() as context:
        context.setattr(owner_seed.OwnerSeedWriter, "insert_if_absent", interrupt_once)
        with pytest.raises(RuntimeError, match="interrupted"):
            _seed_personal()
    assert local_database.rows["users"][0]["onboarding_completed"] is False
    _seed_personal()
    assert local_database.rows["users"][0]["onboarding_completed"] is True
    assert len(local_database.rows["documents"]) == 3
    assert len(local_database.rows["assignments"]) == 11
    assert len(local_database.rows["graph_nodes"]) == 13


def test_two_owners_get_independent_datasets_and_sample_fixtures_remain_unchanged(local_database):
    rich.main([])
    baseline_nodes = deepcopy([row for row in local_database.rows["graph_nodes"] if row["user_id"] == rich.USER_ACTIVE])
    baseline_assignments = deepcopy(local_database.rows["assignments"])
    _seed_personal()
    local_database.rows["users"].append({"id": "user-second-owner", "onboarding_completed": True})
    rich.main(["--owner-user-id", "user-second-owner"])
    assert [row for row in local_database.rows["graph_nodes"] if row["user_id"] == rich.USER_ACTIVE] == baseline_nodes
    assert all(row in local_database.rows["assignments"] for row in baseline_assignments)
    assert len(local_database.rows["graph_nodes"]) == 39
    assert len(local_database.rows["rooms"]) == 6


@pytest.mark.parametrize("args", [["--owner-email", "missing@gmail.com"], ["--owner-user-id", "missing"]])
def test_missing_owner_fails_before_writing(local_database, args):
    with pytest.raises(SystemExit):
        rich.main(args)
    assert local_database.writes == []


def test_duplicate_email_requires_an_explicit_user_id(local_database):
    local_database.rows["users"].append({"id": "duplicate", "email": encrypt("developer@gmail.com")})
    with pytest.raises(SystemExit):
        _seed_personal()
    assert local_database.writes == []


def test_wrong_encryption_key_fails_before_writing(local_database):
    local_database.rows["users"][0]["email"] = "not-ciphertext"
    with pytest.raises(SystemExit):
        _seed_personal()
    assert local_database.writes == []


def test_cli_refuses_both_owner_options(local_database):
    with pytest.raises(SystemExit):
        rich.main(["--owner-email", "developer@gmail.com", "--owner-user-id", "user-personal"])
    assert local_database.writes == []


def test_cli_checks_environment_before_looking_up_an_owner(local_database, monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")

    def unexpected_database_access(_name):
        pytest.fail("the guard must run before any database access")

    monkeypatch.setattr(owner_seed, "table", unexpected_database_access)
    with pytest.raises(SystemExit, match="APP_ENV=local"):
        _seed_personal()
    assert local_database.writes == []


def test_email_lookup_pages_past_the_postgrest_row_cap(local_database):
    local_database.rows["users"] = [
        {"id": f"a-{i:04d}", "email": encrypt(f"user{i}@example.test")} for i in range(1001)
    ] + local_database.rows["users"]
    assert owner_seed.resolve_owner(email="developer@gmail.com")["id"] == "user-personal"


def test_email_lookup_skips_a_row_encrypted_under_another_key(local_database):
    local_database.rows["users"].insert(0, {"id": "a-stray", "email": "not-ciphertext"})
    assert owner_seed.resolve_owner(email="developer@gmail.com")["id"] == "user-personal"


def test_email_lookup_names_the_key_when_nothing_matches_and_rows_were_unreadable(local_database):
    local_database.rows["users"].insert(0, {"id": "a-stray", "email": "not-ciphertext"})
    with pytest.raises(ValueError, match="ENCRYPTION_KEY"):
        owner_seed.resolve_owner(email="nobody@gmail.com")


def test_owner_room_messages_carry_the_owner_name(local_database):
    _seed_personal()
    mine = [row for row in local_database.rows["room_messages"] if row["user_id"] == "user-personal"]
    assert mine and all(row["user_name"] == "Real Developer" for row in mine)


# ── seed_owner: the callable both the CLI and the local-seed watcher run ────


def test_seed_owner_is_quiet_and_returns_what_it_created(local_database, capsys):
    """The watcher seeds in a backend thread: no stdout summary, a count instead."""
    owner = {"id": "user-personal", "onboarding_completed": False}
    created = rich.seed_owner(owner, report=False)
    assert created > 0
    assert capsys.readouterr().out == ""
    assert local_database.rows["users"][0]["onboarding_completed"] is True
    assert rich.seed_owner({"id": "user-personal", "onboarding_completed": True}, report=False) == 0


def test_seed_owner_counts_only_its_own_run(local_database):
    """h.counts is process-global; a second owner's run must not inherit the first's."""
    local_database.rows["users"].append({"id": "user-other", "onboarding_completed": False})
    rich.seed_owner({"id": "user-personal"}, report=False)
    before = len(local_database.writes)
    second = rich.seed_owner({"id": "user-other"}, report=False)
    inserts = [write for write in local_database.writes[before:] if write[1] == "insert"]
    assert second == len(inserts) > 0


def test_seed_owner_refuses_outside_local_without_exiting(local_database, monkeypatch):
    """A watcher thread must get an exception, never SystemExit."""
    monkeypatch.setenv("SUPABASE_URL", "https://prod.supabase.co")
    with pytest.raises(RuntimeError, match="local"):
        rich.seed_owner({"id": "user-personal"}, report=False)
    assert local_database.writes == []


def test_owner_seed_skips_the_sample_feedback_and_issue_reports(local_database):
    """Those rows exist for the ciphertext oracle's baseline, not as account
    content: on a developer's account they would read as real submissions."""
    _seed_personal()
    assert local_database.rows["feedback"] == []
    assert local_database.rows["issue_reports"] == []


def test_owner_seed_existence_probes_select_only_key_columns(local_database):
    """A probe must not drag back ciphertext or 768-float embeddings."""
    _seed_personal()
    probes = [(name, columns) for name, columns in local_database.selects if columns == "*"]
    assert probes == []
    chunk_probes = {columns for name, columns in local_database.selects if name == "course_chunks"}
    assert chunk_probes == {"id"}


# ── the study dataset: an account's first seed only ─────────────────────────


def _study_rows(db, table_name):
    """The rows the study seed made (it updates a concept the account already
    has under the id it has, so those are not among them)."""
    return [row for row in db.rows[table_name] if str(row.get("id", "")).startswith("study-")]


def test_a_new_owner_gets_the_rich_copy_and_the_study_dataset(database_with_study, capsys):
    db = database_with_study
    before_profile = deepcopy(db.rows["user_profiles"][0])
    created = rich.seed_owner({"id": "user-personal", "onboarding_completed": False}, report=False)

    assert created > 0 and capsys.readouterr().out == ""  # a watcher thread prints nothing
    assert db.rows["users"][0]["onboarding_completed"] is True
    assert db.rows["user_profiles"][0] == before_profile
    # The rich copy is all there, exactly as without the study seed.
    for table_name, rich_rows in {"documents": 3, "assignments": 11, "quiz_attempts": 3,
                                  "flashcards": 6, "study_guides": 1, "sessions": 2}.items():
        made = len(_study_rows(db, table_name))
        assert made > rich_rows, table_name  # the study seed adds far more than the copy has
        assert len(db.rows[table_name]) - made == rich_rows, table_name
    assert len(db.rows["enrollments"]) == 5 and len(db.rows["course_chunks"]) == 3
    # One tree per class: the 13 concepts of the rich copy keep their rows and
    # the study seed's other concepts join them. No name is there twice.
    nodes = db.rows["graph_nodes"]
    assert len(nodes) - len(_study_rows(db, "graph_nodes")) == 13
    assert len({(n["course_id"], n["concept_name"]) for n in nodes}) == len(nodes)
    assert sum(len(c.concepts) for c in local_study_data.CLASSES) == len(nodes)
    # Everything is the account's own, and every class got its outline.
    for table_name in ("graph_nodes", "documents", "quiz_attempts", "flashcards", "study_guides"):
        assert {row["user_id"] for row in db.rows[table_name]} == {"user-personal"}, table_name
    outlines = [row for row in db.rows["topic_checklists"]
                if row["input_hash"] == f"hash-of-{row['enrollment_id']}"]
    assert len(outlines) == len(local_study_data.CLASSES)


def test_a_later_owner_seed_writes_nothing_and_keeps_what_the_developer_changed(database_with_study):
    """The study seed rewrites its rows, so only the first seed may run it."""
    db = database_with_study
    _seed_personal()
    guide = _study_rows(db, "study_guides")[0]
    guide["read_sections"], guide["saved_at"] = ["s1"], "2026-11-12T09:00:00+00:00"
    _study_rows(db, "assignments")[0]["due_date"] = "2027-01-15"
    db.rows["flashcards"].remove(_study_rows(db, "flashcards")[0])
    before = deepcopy(db.rows)
    db.writes.clear()

    _seed_personal()  # the manual command, which reads the account as it now is
    rich.seed_owner(db.rows["users"][0], report=False)  # a watcher pass

    assert db.rows == before
    assert db.writes == []


def test_an_onboarded_account_gets_the_rich_copy_only(local_database, monkeypatch):
    """It may hold the developer's own work, which the study seed would reset;
    `python -m db.seed_local_study` is the explicit way to ask for that."""
    local_database.rows["users"][0]["onboarding_completed"] = True
    monkeypatch.setattr(study, "apply", lambda *_, **__: pytest.fail("the study seed ran"))
    _seed_personal()
    assert len(local_database.rows["documents"]) == 3


def test_a_failing_study_seed_still_completes_the_account_with_one_warning(local_database, monkeypatch, caplog):
    def refused(owner_id, **_):
        raise RuntimeError("Client error '400 Bad Request'\nFor more information check: https://httpstatuses.com/400")

    monkeypatch.setattr(study, "apply", refused)
    with caplog.at_level("WARNING"):
        created = rich.seed_owner({"id": "user-personal", "onboarding_completed": False}, report=False)

    assert created > 0 and len(local_database.rows["documents"]) == 3
    assert local_database.rows["users"][0]["onboarding_completed"] is True
    [warning] = caplog.records
    # One line and no traceback: the E2E logscan oracle reads one as a crash.
    assert warning.levelname == "WARNING" and warning.exc_info is None
    message = warning.getMessage()
    assert "\n" not in message
    assert "user-personal" in message and "RuntimeError: Client error '400 Bad Request'" in message
    assert "python -m db.seed_local_study --owner-user-id user-personal" in message


def test_a_first_seed_that_stopped_before_the_study_dataset_gets_it_on_the_next_run(database_with_study, monkeypatch):
    original_insert = owner_seed.OwnerSeedWriter.insert_if_absent

    def interrupt(writer, name, row_id, row):
        if name == "documents":
            raise RuntimeError("interrupted")
        return original_insert(writer, name, row_id, row)

    with monkeypatch.context() as context:
        context.setattr(owner_seed.OwnerSeedWriter, "insert_if_absent", interrupt)
        with pytest.raises(RuntimeError, match="interrupted"):
            _seed_personal()
    assert database_with_study.rows["study_guides"] == []
    _seed_personal()
    assert database_with_study.rows["users"][0]["onboarding_completed"] is True
    assert _study_rows(database_with_study, "study_guides")


# ── the default dataset: the baseline every other lane asserts on ───────────

#: sha256 of the default dataset, encrypted columns decrypted (see _digest).
BASELINE_DIGEST = "f6cf9ed52bd3ca878dd61cb2b760ad7fa6ead999228d02bfc7bde510e10667e9"


def _digest(db) -> str:
    def plain(value):
        if not isinstance(value, str):
            return value
        try:
            return decrypt(value)  # a nonce makes two encryptions of one value differ
        except Exception:
            return value

    rows = {name: [{key: plain(value) for key, value in row.items()} for row in table_rows]
            for name, table_rows in sorted(db.rows.items())}
    return hashlib.sha256(json.dumps(rows, sort_keys=True).encode()).hexdigest()


def test_the_default_dataset_is_unchanged_and_never_runs_the_study_seed(monkeypatch):
    """The `rich-*` accounts are what the E2E journeys, the oracles and the
    integration suite assert on, row for row. If this fails because the
    dataset was changed on purpose, check those lanes, then update the digest."""
    db = _database(monkeypatch)
    db.rows["users"], db.rows["user_profiles"] = [], []  # no developer account: the fixtures only
    monkeypatch.setattr(study, "apply", lambda *_, **__: pytest.fail("the study seed ran"))
    rich.main([])
    assert not any(str(row.get("id", "")).startswith("study-") for rows in db.rows.values() for row in rows)
    assert _digest(db) == BASELINE_DIGEST

from copy import deepcopy

import pytest

import db.seed_local_rich as rich
from db import seed_helpers as h, seed_local_owner as owner_seed
from e2e_oracles import judges
from e2e_oracles.gather import _CIPHERTEXT_MANIFEST
from services.encryption import decrypt, encrypt
from services import profiles
from tests.seed_memory_db import MemoryDatabase


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


@pytest.fixture
def local_database(monkeypatch):
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


def test_owner_seed_keeps_oracle_ciphertext_and_foreign_keys_clean(local_database):
    _seed_personal()
    for table_name, pk, column in _CIPHERTEXT_MANIFEST:
        pairs = [(row[pk], row[column]) for row in local_database.rows[table_name] if row.get(column) is not None]
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
    }
    for child, fields in references.items():
        for field, parent in fields.items():
            parent_ids = {row["id"] for row in local_database.rows[parent]}
            orphans = [row.get("id") for row in local_database.rows[child] if row[field] not in parent_ids]
            assert judges.orphan_findings(f"{child}->{parent}", orphans) == []


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
    # 13 rich-user-active nodes + 13 per owner, plus the learning-loop fixture's
    # nodes for its two loop users (the no-flag seed only; owners never get them).
    assert len(local_database.rows["graph_nodes"]) == 39 + len(rich.LOOP_USERS) * len(rich.LOOP_NODES)
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


# ── PKG-14 final fix round: seeded tiers follow the launch cuts (A95) ────────


def _seeded_graph_nodes(monkeypatch) -> list[dict]:
    """Every graph_nodes row the rich seed writes (seed_graph + the loop users),
    captured at the helper seam — no database."""
    from unittest.mock import MagicMock

    rows: list[dict] = []

    def upsert(name, row, **kw):
        if name == "graph_nodes":
            rows.append(dict(row))

    monkeypatch.setattr(rich.h, "upsert", upsert)
    monkeypatch.setattr(rich.h, "insert_if_absent", lambda *a, **k: None)
    monkeypatch.setattr(rich, "table", lambda name: MagicMock(select=MagicMock(return_value=[])))
    rich.seed_graph()
    try:
        rich.seed_learning_loop()
    except Exception:  # noqa: BLE001 — only its graph_nodes upserts matter here
        pass
    return rows


def test_every_seeded_tier_is_tier_for_its_score(monkeypatch):
    from learning.bkt import tier_for

    rows = _seeded_graph_nodes(monkeypatch)
    assert rows, "the seed writes no graph_nodes rows"
    for row in rows:
        assert row["mastery_tier"] == tier_for(row["mastery_score"]), row["id"]


def test_the_seeded_student_covers_every_tier(monkeypatch):
    """frontend/e2e/graph.spec.ts's journey guard: the rich seed has a node in
    EVERY tier for rich-user-active — after the launch cuts (mastered ≥ 0.95)."""
    from learning.bkt import tier_for

    tiers = {
        tier_for(score)
        for nodes in rich._GRAPH_NODES.values()
        for _id, _name, score in nodes
    }
    assert tiers == {"mastered", "learning", "struggling", "unexplored"}
    active = [r for r in _seeded_graph_nodes(monkeypatch) if r["user_id"] == rich.USER_ACTIVE]
    assert {r["mastery_tier"] for r in active} == tiers

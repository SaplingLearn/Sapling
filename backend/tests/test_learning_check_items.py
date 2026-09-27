"""PKG-04 check items: params, migration invariants, models, service, agent
plumbing, route hook, backfill. Spec §3.4, §3.5, §4, §8.6/8.9/8.12, §13 A2/A22/A23."""

from __future__ import annotations

import json
import pathlib
import re
from unittest.mock import MagicMock, patch

import pytest

MIG_DIR = pathlib.Path(__file__).resolve().parents[1] / "db" / "migrations"


def _migration() -> str:
    hits = sorted(MIG_DIR.glob("*_learning_check_items.sql"))
    assert len(hits) == 1, f"expected exactly one learning_check_items migration, got {hits}"
    return hits[0].read_text()


class TestParams:
    def test_constants_match_spec(self):
        from learning import params

        assert params.CHECK_ITEM_FORMATS == ("free", "teachback", "mc_reason")
        assert params.CHECK_ITEM_DIFFICULTIES == (1, 2, 3)
        assert params.CHECK_ITEM_MIN_RUBRIC == 2
        assert params.CHECK_ITEM_MIN_WRONG == 1
        assert params.CHECK_ITEM_MAX_CHUNKS == 8
        assert params.CHECK_ITEM_MAX_CONCEPTS_PER_DOC == 10
        assert params.CHECK_ITEM_OUTPUT_RETRIES == 2
        assert isinstance(params.CHECK_HASH_VERSION, str) and params.CHECK_HASH_VERSION
        assert params.CHECK_ITEM_CONCEPTS_PER_CALL == 3
        assert params.FLEX_TIMEOUT_S == 900
        assert params.CHECK_ITEM_ANSWER_KINDS == ("free", "numeric")
        assert params.CHECK_ITEM_STEPWISE_MIN_STEPS >= 2
        assert params.CHECK_ITEM_FLEX_RETRIES >= 0
        assert params.CHECK_ITEM_BACKFILL_MIN_CHUNK_SCORE == 1

    def test_initial_set_is_every_pair_and_covers_its_consumers(self):
        from learning import params

        pairs = len(params.CHECK_ITEM_FORMATS) * len(params.CHECK_ITEM_DIFFICULTIES)
        assert params.CHECK_ITEM_INITIAL_PER_CONCEPT == pairs == 9
        # §3.5: >= PROBE_ITEMS_PER_SKILL_MAX + 2 isomorphs + 1 post-test reserve
        assert params.CHECK_ITEM_INITIAL_PER_CONCEPT >= params.PROBE_ITEMS_PER_SKILL_MAX + 2 + 1


class TestMigration:
    def test_prefix_is_a_utc_timestamp_and_header_names_the_package(self):
        hits = sorted(MIG_DIR.glob("*_learning_check_items.sql"))
        assert hits, "no learning_check_items migration"
        name = hits[0].name
        assert re.fullmatch(r"\d{14}_learning_check_items\.sql", name), name
        assert "PKG-04" in _migration()

    def test_unique_is_on_course_concept_and_question_hash_only(self):
        sql = _migration()
        uniques = [ln for ln in sql.splitlines() if "UNIQUE" in ln.upper()]
        assert uniques == ["  UNIQUE (course_id, concept_key, question_hash)"], uniques

    def test_items_are_course_assets_with_no_graph_nodes_fk(self):
        sql = _migration()
        assert "REFERENCES" not in sql.upper()
        assert not re.search(r"^\s*node_id\s", sql, re.M), "A2: no node_id column"

    def test_format_difficulty_and_answer_kind_are_check_constrained(self):
        from learning.params import (
            CHECK_ITEM_ANSWER_KINDS,
            CHECK_ITEM_DIFFICULTIES,
            CHECK_ITEM_FORMATS,
        )

        sql = _migration()
        enum = ",".join(f"'{f}'" for f in CHECK_ITEM_FORMATS)
        assert f"CHECK (format IN ({enum}))" in sql
        lo, hi = min(CHECK_ITEM_DIFFICULTIES), max(CHECK_ITEM_DIFFICULTIES)
        assert f"CHECK (difficulty BETWEEN {lo} AND {hi})" in sql
        kinds = ",".join(f"'{k}'" for k in CHECK_ITEM_ANSWER_KINDS)
        assert f"CHECK (answer_kind IN ({kinds}))" in sql

    def test_a22_and_a17_columns_have_safe_defaults(self):
        sql = _migration()
        for col in ("options_json", "correct_option", "canonical_answer", "tolerance"):
            assert re.search(rf"^\s*{col}\s", sql, re.M), col
        assert re.search(r"answer_kind\s+text NOT NULL DEFAULT 'free'", sql)
        assert re.search(r"canonical_verified\s+boolean NOT NULL DEFAULT false", sql)
        assert re.search(r"stepwise\s+boolean NOT NULL DEFAULT false", sql)

    def test_a23_and_a32_columns(self):
        sql = _migration()
        assert re.search(r"source_document_ids\s+text\[\] NOT NULL DEFAULT '\{\}'", sql)
        assert re.search(r"graded\s+boolean NOT NULL DEFAULT false", sql)
        assert (
            "CREATE INDEX IF NOT EXISTS check_items_source_docs_idx "
            "ON check_items USING gin (source_document_ids)"
        ) in sql

    def test_idempotent_and_indexed(self):
        sql = _migration()
        assert "CREATE TABLE IF NOT EXISTS check_items" in sql
        assert (
            "CREATE INDEX IF NOT EXISTS check_items_concept_idx "
            "ON check_items (course_id, concept_key, format, difficulty)"
        ) in sql


# ── learning/checks.py ─────────────────────────────────────────────────────


def _draft(**over):
    from learning.checks import CheckItemDraft

    base = dict(
        concept="Learning Rate",
        format="free",
        difficulty=1,
        prompt="In one sentence, what does the learning rate control?",
        reference_answer="The size of each update step along the negative gradient.",
        rubric=["Names the step size.", "Ties it to the gradient direction."],
        wrong_keys=["rate_is_iterations"],
        wrong_texts=["Confuses the rate with the number of iterations."],
        chunk_ids=["c1"],
    )
    base.update(over)
    return CheckItemDraft(**base)


def _mc_draft(**over):
    base = dict(
        format="mc_reason",
        prompt="Which quantity does the learning rate scale? Pick one and give your reason.",
        reference_answer="A: it scales each step taken along the negative gradient.",
        wrong_keys=["rate_is_iterations", "rate_is_loss", "rate_is_sign"],
        wrong_texts=[
            "Counts iterations.",
            "Treats the rate as the loss.",
            "Thinks it flips the sign.",
        ],
        option_letters=["A", "B", "C", "D"],
        option_texts=[
            "The update step size",
            "The iteration count",
            "The loss value",
            "The gradient sign",
        ],
        option_wrong_keys=["", "rate_is_iterations", "rate_is_loss", "rate_is_sign"],
        correct_option="A",
    )
    base.update(over)
    return _draft(**base)


def _item(**over):
    from learning.checks import CheckItem, RubricItem, WrongReason, question_hash

    prompt = over.pop("prompt", "What is a base case?")
    base = dict(
        id=over.pop("id", "i1"),
        course_id="c1",
        concept_key="recursion",
        document_id="d1",
        format="free",
        difficulty=1,
        prompt=prompt,
        reference_answer="The condition that stops recursion.",
        rubric=[RubricItem(id="r1", text="stops"), RubricItem(id="r2", text="condition")],
        common_wrong=[WrongReason(key="no_stop", text="thinks recursion never stops")],
        source_chunk_ids=[],
        question_hash=question_hash(prompt),
        created_at=None,
    )
    return CheckItem(**{**base, **over})


class TestQuestionHash:
    def test_stable_and_presentation_insensitive(self):
        from learning.checks import question_hash

        a = question_hash("What  is\na Base Case?")
        assert a == question_hash("what is a base case?")
        assert re.fullmatch(r"[0-9a-f]{64}", a)

    def test_content_sensitive(self):
        from learning.checks import question_hash

        assert question_hash("What is a base case?") != question_hash("What is a recursive case?")

    def test_version_tag_is_part_of_identity_and_item_id_is_course_keyed(self, monkeypatch):
        from learning import checks

        before = checks.question_hash("x")
        monkeypatch.setattr(checks, "CHECK_HASH_VERSION", "v999")
        assert checks.question_hash("x") != before
        assert checks.item_id("c1", "k1", "h") == checks.item_id("c1", "k1", "h")
        assert checks.item_id("c1", "k1", "h") != checks.item_id("c1", "k2", "h")
        assert checks.item_id("c1", "k1", "h") != checks.item_id("c2", "k1", "h")

    def test_not_the_quiz_identity(self):
        """A deliberate copy of quiz_identity's normalization, versioned apart."""
        from learning.checks import normalize, question_hash
        from services import quiz_identity

        assert normalize("  A\tB  ") == quiz_identity.normalize_text("  A\tB  ") == "a b"
        assert question_hash("What is x?") != quiz_identity.question_hash("What is x?", [])


class TestSelectItem:
    def test_exact_format_and_difficulty_first(self):
        from learning.checks import select_item

        items = [
            _item(id="a", difficulty=2, prompt="p-a"),
            _item(id="b", difficulty=1, prompt="p-b"),
        ]
        assert select_item(items, format="free", difficulty=1).id == "b"

    def test_nearest_difficulty_lower_wins_ties(self):
        from learning.checks import select_item

        items = [
            _item(id="hi", difficulty=3, prompt="p-hi"),
            _item(id="lo", difficulty=1, prompt="p-lo"),
        ]
        assert select_item(items, format="free", difficulty=2).id == "lo"

    def test_ties_at_the_exact_difficulty_break_on_created_at_then_id(self):
        from learning.checks import select_item

        items = [
            _item(id="z", prompt="p-z", created_at="2026-09-02T00:00:00Z"),
            _item(id="y", prompt="p-y", created_at="2026-09-01T00:00:00Z"),
            _item(id="x", prompt="p-x", created_at="2026-09-01T00:00:00Z"),
        ]
        assert select_item(items, format="free", difficulty=1).id == "x"

    def test_never_substitutes_format_and_honours_exclusions(self):
        from learning.checks import question_hash, select_item

        items = [_item(id="tb", format="teachback", prompt="p-tb"), _item(id="fr", prompt="p-fr")]
        assert select_item(items, format="mc_reason", difficulty=1) is None
        assert (
            select_item(items, format="free", difficulty=1, exclude_hashes={question_hash("p-fr")})
            is None
        )


class TestPosttestReserve:
    def test_lowest_hash_among_free_items_at_the_middle_difficulty(self):
        from learning.checks import posttest_reserve_hash
        from learning.params import CHECK_ITEM_DIFFICULTIES

        mid = CHECK_ITEM_DIFFICULTIES[1]
        items = [_item(id=f"f{i}", difficulty=mid, prompt=f"free {i}") for i in range(3)]
        items += [
            _item(id="tb", format="teachback", difficulty=mid, prompt="tb"),
            _item(id="lo", difficulty=CHECK_ITEM_DIFFICULTIES[0], prompt="other difficulty"),
        ]
        want = min(i.question_hash for i in items if i.format == "free" and i.difficulty == mid)
        assert posttest_reserve_hash(items) == want

    def test_falls_back_to_the_lowest_hash_overall_then_none(self):
        from learning.checks import posttest_reserve_hash

        items = [
            _item(id="a", difficulty=1, prompt="a"),
            _item(id="b", format="teachback", difficulty=2, prompt="b"),
        ]
        assert posttest_reserve_hash(items) == min(i.question_hash for i in items)
        assert posttest_reserve_hash([]) is None


class TestValidateDraft:
    def test_valid_drafts_have_no_reasons(self):
        from learning.checks import validate_draft

        assert validate_draft(_draft()) == []
        assert validate_draft(_mc_draft()) == []
        assert validate_draft(_draft(answer_kind="numeric", canonical_answer="0.01")) == []
        assert (
            validate_draft(_draft(answer_kind="numeric", canonical_answer="3", tolerance="0.5"))
            == []
        )
        steps = "1. Compute the gradient.\n2) Step against it by the rate."
        assert validate_draft(_draft(stepwise=True, reference_answer=steps)) == []

    @pytest.mark.parametrize(
        "over,reason",
        [
            ({"format": "mc"}, "format"),
            ({"difficulty": 4}, "difficulty"),
            ({"rubric": ["only one"]}, "rubric"),
            ({"wrong_keys": [], "wrong_texts": []}, "wrong"),
            ({"wrong_keys": ["k", "k"], "wrong_texts": ["a", "b"]}, "wrong"),
            ({"wrong_keys": ["k"], "wrong_texts": []}, "wrong"),
            ({"reference_answer": "   "}, "reference"),
            ({"prompt": "  "}, "prompt"),
            ({"answer_kind": "symbolic"}, "answer_kind"),
            ({"answer_kind": "numeric", "canonical_answer": "about three"}, "canonical"),
            ({"answer_kind": "numeric", "canonical_answer": ""}, "canonical"),
            ({"answer_kind": "numeric", "canonical_answer": "nan"}, "canonical"),
            (
                {"answer_kind": "numeric", "canonical_answer": "3.0", "tolerance": "-0.1"},
                "tolerance",
            ),
            (
                {"answer_kind": "numeric", "canonical_answer": "3.0", "tolerance": "wide"},
                "tolerance",
            ),
            ({"stepwise": True}, "stepwise"),
        ],
    )
    def test_each_rule_names_itself(self, over, reason):
        from learning.checks import validate_draft

        reasons = validate_draft(_draft(**over))
        assert any(reason in r for r in reasons), reasons

    @pytest.mark.parametrize(
        "over",
        [
            {"option_texts": ["only", "three", "texts"]},
            {"correct_option": "E"},
            {"option_letters": ["A", "A", "C", "D"]},
            {"option_wrong_keys": ["", "rate_is_iterations", "not_listed", "rate_is_sign"]},
            {"option_wrong_keys": ["", "", "rate_is_loss", "rate_is_sign"]},
        ],
    )
    def test_mc_reason_needs_one_correct_option_and_keyed_distractors(self, over):
        from learning.checks import validate_draft

        assert any("option" in r for r in validate_draft(_mc_draft(**over)))

    def test_option_and_numeric_fields_are_ignored_where_they_do_not_apply(self):
        from learning.checks import validate_draft

        # free answer kind: canonical/tolerance ignored; non-mc format: options ignored.
        assert validate_draft(_draft(canonical_answer="junk", tolerance="-1")) == []
        assert validate_draft(_draft(option_letters=["A"], correct_option="Z")) == []

    def test_leak_is_rejected_and_unknown_chunk_ids_are_dropped(self):
        from learning.checks import clean_chunk_ids, leak_in_prompt, validate_draft

        d = _draft(
            prompt="Explain why the size of each update step along the negative gradient matters."
        )
        assert leak_in_prompt(d.prompt, d.reference_answer)
        assert any("leak" in r for r in validate_draft(d))
        assert not leak_in_prompt("anything", "   ")
        assert clean_chunk_ids(
            _draft(chunk_ids=["c2", "zz", "c1", "c2"]), allowed={"c1", "c2"}
        ) == [
            "c2",
            "c1",
        ]


class TestRankChunks:
    def test_token_overlap_then_chunk_index(self):
        from learning.checks import rank_chunks_for_concept

        chunks = [
            {"id": "a", "chunk_index": 2, "chunk_text": "The learning rate sets the step size."},
            {"id": "b", "chunk_index": 0, "chunk_text": "Unrelated prose about syllabus dates."},
            {
                "id": "c",
                "chunk_index": 1,
                "chunk_text": "Learning rate: a rate that scales the gradient.",
            },
        ]
        ranked = rank_chunks_for_concept("Learning Rate", chunks, limit=2)
        assert [c["id"] for c in ranked] == ["c", "a"]

    def test_min_score_drops_unrelated_chunks(self):
        from learning.checks import rank_chunks_for_concept

        chunks = [
            {"id": "a", "chunk_index": 0, "chunk_text": "photosynthesis in leaves"},
            {"id": "b", "chunk_index": 1, "chunk_text": "gradient descent steps downhill"},
        ]
        assert [c["id"] for c in rank_chunks_for_concept("Gradient Descent", chunks, limit=8)] == [
            "b",
            "a",
        ]
        assert [
            c["id"]
            for c in rank_chunks_for_concept("Gradient Descent", chunks, limit=8, min_score=1)
        ] == ["b"]

    def test_short_names_match_as_a_whole_word(self):
        from learning.checks import rank_chunks_for_concept

        chunks = [
            {"id": "a", "chunk_index": 0, "chunk_text": "The constant pi appears here."},
            {"id": "b", "chunk_index": 1, "chunk_text": "A spinning top."},
        ]
        assert [c["id"] for c in rank_chunks_for_concept("Pi", chunks, limit=8, min_score=1)] == [
            "a"
        ]


# ── services/check_item_service.py ─────────────────────────────────────────


def _cached_tables(data: dict):
    mocks: dict = {}

    def factory(name):
        if name not in mocks:
            rows = data.get(name, [])
            m = MagicMock()
            m.select.return_value = rows
            m.select_with_count.return_value = (rows, len(rows))  # db.connection.page_all
            m.upsert.return_value = []
            m.delete.return_value = []
            mocks[name] = m
        return mocks[name]

    return factory, mocks


def _doc(**over):
    from services.encryption import encrypt_if_present

    return {
        "id": "doc-1",
        "user_id": "u1",
        "shareability": "course_material",
        "shareability_confidence": 0.9,
        "extracted_text": encrypt_if_present("plain body"),
        **over,
    }


class TestCreateItems:
    def test_encrypts_at_write_and_hashes_plaintext(self):
        from learning.checks import item_id, question_hash
        from services import check_item_service as svc
        from services.encryption import decrypt_if_present

        factory, mocks = _cached_tables({})
        with patch("services.check_item_service.table", side_effect=factory):
            ids = svc.create_items(
                "course-1", "learning rate", "doc-1", [_draft()], allowed_chunk_ids={"c1"}
            )

        upsert = mocks["check_items"].upsert
        upsert.assert_called_once()
        rows, kwargs = upsert.call_args[0][0], upsert.call_args[1]
        assert kwargs == {"on_conflict": "course_id,concept_key,question_hash"}
        row = rows[0]
        assert (
            ids
            == [row["id"]]
            == [item_id("course-1", "learning rate", question_hash(_draft().prompt))]
        )
        assert (
            row["course_id"] == "course-1"
            and row["concept_key"] == "learning rate"
            and "node_id" not in row
        )
        assert row["question_hash"] == question_hash(_draft().prompt)
        assert (
            row["prompt"] != _draft().prompt
            and decrypt_if_present(row["prompt"]) == _draft().prompt
        )
        assert decrypt_if_present(row["reference_answer"]) == _draft().reference_answer
        assert json.loads(decrypt_if_present(row["rubric_json"])) == [
            {"id": "r1", "text": "Names the step size."},
            {"id": "r2", "text": "Ties it to the gradient direction."},
        ]
        assert json.loads(decrypt_if_present(row["common_wrong_json"])) == [
            {
                "key": "rate_is_iterations",
                "text": "Confuses the rate with the number of iterations.",
            },
        ]
        assert row["source_chunk_ids"] == ["c1"]
        assert row["source_document_ids"] == ["doc-1"]
        assert row["graded"] is False and row["format"] == "free" and row["difficulty"] == 1
        assert (
            row["answer_kind"] == "free"
            and row["canonical_verified"] is False
            and row["stepwise"] is False
        )
        assert row["options_json"] is None and row["correct_option"] is None
        assert row["canonical_answer"] is None and row["tolerance"] is None

    def test_mc_reason_options_and_numeric_key_are_encrypted(self):
        from services import check_item_service as svc
        from services.encryption import decrypt_if_present, decrypt_json

        numeric = _draft(
            prompt="What learning rate does the worked example use?",
            reference_answer="It uses 0.01.",
            answer_kind="numeric",
            canonical_answer="0.01",
            tolerance="0.001",
        )
        factory, mocks = _cached_tables({})
        with patch("services.check_item_service.table", side_effect=factory):
            svc.create_items("course-1", "learning rate", "doc-1", [_mc_draft(), numeric])
        mc, num = mocks["check_items"].upsert.call_args[0][0]
        assert decrypt_json(mc["options_json"]) == [
            {"letter": "A", "text": "The update step size", "wrong_key": None},
            {"letter": "B", "text": "The iteration count", "wrong_key": "rate_is_iterations"},
            {"letter": "C", "text": "The loss value", "wrong_key": "rate_is_loss"},
            {"letter": "D", "text": "The gradient sign", "wrong_key": "rate_is_sign"},
        ]
        assert mc["correct_option"] != "A" and decrypt_if_present(mc["correct_option"]) == "A"
        assert num["answer_kind"] == "numeric" and num["tolerance"] == 0.001
        assert (
            num["canonical_answer"] != "0.01"
            and decrypt_if_present(num["canonical_answer"]) == "0.01"
        )
        assert num["canonical_verified"] is False and num["options_json"] is None

    def test_invalid_drafts_are_dropped_not_stored(self, caplog):
        from services import check_item_service as svc

        factory, mocks = _cached_tables({})
        with (
            patch("services.check_item_service.table", side_effect=factory),
            caplog.at_level("WARNING"),
        ):
            ids = svc.create_items(
                "course-1", "learning rate", None, [_draft(rubric=["one"]), _draft(prompt="ok?")]
            )
        rows = mocks["check_items"].upsert.call_args[0][0]
        assert len(rows) == 1 and len(ids) == 1
        assert rows[0]["source_document_ids"] == []
        assert any("rubric" in r.getMessage() for r in caplog.records)

    def test_all_invalid_or_duplicate_prompts_never_double_write_a_row(self):
        from services import check_item_service as svc

        factory, mocks = _cached_tables({})
        with patch("services.check_item_service.table", side_effect=factory):
            assert svc.create_items("course-1", "k", None, [_draft(rubric=[])]) == []
            ids = svc.create_items(
                "course-1", "k", None, [_draft(), _draft(prompt=" " + _draft().prompt)]
            )
        # an all-invalid batch makes no call; one upsert never names a row twice
        assert mocks["check_items"].upsert.call_count == 1
        assert len(ids) == 1 and len(mocks["check_items"].upsert.call_args[0][0]) == 1


class TestReadItems:
    def _stored_row(self):
        from learning.checks import question_hash
        from services.encryption import encrypt_if_present

        enc = encrypt_if_present
        return {
            "id": "i1",
            "course_id": "course-1",
            "concept_key": "recursion",
            "document_id": "doc-1",
            "format": "free",
            "difficulty": 1,
            "prompt": enc("What is a base case?"),
            "reference_answer": enc("The stopping condition."),
            "rubric_json": enc(
                json.dumps([{"id": "r1", "text": "stops"}, {"id": "r2", "text": "condition"}])
            ),
            "common_wrong_json": enc(json.dumps([{"key": "no_stop", "text": "never stops"}])),
            "options_json": None,
            "correct_option": None,
            "answer_kind": "free",
            "canonical_answer": None,
            "tolerance": None,
            "canonical_verified": False,
            "stepwise": False,
            "source_chunk_ids": ["c1"],
            "source_document_ids": ["doc-1"],
            "question_hash": question_hash("What is a base case?"),
            "graded": False,
            "created_at": "2026-09-26T00:00:00Z",
        }

    def test_list_items_decrypts_and_filters_on_plaintext_columns_only(self):
        from services import check_item_service as svc

        factory, mocks = _cached_tables({"check_items": [self._stored_row()]})
        with patch("services.check_item_service.table", side_effect=factory):
            items = svc.list_items("course-1", "recursion", format="free", difficulty=1)
        assert items[0].prompt == "What is a base case?" and items[0].concept_key == "recursion"
        assert items[0].rubric[1].text == "condition" and items[0].common_wrong[0].key == "no_stop"
        filters = mocks["check_items"].select.call_args[1]["filters"]
        assert filters == {
            "course_id": "eq.course-1",
            "concept_key": "eq.recursion",
            "format": "eq.free",
            "difficulty": "eq.1",
        }

    def test_mc_and_numeric_rows_decrypt_every_a22_field(self):
        from services import check_item_service as svc
        from services.encryption import encrypt_if_present, encrypt_json

        row = dict(
            self._stored_row(),
            format="mc_reason",
            options_json=encrypt_json(
                [
                    {"letter": "A", "text": "stops", "wrong_key": None},
                    {"letter": "B", "text": "loops", "wrong_key": "no_stop"},
                ]
            ),
            correct_option=encrypt_if_present("A"),
            answer_kind="numeric",
            canonical_answer=encrypt_if_present("3"),
            tolerance=0.5,
        )
        factory, _ = _cached_tables({"check_items": [row]})
        with patch("services.check_item_service.table", side_effect=factory):
            (item,) = svc.list_items("course-1", "recursion")
        assert [o.letter for o in item.options] == ["A", "B"] and item.options[0].wrong_key is None
        assert item.options[1].wrong_key == "no_stop" and item.correct_option == "A"
        assert item.canonical_answer == "3" and item.tolerance == 0.5
        assert item.canonical_verified is False and item.graded is False

    def test_items_for_concepts_groups_by_concept_key(self):
        from services import check_item_service as svc

        row2 = dict(self._stored_row(), id="i2", concept_key="base case")
        factory, mocks = _cached_tables({"check_items": [self._stored_row(), row2]})
        with patch("services.check_item_service.table", side_effect=factory):
            grouped = svc.items_for_concepts("course-1", ["recursion", "base case"])
        assert set(grouped) == {"recursion", "base case"} and grouped["base case"][0].id == "i2"
        filters = mocks["check_items"].select.call_args[1]["filters"]
        assert filters["course_id"] == "eq.course-1" and filters["concept_key"].startswith("in.(")
        assert filters["concept_key"] == 'in.("recursion","base case")'

    def test_items_for_no_concepts_reads_nothing(self):
        from services import check_item_service as svc

        with patch("services.check_item_service.table") as t:
            assert svc.items_for_concepts("course-1", []) == {}
        t.assert_not_called()

    def test_bad_rubric_json_yields_empty_rubric_not_a_raise(self, caplog):
        from services import check_item_service as svc
        from services.encryption import encrypt_if_present

        row = dict(
            self._stored_row(),
            rubric_json=encrypt_if_present("not json"),
            options_json=encrypt_if_present("{broken"),
        )
        factory, _ = _cached_tables({"check_items": [row]})
        with (
            patch("services.check_item_service.table", side_effect=factory),
            caplog.at_level("WARNING"),
        ):
            items = svc.list_items("course-1", "recursion")
        assert items[0].rubric == [] and items[0].options is None
        assert items[0].common_wrong[0].key == "no_stop"
        assert any("rubric_json" in r.getMessage() for r in caplog.records)

    def test_course_has_items_count_and_coverage(self):
        from services import check_item_service as svc

        factory, mocks = _cached_tables(
            {
                "check_items": [self._stored_row()],
                "graph_nodes": [
                    {"concept_name": "Recursion"},
                    {"concept_name": " recursion "},
                    {"concept_name": "Momentum"},
                ],
            }
        )
        with patch("services.check_item_service.table", side_effect=factory):
            assert svc.course_has_items("course-1") is True
            assert svc.count_items("course-1", "recursion") == 1
            assert svc.coverage("course-1") == (1, 2)
        first = mocks["check_items"].select.call_args_list[0][1]
        assert first["filters"] == {"course_id": "eq.course-1"} and first["limit"] == 1
        # both course-wide coverage reads page with a total order
        for name in ("graph_nodes", "check_items"):
            call = mocks[name].select_with_count.call_args
            assert call[1]["order"] == "id" and call[1]["filters"] == {"course_id": "eq.course-1"}

    def test_course_without_items(self):
        from services import check_item_service as svc

        factory, _ = _cached_tables({"check_items": []})
        with patch("services.check_item_service.table", side_effect=factory):
            assert svc.course_has_items("course-1") is False
            assert svc.count_items("course-1", "recursion") == 0

    def test_concept_key_is_the_graph_normalizer_and_the_hook_is_an_unwired_stub(self):
        from services import check_item_service as svc
        from services.graph_service import _normalize_concept

        for name in ("Learning  Rate", " learning rate", "LEARNING RATE"):
            assert svc.concept_key(name) == _normalize_concept(name) == "learning rate"
        assert svc.answerable_hook is None


class TestItemSources:
    def test_chunks_for_document_reads_by_doc_id_and_decrypts(self):
        from services import check_item_service as svc
        from services.encryption import encrypt_if_present

        rows = [
            {
                "id": "c1",
                "chunk_index": 0,
                "chunk_text": encrypt_if_present("gradient text"),
                "visibility": "shared",
                "doc_id": "doc-1",
            }
        ]
        factory, mocks = _cached_tables({"course_chunks": rows})
        with patch("services.check_item_service.table", side_effect=factory):
            chunks = svc.chunks_for_document("doc-1")
        assert chunks == [
            {
                "id": "c1",
                "chunk_index": 0,
                "chunk_text": "gradient text",
                "visibility": "shared",
                "doc_id": "doc-1",
            }
        ]
        call = mocks["course_chunks"].select.call_args
        assert call[1]["filters"] == {"doc_id": "eq.doc-1"} and call[1]["order"] == "chunk_index"

    def test_only_shared_course_material_is_a_source(self):
        from services import check_item_service as svc

        with patch("services.check_item_service.decide_visibility", return_value="shared") as dv:
            assert svc.document_is_item_source(_doc()) is True
            dv.assert_called_once_with("u1", shareability="course_material", confidence=0.9)
            assert svc.document_is_item_source(_doc(shareability="completed_work")) is False
            assert svc.document_is_item_source(_doc(shareability="personal_notes")) is False
            assert svc.document_is_item_source(_doc(shareability=None)) is False
        with patch("services.check_item_service.decide_visibility", return_value="private"):
            assert (
                svc.document_is_item_source(_doc()) is False
            )  # opted-out uploader or low confidence

    def test_private_chunks_are_never_a_source_and_never_trigger_the_fallback(self):
        from services import check_item_service as svc
        from services.encryption import encrypt_if_present

        shared = {
            "id": "c1",
            "chunk_index": 0,
            "chunk_text": encrypt_if_present("a"),
            "visibility": "shared",
            "doc_id": "doc-1",
        }
        private = {
            "id": "c2",
            "chunk_index": 1,
            "chunk_text": encrypt_if_present("b"),
            "visibility": "private",
            "doc_id": "doc-1",
        }
        with patch("services.check_item_service.decide_visibility", return_value="shared"):
            for rows, want in (([shared, private], ["c1"]), ([private], [])):
                factory, _ = _cached_tables({"course_chunks": rows})
                with patch("services.check_item_service.table", side_effect=factory):
                    assert [c["id"] for c in svc.source_chunks(_doc())] == want

    def test_unindexed_source_falls_back_to_extracted_text(self):
        from services import check_item_service as svc

        factory, _ = _cached_tables({"course_chunks": []})
        with (
            patch("services.check_item_service.table", side_effect=factory),
            patch("services.check_item_service.decide_visibility", return_value="shared"),
        ):
            assert svc.source_chunks(_doc()) == [
                {"id": None, "chunk_index": 0, "chunk_text": "plain body", "doc_id": "doc-1"}
            ]
            assert svc.source_chunks(_doc(extracted_text=None)) == []

    def test_non_source_reads_no_chunks(self):
        from services import check_item_service as svc

        with (
            patch("services.check_item_service.table") as t,
            patch("services.check_item_service.decide_visibility", return_value="private"),
        ):
            assert svc.source_chunks(_doc()) == []
        t.assert_not_called()


# ── agents/check_items.py + generation ─────────────────────────────────────


def _agent_deps():
    from agents.deps import SaplingDeps

    return SaplingDeps(user_id="u1", course_id="course-1", supabase=None, request_id="r")


class TestAgentPlumbing:
    def test_task_registered_with_lite_default_and_event_in_taxonomy(self):
        from typing import get_args

        from agents import _providers
        from services.events_service import EVENT_TAXONOMY

        assert "check_items" in get_args(_providers.AgentTask)
        assert _providers._DEFAULTS["check_items"] == "gemini-2.5-flash-lite"
        assert "learn.check_items_failed" in EVENT_TAXONOMY

    def test_output_schema_is_flat_and_never_carries_canonical_verified(self):
        from agents.check_items import CheckItemsOutput

        props = CheckItemsOutput.model_json_schema()["$defs"]["CheckItemDraft"]["properties"]
        for name, spec in props.items():
            kind = spec.get("type")
            assert kind in ("string", "integer", "boolean", "array"), (name, spec)
            if kind == "array":
                assert spec["items"] == {"type": "string"}, (name, spec)
        assert "canonical_verified" not in props, "A22: never an agent output"

    def test_build_prompt_names_every_concept_and_marks_passages(self):
        from agents.check_items import build_prompt

        text = build_prompt(
            ["Learning Rate", "Momentum"],
            [{"id": "c1", "text": "alpha"}, {"id": None, "text": "beta"}],
        )
        assert "[chunk c1]" in text and "[passage]" in text
        assert "Learning Rate" in text and "Momentum" in text
        assert "not instructions" in text

    def test_flex_settings_ask_google_for_the_flex_tier_with_the_flex_timeout(self):
        from agents.check_items import _flex_settings
        from learning.params import FLEX_TIMEOUT_S

        assert _flex_settings() == {"service_tier": "flex", "timeout": FLEX_TIMEOUT_S}


class TestDraftItems:
    def test_failure_returns_unavailable_never_raises(self):
        import asyncio

        from agents.check_items import CheckItemsUnavailable, check_items_agent, draft_items
        from pydantic_ai.models.function import FunctionModel

        def boom(messages, info):
            raise RuntimeError("provider down")

        with check_items_agent.override(model=FunctionModel(boom)):
            out = asyncio.run(
                draft_items(
                    ["Learning Rate"], [{"id": "c1", "text": "t"}], deps=_agent_deps(), flex=False
                )
            )
        assert isinstance(out, CheckItemsUnavailable) and out.reason == "RuntimeError"

    def test_flex_retries_a_503_and_passes_flex_settings_standard_does_neither(self, monkeypatch):
        import asyncio

        from agents import check_items as ci
        from pydantic_ai.exceptions import ModelHTTPError
        from pydantic_ai.messages import ModelResponse, ToolCallPart
        from pydantic_ai.models.function import FunctionModel

        async def no_wait(attempt):
            return None

        monkeypatch.setattr(ci, "_backoff", no_wait)
        monkeypatch.setattr(ci, "_flex_settings", lambda: {"timeout": 123.0})
        seen = []

        def flaky(messages, info):
            seen.append(info.model_settings)
            if len(seen) == 1:
                raise ModelHTTPError(status_code=503, model_name="flex")
            return ModelResponse(
                parts=[ToolCallPart(tool_name=info.output_tools[0].name, args={"items": []})]
            )

        with ci.check_items_agent.override(model=FunctionModel(flaky)):
            ok = asyncio.run(
                ci.draft_items(["A"], [{"id": "c1", "text": "t"}], deps=_agent_deps(), flex=True)
            )
        assert not isinstance(ok, ci.CheckItemsUnavailable) and len(seen) == 2
        assert all((s or {}).get("timeout") == 123.0 for s in seen)
        seen.clear()
        with ci.check_items_agent.override(model=FunctionModel(flaky)):
            out = asyncio.run(
                ci.draft_items(["A"], [{"id": "c1", "text": "t"}], deps=_agent_deps(), flex=False)
            )
        assert isinstance(out, ci.CheckItemsUnavailable) and out.reason == "ModelHTTPError"
        assert len(seen) == 1 and (seen[0] or {}).get("timeout") != 123.0

    def test_flex_gives_up_after_its_retry_budget_and_never_retries_other_errors(self, monkeypatch):
        import asyncio

        from agents import check_items as ci
        from learning.params import CHECK_ITEM_FLEX_RETRIES
        from pydantic_ai.exceptions import ModelHTTPError
        from pydantic_ai.models.function import FunctionModel

        async def no_wait(attempt):
            return None

        monkeypatch.setattr(ci, "_backoff", no_wait)
        calls = []

        def busy(messages, info):
            calls.append(1)
            raise ModelHTTPError(status_code=429, model_name="flex")

        with ci.check_items_agent.override(model=FunctionModel(busy)):
            out = asyncio.run(
                ci.draft_items(["A"], [{"id": "c1", "text": "t"}], deps=_agent_deps(), flex=True)
            )
        assert isinstance(out, ci.CheckItemsUnavailable) and out.reason == "ModelHTTPError"
        assert len(calls) == CHECK_ITEM_FLEX_RETRIES + 1
        calls.clear()

        def bad_request(messages, info):
            calls.append(1)
            raise ModelHTTPError(status_code=400, model_name="flex")

        with ci.check_items_agent.override(model=FunctionModel(bad_request)):
            out = asyncio.run(
                ci.draft_items(["A"], [{"id": "c1", "text": "t"}], deps=_agent_deps(), flex=True)
            )
        assert isinstance(out, ci.CheckItemsUnavailable) and len(calls) == 1

    def test_usage_is_recorded_against_the_deps_user_or_the_system_actor(self):
        import asyncio

        from agents import check_items as ci
        from agents.deps import SaplingDeps
        from pydantic_ai.messages import ModelResponse, ToolCallPart
        from pydantic_ai.models.function import FunctionModel

        def ok(messages, info):
            return ModelResponse(
                parts=[ToolCallPart(tool_name=info.output_tools[0].name, args={"items": []})]
            )

        system = SaplingDeps(user_id="", course_id="course-1", supabase=None, request_id="r")
        with (
            ci.check_items_agent.override(model=FunctionModel(ok)),
            patch("agents.check_items.record_agent_usage") as rec,
        ):
            asyncio.run(ci.draft_items(["A"], [], deps=_agent_deps(), flex=False))
            asyncio.run(ci.draft_items(["A"], [], deps=system, flex=False))
        kwargs = [c.kwargs for c in rec.call_args_list]
        assert kwargs == [
            {"feature": "check_items", "task": "check_items", "user_id": "u1"},
            {"feature": "check_items", "task": "check_items", "user_id": None},
        ]


def _drafts_for(*concepts):
    from agents.check_items import CheckItemsOutput

    items = []
    for c in concepts:
        items += [
            _draft(concept=c, prompt=f"What does {c} control?"),
            _draft(concept=c, format="teachback", prompt=f"Teach a peer what {c} does."),
        ]
    return CheckItemsOutput(items=items)


_CHUNK = {"id": "c1", "chunk_index": 0, "chunk_text": "learning rate text", "doc_id": "doc-1"}


def _gen_patches(factory, fake_draft):
    """table + draft_items patched on the service, log_event spied."""
    return (
        patch("services.check_item_service.table", side_effect=factory),
        patch("services.check_item_service.draft_items", side_effect=fake_draft),
        patch("services.check_item_service.log_event"),
    )


class TestGenerate:
    @pytest.fixture(autouse=True)
    def _sources_stay_live(self):
        """Every source stays shared while these tests draft; the write-time
        re-check itself is TestWithdrawalDuringDrafting's."""
        with patch("services.check_item_service._withdrawn_sources", return_value=[]):
            yield

    def test_flag_off_is_inert(self, monkeypatch):
        import config
        from services import check_item_service as svc

        monkeypatch.setattr(config, "LEARNING_LOOP_ENABLED", False)
        with (
            patch("services.check_item_service.table") as t,
            patch("services.check_item_service.draft_items") as d,
        ):
            out = svc.generate_for_concepts(
                user_id="u1",
                course_id="course-1",
                concept_names=["Learning Rate"],
                chunks=[_CHUNK],
                flex=True,
            )
            doc_out = svc.generate_for_document(
                "doc-1",
                user_id="u1",
                course_id="course-1",
                concept_names=["Learning Rate"],
                flex=True,
            )
        assert out == doc_out == (0, 0, 0, 0, 0)
        t.assert_not_called()
        d.assert_not_called()

    def test_no_chunks_is_inert(self, monkeypatch):
        import config
        from services import check_item_service as svc

        monkeypatch.setattr(config, "LEARNING_LOOP_ENABLED", True)
        with (
            patch("services.check_item_service.table") as t,
            patch("services.check_item_service.draft_items") as d,
        ):
            out = svc.generate_for_concepts(
                user_id="u1", course_id="course-1", concept_names=["A"], chunks=[], flex=True
            )
        assert out == (0, 0, 0, 0, 0)
        t.assert_not_called()
        d.assert_not_called()

    def test_batches_concepts_and_stores_per_concept(self, monkeypatch):
        import config
        from learning.params import CHECK_ITEM_CONCEPTS_PER_CALL
        from services import check_item_service as svc

        monkeypatch.setattr(config, "LEARNING_LOOP_ENABLED", True)
        factory, mocks = _cached_tables({"check_items": []})
        names = ["Learning Rate", "Momentum", "Batch Size", "Epoch"]
        batches = []

        async def fake_draft(concepts, passages, *, deps, flex):
            batches.append(list(concepts))
            assert passages[0]["id"] == "c1" and flex is True and deps.feature == "check_items"
            assert deps.user_id == "u1" and deps.course_id == "course-1"
            return _drafts_for(*concepts)

        t, d, _ = _gen_patches(factory, fake_draft)
        with t, d:
            out = svc.generate_for_concepts(
                user_id="u1",
                course_id="course-1",
                concept_names=names + ["learning  rate"],
                chunks=[_CHUNK],
                document_id="doc-1",
                flex=True,
            )
        assert batches == [
            names[:CHECK_ITEM_CONCEPTS_PER_CALL],
            names[CHECK_ITEM_CONCEPTS_PER_CALL:],
        ]
        assert out == (8, 4, 0, 0, 0)
        stored = [r for call in mocks["check_items"].upsert.call_args_list for r in call[0][0]]
        assert {r["concept_key"] for r in stored} == {
            "learning rate",
            "momentum",
            "batch size",
            "epoch",
        }
        assert all(r["document_id"] == "doc-1" and r["course_id"] == "course-1" for r in stored)
        assert all(r["source_document_ids"] == ["doc-1"] for r in stored)

    def test_max_concepts_keeps_the_first_unique_names(self, monkeypatch):
        import config
        from services import check_item_service as svc

        monkeypatch.setattr(config, "LEARNING_LOOP_ENABLED", True)
        factory, _ = _cached_tables({"check_items": []})
        batches = []

        async def fake_draft(concepts, passages, *, deps, flex):
            batches.append(list(concepts))
            return _drafts_for(*concepts)

        t, d, _ = _gen_patches(factory, fake_draft)
        with t, d:
            out = svc.generate_for_concepts(
                user_id="u1",
                course_id="course-1",
                concept_names=["A", "a", "B", "C"],
                chunks=[_CHUNK],
                flex=True,
                max_concepts=2,
            )
        assert batches == [["A", "B"]] and out.concepts_attempted == 2

    def test_covered_concept_makes_zero_agent_calls(self, monkeypatch):
        import config
        from learning.params import CHECK_ITEM_INITIAL_PER_CONCEPT
        from services import check_item_service as svc

        monkeypatch.setattr(config, "LEARNING_LOOP_ENABLED", True)
        full = [{"id": f"i{n}"} for n in range(CHECK_ITEM_INITIAL_PER_CONCEPT)]
        factory, mocks = _cached_tables({"check_items": full})
        t, d, e = _gen_patches(factory, None)
        with t, d as draft, e:
            out = svc.generate_for_concepts(
                user_id="u1",
                course_id="course-1",
                concept_names=["Learning Rate"],
                chunks=[_CHUNK],
                flex=True,
            )
        draft.assert_not_called()
        mocks["check_items"].upsert.assert_not_called()
        assert out == (0, 0, 0, 1, 0)

    def test_unavailable_batch_emits_one_event_and_continues(self, monkeypatch):
        import config
        from agents.check_items import CheckItemsUnavailable
        from learning.params import CHECK_ITEM_CONCEPTS_PER_CALL
        from services import check_item_service as svc

        monkeypatch.setattr(config, "LEARNING_LOOP_ENABLED", True)
        factory, _ = _cached_tables({"check_items": []})
        names = [f"Concept {n}" for n in range(CHECK_ITEM_CONCEPTS_PER_CALL + 1)]
        answers = iter([CheckItemsUnavailable(reason="UsageLimitExceeded"), _drafts_for(names[-1])])

        async def fake_draft(concepts, passages, *, deps, flex):
            return next(answers)

        t, d, e = _gen_patches(factory, fake_draft)
        with t, d, e as ev:
            out = svc.generate_for_concepts(
                user_id="u1",
                course_id="course-1",
                concept_names=names,
                chunks=[_CHUNK],
                document_id="doc-1",
                flex=True,
            )
        assert out == (2, len(names), CHECK_ITEM_CONCEPTS_PER_CALL, 0, 0)
        ev.assert_called_once()
        assert (
            ev.call_args[0][0] == "learn.check_items_failed"
            and ev.call_args[1]["category"] == "error"
        )
        assert ev.call_args[1]["payload"] == {
            "document_id": "doc-1",
            "course_id": "course-1",
            "reason": "UsageLimitExceeded",
        }

    def test_storage_failure_is_one_event_per_concept_and_the_rest_continue(
        self, monkeypatch, caplog
    ):
        import config
        from services import check_item_service as svc

        monkeypatch.setattr(config, "LEARNING_LOOP_ENABLED", True)
        factory, mocks = _cached_tables({"check_items": []})
        mocks_t = factory("check_items")
        mocks_t.upsert.side_effect = [RuntimeError("pg down"), []]

        async def fake_draft(concepts, passages, *, deps, flex):
            return _drafts_for(*concepts)

        t, d, e = _gen_patches(factory, fake_draft)
        with t, d, e as ev, caplog.at_level("WARNING"):
            out = svc.generate_for_concepts(
                user_id="u1",
                course_id="course-1",
                concept_names=["A", "B"],
                chunks=[_CHUNK],
                flex=True,
            )
        assert out.items_created == 2 and out.concepts_attempted == 2
        ev.assert_called_once()
        assert ev.call_args[1]["payload"]["reason"] == "StorageError"

    def test_draft_for_a_concept_outside_the_batch_is_dropped(self, monkeypatch, caplog):
        import config
        from services import check_item_service as svc

        monkeypatch.setattr(config, "LEARNING_LOOP_ENABLED", True)
        factory, mocks = _cached_tables({"check_items": []})

        async def fake_draft(concepts, passages, *, deps, flex):
            return _drafts_for("Learning Rate", "Not Asked For")

        t, d, _ = _gen_patches(factory, fake_draft)
        with t, d, caplog.at_level("WARNING"):
            out = svc.generate_for_concepts(
                user_id="u1",
                course_id="course-1",
                concept_names=["Learning Rate"],
                chunks=[_CHUNK],
                flex=True,
            )
        assert out.items_created == 2
        assert {r["concept_key"] for r in mocks["check_items"].upsert.call_args[0][0]} == {
            "learning rate"
        }
        assert any("Not Asked For" in r.getMessage() for r in caplog.records)

    def test_relevance_floor_drops_a_concept_no_passage_mentions(self, monkeypatch):
        import config
        from services import check_item_service as svc

        monkeypatch.setattr(config, "LEARNING_LOOP_ENABLED", True)
        factory, _ = _cached_tables({"check_items": []})
        batches = []

        async def fake_draft(concepts, passages, *, deps, flex):
            batches.append((list(concepts), [p["id"] for p in passages]))
            return _drafts_for(*concepts)

        other = {
            "id": "c9",
            "chunk_index": 1,
            "chunk_text": "momentum and friction",
            "doc_id": "doc-2",
        }
        t, d, _ = _gen_patches(factory, fake_draft)
        with t, d:
            out = svc.generate_for_concepts(
                user_id=None,
                course_id="course-1",
                concept_names=["Learning Rate", "Photosynthesis", "Momentum"],
                chunks=[_CHUNK, other],
                flex=True,
                min_chunk_score=1,
            )
        assert batches == [(["Learning Rate", "Momentum"], ["c1", "c9"])]
        assert out == (4, 2, 0, 0, 1)

    def test_every_concept_records_every_document_its_call_showed(self, monkeypatch):
        """A23: source_document_ids records EVERY document whose passages
        drafted an item. One call shows the model the union of its batch's
        passages, so an item may use (and cite) another concept's passage —
        here the Momentum drafts cite doc-1's c1. Withdrawing either document
        must reach every item of that call."""
        import config
        from services import check_item_service as svc

        monkeypatch.setattr(config, "LEARNING_LOOP_ENABLED", True)
        factory, mocks = _cached_tables({"check_items": []})
        shown = []

        async def fake_draft(concepts, passages, *, deps, flex):
            shown.append([p["id"] for p in passages])
            return _drafts_for(*concepts)  # every draft cites c1

        other = {
            "id": "c9",
            "chunk_index": 1,
            "chunk_text": "momentum and friction",
            "doc_id": "doc-2",
        }
        doc_of = {"c1": "doc-1", "c9": "doc-2"}
        t, d, _ = _gen_patches(factory, fake_draft)
        with t, d:
            svc.generate_for_concepts(
                user_id=None,
                course_id="course-1",
                concept_names=["Learning Rate", "Momentum"],
                chunks=[_CHUNK, other],
                flex=True,
                min_chunk_score=1,
            )
        assert shown == [["c1", "c9"]]
        stored = [r for call in mocks["check_items"].upsert.call_args_list for r in call[0][0]]
        assert {r["concept_key"] for r in stored} == {"learning rate", "momentum"}
        for row in stored:
            assert row["source_document_ids"] == ["doc-1", "doc-2"]
            assert {doc_of[c] for c in row["source_chunk_ids"]} <= set(row["source_document_ids"])
        for withdrawn in ("doc-1", "doc-2"):
            survivors = [r for r in stored if withdrawn not in r["source_document_ids"]]
            assert survivors == [], f"withdrawing {withdrawn} must retire every item of the call"

    def test_a_citation_of_a_passage_the_call_never_showed_is_dropped(self, monkeypatch):
        """source_chunk_ids name only passages the call showed, so every cited
        chunk's document is in source_document_ids (A23 withdrawal)."""
        import config
        from agents.check_items import CheckItemsOutput
        from services import check_item_service as svc

        monkeypatch.setattr(config, "LEARNING_LOOP_ENABLED", True)
        factory, mocks = _cached_tables({"check_items": []})

        async def fake_draft(concepts, passages, *, deps, flex):
            assert [p["id"] for p in passages] == ["c1"]
            return CheckItemsOutput(items=[_draft(chunk_ids=["c5", "c1"])])

        unshown = {
            "id": "c5",
            "chunk_index": 2,
            "chunk_text": "photosynthesis in leaves",
            "doc_id": "doc-3",
        }
        t, d, _ = _gen_patches(factory, fake_draft)
        with t, d:
            svc.generate_for_concepts(
                user_id=None,
                course_id="course-1",
                concept_names=["Learning Rate"],
                chunks=[_CHUNK, unshown],
                flex=True,
                min_chunk_score=1,
            )
        row = mocks["check_items"].upsert.call_args[0][0][0]
        assert row["source_chunk_ids"] == ["c1"]
        assert row["source_document_ids"] == ["doc-1"]

    def test_generate_for_document_falls_back_to_extracted_text(self, monkeypatch):
        import config
        from services import check_item_service as svc

        monkeypatch.setattr(config, "LEARNING_LOOP_ENABLED", True)
        factory, mocks = _cached_tables(
            {"documents": [_doc()], "course_chunks": [], "check_items": []}
        )
        seen = {}

        async def fake_draft(concepts, passages, *, deps, flex):
            seen["passages"] = passages
            return _drafts_for(*concepts)

        t, d, _ = _gen_patches(factory, fake_draft)
        with t, d, patch("services.check_item_service.decide_visibility", return_value="shared"):
            out = svc.generate_for_document(
                "doc-1", user_id="u1", course_id="course-1", concept_names=["A"], flex=True
            )
        assert seen["passages"] == [{"id": None, "text": "plain body"}]
        assert out.items_created == 2
        row = mocks["check_items"].upsert.call_args[0][0][0]
        assert row["source_chunk_ids"] == [] and row["source_document_ids"] == ["doc-1"]
        doc_read = mocks["documents"].select.call_args[1]
        assert doc_read["filters"] == {"id": "eq.doc-1", "deleted_at": "is.null"}

    def test_generate_for_document_caps_concepts_per_upload(self, monkeypatch):
        import config
        from learning.params import CHECK_ITEM_MAX_CONCEPTS_PER_DOC
        from services import check_item_service as svc

        monkeypatch.setattr(config, "LEARNING_LOOP_ENABLED", True)
        factory, _ = _cached_tables({"documents": [_doc()], "course_chunks": [], "check_items": []})
        drafted = []

        async def fake_draft(concepts, passages, *, deps, flex):
            drafted.extend(concepts)
            return _drafts_for(*concepts)

        names = [f"Concept {n}" for n in range(CHECK_ITEM_MAX_CONCEPTS_PER_DOC + 2)]
        t, d, _ = _gen_patches(factory, fake_draft)
        with t, d, patch("services.check_item_service.decide_visibility", return_value="shared"):
            svc.generate_for_document(
                "doc-1", user_id="u1", course_id="course-1", concept_names=names, flex=True
            )
        assert drafted == names[:CHECK_ITEM_MAX_CONCEPTS_PER_DOC]

    def test_missing_document_yields_zero(self, monkeypatch):
        import config
        from services import check_item_service as svc

        monkeypatch.setattr(config, "LEARNING_LOOP_ENABLED", True)
        factory, mocks = _cached_tables({"documents": []})
        t, d, _ = _gen_patches(factory, None)
        with t, d as draft:
            out = svc.generate_for_document(
                "doc-x", user_id="u1", course_id="course-1", concept_names=["A"], flex=True
            )
        assert out == (0, 0, 0, 0, 0)
        draft.assert_not_called()

    @pytest.mark.parametrize(
        "over,visibility",
        [
            ({"shareability": "completed_work"}, "shared"),  # the student's own answers (#630)
            ({"shareability": "personal_notes"}, "shared"),
            ({}, "private"),  # opted-out uploader or low confidence (#629)
        ],
    )
    def test_completed_work_or_opted_out_document_yields_zero_items(
        self, monkeypatch, over, visibility
    ):
        import config
        from services import check_item_service as svc

        monkeypatch.setattr(config, "LEARNING_LOOP_ENABLED", True)
        factory, mocks = _cached_tables({"documents": [_doc(**over)], "course_chunks": [_CHUNK]})
        t, d, e = _gen_patches(factory, None)
        with (
            t,
            d as draft,
            e as ev,
            patch("services.check_item_service.decide_visibility", return_value=visibility),
        ):
            out = svc.generate_for_document(
                "doc-1", user_id="u1", course_id="course-1", concept_names=["A"], flex=True
            )
        assert out == (0, 0, 0, 0, 0)
        draft.assert_not_called()
        ev.assert_not_called()
        assert "check_items" not in mocks, "a non-source document must not reach the item table"


class TestWithdrawalDuringDrafting:
    """A23: a Flex call can take minutes. A source deleted or opted out while
    it runs must not reach the class pool — delete_document / the opt-out
    retire only the rows that exist when they run, so the write re-checks."""

    def _run(self, monkeypatch, *, doc_reads, visibility=("shared",)):
        import config
        from services import check_item_service as svc

        monkeypatch.setattr(config, "LEARNING_LOOP_ENABLED", True)
        # unindexed: the one extracted-text passage, doc_id doc-1
        factory, mocks = _cached_tables({"course_chunks": [], "check_items": []})
        factory("documents").select.side_effect = list(doc_reads)

        async def fake_draft(concepts, passages, *, deps, flex):
            return _drafts_for(*concepts)

        vis = list(visibility)
        t, d, e = _gen_patches(factory, fake_draft)
        with (
            t,
            d,
            e as ev,
            patch(
                "services.check_item_service.decide_visibility",
                side_effect=lambda *a, **k: vis.pop(0) if len(vis) > 1 else vis[0],
            ),
        ):
            out = svc.generate_for_document(
                "doc-1",
                user_id="u1",
                course_id="course-1",
                concept_names=["Learning Rate"],
                flex=True,
            )
        return out, mocks, ev

    def test_a_source_deleted_mid_call_is_never_written(self, monkeypatch):
        out, mocks, _ = self._run(monkeypatch, doc_reads=[[_doc()], []])
        mocks["check_items"].upsert.assert_not_called()
        assert out.items_created == 0 and out.concepts_attempted == 1
        recheck = mocks["documents"].select.call_args_list[1][1]["filters"]
        assert recheck == {"id": 'in.("doc-1")', "deleted_at": "is.null"}

    def test_a_source_opted_out_mid_call_is_never_written(self, monkeypatch):
        out, mocks, _ = self._run(
            monkeypatch, doc_reads=[[_doc()], [_doc()]], visibility=("shared", "private")
        )
        mocks["check_items"].upsert.assert_not_called()
        assert out.items_created == 0

    def test_a_withdrawal_landing_during_the_write_is_retired_right_after(self, monkeypatch):
        out, mocks, _ = self._run(monkeypatch, doc_reads=[[_doc()], [_doc()], []])
        mocks["check_items"].upsert.assert_called_once()
        mocks["check_items"].delete.assert_called_once()
        filters = mocks["check_items"].delete.call_args.kwargs["filters"]
        assert filters["source_document_ids"] == 'ov.{"doc-1"}'

    def test_a_live_source_is_written_and_nothing_is_retired(self, monkeypatch):
        out, mocks, _ = self._run(monkeypatch, doc_reads=[[_doc()], [_doc()], [_doc()]])
        assert out.items_created == 2
        mocks["check_items"].delete.assert_not_called()

    def test_a_failed_recheck_fails_closed(self, monkeypatch):
        out, mocks, ev = self._run(monkeypatch, doc_reads=[[_doc()], RuntimeError("pg down")])
        mocks["check_items"].upsert.assert_not_called()
        assert ev.call_args[1]["payload"]["reason"] == "StorageError"

    def test_a_failed_post_write_recheck_is_reported_never_answered_by_deleting(self, monkeypatch):
        out, mocks, ev = self._run(
            monkeypatch, doc_reads=[[_doc()], [_doc()], RuntimeError("pg down")]
        )
        mocks["check_items"].upsert.assert_called_once()
        mocks["check_items"].delete.assert_not_called()
        assert ev.call_args[1]["payload"]["reason"] == "StorageError"


# ── routes/documents.py hook ───────────────────────────────────────────────


def _documents_route_helpers():
    import importlib
    import sys

    sys.path.insert(0, str(pathlib.Path(__file__).parent))  # no tests/__init__.py
    return importlib.import_module("test_documents_routes")  # its helpers, not copies


def _upload_sync_with(monkeypatch, *, flag: bool, mode: str):
    """Drive /upload/sync with the orchestrator mocked, returning
    (index_document mock, generate_for_document mock)."""
    import config

    tdr = _documents_route_helpers()
    monkeypatch.setattr(config, "LEARNING_LOOP_ENABLED", flag)
    result = tdr._make_orchestrator_result(category="lecture_notes", is_syllabus=False)
    with (
        tdr._mock_validate_user(),
        patch("routes.documents.extract_text_from_file", return_value=tdr._doc_text("text")),
        patch("routes.documents.process_document", return_value=result),
        patch("routes.documents.apply_graph_update"),
        patch("routes.documents.table") as t,
        patch("routes.documents.model_mode", return_value=mode),
        patch("routes.documents.index_document") as idx,
        patch("routes.documents.generate_for_document") as gen,
        patch("routes.documents.update_course_context"),
        patch("routes.documents._check_upload_achievements"),
    ):
        t.return_value.select.return_value = []
        t.return_value.insert.return_value = [{"id": "doc-1"}]
        r = tdr._make_upload()
        assert r.status_code == 200, r.text
    return idx, gen


def _fn_name(fn) -> str:
    """A scheduled callable's name; a patched one is a MagicMock (no __name__)."""
    return getattr(fn, "__name__", None) or fn._mock_name


class TestUploadHook:
    def test_flag_off_schedules_index_document_only(self, monkeypatch):
        idx, gen = _upload_sync_with(monkeypatch, flag=False, mode="real")
        idx.assert_called_once_with("doc-1")
        gen.assert_not_called()

    def test_flag_off_background_tasks_are_unchanged(self, monkeypatch):
        """Byte-identical flag-off post-roll: the same four tasks as before."""
        from fastapi import BackgroundTasks

        added = []
        monkeypatch.setattr(
            BackgroundTasks, "add_task", lambda self, fn, *a, **k: added.append((_fn_name(fn), a))
        )
        _upload_sync_with(monkeypatch, flag=False, mode="function")
        assert [name for name, _ in added] == [
            "_invalidate_study_guide_cache",
            "update_course_context",
            "_check_upload_achievements",
            "index_document",
        ]
        assert added[-1][1] == ("doc-1",)

    def test_flag_on_real_mode_chains_index_then_generate_in_background(self, monkeypatch):
        idx, gen = _upload_sync_with(monkeypatch, flag=True, mode="real")
        # TestClient runs BackgroundTasks before returning, so both ran, in order.
        idx.assert_called_once_with("doc-1")
        gen.assert_called_once()
        assert gen.call_args[0] == ("doc-1",)
        kwargs = gen.call_args[1]
        assert kwargs["user_id"] == "u1" and kwargs["course_id"] == "course-1"
        assert kwargs["concept_names"] == ["Concept A"]
        assert kwargs["flex"] is True, "ingest-time generation is background prefill (A23)"

    def test_flag_on_function_mode_runs_synchronously(self, monkeypatch):
        from fastapi import BackgroundTasks

        added = []
        monkeypatch.setattr(
            BackgroundTasks, "add_task", lambda self, fn, *a, **k: added.append(_fn_name(fn))
        )
        idx, gen = _upload_sync_with(monkeypatch, flag=True, mode="function")
        idx.assert_called_once_with("doc-1")
        gen.assert_called_once()
        assert "_index_then_check_items" not in added and "index_document" not in added

    def test_index_then_check_items_orders_the_two(self):
        from routes import documents as rd

        calls = []
        with (
            patch(
                "routes.documents.index_document", side_effect=lambda d: calls.append(("index", d))
            ),
            patch(
                "routes.documents.generate_for_document",
                side_effect=lambda d, **k: calls.append(("gen", d)),
            ),
        ):
            rd._index_then_check_items("doc-1", "u1", "course-1", ["A"])
        assert calls == [("index", "doc-1"), ("gen", "doc-1")]

    def test_an_indexing_failure_still_drafts_and_a_drafting_failure_never_raises(self, caplog):
        from routes import documents as rd

        with (
            patch("routes.documents.index_document", side_effect=RuntimeError("pg down")),
            patch(
                "routes.documents.generate_for_document", side_effect=RuntimeError("boom")
            ) as gen,
            caplog.at_level("ERROR"),
        ):
            rd._index_then_check_items("doc-1", "u1", "course-1", ["A"])
        gen.assert_called_once()
        assert len([r for r in caplog.records if r.levelname == "ERROR"]) == 2


def _sse_upload_with(monkeypatch, *, flag: bool, mode: str):
    """Drive the streaming /upload with every agent mocked; return the
    post-roll labels spawned and the generate_for_document mock."""
    import config
    from types import SimpleNamespace

    tdr = _documents_route_helpers()
    monkeypatch.setattr(config, "LEARNING_LOOP_ENABLED", flag)
    res = tdr._make_orchestrator_result(category="lecture_notes", is_syllabus=False)

    def _run(output):
        async def run(*a, **k):
            return SimpleNamespace(output=output, usage=lambda: None)

        return run

    spawned = []
    with (
        tdr._mock_validate_user(),
        patch("routes.documents.extract_text_from_file", return_value=tdr._doc_text("text")),
        patch("routes.documents.classifier_agent.run", side_effect=_run(res.classification)),
        patch("routes.documents.summary_agent.run", side_effect=_run(res.summary)),
        patch("routes.documents.concept_extraction_agent.run", side_effect=_run(res.concepts)),
        patch("routes.documents.apply_concepts_to_graph", return_value=1),
        patch("routes.documents.record_agent_usage", side_effect=lambda r, **k: r),
        patch("routes.documents.apply_graph_update"),
        patch("routes.documents.table") as t,
        patch("routes.documents.model_mode", return_value=mode),
        patch("routes.documents.index_document") as idx,
        patch("routes.documents.generate_for_document") as gen,
        patch("routes.documents._spawn_post_roll", side_effect=lambda *ts: spawned.extend(ts)),
    ):
        t.return_value.select.return_value = []
        t.return_value.insert.return_value = [{"id": "doc-1"}]
        r = tdr.client.post(
            "/api/documents/upload",
            files={"file": ("notes.pdf", b"%PDF-1.4 sample", "application/pdf")},
            data={"course_id": "course-1", "user_id": "u1"},
        )
        assert r.status_code == 200 and '"done"' in r.text, r.text
    return spawned, idx, gen


class TestSseUploadHook:
    def test_flag_off_spawns_index_document_exactly_as_before(self, monkeypatch):
        spawned, idx, gen = _sse_upload_with(monkeypatch, flag=False, mode="real")
        assert [s[0] for s in spawned] == [
            "invalidate_study_guide_cache",
            "update_course_context",
            "check_upload_achievements",
            "index_document",
        ]
        assert spawned[-1][2:] == ("doc-1",)
        gen.assert_not_called()

    def test_flag_on_real_mode_spawns_the_chain(self, monkeypatch):
        spawned, idx, gen = _sse_upload_with(monkeypatch, flag=True, mode="real")
        assert spawned[-1][0] == "index_then_check_items"
        assert spawned[-1][2:] == ("doc-1", "u1", "course-1", ["Concept A"])
        assert "index_document" not in [s[0] for s in spawned]
        gen.assert_not_called()  # spawned, not run, since _spawn_post_roll is spied

    def test_flag_on_function_mode_runs_inline_before_the_post_roll(self, monkeypatch):
        spawned, idx, gen = _sse_upload_with(monkeypatch, flag=True, mode="function")
        idx.assert_called_once_with("doc-1")
        gen.assert_called_once()
        assert gen.call_args[1]["concept_names"] == ["Concept A"]
        assert [s[0] for s in spawned] == [
            "invalidate_study_guide_cache",
            "update_course_context",
            "check_upload_achievements",
        ]


# ── withdrawal (A23): consent stays answerable for items ──────────────────


def _profile_route_helpers():
    import importlib
    import sys

    sys.path.insert(0, str(pathlib.Path(__file__).parent))  # no tests/__init__.py
    return importlib.import_module("test_profile_routes")  # its harness, not a copy


class TestWithdrawal:
    def test_create_items_records_source_documents(self):
        from services import check_item_service as svc

        factory, mocks = _cached_tables({})
        with patch("services.check_item_service.table", side_effect=factory):
            svc.create_items(
                "course-1",
                "k",
                "doc-1",
                [_draft()],
                allowed_chunk_ids={"c1"},
                source_document_ids=["doc-2", "doc-1", "doc-2"],
            )
        assert mocks["check_items"].upsert.call_args[0][0][0]["source_document_ids"] == [
            "doc-1",
            "doc-2",
        ]

    def test_retire_for_documents_deletes_every_item_citing_them(self, caplog):
        from services import check_item_service as svc

        factory, mocks = _cached_tables({})
        mocks_t = factory("check_items")
        mocks_t.delete.return_value = [{"id": "i1"}, {"id": "i2"}]
        with (
            patch("services.check_item_service.table", side_effect=factory),
            caplog.at_level("INFO", logger="sapling.services.check_items"),
        ):
            assert svc.retire_items_for_documents(["doc-1", "doc,2"]) == 2
        filters = mocks_t.delete.call_args.kwargs["filters"]
        assert filters["source_document_ids"] == 'ov.{"doc-1","doc,2"}'
        assert set(filters) <= {"source_document_ids", "select"}, "never a filter on item text"
        assert any("retired: 2" in r.getMessage() for r in caplog.records)

    def test_retire_for_documents_with_nothing_makes_no_call(self):
        from services import check_item_service as svc

        factory, mocks = _cached_tables({})
        with patch("services.check_item_service.table", side_effect=factory):
            assert svc.retire_items_for_documents([]) == 0
        assert mocks == {}

    def test_retire_for_uploader_covers_every_document_of_the_user(self):
        from services import check_item_service as svc

        factory, mocks = _cached_tables({"documents": [{"id": "doc-1"}, {"id": "doc-2"}]})
        with (
            patch("services.check_item_service.table", side_effect=factory),
            patch.object(svc, "retire_items_for_documents", return_value=3) as retire,
        ):
            assert svc.retire_items_for_uploader("user_andres") == 3
        retire.assert_called_once_with(["doc-1", "doc-2"])
        call = mocks["documents"].select_with_count.call_args
        # deleted documents included: withdrawal covers every document ever uploaded
        assert call[1]["filters"] == {"user_id": "eq.user_andres"} and call[1]["order"] == "id"

    def test_retire_is_never_gated_on_the_flag(self, monkeypatch):
        import config
        from services import check_item_service as svc

        monkeypatch.setattr(config, "LEARNING_LOOP_ENABLED", False)
        factory, mocks = _cached_tables({})
        with patch("services.check_item_service.table", side_effect=factory):
            svc.retire_items_for_documents(["doc-1"])
        mocks["check_items"].delete.assert_called_once()

    def test_deleting_a_document_retires_its_items_even_with_the_flag_off(self, monkeypatch):
        import config
        from fastapi.testclient import TestClient
        from main import app
        from routes import documents

        monkeypatch.setattr(config, "LEARNING_LOOP_ENABLED", False)  # withdrawal is never gated
        factory, _ = _cached_tables({"documents": [{"id": "doc-1"}]})
        monkeypatch.setattr(documents, "table", factory)
        monkeypatch.setattr(documents, "require_self", lambda *a, **k: None)
        monkeypatch.setattr(documents, "_validate_user", lambda *a, **k: None)
        with patch("routes.documents.retire_items_for_documents", return_value=1) as retire:
            r = TestClient(app).delete("/api/documents/doc/doc-1?user_id=user_andres")
        assert r.status_code == 200 and r.json() == {"deleted": True}
        retire.assert_called_once_with(["doc-1"])

    def test_a_missing_document_retires_nothing(self, monkeypatch):
        from fastapi.testclient import TestClient
        from main import app
        from routes import documents

        factory, _ = _cached_tables({"documents": []})
        monkeypatch.setattr(documents, "table", factory)
        monkeypatch.setattr(documents, "require_self", lambda *a, **k: None)
        monkeypatch.setattr(documents, "_validate_user", lambda *a, **k: None)
        with patch("routes.documents.retire_items_for_documents") as retire:
            r = TestClient(app).delete("/api/documents/doc/doc-1?user_id=user_andres")
        assert r.status_code == 404
        retire.assert_not_called()

    def test_a_retire_failure_never_fails_the_delete(self, monkeypatch):
        from fastapi.testclient import TestClient
        from main import app
        from routes import documents

        factory, _ = _cached_tables({"documents": [{"id": "doc-1"}]})
        monkeypatch.setattr(documents, "table", factory)
        monkeypatch.setattr(documents, "require_self", lambda *a, **k: None)
        monkeypatch.setattr(documents, "_validate_user", lambda *a, **k: None)
        with patch(
            "routes.documents.retire_items_for_documents", side_effect=RuntimeError("pg down")
        ):
            r = TestClient(app).delete("/api/documents/doc/doc-1?user_id=user_andres")
        assert r.status_code == 200

    def test_opting_out_retires_the_uploaders_items(self, monkeypatch):
        import config

        monkeypatch.setattr(config, "LEARNING_LOOP_ENABLED", False)  # never gated
        tpr = _profile_route_helpers()
        for body, retired in (
            ({"share_class_context": False}, True),
            ({"share_class_context": True}, False),
            ({"theme": "dark"}, False),
        ):
            with (
                tpr._mock_self(),
                patch(
                    "routes.profile.table",
                    side_effect=tpr.TestShareClassContextToggleRefresh()._tables(),
                ),
                patch("routes.profile.update_course_context"),
                patch("routes.profile.resync_user_chunk_visibility") as resync,
                patch("routes.profile.retire_items_for_uploader") as retire,
            ):
                r = tpr.client.patch(f"/api/profile/{tpr.USER_ID}/settings", json=body)
            assert r.status_code == 200, body
            if "share_class_context" in body:
                resync.assert_called_once_with(tpr.USER_ID)
            if retired:
                retire.assert_called_once_with(tpr.USER_ID)
            else:
                retire.assert_not_called()


# ── scripts/backfill_check_items.py ────────────────────────────────────────


@pytest.fixture
def backfill(monkeypatch):
    """Mirror of tests/test_backfill_document_chunks.py::backfill — the script
    calls load_dotenv(".env.staging") at import; neutralise it first."""
    import importlib
    import sys

    monkeypatch.setattr("dotenv.load_dotenv", lambda *a, **k: False)
    sys.modules.pop("scripts.backfill_check_items", None)
    module = importlib.import_module("scripts.backfill_check_items")
    monkeypatch.setattr(module.time, "sleep", lambda s: None)
    monkeypatch.setattr(module, "_project_ref", lambda: "proj-a")
    yield module
    sys.modules.pop("scripts.backfill_check_items", None)


_NODES = [{"course_id": "course-1", "concept_name": "A"}]


class TestBackfill:
    def _wire(self, backfill, monkeypatch, *, nodes=_NODES, chunks=(_CHUNK,)):
        import config

        monkeypatch.setattr(config, "LEARNING_LOOP_ENABLED", True)
        factory, mocks = _cached_tables(
            {"graph_nodes": list(nodes), "documents": [{"id": "doc-1"}]}
        )
        monkeypatch.setattr(backfill, "table", factory)
        monkeypatch.setattr(backfill, "model_mode", lambda: "real")
        monkeypatch.setattr(backfill, "course_offering_ids", lambda c: ["off-1"])
        monkeypatch.setattr(backfill, "source_chunks", lambda d: list(chunks))
        monkeypatch.setattr(backfill, "coverage", lambda c: (1, 1))
        return mocks

    def test_refuses_when_flag_off(self, backfill, monkeypatch, capsys):
        import config

        monkeypatch.setattr(config, "LEARNING_LOOP_ENABLED", False)
        with pytest.raises(SystemExit) as e:
            backfill.main(["--course", "course-1", "--project", "proj-a"])
        assert e.value.code == 2 and "LEARNING_LOOP_ENABLED" in capsys.readouterr().out

    def test_refuses_outside_real_mode_without_function_mode(self, backfill, monkeypatch):
        import config

        monkeypatch.setattr(config, "LEARNING_LOOP_ENABLED", True)
        monkeypatch.setattr(backfill, "model_mode", lambda: "function")
        with pytest.raises(SystemExit) as e:
            backfill.main(["--course", "course-1", "--project", "proj-a"])
        assert e.value.code == 2

    def test_function_mode_flag_allows_a_deterministic_run(self, backfill, monkeypatch):
        from services.check_item_service import GenerationOutcome

        self._wire(backfill, monkeypatch)
        monkeypatch.setattr(backfill, "model_mode", lambda: "function")
        with patch.object(
            backfill, "generate_for_concepts", return_value=GenerationOutcome(9, 1, 0, 0)
        ) as gen:
            backfill.main(["--course", "course-1", "--project", "proj-a", "--function-mode"])
        gen.assert_called_once()

    def test_exactly_one_of_course_or_all_courses(self, backfill, monkeypatch):
        import config

        monkeypatch.setattr(config, "LEARNING_LOOP_ENABLED", True)
        for argv in (
            [],
            ["--project", "proj-a"],
            ["--course", "course-1", "--all-courses", "--project", "proj-a"],
            ["--course", "course-1"],  # --project is required
        ):
            with pytest.raises(SystemExit) as e:
                backfill.main(argv)
            assert e.value.code == 2

    def test_dry_run_reads_but_generates_nothing(self, backfill, monkeypatch, capsys):
        self._wire(backfill, monkeypatch)
        with (
            patch.object(backfill, "generate_for_concepts") as gen,
            patch("services.check_item_service.draft_items") as draft,
        ):
            backfill.main(["--course", "course-1", "--project", "proj-a", "--dry-run"])
        gen.assert_not_called()
        draft.assert_not_called()
        out = capsys.readouterr().out
        assert out.startswith("Project: proj-a") and "coverage course-1 1/1" in out
        assert "would draft" in out

    def test_all_courses_prints_coverage_per_course(self, backfill, monkeypatch, capsys):
        from services.check_item_service import GenerationOutcome

        mocks = self._wire(
            backfill, monkeypatch, nodes=_NODES + [{"course_id": "course-2", "concept_name": "A"}]
        )
        calls = []

        def fake_generate(**k):
            calls.append(k)
            return GenerationOutcome(9, 1, 0, 0)

        monkeypatch.setattr(backfill, "generate_for_concepts", fake_generate)
        backfill.main(["--all-courses", "--project", "proj-a"])
        out = capsys.readouterr().out
        assert "coverage course-1 1/1" in out and "coverage course-2 1/1" in out
        # uncapped, the relevance floor, Flex, and the system actor (A23, Behaviour 8)
        assert [c["course_id"] for c in calls] == ["course-1", "course-2"]
        for c in calls:
            assert c["user_id"] is None and c["flex"] is True and "max_concepts" not in c
            assert c["min_chunk_score"] == 1
        doc_read = mocks["documents"].select_with_count.call_args[1]
        assert doc_read["filters"] == {
            "offering_id": 'in.("off-1")',
            "shareability": "eq.course_material",
            "deleted_at": "is.null",
        }
        assert doc_read["order"] == "id"

    def test_unknown_offerings_skip_the_course(self, backfill, monkeypatch, capsys):
        self._wire(backfill, monkeypatch)
        monkeypatch.setattr(backfill, "course_offering_ids", lambda c: None)
        with patch.object(backfill, "generate_for_concepts") as gen:
            backfill.main(["--course", "course-1", "--project", "proj-a"])
        gen.assert_not_called()
        assert "offerings unknown" in capsys.readouterr().out

    def test_covered_concept_makes_zero_agent_calls_and_exits_zero(self, backfill, monkeypatch):
        from learning.params import CHECK_ITEM_INITIAL_PER_CONCEPT

        self._wire(backfill, monkeypatch)
        full, _ = _cached_tables(
            {"check_items": [{"id": f"i{n}"} for n in range(CHECK_ITEM_INITIAL_PER_CONCEPT)]}
        )
        with (
            patch("services.check_item_service.table", side_effect=full),
            patch("services.check_item_service.draft_items") as draft,
        ):
            backfill.main(
                ["--course", "course-1", "--project", "proj-a"]
            )  # returns: a fully covered run exits 0
        draft.assert_not_called()

    def test_zero_items_landed_exits_one(self, backfill, monkeypatch):
        from services.check_item_service import GenerationOutcome

        self._wire(backfill, monkeypatch)
        monkeypatch.setattr(
            backfill, "generate_for_concepts", lambda **k: GenerationOutcome(0, 1, 1, 0)
        )
        with pytest.raises(SystemExit) as e:
            backfill.main(["--course", "course-1", "--project", "proj-a"])
        assert e.value.code == 1

    def test_refuses_when_project_is_not_the_connected_one(self, backfill, monkeypatch, capsys):
        mocks = self._wire(backfill, monkeypatch)
        with patch.object(backfill, "generate_for_concepts") as gen:
            with pytest.raises(SystemExit) as e:
                backfill.main(["--all-courses", "--project", "prod-ref"])
        out = capsys.readouterr().out
        assert e.value.code == 2 and "Project: proj-a" in out and "prod-ref" in out
        gen.assert_not_called()
        assert mocks == {}, "no table() read before the project check"

    def test_concept_no_shared_passage_mentions_makes_no_agent_call(
        self, backfill, monkeypatch, capsys
    ):
        """A23 relevance floor: a concept from a private note that no shared course-material
        passage mentions is never drafted from unrelated (score-0) chunks."""
        off_topic = {
            "id": "c9",
            "chunk_index": 0,
            "chunk_text": "photosynthesis in leaves",
            "doc_id": "doc-1",
        }
        self._wire(
            backfill,
            monkeypatch,
            nodes=[{"course_id": "course-1", "concept_name": "Gradient descent"}],
            chunks=(off_topic,),
        )
        empty, _ = _cached_tables({"check_items": []})
        with (
            patch("services.check_item_service.table", side_effect=empty),
            patch("services.check_item_service.draft_items") as draft,
            patch("services.check_item_service.create_items") as create,
        ):
            backfill.main(["--course", "course-1", "--project", "proj-a"])
        draft.assert_not_called()
        create.assert_not_called()
        assert "unmatched 1" in capsys.readouterr().out


class TestProjectRef:
    @pytest.mark.parametrize(
        "url,ref",
        [
            ("https://abcdefghij.supabase.co", "abcdefghij"),
            ("https://ABCDEFGHIJ.supabase.co/", "abcdefghij"),
            ("http://127.0.0.1:54321", "local"),
            ("http://localhost:54321", "local"),
            ("", "local"),
        ],
    )
    def test_ref_is_parsed_from_supabase_url(self, monkeypatch, url, ref):
        import importlib
        import sys

        monkeypatch.setattr("dotenv.load_dotenv", lambda *a, **k: False)
        sys.modules.pop("scripts.backfill_check_items", None)
        try:
            module = importlib.import_module("scripts.backfill_check_items")
            monkeypatch.setattr(module, "SUPABASE_URL", url)
            assert module._project_ref() == ref
        finally:
            sys.modules.pop("scripts.backfill_check_items", None)

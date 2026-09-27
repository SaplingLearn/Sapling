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

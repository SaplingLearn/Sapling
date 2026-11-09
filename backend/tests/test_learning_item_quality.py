"""Spec §13 A113 — check-item quality guards: the item-flaw linter
(learning/item_lint.py), "Report this question" (GitHub #695; the store in
learning/item_reports.py), the post-test's clean-first preference and the admin
review queue (routes/admin_check_items.py), plus the lint backfill script.

Hermetic: every table()/rpc() here is a fake. The route halves of the report
live beside their fixtures (tests/test_learn_loop_routes.py for the loop's check
card, tests/test_learning_review.py for the review queue,
tests/test_learning_posttest.py for the post-test); the real-database half (the
race-safe count under concurrency) is
tests/integration/test_check_item_reports_db.py."""

from __future__ import annotations

import math
import pathlib
import re
from datetime import datetime, timedelta, timezone
from typing import get_args
from unittest.mock import patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from learning import item_lint, item_reports, params
from learning.checks import CheckItem, Option, RubricItem, WrongReason, question_hash
from tests.test_learning_check_items import _cached_tables, _draft, _mc_draft, _opts

MIG_DIR = pathlib.Path(__file__).resolve().parents[1] / "db" / "migrations"
NOW = datetime(2026, 11, 8, 12, 0, tzinfo=timezone.utc)


def _migration() -> str:
    hits = sorted(MIG_DIR.glob("*_learning_item_quality.sql"))
    assert len(hits) == 1, hits
    return hits[0].read_text()


def _stored(qh="qh-1", *, options=None, correct=None, lint=None, fmt=None, prompt="Q?", **over):
    """A decrypted CheckItem as the service returns it."""
    return CheckItem(
        id=over.pop("id", f"id-{qh}"),
        course_id=over.pop("course_id", "c1"),
        concept_key=over.pop("concept_key", "recursion"),
        format=fmt or ("mc_reason" if options else "free"),
        difficulty=over.pop("difficulty", 2),
        prompt=prompt,
        reference_answer="A reference. Final answer: the base case.",
        final_answer=over.pop("final_answer", "the base case"),
        rubric=[RubricItem(id="r1", text="a"), RubricItem(id="r2", text="b")],
        common_wrong=[WrongReason(key="w", text="a wrong reason")],
        options=options,
        correct_option=correct,
        source_chunk_ids=[],
        question_hash=qh,
        lint_flags=lint,
        **over,
    )


def _letters(*texts):
    return [
        Option(letter=chr(ord("A") + i), text=t, wrong_key=None if i == 0 else f"w{i}")
        for i, t in enumerate(texts)
    ]


# ── constants, migration, flag, body ────────────────────────────────────────


class TestPins:
    def test_constants(self):
        assert params.ITEM_REPORT_REASONS == ("wrong_answer", "unclear", "not_from_my_course")
        assert params.ITEM_REPORT_SURFACES == ("loop", "review")
        assert params.ITEM_REPORT_QUARANTINE_MIN_REPORTERS == 2  # † #695's N (A123: a quarantine)
        assert 0 < params.ITEM_LINT_LONGEST_MARGIN < 1
        assert params.ITEM_LINT_STEM_OVERLAP_MARGIN >= 1

    def test_migration_name_and_enums_follow_params(self):
        (path,) = sorted(MIG_DIR.glob("*_learning_item_quality.sql"))
        assert re.fullmatch(r"\d{14}_learning_item_quality\.sql", path.name)
        # after the newest migration it was written on top of (the ledger runs in name order)
        assert path.name > "20261108033310_checklist_budget_no_course_soft_delete.sql"
        sql = _migration()
        reasons = ",".join(f"'{r}'" for r in params.ITEM_REPORT_REASONS)
        surfaces = ",".join(f"'{s}'" for s in params.ITEM_REPORT_SURFACES)
        assert f"CHECK (reason IN ({reasons}))" in sql
        assert f"CHECK (surface IN ({surfaces}))" in sql
        assert "ADD COLUMN IF NOT EXISTS lint_flags text[];" in sql  # NULL = never linted

    def test_one_report_per_student_and_item_and_one_review_per_course_item(self):
        sql = _migration()
        reports = sql.split("CREATE TABLE IF NOT EXISTS check_item_reports", 1)[1].split(");", 1)[0]
        assert "PRIMARY KEY (user_id, question_hash)" in reports
        assert "REFERENCES users(id) ON DELETE CASCADE" in reports
        reviews = sql.split("CREATE TABLE IF NOT EXISTS check_item_reviews", 1)[1].split(");", 1)[0]
        assert "PRIMARY KEY (course_id, question_hash)" in reviews
        assert "CHECK (status IN ('approved','retired'))" in reviews

    def test_the_threshold_is_decided_by_the_database_under_one_lock(self):
        """#695 race: two reporters arriving together. The count is the
        database's, taken after a per-item advisory lock, and only a FIRST
        report of the student can be the retiring one; both functions take the
        same lock key, so an admin decision is ordered with the reports."""
        sql = _migration()
        report = sql.split("FUNCTION check_item_report(", 1)[1].split("$$;", 1)[0]
        decide = sql.split("FUNCTION check_item_review_decide(", 1)[1].split("$$;", 1)[0]
        lock = "hashtextextended('check-item-review:' || p_course_id || ':' || p_question_hash, 0)"
        for body in (report, decide):
            assert f"pg_advisory_xact_lock(\n    {lock})" in body
            assert body.index("pg_advisory_xact_lock") < body.index("INSERT INTO")
        assert "ON CONFLICT (user_id, question_hash) DO NOTHING" in report
        assert "v_first := FOUND;" in report
        assert (
            "retire := v_first AND v_count >= p_min_reporters AND v_status IS DISTINCT FROM 'retired'"
            in report
        )
        # a report newer than an approval counts afresh; timestamps follow the lock
        assert "(v_status IS DISTINCT FROM 'approved' OR c.created_at > v_since)" in report
        assert "clock_timestamp()" in report and "clock_timestamp()" in decide
        # a retired item is never approved
        assert "NOT (v_prev IS NOT DISTINCT FROM 'retired' AND p_status = 'approved')" in decide

    def test_backend_only(self):
        sql = _migration()
        for name in ("check_item_reports", "check_item_reviews"):
            assert f"ALTER TABLE {name} ENABLE ROW LEVEL SECURITY;" in sql
            assert f"REVOKE ALL ON TABLE {name} FROM PUBLIC;" in sql
        assert "REVOKE ALL ON FUNCTION check_item_report(text, text, text, text, text, integer) FROM PUBLIC;" in sql
        assert "REVOKE ALL ON FUNCTION check_item_review_decide(text, text, text, text) FROM PUBLIC;" in sql
        assert "NOTIFY pgrst, 'reload schema';" in sql
        assert "SECURITY DEFINER" not in sql

    def test_the_flag_is_declared_and_client_visible(self):
        from services.feature_flags import REGISTRY

        fd = REGISTRY[item_reports.ITEM_REPORTS_FLAG]
        assert fd.variants == ("off", "on") and fd.client_visible is True

    def test_the_flag_description_says_what_reports_do(self):
        """Spec §13 A142: the admin flags page shows this text. Since A123
        reports quarantine (hold) an item and only staff retire it; the text
        said two reporters "retire it course-wide"."""
        from services.feature_flags import REGISTRY

        text = REGISTRY[item_reports.ITEM_REPORTS_FLAG].description
        words = {2: "two", 3: "three", 4: "four"}
        assert f"{words[params.ITEM_REPORT_QUARANTINE_MIN_REPORTERS]} reporters hold it" in text
        assert "reporters retire" not in text and "until staff approve or retire it" in text

    def test_the_report_body_takes_enums_only(self):
        from pydantic import ValidationError

        from models import LoopReportBody

        fields = LoopReportBody.model_fields
        assert get_args(fields["reason"].annotation) == params.ITEM_REPORT_REASONS
        assert get_args(fields["surface"].annotation) == params.ITEM_REPORT_SURFACES
        ok = {"surface": "loop", "session_id": "s1", "question_hash": "qh", "reason": "unclear"}
        assert LoopReportBody(**ok).reason == "unclear"
        for bad in (
            {**ok, "reason": "other"},
            {**ok, "comment": "the key is wrong because ..."},  # no free text, ever
            {**ok, "question_hash": None},  # a loop report names its check
            {**ok, "surface": "review", "question_hash": None},  # a review report names its item
        ):
            with pytest.raises(ValidationError):
                LoopReportBody(**bad)

    def test_events_are_in_the_taxonomy(self):
        from services.events_service import EVENT_TAXONOMY

        assert {
            "learn.check_item_reported",
            "learn.check_item_retired",
            "learn.check_item_approved",
        } <= EVENT_TAXONOMY


# ── the linter ───────────────────────────────────────────────────────────────


class TestLint:
    def test_a_clean_item_has_no_flags(self):
        assert item_lint.lint_item(
            "Which quantity does the learning rate scale?",
            ["The update step size", "The iteration count", "The loss value", "The gradient sign"],
            0,
        ) == []
        assert item_lint.lint_item("In one sentence, what does the learning rate control?") == []

    def test_correct_longest_needs_the_margin(self):
        distractors = ["a short one", "brief text", "terse"]  # the longest: 11 characters
        long = "a much longer and more detailed answer"
        assert item_lint.lint_item("Q?", [long, *distractors], 0) == [item_lint.CORRECT_LONGEST]
        # uniquely the longest, but inside the margin of the longest distractor: no flag
        edge = len("a short one") * (1 + params.ITEM_LINT_LONGEST_MARGIN)
        within, beyond = "y" * (math.ceil(edge) - 1), "y" * math.ceil(edge)
        assert len("a short one") < len(within) < edge <= len(beyond)
        assert item_lint.lint_item("Q?", [within, *distractors], 0) == []
        assert item_lint.lint_item("Q?", [beyond, *distractors], 0) == [item_lint.CORRECT_LONGEST]
        # a distractor that is the longest is no cue for the key
        assert item_lint.lint_item("Q?", ["short", long, "brief", "tiny"], 0) == []
        # whitespace runs do not count: "a b" is three characters, not thirty-two
        assert item_lint.lint_item("Q?", ["a" + " " * 30 + "b", "abcd", "x", "y"], 0) == []

    def test_correct_repeats_stem(self):
        prompt = "Why does the learning rate scale each gradient step size?"
        flagged = item_lint.lint_item(
            prompt, ["It sets gradient step size", "It counts epochs", "It is loss", "It flips"], 0
        )
        assert item_lint.CORRECT_REPEATS_STEM in flagged
        # one shared word is ordinary; a distractor sharing as many is no cue
        assert item_lint.CORRECT_REPEATS_STEM not in item_lint.lint_item(
            prompt, ["It caps each step", "It counts epochs", "It is loss", "It flips"], 0
        )
        assert item_lint.CORRECT_REPEATS_STEM not in item_lint.lint_item(
            prompt,
            ["It sets gradient step size", "Gradient step size grows", "It is loss", "It flips"],
            0,
        )
        # plurals and case fold: "Steps"/"step", "Sizes"/"size"
        assert item_lint.CORRECT_REPEATS_STEM in item_lint.lint_item(
            prompt, ["Gradient Steps and Sizes", "It counts epochs", "It is loss", "It flips"], 0
        )

    @pytest.mark.parametrize(
        "text",
        ["All of the above", "none of these.", "Both of the above", "all the above", "Neither of those"],
    )
    def test_all_or_none_of_the_above(self, text):
        assert item_lint.ALL_OR_NONE_OF_ABOVE in item_lint.lint_item("Q?", ["a", "b", "c", text], 1)

    def test_duplicate_options(self):
        assert item_lint.lint_item("Q?", ["The base case.", "the Base Cases", "x", "y"], 2) == [
            item_lint.DUPLICATE_OPTIONS
        ]
        assert item_lint.lint_item("Q?", ["A base case", "The base case", "x", "y"], 2) == [
            item_lint.DUPLICATE_OPTIONS
        ]
        # one key word apart is a real distractor, not a duplicate
        assert item_lint.lint_item(
            "Q?", ["The base case returns 1", "The base case returns 0", "x", "y"], 2
        ) == []

    @pytest.mark.parametrize(
        "prompt",
        [
            "Which of the following is NOT a base case?",
            "Which loop does not terminate?",
            "Which statement about recursion is false?",
            "All of the following are stable sorts except which one?",
            "Which of these is the least efficient?",
            "Explain why this claim is not correct: recursion needs no base case.",
        ],
    )
    def test_negative_stems(self, prompt):
        assert item_lint.lint_item(prompt) == [item_lint.NEGATIVE_STEM]

    @pytest.mark.parametrize(
        "prompt",
        [
            "Why does the loop not stop?",
            "What does a NOT gate output for input 1?",
            "What does SQL's EXCEPT operator return?",
            "Explain why the base case is needed.",
        ],
    )
    def test_not_negative_stems(self, prompt):
        assert item_lint.lint_item(prompt) == []

    def test_flags_come_in_one_order_and_need_a_valid_correct_index(self):
        options = ["a much longer and more detailed answer", "x", "x.", "All of the above"]
        flags = item_lint.lint_item("Which of these is NOT true?", options, 0)
        assert flags == [
            item_lint.CORRECT_LONGEST,
            item_lint.ALL_OR_NONE_OF_ABOVE,
            item_lint.DUPLICATE_OPTIONS,
            item_lint.NEGATIVE_STEM,
        ]
        assert flags == [f for f in item_lint.LINT_FLAGS if f in flags]
        # no (or an out-of-range) correct index: the two key rules are not read
        assert item_lint.CORRECT_LONGEST not in item_lint.lint_item("Q?", options, None)
        assert item_lint.CORRECT_LONGEST not in item_lint.lint_item("Q?", options, 9)

    def test_lint_check_item_reads_the_stored_shape(self):
        options = _letters("x", "the longest option of them all here", "y", "z")
        item = _stored(options=options, correct="B")
        assert item_lint.lint_check_item(item) == [item_lint.CORRECT_LONGEST]
        assert item_lint.lint_check_item(_stored(prompt="Which one is false?")) == [
            item_lint.NEGATIVE_STEM
        ]


# ── checks: the post-test reserve prefers clean items ────────────────────────


class TestPosttestPreference:
    MID = params.CHECK_ITEM_DIFFICULTIES[1]

    def test_lint_rank_and_tiers(self):
        from learning.checks import lint_rank, lint_tiers

        clean, unknown, flagged = _stored("a", lint=[]), _stored("b"), _stored("c", lint=["x"])
        assert [lint_rank(i) for i in (clean, unknown, flagged)] == [0, 1, 2]
        assert lint_tiers([flagged, unknown, clean]) == [[clean], [unknown], [flagged]]

    def test_the_reserve_is_the_cleanest_free_mid_item(self):
        from learning.checks import posttest_reserve_hash

        a = _stored("qh-a", lint=["negative_stem"])  # lowest hash, flagged
        b = _stored("qh-b")  # never linted
        c = _stored("qh-c", lint=[])  # clean
        assert posttest_reserve_hash([a, b, c]) == "qh-c"
        assert posttest_reserve_hash([a, b]) == "qh-b"
        assert posttest_reserve_hash([a]) == "qh-a"  # flawed only when nothing else
        # A23 still first: a free mid item beats a clean item of another shape
        other = _stored("qh-0", lint=[], difficulty=1)
        assert posttest_reserve_hash([a, other]) == "qh-a"
        # without lint data the rule is the old one exactly
        assert posttest_reserve_hash([_stored("qh-2"), _stored("qh-1")]) == "qh-1"

    def test_posttest_item_prefers_clean_within_each_rule(self):
        from learning.checks import choose_posttest_item

        def posttest_item(items, excluded):  # the first window, no pretest (A126's choice)
            choice = choose_posttest_item(items, excluded, window_index=0)
            return choice.item if choice else None

        reserve = _stored("qh-1", lint=[])
        flagged_mid = _stored("qh-2", lint=["negative_stem"])
        clean_easy = _stored("qh-3", lint=[], difficulty=1)
        items = [reserve, flagged_mid, clean_easy]
        assert posttest_item(items, set()).question_hash == "qh-1"
        # reserve excluded (seen/revealed/reported): a clean free item beats a flagged one
        assert posttest_item(items, {"qh-1"}).question_hash == "qh-3"
        assert posttest_item(items, {"qh-1", "qh-3"}).question_hash == "qh-2"
        # the last rule (any servable item) prefers clean too
        mc_flagged = _stored("qh-4", lint=["correct_longest"], fmt="mc_reason")
        mc_clean = _stored("qh-9", lint=[], fmt="mc_reason")
        assert posttest_item([mc_flagged, mc_clean], set()).question_hash == "qh-9"
        assert posttest_item([mc_flagged, mc_clean], {"qh-9"}).question_hash == "qh-4"
        assert posttest_item([mc_flagged], {"qh-4"}) is None


# ── check_item_service ──────────────────────────────────────────────────────


class TestServiceWrites:
    def test_create_items_stores_the_lint_of_the_stored_shape(self):
        from services import check_item_service as svc

        longest = _mc_draft(
            prompt="Which quantity does the learning rate set? Pick one and give your reason.",
            options=_opts(
                ("The size of each update step along the negative gradient", True, None),
                ("The iteration count", False, "rate_is_iterations"),
                ("The loss value", False, "rate_is_loss"),
                ("The gradient sign", False, "rate_is_sign"),
            ),
            reference_answer=(
                "Final answer: The size of each update step along the negative gradient."
            ),
            final_answer="The size of each update step along the negative gradient",
        )
        factory, mocks = _cached_tables({})
        with patch("services.check_item_service.table", side_effect=factory):
            svc.create_items("course-1", "learning rate", None, [_draft(), _mc_draft(), longest])
        free, clean_mc, flagged_mc = mocks["check_items"].upsert.call_args[0][0]
        assert free["lint_flags"] == [] and clean_mc["lint_flags"] == []
        assert item_lint.CORRECT_LONGEST in flagged_mc["lint_flags"]  # stored, not dropped

    def test_a_retired_question_is_never_stored_again(self, caplog):
        from services import check_item_service as svc

        retired = question_hash(_mc_draft().prompt)
        factory, mocks = _cached_tables(
            {"check_item_reviews": [{"question_hash": retired, "status": "retired"}]}
        )
        with (
            patch("services.check_item_service.table", side_effect=factory),
            patch("learning.item_reports.table", side_effect=factory),
            caplog.at_level("INFO", logger="sapling.services.check_items"),
        ):
            write = svc._store_drafts("course-1", "learning rate", None, [_draft(), _mc_draft()])
        (row,) = mocks["check_items"].upsert.call_args[0][0]
        assert row["format"] == "free" and write.ids == [row["id"]]
        assert write.mc_drops == [svc._RETIRED]  # the top-up is told why
        read = mocks["check_item_reviews"].select.call_args
        assert read.kwargs["filters"]["course_id"] == "eq.course-1"
        assert read.kwargs["filters"]["status"] == "in.(quarantined,retired)"
        assert any("retired for the course" in r.getMessage() for r in caplog.records)

    def test_a_quarantined_question_drafted_again_is_stored_held(self, caplog):
        """A123: only a staff retire blocks a re-draft. A question its reporters
        quarantined is stored again, HELD like its other rows (the database's
        trigger adds `reports_threshold` whatever the write says; the write
        adds it too so it takes no top-up slot and counts toward no floor)."""
        from learning.checks import REPORTS_THRESHOLD, held
        from services import check_item_service as svc

        quarantined = question_hash(_mc_draft().prompt)
        fresh = _mc_draft(prompt="Which quantity does the learning rate set? Pick one and give your reason.")
        factory, mocks = _cached_tables(
            {"check_item_reviews": [{"question_hash": quarantined, "status": "quarantined"}]}
        )
        with (
            patch("services.check_item_service.table", side_effect=factory),
            patch("learning.item_reports.table", side_effect=factory),
            caplog.at_level("INFO", logger="sapling.services.check_items"),
        ):
            write = svc._store_drafts("course-1", "learning rate", None, [_mc_draft(), fresh], limit=1)
        stored = mocks["check_items"].upsert.call_args[0][0]
        by_hash = {r["question_hash"]: r for r in stored}
        assert set(by_hash) == {quarantined, question_hash(fresh.prompt)}  # both stored
        assert by_hash[quarantined]["lint_flags"][-1] == REPORTS_THRESHOLD
        assert held(svc._row_to_item(by_hash[quarantined]))
        assert REPORTS_THRESHOLD not in by_hash[question_hash(fresh.prompt)]["lint_flags"]
        assert write.mc_drops == [svc._QUARANTINED]  # the top-up is told why
        assert write.mc_reason == {by_hash[question_hash(fresh.prompt)]["id"]: fresh.difficulty}
        assert any("quarantined for the course" in r.getMessage() for r in caplog.records)

    def test_a_retired_draft_never_takes_a_top_up_slot(self):
        """The top-up asks for exactly the missing count (`limit`): a retired
        repeat is dropped before the count, so the fresh draft after it lands."""
        from services import check_item_service as svc

        fresh = _mc_draft(prompt="Which quantity does the learning rate set? Pick one and give your reason.")
        retired = question_hash(_mc_draft().prompt)
        factory, mocks = _cached_tables(
            {"check_item_reviews": [{"question_hash": retired, "status": "retired"}]}
        )
        with (
            patch("services.check_item_service.table", side_effect=factory),
            patch("learning.item_reports.table", side_effect=factory),
        ):
            write = svc._store_drafts("course-1", "learning rate", None, [_mc_draft(), fresh], limit=1)
        (row,) = mocks["check_items"].upsert.call_args[0][0]
        assert row["question_hash"] == question_hash(fresh.prompt) and write.ids == [row["id"]]
        assert write.mc_drops == [svc._RETIRED]

    def test_a_failed_retired_read_fails_the_write_closed(self):
        from services import check_item_service as svc

        factory, mocks = _cached_tables({})
        factory("check_item_reviews").select.side_effect = RuntimeError("down")
        with (
            patch("services.check_item_service.table", side_effect=factory),
            patch("learning.item_reports.table", side_effect=factory),
            pytest.raises(RuntimeError),
        ):
            svc.create_items("course-1", "learning rate", None, [_draft()])
        assert "check_items" not in mocks  # nothing was written

    def test_retire_course_item_voids_every_students_evidence_then_retires_every_row(self):
        """A123: the staff retire voids first — one apply_graph_update(void_evidence)
        per student with non-void evidence on the item — and deletes the rows
        only after every void went through."""
        from services import check_item_service as svc

        factory, mocks = _cached_tables({"check_items": [{"id": "i1"}, {"id": "i2"}]})
        mocks_t = factory("check_items")
        mocks_t.delete.return_value = [{"id": "i1"}, {"id": "i2"}]
        order = []
        with (
            patch("services.check_item_service.table", side_effect=factory),
            patch("learning.evidence_transaction.void_pending", return_value={"u2": 1, "u1": 3}),
            patch(
                "services.graph_service.apply_graph_update",
                side_effect=lambda user, update, course: order.append((user, update, course)) or [],
            ),
        ):
            out = svc.retire_course_item("c1", "qh-1")
        assert out == svc.RetireOutcome(items=2, students=2, voided=4)
        assert order == [
            ("u1", {"void_evidence": {"question_hash": "qh-1"}}, "c1"),
            ("u2", {"void_evidence": {"question_hash": "qh-1"}}, "c1"),
        ]
        filters = mocks_t.select.call_args.kwargs["filters"]
        assert filters == {"course_id": "eq.c1", "question_hash": "eq.qh-1"}
        assert mocks_t.delete.call_args.kwargs["filters"]["id"] == 'in.("i1","i2")'

    def test_a_failed_void_keeps_the_rows_for_a_retire_pending_rerun(self):
        from services import check_item_service as svc

        factory, mocks = _cached_tables({"check_items": [{"id": "i1"}]})
        with (
            patch("services.check_item_service.table", side_effect=factory),
            patch("learning.evidence_transaction.void_pending", return_value={"u1": 1}),
            patch("services.graph_service.apply_graph_update", side_effect=RuntimeError("down")),
            pytest.raises(RuntimeError),
        ):
            svc.retire_course_item("c1", "qh-1")
        assert not factory("check_items").delete.called  # stored: the queue lists it retire-pending

    def test_store_lint_flags_batches_by_id(self):
        from services import check_item_service as svc

        factory, mocks = _cached_tables({})
        ids = [f"i{n}" for n in range(svc._DOC_ID_BATCH + 1)]
        with patch("services.check_item_service.table", side_effect=factory):
            assert svc.store_lint_flags(("negative_stem",), ids) == len(ids)
        calls = mocks["check_items"].update.call_args_list
        assert len(calls) == 2
        assert calls[0].args[0] == {"lint_flags": ["negative_stem"]}
        assert calls[0].kwargs["prefer_return_minimal"] is True


class TestServiceReads:
    def test_lint_flags_are_read_back_plaintext(self):
        from services.check_item_service import _row_to_item

        base = {
            "id": "i1", "course_id": "c1", "concept_key": "k", "format": "free", "difficulty": 2,
            "prompt": None, "reference_answer": None, "question_hash": "qh", "source_chunk_ids": [],
        }
        assert _row_to_item({**base, "lint_flags": ["negative_stem"]}).lint_flags == ["negative_stem"]
        assert _row_to_item({**base, "lint_flags": []}).lint_flags == []
        assert _row_to_item({**base, "lint_flags": None}).lint_flags is None
        assert _row_to_item(base).lint_flags is None

    def test_flagged_rows_are_read_by_plaintext_columns(self):
        from services import check_item_service as svc

        factory, mocks = _cached_tables({"check_items": [{"id": "i1"}]})
        with patch("services.check_item_service.table", side_effect=factory):
            assert svc.flagged_item_rows() == [{"id": "i1"}]
        args, kwargs = mocks["check_items"].select_with_count.call_args
        assert args[0] == svc._QUEUE_COLUMNS
        assert "prompt" not in svc._QUEUE_COLUMNS and "options_json" not in svc._QUEUE_COLUMNS
        assert kwargs["filters"]["lint_flags"].startswith("ov.{")
        for flag in item_lint.LINT_FLAGS:
            assert f'"{flag}"' in kwargs["filters"]["lint_flags"]

    def test_item_rows_for_matches_the_course(self):
        from services import check_item_service as svc

        rows = [
            {"id": "i1", "course_id": "c1", "question_hash": "qh"},
            {"id": "i2", "course_id": "c2", "question_hash": "qh"},  # same prompt, other course
        ]
        factory, mocks = _cached_tables({"check_items": rows})
        with patch("services.check_item_service.table", side_effect=factory):
            assert [r["id"] for r in svc.item_rows_for([("c1", "qh")])] == ["i1"]
            assert svc.item_rows_for([]) == []

    def test_items_to_lint_reads_the_unlinted_or_all(self):
        from services import check_item_service as svc

        factory, mocks = _cached_tables({})
        with patch("services.check_item_service.table", side_effect=factory):
            list(svc.items_to_lint("c1"))
            unlinted = mocks["check_items"].select_with_count.call_args.kwargs["filters"]
            list(svc.items_to_lint(None, relint=True))
            every = mocks["check_items"].select_with_count.call_args.kwargs["filters"]
        assert unlinted == {"course_id": "eq.c1", "lint_flags": "is.null"}
        assert every == {}

    def test_lint_update_is_none_when_nothing_changes(self):
        from services.check_item_service import lint_update

        assert lint_update(_stored(lint=[])) is None
        assert lint_update(_stored()) == []  # never linted → write the clean answer
        assert lint_update(_stored(prompt="Which is false?", lint=[])) == [item_lint.NEGATIVE_STEM]


# ── learning/item_reports ──────────────────────────────────────────────────


class TestReportStore:
    def test_record_report_is_one_database_decision(self):
        with patch(
            "learning.item_reports.rpc",
            return_value=[{"first_report": True, "reporters": 2, "quarantine": True}],
        ) as rpc:
            out = item_reports.record_report("u1", "c1", "qh", reason="wrong_answer", surface="loop")
        assert out == item_reports.ReportOutcome(first=True, reporters=2, quarantine=True)
        name, args = rpc.call_args.args
        assert name == "check_item_report_quarantine"  # A123: reports never retire
        assert args == {
            "p_user_id": "u1",
            "p_course_id": "c1",
            "p_question_hash": "qh",
            "p_reason": "wrong_answer",
            "p_surface": "loop",
            "p_min_reporters": params.ITEM_REPORT_QUARANTINE_MIN_REPORTERS,
        }

    def test_record_report_raises_when_the_store_does_not_answer(self):
        with patch("learning.item_reports.rpc", return_value=[]), pytest.raises(
            item_reports.StoreUnavailable
        ):
            item_reports.record_report("u1", "c1", "qh", reason="unclear", surface="review")
        with pytest.raises(ValueError):
            item_reports.record_report("u1", "c1", "qh", reason="free text", surface="loop")

    def test_decide(self):
        with patch(
            "learning.item_reports.rpc", return_value=[{"previous": "retired", "applied": False}]
        ) as rpc:
            out = item_reports.decide("c1", "qh", "approved", reviewed_by="admin-1")
        assert out == item_reports.Decision(previous="retired", applied=False)
        assert rpc.call_args.args == (
            "check_item_review_decide",
            {"p_course_id": "c1", "p_question_hash": "qh", "p_status": "approved", "p_reviewed_by": "admin-1"},
        )
        with pytest.raises(ValueError):
            item_reports.decide("c1", "qh", "deleted", reviewed_by="admin-1")

    def test_report_counts_by_reason(self):
        rows = [
            {"course_id": "c1", "question_hash": "q", "reason": "wrong_answer", "created_at": "2026-11-08T10:00:00+00:00"},
            {"course_id": "c1", "question_hash": "q", "reason": "wrong_answer", "created_at": "2026-11-08T11:00:00Z"},
            {"course_id": "c1", "question_hash": "q", "reason": "unclear", "created_at": "2026-11-08T09:00:00+00:00"},
            {"course_id": "c2", "question_hash": "q", "reason": "not_from_my_course", "created_at": None},
        ]
        factory, _ = _cached_tables({"check_item_reports": rows})
        with patch("learning.item_reports.table", side_effect=factory):
            counts = item_reports.report_counts()
        one = counts[("c1", "q")]
        assert (one["wrong_answer"], one["unclear"], one["not_from_my_course"], one["total"]) == (2, 1, 0, 3)
        assert one["last_reported_at"] == datetime(2026, 11, 8, 11, tzinfo=timezone.utc)
        assert counts[("c2", "q")]["last_reported_at"] is None

    def test_reported_hashes_reads_the_students_reports(self):
        from learning import loop_state_store

        factory, mocks = _cached_tables({"check_item_reports": [{"question_hash": "q1"}, {"question_hash": "q2"}]})
        with patch("learning.loop_state_store.table", side_effect=factory):
            assert loop_state_store.reported_hashes("u1") == {"q1", "q2"}
        kwargs = mocks["check_item_reports"].select_with_count.call_args.kwargs
        assert kwargs["filters"] == {"user_id": "eq.u1"} and kwargs["order"] == "question_hash"


def _row(item_id, qh, *, flags=(), course="c1"):
    return {
        "id": item_id, "course_id": course, "concept_key": "k", "question_hash": qh,
        "format": "mc_reason", "difficulty": 2, "lint_flags": list(flags),
    }


def _count(total=1, *, at=NOW, reason="wrong_answer"):
    return {**dict.fromkeys(params.ITEM_REPORT_REASONS, 0), reason: total, "total": total, "last_reported_at": at}


class TestQueue:
    def test_membership(self):
        rows = [
            _row("clean", "q0"),
            _row("flagged", "q1", flags=["negative_stem"]),
            _row("reported", "q2"),
            _row("approved", "q3", flags=["correct_longest"]),
            _row("reopened", "q4"),
            _row("pending", "q5"),
        ]
        counts = {
            ("c1", "q2"): _count(),
            ("c1", "q4"): _count(at=NOW),
        }
        decisions = {
            ("c1", "q3"): {"status": "approved", "reviewed_at": (NOW - timedelta(days=1)).isoformat()},
            ("c1", "q4"): {"status": "approved", "reviewed_at": (NOW - timedelta(hours=1)).isoformat()},
            ("c1", "q5"): {"status": "retired", "reviewed_at": NOW.isoformat()},
        }
        entries = item_reports.queue_entries(rows, counts, decisions)
        assert [e["id"] for e in entries] == ["pending", "reopened", "reported", "flagged"]
        pending, reopened, reported, flagged = entries
        assert pending["retire_pending"] is True and pending["status"] == "retired"
        assert reopened["reports"]["total"] == 1  # a report after the approval re-opens it
        assert reported["reports"] == {**dict.fromkeys(params.ITEM_REPORT_REASONS, 0), "wrong_answer": 1, "total": 1}
        assert reported["last_reported_at"] == NOW.isoformat()
        assert flagged["lint_flags"] == ["negative_stem"] and flagged["reports"]["total"] == 0

    def test_an_approval_after_the_last_report_clears_it(self):
        rows = [_row("i", "q", flags=["negative_stem"])]
        counts = {("c1", "q"): _count(at=NOW - timedelta(hours=2))}
        decisions = {("c1", "q"): {"status": "approved", "reviewed_at": NOW.isoformat()}}
        assert item_reports.queue_entries(rows, counts, decisions) == []

    def test_a_quarantined_item_is_a_held_one_listed_after_the_retire_pending(self):
        """A123 on A124's hold: an item its reporters quarantined carries the
        database's `reports_threshold` code, so it is `held` — listed after an
        unfinished retire, before the merely reported, whatever an older
        approval said — until staff decide; the approval drops the code (the
        database's), and then it clears like any approval."""
        rows = [
            _row("reported", "q1"),
            _row("quarantined", "q2", flags=["negative_stem", "reports_threshold"]),
            _row("pending", "q3", flags=["staff_retired"]),
        ]
        counts = {("c1", "q1"): _count(3), ("c1", "q2"): _count(2)}
        decisions = {
            ("c1", "q2"): {"status": "quarantined", "reviewed_at": NOW.isoformat()},
            ("c1", "q3"): {"status": "retired", "reviewed_at": NOW.isoformat()},
        }
        entries = item_reports.queue_entries(rows, counts, decisions)
        assert [e["id"] for e in entries] == ["pending", "quarantined", "reported"]
        assert [e["held"] for e in entries] == [True, True, False]
        assert entries[1]["status"] == "quarantined" and "quarantined" not in entries[1]
        # a key the solve confirmed does not lift a staff hold
        verified = [{**rows[1], "canonical_verified": True}]
        assert item_reports.queue_entries(verified, counts, decisions)[0]["held"] is True
        # a quarantine whose code is not read back yet still waits for staff: its reports list it
        bare = [_row("quarantined", "q2")]
        (entry,) = item_reports.queue_entries(bare, counts, decisions)
        assert entry["held"] is False and entry["status"] == "quarantined"
        approved = {("c1", "q2"): {"status": "approved", "reviewed_at": (NOW + timedelta(hours=1)).isoformat()}}
        assert item_reports.queue_entries([_row("quarantined", "q2")], counts, approved) == []

    def test_review_statuses_reads_the_pending_and_final_decisions(self):
        reviews = [
            {"question_hash": "q1", "status": "quarantined"},
            {"question_hash": "q2", "status": "retired"},
            {"question_hash": "q3", "status": "approved"},  # never asked for; ignored if served
        ]
        factory, mocks = _cached_tables({"check_item_reviews": reviews})
        with patch("learning.item_reports.table", side_effect=factory):
            assert item_reports.review_statuses("c1", ["q2", "q1", "q3", ""]) == {
                "q1": "quarantined",
                "q2": "retired",
            }
        filters = mocks["check_item_reviews"].select.call_args.kwargs["filters"]
        assert filters == {
            "course_id": "eq.c1",
            "status": "in.(quarantined,retired)",
            "question_hash": 'in.("q1","q2","q3")',
        }

    def test_retired_items_are_the_staff_retires_only(self):
        rows = [{"course_id": "c1", "question_hash": "q1"}, {"course_id": "c2", "question_hash": "q1"}]
        factory, mocks = _cached_tables({"check_item_reviews": rows})
        with patch("learning.item_reports.table", side_effect=factory):
            assert item_reports.retired_items() == {("c1", "q1"), ("c2", "q1")}
        kwargs = mocks["check_item_reviews"].select_with_count.call_args.kwargs
        assert kwargs["filters"] == {"status": "eq.retired"}

    def test_order_most_reported_then_latest_then_most_flagged(self):
        rows = [
            _row("one-old", "q1"),
            _row("one-new", "q2"),
            _row("two", "q3"),
            _row("flags2", "q4", flags=["correct_longest", "negative_stem"]),
            _row("flags1", "q5", flags=["negative_stem"]),
        ]
        counts = {
            ("c1", "q1"): _count(at=NOW - timedelta(days=1)),
            ("c1", "q2"): _count(at=NOW),
            ("c1", "q3"): _count(2, at=NOW - timedelta(days=3)),
        }
        entries = item_reports.queue_entries(rows, counts, {})
        assert [e["id"] for e in entries] == ["two", "one-new", "one-old", "flags2", "flags1"]


# ── review: a reported open entry is dropped ────────────────────────────────


def test_drop_reported_drops_only_an_unanswered_unclaimed_entry(monkeypatch):
    from learning import review
    from learning.policy import LoopState

    now = NOW
    state = LoopState(
        extra={
            "open": {
                "n1": {"item_id": "i1", "served_at": 0.0},
                "n2": {"item_id": "i2", "served_at": 0.0, "graded_at": 1.0},
                "n3": {"item_id": "i3", "served_at": 0.0, "claim": "c", "claim_at": now.timestamp()},
            }
        }
    )

    def update(session_id, mutate):
        mutate(state)
        return state

    monkeypatch.setattr(review, "update_loop_state", update)
    assert review.drop_reported("s1", "i1", now) is True
    assert review.drop_reported("s1", "i2", now) is False  # graded: its record stays
    assert review.drop_reported("s1", "i3", now) is False  # being graded
    assert set(state.extra["open"]) == {"n2", "n3"}


# ── the admin review queue (routes/admin_check_items.py) ────────────────────

ADMIN = "/api/admin/check-items"


@pytest.fixture
def admin_client(monkeypatch):
    import routes.admin_check_items as admin

    monkeypatch.setattr(admin, "require_admin", lambda request: None)
    monkeypatch.setattr(admin, "get_session_user_id", lambda request: "admin-1")
    events = []
    monkeypatch.setattr(admin, "log_event", lambda et, **kw: events.append({"event_type": et, **kw}))
    # spec §13 A123: an approval re-lints the course item's rows (a store write)
    relints = []
    monkeypatch.setattr(admin, "relint_course_item", lambda c, q: relints.append((c, q)) or 0)
    from main import app

    c = TestClient(app)
    c.events = events
    c.relints = relints
    return c


def _deny(request):
    raise HTTPException(status_code=403, detail="Admin access required")


@pytest.mark.parametrize("method,path", [("get", "/queue"), ("post", "/i1/approve"), ("post", "/i1/retire")])
def test_every_admin_endpoint_is_admin_only(monkeypatch, method, path):
    import routes.admin_check_items as admin

    monkeypatch.setattr(admin, "require_admin", _deny)
    touched = []
    monkeypatch.setattr(admin, "get_check_item", lambda i, **k: touched.append(i))
    monkeypatch.setattr(admin.item_reports, "report_counts", lambda: touched.append("reports"))
    from main import app

    r = getattr(TestClient(app), method)(ADMIN + path)
    assert r.status_code == 403 and touched == []


def test_the_queue_decrypts_only_its_page_at_the_read_boundary(admin_client, monkeypatch):
    import routes.admin_check_items as admin

    item = _stored(
        "q2",
        id="i2",
        options=_letters("the right one", "wrong one", "wrong two", "wrong three"),
        correct="A",
        prompt="Which one?",
    )
    monkeypatch.setattr(admin.item_reports, "report_counts", lambda: {("c1", "q2"): _count(2)})
    monkeypatch.setattr(admin.item_reports, "reviews", lambda: {})
    monkeypatch.setattr(admin, "flagged_item_rows", lambda: [_row("i1", "q1", flags=["negative_stem"])])
    asked = {}
    monkeypatch.setattr(admin, "item_rows_for", lambda keys: asked.setdefault("keys", set(keys)) and [_row("i2", "q2")])
    monkeypatch.setattr(admin, "QUEUE_PAGE", 1)
    seen = {}

    def items_by_ids(ids):
        seen["ids"] = list(ids)
        return [item]

    monkeypatch.setattr(admin, "items_by_ids", items_by_ids)
    body = admin_client.get(f"{ADMIN}/queue").json()
    assert asked["keys"] == {("c1", "q2")}
    assert body["count"] == 2 and body["page_size"] == 1
    assert body["quarantine_min_reporters"] == params.ITEM_REPORT_QUARANTINE_MIN_REPORTERS
    (entry,) = body["items"]
    assert seen["ids"] == ["i2"]  # only the page is decrypted
    assert entry["id"] == "i2" and entry["reports"]["wrong_answer"] == 2
    assert entry["prompt"] == "Which one?" and entry["final_answer"] == "the base case"
    assert [o["correct"] for o in entry["options"]] == [True, False, False, False]


def test_approve_records_the_decision_and_an_audit_event(admin_client, monkeypatch):
    import routes.admin_check_items as admin

    monkeypatch.setattr(admin, "get_check_item", lambda i, **k: _stored("qh-1", id=i))
    calls = []
    monkeypatch.setattr(
        admin.item_reports,
        "decide",
        lambda c, q, s, *, reviewed_by: calls.append((c, q, s, reviewed_by))
        or item_reports.Decision(previous=None, applied=True),
    )
    # spec §13 A124: an approval confirms the key (canonical_verified), after the decision
    monkeypatch.setattr(admin, "confirm_course_item", lambda c, q: calls.append(("confirm", c, q)))
    r = admin_client.post(f"{ADMIN}/i1/approve")
    assert r.status_code == 200 and r.json() == {"id": "i1", "status": "approved", "restored": False}
    assert calls == [("c1", "qh-1", "approved", "admin-1"), ("confirm", "c1", "qh-1")]
    assert admin_client.relints == [("c1", "qh-1")]  # A123: after the confirmation
    assert admin_client.events[0]["event_type"] == "learn.check_item_approved"
    assert admin_client.events[0]["category"] == "audit"
    assert admin_client.events[0]["payload"]["restored"] is False


@pytest.mark.parametrize("flag", ["reports_threshold", "key_disputed"])
def test_approving_a_held_item_restores_it(admin_client, monkeypatch, flag):
    """A123 on A124's hold: the approval lifts a quarantine (the database
    drops `reports_threshold` with the decision, under the item lock) as it
    lifts a key hold (the confirmation); the response and the audit event say
    the item is served again. The hold is read off the row staff decided on,
    before the decision."""
    import routes.admin_check_items as admin

    monkeypatch.setattr(admin, "get_check_item", lambda i, **k: _stored("qh-1", id=i, lint=[flag]))
    monkeypatch.setattr(
        admin.item_reports, "decide",
        lambda *a, **k: item_reports.Decision(previous="quarantined", applied=True),
    )
    monkeypatch.setattr(admin, "confirm_course_item", lambda c, q: None)
    r = admin_client.post(f"{ADMIN}/i1/approve")
    assert r.json() == {"id": "i1", "status": "approved", "restored": True}
    assert admin_client.events[0]["payload"] == {"course_id": "c1", "question_hash": "qh-1", "restored": True}


def test_a_failed_relint_is_a_503_finished_by_approving_again(admin_client, monkeypatch):
    import routes.admin_check_items as admin

    monkeypatch.setattr(admin, "get_check_item", lambda i, **k: _stored("qh-1", id=i))
    monkeypatch.setattr(admin.item_reports, "decide", lambda *a, **k: item_reports.Decision(None, True))
    monkeypatch.setattr(admin, "confirm_course_item", lambda c, q: None)

    def down(c, q):
        raise RuntimeError("down")

    monkeypatch.setattr(admin, "relint_course_item", down)
    r = admin_client.post(f"{ADMIN}/i1/approve")
    assert r.status_code == 503 and "approve it again" in r.json()["detail"]
    assert admin_client.events == []


def test_a_retired_item_cannot_be_approved(admin_client, monkeypatch):
    import routes.admin_check_items as admin

    monkeypatch.setattr(admin, "get_check_item", lambda i, **k: _stored("qh-1", id=i))
    monkeypatch.setattr(
        admin.item_reports,
        "decide",
        lambda *a, **k: item_reports.Decision(previous="retired", applied=False),
    )
    r = admin_client.post(f"{ADMIN}/i1/approve")
    assert r.status_code == 409 and admin_client.events == []


def test_retire_decides_then_retires_through_the_service(admin_client, monkeypatch):
    import routes.admin_check_items as admin

    order = []
    monkeypatch.setattr(admin, "get_check_item", lambda i, **k: _stored("qh-1", id=i))
    monkeypatch.setattr(
        admin.item_reports,
        "decide",
        lambda c, q, s, *, reviewed_by: order.append(("decide", s))
        or item_reports.Decision(previous=None, applied=True),
    )
    from services.check_item_service import RetireOutcome

    monkeypatch.setattr(
        admin, "retire_course_item",
        lambda c, q: order.append(("retire", c, q)) or RetireOutcome(items=2, students=3, voided=5),
    )
    r = admin_client.post(f"{ADMIN}/i1/retire")
    assert r.status_code == 200
    assert r.json() == {"id": "i1", "status": "retired", "items": 2, "students": 3, "voided": 5}
    assert order == [("decide", "retired"), ("retire", "c1", "qh-1")]  # decided BEFORE any void
    (event,) = admin_client.events
    assert event["event_type"] == "learn.check_item_retired"
    assert event["payload"] == {
        "course_id": "c1", "question_hash": "qh-1", "decided_by": "admin",
        "items": 2, "students": 3, "voided": 5,
    }


def test_a_failed_retire_is_a_503_and_the_decision_stands(admin_client, monkeypatch):
    import routes.admin_check_items as admin

    monkeypatch.setattr(admin, "get_check_item", lambda i, **k: _stored("qh-1", id=i))
    monkeypatch.setattr(
        admin.item_reports, "decide", lambda *a, **k: item_reports.Decision(None, True)
    )

    def boom(c, q):
        raise RuntimeError("down")

    monkeypatch.setattr(admin, "retire_course_item", boom)
    assert admin_client.post(f"{ADMIN}/i1/retire").status_code == 503
    assert admin_client.events == []


def test_an_unknown_item_is_404_and_a_store_failure_503(admin_client, monkeypatch):
    import routes.admin_check_items as admin

    monkeypatch.setattr(admin, "get_check_item", lambda i, **k: None)
    assert admin_client.post(f"{ADMIN}/gone/approve").status_code == 404
    monkeypatch.setattr(admin, "get_check_item", lambda i, **k: _stored("qh-1", id=i))

    def down(*a, **k):
        raise RuntimeError("rpc down")

    monkeypatch.setattr(admin.item_reports, "decide", down)
    assert admin_client.post(f"{ADMIN}/i1/approve").status_code == 503


def test_the_admin_router_is_mounted():
    from main import app
    from routes import admin_check_items

    prefixes = [
        r.include_context.prefix
        for r in app.routes
        if getattr(r, "include_context", None) is not None
        and r.include_context.included_router is admin_check_items.router
    ]
    assert prefixes == ["/api/admin/check-items"]


# ── the lint backfill (scripts/backfill_check_item_lint.py) ─────────────────


@pytest.fixture
def backfill(monkeypatch):
    import importlib
    import sys

    monkeypatch.setattr("dotenv.load_dotenv", lambda *a, **k: False)
    sys.modules.pop("scripts.backfill_check_item_lint", None)
    module = importlib.import_module("scripts.backfill_check_item_lint")
    monkeypatch.setattr(module, "_project_ref", lambda: "proj-a")
    yield module
    sys.modules.pop("scripts.backfill_check_item_lint", None)


def _backfill_items():
    return [
        _stored("q1", id="i1"),  # never linted, clean
        _stored("q2", id="i2", prompt="Which one is false?"),  # never linted, flagged
        _stored("q3", id="i3", lint=[]),  # already right: not written
    ]


def test_backfill_dry_run_writes_nothing(backfill, monkeypatch, capsys):
    reads = []
    monkeypatch.setattr(
        backfill, "items_to_lint", lambda course, *, relint: reads.append((course, relint)) or iter(_backfill_items())
    )
    writes = []
    monkeypatch.setattr(backfill, "store_lint_flags", lambda flags, ids: writes.append((flags, ids)))
    assert backfill.main([]) == 0
    out = capsys.readouterr().out
    assert out.splitlines()[0] == "Project: proj-a"
    assert "3 row(s) read; 2 to write (1 clean, 1 flagged) — dry run" in out
    assert "negative_stem: 1" in out
    assert "Which one is false" not in out  # never item text
    assert writes == [] and reads == [(None, False)]


def test_backfill_apply_writes_each_flag_set_once(backfill, monkeypatch, capsys):
    monkeypatch.setattr(backfill, "items_to_lint", lambda course, *, relint: iter(_backfill_items()))
    writes = []
    monkeypatch.setattr(backfill, "store_lint_flags", lambda flags, ids: writes.append((flags, list(ids))))
    assert backfill.main(["--apply", "--course", "c1", "--relint"]) == 0
    assert sorted(writes) == [((), ["i1"]), (("negative_stem",), ["i2"])]
    assert "Done: 2 row(s) written, 0 failed" in capsys.readouterr().out


def test_backfill_reads_everything_before_writing_and_exits_1_on_a_failure(backfill, monkeypatch):
    """The default read pages `lint_flags IS NULL`; a write mid-read would move
    rows out from under the offset paging. Every write waits for the read."""
    log = []

    def items(course, *, relint):
        for item in _backfill_items():
            log.append(("read", item.id))
            yield item

    def store(flags, ids):
        log.append(("write", tuple(ids)))
        raise RuntimeError("down")

    monkeypatch.setattr(backfill, "items_to_lint", items)
    monkeypatch.setattr(backfill, "store_lint_flags", store)
    assert backfill.main(["--apply"]) == 1
    first_write = next(i for i, entry in enumerate(log) if entry[0] == "write")
    assert all(entry[0] == "read" for entry in log[:first_write]) and len(log[:first_write]) == 3

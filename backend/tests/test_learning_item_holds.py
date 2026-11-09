"""Spec §13 A123 folded into A124's hold: a report-threshold quarantine and a
staff retire are HOLDS — reason codes in check_items.lint_flags
(`reports_threshold`, `staff_retired`) that every student read drops through
the one predicate (learning/checks.py held_flags / is_servable) — not a second
"never served" state. Here: the predicate, the student reads, the flag
rewrites that must keep the codes, the queue's read of them, the approval's
re-lint, and the migration's derivation and trigger as SQL text. What the
database decides with them (the report/decision functions, the trigger, the
races) is tests/integration/test_check_item_reports_db.py's, on the real
database."""

from __future__ import annotations

import pathlib
import re
from unittest.mock import patch

import pytest

from learning.checks import (
    HOLD_FLAGS,
    KEY_DISPUTED,
    KEY_HOLD_FLAGS,
    REPORTS_THRESHOLD,
    STAFF_HOLD_FLAGS,
    STAFF_RETIRED,
    held,
    held_flags,
    is_servable,
    key_held,
    states_final_answer,
)
from tests.test_learning_check_items import _cached_tables, _item
from tests.test_learning_item_keys import _row

MIG_DIR = pathlib.Path(__file__).resolve().parents[1] / "db" / "migrations"


def _migration() -> str:
    (path,) = sorted(MIG_DIR.glob("*_learning_evidence_void.sql"))
    return path.read_text()


class TestThePredicate:
    def test_a_staff_hold_holds_whatever_the_key_says(self):
        for code in STAFF_HOLD_FLAGS:
            for verified in (False, True):
                item = _item(lint_flags=["negative_stem", code], canonical_verified=verified)
                assert held(item) and not is_servable(item) and states_final_answer(item)
                # the key's own status is untouched (A124's key_status / key_held)
                assert not key_held(item)

    def test_held_is_a_staff_hold_or_an_unconfirmed_key_hold(self):
        assert HOLD_FLAGS == (*KEY_HOLD_FLAGS, REPORTS_THRESHOLD, STAFF_RETIRED)
        assert held_flags([KEY_DISPUTED], False) and not held_flags([KEY_DISPUTED], True)
        assert held_flags([REPORTS_THRESHOLD], True) and held_flags([STAFF_RETIRED], True)
        assert not held_flags(["negative_stem", "concept_retagged"], False)
        assert not held_flags(None, False) and not held_flags([], True)

    def test_selection_never_serves_a_staff_held_item(self):
        from learning.checks import posttest_reserve_hash, select_item

        quarantined = _item(id="q", prompt="Quarantined?", lint_flags=[REPORTS_THRESHOLD], canonical_verified=True)
        kept = _item(id="kept", prompt="Kept one?", difficulty=3)
        assert select_item([quarantined, kept], format="free", difficulty=1).id == "kept"
        assert select_item([quarantined], format="free", difficulty=1) is None
        assert posttest_reserve_hash([quarantined]) is None

    def test_the_served_scan_still_covers_a_quarantined_item(self):
        """One posed before its quarantine must not leak its answer either."""
        from learning.served_scan import ScanSet

        quarantined = _item(lint_flags=[REPORTS_THRESHOLD])
        assert ScanSet.build([quarantined], given="").hashes == [quarantined.question_hash]


class TestRewritesKeepTheCodes:
    """Every Python write of lint_flags keeps a staff-hold code it read (the
    database's trigger restores one regardless; keeping it means no rewrite
    ever fights the trigger, and the code order is the stored one)."""

    def test_merge_flags_orders_staff_holds_last(self):
        from learning.item_alignment import kept_flags, merge_flags

        assert merge_flags([REPORTS_THRESHOLD, "negative_stem"], [KEY_DISPUTED, "concept_retagged"]) == [
            "negative_stem",
            "concept_retagged",
            KEY_DISPUTED,
            REPORTS_THRESHOLD,
        ]
        assert kept_flags(["negative_stem", STAFF_RETIRED, KEY_DISPUTED]) == [KEY_DISPUTED, STAFF_RETIRED]

    def test_a_relint_a_key_check_and_an_audit_keep_a_staff_hold(self):
        from learning.item_keys import KeyCheck, audited_flags, checked_flags
        from services.check_item_service import lint_update

        assert lint_update(_item(lint_flags=[REPORTS_THRESHOLD])) is None  # nothing to write: kept
        flawed = _item(prompt="Which statement is false?", lint_flags=[STAFF_RETIRED])
        assert lint_update(flawed) == ["negative_stem", STAFF_RETIRED]
        agreed = KeyCheck(verified=True, flag=None)
        assert checked_flags(["negative_stem", REPORTS_THRESHOLD], agreed) == ["negative_stem", REPORTS_THRESHOLD]
        assert audited_flags([REPORTS_THRESHOLD], "key_audit_wrong") == ["key_audit_wrong", REPORTS_THRESHOLD]


class TestStudentReads:
    def _tables(self, *items):
        return _cached_tables({"check_items": [_row(i) for i in items]})

    def test_every_student_read_drops_a_quarantined_item_even_with_a_confirmed_key(self):
        from services import check_item_service as svc

        quarantined = _item(
            id="q", prompt="Quarantined?", concept_key="recursion",
            lint_flags=[REPORTS_THRESHOLD], canonical_verified=True,
        )
        kept = _item(id="kept", prompt="Kept?", concept_key="recursion")
        factory, _ = self._tables(quarantined, kept)
        with patch("services.check_item_service.table", side_effect=factory):
            assert [i.id for i in svc.list_items("c1", "recursion")] == ["kept"]
            assert [i.id for i in svc.items_for_concepts("c1", ["recursion"])["recursion"]] == ["kept"]
        factory, _ = self._tables(quarantined)
        with patch("services.check_item_service.table", side_effect=factory):
            assert svc.get_check_item("q") is None  # withdrawn for the loop, review and post-test
            assert svc.get_check_item("q", include_held=True).id == "q"  # the admin's read
            assert [i.id for i in svc.items_by_ids(["q"])] == ["q"]  # the scan keeps it

    def test_course_has_items_counts_no_staff_held_item(self):
        from services import check_item_service as svc

        retired = {"id": "r", "lint_flags": [STAFF_RETIRED], "canonical_verified": True}
        factory, _ = _cached_tables({"check_items": [retired]})
        with patch("services.check_item_service.table", side_effect=factory):
            assert svc.course_has_items("c1") is False

    def test_the_queue_reads_the_staff_hold_codes(self):
        from services import check_item_service as svc

        assert set(HOLD_FLAGS) <= set(svc.QUEUE_FLAGS)
        factory, mocks = _cached_tables({"check_items": []})
        with patch("services.check_item_service.table", side_effect=factory):
            svc.flagged_item_rows()
        overlap = mocks["check_items"].select_with_count.call_args.kwargs["filters"]["lint_flags"]
        for flag in STAFF_HOLD_FLAGS:
            assert f'"{flag}"' in overlap


class TestRelint:
    def test_an_approval_lints_a_never_linted_row_a_quarantine_left_empty(self):
        """A NULL row a quarantine held carries [] once the hold is lifted,
        which reads "linted clean"; the approval's re-lint makes that true —
        and writes nothing for a row whose stored codes are already right."""
        from services import check_item_service as svc

        emptied = _item(id="e", prompt="Which statement is false?", lint_flags=[])
        # stored under an older linter: brought to the current linter's codes too
        stale = _item(id="r", prompt="Right?", lint_flags=["negative_stem"])
        clean = _item(id="c", prompt="Clean?", lint_flags=[])
        factory, mocks = self._tables(emptied, stale, clean)
        with patch("services.check_item_service.table", side_effect=factory):
            assert svc.relint_course_item("c1", emptied.question_hash) == 2
        writes = {
            c.kwargs["filters"]["id"]: c.args[0]["lint_flags"]
            for c in mocks["check_items"].update.call_args_list
        }
        assert writes == {'in.("e")': ["negative_stem"], 'in.("r")': []}
        read = mocks["check_items"].select.call_args.kwargs["filters"]
        assert read == {"course_id": "eq.c1", "question_hash": f"eq.{emptied.question_hash}"}

    def _tables(self, *items):
        return _cached_tables({"check_items": [_row(i) for i in items]})


class TestTheMigration:
    """The derivation and its trigger, as SQL text (their behaviour on a real
    database: tests/integration/test_check_item_reports_db.py)."""

    def test_the_codes_match_the_python_ones(self):
        sql = _migration()
        derive = sql.split("FUNCTION check_item_hold_flags(", 1)[1].split("$$;", 1)[0]
        assert f"'{REPORTS_THRESHOLD}'" in derive and f"'{STAFF_RETIRED}'" in derive
        assert "WHEN 'quarantined' THEN" in derive and "WHEN 'retired' THEN" in derive
        assert "IMMUTABLE" in derive

    def test_the_trigger_rederives_on_every_insert_and_flag_write(self):
        sql = _migration()
        assert (
            "BEFORE INSERT OR UPDATE OF lint_flags, course_id, question_hash ON check_items\n"
            "  FOR EACH ROW EXECUTE FUNCTION check_items_staff_hold();"
        ) in sql
        body = sql.split("FUNCTION check_items_staff_hold()", 1)[1].split("$$;", 1)[0]
        # a row joining a course item waits for a decision in flight (shared vs exclusive)
        lock = "pg_advisory_xact_lock_shared(\n      hashtextextended('check-item-review:' || NEW.course_id"
        assert lock in body
        assert "IF TG_OP = 'INSERT' OR NEW.course_id IS DISTINCT FROM OLD.course_id" in body
        assert "NEW.lint_flags := check_item_hold_flags(NEW.lint_flags, v_status);" in body

    @pytest.mark.parametrize(
        "function,status",
        [("check_item_report_quarantine(", "'quarantined'"), ("check_item_review_decide(", "p_status")],
    )
    def test_the_decision_holds_its_rows_in_its_own_transaction(self, function, status):
        body = _migration().split(f"FUNCTION {function}", 1)[1].split("$$;", 1)[0]
        update = re.search(r"UPDATE check_items c\s+SET lint_flags = check_item_hold_flags\(c\.lint_flags, (\S+)\)", body)
        assert update and update.group(1) == status
        assert body.index("pg_advisory_xact_lock(") < body.index("UPDATE check_items")

    def test_the_backfill_rederives_every_decided_row(self):
        sql = _migration()
        assert (
            "UPDATE check_items c\n   SET lint_flags = check_item_hold_flags(c.lint_flags, r.status)\n"
            "  FROM check_item_reviews r"
        ) in sql
        assert sql.index("CREATE TRIGGER check_items_staff_hold") < sql.index("FROM check_item_reviews r\n WHERE r.course_id = c.course_id")

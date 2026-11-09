"""A SQL function re-created by a later migration keeps every earlier change
(learning-loop spec §13 A123 × A127).

`CREATE OR REPLACE FUNCTION` replaces the whole body. Migrations apply in
filename order, so the LAST definition of a function is what the database
runs. A migration written on an older base drops what a branch merged in
between added: A127's 20261108092032 re-created learning_evidence_commit from
the pre-A123 body, which, applied after A123's 20261108072715, removed A123's
shared item lock and its refusal of a retired item's grade, and refused
A123's journaled replay keys outright. 20261108103333 reconciles the two.

REGISTRY lists, for every function (name and arity) that a migration from the
wave-2 day on (2026-11-08) defines and that is defined more than once, the
change EACH defining migration made: substrings its body must keep (`requires`)
and, for a change that removed something, substrings it must not bring back
(`forbids`). The tests below fail when:
  - a function in scope is missing from the registry, or a migration defines
    it without an entry (a new re-definition must declare its change here);
  - an entry's markers are not what that migration's definition says (so no
    entry is vacuous);
  - the last definition drops a required marker or brings back a forbidden one.
Markers are matched in the body with SQL line comments removed, so a comment
can never satisfy one.
"""

from __future__ import annotations

import pathlib
import re
from typing import NamedTuple

MIGRATIONS = pathlib.Path(__file__).resolve().parents[1] / "db" / "migrations"
#: Definitions from this day on are in scope (the wave-2 migrations, and the
#: base's checklist-budget fix of the same day).
WAVE2_START = "20261108000000"


class Change(NamedTuple):
    requires: tuple[str, ...] = ()
    forbids: tuple[str, ...] = ()


REGISTRY: dict[tuple[str, int], dict[str, Change]] = {
    # main's Canopy metrics (not a loop function): in scope because main's
    # wave 2 re-created it on 2026-11-08 (#116/#119). Each definition is the
    # previous one plus its own change, copied verbatim.
    ("canopy_metrics", 0): {
        "20260921055024_canopy_metrics.sql": Change(
            requires=("'active_users'", "'counts'", "'totals'", "'llm_cost_cents'"),
        ),
        # #760: completed quizzes count only scored attempts
        "20261106055333_state_machines_audit.sql": Change(
            requires=("WHERE completed_at >= now() - interval '30 days' AND score IS NOT NULL",),
        ),
        # #116/#119: the job-queue and weekly LLM-cost numbers
        "20261108213623_jobs_upkeep.sql": Change(
            requires=(
                "'jobs_dead_lettered'",
                "'jobs_queue_depth'",
                "public.llm_cost_per_active_user_weekly()",
                "jsonb_strip_nulls(jsonb_build_object(",
            ),
        ),
    },
    ("learning_evidence_commit", 5): {
        "20261019131339_learning_evidence_transaction.sql": Change(
            requires=(
                "INSERT INTO learning_evidence_operations",
                "RETURN learning_evidence_receipt(p_user_id,p_operation_id)",
                "'Invalid transaction evidence'",
            )
        ),
        "20261019141950_learning_evidence_forward_repair.sql": Change(
            requires=(
                "'observations'",
                "'Invalid exposure snapshot'",
                "evidence_touch_at=greatest(learner_state.evidence_touch_at,EXCLUDED.evidence_touch_at)",
            )
        ),
        # A123: the shared item lock, the retired refusal, the replay keys
        "20261108072715_learning_evidence_void.sql": Change(
            requires=(
                "pg_advisory_xact_lock_shared(",
                "hashtextextended('check-item-review:'",
                "cr.status='retired'",
                "jsonb_build_object('status','retired','items',retired_items)",
                "'retention','same_session_recheck','propagated_to'",
                "ev.retention,ev.same_session_recheck,ev.propagated_to",
            )
        ),
        # A127: the student's stated confidence, admitted, checked, journaled
        "20261108092032_learning_student_confidence.sql": Change(
            requires=(
                "'student_confidence'",
                "ev.student_confidence BETWEEN 0 AND 1",
                "ev.student_confidence)",
            )
        ),
        # A123 × A127: the union of the two above; it adds nothing of its own
        "20261108103333_learning_evidence_commit_reconcile.sql": Change(),
        # A141: a multi-concept item's row says so, admitted, checked, journaled
        "20261108205812_learning_varied_practice_review.sql": Change(
            requires=(
                "'multi_concept'))",
                "jsonb_typeof(x->'multi_concept') NOT IN ('boolean','null')",
                "ev.multi_concept,",
            )
        ),
    },
    ("check_item_report", 6): {
        # A113 — its signature, kept for a backend deployed before A123. Its
        # auto-retire at the reporters' threshold was superseded by A123 (a
        # report quarantines, never retires), so it is not required.
        "20261108041639_learning_item_quality.sql": Change(
            requires=("RETURNS TABLE (first_report boolean, reporters integer, retire boolean)",)
        ),
        "20261108072715_learning_evidence_void.sql": Change(
            requires=("check_item_report_quarantine(",),
            forbids=("'retired', 'reports'",),  # reports never retire an item
        ),
    },
    ("check_item_report_quarantine", 6): {
        # A123: the report that reaches the threshold quarantines (the hold)
        "20261108072715_learning_evidence_void.sql": Change(
            requires=(
                "pg_advisory_xact_lock(",
                "hashtextextended('check-item-review:'",
                "'Invalid check item report'",
                "check_item_hold_flags(c.lint_flags, 'quarantined')",
                "AND v_status IS DISTINCT FROM 'retired'",
            )
        ),
        # A142: one report per (student, course item), not per hash
        "20261108193927_learning_report_course_key.sql": Change(
            requires=("ON CONFLICT (user_id, course_id, question_hash) DO NOTHING",),
            forbids=("ON CONFLICT (user_id, question_hash)",),
        ),
    },
    ("check_item_review_decide", 4): {
        "20261108041639_learning_item_quality.sql": Change(
            requires=(
                "pg_advisory_xact_lock(",
                "hashtextextended('check-item-review:'",
                "'Invalid check item review'",
                "applied := NOT (v_prev IS NOT DISTINCT FROM 'retired' AND p_status = 'approved')",
            )
        ),
        # A123: approved_at, and the staff hold derived on the decision
        "20261108072715_learning_evidence_void.sql": Change(
            requires=("approved_at", "check_item_hold_flags(c.lint_flags, p_status)")
        ),
    },
    ("misconception_record", 6): {
        "20260929143810_learning_misconceptions_atomic.sql": Change(
            requires=("RETURNS TABLE (id text, count int)",)
        ),
        # A123: the six-argument form looks the item's hash up and goes through
        # the seven-argument one (the retired refusal, the recorded attempt)
        "20261108072715_learning_evidence_void.sql": Change(
            requires=("(SELECT ci.question_hash FROM check_items ci WHERE ci.id = p_check_item_id)",)
        ),
    },
    ("misconception_record", 7): {
        # A123: the retired-item refusal under the shared item lock, and the
        # supporting attempt row the void closure reads
        "20261108072715_learning_evidence_void.sql": Change(
            requires=(
                "pg_advisory_xact_lock_shared(",
                "AND r.status = 'retired'",
                "INSERT INTO misconception_attempts",
                "ON CONFLICT (user_id, node_id, wrong_key) WHERE resolved_at IS NULL",
            )
        ),
        # A142: nothing is recorded on a node the student does not own
        "20261108193927_learning_report_course_key.sql": Change(
            requires=("WHERE g.id = p_node_id AND g.user_id = p_user_id", "IF v_owned IS NOT TRUE THEN")
        ),
    },
    ("checklist_budget_admit", 9): {
        "20261019125459_checklist_budget.sql": Change(
            requires=("WHERE e.id=p_enrollment_id AND e.user_id=p_user_id",)
        ),
        "20261108033310_checklist_budget_no_course_soft_delete.sql": Change(
            forbids=("c.deleted_at IS NULL",)
        ),
    },
    ("checklist_budget_start", 3): {
        "20261019125459_checklist_budget.sql": Change(
            requires=("WHERE e.id=r.enrollment_id AND e.user_id=p_user_id",)
        ),
        "20261108033310_checklist_budget_no_course_soft_delete.sql": Change(
            forbids=("c.deleted_at IS NULL",)
        ),
    },
    ("posttest_anchors", 5): {
        # A126: each concept's first evidence time, one row per node, keyset-paged
        "20261108093359_learning_posttest_outcomes.sql": Change(
            requires=(
                "min(e.created_at)",
                "e.event_type = 'evidence'",
                "g.course_id IS NOT NULL",
                "LEAST(GREATEST(coalesce(p_limit, 1000), 1), 1000)",
            )
        ),
        # A123 × A126: a void row never anchors (evidence_spans' rule)
        "20261108105254_learning_posttest_anchors_void.sql": Change(
            requires=("AND NOT EXISTS (SELECT 1 FROM learning_evidence_voids v WHERE v.event_id = e.id)",)
        ),
    },
    ("checklist_budget_reconcile", None): {},  # arity filled below
}

_HEAD = re.compile(
    r"CREATE\s+(?:OR\s+REPLACE\s+)?FUNCTION\s+(?:public\.)?([A-Za-z_][A-Za-z0-9_]*)\s*\(", re.I
)
_DOLLAR = re.compile(r"\$([A-Za-z_]*)\$")


def _strip_comments(sql: str) -> str:
    return re.sub(r"--[^\n]*", "", sql)


def _arity(sql: str, open_paren: int) -> tuple[int, int]:
    """(number of parameters, index after the closing paren)."""
    depth, i, params, current = 0, open_paren, 0, ""
    while True:
        ch = sql[i]
        if ch == "(":
            depth += 1
            if depth > 1:
                current += ch
        elif ch == ")":
            depth -= 1
            if depth == 0:
                if current.strip():
                    params += 1
                return params, i + 1
            current += ch
        elif ch == "," and depth == 1:
            params += 1
            current = ""
        else:
            current += ch
        i += 1


def definitions() -> dict[tuple[str, int], list[tuple[str, str]]]:
    """(name, arity) -> [(migration, definition text)] in apply order."""
    out: dict[tuple[str, int], list[tuple[str, str]]] = {}
    for path in sorted(MIGRATIONS.glob("*.sql")):
        sql = _strip_comments(path.read_text())
        for m in _HEAD.finditer(sql):
            arity, after = _arity(sql, m.end() - 1)
            opener = _DOLLAR.search(sql, after)
            close = sql.index(opener.group(0), opener.end())
            text = sql[m.start() : close + len(opener.group(0))]
            out.setdefault((m.group(1).lower(), arity), []).append((path.name, text))
    return out


def _in_scope(defs) -> set[tuple[str, int]]:
    return {
        key
        for key, where in defs.items()
        if len(where) > 1 and any(name >= WAVE2_START for name, _ in where)
    }


def _registry(defs) -> dict[tuple[str, int], dict[str, Change]]:
    """REGISTRY with checklist_budget_reconcile's arity read from its definition
    (one signature; its parameter list spans several lines)."""
    reg = {key: value for key, value in REGISTRY.items() if key[1] is not None}
    [(name, arity)] = [key for key in defs if key[0] == "checklist_budget_reconcile"]
    reg[(name, arity)] = {
        "20261019125459_checklist_budget.sql": Change(requires=("FOR SHARE OF e,o,c",)),
        "20261108033310_checklist_budget_no_course_soft_delete.sql": Change(
            forbids=("c.deleted_at IS NULL",)
        ),
    }
    return reg


def test_every_function_redefined_from_the_wave2_day_is_registered():
    defs = definitions()
    assert _in_scope(defs) == set(_registry(defs)), (
        "a function re-created by a migration from 2026-11-08 on is not in REGISTRY "
        "(or one in REGISTRY no longer is): list each defining migration's change"
    )


def test_every_definition_has_an_entry_and_every_entry_a_definition():
    defs = definitions()
    for key, entries in _registry(defs).items():
        assert [name for name, _ in defs[key]] == sorted(entries), key


def test_each_change_is_what_its_own_migration_defines():
    defs = definitions()
    for key, entries in _registry(defs).items():
        bodies = dict(defs[key])
        for migration, change in entries.items():
            for marker in change.requires:
                assert marker in bodies[migration], (key, migration, marker)
            for marker in change.forbids:
                assert marker not in bodies[migration], (key, migration, marker)


def test_the_last_definition_keeps_every_earlier_change():
    defs = definitions()
    for key, entries in _registry(defs).items():
        last_migration, last = defs[key][-1]
        for migration, change in entries.items():
            for marker in change.requires:
                assert marker in last, (
                    f"{key[0]}: {last_migration} drops {marker!r}, added by {migration}"
                )
            for marker in change.forbids:
                assert marker not in last, (
                    f"{key[0]}: {last_migration} brings back {marker!r}, removed by {migration}"
                )


def test_the_parser_reads_signatures_and_bodies():
    sql = (
        "CREATE OR REPLACE FUNCTION f(a text, b numeric(10,2)) RETURNS int "
        "LANGUAGE sql AS $fn$ SELECT 1 $fn$;\n-- CREATE FUNCTION g(x int) AS $$ $$;\n"
        "CREATE FUNCTION public.g() RETURNS void AS $$ BEGIN END $$;"
    )
    stripped = _strip_comments(sql)
    found = [(m.group(1), _arity(stripped, m.end() - 1)[0]) for m in _HEAD.finditer(stripped)]
    assert found == [("f", 2), ("g", 0)]


def test_the_post_test_anchors_leave_the_void_record_out_in_both_branches():
    """A123 × A126: the student branch and the all-students branch of the
    function the database runs both skip a void row, as
    loop_state_store.evidence_spans and the trial export's anchors do."""
    (_, last) = definitions()[("posttest_anchors", 5)][-1]
    assert last.count("NOT EXISTS (SELECT 1 FROM learning_evidence_voids v WHERE v.event_id = e.id)") == 2

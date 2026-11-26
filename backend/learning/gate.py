"""The learning-loop gate (spec §7, §13 A14): is the loop on for this student?

Two switches, both must say yes:

- the env kill switch, `config.LEARNING_LOOP_ENABLED` (false/0/off/no turns the
  loop off for everyone; unset means the switch is not thrown). Read first: when
  it is thrown the answer is False with no read of any kind, so the kill switch
  costs nothing and reaches no database;
- the student's `learning_loop` feature flag (services/feature_flags.py
  REGISTRY; default off, client-visible). The owner turns it on from the admin
  Flags page: their own account, then a class, then everyone.

Off either way is the pre-loop app for that student, byte for byte: the loop
routes 404, the legacy tutor runs, nothing of the loop is read or written and
no loop model runs. No student (an anonymous request, the backfill's system
actor) is off.

Per request, once (owner decision 00): a route resolves the gate at entry and
carries the answer (`request.state.learning_loop`, `SaplingDeps.learning_loop`).
The flag resolver reads the flag store on a cold snapshot, so an `async def`
route reaches the gate through a worker thread (`run_in_threadpool`), never on
the event loop; a sync route (FastAPI's threadpool) calls it directly.

Work with no student request (the upload's check-item drafting, on the request
or the job queue) is the UPLOADER's: `learning_loop_for_uploader`, resolved once
per upload. The per-user settings column of the build phase stays retired
(PKG-14b, ADR 0040): this module reads no table itself.
"""

from __future__ import annotations

from typing import NamedTuple

import config
from services.feature_flags import REGISTRY, Resolution, env_override, explain, flag_on

#: The per-student flag (services/feature_flags.py REGISTRY).
LEARNING_LOOP_FLAG = "learning_loop"

#: The env kill switch, as the admin Flags page names it (config.py parses it).
KILL_SWITCH = "LEARNING_LOOP_ENABLED"

#: The flags that act only where the learning loop is on for the same student
#: (#866 K24). Every reader of each sits behind the loop's route-entry gate (the
#: loop routes 404 while it is off) or reads the gate first: the quiz flags
#: (services/quiz_learning.py::quiz_flags), the upload's prerequisite edges
#: (services/concept_prereqs.py::upload_prereqs_on) and the drafting flags of an
#: upload the loop drafts for. So the kill switch, or the student's own
#: `learning_loop` flag, turns each off whatever its own settings say, and the
#: admin Flags page reports it that way (`served_flag`, `forced_for_everyone`).
#: tests/test_admin_flags_loop_gate.py pins the set, and that every flag
#: services/loop/ reads is in it. crisis_support is not: it serves the legacy
#: tutor, notes and flashcards too.
LOOP_FLAGS: frozenset[str] = frozenset({
    "item_reports", "retention_due_badge", "probe_matched_pretest", "upload_prereq_edges",
    "loop_tutor_v2", "help_gate_strict", "segment_prequestion", "self_explanation_prompts",
    "next_probe_hint",
    "varied_isomorphs", "multi_concept_items", "quiz_concept_plan", "quiz_planned_questions",
    "quiz_item_gates", "quiz_misconceptions", "quiz_results_routing",
    "skill_ladder", "hint_ladder", "verdict_v2", "wrapup_v2", "plan_v2", "new_session_v2", "session_v2", "course_page_v2", "review_v2", "milestones", "just_ask", "saved_items",
})


def learning_loop_active(user_id: str | None) -> bool:
    """The env kill switch (read at call time, so a test or a reload sees the
    current value), then this student's `learning_loop` flag. Never raises:
    the flag resolver fails closed (off) on an unreadable store."""
    if not config.LEARNING_LOOP_ENABLED:
        return False
    return bool(user_id) and flag_on(LEARNING_LOOP_FLAG, user_id)


def loop_off_for_everyone() -> bool:
    """The loop is off for every student with no read of any kind: the env kill
    switch, or `SAPLING_FLAG_LEARNING_LOOP=off` (the flag forced off). For a
    surface that runs BEFORE the loop's own route-entry gate and must not read
    first (main.py's Study path gate, #866 Z37; invariants §9). It never names
    a student and never carries an answer, so the route's gate still decides."""
    return not config.LEARNING_LOOP_ENABLED or env_override(LEARNING_LOOP_FLAG) == "off"


def learning_loop_for_request(user_id: str | None) -> bool:
    """The route-entry gate (owner decision 00): call ONCE per request.

    A route evaluates this at entry and carries the result on
    `SaplingDeps.learning_loop`; agents, tools and services read that field
    and never call the gate themselves (`tests/test_learning_gate_route_entry.py`
    pins that only `routes/` and the named route-entry helpers reference the
    gate). It may read the flag store: from an `async def`, hop to a worker
    thread first.
    """
    return learning_loop_active(user_id)


def learning_loop_for_uploader(user_id: str | None) -> bool:
    """Upload-time work with no student request behind it (check-item drafting,
    inline or on the job queue): the gate for the student who UPLOADED, read
    once per upload, before anything is scheduled. Off — the kill switch, or
    the uploader's flag — schedules the indexing alone, exactly the pre-loop
    upload, and drafts nothing, so a flag-off student's upload spends no loop
    model call. Items are course assets: a flag-on classmate's upload drafts
    the course's items, and the backfill drafts what flag-off uploads left."""
    return learning_loop_active(user_id)


# ── the admin Flags page's view of the gate (#866 K24) ───────────────────────


class ServedFlag(NamedTuple):
    """A flag as a student is served it: the answer and the rule that decided
    it, and — when that rule is the loop being off for them (step "requires")
    — the `learning_loop` answer behind it."""

    resolution: Resolution
    master: Resolution | None = None
    #: forced_for_everyone only: the flag the answer is conditional on — set
    #: when a loop flag's own SAPLING_FLAG_ override forces a non-off answer
    #: but `learning_loop` is not forced on, so only students with the loop on
    #: get it and the rest still get off (learning_loop's own rules decide).
    only_with: str | None = None


def _off(key: str) -> str:
    return REGISTRY[key].variants[0]


def served_flag(key: str, user_id: str | None, *, fresh: bool = False) -> ServedFlag:
    """Flag `key` as `user_id` is served it right now, and which rule decided
    it: the admin Flags page's "Check a student". The loop's gate, in the
    order the code reads it, over the flag's own resolution
    (services/feature_flags.py::explain): for `learning_loop` and every
    LOOP_FLAGS key the kill switch first (step "kill_switch", no read); then,
    for a LOOP_FLAGS key, the student's `learning_loop` flag — off is step
    "requires", that answer its `master`; then the flag's own rules. A flag
    the loop does not gate is its own resolution, exactly as before. An admin
    diagnostic, never a route-entry gate: no answer is carried anywhere."""
    if key != LEARNING_LOOP_FLAG and key not in LOOP_FLAGS:
        return ServedFlag(explain(key, user_id, fresh=fresh))
    if not config.LEARNING_LOOP_ENABLED:
        return ServedFlag(Resolution(_off(key), "kill_switch", KILL_SWITCH))
    if key in LOOP_FLAGS:
        master = explain(LEARNING_LOOP_FLAG, user_id, fresh=fresh)
        if master.variant == _off(LEARNING_LOOP_FLAG):
            return ServedFlag(Resolution(_off(key), "requires", LEARNING_LOOP_FLAG), master)
        fresh = False  # that read refreshed the snapshot this one answers from
    return ServedFlag(explain(key, user_id, fresh=fresh))


def forced_for_everyone(key: str) -> ServedFlag | None:
    """What EVERY student gets from flag `key` whatever its stored settings say
    (overrides, rollout and default alike), and why; None when those settings
    decide, student by student (the admin flag list's row state). The
    environment only, no read: the kill switch over `learning_loop` and
    LOOP_FLAGS; for a LOOP_FLAGS key, `learning_loop` forced off by its
    SAPLING_FLAG_ override; then the flag's own override — for a LOOP_FLAGS
    key a non-off one holds for every student only when `learning_loop` is
    forced on too; otherwise it holds only for students with the loop on, and
    the answer says so (`only_with`). A flag the loop does not gate: None (its
    `env_override` is reported as before)."""
    if key != LEARNING_LOOP_FLAG and key not in LOOP_FLAGS:
        return None
    if not config.LEARNING_LOOP_ENABLED:
        return ServedFlag(Resolution(_off(key), "kill_switch", KILL_SWITCH))
    master = env_override(LEARNING_LOOP_FLAG)
    if key in LOOP_FLAGS and master == _off(LEARNING_LOOP_FLAG):
        return ServedFlag(
            Resolution(_off(key), "requires", LEARNING_LOOP_FLAG),
            Resolution(master, "env_override", f"SAPLING_FLAG_{LEARNING_LOOP_FLAG.upper()}"),
        )
    own = env_override(key)
    if own is None:
        return None
    forced = Resolution(own, "env_override", f"SAPLING_FLAG_{key.upper()}")
    if key in LOOP_FLAGS and own != _off(key) and master is None:
        # learning_loop is not forced: a student without it still gets off
        return ServedFlag(forced, only_with=LEARNING_LOOP_FLAG)
    return ServedFlag(forced)

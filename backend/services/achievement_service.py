"""
Achievement checker service.
Called synchronously after events to grant achievements when thresholds are met.
"""

import logging
from datetime import datetime, timedelta, timezone
from db.connection import MAX_ROWS, page_all, table
from db.scope import runs_as_service
from services import gradebook_service
from services.encryption import decrypt_numeric
from services.xp_service import award_xp_safe

logger = logging.getLogger(__name__)


def _count_rows(table_name: str, filters: dict) -> int:
    """Count matching rows in `table_name`.

    Selects `user_id`, NOT `id`. Two of the tables this is called with are
    junction tables with a composite primary key and no `id` column at all:
    `room_members` is PRIMARY KEY (room_id, user_id) (0001_baseline_schema.sql)
    and `friendships` is PRIMARY KEY (user_id, friend_id)
    (20260731193214_gamification.sql). Asking PostgREST for a column that does not exist
    is a 400 (`42703`), which `db/connection.py` raises — so with `id` the
    `rooms_joined`, `owned_room_members` and `friends_count` stats did not
    merely return a wrong number, they threw, and `study-circle`,
    `room-leader`, `first-friend` and `popular` were unearnable.

    `user_id` is present on every table this is called with (sessions,
    documents, quiz_attempts, room_members, flashcards, room_messages,
    graph_nodes, friendships), including the one call that filters by
    `room_id` rather than `user_id`.

    Every caller compares the result against a small `trigger_threshold`, so
    PostgREST's `max_rows` cap is not a correctness problem here the way it is
    in `_daily_totals` — a truncated 1000 still clears any real threshold.
    """
    rows = table(table_name).select("user_id", filters=filters)
    return len(rows) if rows else 0


@runs_as_service  # #115: achievement counters read rows beyond the student's own grants
def get_user_stat(user_id: str, trigger_type: str) -> int:
    """Public wrapper around the internal stat lookup."""
    return _get_user_stat(user_id, trigger_type)


def _stat_login_streak(user_id: str) -> int:
    # Deliberately the STORED count, not streak_service.effective_streak
    # (#767). Readers that DISPLAY "your streak" must use the effective
    # value, but a badge asks "did you ever reach N days", and a lapsed
    # stored count is a streak that genuinely happened. login_streak is
    # only dispatched at session end and sign-in, so a streak built from
    # quizzes/uploads and then broken would otherwise never earn its badge.
    user = table("users").select("streak_count", filters={"id": f"eq.{user_id}"})
    if user:
        return user[0].get("streak_count", 0) or 0
    return 0


def _stat_quizzes_completed(user_id: str) -> int:
    # #542 D3: really-finished attempts only. Two filters, because
    # neither alone is sufficient: generate writes the attempt row
    # BEFORE the student answers anything (so an unfiltered count let
    # "generate and close the tab" advance quizzes_10), and submit's
    # atomic claim stamps completed_at BEFORE grading (so a submit that
    # dies between the claim and the score write would still count).
    # A persisted score is the evidence a quiz was graded — the same
    # signal agents/tools/quiz_history.py treats as completion.
    return _count_rows("quiz_attempts", {
        "user_id": f"eq.{user_id}",
        "completed_at": "not.is.null",
        "score": "not.is.null",
    })


def _stat_account_age_days(user_id: str) -> int:
    user = table("users").select("created_at", filters={"id": f"eq.{user_id}"})
    if user and user[0].get("created_at"):
        created = datetime.fromisoformat(user[0]["created_at"].replace("Z", "+00:00"))
        delta = datetime.now(timezone.utc) - created
        return delta.days
    return 0


def _stat_flashcards_reviewed(user_id: str) -> int:
    rows = table("flashcards").select(
        "times_reviewed", filters={"user_id": f"eq.{user_id}"}
    )
    return sum(int(r.get("times_reviewed") or 0) for r in rows or [])


def _stat_courses_with_mastery(user_id: str) -> int:
    rows = table("graph_nodes").select(
        "course_id",
        filters={"user_id": f"eq.{user_id}", "mastery_tier": "eq.mastered"},
    )
    return len({r["course_id"] for r in rows or [] if r.get("course_id")})


def _stat_level(user_id: str) -> int:
    rows = table("users").select("level", filters={"id": f"eq.{user_id}"})
    return int(rows[0].get("level") or 1) if rows else 1


def _stat_owned_room_members(user_id: str) -> int:
    rooms = table("rooms").select("id", filters={"created_by": f"eq.{user_id}"})
    best = 0
    for room in rooms or []:
        best = max(best, _count_rows("room_members", {"room_id": f"eq.{room['id']}"}))
    return best


def _stat_rooms_active(user_id: str) -> int:
    rows = table("room_messages").select(
        "room_id", filters={"user_id": f"eq.{user_id}"}
    )
    return len({r["room_id"] for r in rows or [] if r.get("room_id")})


def _stat_room_replies(user_id: str) -> int:
    owned = {
        r["id"] for r in
        (table("rooms").select("id", filters={"created_by": f"eq.{user_id}"}) or [])
    }
    rows = table("room_messages").select(
        "room_id", filters={"user_id": f"eq.{user_id}"}
    )
    return sum(1 for r in rows or [] if r.get("room_id") not in owned)


def _count_own(table_name: str, **extra: str):
    """A stat that is the count of the user's own rows in `table_name`."""
    return lambda user_id: _count_rows(table_name, {"user_id": f"eq.{user_id}", **extra})


# trigger_type -> reader(user_id). The lambdas resolve the helpers defined
# further down the module (and anything a test patches) at call time.
_STAT_READERS = {
    "login_streak": _stat_login_streak,
    "session_count": _count_own("sessions"),
    "documents_uploaded": _count_own("documents"),
    "quizzes_completed": _stat_quizzes_completed,
    "rooms_joined": _count_own("room_members"),
    "flashcards_created": _count_own("flashcards"),
    "post_count": _count_own("room_messages"),
    "account_age_days": _stat_account_age_days,
    "manual_admin_grant": lambda user_id: 0,  # Handled directly by admin endpoint
    "flashcards_reviewed": _stat_flashcards_reviewed,
    "concepts_mastered": _count_own("graph_nodes", mastery_tier="eq.mastered"),
    "courses_with_mastery": _stat_courses_with_mastery,
    "graph_nodes_count": _count_own("graph_nodes"),
    "friends_count": _count_own("friendships"),
    "level": _stat_level,
    "session_minutes": lambda user_id: _session_stat(user_id, "session_minutes"),
    "session_before_hour": lambda user_id: _session_stat(user_id, "session_before_hour"),
    "session_after_midnight": lambda user_id: _session_stat(user_id, "session_after_midnight"),
    "xp_in_day": lambda user_id: _best_day_xp(user_id),
    "goal_streak": lambda user_id: _goal_streak(user_id),
    "owned_room_members": _stat_owned_room_members,
    "rooms_active": _stat_rooms_active,
    "course_grade_a": lambda user_id: _course_grade_a_count(user_id),
    "room_replies": _stat_room_replies,
}


def _get_user_stat(user_id: str, trigger_type: str) -> int:
    """Evaluate the current value for a trigger type (0 for an unknown one)."""
    reader = _STAT_READERS.get(trigger_type)
    return reader(user_id) if reader else 0


def _parse_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


# Trigger types where a LOWER stat is better, so qualifying is
# `value < threshold` instead of the usual `value >= threshold`.
#
# `session_before_hour` is the only one: its threshold IS the wall-clock hour
# in the badge text ('early-bird' = 7 = "finish before 7am"), which is what
# keeps it meaningful when an admin retunes it from the wiki. Encoding it as an
# inverted `24 - hour` score instead — so a plain `>=` could be reused — is
# what made any session ending 07:00-11:59 UTC clear a threshold of 7 and earn
# "Early Bird" for finishing at lunchtime.
LOWER_IS_BETTER = {"session_before_hour"}

# What a lower-is-better stat reports when there is nothing to report. Above
# any real hour, so it never qualifies.
NO_QUALIFYING_VALUE = 99


def _session_stat(user_id: str, trigger_type: str) -> int:
    """Longest session in minutes, or whether one ended in a given window.

    Timestamps are UTC — sessions carry no timezone, so 'before 7am' means
    07:00 UTC. Documented rather than guessed at per-user.

    `session_before_hour` is LOWER_IS_BETTER: it reports the earliest UTC hour
    any session finished at (NO_QUALIFYING_VALUE when none has), and
    check_achievements compares it with `<`.
    """
    rows = table("sessions").select(
        "started_at,ended_at", filters={"user_id": f"eq.{user_id}"}
    ) or []
    lower_is_better = trigger_type in LOWER_IS_BETTER
    best = NO_QUALIFYING_VALUE if lower_is_better else 0
    for r in rows:
        started, ended = _parse_ts(r.get("started_at")), _parse_ts(r.get("ended_at"))
        if not ended:
            continue
        if trigger_type == "session_minutes":
            if started:
                best = max(best, int((ended - started).total_seconds() // 60))
        elif trigger_type == "session_before_hour":
            best = min(best, ended.hour)
        elif trigger_type == "session_after_midnight":
            best = max(best, 1 if 0 <= ended.hour < 4 else 0)
    return best


# The paging loop and the reason for it now live in db/connection.py::page_all
# (PostgREST truncates past max_rows with a 206 — a 2xx, so nothing raises).
# This alias only names the page size for the tests that assert on it.
_XP_EVENTS_PAGE = MAX_ROWS


def _daily_totals(user_id: str) -> dict:
    """Per-day XP totals over the user's ENTIRE xp_events ledger.

    Hot path: since the last wave `award_xp` dispatches `xp_in_day` on every
    single award, so this runs on every action that pays XP (until the badge is
    earned — check_achievements drops already-earned triggers before evaluating
    the stat). It therefore has to page, for the same reason
    xp_service._ledger_total does: an unbounded select silently stops at
    max_rows, and past ~1000 lifetime events `golden-hour` (xp_in_day >= 500)
    would be computed over an arbitrary truncated prefix — unearnable — while
    `perfect-week` (goal_streak >= 7) would spuriously reset.

    Deliberately UNWINDOWED, both callers included:

    - `_best_day_xp` is an all-time max by definition. 0044 only just made
      golden-hour live, so a user's qualifying day may well predate any
      dispatch; a window would silently deny it.
    - `_goal_streak` only walks backwards from today, so a bounded window is
      tempting. It is still wrong: `trigger_threshold` is admin-configurable
      from the wiki (the reason routes/social.py::create_room dispatches
      owned_room_members at all), and a window of N days caps the reported
      streak at N — an admin who raises perfect-week to 30 or 60 gets a badge
      nothing can award. That is precisely the class of bug this wave exists
      to fix, so correctness wins over the read saved.

    The cost is bounded by what the same request already pays: `award_xp` pages
    the whole ledger through `_ledger_total` on every award, so a full paged
    scan here is a constant factor, not a new class of cost.

    The `created_at,id` order is required for offset paging to be correct —
    without a stable sort PostgREST can return rows in a different order across
    pages, skipping or double-counting across the page boundary.
    """
    totals: dict = {}
    for r in page_all(
        table("xp_events"), "amount,created_at",
        filters={"user_id": f"eq.{user_id}"},
        order="created_at.asc,id.asc",
        page=_XP_EVENTS_PAGE,
    ):
        ts = _parse_ts(r.get("created_at"))
        if not ts:
            continue
        day = ts.date().isoformat()
        totals[day] = totals.get(day, 0) + int(r.get("amount") or 0)
    return totals


def _best_day_xp(user_id: str) -> int:
    totals = _daily_totals(user_id)
    return max(totals.values()) if totals else 0


def _goal_streak(user_id: str) -> int:
    """Consecutive days, counting back from today, that met the daily goal."""
    rows = table("users").select("daily_goal_xp", filters={"id": f"eq.{user_id}"})
    goal = int(rows[0].get("daily_goal_xp") or 50) if rows else 50
    # `daily_goal_xp` has no CHECK constraint enforcing positivity (0043). A
    # zero/negative stored goal would make `0 >= goal` trivially true forever
    # and the loop below would never terminate — clamp to at least 1 so
    # "met the goal" always means "earned some positive XP that day".
    goal = max(goal, 1)
    totals = _daily_totals(user_id)
    streak, day = 0, datetime.now(timezone.utc).date()
    while totals.get(day.isoformat(), 0) >= goal:
        streak += 1
        day -= timedelta(days=1)
    return streak


def _course_grade_a_count(user_id: str) -> int:
    """Count the user's gradebook courses (enrollments) whose currently
    computed letter grade is an A variant (A, A-, or A+ under a custom scale).

    Reuses `gradebook_service.current_grade` / `letter_for` — the same pure
    grade math `routes/gradebook.py` runs — rather than recomputing a percent
    here. `points_possible`/`points_earned` are encrypted at rest (see
    CLAUDE.md gotchas), so they're decrypted the same way `_load_assignments`
    does before being handed to the grade math.
    """
    enrollments = table("enrollments").select(
        "id,letter_scale,curve_mode,curve_avg_target,curve_sd_delta",
        filters={"user_id": f"eq.{user_id}"},
    ) or []
    count = 0
    for enr in enrollments:
        categories = table("gradebook_categories").select(
            "id,name,weight,sort_order,drop_lowest",
            filters={"enrollment_id": f"eq.{enr['id']}"},
        ) or []
        assignments = table("assignments").select(
            "id,category_id,points_possible,points_earned",
            filters={"enrollment_id": f"eq.{enr['id']}"},
        ) or []
        for a in assignments:
            a["points_possible"] = decrypt_numeric(a.get("points_possible"))
            a["points_earned"] = decrypt_numeric(a.get("points_earned"))
        percent = gradebook_service.current_grade(
            categories, assignments,
            curve_mode=enr.get("curve_mode") or "raw",
            curve_avg_target=enr.get("curve_avg_target"),
            curve_sd_delta=enr.get("curve_sd_delta"),
        )
        letter = gradebook_service.letter_for(percent, enr.get("letter_scale"))
        if letter and letter.startswith("A"):
            count += 1
    return count


@runs_as_service  # #115: awards are server decisions (user_achievements/user_cosmetics writes are service-only)
def check_achievements(user_id: str, event_type: str, event_data: dict = None) -> list:
    """
    Check and grant achievements for a user after an event.
    Returns list of newly granted achievements as {"slug", "name", "xp"} dicts.
    """
    if event_data is None:
        event_data = {}

    newly_earned = []

    # Find triggers matching the event type
    triggers = table("achievement_triggers").select(
        "id,achievement_id,trigger_type,trigger_threshold",
        filters={"trigger_type": f"eq.{event_type}"},
    )
    if not triggers:
        return newly_earned

    # Get user's existing achievements to avoid re-granting
    existing = table("user_achievements").select(
        "achievement_id,earned_at",
        filters={"user_id": f"eq.{user_id}"},
    ) or []
    existing_ids = {row["achievement_id"] for row in existing}

    # Self-heal this event's badges that were granted RECENTLY (#767): a grant
    # is insert → XP → cosmetics over separate writes, so one that died after
    # the insert left the badge "earned" with its reward never paid, and
    # nothing retried it because the badge is skipped from then on. Bounded to
    # HEAL_WINDOW so the steady state costs no extra reads, and so raising a
    # badge's xp_reward or linking a new cosmetic never pays out retroactively
    # to everyone who already holds it.
    event_ids = {t["achievement_id"] for t in triggers}
    recent_cutoff = datetime.now(timezone.utc) - HEAL_WINDOW
    _heal_grants(user_id, {
        row["achievement_id"] for row in existing
        if row["achievement_id"] in event_ids
        and _earned_since(row.get("earned_at"), recent_cutoff)
    })

    # Drop already-earned triggers BEFORE evaluating the stat. Several stats
    # are expensive (course_grade_a walks every enrollment's assignments,
    # xp_in_day and goal_streak scan the whole xp_events ledger,
    # owned_room_members counts members per owned room), and these now run on
    # request paths — flashcard ratings, room posts, grade writes. Once a
    # badge is earned its stat can never change the outcome, so computing it
    # is pure waste on the steady-state path where users already hold it.
    triggers = [t for t in triggers if t["achievement_id"] not in existing_ids]
    if not triggers:
        return newly_earned

    # Get the current stat value for this event type
    current_value = _get_user_stat(user_id, event_type)

    for trigger in triggers:
        achievement_id = trigger["achievement_id"]

        # Skip if already earned
        if achievement_id in existing_ids:
            continue

        # Check threshold. Most stats count upwards; LOWER_IS_BETTER ones
        # (session_before_hour) qualify by coming in UNDER their threshold,
        # which is a wall-clock hour rather than a count.
        if event_type in LOWER_IS_BETTER:
            if current_value >= trigger["trigger_threshold"]:
                continue
        elif current_value < trigger["trigger_threshold"]:
            continue

        # Resolve the badge BEFORE granting: a 'draft' achievement is
        # work-in-progress in the admin wiki and must never reach a user.
        achievement = table("achievements").select(
            "slug,name,xp_reward,status", filters={"id": f"eq.{achievement_id}"}
        )
        if not achievement:
            continue
        row = achievement[0]
        if row.get("status") != "live":
            continue

        # ON CONFLICT DO NOTHING on the (user_id, achievement_id) PK (#767).
        # A plain insert raised on the conflict — from a second trigger for the
        # same badge in this loop, or a concurrent check that won the race —
        # and the exception aborted every grant after it. An empty
        # representation means the row already existed: someone else granted
        # it, so it is not reported as newly earned here.
        inserted = table("user_achievements").upsert(
            {
                "user_id": user_id,
                "achievement_id": achievement_id,
                "earned_at": datetime.now(timezone.utc).isoformat(),
                "is_featured": False,
            },
            on_conflict="user_id,achievement_id",
            ignore_duplicates=True,
        )
        existing_ids.add(achievement_id)

        # Reward + cosmetics run even when the row was already there: both are
        # idempotent (xp_events' idempotency key, user_cosmetics' PK), so this
        # is free when the winner finished and the repair when it didn't.
        reward = int(row.get("xp_reward") or 0)
        if reward:
            award_xp_safe(
                user_id, "achievement_unlocked",
                source_type="achievement", source_id=achievement_id,
                amount=reward,
            )
        if inserted:
            newly_earned.append({"slug": row["slug"], "name": row["name"], "xp": reward})

        # The badge is committed; a cosmetics failure must not abort the
        # badges after it. _heal_grants re-attempts it on a later check.
        try:
            grant_linked_cosmetics(user_id, achievement_id)
        except Exception:
            logger.exception(
                "linked cosmetics failed user=%s achievement=%s", user_id, achievement_id,
            )

    return newly_earned


# How long after a grant its missing XP/cosmetics are still re-attempted. A
# half-grant is a request that died between the badge insert and its payouts,
# so the student's next qualifying event almost always lands well inside this.
# Past it, a missing payout is indistinguishable from an admin change made
# after the grant (a raised xp_reward, a newly linked cosmetic), which must
# NOT be paid out retroactively to every past holder.
HEAL_WINDOW = timedelta(hours=24)


def parse_utc(raw: str | None) -> datetime | None:
    """A stored timestamp as an aware UTC datetime; None when missing or
    unparseable. A naive value is taken as UTC. Shared with
    scripts/backfill_achievement_xp.py so it reads grant times exactly as the
    heal window does."""
    try:
        ts = _parse_ts(raw)
    except (TypeError, ValueError, AttributeError):
        return None
    if ts is None:
        return None
    return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)


def _earned_since(raw: str | None, cutoff: datetime) -> bool:
    """True when `earned_at` is after `cutoff`. Missing/unparseable → False:
    an unknown grant time is treated as old, so it is never healed."""
    ts = parse_utc(raw)
    return ts is not None and ts > cutoff


def _heal_grants(user_id: str, achievement_ids: set) -> None:
    """Re-attempt the XP reward and linked cosmetics of badges granted within
    HEAL_WINDOW that never received them (#767). Never raises — it runs ahead
    of the event's real work.

    The grant-time reward and cosmetic set are not recorded, so the CURRENT
    values are used — which is why the caller only passes recent grants: an
    admin edit can then at most affect a badge earned in the last day, never
    the whole back catalogue of holders.

    Only LIVE badges are healed: a badge demoted to draft keeps its grant row
    (hidden from display, see routes/admin.py::update_achievement) but pays
    nothing more until it is published again.

    Cost: nothing unless the event's badges include a recent grant; then one
    read of the badges, one of their achievement_unlocked ledger rows (only if
    any pays XP), one of their cosmetic links, and one of the user's cosmetics
    (only if any are linked). Writes happen only when something is missing.
    """
    if not achievement_ids:
        return
    try:
        ids = sorted(achievement_ids)
        badges = table("achievements").select(
            "id,xp_reward,status", filters={"id": f"in.({','.join(ids)})"},
        ) or []
        live = {b["id"]: int(b.get("xp_reward") or 0)
                for b in badges if b.get("status") == "live"}
        if not live:
            return

        paying = sorted(a for a, reward in live.items() if reward)
        if paying:
            paid = {
                r.get("source_id") for r in table("xp_events").select(
                    "source_id",
                    filters={
                        "user_id": f"eq.{user_id}",
                        "rule_key": "eq.achievement_unlocked",
                        "source_type": "eq.achievement",
                        "source_id": f"in.({','.join(paying)})",
                    },
                ) or []
            }
            for achievement_id in paying:
                if achievement_id not in paid:
                    logger.warning(
                        "healing unpaid achievement XP user=%s achievement=%s",
                        user_id, achievement_id,
                    )
                    award_xp_safe(
                        user_id, "achievement_unlocked",
                        source_type="achievement", source_id=achievement_id,
                        amount=live[achievement_id],
                    )

        links = table("achievement_cosmetics").select(
            "achievement_id,cosmetic_id",
            filters={"achievement_id": f"in.({','.join(sorted(live))})"},
        ) or []
        if not links:
            return
        wanted = sorted({lc["cosmetic_id"] for lc in links})
        owned = {
            r["cosmetic_id"] for r in table("user_cosmetics").select(
                "cosmetic_id",
                filters={"user_id": f"eq.{user_id}",
                         "cosmetic_id": f"in.({','.join(wanted)})"},
            ) or []
        }
        for cosmetic_id in wanted:
            if cosmetic_id not in owned:
                logger.warning(
                    "healing missing achievement cosmetic user=%s cosmetic=%s",
                    user_id, cosmetic_id,
                )
                try:
                    _unlock_cosmetic(user_id, cosmetic_id)
                except Exception:
                    logger.exception(
                        "cosmetic heal failed user=%s cosmetic=%s", user_id, cosmetic_id,
                    )
    except Exception:
        logger.exception("achievement grant heal failed user=%s", user_id)


def _unlock_cosmetic(user_id: str, cosmetic_id: str) -> None:
    """Idempotent: ON CONFLICT DO NOTHING on the (user_id, cosmetic_id) PK, so
    a re-grant or a heal of an already-owned cosmetic is a no-op, not a 409."""
    table("user_cosmetics").upsert(
        {
            "user_id": user_id,
            "cosmetic_id": cosmetic_id,
            "unlocked_at": datetime.now(timezone.utc).isoformat(),
        },
        on_conflict="user_id,cosmetic_id",
        ignore_duplicates=True,
    )


@runs_as_service  # #115: cosmetic awards are service-only writes
def grant_linked_cosmetics(user_id: str, achievement_id: str) -> None:
    """Unlock every cosmetic linked to `achievement_id` for `user_id`.

    Shared by the two ways a badge can land on an account: earned above, and
    granted by an admin (routes/admin.py::grant_achievement).

    The admin path cannot reach this through check_achievements, which is why
    it's a function rather than an inline loop. `_get_user_stat` returns a
    hard-coded 0 for `manual_admin_grant` and every manual_admin_grant trigger
    in the catalog has a threshold of 1, so the `current_value < threshold`
    skip fires every time — the dispatch admin.py makes after granting is a
    guaranteed no-op. `mentor`, `comeback`, `secret` and `methuselah` are
    manual-grant-only, so their linked cosmetics could never be unlocked at
    all.
    """
    linked_cosmetics = table("achievement_cosmetics").select(
        "cosmetic_id", filters={"achievement_id": f"eq.{achievement_id}"}
    )
    failed = None
    for lc in linked_cosmetics or []:
        # One bad link (e.g. a dangling cosmetic_id, which has no FK on
        # achievement_cosmetics) must not stop the others; re-raised after.
        try:
            _unlock_cosmetic(user_id, lc["cosmetic_id"])
        except Exception as exc:
            failed = exc
    if failed is not None:
        raise failed

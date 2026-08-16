"""
Achievement checker service.
Called synchronously after events to grant achievements when thresholds are met.
"""

from datetime import datetime, timedelta, timezone
from db.connection import table
from services import gradebook_service
from services.encryption import decrypt_numeric
from services.xp_service import award_xp_safe


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


def get_user_stat(user_id: str, trigger_type: str) -> int:
    """Public wrapper around the internal stat lookup."""
    return _get_user_stat(user_id, trigger_type)


def _get_user_stat(user_id: str, trigger_type: str) -> int:
    """Evaluate the current value for a trigger type."""
    if trigger_type == "login_streak":
        user = table("users").select("streak_count", filters={"id": f"eq.{user_id}"})
        if user:
            return user[0].get("streak_count", 0) or 0
        return 0

    if trigger_type == "session_count":
        return _count_rows("sessions", {"user_id": f"eq.{user_id}"})

    if trigger_type == "documents_uploaded":
        return _count_rows("documents", {"user_id": f"eq.{user_id}"})

    if trigger_type == "quizzes_completed":
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

    if trigger_type == "rooms_joined":
        return _count_rows("room_members", {"user_id": f"eq.{user_id}"})

    if trigger_type == "flashcards_created":
        return _count_rows("flashcards", {"user_id": f"eq.{user_id}"})

    if trigger_type == "post_count":
        return _count_rows("room_messages", {"user_id": f"eq.{user_id}"})

    if trigger_type == "account_age_days":
        user = table("users").select("created_at", filters={"id": f"eq.{user_id}"})
        if user and user[0].get("created_at"):
            created = datetime.fromisoformat(user[0]["created_at"].replace("Z", "+00:00"))
            delta = datetime.now(timezone.utc) - created
            return delta.days
        return 0

    if trigger_type == "manual_admin_grant":
        return 0  # Handled directly by admin endpoint

    if trigger_type == "flashcards_reviewed":
        rows = table("flashcards").select(
            "times_reviewed", filters={"user_id": f"eq.{user_id}"}
        )
        return sum(int(r.get("times_reviewed") or 0) for r in rows or [])

    if trigger_type == "concepts_mastered":
        return _count_rows("graph_nodes", {
            "user_id": f"eq.{user_id}", "mastery_tier": "eq.mastered",
        })

    if trigger_type == "courses_with_mastery":
        rows = table("graph_nodes").select(
            "course_id",
            filters={"user_id": f"eq.{user_id}", "mastery_tier": "eq.mastered"},
        )
        return len({r["course_id"] for r in rows or [] if r.get("course_id")})

    if trigger_type == "graph_nodes_count":
        return _count_rows("graph_nodes", {"user_id": f"eq.{user_id}"})

    if trigger_type == "friends_count":
        return _count_rows("friendships", {"user_id": f"eq.{user_id}"})

    if trigger_type == "level":
        rows = table("users").select("level", filters={"id": f"eq.{user_id}"})
        return int(rows[0].get("level") or 1) if rows else 1

    if trigger_type in ("session_minutes", "session_before_hour", "session_after_midnight"):
        return _session_stat(user_id, trigger_type)

    if trigger_type == "xp_in_day":
        return _best_day_xp(user_id)

    if trigger_type == "goal_streak":
        return _goal_streak(user_id)

    if trigger_type == "owned_room_members":
        rooms = table("rooms").select("id", filters={"created_by": f"eq.{user_id}"})
        best = 0
        for room in rooms or []:
            best = max(best, _count_rows("room_members", {"room_id": f"eq.{room['id']}"}))
        return best

    if trigger_type == "rooms_active":
        rows = table("room_messages").select(
            "room_id", filters={"user_id": f"eq.{user_id}"}
        )
        return len({r["room_id"] for r in rows or [] if r.get("room_id")})

    if trigger_type == "course_grade_a":
        return _course_grade_a_count(user_id)

    if trigger_type == "room_replies":
        owned = {
            r["id"] for r in
            (table("rooms").select("id", filters={"created_by": f"eq.{user_id}"}) or [])
        }
        rows = table("room_messages").select(
            "room_id", filters={"user_id": f"eq.{user_id}"}
        )
        return sum(1 for r in rows or [] if r.get("room_id") not in owned)

    return 0


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


# supabase/config.toml sets PostgREST's `max_rows = 1000`. A response past that
# cap doesn't error — PostgREST returns 206 Partial Content, which is a 2xx, so
# db/connection.py's raise_for_status() never fires and the truncation is silent
# by construction. Same constant and same reasoning as
# routes/gamification.py::_XP_EVENTS_PAGE and xp_service.py::_XP_EVENTS_PAGE;
# keep it at or below max_rows and page to completion.
_XP_EVENTS_PAGE = 1000


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
    seen = 0
    offset = 0
    while True:
        rows, count = table("xp_events").select_with_count(
            "amount,created_at",
            filters={"user_id": f"eq.{user_id}"},
            order="created_at.asc,id.asc",
            limit=_XP_EVENTS_PAGE,
            offset=offset,
        )
        rows = rows or []
        for r in rows:
            ts = _parse_ts(r.get("created_at"))
            if not ts:
                continue
            day = ts.date().isoformat()
            totals[day] = totals.get(day, 0) + int(r.get("amount") or 0)
        seen += len(rows)
        if not rows or seen >= count:
            break
        offset += _XP_EVENTS_PAGE
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
        "achievement_id",
        filters={"user_id": f"eq.{user_id}"},
    )
    existing_ids = {row["achievement_id"] for row in existing} if existing else set()

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

        table("user_achievements").insert({
            "user_id": user_id,
            "achievement_id": achievement_id,
            "earned_at": datetime.now(timezone.utc).isoformat(),
            "is_featured": False,
        })

        reward = int(row.get("xp_reward") or 0)
        if reward:
            award_xp_safe(
                user_id, "achievement_unlocked",
                source_type="achievement", source_id=achievement_id,
                amount=reward,
            )
        newly_earned.append({"slug": row["slug"], "name": row["name"], "xp": reward})

        grant_linked_cosmetics(user_id, achievement_id)

    return newly_earned


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
    for lc in linked_cosmetics or []:
        table("user_cosmetics").insert({
            "user_id": user_id,
            "cosmetic_id": lc["cosmetic_id"],
            "unlocked_at": datetime.now(timezone.utc).isoformat(),
        })

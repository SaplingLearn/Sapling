"""xp_events idempotency is per student, not global.

`xp_service.idempotency_key` does not contain the user: an achievement's key is
`achievement_unlocked:achievement:<achievement_id>`, the same string for every
student who earns that badge. The ledger was created with
`idempotency_key TEXT NOT NULL UNIQUE` (20260731193214_gamification.sql), so the
first student ever to earn a badge was paid and every later earner's insert hit
the conflict, which award_xp reports as "already paid" (`duplicate=True`,
`awarded=0`). The badge row was granted; the XP silently never was.

A MagicMock ledger cannot see that, because the bug lives in the schema. So the
ledger fake here enforces exactly the UNIQUE constraints the migrations leave on
xp_events, replayed from the migration files in filename order. If a later
migration (or a revert) puts a user-blind unique key back, these fail.
"""
from __future__ import annotations

import pathlib
import re
from unittest.mock import MagicMock, patch

import httpx

BACKEND = pathlib.Path(__file__).resolve().parents[1]
MIG_DIR = BACKEND / "db" / "migrations"
E2E_DB_HELPER = BACKEND.parent / "frontend" / "e2e" / "support" / "db.ts"


def _strip_sql_comments(sql: str) -> str:
    return re.sub(r"--[^\n]*", "", sql)


def _cols(raw: str) -> tuple[str, ...]:
    return tuple(c.strip().strip('"') for c in raw.split(","))


def xp_events_unique_keys() -> dict[str, tuple[str, ...]]:
    """Replay the UNIQUE DDL on xp_events across every migration, in order.

    Models the three shapes this table's history uses: an inline column
    `UNIQUE` in the CREATE TABLE (Postgres names it `xp_events_<col>_key`),
    `ADD CONSTRAINT <name> UNIQUE (<cols>)`, and `DROP CONSTRAINT [IF EXISTS]
    <name>`. Returns {constraint name: columns}.
    """
    keys: dict[str, tuple[str, ...]] = {}
    for path in sorted(MIG_DIR.glob("*.sql")):
        sql = _strip_sql_comments(path.read_text())
        if "xp_events" not in sql:
            continue
        create = re.search(
            r"CREATE TABLE IF NOT EXISTS xp_events\s*\((.*?)\n\);", sql, re.S | re.I,
        )
        if create:
            for line in create.group(1).splitlines():
                m = re.match(r"\s*(\w+)\s+[^,]*\bUNIQUE\b", line, re.I)
                if m:
                    keys[f"xp_events_{m.group(1)}_key"] = (m.group(1),)
        for stmt in re.finditer(
            r"ALTER TABLE (?:IF EXISTS )?(?:ONLY )?xp_events\b(.*?);", sql, re.S | re.I,
        ):
            body = stmt.group(1)
            for m in re.finditer(
                r"ADD CONSTRAINT\s+(\w+)\s+UNIQUE\s*\(([^)]*)\)", body, re.I,
            ):
                keys[m.group(1)] = _cols(m.group(2))
            for m in re.finditer(
                r"DROP CONSTRAINT\s+(?:IF EXISTS\s+)?(\w+)", body, re.I,
            ):
                keys.pop(m.group(1), None)
    return keys


def _ledger_tables(unique_keys):
    """A `table` stub whose xp_events insert answers 409 on any violation of
    `unique_keys`, the way PostgREST does."""
    events: list[dict] = []
    users = {"u1": {"total_xp": 0, "level": 1}, "u2": {"total_xp": 0, "level": 1}}

    def _insert(row):
        for cols in unique_keys:
            if any(all(e.get(c) == row.get(c) for c in cols) for e in events):
                raise httpx.HTTPStatusError(
                    "duplicate key", request=MagicMock(),
                    response=MagicMock(status_code=409),
                )
        events.append(dict(row))
        return [row]

    def _ledger_page(*_a, filters=None, **_k):
        uid = (filters or {}).get("user_id", "")[3:]
        rows = [{"amount": e["amount"]} for e in events if e["user_id"] == uid]
        return rows, len(rows)

    def _user_select(_cols, filters=None, **_k):
        uid = (filters or {}).get("id", "")[3:]
        return [dict(users[uid])] if uid in users else []

    def _user_update(data, filters=None, **_k):
        uid = (filters or {}).get("id", "")[3:]
        users[uid].update(data)
        return [dict(users[uid])]

    handles = {"xp_events": MagicMock(), "users": MagicMock(), "xp_rules": MagicMock()}
    handles["xp_events"].insert.side_effect = _insert
    handles["xp_events"].select_with_count.side_effect = _ledger_page
    handles["users"].select.side_effect = _user_select
    handles["users"].update.side_effect = _user_update
    handles["xp_rules"].select.return_value = []
    return (lambda name: handles[name]), events


def _award_badge(tbl, user_id, achievement_id="badge-1", reward=50):
    with patch("services.xp_service.table", side_effect=tbl), \
         patch("services.xp_service._dispatch_xp_achievements"):
        from services.xp_service import award_xp
        return award_xp(
            user_id, "achievement_unlocked",
            source_type="achievement", source_id=achievement_id, amount=reward,
        )


class TestSchemaKeysTheLedgerPerStudent:
    def test_no_unique_key_on_xp_events_is_blind_to_the_user(self):
        """Every key builder omits the user, so any UNIQUE without user_id is
        a cross-student collision waiting on a shared source id."""
        keys = xp_events_unique_keys()
        assert keys, "replay found no UNIQUE constraint on xp_events"
        blind = {name: cols for name, cols in keys.items() if "user_id" not in cols}
        assert not blind, f"user-blind unique keys on xp_events: {blind}"

    def test_a_per_student_idempotency_key_is_still_enforced(self):
        assert ("user_id", "idempotency_key") in xp_events_unique_keys().values()

    def test_the_e2e_award_helper_conflicts_on_a_real_unique_key(self):
        """frontend/e2e/support/db.ts ports award_xp with ON CONFLICT; Postgres
        rejects an ON CONFLICT target that matches no unique constraint."""
        target = re.search(
            r"INSERT INTO xp_events.*?ON CONFLICT \(([^)]*)\)", E2E_DB_HELPER.read_text(), re.S,
        )
        assert target, "awardXp's ON CONFLICT clause moved — update this test"
        assert _cols(target.group(1)) in xp_events_unique_keys().values()


class TestTwoStudentsEarnTheSameBadge:
    def test_both_are_paid(self):
        tbl, events = _ledger_tables(xp_events_unique_keys().values())
        first = _award_badge(tbl, "u1")
        second = _award_badge(tbl, "u2")
        assert (first.awarded, first.duplicate) == (50, False)
        assert (second.awarded, second.duplicate) == (50, False), \
            "the second earner of a badge was reported as already paid"
        assert second.total_xp == 50
        assert sorted(e["user_id"] for e in events) == ["u1", "u2"]

    def test_one_student_is_still_paid_once(self):
        tbl, events = _ledger_tables(xp_events_unique_keys().values())
        _award_badge(tbl, "u1")
        again = _award_badge(tbl, "u1")
        assert (again.awarded, again.duplicate) == (0, True)
        assert len(events) == 1

# Gamification (XP, levels, achievements, leaderboards) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship an XP ledger, levels mapped to eleven growth stages, three leaderboards, an activity dashboard, a friends system, and an editable achievement wiki in the admin console.

**Architecture:** An append-only `xp_events` table is the single source of truth; `total_xp`/`level` on `users` are caches recomputed by one award path. A `growth_stages` table holds the level curve, so both the hero card and the leaderboard's stage label read the same numbers. Everything user-facing hangs off three new `/api/gamification` endpoints; everything editable hangs off the existing `/api/admin` router.

**Tech Stack:** FastAPI + Supabase (PostgREST via `db/connection.py::table()`), raw-DDL numbered migrations, pytest; Next.js/React frontend with Vitest and Playwright.

**Spec:** `docs/superpowers/specs/2026-07-31-gamification-xp-achievements-design.md`

## Global Constraints

- **All Supabase access goes through `db/connection.py::table()`.** Never instantiate `httpx` clients or import `supabase` directly. The sole exception is `db/migrate.py`.
- **Migrations are append-only.** Add new numbered files in `backend/db/migrations/`; never edit an applied one. Latest existing is `0042`.
- **`Cache-Control` on these routes is always `private`, never `public`** — they carry user-scoped, app-decrypted display names (#99).
- **Display names resolve through `services/profiles.py::get_display_names`** — never read name columns off `users`.
- **`lru_cache` requires a matching `clear_*_cache()` hook** that every mutator calls, registered in the autouse `_clear_lru_caches` fixture in `tests/conftest.py` (#98).
- **Frontend tooling needs Node 22** — the system Node is v20.12.1 and vitest will not run on it. From `frontend/`:
  - `fnm exec --using=v22.23.1 -- node ./node_modules/vitest/vitest.mjs run`
  - `fnm exec --using=v22.23.1 -- node ./node_modules/typescript/bin/tsc --noEmit`
  - `fnm exec --using=v22.23.1 -- node ./node_modules/eslint/bin/eslint.js .`
- **ESLint runs against a bulk-suppressions baseline.** New violations fail CI, so keep new files clean — no bare `any`, even in tests.
- **Backend commands run from `backend/`:** `python -m pytest tests/ -q` and `ruff check .`
- **XP amounts, level thresholds and stage names come from the spec's tables verbatim.** Do not invent numbers.
- **Never let XP failures break the request that earned it** — award calls are post-commit background work wrapped so an exception is logged, not raised.

---

## File Structure

**Backend — created**
- `backend/db/migrations/0043_gamification.sql` — schema: `xp_events`, `xp_rules`, `growth_stages`, `friendships`, `friend_requests`, and the `users`/`achievements` column additions.
- `backend/db/migrations/0044_achievement_catalog.sql` — data: slug remaps, the five deletions, the 25 inserts, triggers.
- `backend/services/growth.py` — pure level/stage maths over `growth_stages`. No writes.
- `backend/services/xp_service.py` — the one award path.
- `backend/services/streak_service.py` — the only writer of `streak_count` / `longest_streak`.
- `backend/routes/gamification.py` — `/me`, `/leaderboard`, `/activity`.
- `backend/tests/test_growth.py`, `test_xp_service.py`, `test_streak_service.py`, `test_gamification_routes.py`, `test_friends_routes.py`, `test_achievement_icon_upload.py`, `test_xp_rules_routes.py`

**Backend — modified**
- `backend/services/achievement_service.py` — new trigger types; grant pays `xp_reward`.
- `backend/services/storage_service.py` — `upload_achievement_icon` + dimension validation.
- `backend/routes/social.py` — friends endpoints.
- `backend/routes/profile.py` — scope the achievements read to `status = 'live'`.
- `backend/routes/admin.py` — icon upload, XP rules, wider `update_achievement` allowlist.
- `backend/models.py` — new request bodies.
- `backend/main.py` — mount the gamification router.
- `backend/tests/conftest.py` — register `growth.clear_growth_cache` in `_clear_lru_caches`.

**Frontend — created**
- `frontend/public/growth/*.svg` — eleven pre-rendered stage medallions.
- `frontend/src/components/growth/BadgeArt.tsx` — rarity disc + icon compositor.
- `frontend/src/components/growth/levels.ts` — client-side level/stage maths.
- `frontend/src/components/screens/achievements/` — `HeroCard.tsx`, `BadgeGrid.tsx`, `BadgeModal.tsx`, `LeaderboardTab.tsx`, `ActivityTab.tsx`
- `frontend/src/components/screens/admin/AchievementWiki.tsx` — the wiki, extracted out of `Admin.tsx`.
- Tests: `levels.test.ts`, `BadgeArt.test.tsx`, `ActivityTab.buckets.test.ts`

**Frontend — modified**
- `frontend/src/components/screens/Achievements.tsx` — three tabs.
- `frontend/src/components/screens/Admin.tsx` — swap `AchievementsTab` for `AchievementWiki`.
- `frontend/src/components/screens/Social.tsx` — friends list + requests.
- `frontend/src/lib/api.ts`, `frontend/src/lib/types.ts`

`Admin.tsx` is already 1,485 lines; the wiki goes in its own file rather than growing it further.

---

### Task 1: Schema migration

**Files:**
- Create: `backend/db/migrations/0043_gamification.sql`

**Interfaces:**
- Produces: tables `xp_events`, `xp_rules`, `growth_stages`, `friendships`, `friend_requests`; columns `users.total_xp`, `users.level`, `users.daily_goal_xp`, `users.longest_streak`, `achievements.xp_reward`, `achievements.icon_url`, `achievements.sort_order`.

- [ ] **Step 1: Write the migration**

```sql
-- 0043: gamification — XP ledger, level curve, friends.
--
-- xp_events is append-only and authoritative; users.total_xp/level are caches
-- recomputed by services/xp_service.py and always rederivable from it.

CREATE TABLE IF NOT EXISTS xp_events (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    rule_key        TEXT NOT NULL,
    amount          INT  NOT NULL,
    source_type     TEXT,
    source_id       TEXT,
    idempotency_key TEXT NOT NULL UNIQUE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_xp_events_user_time ON xp_events(user_id, created_at DESC);

CREATE TABLE IF NOT EXISTS xp_rules (
    key        TEXT PRIMARY KEY,
    label      TEXT NOT NULL,
    amount     INT  NOT NULL,
    enabled    BOOL NOT NULL DEFAULT true,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

INSERT INTO xp_rules (key, label, amount) VALUES
    ('session_completed',      'Completed a study session', 25),
    ('quiz_completed',         'Completed a quiz',          30),
    ('flashcards_reviewed_10', 'Reviewed 10 flashcards',     5),
    ('document_uploaded',      'Uploaded a document',       15),
    ('note_created',           'Created a note',            10),
    ('daily_goal_met',         'Hit the daily XP goal',     20)
ON CONFLICT (key) DO NOTHING;

CREATE TABLE IF NOT EXISTS growth_stages (
    slug            TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    blurb           TEXT NOT NULL,
    min_level       INT  NOT NULL,
    xp_to_complete  INT,            -- NULL for the terminal stage
    sort_order      INT  NOT NULL
);

INSERT INTO growth_stages (slug, name, blurb, min_level, xp_to_complete, sort_order) VALUES
    ('bare',     'Bare Soil',     'Nothing planted yet. Just open ground, turned over and waiting.',                  1,   200,  0),
    ('soil',     'Fallow Soil',   'Rich, quiet earth. Everything begins here, potential resting beneath the surface.', 5,   300,  1),
    ('seed',     'Seed',          'A seed settles in. The first thread-thin roots reach down, feeling for a foothold.', 10,  500,  2),
    ('sprout',   'Sprout',        'A pale shoot cracks the surface and, without hesitating, turns toward the light.',  15,  800,  3),
    ('seedling', 'Seedling',      'Two first leaves unfurl on either side. Small, but unmistakably its own.',          20, 1200,  4),
    ('sapling',  'Sapling',       'Standing on its own now, putting down roots and reaching for the light.',           25, 2000,  5),
    ('young',    'Young Tree',    'Bark begins to harden along the trunk, and the first true branches take shape.',    30, 3200,  6),
    ('branch',   'Branching Out', 'Limbs spread wide and confident, and the first tight buds appear along them.',      35, 4800,  7),
    ('bloom',    'In Bloom',      'Blossoms open all across the crown, a bright, showy season of full growth.',        40, 7000,  8),
    ('fruit',    'Fruit-Bearing', 'Heavy with fruit and alive with visitors. Growth that now feeds more than itself.', 45,10000,  9),
    ('old',      'Old Growth',    'A towering crown years in the making, rooted deep, sheltering all beneath it.',     50, NULL, 10)
ON CONFLICT (slug) DO NOTHING;

-- Friends. Rows are written symmetrically on accept so "my friends" is a plain
-- equality filter with no OR — PostgREST expresses that far more cheaply.
CREATE TABLE IF NOT EXISTS friendships (
    user_id    TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    friend_id  TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, friend_id),
    CHECK (user_id <> friend_id)
);

CREATE TABLE IF NOT EXISTS friend_requests (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    from_user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    to_user_id   TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    status       TEXT NOT NULL DEFAULT 'pending'
                   CHECK (status IN ('pending', 'accepted', 'declined')),
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    responded_at TIMESTAMPTZ,
    UNIQUE (from_user_id, to_user_id),
    CHECK (from_user_id <> to_user_id)
);
CREATE INDEX IF NOT EXISTS idx_friend_requests_to ON friend_requests(to_user_id, status);

ALTER TABLE users ADD COLUMN IF NOT EXISTS total_xp       INT DEFAULT 0;
ALTER TABLE users ADD COLUMN IF NOT EXISTS level          INT DEFAULT 1;
ALTER TABLE users ADD COLUMN IF NOT EXISTS daily_goal_xp  INT DEFAULT 50;
ALTER TABLE users ADD COLUMN IF NOT EXISTS longest_streak INT DEFAULT 0;

ALTER TABLE achievements ADD COLUMN IF NOT EXISTS xp_reward  INT DEFAULT 0;
ALTER TABLE achievements ADD COLUMN IF NOT EXISTS icon_url   TEXT;
ALTER TABLE achievements ADD COLUMN IF NOT EXISTS sort_order INT DEFAULT 0;

-- 'draft' badges are visible and editable in the admin wiki but are never
-- served to users, never trigger-evaluated, and never counted in "N of M".
-- This is what lets a badge be authored before its trigger exists.
ALTER TABLE achievements ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'live';
ALTER TABLE achievements DROP CONSTRAINT IF EXISTS achievements_status_check;
ALTER TABLE achievements ADD CONSTRAINT achievements_status_check
    CHECK (status IN ('draft', 'live'));
CREATE INDEX IF NOT EXISTS idx_achievements_status ON achievements(status);
```

- [ ] **Step 2: Apply it against local Supabase**

Run from `backend/`: `python -m db.migrate`
Expected: `0043_gamification.sql` reported applied, no errors.

- [ ] **Step 3: Verify the seed landed**

Run from `backend/`:
```
python -c "from db.connection import table; print(len(table('growth_stages').select('slug')), len(table('xp_rules').select('key')))"
```
Expected: `11 6`

- [ ] **Step 4: Commit**

```bash
git add backend/db/migrations/0043_gamification.sql
git commit -m "feat(db): gamification schema — XP ledger, level curve, friends"
```

---

### Task 2: Achievement catalog migration

**Files:**
- Create: `backend/db/migrations/0044_achievement_catalog.sql`

**Interfaces:**
- Consumes: `achievements.xp_reward` / `sort_order` / `status` from Task 1.
- Produces: 40 rows in `achievements` — the design's 30 as `live`, the 10 pre-existing as `draft`.

Nothing is deleted and nothing is remapped, so no `user_achievements` row is ever cascaded away. The 10 already in the database become the wiki's work-in-progress list.

- [ ] **Step 1: Write the migration**

```sql
-- 0044: bring in the 30 badges from the Achievements.dc.html design as the
-- live catalog, and demote the 10 pre-existing seeds to drafts.
--
-- Deliberately non-destructive: the old rows keep their slugs, triggers and
-- earned rows, so nobody loses a badge. Concepts overlap across the two sets
-- (Week Warrior/draft and On Fire/live are both a 7-day streak) — harmless,
-- because drafts are never served to users. Reconciling them is an editorial
-- job for the admin wiki, not a migration.
UPDATE achievements
   SET status = 'draft'
 WHERE slug IN (
   'first_login','streak_7','streak_30','documents_5','documents_25',
   'quizzes_10','flashcards_50','rooms_joined_10','post_count_50','early_adopter'
 );

INSERT INTO achievements (slug, name, description, category, rarity, is_secret, xp_reward, sort_order, status) VALUES
  ('first-steps','First Steps','Complete your first study session, the moment an idea takes root.','activity','common',false,20,0,'live'),
  ('flash','Quick Draw','Review 100 flashcards. Recall gets sharper every pass.','activity','common',false,30,1,'live'),
  ('early-bird','Early Bird','Finish a study session before 7am.','activity','uncommon',false,60,2,'live'),
  ('night-owl','Night Owl','Wrap a study session after midnight.','activity','uncommon',false,60,3,'live'),
  ('on-fire','On Fire','Reach a 7-day study streak.','activity','rare',false,120,4,'live'),
  ('deep-focus','Deep Focus','Study for two straight hours in a single session.','activity','rare',false,120,5,'live'),
  ('quiz-master','Quiz Master','Complete 100 adaptive quizzes.','activity','epic',false,250,6,'live'),
  ('marathon','Evergreen','Hold a 30-day study streak. Growth that never drops its leaves.','activity','epic',false,300,7,'live'),
  ('wildfire','Wildfire','Keep a 60-day streak alive, a blaze that spreads across the calendar.','activity','legendary',false,400,8,'live'),
  ('first-friend','First Sprout','Add your first friend. Learning grows in company.','social','common',false,20,9,'live'),
  ('study-circle','Study Circle','Join your first study room.','social','uncommon',false,60,10,'live'),
  ('helping-hand','Helping Hand','Answer a roommate''s question in a study room.','social','uncommon',false,70,11,'live'),
  ('room-leader','Grovekeeper','Create a study room that five people join.','social','rare',false,150,12,'live'),
  ('popular','Well-Connected','Grow your friends list to ten.','social','rare',false,150,13,'live'),
  ('social-butterfly','Cross-Pollinator','Stay active across five different study rooms.','social','epic',false,250,14,'live'),
  ('mentor','Mentor','Finish first on a study room''s weekly leaderboard.','social','epic',false,280,15,'live'),
  ('sprout','Sprouted','Reach the Sprout growth stage.','milestone','common',false,25,16,'live'),
  ('rooted','Rooted','Master ten concepts across your courses.','milestone','uncommon',false,80,17,'live'),
  ('grade-a','Top Marks','Finish a course with an A in your gradebook.','milestone','uncommon',false,100,18,'live'),
  ('branching','Branching Out','Master fifty concepts.','milestone','rare',false,180,19,'live'),
  ('rings','Seasoned','Reach Level 15.','milestone','rare',false,180,20,'live'),
  ('canopy','Canopy','Master one hundred concepts.','milestone','epic',false,280,21,'live'),
  ('web','Knowledge Web','Grow your knowledge graph to two hundred nodes.','milestone','epic',false,300,22,'live'),
  ('old-growth','Old Growth','Reach the final growth stage. A canopy years in the making.','milestone','legendary',false,500,23,'live'),
  ('golden-hour','Golden Hour','Earn 500 XP in a single day.','special','rare',false,150,24,'live'),
  ('comeback','Second Wind','Rebuild a streak to seven days after a lapse.','special','rare',false,150,25,'live'),
  ('perfect-week','Perfect Week','Hit your daily XP goal seven days in a row.','special','epic',false,200,26,'live'),
  ('secret','???','A hidden achievement. Keep exploring to discover it.','special','epic',true,250,27,'live'),
  ('methuselah','Methuselah','Named for the bristlecone pine in Inyo National Forest, California, roughly 4,800 years old and still growing. Awarded to founding members from Sapling''s earliest days.','special','legendary',false,300,28,'live'),
  ('polymath','Polymath','Master concepts across five different courses.','special','legendary',false,500,29,'live')
ON CONFLICT (slug) DO UPDATE SET
  name        = EXCLUDED.name,
  description = EXCLUDED.description,
  category    = EXCLUDED.category,
  rarity      = EXCLUDED.rarity,
  is_secret   = EXCLUDED.is_secret,
  xp_reward   = EXCLUDED.xp_reward,
  sort_order  = EXCLUDED.sort_order,
  status      = EXCLUDED.status;

-- Rebuild triggers for the LIVE catalog only. Scoped by join rather than a bare
-- DELETE so the drafts keep the triggers they already had — publishing one from
-- the wiki should not silently produce a badge nothing can award.
DELETE FROM achievement_triggers t
 USING achievements a
 WHERE t.achievement_id = a.id AND a.status = 'live';

INSERT INTO achievement_triggers (achievement_id, trigger_type, trigger_threshold)
SELECT a.id, t.trigger_type, t.trigger_threshold
  FROM achievements a
  JOIN (VALUES
    ('first-steps','session_count',1),
    ('flash','flashcards_reviewed',100),
    ('early-bird','session_before_hour',7),
    ('night-owl','session_after_midnight',1),
    ('on-fire','login_streak',7),
    ('deep-focus','session_minutes',120),
    ('quiz-master','quizzes_completed',100),
    ('marathon','login_streak',30),
    ('wildfire','login_streak',60),
    ('first-friend','friends_count',1),
    ('study-circle','rooms_joined',1),
    ('helping-hand','room_replies',1),
    ('room-leader','owned_room_members',5),
    ('popular','friends_count',10),
    ('social-butterfly','rooms_active',5),
    ('mentor','manual_admin_grant',1),
    ('sprout','level',15),
    ('rooted','concepts_mastered',10),
    ('grade-a','course_grade_a',1),
    ('branching','concepts_mastered',50),
    ('rings','level',15),
    ('canopy','concepts_mastered',100),
    ('web','graph_nodes_count',200),
    ('old-growth','level',50),
    ('golden-hour','xp_in_day',500),
    ('comeback','manual_admin_grant',1),
    ('perfect-week','goal_streak',7),
    ('secret','manual_admin_grant',1),
    ('methuselah','manual_admin_grant',1),
    ('polymath','courses_with_mastery',5)
  ) AS t(slug, trigger_type, trigger_threshold)
    ON t.slug = a.slug;
```

- [ ] **Step 2: Apply and verify counts**

Run from `backend/`: `python -m db.migrate`
Then:
```
python -c "from db.connection import table; \
rows=table('achievements').select('slug,status'); \
print(len(rows), sum(1 for r in rows if r['status']=='live'), sum(1 for r in rows if r['status']=='draft'))"
```
Expected: `40 30 10`

- [ ] **Step 3: Verify no earned row was destroyed**

```
python -c "from db.connection import table; print(len(table('user_achievements').select('achievement_id')))"
```
Expected: the same count as before the migration — nothing was deleted or remapped, so every earned row survives. On a fresh local DB this is `0`, which is also correct.

- [ ] **Step 4: Commit**

```bash
git add backend/db/migrations/0044_achievement_catalog.sql
git commit -m "feat(db): add the design's 30 badges as live, demote the seeded 10 to draft"
```

---

### Task 3: Level and stage maths

**Files:**
- Create: `backend/services/growth.py`
- Create: `backend/tests/test_growth.py`
- Modify: `backend/tests/conftest.py:54-59`

**Interfaces:**
- Produces:
  - `stages() -> list[dict]` — cached, sorted by `sort_order`; each dict has `slug`, `name`, `blurb`, `min_level`, `xp_to_complete`, `sort_order`.
  - `xp_for_level(level: int) -> int` — XP needed to go from `level` to `level + 1`. Returns `0` at the terminal stage.
  - `level_for_xp(total_xp: int) -> int`
  - `xp_into_level(total_xp: int) -> tuple[int, int]` — `(xp_into, xp_for)` for the current level.
  - `stage_for_level(level: int) -> dict`
  - `clear_growth_cache() -> None`

- [ ] **Step 1: Write the failing tests**

```python
"""Unit tests for services/growth.py — the level curve from growth_stages."""
import pytest
from unittest.mock import patch

STAGE_ROWS = [
    {"slug": "bare", "name": "Bare Soil", "blurb": "b", "min_level": 1, "xp_to_complete": 200, "sort_order": 0},
    {"slug": "soil", "name": "Fallow Soil", "blurb": "b", "min_level": 5, "xp_to_complete": 300, "sort_order": 1},
    {"slug": "seed", "name": "Seed", "blurb": "b", "min_level": 10, "xp_to_complete": 500, "sort_order": 2},
    {"slug": "sprout", "name": "Sprout", "blurb": "b", "min_level": 15, "xp_to_complete": 800, "sort_order": 3},
    {"slug": "old", "name": "Old Growth", "blurb": "b", "min_level": 20, "xp_to_complete": None, "sort_order": 4},
]


@pytest.fixture(autouse=True)
def _stub_stages():
    with patch("services.growth.table") as t:
        t.return_value.select.return_value = STAGE_ROWS
        from services.growth import clear_growth_cache
        clear_growth_cache()
        yield t
        clear_growth_cache()


class TestXpForLevel:
    def test_first_band_divides_by_its_span(self):
        # Bare Soil spans levels 1-5 => 4 levels, 200 XP => 50 each.
        from services.growth import xp_for_level
        assert xp_for_level(1) == 50
        assert xp_for_level(4) == 50

    def test_band_boundary_uses_the_new_band(self):
        # Level 5 is the first level of Fallow Soil: 300 / 5 = 60.
        from services.growth import xp_for_level
        assert xp_for_level(5) == 60

    def test_terminal_stage_costs_nothing(self):
        from services.growth import xp_for_level
        assert xp_for_level(20) == 0
        assert xp_for_level(99) == 0


class TestLevelForXp:
    def test_zero_xp_is_level_one(self):
        from services.growth import level_for_xp
        assert level_for_xp(0) == 1

    def test_just_short_of_a_level_does_not_advance(self):
        from services.growth import level_for_xp
        assert level_for_xp(49) == 1

    def test_exact_threshold_advances(self):
        from services.growth import level_for_xp
        assert level_for_xp(50) == 2

    def test_completing_the_first_band_reaches_level_five(self):
        from services.growth import level_for_xp
        assert level_for_xp(200) == 5

    def test_caps_at_the_terminal_level(self):
        from services.growth import level_for_xp
        # 200 + 300 + 500 + 800 = 1800 reaches level 20 and stops there.
        assert level_for_xp(1800) == 20
        assert level_for_xp(999_999) == 20


class TestRoundTrip:
    def test_level_for_xp_inverts_xp_for_level(self):
        from services.growth import level_for_xp, xp_for_level
        total = 0
        for level in range(1, 20):
            assert level_for_xp(total) == level
            total += xp_for_level(level)
        assert level_for_xp(total) == 20


class TestXpIntoLevel:
    def test_reports_progress_within_the_band(self):
        from services.growth import xp_into_level
        assert xp_into_level(70) == (20, 50)   # 50 spent on L1->2, 20 into L2

    def test_terminal_level_reports_zero_of_zero(self):
        from services.growth import xp_into_level
        assert xp_into_level(5000) == (0, 0)


class TestStageForLevel:
    def test_picks_the_containing_band(self):
        from services.growth import stage_for_level
        assert stage_for_level(1)["slug"] == "bare"
        assert stage_for_level(4)["slug"] == "bare"
        assert stage_for_level(5)["slug"] == "soil"
        assert stage_for_level(17)["slug"] == "sprout"

    def test_above_the_last_threshold_is_terminal(self):
        from services.growth import stage_for_level
        assert stage_for_level(50)["slug"] == "old"
```

- [ ] **Step 2: Run to verify they fail**

Run from `backend/`: `python -m pytest tests/test_growth.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'services.growth'`

- [ ] **Step 3: Implement**

```python
"""The level curve, derived from the growth_stages table.

growth_stages is the single source of truth for level maths: the hero card,
the leaderboard's stage label and the `level` achievement trigger all read it
through here, so there is exactly one answer to "what stage is level 17".

Each stage band declares the XP needed to cross it. A level inside a band
costs `xp_to_complete / span`, where span is the distance to the next band's
min_level. The terminal band has no xp_to_complete and costs nothing.
"""

from functools import lru_cache

from db.connection import table


@lru_cache(maxsize=1)
def _stages_cached() -> tuple:
    rows = table("growth_stages").select(
        "slug,name,blurb,min_level,xp_to_complete,sort_order",
        order="sort_order.asc",
    )
    return tuple(rows or [])


def stages() -> list[dict]:
    """The stage bands, ascending. Deep-copied — the cache holds the original."""
    return [dict(r) for r in _stages_cached()]


def clear_growth_cache() -> None:
    """#98: every growth_stages mutator must call this."""
    _stages_cached.cache_clear()


def _bands() -> list[dict]:
    """Stages annotated with the span and per-level cost of each band."""
    rows = stages()
    out = []
    for i, s in enumerate(rows):
        nxt = rows[i + 1]["min_level"] if i + 1 < len(rows) else None
        span = (nxt - s["min_level"]) if nxt else 0
        cost = s.get("xp_to_complete")
        out.append({
            **s,
            "span": span,
            "per_level": (cost // span) if (cost and span) else 0,
        })
    return out


def _band_for_level(level: int) -> dict | None:
    band = None
    for b in _bands():
        if level >= b["min_level"]:
            band = b
        else:
            break
    return band


def xp_for_level(level: int) -> int:
    """XP needed to go from `level` to `level + 1`. 0 at the terminal stage."""
    band = _band_for_level(level)
    return band["per_level"] if band else 0


def stage_for_level(level: int) -> dict:
    band = _band_for_level(level)
    if band:
        return {k: v for k, v in band.items() if k not in ("span", "per_level")}
    first = stages()
    return first[0] if first else {}


def max_level() -> int:
    rows = stages()
    return rows[-1]["min_level"] if rows else 1


def level_for_xp(total_xp: int) -> int:
    """Walk the curve from level 1, spending XP, until it runs out or we cap."""
    cap = max_level()
    level, spent = 1, 0
    while level < cap:
        cost = xp_for_level(level)
        if cost <= 0 or spent + cost > total_xp:
            break
        spent += cost
        level += 1
    return level


def xp_into_level(total_xp: int) -> tuple[int, int]:
    """(xp earned into the current level, xp the current level costs)."""
    level = level_for_xp(total_xp)
    spent = 0
    for lv in range(1, level):
        spent += xp_for_level(lv)
    return total_xp - spent, xp_for_level(level)
```

- [ ] **Step 4: Register the cache hook**

In `backend/tests/conftest.py`, extend `_clear_lru_caches` (currently lines 54-59):

```python
    from services import academics, course_context_service, growth
    academics.clear_academics_caches()
    course_context_service.clear_course_context_cache()
    growth.clear_growth_cache()
    yield
    academics.clear_academics_caches()
    course_context_service.clear_course_context_cache()
    growth.clear_growth_cache()
```

- [ ] **Step 5: Run tests**

Run from `backend/`: `python -m pytest tests/test_growth.py -q`
Expected: PASS, 15 tests.

- [ ] **Step 6: Lint and commit**

```bash
cd backend && ruff check services/growth.py tests/test_growth.py
git add backend/services/growth.py backend/tests/test_growth.py backend/tests/conftest.py
git commit -m "feat(growth): level curve derived from growth_stages"
```

---

### Task 4: The XP award path

**Files:**
- Create: `backend/services/xp_service.py`
- Create: `backend/tests/test_xp_service.py`

**Interfaces:**
- Consumes: `services.growth.level_for_xp`, `xp_for_level` (Task 3).
- Produces:
  - `award_xp(user_id: str, rule_key: str, *, source_type: str | None = None, source_id: str | None = None, amount: int | None = None) -> XpAward`
  - `XpAward` — dataclass with `awarded: int`, `total_xp: int`, `level: int`, `leveled_up: bool`, `duplicate: bool`.
  - `award_xp_safe(...) -> XpAward | None` — same signature, swallows and logs every exception. Callers on a request path use this one.
  - `idempotency_key(rule_key, source_type, source_id) -> str`

`amount` overrides the rule lookup; the achievement grant path uses it to pay a badge's `xp_reward`.

- [ ] **Step 1: Write the failing tests**

```python
"""Unit tests for services/xp_service.py."""
import pytest
from unittest.mock import MagicMock, patch

import httpx

RULE = [{"key": "quiz_completed", "label": "Completed a quiz", "amount": 30, "enabled": True}]


def _tables(rule_rows=RULE, user_rows=None, insert=None):
    """Build a `table` stub that dispatches on table name."""
    user_rows = user_rows if user_rows is not None else [{"total_xp": 0, "level": 1}]
    handles = {
        "xp_rules": MagicMock(),
        "xp_events": MagicMock(),
        "users": MagicMock(),
    }
    handles["xp_rules"].select.return_value = rule_rows
    handles["xp_events"].insert.side_effect = insert or (lambda data: [data])
    handles["users"].select.return_value = user_rows
    handles["users"].update.return_value = []
    return lambda name: handles[name], handles


class TestAwardXp:
    def test_awards_the_rule_amount(self):
        tbl, handles = _tables()
        with patch("services.xp_service.table", side_effect=tbl), \
             patch("services.xp_service.level_for_xp", return_value=1):
            from services.xp_service import award_xp
            result = award_xp("u1", "quiz_completed", source_type="quiz", source_id="q1")
        assert result.awarded == 30
        assert result.total_xp == 30
        assert result.duplicate is False

    def test_explicit_amount_overrides_the_rule(self):
        tbl, _ = _tables()
        with patch("services.xp_service.table", side_effect=tbl), \
             patch("services.xp_service.level_for_xp", return_value=1):
            from services.xp_service import award_xp
            result = award_xp("u1", "achievement_unlocked", amount=120,
                              source_type="achievement", source_id="a1")
        assert result.awarded == 120

    def test_disabled_rule_pays_nothing(self):
        tbl, handles = _tables(rule_rows=[{**RULE[0], "enabled": False}])
        with patch("services.xp_service.table", side_effect=tbl):
            from services.xp_service import award_xp
            result = award_xp("u1", "quiz_completed", source_type="quiz", source_id="q1")
        assert result.awarded == 0
        handles["xp_events"].insert.assert_not_called()

    def test_unknown_rule_pays_nothing(self):
        tbl, handles = _tables(rule_rows=[])
        with patch("services.xp_service.table", side_effect=tbl):
            from services.xp_service import award_xp
            result = award_xp("u1", "nope", source_type="quiz", source_id="q1")
        assert result.awarded == 0
        handles["xp_events"].insert.assert_not_called()

    def test_duplicate_idempotency_key_is_a_no_op(self):
        """A 409 from the unique index means someone already paid this out."""
        response = MagicMock(status_code=409)
        def _conflict(_data):
            raise httpx.HTTPStatusError("duplicate", request=MagicMock(), response=response)

        tbl, handles = _tables(insert=_conflict, user_rows=[{"total_xp": 30, "level": 1}])
        with patch("services.xp_service.table", side_effect=tbl), \
             patch("services.xp_service.level_for_xp", return_value=1):
            from services.xp_service import award_xp
            result = award_xp("u1", "quiz_completed", source_type="quiz", source_id="q1")
        assert result.duplicate is True
        assert result.awarded == 0
        assert result.total_xp == 30
        handles["users"].update.assert_not_called()

    def test_non_conflict_http_error_propagates(self):
        response = MagicMock(status_code=500)
        def _boom(_data):
            raise httpx.HTTPStatusError("server error", request=MagicMock(), response=response)

        tbl, _ = _tables(insert=_boom)
        with patch("services.xp_service.table", side_effect=tbl):
            from services.xp_service import award_xp
            with pytest.raises(httpx.HTTPStatusError):
                award_xp("u1", "quiz_completed", source_type="quiz", source_id="q1")

    def test_reports_a_level_up(self):
        tbl, handles = _tables(user_rows=[{"total_xp": 40, "level": 1}])
        with patch("services.xp_service.table", side_effect=tbl), \
             patch("services.xp_service.level_for_xp", return_value=2):
            from services.xp_service import award_xp
            result = award_xp("u1", "quiz_completed", source_type="quiz", source_id="q1")
        assert result.leveled_up is True
        assert result.level == 2
        handles["users"].update.assert_called_once()
        assert handles["users"].update.call_args[0][0] == {"total_xp": 70, "level": 2}


class TestIdempotencyKey:
    def test_is_stable_for_the_same_source(self):
        from services.xp_service import idempotency_key
        assert idempotency_key("quiz_completed", "quiz", "q1") == \
               idempotency_key("quiz_completed", "quiz", "q1")

    def test_differs_across_sources(self):
        from services.xp_service import idempotency_key
        assert idempotency_key("quiz_completed", "quiz", "q1") != \
               idempotency_key("quiz_completed", "quiz", "q2")


class TestAwardXpSafe:
    def test_swallows_errors(self):
        with patch("services.xp_service.award_xp", side_effect=RuntimeError("db down")):
            from services.xp_service import award_xp_safe
            assert award_xp_safe("u1", "quiz_completed", source_type="quiz", source_id="q1") is None
```

- [ ] **Step 2: Run to verify they fail**

Run from `backend/`: `python -m pytest tests/test_xp_service.py -q`
Expected: FAIL — `No module named 'services.xp_service'`

- [ ] **Step 3: Implement**

```python
"""The single XP award path.

Every XP grant in the product goes through `award_xp`. It writes one row to the
append-only `xp_events` ledger and then refreshes the `users.total_xp` /
`users.level` caches from it.

Idempotency is the reason this is a service and not three inline inserts: a
retried quiz submit, a re-delivered background task or a double-clicked upload
must not pay out twice. Each event carries a deterministic key backed by a
UNIQUE index; a 409 from Postgres means "already paid" and is a clean no-op,
not an error.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import httpx

from db.connection import table
from services.growth import level_for_xp

logger = logging.getLogger(__name__)


@dataclass
class XpAward:
    awarded: int
    total_xp: int
    level: int
    leveled_up: bool
    duplicate: bool = False


def idempotency_key(rule_key: str, source_type: str | None, source_id: str | None) -> str:
    return f"{rule_key}:{source_type or '-'}:{source_id or '-'}"


def _rule_amount(rule_key: str) -> int:
    rows = table("xp_rules").select(
        "key,amount,enabled", filters={"key": f"eq.{rule_key}"}
    )
    if not rows:
        logger.warning("award_xp: unknown rule_key=%s", rule_key)
        return 0
    rule = rows[0]
    if not rule.get("enabled", True):
        return 0
    return int(rule.get("amount") or 0)


def _user_state(user_id: str) -> tuple[int, int]:
    rows = table("users").select("total_xp,level", filters={"id": f"eq.{user_id}"})
    if not rows:
        return 0, 1
    return int(rows[0].get("total_xp") or 0), int(rows[0].get("level") or 1)


def award_xp(
    user_id: str,
    rule_key: str,
    *,
    source_type: str | None = None,
    source_id: str | None = None,
    amount: int | None = None,
) -> XpAward:
    """Grant XP once. `amount` overrides the rule (achievement rewards use it)."""
    value = amount if amount is not None else _rule_amount(rule_key)
    if value <= 0:
        total_xp, level = _user_state(user_id)
        return XpAward(awarded=0, total_xp=total_xp, level=level, leveled_up=False)

    key = idempotency_key(rule_key, source_type, source_id)
    try:
        table("xp_events").insert({
            "user_id": user_id,
            "rule_key": rule_key,
            "amount": value,
            "source_type": source_type,
            "source_id": source_id,
            "idempotency_key": key,
        })
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code != 409:
            raise
        # Already paid out — report current state without touching the cache.
        total_xp, level = _user_state(user_id)
        return XpAward(awarded=0, total_xp=total_xp, level=level,
                       leveled_up=False, duplicate=True)

    prev_total, prev_level = _user_state(user_id)
    total_xp = prev_total + value
    level = level_for_xp(total_xp)
    table("users").update(
        {"total_xp": total_xp, "level": level}, filters={"id": f"eq.{user_id}"}
    )
    return XpAward(
        awarded=value, total_xp=total_xp, level=level,
        leveled_up=level > prev_level,
    )


def award_xp_safe(*args, **kwargs) -> XpAward | None:
    """award_xp that never raises. Use this on request paths — XP must not be
    able to fail the action that earned it."""
    try:
        return award_xp(*args, **kwargs)
    except Exception:
        logger.exception("award_xp failed rule=%s", args[1] if len(args) > 1 else kwargs.get("rule_key"))
        return None
```

- [ ] **Step 4: Run tests**

Run from `backend/`: `python -m pytest tests/test_xp_service.py -q`
Expected: PASS, 11 tests.

- [ ] **Step 5: Lint and commit**

```bash
cd backend && ruff check services/xp_service.py tests/test_xp_service.py
git add backend/services/xp_service.py backend/tests/test_xp_service.py
git commit -m "feat(xp): idempotent award path over the xp_events ledger"
```

---

### Task 5: Wire XP into the earning paths

**Files:**
- Modify: `backend/routes/quiz.py`, `backend/routes/documents.py`, `backend/routes/notes.py`, `backend/routes/learn.py`
- Create: `backend/tests/test_xp_wiring.py`

**Interfaces:**
- Consumes: `services.xp_service.award_xp_safe`, `idempotency_key` (Task 4).

Find the commit point in each route — the place where the row is already persisted — and award immediately after. `award_xp_safe` is used everywhere so a ledger problem can never fail the user's action.

- [ ] **Step 1: Locate the four call sites**

Run from `backend/`:
```
grep -n "quiz_attempts\").insert\|def score_quiz\|def submit" routes/quiz.py
grep -n "documents\").insert" routes/documents.py
grep -n "def create_note" routes/notes.py
grep -n "ended_at" routes/learn.py
```
Record the line numbers; the awards go immediately after each successful insert/update.

- [ ] **Step 2: Write the failing tests**

```python
"""XP is awarded from the routes that earn it, and never breaks them."""
from unittest.mock import patch

from services.xp_service import idempotency_key


class TestIdempotencyKeys:
    def test_quiz_key_is_scoped_to_the_attempt(self):
        assert idempotency_key("quiz_completed", "quiz", "attempt-1") == \
               "quiz_completed:quiz:attempt-1"

    def test_document_key_is_scoped_to_the_document(self):
        assert idempotency_key("document_uploaded", "document", "doc-1") == \
               "document_uploaded:document:doc-1"


class TestSafety:
    def test_a_broken_ledger_does_not_raise(self):
        with patch("services.xp_service.table", side_effect=RuntimeError("db down")):
            from services.xp_service import award_xp_safe
            assert award_xp_safe("u1", "quiz_completed",
                                 source_type="quiz", source_id="q1") is None
```

- [ ] **Step 3: Add the award calls**

In `routes/quiz.py`, after the attempt row is written:

```python
from services.xp_service import award_xp_safe   # top of file

    award_xp_safe(user_id, "quiz_completed", source_type="quiz", source_id=attempt_id)
    check_achievements(user_id, "quizzes_completed")
```

In `routes/documents.py`, after the document row is written:

```python
    award_xp_safe(user_id, "document_uploaded", source_type="document", source_id=document_id)
```

In `routes/notes.py`, after `create_note` returns:

```python
    award_xp_safe(user_id, "note_created", source_type="note", source_id=note["id"])
```

In `routes/learn.py`, where a session gets its `ended_at`:

```python
    award_xp_safe(user_id, "session_completed", source_type="session", source_id=session_id)
    check_achievements(user_id, "session_count")
```

Use the existing `user_id` variable in each scope; do not re-resolve it from the request.

- [ ] **Step 4: Run the affected suites**

Run from `backend/`: `python -m pytest tests/test_xp_wiring.py tests/test_quiz_routes.py tests/test_documents_routes.py tests/test_notes_routes.py -q`
Expected: PASS. If a pre-existing route test now fails because `table` is mocked without `xp_rules`, that is the safety net working — confirm the failure is a mock gap, then extend that test's stub rather than removing the award.

- [ ] **Step 5: Commit**

```bash
git add backend/routes/quiz.py backend/routes/documents.py backend/routes/notes.py backend/routes/learn.py backend/tests/test_xp_wiring.py
git commit -m "feat(xp): award XP from quiz, upload, note and session completion"
```

---

### Task 6: New achievement triggers and XP payout

**Files:**
- Modify: `backend/services/achievement_service.py`
- Modify: `backend/tests/test_achievement_service.py`

**Interfaces:**
- Consumes: `services.xp_service.award_xp_safe` (Task 4).
- Produces: `check_achievements(user_id, event_type, event_data=None) -> list[dict]` — each dict is `{"slug": str, "name": str, "xp": int}`. **This is a return-type change** from `list[str]`; `routes/admin.py:262` and `routes/auth.py` consume it.

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_achievement_service.py`:

```python
class TestNewTriggerTypes:
    def test_flashcards_reviewed_sums_times_reviewed(self):
        with patch("services.achievement_service.table") as t:
            t.return_value.select.return_value = [
                {"times_reviewed": 40}, {"times_reviewed": 61}
            ]
            from services.achievement_service import _get_user_stat
            assert _get_user_stat("u1", "flashcards_reviewed") == 101

    def test_concepts_mastered_counts_mastered_nodes(self):
        with patch("services.achievement_service.table") as t:
            t.return_value.select.return_value = [{"id": "n1"}, {"id": "n2"}]
            from services.achievement_service import _get_user_stat
            assert _get_user_stat("u1", "concepts_mastered") == 2

    def test_courses_with_mastery_counts_distinct_courses(self):
        with patch("services.achievement_service.table") as t:
            t.return_value.select.return_value = [
                {"course_id": "c1"}, {"course_id": "c1"}, {"course_id": "c2"}, {"course_id": None}
            ]
            from services.achievement_service import _get_user_stat
            assert _get_user_stat("u1", "courses_with_mastery") == 2

    def test_friends_count(self):
        with patch("services.achievement_service.table") as t:
            t.return_value.select.return_value = [{"friend_id": "u2"}, {"friend_id": "u3"}]
            from services.achievement_service import _get_user_stat
            assert _get_user_stat("u1", "friends_count") == 2

    def test_level_reads_the_cached_column(self):
        with patch("services.achievement_service.table") as t:
            t.return_value.select.return_value = [{"level": 17}]
            from services.achievement_service import _get_user_stat
            assert _get_user_stat("u1", "level") == 17

    def test_session_minutes_takes_the_longest_session(self):
        with patch("services.achievement_service.table") as t:
            t.return_value.select.return_value = [
                {"started_at": "2026-07-01T10:00:00+00:00", "ended_at": "2026-07-01T10:45:00+00:00"},
                {"started_at": "2026-07-02T10:00:00+00:00", "ended_at": "2026-07-02T12:30:00+00:00"},
            ]
            from services.achievement_service import _get_user_stat
            assert _get_user_stat("u1", "session_minutes") == 150

    def test_session_minutes_ignores_unfinished_sessions(self):
        with patch("services.achievement_service.table") as t:
            t.return_value.select.return_value = [
                {"started_at": "2026-07-01T10:00:00+00:00", "ended_at": None},
            ]
            from services.achievement_service import _get_user_stat
            assert _get_user_stat("u1", "session_minutes") == 0

    def test_xp_in_day_takes_the_best_day(self):
        with patch("services.achievement_service.table") as t:
            t.return_value.select.return_value = [
                {"amount": 200, "created_at": "2026-07-01T09:00:00+00:00"},
                {"amount": 150, "created_at": "2026-07-01T20:00:00+00:00"},
                {"amount": 300, "created_at": "2026-07-02T09:00:00+00:00"},
            ]
            from services.achievement_service import _get_user_stat
            assert _get_user_stat("u1", "xp_in_day") == 350


class TestGrantPaysXp:
    def test_granting_awards_the_badge_reward(self):
        with patch("services.achievement_service.table") as t, \
             patch("services.achievement_service.award_xp_safe") as award:
            def _select(columns="*", filters=None, **kw):
                if "trigger_type" in (filters or {}):
                    return [{"id": "t1", "achievement_id": "a1",
                             "trigger_type": "login_streak", "trigger_threshold": 7}]
                if columns.startswith("slug"):
                    return [{"slug": "on-fire", "name": "On Fire", "xp_reward": 120}]
                if columns == "achievement_id":
                    return []
                if columns == "streak_count":
                    return [{"streak_count": 9}]
                return []
            t.return_value.select.side_effect = _select
            from services.achievement_service import check_achievements
            earned = check_achievements("u1", "login_streak")
        assert earned == [{"slug": "on-fire", "name": "On Fire", "xp": 120}]
        award.assert_called_once_with(
            "u1", "achievement_unlocked", source_type="achievement",
            source_id="a1", amount=120,
        )
```

- [ ] **Step 2: Run to verify they fail**

Run from `backend/`: `python -m pytest tests/test_achievement_service.py -q`
Expected: FAIL on the new classes.

- [ ] **Step 3: Extend `_get_user_stat`**

Add these branches to `backend/services/achievement_service.py` before the final `return 0`:

```python
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

    if trigger_type == "room_replies":
        owned = {
            r["id"] for r in
            (table("rooms").select("id", filters={"created_by": f"eq.{user_id}"}) or [])
        }
        rows = table("room_messages").select(
            "room_id", filters={"user_id": f"eq.{user_id}"}
        )
        return sum(1 for r in rows or [] if r.get("room_id") not in owned)
```

And the three helpers, above `check_achievements`:

```python
def _parse_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _session_stat(user_id: str, trigger_type: str) -> int:
    """Longest session in minutes, or whether one ended in a given window.

    Timestamps are UTC — sessions carry no timezone, so 'before 7am' means
    07:00 UTC. Documented rather than guessed at per-user.
    """
    rows = table("sessions").select(
        "started_at,ended_at", filters={"user_id": f"eq.{user_id}"}
    ) or []
    best = 0
    for r in rows:
        started, ended = _parse_ts(r.get("started_at")), _parse_ts(r.get("ended_at"))
        if not ended:
            continue
        if trigger_type == "session_minutes":
            if started:
                best = max(best, int((ended - started).total_seconds() // 60))
        elif trigger_type == "session_before_hour":
            # Report the earliest finish as "hours before 24" so a plain
            # `value >= threshold` comparison still works for an "earlier is
            # better" stat: finishing at 05:00 yields 19, which clears 7.
            best = max(best, 24 - ended.hour if ended.hour < 12 else 0)
        elif trigger_type == "session_after_midnight":
            best = max(best, 1 if 0 <= ended.hour < 4 else 0)
    return best


def _daily_totals(user_id: str) -> dict:
    rows = table("xp_events").select(
        "amount,created_at", filters={"user_id": f"eq.{user_id}"}
    ) or []
    totals: dict = {}
    for r in rows:
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
    totals = _daily_totals(user_id)
    streak, day = 0, datetime.now(timezone.utc).date()
    while totals.get(day.isoformat(), 0) >= goal:
        streak += 1
        day -= timedelta(days=1)
    return streak
```

Update the import at the top: `from datetime import datetime, timedelta, timezone`.

- [ ] **Step 4: Pay XP on grant, skip drafts, and change the return shape**

The existing loop inserts the `user_achievements` row *first* and only then looks
up the slug. That ordering has to invert: a draft badge must never be granted, so
the row is fetched and its status checked **before** anything is written.

Replace the body of the `for trigger in triggers:` loop, from the threshold check
onward, with:

```python
        # Check threshold
        if current_value < trigger["trigger_threshold"]:
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

        # Grant linked cosmetics
        linked_cosmetics = table("achievement_cosmetics").select(
            "cosmetic_id", filters={"achievement_id": f"eq.{achievement_id}"}
        )
        if linked_cosmetics:
            for lc in linked_cosmetics:
                table("user_cosmetics").insert({
                    "user_id": user_id,
                    "cosmetic_id": lc["cosmetic_id"],
                    "unlocked_at": datetime.now(timezone.utc).isoformat(),
                })
```

Add `from services.xp_service import award_xp_safe` at the top.

- [ ] **Step 4b: Add the draft-skip test**

```python
class TestDraftsAreNeverGranted:
    def test_a_draft_badge_is_not_awarded(self):
        with patch("services.achievement_service.table") as t, \
             patch("services.achievement_service.award_xp_safe") as award:
            def _select(columns="*", filters=None, **kw):
                if "trigger_type" in (filters or {}):
                    return [{"id": "t1", "achievement_id": "a1",
                             "trigger_type": "login_streak", "trigger_threshold": 7}]
                if columns.startswith("slug"):
                    return [{"slug": "streak_7", "name": "Week Warrior",
                             "xp_reward": 0, "status": "draft"}]
                if columns == "achievement_id":
                    return []
                if columns == "streak_count":
                    return [{"streak_count": 9}]
                return []
            t.return_value.select.side_effect = _select
            from services.achievement_service import check_achievements
            assert check_achievements("u1", "login_streak") == []
        t.return_value.insert.assert_not_called()
        award.assert_not_called()
```

Add `"status": "live"` to the `TestGrantPaysXp` stub's achievement row so it still passes.

- [ ] **Step 5: Update the two consumers**

`routes/admin.py:262` (`grant_achievement`) and `routes/auth.py` read the returned list. Change any `slug in earned` / direct string use to read `e["slug"]`.

Run from `backend/`: `grep -rn "check_achievements(" routes/ services/` and fix each call site.

- [ ] **Step 6: Run tests**

Run from `backend/`: `python -m pytest tests/test_achievement_service.py tests/test_admin_routes.py tests/test_auth_first_login_achievement.py -q`
Expected: PASS.

- [ ] **Step 7: Lint and commit**

```bash
cd backend && ruff check services/achievement_service.py
git add backend/services/achievement_service.py backend/tests/test_achievement_service.py backend/routes/admin.py backend/routes/auth.py
git commit -m "feat(achievements): new trigger types and XP payout on unlock"
```

---

### Task 6b: Streak maintenance and live-only reads

**Files:**
- Create: `backend/services/streak_service.py`, `backend/tests/test_streak_service.py`
- Modify: `backend/routes/profile.py:572-590`, `backend/routes/learn.py`

**Interfaces:**
- Produces: `touch_streak(user_id: str) -> int` — advances and returns the current streak.

Two gaps this closes. First, **nothing in the codebase advances `streak_count`** — it is initialised to 0 in `graph_service.py:81` and only ever read. Four achievements and the hero card's streak tile depend on it, so without this they read zero forever. Second, the user-facing achievement reads must exclude drafts.

- [ ] **Step 1: Write the failing tests**

```python
"""Streak advancement — the thing that makes streak_count mean anything."""
from datetime import date, timedelta
from unittest.mock import MagicMock, patch


def _user(last_active, streak, longest=0):
    t = MagicMock()
    t.select.return_value = [{
        "last_active_date": last_active,
        "streak_count": streak,
        "longest_streak": longest,
    }]
    t.update.return_value = []
    return t


class TestTouchStreak:
    def test_first_ever_activity_starts_at_one(self):
        t = _user(None, 0)
        with patch("services.streak_service.table", return_value=t):
            from services.streak_service import touch_streak
            assert touch_streak("u1") == 1

    def test_same_day_repeat_does_not_advance(self):
        today = date.today().isoformat()
        t = _user(today, 4)
        with patch("services.streak_service.table", return_value=t):
            from services.streak_service import touch_streak
            assert touch_streak("u1") == 4
        t.update.assert_not_called()

    def test_yesterday_advances_by_one(self):
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        t = _user(yesterday, 4)
        with patch("services.streak_service.table", return_value=t):
            from services.streak_service import touch_streak
            assert touch_streak("u1") == 5

    def test_a_gap_resets_to_one(self):
        stale = (date.today() - timedelta(days=3)).isoformat()
        t = _user(stale, 20)
        with patch("services.streak_service.table", return_value=t):
            from services.streak_service import touch_streak
            assert touch_streak("u1") == 1

    def test_longest_streak_ratchets_up(self):
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        t = _user(yesterday, 9, longest=9)
        with patch("services.streak_service.table", return_value=t):
            from services.streak_service import touch_streak
            touch_streak("u1")
        assert t.update.call_args[0][0]["longest_streak"] == 10

    def test_longest_streak_is_not_lowered_by_a_reset(self):
        stale = (date.today() - timedelta(days=5)).isoformat()
        t = _user(stale, 30, longest=30)
        with patch("services.streak_service.table", return_value=t):
            from services.streak_service import touch_streak
            touch_streak("u1")
        assert t.update.call_args[0][0]["longest_streak"] == 30
```

- [ ] **Step 2: Run to verify they fail**

Run from `backend/`: `python -m pytest tests/test_streak_service.py -q`
Expected: FAIL — `No module named 'services.streak_service'`

- [ ] **Step 3: Implement**

```python
"""Daily study-streak maintenance.

`users.streak_count` existed since the baseline schema but nothing ever advanced
it — it was initialised to 0 and only read. This is the writer. Call it once per
day of activity, from the same post-commit hook that awards XP.

Days are UTC calendar days, matching `users.last_active_date` (a DATE since 0024).
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone

from db.connection import table

logger = logging.getLogger(__name__)


def _today() -> date:
    return datetime.now(timezone.utc).date()


def touch_streak(user_id: str) -> int:
    """Advance the streak for today's activity. Idempotent within a day."""
    rows = table("users").select(
        "last_active_date,streak_count,longest_streak",
        filters={"id": f"eq.{user_id}"},
    )
    if not rows:
        return 0
    row = rows[0]
    today = _today()
    streak = int(row.get("streak_count") or 0)
    longest = int(row.get("longest_streak") or 0)

    last_raw = row.get("last_active_date")
    last = date.fromisoformat(last_raw[:10]) if last_raw else None

    if last == today:
        return streak                      # already counted today
    if last == today - timedelta(days=1):
        streak += 1                        # consecutive day
    else:
        streak = 1                         # first day, or the streak broke

    table("users").update(
        {
            "streak_count": streak,
            "longest_streak": max(longest, streak),
            "last_active_date": today.isoformat(),
        },
        filters={"id": f"eq.{user_id}"},
    )
    return streak


def touch_streak_safe(user_id: str) -> int | None:
    """touch_streak that never raises — request paths use this."""
    try:
        return touch_streak(user_id)
    except Exception:
        logger.exception("touch_streak failed user=%s", user_id)
        return None
```

- [ ] **Step 4: Call it where XP is awarded**

In `routes/learn.py`, beside the `session_completed` award added in Task 5:

```python
from services.streak_service import touch_streak_safe   # top of file

    touch_streak_safe(user_id)
    check_achievements(user_id, "login_streak")
```

- [ ] **Step 5: Filter drafts out of the user-facing read**

In `routes/profile.py`, `get_achievements` (around line 572) currently selects the
whole catalog. Scope it to live badges:

```python
    all_achs = table("achievements").select("*", filters={"status": "eq.live"})
```

Leave the `user_achievements` read alone — a user who earned a badge that later
went back to draft keeps the row; it simply stops being listed until republished.

- [ ] **Step 6: Filter the `/me` badge count**

This is a forward reference to Task 8 — when writing `routes/gamification.py`,
the catalog count must be:

```python
    catalog = table("achievements").select("id", filters={"status": "eq.live"}) or []
```

so "12 / 30" never counts drafts. Task 8's test asserts this.

- [ ] **Step 7: Run tests, lint, commit**

Run from `backend/`: `python -m pytest tests/test_streak_service.py tests/test_profile_routes.py -q && ruff check services/streak_service.py`

```bash
git add backend/services/streak_service.py backend/tests/test_streak_service.py backend/routes/profile.py backend/routes/learn.py
git commit -m "feat(streaks): advance streak_count and longest_streak; hide drafts from users"
```

---

### Task 7: Friends backend

**Files:**
- Modify: `backend/routes/social.py`, `backend/models.py`
- Create: `backend/tests/test_friends_routes.py`

**Interfaces:**
- Produces, all under the `/api/social` prefix:
  - `POST /friends/request` — body `{from_user_id, to_user_id}` → `{"request": {...}}`
  - `POST /friends/requests/{request_id}/accept` → `{"accepted": true}`
  - `POST /friends/requests/{request_id}/decline` → `{"declined": true}`
  - `DELETE /friends/{friend_id}?user_id=` → `{"removed": true}`
  - `GET /friends/{user_id}` → `{"friends": [{"user_id","name","level","total_xp"}]}`
  - `GET /friends/requests?user_id=` → `{"incoming": [...], "outgoing": [...]}`

- [ ] **Step 1: Write the failing tests**

```python
"""Friends endpoints — request, accept, decline, remove, list."""
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from main import app

client = TestClient(app)


def _tables(handles):
    return lambda name: handles[name]


class TestSendRequest:
    def test_creates_a_pending_request(self):
        handles = {"friend_requests": MagicMock(), "friendships": MagicMock()}
        handles["friendships"].select.return_value = []
        handles["friend_requests"].select.return_value = []
        handles["friend_requests"].insert.return_value = [
            {"id": "r1", "from_user_id": "u1", "to_user_id": "u2", "status": "pending"}
        ]
        with patch("routes.social.table", side_effect=_tables(handles)):
            r = client.post("/api/social/friends/request",
                            json={"from_user_id": "u1", "to_user_id": "u2"})
        assert r.status_code == 200
        assert r.json()["request"]["status"] == "pending"

    def test_rejects_self_friending(self):
        with patch("routes.social.table"):
            r = client.post("/api/social/friends/request",
                            json={"from_user_id": "u1", "to_user_id": "u1"})
        assert r.status_code == 400

    def test_rejects_when_already_friends(self):
        handles = {"friend_requests": MagicMock(), "friendships": MagicMock()}
        handles["friendships"].select.return_value = [{"friend_id": "u2"}]
        with patch("routes.social.table", side_effect=_tables(handles)):
            r = client.post("/api/social/friends/request",
                            json={"from_user_id": "u1", "to_user_id": "u2"})
        assert r.status_code == 409


class TestAccept:
    def test_writes_both_directions_and_checks_both_users(self):
        handles = {"friend_requests": MagicMock(), "friendships": MagicMock()}
        handles["friend_requests"].select.return_value = [
            {"id": "r1", "from_user_id": "u1", "to_user_id": "u2", "status": "pending"}
        ]
        with patch("routes.social.table", side_effect=_tables(handles)), \
             patch("routes.social.check_achievements") as check:
            r = client.post("/api/social/friends/requests/r1/accept?user_id=u2")
        assert r.status_code == 200
        inserted = handles["friendships"].insert.call_args[0][0]
        assert {"user_id": "u1", "friend_id": "u2"} in inserted
        assert {"user_id": "u2", "friend_id": "u1"} in inserted
        assert check.call_count == 2

    def test_only_the_recipient_may_accept(self):
        handles = {"friend_requests": MagicMock(), "friendships": MagicMock()}
        handles["friend_requests"].select.return_value = [
            {"id": "r1", "from_user_id": "u1", "to_user_id": "u2", "status": "pending"}
        ]
        with patch("routes.social.table", side_effect=_tables(handles)):
            r = client.post("/api/social/friends/requests/r1/accept?user_id=u9")
        assert r.status_code == 403

    def test_missing_request_is_404(self):
        handles = {"friend_requests": MagicMock(), "friendships": MagicMock()}
        handles["friend_requests"].select.return_value = []
        with patch("routes.social.table", side_effect=_tables(handles)):
            r = client.post("/api/social/friends/requests/nope/accept?user_id=u2")
        assert r.status_code == 404


class TestRemove:
    def test_deletes_both_directions(self):
        handles = {"friendships": MagicMock()}
        with patch("routes.social.table", side_effect=_tables(handles)):
            r = client.delete("/api/social/friends/u2?user_id=u1")
        assert r.status_code == 200
        assert handles["friendships"].delete.call_count == 2


class TestList:
    def test_returns_friends_with_level_and_xp(self):
        handles = {"friendships": MagicMock(), "users": MagicMock()}
        handles["friendships"].select.return_value = [{"friend_id": "u2"}]
        handles["users"].select.return_value = [{"id": "u2", "level": 7, "total_xp": 900}]
        with patch("routes.social.table", side_effect=_tables(handles)), \
             patch("routes.social.get_display_names", return_value={"u2": "Priya Nair"}):
            r = client.get("/api/social/friends/u1")
        assert r.json()["friends"] == [
            {"user_id": "u2", "name": "Priya Nair", "level": 7, "total_xp": 900}
        ]
```

- [ ] **Step 2: Run to verify they fail**

Run from `backend/`: `python -m pytest tests/test_friends_routes.py -q`
Expected: FAIL — 404s, routes not registered.

- [ ] **Step 3: Add the request body to `models.py`**

```python
class FriendRequestBody(BaseModel):
    from_user_id: str
    to_user_id: str
```

- [ ] **Step 4: Implement the routes**

Append to `backend/routes/social.py` (imports: `from services.profiles import get_display_names`, `from services.achievement_service import check_achievements`, `from models import FriendRequestBody`):

```python
# ── Friends ──────────────────────────────────────────────────────────────────

def _are_friends(user_id: str, other_id: str) -> bool:
    rows = table("friendships").select(
        "friend_id", filters={"user_id": f"eq.{user_id}", "friend_id": f"eq.{other_id}"}
    )
    return bool(rows)


@router.post("/friends/request")
def send_friend_request(body: FriendRequestBody):
    if body.from_user_id == body.to_user_id:
        raise HTTPException(status_code=400, detail="You can't friend yourself")
    if _are_friends(body.from_user_id, body.to_user_id):
        raise HTTPException(status_code=409, detail="Already friends")
    existing = table("friend_requests").select(
        "id,status",
        filters={
            "from_user_id": f"eq.{body.from_user_id}",
            "to_user_id": f"eq.{body.to_user_id}",
        },
    )
    if existing and existing[0].get("status") == "pending":
        raise HTTPException(status_code=409, detail="Request already pending")
    result = table("friend_requests").insert({
        "from_user_id": body.from_user_id,
        "to_user_id": body.to_user_id,
        "status": "pending",
    })
    return {"request": result[0] if result else None}


def _load_request(request_id: str, user_id: str) -> dict:
    rows = table("friend_requests").select(
        "id,from_user_id,to_user_id,status", filters={"id": f"eq.{request_id}"}
    )
    if not rows:
        raise HTTPException(status_code=404, detail="Request not found")
    req = rows[0]
    if req["to_user_id"] != user_id:
        raise HTTPException(status_code=403, detail="Not your request to answer")
    return req


@router.post("/friends/requests/{request_id}/accept")
def accept_friend_request(request_id: str, user_id: str):
    req = _load_request(request_id, user_id)
    a, b = req["from_user_id"], req["to_user_id"]
    # Symmetric rows: "my friends" stays a plain equality filter.
    table("friendships").insert([
        {"user_id": a, "friend_id": b},
        {"user_id": b, "friend_id": a},
    ])
    table("friend_requests").update(
        {"status": "accepted", "responded_at": datetime.now(timezone.utc).isoformat()},
        filters={"id": f"eq.{request_id}"},
    )
    check_achievements(a, "friends_count")
    check_achievements(b, "friends_count")
    return {"accepted": True}


@router.post("/friends/requests/{request_id}/decline")
def decline_friend_request(request_id: str, user_id: str):
    _load_request(request_id, user_id)
    table("friend_requests").update(
        {"status": "declined", "responded_at": datetime.now(timezone.utc).isoformat()},
        filters={"id": f"eq.{request_id}"},
    )
    return {"declined": True}


@router.delete("/friends/{friend_id}")
def remove_friend(friend_id: str, user_id: str):
    table("friendships").delete(
        filters={"user_id": f"eq.{user_id}", "friend_id": f"eq.{friend_id}"}
    )
    table("friendships").delete(
        filters={"user_id": f"eq.{friend_id}", "friend_id": f"eq.{user_id}"}
    )
    return {"removed": True}


@router.get("/friends/{user_id}")
def list_friends(user_id: str):
    rows = table("friendships").select("friend_id", filters={"user_id": f"eq.{user_id}"})
    ids = [r["friend_id"] for r in rows or []]
    if not ids:
        return {"friends": []}
    users = table("users").select(
        "id,level,total_xp", filters={"id": f"in.({','.join(ids)})"}
    ) or []
    names = get_display_names(ids)
    return {"friends": [
        {
            "user_id": u["id"],
            "name": names.get(u["id"], "Someone"),
            "level": u.get("level") or 1,
            "total_xp": u.get("total_xp") or 0,
        }
        for u in users
    ]}


@router.get("/friends/requests")
def list_friend_requests(user_id: str):
    incoming = table("friend_requests").select(
        "id,from_user_id,created_at",
        filters={"to_user_id": f"eq.{user_id}", "status": "eq.pending"},
    ) or []
    outgoing = table("friend_requests").select(
        "id,to_user_id,created_at",
        filters={"from_user_id": f"eq.{user_id}", "status": "eq.pending"},
    ) or []
    ids = [r["from_user_id"] for r in incoming] + [r["to_user_id"] for r in outgoing]
    names = get_display_names(ids) if ids else {}
    return {
        "incoming": [
            {**r, "name": names.get(r["from_user_id"], "Someone")} for r in incoming
        ],
        "outgoing": [
            {**r, "name": names.get(r["to_user_id"], "Someone")} for r in outgoing
        ],
    }
```

**Route ordering matters:** `/friends/requests` must be declared before `/friends/{user_id}`, or FastAPI matches `requests` as a `user_id`. The order above is correct — keep it.

- [ ] **Step 5: Run tests**

Run from `backend/`: `python -m pytest tests/test_friends_routes.py -q`
Expected: PASS, 9 tests.

- [ ] **Step 6: Lint and commit**

```bash
cd backend && ruff check routes/social.py models.py
git add backend/routes/social.py backend/models.py backend/tests/test_friends_routes.py
git commit -m "feat(social): friends — requests, accept/decline, list"
```

---

### Task 8: Gamification API

**Files:**
- Create: `backend/routes/gamification.py`
- Create: `backend/tests/test_gamification_routes.py`
- Modify: `backend/main.py:220`

**Interfaces:**
- Consumes: `services.growth` (Task 3), `services.profiles.get_display_names`.
- Produces:
  - `GET /api/gamification/me?user_id=` → `{level, stage:{slug,name,blurb}, total_xp, xp_into_level, xp_for_level, level_pct, streak, longest_streak, daily_goal_xp, today_xp, earned_count, total_count}`
  - `GET /api/gamification/leaderboard?user_id=&scope=everyone|friends|school` → `{rows: [{rank,user_id,name,level,stage,total_xp,week_xp,streak,is_you}], you: {...}|null, resets_at}`
  - `GET /api/gamification/activity?user_id=` → `{week:[{day,xp}], trend:[{label,xp}], tiles:{week_total,daily_avg,best_day,best_day_label,streak}}`

- [ ] **Step 1: Write the failing tests**

```python
"""Gamification endpoints — hero card, leaderboards, activity."""
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from main import app

client = TestClient(app)

STAGE = {"slug": "seed", "name": "Seed", "blurb": "b", "min_level": 10,
         "xp_to_complete": 500, "sort_order": 2}


def _tables(handles):
    return lambda name: handles[name]


class TestMe:
    def test_reports_level_stage_and_progress(self):
        handles = {"users": MagicMock(), "xp_events": MagicMock(),
                   "user_achievements": MagicMock(), "achievements": MagicMock()}
        handles["users"].select.return_value = [{
            "total_xp": 720, "level": 12, "streak_count": 23,
            "longest_streak": 31, "daily_goal_xp": 50,
        }]
        handles["xp_events"].select.return_value = [
            {"amount": 40, "created_at": datetime.now(timezone.utc).isoformat()}
        ]
        handles["user_achievements"].select.return_value = [{"achievement_id": "a1"}]
        handles["achievements"].select.return_value = [{"id": "a1"}, {"id": "a2"}]
        with patch("routes.gamification.table", side_effect=_tables(handles)), \
             patch("routes.gamification.stage_for_level", return_value=STAGE), \
             patch("routes.gamification.xp_into_level", return_value=(20, 100)):
            r = client.get("/api/gamification/me?user_id=u1")
        body = r.json()
        assert body["level"] == 12
        assert body["stage"]["name"] == "Seed"
        assert body["xp_into_level"] == 20
        assert body["level_pct"] == 20
        assert body["today_xp"] == 40
        assert body["earned_count"] == 1
        assert body["total_count"] == 2

    def test_the_badge_total_counts_live_only(self):
        handles = {"users": MagicMock(), "xp_events": MagicMock(),
                   "user_achievements": MagicMock(), "achievements": MagicMock()}
        handles["users"].select.return_value = [{"total_xp": 0, "level": 1}]
        for k in ("xp_events", "user_achievements", "achievements"):
            handles[k].select.return_value = []
        with patch("routes.gamification.table", side_effect=_tables(handles)), \
             patch("routes.gamification.stage_for_level", return_value=STAGE), \
             patch("routes.gamification.xp_into_level", return_value=(0, 50)):
            client.get("/api/gamification/me?user_id=u1")
        # Drafts are work-in-progress and must not inflate the denominator.
        assert handles["achievements"].select.call_args.kwargs["filters"] == {
            "status": "eq.live"
        }

    def test_sends_a_private_cache_control(self):
        handles = {"users": MagicMock(), "xp_events": MagicMock(),
                   "user_achievements": MagicMock(), "achievements": MagicMock()}
        handles["users"].select.return_value = [{"total_xp": 0, "level": 1}]
        for k in ("xp_events", "user_achievements", "achievements"):
            handles[k].select.return_value = []
        with patch("routes.gamification.table", side_effect=_tables(handles)), \
             patch("routes.gamification.stage_for_level", return_value=STAGE), \
             patch("routes.gamification.xp_into_level", return_value=(0, 50)):
            r = client.get("/api/gamification/me?user_id=u1")
        assert "private" in r.headers["cache-control"]
        assert "public" not in r.headers["cache-control"]


class TestLeaderboard:
    def _week_events(self):
        now = datetime.now(timezone.utc).isoformat()
        return [
            {"user_id": "u1", "amount": 300, "created_at": now},
            {"user_id": "u2", "amount": 500, "created_at": now},
            {"user_id": "u3", "amount": 100, "created_at": now},
        ]

    def test_ranks_by_weekly_xp_descending(self):
        handles = {"xp_events": MagicMock(), "users": MagicMock(),
                   "user_settings": MagicMock(), "friendships": MagicMock()}
        handles["xp_events"].select.return_value = self._week_events()
        handles["users"].select.return_value = [
            {"id": "u1", "level": 5, "total_xp": 900, "streak_count": 3},
            {"id": "u2", "level": 9, "total_xp": 2000, "streak_count": 12},
            {"id": "u3", "level": 2, "total_xp": 200, "streak_count": 1},
        ]
        handles["user_settings"].select.return_value = []
        with patch("routes.gamification.table", side_effect=_tables(handles)), \
             patch("routes.gamification.stage_for_level", return_value=STAGE), \
             patch("routes.gamification.get_display_names",
                   return_value={"u1": "A", "u2": "B", "u3": "C"}):
            r = client.get("/api/gamification/leaderboard?user_id=u1&scope=everyone")
        rows = r.json()["rows"]
        assert [x["rank"] for x in rows] == [1, 2, 3]
        assert rows[0]["user_id"] == "u2"
        assert rows[1]["is_you"] is True

    def test_private_users_are_hidden_but_still_see_themselves(self):
        handles = {"xp_events": MagicMock(), "users": MagicMock(),
                   "user_settings": MagicMock(), "friendships": MagicMock()}
        handles["xp_events"].select.return_value = self._week_events()
        handles["users"].select.return_value = [
            {"id": "u1", "level": 5, "total_xp": 900, "streak_count": 3},
            {"id": "u2", "level": 9, "total_xp": 2000, "streak_count": 12},
            {"id": "u3", "level": 2, "total_xp": 200, "streak_count": 1},
        ]
        handles["user_settings"].select.return_value = [
            {"user_id": "u2", "profile_visibility": "private"}
        ]
        with patch("routes.gamification.table", side_effect=_tables(handles)), \
             patch("routes.gamification.stage_for_level", return_value=STAGE), \
             patch("routes.gamification.get_display_names",
                   return_value={"u1": "A", "u3": "C"}):
            r = client.get("/api/gamification/leaderboard?user_id=u1&scope=everyone")
        ids = [x["user_id"] for x in r.json()["rows"]]
        assert "u2" not in ids
        assert r.json()["you"]["user_id"] == "u1"

    def test_private_viewer_sees_their_own_row(self):
        handles = {"xp_events": MagicMock(), "users": MagicMock(),
                   "user_settings": MagicMock(), "friendships": MagicMock()}
        handles["xp_events"].select.return_value = self._week_events()
        handles["users"].select.return_value = [
            {"id": "u1", "level": 5, "total_xp": 900, "streak_count": 3},
        ]
        handles["user_settings"].select.return_value = [
            {"user_id": "u1", "profile_visibility": "private"}
        ]
        with patch("routes.gamification.table", side_effect=_tables(handles)), \
             patch("routes.gamification.stage_for_level", return_value=STAGE), \
             patch("routes.gamification.get_display_names", return_value={"u1": "A"}):
            r = client.get("/api/gamification/leaderboard?user_id=u1&scope=everyone")
        assert r.json()["you"]["user_id"] == "u1"

    def test_friends_scope_filters_to_friends_plus_self(self):
        handles = {"xp_events": MagicMock(), "users": MagicMock(),
                   "user_settings": MagicMock(), "friendships": MagicMock()}
        handles["friendships"].select.return_value = [{"friend_id": "u3"}]
        handles["xp_events"].select.return_value = self._week_events()
        handles["users"].select.return_value = [
            {"id": "u1", "level": 5, "total_xp": 900, "streak_count": 3},
            {"id": "u3", "level": 2, "total_xp": 200, "streak_count": 1},
        ]
        handles["user_settings"].select.return_value = []
        with patch("routes.gamification.table", side_effect=_tables(handles)), \
             patch("routes.gamification.stage_for_level", return_value=STAGE), \
             patch("routes.gamification.get_display_names",
                   return_value={"u1": "A", "u3": "C"}):
            r = client.get("/api/gamification/leaderboard?user_id=u1&scope=friends")
        assert {x["user_id"] for x in r.json()["rows"]} == {"u1", "u3"}

    def test_rejects_an_unknown_scope(self):
        with patch("routes.gamification.table"):
            r = client.get("/api/gamification/leaderboard?user_id=u1&scope=galaxy")
        assert r.status_code == 400


class TestActivity:
    def test_buckets_the_last_seven_days(self):
        now = datetime.now(timezone.utc)
        handles = {"xp_events": MagicMock(), "users": MagicMock()}
        handles["xp_events"].select.return_value = [
            {"amount": 40, "created_at": now.isoformat()},
            {"amount": 60, "created_at": (now - timedelta(days=1)).isoformat()},
            {"amount": 25, "created_at": (now - timedelta(days=40)).isoformat()},
        ]
        handles["users"].select.return_value = [
            {"streak_count": 4, "daily_goal_xp": 50}
        ]
        with patch("routes.gamification.table", side_effect=_tables(handles)):
            r = client.get("/api/gamification/activity?user_id=u1")
        body = r.json()
        assert len(body["week"]) == 7
        assert body["week"][-1]["xp"] == 40
        assert body["week"][-2]["xp"] == 60
        assert body["tiles"]["week_total"] == 100
        assert len(body["trend"]) == 8
```

- [ ] **Step 2: Run to verify they fail**

Run from `backend/`: `python -m pytest tests/test_gamification_routes.py -q`
Expected: FAIL — 404 on every route.

- [ ] **Step 3: Implement the router**

```python
"""Gamification read endpoints — hero card, leaderboards, activity charts.

Everything here derives from the xp_events ledger. Responses carry
app-decrypted display names, so Cache-Control is always `private` (#99).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException, Request

from db.connection import table
from services import academics
from services.growth import stage_for_level, xp_into_level
from services.http_cache import cached_json, conditional, make_etag
from services.profiles import get_display_names

router = APIRouter()

SCOPES = ("everyone", "friends", "school")


def _parse_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _events_since(user_id: str | None, since: datetime) -> list[dict]:
    filters = {"created_at": f"gte.{since.isoformat()}"}
    if user_id:
        filters["user_id"] = f"eq.{user_id}"
    return table("xp_events").select(
        "user_id,amount,created_at", filters=filters
    ) or []


def _week_start(now: datetime) -> datetime:
    """Monday 00:00 UTC of the current week — the leaderboard reset boundary."""
    monday = now - timedelta(days=now.weekday())
    return monday.replace(hour=0, minute=0, second=0, microsecond=0)


@router.get("/me")
def get_me(user_id: str, request: Request):
    rows = table("users").select(
        "total_xp,level,streak_count,longest_streak,daily_goal_xp",
        filters={"id": f"eq.{user_id}"},
    )
    u = rows[0] if rows else {}
    total_xp = int(u.get("total_xp") or 0)
    level = int(u.get("level") or 1)

    earned = table("user_achievements").select(
        "achievement_id", filters={"user_id": f"eq.{user_id}"}
    ) or []
    # Live only — a work-in-progress badge must not inflate "12 of 30".
    catalog = table("achievements").select("id", filters={"status": "eq.live"}) or []

    etag = make_etag(user_id, total_xp, level, len(earned))
    not_mod = conditional(request, etag)
    if not_mod:
        return not_mod

    today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    today_xp = sum(int(e.get("amount") or 0) for e in _events_since(user_id, today))

    into, for_level = xp_into_level(total_xp)
    stage = stage_for_level(level)
    return cached_json({
        "level": level,
        "next_level": level + 1,
        "stage": {"slug": stage.get("slug"), "name": stage.get("name"),
                  "blurb": stage.get("blurb")},
        "total_xp": total_xp,
        "xp_into_level": into,
        "xp_for_level": for_level,
        "level_pct": round(into / for_level * 100) if for_level else 100,
        "streak": int(u.get("streak_count") or 0),
        "longest_streak": int(u.get("longest_streak") or 0),
        "daily_goal_xp": int(u.get("daily_goal_xp") or 50),
        "today_xp": today_xp,
        "earned_count": len(earned),
        "total_count": len(catalog),
    }, etag)


def _scope_ids(user_id: str, scope: str) -> set[str] | None:
    """Candidate user ids for a scope. None means 'no restriction'."""
    if scope == "friends":
        rows = table("friendships").select(
            "friend_id", filters={"user_id": f"eq.{user_id}"}
        ) or []
        return {r["friend_id"] for r in rows} | {user_id}
    if scope == "school":
        # `school` is NOT a column on user_profiles after the 0024 identity
        # split — it resolves through the enrollment chain. Reuse the same
        # fail-closed resolver GET /api/social/students uses (#342) rather than
        # reinventing it: an unenrolled viewer sees only themselves.
        peers = academics.school_peer_user_ids(user_id)
        return set(peers) | {user_id} if peers else {user_id}
    return None


def _private_ids() -> set[str]:
    rows = table("user_settings").select(
        "user_id,profile_visibility", filters={"profile_visibility": "eq.private"}
    ) or []
    return {r["user_id"] for r in rows}


@router.get("/leaderboard")
def get_leaderboard(user_id: str, request: Request, scope: str = "everyone"):
    if scope not in SCOPES:
        raise HTTPException(status_code=400, detail=f"scope must be one of {SCOPES}")

    now = datetime.now(timezone.utc)
    start = _week_start(now)
    events = _events_since(None, start)

    weekly: dict[str, int] = {}
    for e in events:
        uid = e.get("user_id")
        if uid:
            weekly[uid] = weekly.get(uid, 0) + int(e.get("amount") or 0)

    allowed = _scope_ids(user_id, scope)
    if allowed is not None:
        weekly = {k: v for k, v in weekly.items() if k in allowed}

    # The viewer always sees their own row, even at zero and even when private.
    weekly.setdefault(user_id, 0)

    hidden = _private_ids() - {user_id} if scope in ("everyone", "school") else set()

    ids = [k for k in weekly if k not in hidden]
    etag = make_etag(user_id, scope, len(ids), sum(weekly.get(i, 0) for i in ids))
    not_mod = conditional(request, etag)
    if not_mod:
        return not_mod

    users = table("users").select(
        "id,level,total_xp,streak_count", filters={"id": f"in.({','.join(ids)})"}
    ) if ids else []
    names = get_display_names(ids) if ids else {}
    by_id = {u["id"]: u for u in users or []}

    ranked = sorted(ids, key=lambda i: (-weekly.get(i, 0), i))
    rows, you = [], None
    for rank, uid in enumerate(ranked, start=1):
        u = by_id.get(uid, {})
        level = int(u.get("level") or 1)
        row = {
            "rank": rank,
            "user_id": uid,
            "name": names.get(uid, "Someone"),
            "level": level,
            "stage": stage_for_level(level).get("name"),
            "total_xp": int(u.get("total_xp") or 0),
            "week_xp": weekly.get(uid, 0),
            "streak": int(u.get("streak_count") or 0),
            "is_you": uid == user_id,
        }
        rows.append(row)
        if row["is_you"]:
            you = row

    return cached_json({
        "rows": rows,
        "you": you,
        "resets_at": (start + timedelta(days=7)).isoformat(),
    }, etag)


@router.get("/activity")
def get_activity(user_id: str, request: Request):
    now = datetime.now(timezone.utc)
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    since = today - timedelta(days=55)          # 8 weeks back
    events = _events_since(user_id, since)

    etag = make_etag(user_id, len(events),
                     sum(int(e.get("amount") or 0) for e in events))
    not_mod = conditional(request, etag)
    if not_mod:
        return not_mod

    daily: dict[str, int] = {}
    for e in events:
        ts = _parse_ts(e.get("created_at"))
        if ts:
            key = ts.date().isoformat()
            daily[key] = daily.get(key, 0) + int(e.get("amount") or 0)

    week = []
    for offset in range(6, -1, -1):
        day = (today - timedelta(days=offset)).date()
        week.append({"day": day.strftime("%a"), "date": day.isoformat(),
                     "xp": daily.get(day.isoformat(), 0)})

    trend = []
    for w in range(7, -1, -1):
        start = today - timedelta(days=now.weekday() + 7 * w)
        total = sum(
            daily.get((start + timedelta(days=d)).date().isoformat(), 0)
            for d in range(7)
        )
        trend.append({"label": "This" if w == 0 else start.strftime("%b %-d"),
                      "xp": total})

    urow = table("users").select(
        "streak_count,daily_goal_xp", filters={"id": f"eq.{user_id}"}
    )
    u = urow[0] if urow else {}
    week_total = sum(d["xp"] for d in week)
    active = [d for d in week if d["xp"] > 0]
    best = max(week, key=lambda d: d["xp"]) if week else {"xp": 0, "day": ""}

    return cached_json({
        "week": week,
        "trend": trend,
        "daily_goal_xp": int(u.get("daily_goal_xp") or 50),
        "tiles": {
            "week_total": week_total,
            "daily_avg": round(week_total / len(active)) if active else 0,
            "best_day": best["xp"],
            "best_day_label": best["day"],
            "streak": int(u.get("streak_count") or 0),
        },
    }, etag)
```

`strftime("%-d")` is POSIX-only. On Windows use `str(start.day)` instead — build the label as `f"{start.strftime('%b')} {start.day}"`, which is portable. Use that form.

- [ ] **Step 4: Mount the router**

In `backend/main.py`, add the import alongside the others and a mount in the block ending at line 220:

```python
app.include_router(gamification.router, prefix="/api/gamification")
```

- [ ] **Step 5: Run tests**

Run from `backend/`: `python -m pytest tests/test_gamification_routes.py -q`
Expected: PASS, 9 tests.

- [ ] **Step 6: Lint and commit**

```bash
cd backend && ruff check routes/gamification.py
git add backend/routes/gamification.py backend/main.py backend/tests/test_gamification_routes.py
git commit -m "feat(gamification): hero, leaderboard and activity endpoints"
```

---

### Task 9: Achievement icon upload

**Files:**
- Modify: `backend/services/storage_service.py`, `backend/routes/admin.py`, `backend/models.py`
- Create: `backend/tests/test_achievement_icon_upload.py`

**Interfaces:**
- Produces:
  - `storage_service.validate_icon(file_bytes: bytes, content_type: str) -> None` — raises `HTTPException(400)` on any violation.
  - `storage_service.upload_achievement_icon(achievement_id: str, file_bytes: bytes, content_type: str) -> str` — returns the public URL.
  - `POST /api/admin/achievements/{achievement_id}/icon` — body `{file_base64, content_type}` → `{"icon_url": str}`

Dimensions are parsed from the file header, never trusted from the client. PNG carries width/height as big-endian uint32 at byte offsets 16 and 20 of the IHDR chunk; WebP VP8X carries them at offset 24 as 24-bit little-endian minus-one values.

- [ ] **Step 1: Write the failing tests**

```python
"""Achievement icon upload — server-side format and dimension validation."""
import base64
import struct
import zlib

import pytest
from fastapi import HTTPException


def _png(width: int, height: int) -> bytes:
    """A minimal but structurally valid PNG with the given dimensions."""
    def chunk(tag: bytes, data: bytes) -> bytes:
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IEND", b"")


SQUARE_SVG = b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64"></svg>'
TALL_SVG = b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 128"></svg>'


class TestValidateIcon:
    def test_accepts_a_512_square_png(self):
        from services.storage_service import validate_icon
        validate_icon(_png(512, 512), "image/png")

    def test_rejects_the_wrong_dimensions(self):
        from services.storage_service import validate_icon
        with pytest.raises(HTTPException) as exc:
            validate_icon(_png(256, 256), "image/png")
        assert exc.value.status_code == 400
        assert "512" in exc.value.detail

    def test_rejects_a_non_square_png(self):
        from services.storage_service import validate_icon
        with pytest.raises(HTTPException):
            validate_icon(_png(512, 256), "image/png")

    def test_rejects_an_unsupported_content_type(self):
        from services.storage_service import validate_icon
        with pytest.raises(HTTPException) as exc:
            validate_icon(_png(512, 512), "image/gif")
        assert exc.value.status_code == 400

    def test_rejects_an_oversized_file(self):
        from services.storage_service import validate_icon
        payload = _png(512, 512) + b"\x00" * (512 * 1024)
        with pytest.raises(HTTPException) as exc:
            validate_icon(payload, "image/png")
        assert "512 KB" in exc.value.detail

    def test_accepts_a_square_svg(self):
        from services.storage_service import validate_icon
        validate_icon(SQUARE_SVG, "image/svg+xml")

    def test_rejects_a_non_square_svg(self):
        from services.storage_service import validate_icon
        with pytest.raises(HTTPException):
            validate_icon(TALL_SVG, "image/svg+xml")

    def test_rejects_an_svg_with_no_viewbox(self):
        from services.storage_service import validate_icon
        with pytest.raises(HTTPException):
            validate_icon(b"<svg></svg>", "image/svg+xml")

    def test_rejects_a_truncated_png(self):
        from services.storage_service import validate_icon
        with pytest.raises(HTTPException):
            validate_icon(b"\x89PNG\r\n\x1a\n", "image/png")


class TestUploadRoute:
    def test_stores_the_icon_and_patches_the_row(self):
        from unittest.mock import MagicMock, patch
        from fastapi.testclient import TestClient
        from main import app

        client = TestClient(app)
        payload = base64.b64encode(_png(512, 512)).decode()
        with patch("routes.admin.require_admin"), \
             patch("routes.admin.get_session_user_id", return_value="admin1"), \
             patch("routes.admin.upload_achievement_icon",
                   return_value="https://cdn/icons/a1.png") as up, \
             patch("routes.admin.table") as t, \
             patch("routes.admin.log_admin_action"):
            t.return_value.update.return_value = []
            r = client.post("/api/admin/achievements/a1/icon",
                            json={"file_base64": payload, "content_type": "image/png"})
        assert r.status_code == 200
        assert r.json()["icon_url"] == "https://cdn/icons/a1.png"
        up.assert_called_once()
```

- [ ] **Step 2: Run to verify they fail**

Run from `backend/`: `python -m pytest tests/test_achievement_icon_upload.py -q`
Expected: FAIL — `cannot import name 'validate_icon'`

- [ ] **Step 3: Implement validation and upload**

Append to `backend/services/storage_service.py`:

```python
ICON_CONTENT_TYPES = {"image/png", "image/webp", "image/svg+xml"}
ICON_SIZE_PX = 512
MAX_ICON_BYTES = 512 * 1024

_ICON_EXT = {"image/png": "png", "image/webp": "webp", "image/svg+xml": "svg"}


def _png_dimensions(data: bytes) -> tuple[int, int] | None:
    # 8-byte signature, 4-byte length, 4-byte "IHDR", then width/height.
    if len(data) < 24 or not data.startswith(b"\x89PNG\r\n\x1a\n"):
        return None
    if data[12:16] != b"IHDR":
        return None
    return struct.unpack(">II", data[16:24])


def _webp_dimensions(data: bytes) -> tuple[int, int] | None:
    if len(data) < 30 or data[:4] != b"RIFF" or data[8:12] != b"WEBP":
        return None
    fourcc = data[12:16]
    if fourcc == b"VP8X":
        w = int.from_bytes(data[24:27], "little") + 1
        h = int.from_bytes(data[27:30], "little") + 1
        return w, h
    if fourcc == b"VP8 ":
        w = int.from_bytes(data[26:28], "little") & 0x3FFF
        h = int.from_bytes(data[28:30], "little") & 0x3FFF
        return w, h
    if fourcc == b"VP8L":
        bits = int.from_bytes(data[21:25], "little")
        return (bits & 0x3FFF) + 1, ((bits >> 14) & 0x3FFF) + 1
    return None


def _svg_is_square(data: bytes) -> bool:
    match = re.search(rb'viewBox\s*=\s*["\']([^"\']+)["\']', data[:4096])
    if not match:
        return False
    parts = match.group(1).replace(b",", b" ").split()
    if len(parts) != 4:
        return False
    try:
        width, height = float(parts[2]), float(parts[3])
    except ValueError:
        return False
    return width > 0 and abs(width - height) < 0.01


def validate_icon(file_bytes: bytes, content_type: str) -> None:
    """Reject anything that would render badly in the badge grid.

    Dimensions come from the file header, not the client — an admin bypassing
    the upload form must not be able to plant a 4000px icon.
    """
    if content_type not in ICON_CONTENT_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Icon must be PNG, WebP or SVG (got {content_type})",
        )
    if len(file_bytes) > MAX_ICON_BYTES:
        raise HTTPException(status_code=400, detail="Icon must be 512 KB or smaller")

    if content_type == "image/svg+xml":
        if not _svg_is_square(file_bytes):
            raise HTTPException(
                status_code=400,
                detail="SVG icons need a square viewBox (e.g. viewBox=\"0 0 64 64\")",
            )
        return

    dims = (_png_dimensions(file_bytes) if content_type == "image/png"
            else _webp_dimensions(file_bytes))
    if not dims:
        raise HTTPException(status_code=400, detail="Could not read the image header")
    width, height = dims
    if width != ICON_SIZE_PX or height != ICON_SIZE_PX:
        raise HTTPException(
            status_code=400,
            detail=f"Icon must be exactly {ICON_SIZE_PX}x{ICON_SIZE_PX} (got {width}x{height})",
        )


def upload_achievement_icon(achievement_id: str, file_bytes: bytes, content_type: str) -> str:
    validate_icon(file_bytes, content_type)
    ext = _ICON_EXT[content_type]
    path = f"achievement-icons/{achievement_id}.{ext}"
    url = f"{_storage_base}/{STORAGE_BUCKET}/{path}"
    resp = httpx.put(
        url,
        content=file_bytes,
        headers={**_headers, "Content-Type": content_type, "x-upsert": "true"},
    )
    if resp.status_code not in (200, 201):
        body_text = (resp.text or "").strip()[:500]
        logger.warning(
            "upload_achievement_icon: Supabase storage rejected upload "
            "achievement=%s status=%d body=%s",
            achievement_id, resp.status_code, body_text,
        )
        raise HTTPException(
            status_code=502,
            detail=f"Icon upload failed (Supabase {resp.status_code}): {body_text or 'no body'}",
        )
    return f"{SUPABASE_URL}/storage/v1/object/public/{STORAGE_BUCKET}/{path}"
```

Add `import re` and `import struct` to the top of the file.

- [ ] **Step 4: Add the admin route and body model**

In `backend/models.py`:

```python
class AchievementIconBody(BaseModel):
    file_base64: str
    content_type: str
```

In `backend/routes/admin.py` (import `base64`, `AchievementIconBody`, and `upload_achievement_icon`):

```python
@router.post("/achievements/{achievement_id}/icon")
def upload_icon(achievement_id: str, body: AchievementIconBody, request: Request):
    require_admin(request)
    actor = get_session_user_id(request)
    try:
        file_bytes = base64.b64decode(body.file_base64, validate=True)
    except Exception:
        raise HTTPException(status_code=400, detail="file_base64 is not valid base64")
    icon_url = upload_achievement_icon(achievement_id, file_bytes, body.content_type)
    table("achievements").update(
        {"icon_url": icon_url}, filters={"id": f"eq.{achievement_id}"}
    )
    log_admin_action(
        actor_id=actor, action="achievement.icon", target_type="achievement",
        target_id=achievement_id, payload={"icon_url": icon_url},
    )
    return {"icon_url": icon_url}
```

Also widen the `update_achievement` allowlist at `routes/admin.py:221`:

```python
    allowed = {"name", "description", "icon", "icon_url", "category", "rarity",
               "is_secret", "xp_reward", "sort_order", "status"}
```

- [ ] **Step 5: Run tests**

Run from `backend/`: `python -m pytest tests/test_achievement_icon_upload.py tests/test_admin_routes.py -q`
Expected: PASS, 10 new tests.

- [ ] **Step 6: Lint and commit**

```bash
cd backend && ruff check services/storage_service.py routes/admin.py models.py
git add backend/services/storage_service.py backend/routes/admin.py backend/models.py backend/tests/test_achievement_icon_upload.py
git commit -m "feat(admin): 512x512 achievement icon upload with header-parsed validation"
```

---

### Task 10: XP rules admin endpoints

**Files:**
- Modify: `backend/routes/admin.py`, `backend/models.py`
- Create: `backend/tests/test_xp_rules_routes.py`

**Interfaces:**
- Produces:
  - `GET /api/admin/xp-rules` → `{"rules": [{key,label,amount,enabled,updated_at}]}`
  - `PATCH /api/admin/xp-rules/{key}` — body `{amount?, enabled?}` → `{"updated": true}`

- [ ] **Step 1: Write the failing tests**

```python
"""Admin XP-rule editing."""
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from main import app

client = TestClient(app)


class TestListRules:
    def test_returns_every_rule(self):
        with patch("routes.admin.require_admin"), patch("routes.admin.table") as t:
            t.return_value.select.return_value = [
                {"key": "quiz_completed", "label": "Completed a quiz",
                 "amount": 30, "enabled": True}
            ]
            r = client.get("/api/admin/xp-rules")
        assert r.json()["rules"][0]["key"] == "quiz_completed"


class TestUpdateRule:
    def test_updates_the_amount(self):
        with patch("routes.admin.require_admin"), \
             patch("routes.admin.get_session_user_id", return_value="admin1"), \
             patch("routes.admin.log_admin_action") as audit, \
             patch("routes.admin.table") as t:
            t.return_value.update.return_value = []
            r = client.patch("/api/admin/xp-rules/quiz_completed", json={"amount": 45})
        assert r.json() == {"updated": True}
        assert t.return_value.update.call_args[0][0]["amount"] == 45
        audit.assert_called_once()

    def test_rejects_a_negative_amount(self):
        with patch("routes.admin.require_admin"), patch("routes.admin.table"):
            r = client.patch("/api/admin/xp-rules/quiz_completed", json={"amount": -5})
        assert r.status_code == 400

    def test_rejects_an_empty_body(self):
        with patch("routes.admin.require_admin"), patch("routes.admin.table"):
            r = client.patch("/api/admin/xp-rules/quiz_completed", json={})
        assert r.status_code == 400
```

- [ ] **Step 2: Run to verify they fail**

Run from `backend/`: `python -m pytest tests/test_xp_rules_routes.py -q`
Expected: FAIL — 404.

- [ ] **Step 3: Implement**

In `backend/models.py`:

```python
class UpdateXpRuleBody(BaseModel):
    amount: Optional[int] = None
    enabled: Optional[bool] = None
```

In `backend/routes/admin.py`:

```python
# ── XP rules ─────────────────────────────────────────────────────────────────

@router.get("/xp-rules")
def list_xp_rules(request: Request):
    require_admin(request)
    rows = table("xp_rules").select("*", order="key.asc")
    return {"rules": rows or []}


@router.patch("/xp-rules/{key}")
def update_xp_rule(key: str, body: UpdateXpRuleBody, request: Request):
    require_admin(request)
    actor = get_session_user_id(request)
    updates: dict = {}
    if body.amount is not None:
        if body.amount < 0:
            raise HTTPException(status_code=400, detail="amount must be >= 0")
        updates["amount"] = body.amount
    if body.enabled is not None:
        updates["enabled"] = body.enabled
    if not updates:
        raise HTTPException(status_code=400, detail="No valid fields to update")
    updates["updated_at"] = datetime.now(timezone.utc).isoformat()
    table("xp_rules").update(updates, filters={"key": f"eq.{key}"})
    log_admin_action(
        actor_id=actor, action="xp_rule.update", target_type="xp_rule",
        target_id=key, payload=updates,
    )
    return {"updated": True}
```

- [ ] **Step 4: Run tests**

Run from `backend/`: `python -m pytest tests/test_xp_rules_routes.py -q`
Expected: PASS, 4 tests.

- [ ] **Step 5: Full backend suite, lint, commit**

```bash
cd backend && python -m pytest tests/ -q && ruff check .
git add backend/routes/admin.py backend/models.py backend/tests/test_xp_rules_routes.py
git commit -m "feat(admin): editable XP rules"
```

---

### Task 11: Frontend level maths and badge art

**Files:**
- Create: `frontend/src/components/growth/levels.ts`, `levels.test.ts`
- Create: `frontend/src/components/growth/BadgeArt.tsx`, `BadgeArt.test.tsx`
- Create: `frontend/public/growth/*.svg` (11 files)
- Modify: `frontend/src/lib/types.ts`

**Interfaces:**
- Produces:
  - `RARITY_DISC: Record<RarityTier, {band, gl, gd, br}>` and `LOCKED_DISC`
  - `discFor(rarity: RarityTier, locked: boolean)`
  - `BadgeArt({ slug, rarity, locked, iconUrl, emoji, size })` — React component
  - `stageAssetPath(slug: string): string`
  - Types `GrowthStage`, `GamificationMe`, `LeaderboardRow`, `ActivityData`

Colour values are copied verbatim from the design's `disc()` map — do not re-derive them.

- [ ] **Step 1: Write the failing tests**

`frontend/src/components/growth/levels.test.ts`:

```ts
import { describe, it, expect } from "vitest";
import { discFor, RARITY_DISC, stageAssetPath } from "./levels";

describe("discFor", () => {
  it("returns the rarity palette when unlocked", () => {
    expect(discFor("legendary", false)).toEqual(RARITY_DISC.legendary);
  });

  it("returns the grey palette when locked, whatever the rarity", () => {
    expect(discFor("legendary", true)).toEqual(discFor("common", true));
  });

  it("falls back to common for an unknown rarity", () => {
    expect(discFor("mythic" as never, false)).toEqual(RARITY_DISC.common);
  });
});

describe("stageAssetPath", () => {
  it("maps a slug to its committed SVG", () => {
    expect(stageAssetPath("sapling")).toBe("/growth/sapling.svg");
  });
});
```

`frontend/src/components/growth/BadgeArt.test.tsx`:

```tsx
import { describe, it, expect } from "vitest";
import { render } from "@testing-library/react";
import { BadgeArt } from "./BadgeArt";

describe("BadgeArt icon precedence", () => {
  it("prefers an uploaded icon_url", () => {
    const { container } = render(
      <BadgeArt slug="on-fire" rarity="rare" locked={false}
                iconUrl="https://cdn/x.png" emoji="🔥" />,
    );
    expect(container.querySelector("image")?.getAttribute("href")).toBe("https://cdn/x.png");
  });

  it("falls back to the built-in icon when there is no upload", () => {
    const { container } = render(
      <BadgeArt slug="on-fire" rarity="rare" locked={false} emoji="🔥" />,
    );
    expect(container.querySelector("image")).toBeNull();
    expect(container.querySelector('[data-icon="on-fire"]')).not.toBeNull();
  });

  it("falls back to the emoji when the slug has no built-in art", () => {
    const { container } = render(
      <BadgeArt slug="made-up-slug" rarity="common" locked={false} emoji="🌱" />,
    );
    expect(container.textContent).toContain("🌱");
  });

  it("renders a default star when there is nothing at all", () => {
    const { container } = render(
      <BadgeArt slug="made-up-slug" rarity="common" locked={false} />,
    );
    expect(container.textContent).toContain("★");
  });

  it("greys the disc when locked", () => {
    const { container } = render(
      <BadgeArt slug="on-fire" rarity="legendary" locked />,
    );
    expect(container.innerHTML).toContain("#eceae4");
  });
});
```

- [ ] **Step 2: Run to verify they fail**

Run from `frontend/`:
```
fnm exec --using=v22.23.1 -- node ./node_modules/vitest/vitest.mjs run src/components/growth
```
Expected: FAIL — cannot resolve `./levels`.

- [ ] **Step 3: Implement `levels.ts`**

```ts
import type { RarityTier } from "@/lib/types";

// Disc palettes copied verbatim from the design's disc() map:
// band = outer ring, gl/gd = inner radial gradient stops, br = border ring.
export const RARITY_DISC: Record<RarityTier, { band: string; gl: string; gd: string; br: string }> = {
  common:    { band: "#c9c6bd", gl: "#a8a498", gd: "#807b6d", br: "#645f51" },
  uncommon:  { band: "#a7c49a", gl: "#7a9e79", gd: "#4f7757", br: "#38603f" },
  rare:      { band: "#9ad3d8", gl: "#72bcc3", gd: "#3f8f98", br: "#2f727a" },
  epic:      { band: "#cdb9f6", gl: "#ab8ef0", gd: "#8059d6", br: "#6842b8" },
  legendary: { band: "#eed79c", gl: "#dcbd6f", gd: "#b4934a", br: "#8f7333" },
};

export const LOCKED_DISC = { band: "#eceae4", gl: "#ffffff", gd: "#e4e1d8", br: "#c3bfb2" };

export function discFor(rarity: RarityTier, locked: boolean) {
  if (locked) return LOCKED_DISC;
  return RARITY_DISC[rarity] ?? RARITY_DISC.common;
}

export const STAGE_SLUGS = [
  "bare", "soil", "seed", "sprout", "seedling",
  "sapling", "young", "branch", "bloom", "fruit", "old",
] as const;

export function stageAssetPath(slug: string): string {
  return `/growth/${slug}.svg`;
}
```

- [ ] **Step 4: Implement `BadgeArt.tsx`**

```tsx
"use client";
import React from "react";
import type { RarityTier } from "@/lib/types";
import { discFor } from "./levels";

// Built-in icon art, keyed by slug. Each entry is the inner SVG for a
// 48-unit viewBox; `c` is the main fill and `l` the secondary. Ported from
// the design's iconPaths(). Slugs with no entry fall through to the emoji.
const ICON_PATHS: Record<string, (c: string, l: string) => string> = {
  "first-steps": (c, l) =>
    `<rect x="22.4" y="19" width="3.2" height="21" rx="1.6" fill="${c}"/>` +
    `<path d="M24 30c-2-8-9-11-16-10 0 8 7 12 16 10Z" fill="${l}"/>` +
    `<path d="M24 26c2-9 9-12 16-11 0 8-7 12-16 11Z" fill="${c}"/>` +
    `<circle cx="24" cy="17.5" r="2.8" fill="${c}"/>`,
  "on-fire": (c, l) =>
    `<path d="M24 6c5 6-1 11-1 15 0 3 2 4 4 3 2-1 2-4 1-7 5 3 8 8 8 13a12 12 0 0 1-24 0c0-6 4-9 6-13 2-4 4-6 3-11Z" fill="${c}"/>` +
    `<path d="M24 40a6 6 0 0 0 3-11c0 3-2 4-3 3-1 3-4 2-4 0-2 2-2 3-2 4a6 6 0 0 0 6 4Z" fill="${l}"/>`,
  // The other 28 entries are transcribed mechanically — see Step 4b.
};

// Per-icon colours [main, shade], verbatim from the design's iconColor().
const ICON_COLORS: Record<string, [string, string]> = {
  "first-steps": ["#c8dd97", "#e8f0b4"],
  "on-fire": ["#ffb07f", "#ffdca0"],
  // The other 28 entries are transcribed mechanically — see Step 4b.
};

const LOCKED_COLORS: [string, string] = ["#cbc8c0", "#e6e3db"];

export function BadgeArt({
  slug, rarity, locked, iconUrl, emoji, size = 80,
}: {
  slug: string;
  rarity: RarityTier;
  locked: boolean;
  iconUrl?: string | null;
  emoji?: string | null;
  size?: number;
}) {
  const d = discFor(rarity, locked);
  const id = React.useId().replace(/:/g, "");
  const builtIn = ICON_PATHS[slug];
  const [main, shade] = locked ? LOCKED_COLORS : (ICON_COLORS[slug] ?? ["#bcd678", "#e4ef9c"]);

  return (
    <svg viewBox="0 0 64 64" width={size} height={size} style={{ display: "block", overflow: "visible" }}>
      <defs>
        <radialGradient id={`bg-${id}`} cx="40%" cy="33%" r="72%">
          <stop offset="0%" stopColor={d.gl} />
          <stop offset="100%" stopColor={d.gd} />
        </radialGradient>
        <clipPath id={`clip-${id}`}><circle cx="32" cy="32" r="23.2" /></clipPath>
      </defs>
      <circle cx="32" cy="33.4" r="30" fill="rgba(19,38,16,0.16)" />
      <circle cx="32" cy="32" r="30" fill={d.band} stroke="rgba(0,0,0,0.06)" strokeWidth="1" />
      <circle cx="32" cy="32" r="23.2" fill={`url(#bg-${id})`} stroke={d.br} strokeWidth="2.6" />
      {iconUrl ? (
        <image
          href={iconUrl} x="17" y="17" width="30" height="30"
          clipPath={`url(#clip-${id})`} preserveAspectRatio="xMidYMid meet"
          style={locked ? { filter: "grayscale(1) opacity(0.55)" } : undefined}
        />
      ) : builtIn ? (
        <svg x="17" y="17" width="30" height="30" viewBox="0 0 48 48" fill="none"
             data-icon={slug}
             dangerouslySetInnerHTML={{ __html: builtIn(main, shade) }} />
      ) : (
        <text x="32" y="39" textAnchor="middle" fontSize="20"
              style={locked ? { filter: "grayscale(1) opacity(0.5)" } : undefined}>
          {emoji || "★"}
        </text>
      )}
    </svg>
  );
}
```

- [ ] **Step 4b: Transcribe the remaining 28 icons mechanically**

Do not hand-copy these — the paths are long and a single mistyped coordinate is
invisible until it renders wrong. Extract them with a script instead.

The design file is already saved locally at
`C:\Users\Jack\AppData\Local\Temp\claude\C--Users-Jack-Desktop-VS-Code-sapling\c39b31a2-2415-4e73-9081-bcb5e8824b45\scratchpad\Achievements.dc.html`.
If it is gone, re-fetch it with the `DesignSync` tool (`method: get_file`,
`projectId: 3aab5746-8bd8-4649-88f3-7d0901d9272a`, `path: Achievements.dc.html`).

In that file, `iconPaths(slug, c, L, lk)` at line 875 holds a single object
literal `A` whose keys are the 30 slugs and whose values are template literals
using `${c}` (main), `${L}` (shade), and `ac(...)` / `ac2(...)` for accent
colours that grey out when locked. `iconColor(slug, locked)` at line 928 holds
the `[main, shade]` pairs.

Transcription rules:
- `${c}` → `${c}` and `${L}` → `${l}` (the TS helper's second parameter is lowercase `l`).
- `${ac('#xxxxxx')}` and `${ac2('#xxxxxx')}` → the literal hex when unlocked. Because
  `BadgeArt` already passes `LOCKED_COLORS` for `main`/`shade` when locked, replace
  each `ac(v)`/`ac2(v)` call with a ternary on a `locked` third parameter, or —
  simpler and sufficient here — inline the unlocked hex and let the disc's grey
  palette plus the `grayscale(1)` filter carry the locked look.
- Keep every coordinate exactly as written.

The 28 remaining slugs: `flash`, `bookworm`, `early-bird`, `night-owl`,
`deep-focus`, `quiz-master`, `marathon`, `wildfire`, `first-friend`,
`study-circle`, `helping-hand`, `room-leader`, `popular`, `mentor`,
`social-butterfly`, `sprout`, `rooted`, `grade-a`, `branching`, `rings`, `web`,
`canopy`, `old-growth`, `methuselah`, `perfect-week`, `comeback`, `polymath`,
`golden-hour`, `secret`.

Verify with a render check after transcribing — every live slug must produce
built-in art rather than falling through to the emoji:

```tsx
it("has built-in art for every live catalog slug", () => {
  const LIVE_SLUGS = ["first-steps","flash","early-bird","night-owl","on-fire",
    "deep-focus","quiz-master","marathon","wildfire","first-friend","study-circle",
    "helping-hand","room-leader","popular","social-butterfly","mentor","sprout",
    "rooted","grade-a","branching","rings","canopy","web","old-growth",
    "golden-hour","comeback","perfect-week","secret","methuselah","polymath"];
  for (const slug of LIVE_SLUGS) {
    const { container } = render(
      <BadgeArt slug={slug} rarity="common" locked={false} />,
    );
    expect(container.querySelector(`[data-icon="${slug}"]`), slug).not.toBeNull();
  }
});
```

Add that test to `BadgeArt.test.tsx`. It fails until all 30 are present, which is
exactly the signal you want.

- [ ] **Step 5: Generate the eleven stage SVGs**

The design's `stageDisc()` + `tree()` engine is deterministic. Extract it into a throwaway Node script and write the output once:

```bash
mkdir -p frontend/public/growth
node scripts/render-growth-stages.mjs   # writes bare.svg … old.svg
```

Build `scripts/render-growth-stages.mjs` by copying these members from the design file `Achievements.dc.html` (lines 421–860): `BARK`, `FRESH`, `CROWN_*`, `_r`, `_p`, `_seg`, `_nrm`, `_lerp`, `atSpine`, `atW`, `limbPath`, `branchFrom`, `wood`, `_lobed`, `_blob`, `crown`, `roundCrown`, `shortB`, `scatter`, `leaf`, `tuft`, `flower`, `apple`, `stageDisc`, `tree`, `SPREAD_*`, and `STAGES`. For each entry in `STAGES`, call `stageDisc({key, sky, plant, glow, turf, turf2, bare, ring: ringT})` and write the returned string to `frontend/public/growth/<key>.svg` with an `<?xml version="1.0" encoding="UTF-8"?>` prolog.

Delete the script after the assets are committed — it is build-time scaffolding, not shipped code.

- [ ] **Step 6: Add the new types**

Append to `frontend/src/lib/types.ts`:

```ts
export interface GrowthStage { slug: string; name: string; blurb: string; }

export interface GamificationMe {
  level: number;
  next_level: number;
  stage: GrowthStage;
  total_xp: number;
  xp_into_level: number;
  xp_for_level: number;
  level_pct: number;
  streak: number;
  longest_streak: number;
  daily_goal_xp: number;
  today_xp: number;
  earned_count: number;
  total_count: number;
}

export interface LeaderboardRow {
  rank: number;
  user_id: string;
  name: string;
  level: number;
  stage: string;
  total_xp: number;
  week_xp: number;
  streak: number;
  is_you: boolean;
}

export interface ActivityData {
  week: { day: string; date: string; xp: number }[];
  trend: { label: string; xp: number }[];
  daily_goal_xp: number;
  tiles: {
    week_total: number;
    daily_avg: number;
    best_day: number;
    best_day_label: string;
    streak: number;
  };
}

export interface Friend {
  user_id: string;
  name: string;
  level: number;
  total_xp: number;
}
```

Also extend `Achievement` with `xp_reward: number;`, `icon_url: string | null;`, `sort_order: number;`.

- [ ] **Step 7: Run tests and typecheck**

Run from `frontend/`:
```
fnm exec --using=v22.23.1 -- node ./node_modules/vitest/vitest.mjs run src/components/growth
fnm exec --using=v22.23.1 -- node ./node_modules/typescript/bin/tsc --noEmit
```
Expected: PASS, 8 tests; typecheck clean.

- [ ] **Step 8: Commit**

```bash
git add frontend/src/components/growth frontend/public/growth frontend/src/lib/types.ts
git commit -m "feat(frontend): badge art compositor and pre-rendered growth stages"
```

---

### Task 12: Frontend API client

**Files:**
- Modify: `frontend/src/lib/api.ts`

**Interfaces:**
- Produces: `fetchGamificationMe`, `fetchLeaderboard`, `fetchActivity`, `fetchFriends`, `fetchFriendRequests`, `sendFriendRequest`, `acceptFriendRequest`, `declineFriendRequest`, `removeFriend`, `adminListXpRules`, `adminUpdateXpRule`, `adminUploadAchievementIcon`, `adminUpdateAchievement`.

- [ ] **Step 1: Add the functions**

```ts
// ── Gamification ─────────────────────────────────────────────────────────────
export const fetchGamificationMe = (userId: string) =>
  fetchJSON<GamificationMe>(`/api/gamification/me?user_id=${encodeURIComponent(userId)}`);

export const fetchLeaderboard = (userId: string, scope: 'everyone' | 'friends' | 'school') =>
  fetchJSON<{ rows: LeaderboardRow[]; you: LeaderboardRow | null; resets_at: string }>(
    `/api/gamification/leaderboard?user_id=${encodeURIComponent(userId)}&scope=${scope}`);

export const fetchActivity = (userId: string) =>
  fetchJSON<ActivityData>(`/api/gamification/activity?user_id=${encodeURIComponent(userId)}`);

// ── Friends ──────────────────────────────────────────────────────────────────
export const fetchFriends = (userId: string) =>
  fetchJSON<{ friends: Friend[] }>(`/api/social/friends/${encodeURIComponent(userId)}`);

export const fetchFriendRequests = (userId: string) =>
  fetchJSON<{
    incoming: { id: string; from_user_id: string; name: string; created_at: string }[];
    outgoing: { id: string; to_user_id: string; name: string; created_at: string }[];
  }>(`/api/social/friends/requests?user_id=${encodeURIComponent(userId)}`);

export const sendFriendRequest = (fromUserId: string, toUserId: string) =>
  fetchJSON<{ request: { id: string } }>('/api/social/friends/request', {
    method: 'POST',
    body: JSON.stringify({ from_user_id: fromUserId, to_user_id: toUserId }),
  });

export const acceptFriendRequest = (requestId: string, userId: string) =>
  fetchJSON<{ accepted: boolean }>(
    `/api/social/friends/requests/${encodeURIComponent(requestId)}/accept?user_id=${encodeURIComponent(userId)}`,
    { method: 'POST' });

export const declineFriendRequest = (requestId: string, userId: string) =>
  fetchJSON<{ declined: boolean }>(
    `/api/social/friends/requests/${encodeURIComponent(requestId)}/decline?user_id=${encodeURIComponent(userId)}`,
    { method: 'POST' });

export const removeFriend = (friendId: string, userId: string) =>
  fetchJSON<{ removed: boolean }>(
    `/api/social/friends/${encodeURIComponent(friendId)}?user_id=${encodeURIComponent(userId)}`,
    { method: 'DELETE' });

// ── Admin — XP rules and icons ───────────────────────────────────────────────
export const adminListXpRules = () =>
  fetchJSON<{ rules: { key: string; label: string; amount: number; enabled: boolean }[] }>(
    '/api/admin/xp-rules');

export const adminUpdateXpRule = (key: string, patch: { amount?: number; enabled?: boolean }) =>
  fetchJSON<{ updated: boolean }>(`/api/admin/xp-rules/${encodeURIComponent(key)}`, {
    method: 'PATCH', body: JSON.stringify(patch),
  });

export const adminUpdateAchievement = (
  achievementId: string,
  patch: Partial<Pick<Achievement, 'name' | 'description' | 'category' | 'rarity' | 'is_secret'>>
    & { xp_reward?: number; sort_order?: number; status?: 'draft' | 'live' },
) =>
  fetchJSON<{ updated: boolean }>(`/api/admin/achievements/${encodeURIComponent(achievementId)}`, {
    method: 'PATCH', body: JSON.stringify(patch),
  });

export const adminUploadAchievementIcon = (
  achievementId: string, fileBase64: string, contentType: string,
) =>
  fetchJSON<{ icon_url: string }>(
    `/api/admin/achievements/${encodeURIComponent(achievementId)}/icon`, {
      method: 'POST',
      body: JSON.stringify({ file_base64: fileBase64, content_type: contentType }),
    });
```

Extend the type import at the top of the file with `GamificationMe`, `LeaderboardRow`, `ActivityData`, `Friend`.

- [ ] **Step 2: Typecheck**

Run from `frontend/`: `fnm exec --using=v22.23.1 -- node ./node_modules/typescript/bin/tsc --noEmit`
Expected: clean.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/lib/api.ts
git commit -m "feat(frontend): API client for gamification, friends and XP rules"
```

---

### Task 13: Achievements screen — hero and badge grid

**Files:**
- Create: `frontend/src/components/screens/achievements/HeroCard.tsx`, `BadgeGrid.tsx`, `BadgeModal.tsx`
- Modify: `frontend/src/components/screens/Achievements.tsx`

**Interfaces:**
- Consumes: `BadgeArt` (Task 11), `fetchGamificationMe`, `fetchAchievements` (Task 12).
- Produces: `<HeroCard me={GamificationMe} />`, `<BadgeGrid achievements earned onOpen />`, `<BadgeModal ... onClose />`

- [ ] **Step 1: Build `HeroCard.tsx`**

```tsx
"use client";
import React from "react";
import type { GamificationMe } from "@/lib/types";
import { stageAssetPath } from "@/components/growth/levels";

export function HeroCard({ me }: { me: GamificationMe }) {
  const R = 68;
  const C = 2 * Math.PI * R;
  return (
    <div className="card" style={{ padding: "24px 30px", display: "flex", alignItems: "center", gap: 30, marginBottom: 16 }}>
      <div style={{ position: "relative", width: 132, height: 132, flexShrink: 0, display: "flex", alignItems: "center", justifyContent: "center" }}>
        <svg width={150} height={150} viewBox="0 0 150 150" style={{ position: "absolute", transform: "rotate(-90deg)" }}>
          <circle cx={75} cy={75} r={R} fill="none" stroke="var(--bg-soft)" strokeWidth={8} />
          <circle cx={75} cy={75} r={R} fill="none" stroke="var(--accent)" strokeWidth={8}
                  strokeLinecap="round" strokeDasharray={C}
                  strokeDashoffset={C * (1 - me.level_pct / 100)} />
        </svg>
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img src={stageAssetPath(me.stage.slug)} alt={me.stage.name}
             width={92} height={92}
             style={{ position: "absolute", borderRadius: "50%" }} />
        <div style={{ position: "absolute", bottom: -4, left: "50%", transform: "translateX(-50%)",
                      background: "var(--accent)", color: "#fff", fontSize: 10.5, fontWeight: 600,
                      padding: "3px 10px", borderRadius: "var(--r-full)", whiteSpace: "nowrap" }}>
          LVL {me.level}
        </div>
      </div>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div className="label-micro">Growth stage · Level {me.level}</div>
        <div style={{ display: "flex", alignItems: "baseline", gap: 12, flexWrap: "wrap", marginTop: 3 }}>
          <span style={{ fontSize: 30, fontWeight: 600, letterSpacing: "-0.02em" }}>{me.stage.name}</span>
          <span style={{ fontSize: 14, fontStyle: "italic", color: "var(--text-dim)" }}>{me.stage.blurb}</span>
        </div>
        <div style={{ marginTop: 16, maxWidth: 560 }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", marginBottom: 6, gap: 10 }}>
            <span style={{ fontSize: 12, fontWeight: 600 }}>{me.total_xp.toLocaleString()} XP total</span>
            <span style={{ fontSize: 11, color: "var(--text-muted)", whiteSpace: "nowrap" }}>
              {me.xp_for_level > 0
                ? `${me.xp_into_level} / ${me.xp_for_level} XP → Level ${me.next_level}`
                : "Highest stage reached"}
            </span>
          </div>
          <div style={{ height: 9, background: "var(--bg-soft)", borderRadius: "var(--r-full)", overflow: "hidden" }}>
            <div style={{ height: "100%", width: `${me.level_pct}%`, background: "var(--accent)", borderRadius: "var(--r-full)" }} />
          </div>
        </div>
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Build `BadgeGrid.tsx` and `BadgeModal.tsx`**

```tsx
"use client";
import React from "react";
import { BadgeArt } from "@/components/growth/BadgeArt";
import type { Achievement, AchievementCategory, UserAchievement } from "@/lib/types";

const CAT_ORDER: AchievementCategory[] = ["activity", "social", "milestone", "special"];

// Category copy, verbatim from the design's CAT_META.
const CAT_META: Record<AchievementCategory, { label: string; blurb: string }> = {
  activity:  { label: "Activity",  blurb: "Show up, study, and keep the streak alive." },
  social:    { label: "Social",    blurb: "Learning grows faster in good company." },
  milestone: { label: "Milestone", blurb: "The long arc of mastery, one concept at a time." },
  special:   { label: "Special",   blurb: "Rare feats, seasonal moments, and the occasional secret." },
};

export function BadgeGrid({
  achievements, earnedById, onOpen,
}: {
  achievements: Achievement[];
  earnedById: Map<string, UserAchievement>;
  onOpen: (a: Achievement) => void;
}) {
  return (
    <>
      {CAT_ORDER.map((cat) => {
        const list = achievements.filter((a) => a.category === cat);
        if (!list.length) return null;
        const earnedCount = list.filter((a) => earnedById.has(a.id)).length;
        // Earned badges float to the top of their section.
        const ordered = [...list].sort(
          (a, b) => Number(earnedById.has(b.id)) - Number(earnedById.has(a.id))
            || a.sort_order - b.sort_order,
        );
        return (
          <section key={cat} style={{ marginBottom: 38 }}>
            <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 4 }}>
              <h2 style={{ margin: 0, fontSize: 21, fontWeight: 600 }}>{CAT_META[cat].label}</h2>
              <span className="chip">{earnedCount} / {list.length}</span>
            </div>
            <div style={{ fontSize: 12.5, color: "var(--text-muted)", marginBottom: 16, maxWidth: 640 }}>
              {CAT_META[cat].blurb}
            </div>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(268px, 1fr))", gap: 14 }}>
              {ordered.map((a) => {
                const ua = earnedById.get(a.id);
                const earned = !!ua;
                const secret = a.is_secret && !earned;
                const pct = a.progress
                  ? Math.min(100, Math.round((a.progress.current / Math.max(1, a.progress.target)) * 100))
                  : null;
                return (
                  <button
                    key={a.id}
                    onClick={() => onOpen(a)}
                    className="card"
                    style={{ textAlign: "left", padding: 18, display: "flex", gap: 15,
                             alignItems: "flex-start", cursor: "pointer" }}
                  >
                    <div style={{ width: 80, height: 80, flexShrink: 0 }}>
                      <BadgeArt slug={secret ? "secret" : a.slug} rarity={a.rarity}
                                locked={!earned} iconUrl={a.icon_url} emoji={a.icon} size={80} />
                    </div>
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <div style={{ display: "flex", justifyContent: "space-between",
                                    alignItems: "baseline", gap: 6 }}>
                        <div style={{ fontWeight: 600, fontSize: 14.5 }}>
                          {secret ? "???" : a.name}
                        </div>
                        <span className="chip">{a.rarity}</span>
                      </div>
                      <div style={{ fontSize: 12, color: "var(--text-dim)", marginTop: 5, lineHeight: 1.45 }}>
                        {secret ? "A hidden achievement. Keep exploring to discover it." : a.description}
                      </div>
                      {earned && (
                        <div style={{ marginTop: 10, fontSize: 11, color: "var(--accent)", fontWeight: 500 }}>
                          Earned {new Date(ua.earned_at).toLocaleDateString()} · +{a.xp_reward} XP
                        </div>
                      )}
                      {!earned && pct !== null && (
                        <div style={{ marginTop: 11 }}>
                          <div style={{ height: 5, background: "var(--bg-soft)",
                                        borderRadius: "var(--r-full)", overflow: "hidden" }}>
                            <div style={{ height: "100%", width: `${pct}%`, background: "var(--accent)" }} />
                          </div>
                          <div style={{ display: "flex", justifyContent: "space-between",
                                        fontSize: 10, color: "var(--text-muted)", marginTop: 5 }}>
                            <span>{a.progress!.current} / {a.progress!.target}</span><span>{pct}%</span>
                          </div>
                        </div>
                      )}
                      {!earned && pct === null && (
                        <div style={{ marginTop: 10, fontSize: 10, color: "var(--text-muted)",
                                      textTransform: "uppercase", letterSpacing: "0.06em" }}>
                          Locked · +{a.xp_reward} XP
                        </div>
                      )}
                    </div>
                  </button>
                );
              })}
            </div>
          </section>
        );
      })}
    </>
  );
}
```

`BadgeModal` reuses the same three states (earned line / progress bar / locked line) at 130px art, adds a `rarity · category` chip under the name, and renders the leaf burst — 14 absolutely-positioned spans on the design's `sap-burst` keyframes — only when `earned`.

`BadgeModal` renders the same art at 130px, the name, a `rarity · category` chip, the description, and either the earned line (`Earned {date} · +{xp} XP`), the progress bar, or `Not yet unlocked · +{xp} XP`. Add the leaf-burst animation only when `earned` — 14 spans on the design's `sap-burst` keyframes.

Both reuse the category blurbs from the design:
- activity: "Show up, study, and keep the streak alive."
- social: "Learning grows faster in good company."
- milestone: "The long arc of mastery, one concept at a time."
- special: "Rare feats, seasonal moments, and the occasional secret."

- [ ] **Step 3: Wire the tab shell in `Achievements.tsx`**

Add `const [tab, setTab] = React.useState<"achievements" | "leaderboard" | "activity">("achievements")` and a tab bar under the existing `TopBar`. Load `fetchGamificationMe` alongside `fetchAchievements` in the existing `load` callback. Render `<HeroCard>` plus the three-up stat row above the existing showcase, then `<BadgeGrid>` in place of the current earned/locked grids. Keep the showcase and `toggleFeature` logic exactly as it is.

The three-up stat row shows: streak (`me.streak` days, "longest {me.longest_streak}"), the daily-goal ring (`me.today_xp / me.daily_goal_xp`), and badges (`me.earned_count / me.total_count`).

- [ ] **Step 4: Typecheck, lint, run the suite**

Run from `frontend/`:
```
fnm exec --using=v22.23.1 -- node ./node_modules/typescript/bin/tsc --noEmit
fnm exec --using=v22.23.1 -- node ./node_modules/eslint/bin/eslint.js src/components/screens/achievements
fnm exec --using=v22.23.1 -- node ./node_modules/vitest/vitest.mjs run
```
Expected: all clean.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/screens/achievements frontend/src/components/screens/Achievements.tsx
git commit -m "feat(frontend): growth hero card and category badge grid"
```

---

### Task 14: Leaderboard and activity tabs

**Files:**
- Create: `frontend/src/components/screens/achievements/LeaderboardTab.tsx`, `ActivityTab.tsx`, `ActivityTab.buckets.test.ts`
- Modify: `frontend/src/components/screens/Achievements.tsx`

**Interfaces:**
- Consumes: `fetchLeaderboard`, `fetchActivity` (Task 12).
- Produces: `<LeaderboardTab userId />`, `<ActivityTab userId />`, `barHeights(values: number[], max: number, chartH: number): number[]`

- [ ] **Step 1: Write the failing test**

```ts
import { describe, it, expect } from "vitest";
import { barHeights } from "./ActivityTab";

describe("barHeights", () => {
  it("scales the tallest bar to the chart height", () => {
    expect(barHeights([50, 100], 100, 140)).toEqual([70, 140]);
  });

  it("gives a zero value a visible stub", () => {
    expect(barHeights([0, 100], 100, 140)).toEqual([4, 140]);
  });

  it("returns stubs when every value is zero", () => {
    expect(barHeights([0, 0, 0], 0, 140)).toEqual([4, 4, 4]);
  });
});
```

- [ ] **Step 2: Run to verify it fails**

Run from `frontend/`:
```
fnm exec --using=v22.23.1 -- node ./node_modules/vitest/vitest.mjs run src/components/screens/achievements
```
Expected: FAIL — no export `barHeights`.

- [ ] **Step 3: Implement `ActivityTab.tsx`**

```tsx
export function barHeights(values: number[], max: number, chartH: number): number[] {
  if (!max) return values.map(() => 4);
  return values.map((v) => Math.max(4, Math.round((v / max) * chartH)));
}
```

The component fetches `fetchActivity(userId)`, renders the four stat tiles from `data.tiles`, the weekly bar chart (7 bars, `barHeights(week.map(d => d.xp), Math.max(...xps, daily_goal_xp) * 1.15, 140)`, with a dashed goal line positioned at the same scale), and the 8-week trend using the same helper at `chartH = 100`. Today's bar uses `var(--accent)`; days that met the goal use a mid green; the rest use `var(--bg-soft)`.

- [ ] **Step 4: Implement `LeaderboardTab.tsx`**

Segmented pills for `everyone | friends | school` driving `fetchLeaderboard`. Podium renders `rows[1], rows[0], rows[2]` (skip cleanly when fewer than three rows exist — render only the rows present). Ranked list below shows rank, avatar initials, name, a `YOU` chip when `is_you`, streak, stage, and `week_xp`. The reset timer is derived from `resets_at`. Empty state: "No XP earned in this group yet this week."

- [ ] **Step 5: Wire both into the tab shell**

In `Achievements.tsx`, render `{tab === "leaderboard" && <LeaderboardTab userId={userId} />}` and `{tab === "activity" && <ActivityTab userId={userId} />}`.

- [ ] **Step 6: Test, typecheck, lint, commit**

Run from `frontend/`:
```
fnm exec --using=v22.23.1 -- node ./node_modules/vitest/vitest.mjs run
fnm exec --using=v22.23.1 -- node ./node_modules/typescript/bin/tsc --noEmit
fnm exec --using=v22.23.1 -- node ./node_modules/eslint/bin/eslint.js src/components/screens/achievements
```

```bash
git add frontend/src/components/screens/achievements frontend/src/components/screens/Achievements.tsx
git commit -m "feat(frontend): leaderboard and activity tabs"
```

---

### Task 15: Admin achievement wiki

**Files:**
- Create: `frontend/src/components/screens/admin/AchievementWiki.tsx`
- Modify: `frontend/src/components/screens/Admin.tsx`

**Interfaces:**
- Consumes: `BadgeArt` (Task 11); `adminListAchievements`, `adminUpdateAchievement`, `adminUploadAchievementIcon`, `adminListXpRules`, `adminUpdateXpRule`, plus the existing trigger and grant functions (Task 12).
- Produces: `<AchievementWiki />` — drops into the existing `achievements` tab.

This replaces the current `AchievementsTab` in place. `Admin.tsx` is already 1,485 lines, so the wiki lives in its own file rather than growing it.

- [ ] **Step 1: Build the wiki component**

Structure:

1. **Header** — the catalog count split as `N live · M work in progress`, plus filter controls: category (`all` + the four), rarity (`all` + the five), and a text search over name/slug/description.
2. **Work in progress section** — rendered first, above the live catalog, listing every `status === "draft"` achievement. This is where the ten pre-existing badges (First Steps, Week Warrior, Monthly Master, Document Collector, Library Builder, Quiz Enthusiast, Flashcard Fanatic, Social Butterfly, Conversation Starter, Early Adopter) land after migration 0044. Each row carries the same editing affordances as a live card plus a **Publish** button calling `adminUpdateAchievement(id, { status: "live" })`. Give the section a short explanatory line: *"Drafts are visible only here — users never see them and their triggers never fire."* Collapse the section entirely when there are no drafts.
3. **Live catalog grid** — `repeat(auto-fill, minmax(340px, 1fr))`. Each card carries a live `<BadgeArt slug={a.slug} rarity={a.rarity} locked={false} iconUrl={a.icon_url} emoji={a.icon} size={64} />`, so an admin sees exactly what users will. Each has an **Unpublish** action calling `adminUpdateAchievement(id, { status: "draft" })`, behind `useConfirm` since it removes a badge from every user's view.
4. **Inline edit** — clicking a card expands it into fields for name, description (textarea), category (`CustomSelect`), rarity (`CustomSelect`), XP reward (number), sort order (number), and the secret toggle. A single Save calls `adminUpdateAchievement` with only the changed keys.
5. **Icon drop zone** — validates before upload so the common mistake gets an instant, specific error:

```tsx
const ICON_PX = 512;
const MAX_ICON_BYTES = 512 * 1024;

async function readIcon(file: File): Promise<{ base64: string; contentType: string }> {
  if (!["image/png", "image/webp", "image/svg+xml"].includes(file.type)) {
    throw new Error("Icon must be a PNG, WebP or SVG");
  }
  if (file.size > MAX_ICON_BYTES) {
    throw new Error(`Icon must be 512 KB or smaller (this one is ${Math.round(file.size / 1024)} KB)`);
  }
  if (file.type !== "image/svg+xml") {
    const bitmap = await createImageBitmap(file);
    const { width, height } = bitmap;
    bitmap.close();
    if (width !== ICON_PX || height !== ICON_PX) {
      throw new Error(`Icon must be exactly ${ICON_PX}×${ICON_PX} (this one is ${width}×${height})`);
    }
  }
  const buffer = await file.arrayBuffer();
  const bytes = new Uint8Array(buffer);
  let binary = "";
  for (let i = 0; i < bytes.length; i += 1) binary += String.fromCharCode(bytes[i]);
  return { base64: btoa(binary), contentType: file.type };
}
```

On success, call `adminUploadAchievementIcon` and patch `icon_url` into local state so the preview updates without a refetch.

6. **Triggers** — the existing trigger list/create/update/delete controls, moved over unchanged from `AchievementsTab`.
7. **Grant to user** — the existing `adminGrantAchievement` control, moved over unchanged.
8. **XP rules panel** — a table below the grid: label, editable amount, enabled toggle. Each change calls `adminUpdateXpRule` and shows a toast.

Use the existing `useToast` for every success and error, matching the rest of `Admin.tsx`.

- [ ] **Step 2: Swap it into `Admin.tsx`**

Replace the `AchievementsTab` component definition with an import, and update the render line at `Admin.tsx:91`:

```tsx
import { AchievementWiki } from "./admin/AchievementWiki";
...
        {tab === "achievements" && <AchievementWiki />}
```

Delete the now-unused `AchievementsTab` body and any imports it alone used.

- [ ] **Step 3: Typecheck, lint, test**

Run from `frontend/`:
```
fnm exec --using=v22.23.1 -- node ./node_modules/typescript/bin/tsc --noEmit
fnm exec --using=v22.23.1 -- node ./node_modules/eslint/bin/eslint.js src/components/screens
fnm exec --using=v22.23.1 -- node ./node_modules/vitest/vitest.mjs run
```
Expected: clean; no unused-import warnings from the deleted tab.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/screens/admin frontend/src/components/screens/Admin.tsx
git commit -m "feat(admin): achievement wiki with icon upload and XP rules"
```

---

### Task 16: Friends UI

**Files:**
- Modify: `frontend/src/components/screens/Social.tsx`, `frontend/src/components/ProfileView.tsx`

**Interfaces:**
- Consumes: `fetchFriends`, `fetchFriendRequests`, `sendFriendRequest`, `acceptFriendRequest`, `declineFriendRequest`, `removeFriend` (Task 12).

- [ ] **Step 1: Add a Friends section to `Social.tsx`**

Above the existing rooms list, add a "Friends" panel:
- the friends list, each row showing avatar, name, `Lv {level}`, `{total_xp} XP`, and a Remove action behind `useConfirm`
- an "Incoming requests" list with Accept / Decline buttons, shown only when non-empty, with a count chip
- an "Outgoing" list showing pending requests, shown only when non-empty

Refetch both lists after every mutation.

- [ ] **Step 2: Add the request action to `ProfileView.tsx`**

On another user's profile, render an "Add friend" button when they are not already a friend and no request is pending. On click, call `sendFriendRequest(viewerId, profileUserId)` and switch the button to a disabled "Request sent". Handle the 409 by showing the existing toast with the server's detail.

- [ ] **Step 3: Typecheck, lint, test**

Run from `frontend/`:
```
fnm exec --using=v22.23.1 -- node ./node_modules/typescript/bin/tsc --noEmit
fnm exec --using=v22.23.1 -- node ./node_modules/eslint/bin/eslint.js src/components
fnm exec --using=v22.23.1 -- node ./node_modules/vitest/vitest.mjs run
```

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/screens/Social.tsx frontend/src/components/ProfileView.tsx
git commit -m "feat(social): friends list, requests and add-friend action"
```

---

### Task 17: E2E journey and full verification

**Files:**
- Create: `frontend/e2e/gamification.spec.ts`
- Modify: `docs/frontend-testids.md`

**Interfaces:**
- Consumes: everything above.

- [ ] **Step 1: Add testids**

Add `data-testid` to the surfaces the journey drives: `gamification-hero`, `gamification-level`, `gamification-total-xp`, `achievements-tab-leaderboard`, `leaderboard-row-you`, `achievements-tab-activity`, `activity-week-total`. Record each in `docs/frontend-testids.md` per its "Adding a surface" section.

- [ ] **Step 2: Write the journey**

```ts
import { test, expect } from "./support/fixtures";

test("earning XP moves the hero card and the leaderboard", async ({ page, db, user }) => {
  await page.goto("/achievements");
  await expect(page.getByTestId("gamification-hero")).toBeVisible();
  const before = Number(await page.getByTestId("gamification-total-xp").innerText());

  await db.awardXp(user.id, "quiz_completed", "quiz", "e2e-quiz-1");
  await page.reload();

  await expect
    .poll(async () => Number(await page.getByTestId("gamification-total-xp").innerText()))
    .toBeGreaterThan(before);

  await page.getByTestId("achievements-tab-leaderboard").click();
  await expect(page.getByTestId("leaderboard-row-you")).toBeVisible();

  await page.getByTestId("achievements-tab-activity").click();
  await expect(page.getByTestId("activity-week-total")).not.toHaveText("0");
});
```

Add `awardXp` to `frontend/e2e/support/db.ts`, inserting an `xp_events` row and refreshing `users.total_xp` / `users.level` the same way `xp_service` does.

- [ ] **Step 3: Run the full verification**

The local E2E stack is a machine singleton — wrap the whole up→test→down cycle in ONE `flock` call:

```bash
flock /tmp/claude-$(id -u)/sapling-e2e-stack.lock -c '
  make e2e-up &&
  (cd frontend && npx playwright test e2e/gamification.spec.ts) &&
  (cd backend && venv/bin/python -m e2e_oracles);
  make e2e-down'
```
Expected: Playwright green, oracles exit 0.

- [ ] **Step 4: Run everything one more time**

```bash
cd backend && python -m pytest tests/ -q && ruff check .
cd ../frontend && fnm exec --using=v22.23.1 -- node ./node_modules/vitest/vitest.mjs run
fnm exec --using=v22.23.1 -- node ./node_modules/typescript/bin/tsc --noEmit
fnm exec --using=v22.23.1 -- node ./node_modules/eslint/bin/eslint.js .
```
Expected: all green. Paste the actual output into the PR — do not claim success without it.

- [ ] **Step 5: Commit and mark the PR ready**

```bash
git add frontend/e2e docs/frontend-testids.md
git commit -m "test(e2e): XP earn to hero card and leaderboard journey"
git push
gh pr ready 505
```

---

## Notes for the implementer

- **Task order matters.** Tasks 1–2 (schema) gate everything; Task 3 gates 4; Task 4 gates 5, 6 and 8. Tasks 11–16 (frontend) all need Task 12's API client, which needs Task 8's endpoints.
- **Task 7 (friends) is independently shippable.** If this PR needs to be split, that is the clean seam.
- **Task 6b is not optional.** Without `touch_streak`, `streak_count` stays at 0 forever and four of the thirty achievements can never fire.
- **`status` gates every user-facing read.** Grep for `table("achievements")` before shipping and confirm each user-facing call site filters `status=eq.live`; admin call sites deliberately do not.
- **Do not invent XP numbers.** Every amount, threshold and stage name is in the spec's tables or in Task 2's migration.
- **`check_achievements` changed its return type** in Task 6 from `list[str]` to `list[dict]`. Grep for every call site before assuming a caller is unaffected.

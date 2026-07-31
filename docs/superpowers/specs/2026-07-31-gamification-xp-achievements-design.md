# Gamification: XP, levels, achievements, leaderboards

**Date:** 2026-07-31
**Branch:** `feat/gamification-xp-achievements`
**Source design:** Claude Design project `3aab5746-8bd8-4649-88f3-7d0901d9272a`, file `Achievements.dc.html`

## Goal

Turn the half-built achievements feature into a complete growth system: an XP
ledger, levels mapped to the eleven Sapling growth stages, three leaderboards, an
activity dashboard, and an admin wiki that makes the whole catalog editable —
descriptions, icons, rarity, XP rewards — without a deploy.

## What already exists

The repo is further along than the design assumes. Migration `0007_achievements.sql`
already ships `achievements`, `achievement_triggers`, `user_achievements` and
`achievement_cosmetics`, seeded with ten achievements.
`services/achievement_service.py` evaluates threshold triggers and grants badges.
`routes/admin.py` has full achievement/trigger/cosmetic CRUD behind `require_admin`,
surfaced by an `AchievementsTab` in `Admin.tsx`. `Achievements.tsx` renders earned
and locked badges with a five-slot profile showcase, and `AchievementUnlockToast.tsx`
handles unlock notifications. `users.streak_count` and `users.last_active_date`
already track streaks.

Nothing about XP, levels, growth stages, leaderboards or activity history exists.
`achievements.icon` is a text column holding an emoji — there is no image upload.

## Contradictions in the source design, and how they are resolved

The design file is internally inconsistent in three places. Each is resolved here
so implementation has a single answer.

**Growth-stage thresholds.** `STAGE_MIN` in the hero card uses `1, 5, 10, 15, 20,
25, 30, 35, 40, 45, 50`, while `stageFor()` in the leaderboard uses `3, 6, 10, 15,
21, 28, 36` and a shorter stage list. Resolution: `STAGE_MIN` is canonical, stored
in a `growth_stages` table, and both surfaces read from it.

**The XP curve.** The mock shows a level-12 user with 8,420 total XP and 600 XP to
level 13. No curve produces that: 8,000 XP across eleven levels averages 727 per
level, so a 600-XP level 12 would mean levels getting *cheaper* as you climb. The
per-user numbers are illustrative. The *stage sheet*, however, is coherent and is
adopted as the curve.

| Stage | Levels | XP to complete | XP per level |
|---|---|---|---|
| Bare Soil | 1–5 | 200 | 50 |
| Fallow Soil | 5–10 | 300 | 60 |
| Seed | 10–15 | 500 | 100 |
| Sprout | 15–20 | 800 | 160 |
| Seedling | 20–25 | 1,200 | 240 |
| Sapling | 25–30 | 2,000 | 400 |
| Young Tree | 30–35 | 3,200 | 640 |
| Branching Out | 35–40 | 4,800 | 960 |
| In Bloom | 40–45 | 7,000 | 1,400 |
| Fruit-Bearing | 45–50 | 10,000 | 2,000 |
| Old Growth | 50+ | — | terminal |

Reaching level 50 costs **29,800 XP**. `xp_for_level(n)` is the containing band's
`xp_to_complete / 5`; Bare Soil spans four levels and is treated as `200 / 4`.

**Streak freezes.** The stat row renders "23 days · 2 freezes", but no freeze
mechanic exists anywhere in the design — nothing earns or spends them. Cut from
v1; the tile reads "Study streak · longest N days" instead.

## Data model

One migration, `0043_gamification.sql`.

### New tables

`xp_events` — the append-only ledger everything else derives from.

```
id               uuid pk
user_id          text not null references users(id) on delete cascade
rule_key         text not null
amount           int not null
source_type      text            -- 'session' | 'quiz' | 'document' | 'note' | 'flashcards' | 'achievement' | 'goal'
source_id        text
idempotency_key  text not null unique
created_at       timestamptz not null default now()
```

The unique `idempotency_key` is load-bearing: a retried quiz submit or a
double-fired background task must not pay out twice. Callers build it as
`f"{rule_key}:{source_type}:{source_id}"`. Indexed on `(user_id, created_at)`
for the weekly and daily rollups.

`xp_rules` — `key` (pk), `label`, `amount`, `enabled`, `updated_at`. Admin-editable.

Seeded defaults:

| key | label | amount |
|---|---|---|
| `session_completed` | Completed a study session | 25 |
| `quiz_completed` | Completed a quiz | 30 |
| `flashcards_reviewed_10` | Reviewed 10 flashcards | 5 |
| `document_uploaded` | Uploaded a document | 15 |
| `note_created` | Created a note | 10 |
| `daily_goal_met` | Hit the daily XP goal | 20 |

Achievement unlocks are deliberately *not* a rule — the amount comes from that
badge's own `xp_reward`, passed explicitly by the grant path.

`growth_stages` — `slug` (pk), `name`, `blurb`, `min_level`, `xp_to_complete`,
`sort_order`. Seeded from the table above. Single source of truth for level maths.

`friendships` — `user_id`, `friend_id`, `created_at`, primary key `(user_id, friend_id)`.
Rows are written symmetrically (both directions) on accept, so "my friends" is a
plain `where user_id = ?` with no `OR`.

`friend_requests` — `id`, `from_user_id`, `to_user_id`, `status`
(`pending`/`accepted`/`declined`), `created_at`, `responded_at`, unique
`(from_user_id, to_user_id)`.

### Altered tables

`users` gains `total_xp int default 0`, `level int default 1`,
`daily_goal_xp int default 50`, `longest_streak int default 0` — alongside the
existing `streak_count`. `total_xp` and `level` are caches maintained by the award
path, always recomputable from `xp_events`.

`achievements` gains `xp_reward int default 0`, `icon_url text`, `sort_order int
default 0`, and `status text default 'live' check (status in ('draft','live'))`.

**`status` is what makes the wiki an authoring tool rather than a viewer.** A
`draft` achievement is fully visible and editable in the admin console but is
never served to users, never evaluated by the trigger checker, and never counted
in "N of M badges". That lets a badge be designed, described, given an icon and a
rarity, and sat on until its trigger actually works.

## Catalog migration

The design's 30 achievements are inserted as `live`. The 10 already in the
database keep their slugs, their triggers and their earned rows, and are flipped
to `draft` — they become the wiki's work-in-progress list.

Nothing is deleted and nothing is remapped. That means no `user_achievements` row
is ever cascaded away, and the two prod users holding `first_login`,
`documents_5` and `documents_25` keep what they earned. It also means concepts
overlap across the two sets — `Week Warrior` (draft) and `On Fire` (live) both
describe a 7-day streak — which is harmless precisely because drafts are invisible
to users. Resolving those overlaps is an editorial decision for the wiki, not a
migration.

The resulting catalog is 40 rows: 30 live, 10 draft.

| | count | user-visible | trigger-evaluated |
|---|---|---|---|
| design catalog (`live`) | 30 | yes | yes |
| pre-existing (`draft`) | 10 | no | no |

**Every user-facing read filters on `status = 'live'`** — `GET /api/profile/{id}/achievements`,
the badge counts in `GET /api/gamification/me`, and `check_achievements`. A draft's
already-earned rows stay in the table but do not surface until it is published.

Full catalog with categories, rarities, XP rewards and triggers is in
[Appendix A](#appendix-a--achievement-catalog).

## Trigger coverage

`achievement_service._get_user_stat` grows the new trigger types. Every one below is
computable from existing tables except where noted.

| trigger | source |
|---|---|
| `login_streak` | `users.streak_count` (exists) |
| `session_count` | count `sessions` |
| `documents_uploaded`, `quizzes_completed`, `rooms_joined`, `post_count` | existing counts |
| `flashcards_reviewed` | `sum(flashcards.times_reviewed)` |
| `session_before_hour` / `session_after_midnight` | `sessions.ended_at` hour, UTC |
| `session_minutes` | `max(ended_at - started_at)` |
| `friends_count` | count `friendships` |
| `owned_room_members` | `rooms.created_by` joined to `room_members` |
| `rooms_active` | distinct `room_messages.room_id` |
| `room_replies` | messages in rooms the user did not create |
| `concepts_mastered` | `graph_nodes` where `mastery_tier = 'mastered'` |
| `courses_with_mastery` | distinct `course_id` of those nodes |
| `graph_nodes_count` | count `graph_nodes` |
| `level` | `users.level` |
| `xp_in_day` | max daily `sum(xp_events.amount)` |
| `goal_streak` | consecutive days where daily XP ≥ `daily_goal_xp` |
| `course_grade_a` | `gradebook_service` letter grade |

**Deferred to a follow-up**, granted manually meanwhile: `mentor` (finishing first
on a room's weekly leaderboard needs a weekly rollup job) and `comeback` (rebuilding
a streak after a lapse needs streak history the schema doesn't keep). Both are
seeded on `manual_admin_grant` with a note in the wiki, so the badges exist and are
grantable rather than silently dead.

## Backend

**`services/xp_service.py`** — the single award path.

```
award_xp(user_id, rule_key, *, source_type, source_id) -> XpAward
```

Reads the rule (skipping disabled ones), inserts the ledger row, swallows the
unique-violation on a duplicate `idempotency_key` and returns a no-op award,
recomputes `total_xp` and `level` off `growth_stages`, and reports any level-up
so the caller can surface it. `level_for_xp` / `xp_for_level` / `stage_for_level`
are pure functions over the seeded bands, cached with `lru_cache` and a
`clear_growth_cache()` hook the admin mutator calls — matching the project's
`lru_cache` convention (#98).

Award calls are wired into the existing quiz-score, session-end, document-upload
and note-create paths as post-commit background work: XP must never fail the
request that earned it.

**`services/achievement_service.py`** — `check_achievements` also awards the
badge's `xp_reward` through `xp_service`, and returns XP alongside the slug so the
unlock toast can show "+120 XP".

**`routes/gamification.py`**, mounted at `/api/gamification`:

- `GET /me` — level, stage, total XP, XP into level, XP for level, streak, longest streak, daily goal, today's XP, badge counts.
- `GET /leaderboard?scope=everyone|friends|school&window=weekly` — ranked rows plus the caller's own rank.
- `GET /activity` — last 7 days of daily XP and 8 weeks of weekly totals, plus the four summary tiles.

All three are conditional GETs via `services/http_cache.py` with
`Cache-Control: private` — these carry user-scoped, app-decrypted display names and
must never reach a shared cache (#99). Names resolve through
`services/profiles.py::get_display_names`.

**Leaderboard privacy.** Users with `profile_visibility = 'private'` are excluded
from `everyone` and `school` but always see their own row and rank. `friends` is
unaffected — it is opt-in by construction. The `school` scope resolves peers
through `services/academics.py::school_peer_user_ids`, the same fail-closed
resolver `GET /api/social/students` uses (#342) — `school` is not a column on
`user_profiles` after the 0024 identity split, and must not be reintroduced as one.

**Streak maintenance.** `users.streak_count` is currently only initialised, never
advanced, and `longest_streak` is new. `services/streak_service.py` gains a
`touch_streak(user_id)` called from the same post-commit hook as `award_xp`: it
advances `streak_count` when the last active date was yesterday, resets it to 1
on a gap, leaves it alone on a same-day repeat, and raises `longest_streak` to
match whenever the current streak exceeds it. Without this the hero card's streak
tile and four streak achievements would read zero forever.

**`routes/social.py`** gains the friends surface: `POST /friends/request`,
`POST /friends/requests/{id}/accept`, `POST /friends/requests/{id}/decline`,
`DELETE /friends/{friend_id}`, `GET /friends/{user_id}`, `GET /friends/requests`.
Accept writes both `friendships` rows in one call and fires a `friends_count`
achievement check for both users. Requests are scoped to users discoverable through
the existing school directory.

**`routes/admin.py`** gains `POST /achievements/{id}/icon` and
`GET|PATCH /xp-rules`. Every write keeps using the existing audit-log helper.

## Icon upload

`services/storage_service.py` gains `upload_achievement_icon(achievement_id, file_bytes,
content_type)`, mirroring the existing `upload_cosmetic_asset`. Validation, server
side so a hand-rolled request cannot bypass it:

- content type in `image/png`, `image/webp`, `image/svg+xml`
- ≤ 512 KB
- raster must be exactly **512×512**, parsed from the PNG/WebP header rather than
  trusting the client
- SVG must carry a square `viewBox`

512 was chosen to render crisply in the 130 px unlock modal at 2× DPI while
downscaling cleanly to the 52 px card. The admin UI validates dimensions client-side
before upload so the common mistake gets an instant, specific error.

Rendering precedence: `icon_url` if set → built-in SVG icon path for that slug →
the `icon` emoji → a default star.

## Frontend

**`Achievements.tsx`** grows three tabs matching the design:

- *Achievements* — hero growth card (level ring, stage medallion, XP progress), the three-up stat row (streak, daily goal ring, badges earned), category pills, badge grid grouped by category, and the unlock modal with its leaf burst. The existing five-slot showcase is preserved.
- *Leaderboard* — podium for the top three, ranked rows below, three scope pills, reset timer.
- *Activity* — four stat tiles, the weekly XP bar chart with its goal line, and the 8-week trend.

**Artwork.** The design carries a ~500-line procedural tree engine. The eleven
growth-stage medallions are fully deterministic — no per-user variation — so they
are **pre-rendered once into committed static SVGs** under
`frontend/public/growth/` and the generator is not shipped to the browser. Badge
discs cannot be static, because admins now upload custom icons, so the small
`disc(rarity, locked)` palette/gradient function and the built-in icon paths are
ported into `frontend/src/components/growth/BadgeArt.tsx`, which composites an
uploaded `icon_url` over the disc when one is present.

**Social** gains a friends list, incoming/outgoing request handling, and an
"Add friend" action on profile pages.

## The admin wiki

This lives **inside the existing admin console**, in the `achievements` tab already
declared in `Admin.tsx` (`type Tab = "users" | "allowlist" | "roles" | "achievements"
| "cosmetics" | "analytics" | "audit"`). No new route, no new page, no new nav entry
— the current `AchievementsTab` is replaced in place.

The tab holds, in one scrollable view:

- a **Work in progress** section at the top, listing every `draft` achievement with a "Publish" action that flips it to `live`
- the live catalog below it, with an "Unpublish" action that moves a badge back to draft
- every achievement as a card with a live badge preview rendered by the same `BadgeArt` component users see
- inline editing of name, description, category, rarity, XP reward, sort order and secret flag
- drag-and-drop icon upload with client-side dimension validation and instant preview
- the existing trigger editor (type + threshold) per achievement
- a "grant to user" control, already backed by `POST /admin/achievements/grant`
- an **XP rules** panel listing each rule with an editable amount and an enable toggle
- filters by category, rarity and earned-count, so the catalog stays navigable at 30 badges

All writes go through the existing admin endpoints and land in the audit log.

## Testing

**pytest** — `xp_service` idempotency (same key twice = one row, one payout), level
boundaries at each band edge, `level_for_xp` round-tripping against `xp_for_level`,
disabled rules paying zero; leaderboard scoping including the `private` exclusion and
self-rank; each new trigger type against fixture data; the icon validator rejecting
non-square, oversized and wrong-type uploads; the friends accept path writing both
rows and firing both checks.

**Vitest** — level/stage maths mirrored on the client, `BadgeArt` precedence
(`icon_url` → built-in → emoji → default), and the activity chart's bucketing.

**E2E** — a promoted Playwright journey covering earn XP → see it on the hero card →
appear on the leaderboard, per the project's E2E convention.

## Out of scope

Streak freezes, the `mentor` and `comeback` auto-triggers, cosmetic rewards beyond
the existing link table, seasonal or time-limited events, and XP decay.

## Appendix A — achievement catalog

| slug | cat | rarity | XP | trigger | threshold |
|---|---|---|---|---|---|
| `first-steps` | activity | common | 20 | `session_count` | 1 |
| `flash` | activity | common | 30 | `flashcards_reviewed` | 100 |
| `early-bird` | activity | uncommon | 60 | `session_before_hour` | 7 |
| `night-owl` | activity | uncommon | 60 | `session_after_midnight` | 1 |
| `on-fire` | activity | rare | 120 | `login_streak` | 7 |
| `deep-focus` | activity | rare | 120 | `session_minutes` | 120 |
| `quiz-master` | activity | epic | 250 | `quizzes_completed` | 100 |
| `marathon` | activity | epic | 300 | `login_streak` | 30 |
| `wildfire` | activity | legendary | 400 | `login_streak` | 60 |
| `first-friend` | social | common | 20 | `friends_count` | 1 |
| `study-circle` | social | uncommon | 60 | `rooms_joined` | 1 |
| `helping-hand` | social | uncommon | 70 | `room_replies` | 1 |
| `room-leader` | social | rare | 150 | `owned_room_members` | 5 |
| `popular` | social | rare | 150 | `friends_count` | 10 |
| `social-butterfly` | social | epic | 250 | `rooms_active` | 5 |
| `mentor` | social | epic | 280 | `manual_admin_grant` | 1 |
| `sprout` | milestone | common | 25 | `level` | 15 |
| `rooted` | milestone | uncommon | 80 | `concepts_mastered` | 10 |
| `grade-a` | milestone | uncommon | 100 | `course_grade_a` | 1 |
| `branching` | milestone | rare | 180 | `concepts_mastered` | 50 |
| `rings` | milestone | rare | 180 | `level` | 15 |
| `canopy` | milestone | epic | 280 | `concepts_mastered` | 100 |
| `web` | milestone | epic | 300 | `graph_nodes_count` | 200 |
| `old-growth` | milestone | legendary | 500 | `level` | 50 |
| `golden-hour` | special | rare | 150 | `xp_in_day` | 500 |
| `comeback` | special | rare | 150 | `manual_admin_grant` | 1 |
| `perfect-week` | special | epic | 200 | `goal_streak` | 7 |
| `secret` | special | epic | 250 | `manual_admin_grant` | 1 |
| `methuselah` | special | legendary | 300 | `manual_admin_grant` | 1 |
| `polymath` | special | legendary | 500 | `courses_with_mastery` | 5 |

Thirty badges: nine activity, seven social, eight milestone, six special. `secret`
is the only one seeded with `is_secret = true`; it renders as "???" until earned.

# Feature · Achievements

> Covers: `/achievements/page.tsx`, `AchievementCard.tsx`, `AchievementShowcase.tsx`, `AchievementUnlockToast.tsx`. **Orphaned route** — no in-app Link navigates here (see Phase 2 §4).

---

## 1. Overview

A simple gallery page listing the user's earned + available achievements, grouped by category. Categories: `activity` / `social` / `milestone` / `special`. Pill filter for "all" + each category.

Each achievement card (`AchievementCard.tsx`) shows:
- Icon (or SVG fallback, or secret-indicator `?` for locked secret achievements)
- Name + description (suppressed for secret+locked achievements)
- Rarity label (common / uncommon / rare / epic / legendary) with matching border/background colors driven by CSS custom properties (`--rarity-*`)
- Progress bar (locked, non-compact, progress>0)
- Earned date (earned)

`AchievementShowcase` is a 5-slot "featured" strip rendered on public profiles / the settings preview. Shows up to 5 compact `AchievementCard`s; remaining slots are dashed placeholders. Has "Edit showcase" button when `isOwnProfile`.

`AchievementUnlockToast` is defined but **currently unused** (no importers). Looks like a prepared UI for live unlock feedback via `useToast(<AchievementUnlockToast achievement=... />)` — dead code until wired.

---

## 2. User flows

### 2.1 Flow: browse (`/achievements`)

1. Mount: `fetchAchievements(userId)` → `{earned, available}`.
2. Filter pills set `filter: AchievementCategory | 'all'`.
3. Earned section renders first (`AchievementCard earned`); Available section below (`AchievementCard earned={false}`).
4. Click a card: `setExpandedId(id)` — but the expand action doesn't appear to show any extra content beyond the card (verify in Phase 4).

### 2.2 Flow: showcase on settings / profile

- `AchievementShowcase` takes the top 5 earned achievements, renders compact cards, and a "Edit showcase" button for the owner.
- Clicking the button opens a picker (in `/settings`) that lets the user reorder/pick which 5 appear.
- `setFeaturedAchievements(userId, ids[])` persists the selection.

### 2.3 Flow: achievement unlock (hypothetical — not wired)

`AchievementUnlockToast` exists as a component and the `useToast()` hook supports arbitrary content. But there's no code that fires this on unlock. Backend probably grants achievements server-side (see `CLAUDE.md` — `achievement_service.py`); the frontend would need a realtime channel or a post-action refetch to detect new unlocks and trigger the toast. Not implemented.

---

## 3. State

`/achievements` page:
- `earned`, `available`, `loading`, `error`
- `filter`
- `expandedId`

`AchievementShowcase`:
- None — purely rendering props.

`AchievementCard`:
- None.

---

## 4. API calls

- `fetchAchievements(userId)` → `GET /api/profile/:userId/achievements` → `{earned, available}`

---

## 5. Components involved

| Component | Role |
|---|---|
| `AchievementCard` | Individual card, compact + full sizes |
| `AchievementShowcase` | 5-slot featured strip |
| `AchievementUnlockToast` | Toast body (**unused**) |

---

## 6. Edge cases

1. **Orphaned route.** `/achievements` isn't linked from the Navbar or anywhere else. Fix by linking from user-menu or `/settings`. (QUESTIONS Q9.)
2. **Unlock toast component exists but isn't triggered.** Wire it to `useToast()` on new-unlock detection in the rebuild.
3. **Secret achievements**: `isSecret && !earned` renders `Secret Achievement` + `?` icon + `Keep exploring to discover this achievement` description. After earning, the real name/description appear.
4. **Progress bars** only show for locked, non-compact, progress>0. Earned or compact cards skip them.
5. **Rarity CSS variables** live in `globals.css` (not audited yet) — the rebuild must preserve or re-derive these tokens: `--rarity-common/uncommon/rare/epic/legendary` and their `-bg` variants.

---

## 7. Interactive patterns

- Category pill filter.
- Compact vs full card variants.
- Dashed placeholder slots in the showcase.
- Rarity-colored border + glow via `boxShadow` referencing `--rarity-*-bg`.

---

## 8. Things to preserve in the rebuild

- Four categories + five rarities.
- Compact + full card sizes with consistent styling.
- 5-slot `AchievementShowcase` with editable ordering and featured-persist (`setFeaturedAchievements`).
- Secret-achievement scheme (hidden name/description until earned).
- Progress bars on locked achievements with progress>0.
- `AchievementUnlockToast` layout — wire it up on unlock detection.
- Rarity CSS variable system.

## 9. Things to rework

- Link `/achievements` from Navbar user-menu or `/settings`.
- Wire `AchievementUnlockToast` to fire on unlock (probably via a refetch-on-success pattern after the learn chat's `mastery_changes` event).
- The `expandedId` state in `/achievements/page.tsx` does not appear to alter rendering — likely unfinished. Remove or implement an expanded view.

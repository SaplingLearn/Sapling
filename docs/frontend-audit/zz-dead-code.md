# Sapling Frontend Audit — Dead Code & Unused Surfaces

> Files, components, props, and endpoints that have no importer / caller in the in-scope frontend. Flagged so the rebuild doesn't carry them forward.

Verification method: `Grep` for identifier across `src/`, excluding the definition site.

---

## 1. Components with no importer

### 1.1 `src/components/SpaceBackground.tsx`
- Default-exports a `SpaceBackground` function.
- **No importer** in `src/` (case-insensitive search).
- Likely an abandoned experiment for an animated starfield background (name implies canvas RAF visual).
- **Action**: delete unless product wants to reintroduce it.

### 1.2 `src/components/ProfileBanner.tsx`
- Default-exports a `ProfileBanner` function taking `{bannerUrl?}`.
- **No importer** in `src/`.
- Referenced conceptually by `CLAUDE.md` §Components as the banner for profile pages — but `/profile` does not exist and `/settings` profile preview renders its own default gradient inline.
- **Action**: delete, OR reintroduce as part of a new `/profile/[userId]` page (depends on QUESTIONS Q10 decision).

### 1.3 `src/components/UploadZone.tsx`
- Default-exports an `UploadZone` drag-and-drop file picker.
- **No importer** in `src/`.
- Superseded by `DocumentUploadModal`'s inline drop zone. `CLAUDE.md` still references `UploadZone.tsx` (stale).
- **Action**: delete.

### 1.4 `src/components/AchievementUnlockToast.tsx`
- Default-exports a toast body for achievement unlocks.
- **No importer** in `src/`.
- Looks prepared for `useToast(<AchievementUnlockToast achievement=... />)` on grant-detection. Not wired.
- **Action**: keep the component (it's correctly designed) and wire it to fire when a new achievement is detected after chat/quiz actions. Or delete if achievements are discovered passively via the `/achievements` page.

---

## 2. Exported but unused API helpers (`lib/api.ts`)

These are defined in `lib/api.ts` but nothing in `src/` calls them (except the definition site and tests if any).

- `fetchRoles(userId)` — `GET /api/profile/:userId/roles`. `UserContext` gets `roles` from `/api/auth/me` directly.
- `adminAssignRole` / `adminRevokeRole` — admin UI doesn't implement the picker.
- `exportToGoogleCalendar` — may be used by a multi-select Calendar flow; verify before deleting.
- `extractSyllabus` — the uploader goes through `/api/documents/upload` instead. May be legacy.
- `findSchoolMatches` — social page uses room-scoped `findStudyMatches`; school-wide matches don't have a UI yet.
- `checkCalendarStatus` — alias of `getCalendarStatus`.

**Action**: audit each against backend routes; remove if server endpoint is also unused, otherwise keep until the UI is completed.

---

## 3. Dead props

### 3.1 `AvatarFrame.frameSlug?: string`
- Defined in the Props interface (`src/components/AvatarFrame.tsx:8`) but never read.
- **Action**: remove.

### 3.2 `AchievementCard.onPress`
- Declared + wired to the outer div's `onClick`. Callers pass `undefined` — clicking does nothing.
- `/achievements` has `expandedId` state but the card doesn't actually change when expanded.
- **Action**: either implement the expanded view or remove the prop.

---

## 4. Dead state

### 4.1 `/achievements` `expandedId`
- State defined but does not modify rendering based on grep of the file.
- **Action**: remove or implement expanded state.

---

## 5. Stale CLAUDE.md entries

Not dead code, but stale references in the repo-root `CLAUDE.md`:

- `CLAUDE.md` lists `src/app/profile/page.tsx` — directory does not exist.
- `CLAUDE.md` references `UploadZone.tsx` as the upload component — actually `DocumentUploadModal.tsx` is used.
- `CLAUDE.md` "Architecture Notes" says "2-day cooldown" on navigate-away session feedback — code is 3 days.
- `CLAUDE.md` describes `backend/routes/learn.py` as "streaming AI tutoring chat endpoint (SSE)" — the frontend does not consume as a stream; either backend also stopped streaming, or the frontend never used the streaming capability.

**Action**: refresh `CLAUDE.md` to match reality post-rebuild.

---

## 6. Unused packages

### 6.1 `framer-motion`
- Installed at 12.38.0.
- Only imported in `src/components/HowItWorks.tsx` (landing page — out of scope).
- No in-scope feature uses it.
- **Action**: remove from `package.json` unless the rebuild plans to use it.

---

## 7. Summary for the rebuild

Safe to delete outright (in scope):
- `src/components/SpaceBackground.tsx`
- `src/components/ProfileBanner.tsx` (unless reintroducing `/profile`)
- `src/components/UploadZone.tsx`
- `AvatarFrame.frameSlug` prop
- `/achievements` `expandedId` state (if not implementing expansion)
- `framer-motion` dependency (if landing gets rebuilt without it)

Worth wiring, not deleting:
- `AchievementUnlockToast.tsx` — connect to unlock detection.

Backend-dependent:
- `fetchRoles`, `adminAssignRole`, `adminRevokeRole`, `findSchoolMatches`, `exportToGoogleCalendar`, `extractSyllabus`, `checkCalendarStatus` — verify against backend `routes/` before deleting the stubs.

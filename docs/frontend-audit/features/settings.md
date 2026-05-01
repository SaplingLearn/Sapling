# Feature · Settings

> Covers: `/settings/page.tsx` + `CosmeticsManager.tsx`. All account, profile, notification, appearance, privacy, cosmetics, and danger-zone controls. Also hosts the **Profile Preview modal**, which is the only place public-profile rendering happens (since `/profile` doesn't exist — see `QUESTIONS.md` Q10).

---

## 1. Overview

Settings is a two-column layout:

- **Left (sticky, 220px)**: grouped navigation — Identity (Profile, Account), Preferences (Notifications, Appearance, Privacy), Personalization (Cosmetics), Manage (Danger Zone).
- **Right**: one card per section based on `activeSection` state.

Each section renders a `SectionHeader` (title + description + optional action button, `danger` variant for red styling) followed by a card with rows of toggles, inputs, or other controls.

The **Profile Preview modal** opens from the Profile section's action button. It fetches `fetchPublicProfile(userId)` + `fetchAchievements(userId)` and renders the same view a visitor would see if `/profile/[id]` existed — useful for previewing cosmetics before equipping.

---

## 2. User flows

### 2.1 Flow: load settings

- Mount: `fetchSettings(userId)` → populates `settings`, `displayName`, `username`, `bio`, `location`, `website` (`page.tsx:121-135`).
- Loading state: "Loading settings..."

### 2.2 Flow: profile editing + live username availability

- Form fields: display name, username, bio, location, website.
- Username input calls `checkUsername(val)` (debounced 500ms):
  - Calls `updateProfile(userId, { username: val })`; success → `usernameAvailable = true`, failure → `false`.
  - **This mutates the live profile.** Username "check" is implemented as a real PATCH. If the user types several candidate usernames in a row, each one tries to set the username on the backend; whichever fires last "wins". This is non-idiomatic — the rebuild should separate availability check (`GET /api/profile/username-available?q=`) from save.
- "Save profile" button → `saveProfile()` → `updateProfile(userId, {display_name, username, bio, location, website})` + Toast.
- Avatar upload: hidden file input triggered by camera-icon button. `uploadAvatar(userId, file)` (multipart), Toast on success, then `refreshProfile()`.

### 2.3 Flow: appearance toggle (dark mode)

- `handleThemeToggle(theme)`:
  - `document.documentElement.classList.toggle('dark', theme === 'dark')` — applied immediately (optimistic).
  - `saveSettings({ theme })` persists.

Observation: there's no corresponding "respect system preference" tri-state — it's `light` or `dark`.

### 2.4 Flow: notifications / privacy toggles

- Each toggle is the inline `Toggle` component (`page.tsx:59-90`). Calls `saveSettings({ key: value })` with Toast feedback.

### 2.5 Flow: cosmetics (`CosmeticsManager`)

- Four tabs: **Avatar Frames / Banners / Name Colors / Titles**. Each tab shows a grid of owned cosmetics.
- Grid card: image preview, name, rarity label, "Equipped" indicator.
- Click a card: if not equipped, `equipCosmetic(userId, slot, cosmeticId)`; if equipped, re-click to unequip (passes `null`).
- On change, `refreshProfile()` updates `UserContext.equippedCosmetics` so Navbar avatar etc. update immediately.
- Preview card at bottom shows how the combined equipped cosmetics look (`AvatarFrame` + `NameColorRenderer` + `TitleFlair`).

Empty state per tab: "No {type} unlocked yet".

### 2.6 Flow: danger zone

- **Export data**: `exportData(userId)` → JSON blob → triggers download via anchor+click pattern with `URL.createObjectURL` / `revokeObjectURL` (`page.tsx:212-226`).
- **Delete account**: input field requiring literal "DELETE" text; button gated by `deleteConfirm === 'DELETE'`. `deleteAccount(userId, confirmation)` → Toast "Account scheduled for deletion". (Does not auto-sign-out; rebuild should.)

### 2.7 Flow: profile preview modal

- "Preview public profile" button → `openProfilePreview()`:
  - Parallel `fetchPublicProfile(userId)` + `fetchAchievements(userId)` (catch fallback to null).
  - Double-RAF pattern to let mount before animation (`profileModalMounted` then `profileModalVisible`).
- Modal renders: `ProfileBanner` (if bannerUrl — almost never set since `ProfileBanner.tsx` has no importers; see Q10) or default gradient, avatar + name + title + role, bio/location/website, featured achievements via `AchievementShowcase`.
- Close: `closeProfilePreview()` animates out, unmounts after 250ms.

### 2.8 Flow: featured role/achievements

- `setFeaturedRole(userId, roleId)` → shown next to name on public profile.
- `setFeaturedAchievements(userId, ids[])` → top-5 `AchievementShowcase` on public profile.
- UI for these is inside the Profile section or the Cosmetics/achievements sections — verify in a later pass.

---

## 3. State

Top-level:
- `activeSection`: SectionKey
- `settings`, `loading`
- Profile form: `displayName`, `username`, `bio`, `location`, `website`
- `usernameAvailable`, `checkingUsername`, `usernameTimerRef`
- Profile modal: `profileModalMounted`, `profileModalVisible`, `previewProfile`, `previewAchievements`, `previewLoading`
- Danger zone: `deleteConfirm`, `showDeleteForm`, `deleting`

`CosmeticsManager`:
- `activeTab`, `cosmetics`, `equipped`, `loading`, `error`, `equipping`

---

## 4. API calls

- `fetchSettings(userId)` → mount
- `updateSettings(userId, updates)` → toggle/save
- `updateProfile(userId, fields)` → profile save + username "check"
- `uploadAvatar(userId, file)` → avatar upload
- `fetchPublicProfile(userId)` → preview
- `fetchAchievements(userId)` → preview
- `fetchCosmetics(userId)` / `equipCosmetic(userId, slot, cosmeticId)`
- `setFeaturedRole` / `setFeaturedAchievements`
- `exportData(userId)` → JSON download
- `deleteAccount(userId, confirmation)`

---

## 5. Components involved

- `CosmeticsManager`, `AvatarFrame`, `NameColorRenderer`, `TitleFlair`, `RoleBadge`, `AchievementShowcase`
- Inline `Toggle`, `SectionHeader`
- `useToast` for feedback

---

## 6. Edge cases

1. **Username "check" mutates the server.** Anti-pattern — see §2.2. Fix in rebuild.
2. **Dark mode class is applied to `document.documentElement`** optimistically. If the `saveSettings` call fails, the class is still there (inconsistent with persisted state). Rebuild should revert on error.
3. **Profile Preview uses `fetchPublicProfile(userId)` for the current user** — same endpoint as a stranger would use, so the preview is accurate.
4. **Delete account doesn't sign out or redirect.** User is left on a settings page with an invalid session. Rebuild: immediately call `signOut()` and `router.replace('/signin')`.
5. **Data export is a direct download** — no server-side email, no manifest. Acceptable for small datasets.
6. **`ProfileBanner.tsx` is referenced here** but isn't imported — the preview panel inlines a default gradient instead. Flag for dead-code list.

---

## 7. Interactive patterns

- Sticky sidebar navigation with `position: sticky; top: 24px`.
- Pill-group navigation inside the sidebar (imports Lucide icons).
- Debounced username availability check.
- RAF-based modal mount/enter animation.
- Toast feedback for every mutation.
- Dark-mode class toggling on `document.documentElement`.

---

## 8. Things to preserve in the rebuild

- Sidebar nav with grouped sections (Identity / Preferences / Personalization / Manage).
- Profile Preview modal — critical UX for cosmetics.
- Toast feedback after every save.
- Three-step danger-zone delete (type "DELETE" → button enabled).
- JSON-blob data export.
- `equipCosmetic(slot, null)` to unequip by re-clicking.
- Dark-mode via `.dark` class on `<html>` (keep compatible with CSS variables in `globals.css`).

## 9. Things to rework

- Split username availability (GET) from save (PATCH).
- After account deletion, sign the user out and redirect.
- Revert dark-mode class on `saveSettings` error.
- Reintroduce a public `/profile/[userId]` page to match what the Preview modal shows.
- Settings page grows over time — consider a "search settings" affordance.

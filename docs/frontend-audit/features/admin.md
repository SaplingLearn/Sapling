# Feature · Admin

> Covers: `/admin/page.tsx` (269 lines). Admin-only panel for user approval, role management, achievement creation/granting, and cosmetic creation.

---

## 1. Overview

Four tabs, one admin-only page.

- Guard: middleware + client-side `isAdmin` check (`admin/page.tsx:46-58`). Non-admins `router.push('/dashboard')`; component returns `null` until navigation completes.
- Navbar user-menu only shows "Admin" link when `isAdmin` (`Navbar.tsx:374`).

Tabs:
1. **Users**: table with Name / Email / Status / Roles / Actions. Pending users get an "Approve" button.
2. **Roles**: create form (Name + Slug + Color picker). Role assignment to specific users happens elsewhere (probably per-user modal — not wired in current code beyond `adminAssignRole` API).
3. **Achievements**: create form (Name + Slug + Category + Rarity) + Grant form (User ID + Achievement ID).
4. **Cosmetics**: create form (Name + Slug + Type + Rarity).

All actions show a Toast on success / failure.

---

## 2. User flows

### 2.1 Flow: approve a user

1. Users tab. `adminFetchUsers()` on mount.
2. Click Approve → `adminApproveUser(uid)` → local `users` state updates `is_approved = true` + Toast "User approved".

### 2.2 Flow: create a role

- Name + Slug text inputs, native `type="color"` color picker.
- `handleCreateRole` → `adminCreateRole({name, slug, color})` → Toast "Role created". Form resets.

### 2.3 Flow: create achievement

- Name + Slug inputs + Category / Rarity native `<select>` elements (four categories × five rarities — see `features/achievements.md`).
- `handleCreateAchievement` → `adminCreateAchievement` → Toast.

### 2.4 Flow: grant achievement

- Two text inputs for user ID and achievement ID (raw UUIDs — no picker). `adminGrantAchievement(userId, achId)`. Toast.
- Clunky UX — rebuild should pick from a searchable list.

### 2.5 Flow: create cosmetic

- Same shape as achievement creation: Name/Slug + Type (avatar_frame/banner/name_color/title) + Rarity.
- No file-upload for cosmetic `asset_url`. The backend probably accepts asset URL as a separate field or via a later PATCH. (Current UI can't upload assets.)

---

## 3. State

- `isAdmin` from `UserContext`
- `users`, `loading`
- Role form: `roleName`, `roleSlug`, `roleColor`
- Achievement form: `achName`, `achSlug`, `achCategory`, `achRarity`
- Cosmetic form: `cosName`, `cosSlug`, `cosType`, `cosRarity`
- Grant form: `grantUserId`, `grantAchId`

---

## 4. API calls

- `adminFetchUsers()` → `GET /api/admin/users`
- `adminApproveUser(userId)` → `PATCH /api/admin/users/:userId/approve`
- `adminCreateRole({name, slug, color})` → `POST /api/admin/roles`
- `adminAssignRole(userId, roleId, grantedBy?)` → `POST /api/admin/roles/assign` **(defined in lib/api.ts but no UI wiring)**
- `adminRevokeRole(userId, roleId)` → `DELETE /api/admin/roles/revoke` **(defined but no UI)**
- `adminCreateAchievement(data)` → `POST /api/admin/achievements`
- `adminGrantAchievement(userId, achievementId)` → `POST /api/admin/achievements/grant`
- `adminCreateCosmetic(data)` → `POST /api/admin/cosmetics`

---

## 5. Components involved

- `RoleBadge` — rendered inline in the user list.

---

## 6. Edge cases

1. **No role assignment UI.** `adminAssignRole` and `adminRevokeRole` exist in `lib/api.ts` but nothing calls them. Roles can be created but not given to anyone via the current UI. Flag.
2. **Cosmetic / achievement creation has no asset-upload UI.** Assets (frame PNG, banner image, etc.) must be attached via the database or a separate tool. Big gap.
3. **User + achievement "ID" inputs are raw UUIDs.** No picker. Requires copy-pasting from another tab.
4. **No pagination on the users table.** Scales linearly to DOM size.
5. **No error-surface for some actions.** Most handlers catch + show Toast, but some edge errors (network offline etc.) are just swallowed.
6. **Client-side admin check** can be bypassed by a fast-networked attacker reading the page before redirect fires. Acceptable because backend must also gate admin endpoints — verified in `services/auth_guard.py` per `CLAUDE.md`.

---

## 7. Interactive patterns

- Native `<select>` for category/rarity/type (inconsistent with the rest of the app, which uses `CustomSelect`). Cheap but jarring.
- Native `<input type="color">` for role color. Same comment.
- Toast feedback via `useToast`.

---

## 8. Things to preserve in the rebuild

- All 4 tab surfaces exist and need to keep existing: Users, Roles, Achievements, Cosmetics.
- Client-side admin check + `router.push('/dashboard')` (defense in depth).
- Toast feedback on every action.

## 9. Things to rework

- Build role-assignment UI (per-user role picker with `adminAssignRole`/`adminRevokeRole`).
- Add asset upload for cosmetics (avatar frame PNGs, banner images).
- Replace raw-UUID grant form with a user + achievement picker.
- Paginate the users table.
- Use `CustomSelect` for consistency.
- Surface admin errors more prominently (error banner, not just Toast).

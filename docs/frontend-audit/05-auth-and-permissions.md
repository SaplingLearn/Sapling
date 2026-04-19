# Sapling Frontend Audit — 05 · Auth & Permissions

> Frontend-side auth gating, session mechanics, and role/approval visibility. Full flow documentation in `features/auth.md`.

---

## 1. Two-layer guard

### 1.1 Middleware (`src/middleware.ts`)

Runs on every request to a matched path (before any page code):

- Matches: `/signin`, `/dashboard/**`, `/learn/**`, `/study/**`, `/tree/**`, `/flashcards/**`, `/library/**`, `/calendar/**`, `/social/**`, `/settings/**`, `/achievements/**`, `/admin/**`.
- Bypass: `process.env.NEXT_PUBLIC_LOCAL_MODE === 'true'`.

Behavior per matched request:
1. **`/signin`**: if already signed in + approved → redirect `/dashboard`; if signed in + unapproved → `/pending`; if `?error=` present → render; otherwise redirect to `${NEXT_PUBLIC_API_URL}/api/auth/google`.
2. **Protected routes**: require valid HMAC `sapling_session` cookie **plus** live `GET /api/auth/me` returning `is_approved: true`. Unapproved → `/pending`; invalid/missing/timeout → Google OAuth redirect.

3-second `AbortController` timeout on the live `/api/auth/me` call. Timeout → fall back to Google OAuth redirect (fail-closed).

### 1.2 Client gating

- `UserContext.userReady` gates every per-user fetch in every page (`if (!userReady || !userId) return`).
- `UserContext.isAdmin` gates the Navbar "Admin" link (`Navbar.tsx:374`) and the `/admin` page's body (`admin/page.tsx:46-58` — redirects non-admins to `/dashboard`).
- No other role-based UI gating exists yet. `UserContext.roles` is populated from `/api/auth/me` but is only surfaced as `RoleBadge` decorations (Admin users table, profile preview).

---

## 2. Session cookie

| Field | Value |
|---|---|
| Name | `sapling_session` |
| HTTP-only | ✅ |
| SameSite | `lax` |
| Secure flag | not explicitly set — relies on `next start` running behind a TLS-terminating proxy in production. **Verify this.** |
| Max-Age | 30 days (`SESSION_MAX_AGE = 2_592_000`) |
| Signing | HMAC-SHA-256 via Web Crypto (`lib/sessionToken.ts`) |
| Payload | `{userId, exp}` base64url-encoded, then signed |

Secret: `SESSION_SECRET` env var. Must be ≥32 bytes (enforced in `lib/sessionToken.ts:5-8`). Shared with the backend so `/api/auth/session` can fast-path-verify tokens the backend issues.

---

## 3. Role model

From `UserContext`:

- `roles: UserRole[]` — all roles assigned to this user. Shape: `{id, name, color, icon?, description?}` plus an outer wrapper (`UserRole`) with assignment metadata (`granted_by`, `granted_at`).
- `isAdmin: boolean` — comes directly from `/api/auth/me.is_admin`.
- `featuredRole: Role | null` — the user's picked role to feature on their profile; comes from `equipped_cosmetics.featured_role`.

Admin privileges: UI only checks `isAdmin`. The four admin-tab endpoints (`/api/admin/**`) all require backend-enforced admin auth — see `backend/services/auth_guard.py`. The frontend does not know which individual admin actions a user can perform; it assumes admin = all admin actions. A multi-tier role system (moderator can approve users but not create roles, etc.) isn't currently expressed in the UI.

---

## 4. Approval gate

- All new users created with `is_approved = false` (backend default).
- Unapproved users can:
  - Sign in (cookie gets issued).
  - Visit `/pending`, `/signin/callback`, and any marketing page.
  - Visit `/profile` (doesn't exist), `/api/auth/session` (Next route handler).
- Unapproved users cannot reach any middleware-matched route — middleware redirects to `/pending`.
- Admins approve via `/admin` Users tab.
- No "you are now approved" notification surface. User must refresh/retry after an admin approves.

---

## 5. Environment variables referenced

| Var | Used by | Purpose |
|---|---|---|
| `NEXT_PUBLIC_API_URL` | middleware, UserContext, `lib/api.ts`, session route handler, landing page | Backend base URL |
| `BACKEND_URL` | `next.config.ts` only (rewrites `/api/*`) | Build-time rewrite target |
| `SESSION_SECRET` | `lib/sessionToken.ts`, `/api/auth/session` route | HMAC secret |
| `NEXT_PUBLIC_LOCAL_MODE` | middleware, UserContext, `lib/api.ts` | Offline dev bypass |
| `NEXT_PUBLIC_SUPABASE_URL` | `lib/supabase.ts` | Supabase project URL |
| `NEXT_PUBLIC_SUPABASE_ANON_KEY` | `lib/supabase.ts` | Supabase anon key |
| `STATIC_EXPORT` | `next.config.ts` only | Build-time toggle |

`NEXT_PUBLIC_*` vars are exposed to the browser; keep secrets out of them.

---

## 6. Where auth-derived state shows up in the UI

| Surface | Visibility rule |
|---|---|
| Navbar entire nav | Hidden on `publicPaths` + `/careers/*`. Redirect to `/` if `userReady && !isAuthenticated && !isPublic`. |
| Navbar "Admin" link in user menu | `isAdmin === true` |
| `/admin` page body | `isAdmin === true`; else `router.push('/dashboard')` |
| `RoleBadge` on `/admin` Users tab | Always rendered when roles array is populated |
| `RoleBadge` on profile preview | `featuredRole?` + additional roles if present |
| Session-dependent data fetches | `userReady && userId` |

---

## 7. Signed-out reachable paths

| Path | Notes |
|---|---|
| `/` | Landing (out of scope) |
| `/about`, `/privacy`, `/terms`, `/careers/**` | Marketing |
| `/signin` | Only renders UI when `?error=` is present; otherwise middleware redirects to OAuth |
| `/signin/callback` | OAuth return handler — validates params and sets cookie |
| `/pending` | Reachable but only useful to authenticated-but-unapproved users. A signed-out visitor sees it but "Sign out" does nothing productive. |
| `/profile` | Route does not exist. If reintroduced, decide on visibility. |

---

## 8. Known weak points (fix in rebuild)

- **Cookie `Secure` flag not explicitly set.** Confirm deployment does TLS termination; if not, set `secure: true` in the cookie options.
- **`/pending` is unguarded by middleware.** Unauthed visitors can see the waitlist UI. Not a vuln but bad UX. Consider redirecting unauth visitors to `/signin`.
- **Approval polling does not exist.** Users sit on `/pending` with no auto-refresh.
- **Username "availability check" via `PATCH /api/profile/:userId`** (see `features/settings.md`): in addition to being non-idiomatic, if a typed candidate username is valid it *sets* the user's username. Fix by splitting.
- **Session expiry is 30 days with no refresh.** On day 31, user gets silently bounced to Google OAuth on next protected navigation. Consider refreshing on every backend call or implementing a sliding window.
- **`signOut()` doesn't clear `sessionStorage.sapling_onboarding_pending`** (QUESTIONS Q11). Shared-browser hazard.
- **No CSRF considerations.** Relies on `sameSite=lax`. POST/DELETE to `/api/auth/session` requires the cookie; cross-site POST from third-party sites would fail due to SameSite. Explicit CSRF tokens are not used. Acceptable for `sameSite=lax` but a rebuild that adds `sameSite=none` would need to add CSRF.

---

## 9. Things to preserve

- The two-layer guard (middleware + client context + backend re-enforcement).
- 3-second timeout on every middleware network call.
- HMAC cookie signed and verified by the same `SESSION_SECRET` on frontend and backend.
- Fast-path `authToken` verification in `/api/auth/session` (skips backend round-trip).
- Local-mode bypass for offline dev.
- `isAdmin` gating in both Navbar and `/admin`.
- Approval revocation is live — middleware re-checks on every protected navigation.

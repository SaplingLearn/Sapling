# Feature · Auth & Session

> Covers: `/signin`, `/signin/callback`, `/api/auth/session`, `/pending`, the `sapling_session` cookie contract, and `UserContext` — the single global store for authenticated identity. Onboarding (which happens immediately after first sign-in) lives in `features/onboarding.md`.

---

## 1. Overview

Sapling uses **Google OAuth** (handled by the backend) combined with an **HMAC-signed session cookie** issued by the Next.js Route Handler at `/api/auth/session`. The backend is the identity authority (it holds the OAuth client secret, does the Google exchange, and stores the user record). The frontend's job is:

1. Redirect unauthed users to `${NEXT_PUBLIC_API_URL}/api/auth/google`.
2. Receive the callback at `/signin/callback?user_id&name&avatar&is_approved&auth_token`.
3. Hand the `auth_token` (HMAC-signed by the backend using `SESSION_SECRET`) to `/api/auth/session`, which verifies it and issues a separate `sapling_session` cookie signed by the same shared secret.
4. Keep authenticated identity globally available via `UserContext`.
5. Re-verify `is_approved` on every protected navigation via `middleware.ts` + `GET /api/auth/me`.

The frontend session **never** sees a Google OAuth token directly — it only sees the backend's HMAC-signed hand-off token (`auth_token`). The cookie it writes is its own HMAC signature over `{userId, exp}`, not the Google token.

Two secrets share a key:
- `SESSION_SECRET` (frontend env var, ≥32 bytes required — `lib/sessionToken.ts:6-8`) — signs both (a) the Next.js session cookie and (b) the `auth_token` coming from the backend.
- The same secret must be set as `SESSION_SECRET` on the backend; if they don't match, the fast-path verification in `/api/auth/session` fails and the route falls back to calling `GET /api/auth/me` for user verification (`src/app/api/auth/session/route.ts:58-67`).

---

## 2. User flows

### 2.1 Flow: first-time sign-in (new user)

Trigger: user clicks "Continue with Google" (either on landing-page OnboardingFlow step 0, or on a "Try again" button on `/signin?error=...`).

1. `OnboardingFlow.handleGoogleSignIn()` (`src/components/OnboardingFlow.tsx:206-209`) sets `sessionStorage.sapling_onboarding_pending = 'true'` and hard-redirects to `${API_URL}/api/auth/google`.
2. Backend runs the Google OAuth handshake, upserts the user row (with `is_approved = false` by default for new users), creates an `auth_token` HMAC-signed with `SESSION_SECRET`, and redirects the browser to `${FRONTEND_URL}/signin/callback?user_id&name&avatar&is_approved&auth_token` (or `?error=not_approved|invalid_domain` on failure).
3. `/signin/callback` (`src/app/signin/callback/page.tsx`) mounts, `CallbackInner` reads query params, calls `setActiveUser(userId, name, avatar)` + `confirmApproved()` on `UserContext`, and fires `POST /api/auth/session` with `{userId, authToken}`.
4. `/api/auth/session` (`route.ts:52-107`) verifies the HMAC `authToken` via Web Crypto `crypto.subtle.verify` (fast path, no backend round-trip), then calls `signSession(verifiedUserId)` and sets `sapling_session` as an HTTP-only `sameSite=lax` cookie with `maxAge=SESSION_MAX_AGE = 2_592_000` seconds (30 days).
5. Because `sessionStorage.sapling_onboarding_pending === 'true'`, the callback does **not** hit `/api/auth/me`. It `router.replace('/')` straight to the landing page, where the `OnboardingFlow` is already rendered and in mid-flight.
6. Landing-page `useEffect` (`src/app/page.tsx:67-86`) sees `isAuthenticated && pending`, removes the pending flag, jumps the onboarding UI to step 1 (Name), and continues the flow. See `features/onboarding.md` for the rest.

Edge cases:
- **`is_approved === false`** in the callback params (user exists but waiting for admin approval): callback redirects to `/signin?error=not_approved`. The user sees the signin page's error-copy variant. Note: this is a *different* path than `/pending` — `/pending` is reserved for users who have already established a session cookie.
- **Missing/invalid required params** (`!userId || !name || approvedParam !== 'true'` — see `callback/page.tsx:25-28`): redirect to `/signin?error=signin_failed`.
- **`/api/auth/session` fails** (e.g., `SESSION_SECRET` missing or `authToken` invalid): the `fetch` is fire-and-forget in `callback/page.tsx:34-38` — the user still proceeds to `/dashboard` or `/`, but the middleware will bounce them back to Google OAuth on the next navigation because the cookie was never set. Silent-failure trade-off intentional to preserve onboarding UX.

### 2.2 Flow: returning user (existing session, approved)

Trigger: user loads any path.

1. Browser sends `sapling_session` cookie with the request.
2. For matched paths (see §3), `middleware.ts` runs:
   - `verifySession(token)` — HMAC-verifies signature, checks `exp`, returns `{userId}` or `null` (`sessionToken.ts:43-66`).
   - `GET ${NEXT_PUBLIC_API_URL}/api/auth/me?user_id=...` with a 3-second `AbortController` timeout (`middleware.ts:87-98`). Returns `{is_approved, onboarding_completed, ...}`.
   - If `is_approved === true`: `NextResponse.next()` — render the page.
3. Client-side, `UserProvider` (`UserContext.tsx:72-94`) reads `localStorage.sapling_user` (seeded on first sign-in by `setActiveUser`) and populates `userId`/`userName`/`avatarUrl` synchronously for the first paint. `userReady` becomes `true` after the localStorage read — pages use `userReady` to gate data fetches so they don't fire with an empty user id.
4. A second effect in `UserProvider` calls `fetch /api/users` (`UserContext.tsx:97-113`) to re-sync the live user list and overwrite `userName` with the backend-truthful name.
5. `fetchProfileData(userId)` (`UserContext.tsx:115-129`) calls `GET /api/auth/me?user_id=` and populates `username`, `roles`, `equippedCosmetics`, `featuredRole`, `isAdmin`.

Edge cases:
- **Expired cookie** (`exp < now`): `verifySession` returns `null` → middleware redirects to `${API_URL}/api/auth/google`. Effectively indistinguishable from "never signed in" from the user's perspective.
- **Backend down** during middleware `fetch`: `catch` block at `middleware.ts:106-108` → redirect to Google OAuth. Harsh but prevents serving protected pages to unverified users.
- **`/api/auth/me` returns `is_approved: false`**: middleware redirects to `/pending`. This is the revocation path — an admin can un-approve a user and the next navigation kicks them out.
- **Localstorage user present but cookie missing**: `/signin` page's mount effect (`signin/page.tsx:20-51`) POSTs to `/api/auth/session` with just `userId` (no `authToken`). The route falls back to asking the backend if the user is still approved; on 200 sets the cookie and redirects `/dashboard`, on 403 redirects `/pending`.

### 2.3 Flow: sign out

Trigger: user clicks "Sign out" in Navbar user-menu or `/pending` "Sign out" button.

1. `useUser().signOut()` (`UserContext.tsx:151-167`):
   - `fetch('/api/auth/session', { method: 'DELETE' })` — route handler returns `{ok:true}` and sets `sapling_session=''` with `maxAge:0`.
   - Clears all in-memory user state (`userId`, `userName`, `avatarUrl`, `isAuthenticated=false`, `isApproved=false`, roles, cosmetics, `isAdmin`).
   - `localStorage.removeItem('sapling_user')`.
2. Caller code (e.g., Navbar `handleSignOut`) `router.push('/')` to the landing page. Next navigation to any protected path will bounce back to Google OAuth.

Edge cases:
- The `DELETE` fetch is wrapped in `try/finally` — even if it errors (e.g., offline), local state is still cleared so the user isn't trapped in a signed-in UI.
- `sessionStorage.sapling_onboarding_pending` is **not** cleared on sign-out. This is intentional (or an oversight — flag in QUESTIONS) so a user who signed out mid-onboarding can resume. But: if another user signs in on the same browser, they will inherit that pending flag and be dropped into the landing-page onboarding flow until they finish. Flagging as Q11 below.

### 2.4 Flow: unapproved user attempts a protected route

1. Middleware matches path, verifies cookie, calls `/api/auth/me`.
2. Backend returns `{is_approved: false}`.
3. Middleware `return NextResponse.redirect('/pending')` (`middleware.ts:103-105`).
4. `/pending` (`src/app/pending/page.tsx`) renders — wordmark, "You're on the waitlist" message, single "Sign out" button. No polling or auto-redirect; user must manually retry by signing out and back in (admin must have approved them in the interim).

### 2.5 Flow: `/signin` direct access when already signed in

1. `middleware.ts:60-68` special-cases `/signin`:
   - If cookie is valid and `/api/auth/me` returns `is_approved: true` → `redirect('/dashboard')`.
   - If cookie is valid and `is_approved: false` → `redirect('/pending')`.
   - Otherwise, unless `?error=` param is present, redirect directly to Google OAuth (`redirectToGoogleOrSignin`).
   - If `?error=` is present, fall through and render the `/signin` page with its error UI (so users whose sign-in failed can see why and retry).

Meaning: the `/signin` page is **only ever rendered** when there is an `?error=` param. Without `?error=`, it is a transient redirect target.

---

## 3. Middleware matcher (copy-paste-ready)

```ts
// src/middleware.ts:113-122
export const config = {
  matcher: [
    '/signin',
    '/dashboard/:path*', '/learn/:path*', '/study/:path*',
    '/tree/:path*',     '/flashcards/:path*', '/library/:path*',
    '/calendar/:path*', '/social/:path*',
    '/settings/:path*', '/achievements/:path*',
    '/admin/:path*',
  ],
}
```

Not matched (unprotected by middleware): `/`, `/about`, `/privacy`, `/terms`, `/careers/**`, `/signin/callback`, `/pending`, `/api/*`.

**Bypass**: `process.env.NEXT_PUBLIC_LOCAL_MODE === 'true'` short-circuits everything to `NextResponse.next()` (`middleware.ts:54-56`). Combined with `UserContext` local-mode branch (`UserContext.tsx:73-82`), this is the offline dev-loop mode — user is always `LOCAL_USER` (`{id: 'local-user-001', name: 'Local Dev', avatar: ''}`) with `isApproved=true, isAdmin=true`.

---

## 4. `UserContext` — the one global store

File: `src/context/UserContext.tsx`. Wrapped around the entire app in `app/layout.tsx:57`.

### 4.1 Exposed API

| Prop | Type | Source |
|---|---|---|
| `userId` | `string` | localStorage → backend `/api/users` |
| `userName` | `string` | localStorage → backend `/api/users` |
| `avatarUrl` | `string` | localStorage |
| `users` | `UserOption[]` | backend `/api/users` |
| `userReady` | `boolean` | `true` after localStorage read completes |
| `isAuthenticated` | `boolean` | localStorage presence / `setActiveUser` |
| `isApproved` | `boolean` | `confirmApproved()` after callback; not live-synced on mount (relies on middleware to gate) |
| `username` | `string \| null` | `/api/auth/me` |
| `roles` | `UserRole[]` | `/api/auth/me` |
| `equippedCosmetics` | `EquippedCosmetics` | `/api/auth/me` |
| `featuredRole` | `Role \| null` | `equipped_cosmetics.featured_role` in `/api/auth/me` |
| `isAdmin` | `boolean` | `/api/auth/me` (`is_admin` flag) |
| `setActiveUser(id, name, avatar?)` | fn | Writes localStorage `sapling_user` and mutates context |
| `confirmApproved()` | fn | Marks `isApproved=true` (called by `/signin/callback` only) |
| `signOut()` | async fn | DELETE session + clear state + clear localStorage |
| `refreshProfile()` | async fn | Re-runs `/api/auth/me` |

### 4.2 Behavior quirks worth preserving in a rebuild

- **`userReady` gating.** Every page that fetches per-user data does `if (!userReady || !userId) return` before calling its API. This guards against a SSR/CSR race where the page would fetch with `userId === ''` and get garbage/404. Any rebuild must preserve an equivalent "don't fetch until hydrated" mechanism.
- **Name reconciliation.** After localStorage populates `userName`, a second pass from `/api/users` overwrites it (`UserContext.tsx:97-113`). This prevents a stale greeting if the user renamed themselves from another browser.
- **`isApproved` is set once, not polled.** The client-side `isApproved` flag is only set to `true` by `confirmApproved()` in `/signin/callback`. Middleware is the authority for ongoing approval. Don't add client polling — rely on middleware.
- **Local-mode shortcut.** When `NEXT_PUBLIC_LOCAL_MODE=true`, `UserContext` populates with `LOCAL_USER` and skips the backend. All `lib/api.ts` calls are routed through `handleLocalRequest` (`lib/localData.ts`) — fake in-memory data. Keep this path around for offline dev unless you replace it with something better (Storybook mocks, MSW, etc.).

---

## 5. Components involved

| Component | File | Role |
|---|---|---|
| `UserProvider` / `useUser()` | `src/context/UserContext.tsx` | Identity context |
| `SignInPage` / `SignInInner` | `src/app/signin/page.tsx` | Error-recovery signin card + auto-reexchange |
| `CallbackPage` / `CallbackInner` | `src/app/signin/callback/page.tsx` | OAuth return handler |
| `POST/DELETE /api/auth/session` | `src/app/api/auth/session/route.ts` | HMAC verify + cookie issue/clear |
| `PendingPage` | `src/app/pending/page.tsx` | Waitlist holding screen |
| `verifySession` / `signSession` | `src/lib/sessionToken.ts` | Web Crypto HMAC helpers, shared with middleware |
| `middleware` | `src/middleware.ts` | Route guard |
| `Navbar` (user-menu) | `src/components/Navbar.tsx:340-404` | Sign-out button |

Indirect: any page that calls `useUser()` — basically all in-scope pages.

---

## 6. API calls (auth-relevant only)

| Call | Direction | When |
|---|---|---|
| `GET ${API_URL}/api/auth/google` | Hard redirect | Navbar Sign In / `/signin` retry / `OnboardingFlow` step 0 / middleware fallback |
| `GET ${API_URL}/api/auth/google/callback` | Browser (from Google) | Google consent screen → backend → `/signin/callback` |
| `GET ${API_URL}/api/auth/me?user_id=` | Frontend fetch | Middleware (every protected nav), `UserContext.fetchProfileData`, `/api/auth/session` fallback, `/signin/callback` onboarding branch |
| `GET ${API_URL}/api/users` | Frontend fetch | `UserContext` mount |
| `POST /api/auth/session` (Next route) | Frontend fetch | `/signin` (localStorage re-exchange), `/signin/callback` |
| `DELETE /api/auth/session` (Next route) | Frontend fetch | `UserContext.signOut` |

---

## 7. State storage

| Storage | Key | Written by | Read by | Lifetime |
|---|---|---|---|---|
| Cookie (HTTP-only, sameSite=lax) | `sapling_session` | `POST /api/auth/session` | `middleware.ts` (via `verifySession`) | 30 days (`SESSION_MAX_AGE`) |
| `localStorage` | `sapling_user` (`{id, name, avatar}`) | `UserContext.setActiveUser` | `UserContext` mount, `/signin` mount | Until sign-out or manual clear |
| `sessionStorage` | `sapling_onboarding_pending` (`'true'`) | `OnboardingFlow.handleGoogleSignIn`, `/signin/callback` when `onboarding_completed=false` | Landing page mount, `/signin/callback` mount | Cleared by landing page on consume (`src/app/page.tsx:71`) |

---

## 8. Error and edge cases (catalog)

Preserve these in the rebuild.

1. **Error copy table** (`src/app/signin/page.tsx:9-13`):
   - `not_approved` → "Your account is pending approval."
   - `invalid_domain` → "Sign-in is limited to approved school accounts."
   - `google_not_configured` → "Google sign-in is not configured on the server."
   - Fallback for unknown codes → `"Something went wrong (${error})."`
   - Plus `signin_failed` (from callback), which uses the fallback copy.

2. **`/signin` Suspense wrapper** (`signin/page.tsx:134-140`). `useSearchParams` requires `<Suspense>` in Next App Router — don't drop this wrapper.

3. **3-second timeout** on every middleware `/api/auth/me` call (`middleware.ts:33-43, 87-98`). If this is missed, a slow backend will hang page renders. A rebuild should keep the timeout (maybe even lower it) and redirect to Google OAuth on timeout.

4. **`SESSION_SECRET` length guard** (`sessionToken.ts:5-8`). Enforces ≥32 bytes. Throwing on short secrets prevents weak prod configs — keep this.

5. **Base64url de/encoding** (`sessionToken.ts:11-25`, duplicated in `route.ts:16-26`). Both files implement their own `toBase64Url`/`fromBase64Url` because they can't share module code across the Edge runtime boundary (middleware + route.ts run in Edge, not Node). Rebuild can dedupe if using a single runtime.

6. **`Uint8Array<ArrayBuffer>`** type annotation. `fromBase64Url` in `route.ts:17` explicitly returns a `Uint8Array<ArrayBuffer>` (concrete) so TypeScript sees it as `BufferSource` for `crypto.subtle.verify`. This is a TS 5.x typing quirk and is not optional — leaving it as plain `Uint8Array` will fail type-checks.

7. **`/signin/callback` fire-and-forget session POST.** Failure doesn't block the redirect. Intentional. A rebuild that wants stricter guarantees should await the POST and only proceed on success — but be aware of the UX regression.

---

## 9. Things to preserve in the rebuild

- 30-day HTTP-only, `sameSite=lax`, HMAC-SHA-256-signed cookie.
- Dual secret model: the same `SESSION_SECRET` verifies the backend's `auth_token` and signs the frontend's `sapling_session`.
- Fast-path verification (no backend round-trip) when the `auth_token` is present; graceful fallback to `GET /api/auth/me` when it isn't (e.g., direct re-exchange from localStorage).
- Middleware calls `/api/auth/me` on **every** protected navigation for live approval revocation — do not cache approval in the cookie.
- 3-second `AbortController` timeout on every middleware network call.
- `/pending` as the dead-simple holding page with a sign-out button (no dashboard, no nav surface). Keep it "hostile-to-progress" until an admin flips the flag.
- `?error=` query-param mechanism on `/signin` for surfacing backend reasons to the user.
- `sessionStorage.sapling_onboarding_pending` handoff between Google's redirect and the landing-page onboarding flow — this is the only reason new users land on `/` and not `/dashboard` after sign-in.
- Local-mode (`NEXT_PUBLIC_LOCAL_MODE=true`) must stay wired at both the middleware and UserContext levels so offline dev works.
- The `userReady` gate — every page that calls `lib/api.ts` must wait on this flag before fetching.

---

## 10. Question surfaced by this deep-dive

**Q11.** `signOut()` does **not** clear `sessionStorage.sapling_onboarding_pending`. If user A signs out mid-onboarding and user B signs in on the same browser, B could inherit the flag and be forced into the landing-page onboarding instead of going straight to `/dashboard`. Reproduction: sign in as A, trigger `sapling_onboarding_pending=true` via `OnboardingFlow`, sign out before finishing, sign in as B — B lands on `/` with A's partially-entered state. Intentional or a bug? (Noted in `QUESTIONS.md`.)

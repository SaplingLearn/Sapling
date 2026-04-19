# Sapling Frontend Audit — 03 · State Architecture

> How state is organized today. **One context provider** (`UserContext`), **zero** state libraries, heavy reliance on per-page `useState`. Caching is ad-hoc; there is no query cache.

---

## 1. Global state

### 1.1 `UserContext` (`src/context/UserContext.tsx`)

The only React context provider in the app (apart from the in-component `ToastContext` — see §2).

Exposes:

```ts
{
  userId, userName, avatarUrl, users,
  userReady, isAuthenticated, isApproved,
  username, roles, equippedCosmetics, featuredRole, isAdmin,
  setActiveUser(id, name, avatar?), confirmApproved(), signOut(), refreshProfile()
}
```

Lifecycle and semantics covered in `features/auth.md` §4.

Key invariants:
- `userReady = true` only after the localStorage read completes → every feature page gates `useEffect` data fetches on `if (userReady && userId)`.
- `isApproved` is set once by `confirmApproved()` from `/signin/callback`; middleware is the authority for revocation on subsequent navigations.
- `fetchProfileData(userId)` (`UserContext.tsx:115-129`) runs on each change of `userId`/`userReady` and populates roles/cosmetics/isAdmin from `/api/auth/me`.

### 1.2 `ToastProvider` (`src/components/ToastProvider.tsx`)

Second context, wrapping `{children}` in the root layout. Exposes:

```ts
useToast() → { showToast(content, { duration?=5000 }) }
```

Every mutation in the app should `showToast(e.message)` on catch — consistency is enforced by convention, not types.

---

## 2. Per-page state

No feature uses Redux/Zustand/Jotai/XState. Per-page patterns:

- `useState` + `useEffect` for every feature store.
- `useRef` for non-render state (animation counters, timeouts, DOM references, observation subjects).
- `useMemo` for derived slices (filtered nodes, week info, memberships).
- `useCallback` only where identity stability matters (KnowledgeGraph `onNodeClick`, rare).

No feature shares state with another page via context. Cross-page data (e.g., graph nodes) is refetched on every navigation.

This is fine for the current scale but:
- Refetches add flicker/latency on every route change.
- Mutations on one page don't propagate to another (e.g., adding a course on `/dashboard` doesn't update `/library`'s course list unless the user reloads or that effect happens to rerun).

The rebuild should introduce a query cache (React Query / SWR) or at least a feature-scoped context where cross-route consistency matters (courses, achievements, cosmetics).

---

## 3. Persistence (client-side)

### 3.1 Cookies

| Key | Written by | Read by | Lifetime | Purpose |
|---|---|---|---|---|
| `sapling_session` | `POST /api/auth/session` (Next route handler) | `middleware.ts` (via `verifySession`) | 30 days (HTTP-only, `sameSite=lax`) | HMAC session token |

### 3.2 `localStorage`

| Key | Written by | Read by | Purpose |
|---|---|---|---|
| `sapling_user` | `UserContext.setActiveUser` | `UserContext` mount, `/signin` re-exchange | Cached `{id, name, avatar}` for fast first paint |
| `sapling_shared_ctx` | `/learn` toggle | `/learn` initial state | Remember "Class Intel" (shared course context) preference |
| `sapling_session_end_count` | `/learn` on session end | `/learn` + `SessionFeedbackGlobal` | Every-5-sessions feedback counter |
| `sapling_learn_had_session` | `/learn` once `messages.length > 0 && sessionId` | `SessionFeedbackGlobal` | Gate navigate-away feedback to users who actually held a session |
| `sapling_session_feedback_nav_last_shown` | `SessionFeedbackGlobal` on trigger | `SessionFeedbackGlobal` | 3-day cooldown timestamp |
| `sapling_feedback_last_shown` | `FeedbackFlow` on dismiss/submit | `FeedbackFlow` on mount | 3-day cooldown for passive feedback |
| `sapling_disclaimer_ack` | `AIDisclaimerChip` on close | `AIDisclaimerChip` mount | First-view disclaimer acknowledgement |

### 3.3 `sessionStorage`

| Key | Written by | Read by | Purpose |
|---|---|---|---|
| `sapling_onboarding_pending` | `OnboardingFlow.handleGoogleSignIn`, `/signin/callback` when `onboarding_completed=false` | Landing page on mount, `/signin/callback` on subsequent mount | Bridge Google OAuth redirect → resume onboarding |

### 3.4 URL state

Covered in `01-routes.md §3.1`. Summary of long-lived deep-link parameters:
- `/dashboard?suggest=<concept>`
- `/learn?topic&mode&suggest&testFeedback`
- `/tree?suggest`
- `/social?suggest`
- `/calendar?connected=true`
- `/signin?error=...`
- `/signin/callback?user_id&name&avatar&is_approved&auth_token`

### 3.5 Refs (non-render state)

A few patterns worth preserving:

- **`nodeClickPayloadRef` in `/learn`**: keeps `KnowledgeGraph.onNodeClick` identity stable so the D3 simulation doesn't reseed on every mode/course change.
- **`feedbackDueRef` / `pendingNavRef` in `/learn`**: holds the "open feedback after session ends" intent and a deferred navigation target.
- **`prevPathname` in `SessionFeedbackGlobal`**: detects `/learn → elsewhere` transitions.
- **Various animation-timeline refs** in `/`/OnboardingFlow for storing `setTimeout` ids and RAF-driven animation state.

---

## 4. Data flow patterns

### 4.1 Initial-load pattern (read-heavy pages)

1. `if (!userReady || !userId) return;`
2. `Promise.all([...])` to fetch everything a page needs.
3. Populate state, clear loading flag.
4. On error: single `fetchError` string, render an error card with a "Retry" that forces `window.location.reload()`.

Repeated verbatim in `/dashboard`, `/social`, `/settings`, `/learn`, `/library`, `/calendar`, `/tree`, `/achievements`, `/study`.

Rebuild: a `useQuery`-style hook would make this one line, plus proper caching / dedup / refetch-on-focus.

### 4.2 Mutation pattern

- Disable button (`setSaving(true)`).
- Call `libApiFn(...)`.
- On success: mutate local state to match; `showToast('Saved')`.
- On error: `showToast(e.message || 'Failed to ...')`.
- Finally: `setSaving(false)`.

Mostly no optimism. Exceptions: `RoomChat` (chat messages + reactions) and `/learn` chat (appends user message first, then awaits reply).

### 4.3 Realtime pattern (chat only)

- Subscribe to Supabase Realtime on mount.
- `postgres_changes` INSERT/UPDATE → patch local `messages` state.
- Own INSERTs filtered via `user_id === userId` to avoid echo.
- Clean up via `supabase.removeChannel(ch)` on unmount.

Only `RoomChat.tsx` uses this. Everything else is request/response.

### 4.4 Polling

**No polling anywhere.** `/pending` doesn't poll for approval. `/calendar` doesn't re-check Google Calendar status after disconnect. `/social` doesn't reload room overview. The user has to navigate away and back.

The rebuild should consider:
- Polling on `/pending` to auto-redirect when approved.
- Periodic refresh or focus-based invalidation on `/social` room overviews.

---

## 5. Caching

None to speak of.

- No HTTP caching headers respected (most endpoints don't send `Cache-Control`).
- No `React.cache`, no SWR, no React Query.
- The only caching that exists: Supabase Realtime subscriptions keep state live once subscribed.

Navigating from `/dashboard` to `/learn` and back refetches the graph twice.

---

## 6. React Compiler

`next.config.ts:20` → `reactCompiler: true`, with `babel-plugin-react-compiler@1.0.0` installed.

Implications:
- Manual `useMemo`/`useCallback` usages are mostly redundant in the compiled output.
- But load-bearing ref patterns (e.g., `nodeClickPayloadRef`) are still needed because the compiler does not rewrite ref semantics.

Rebuild can probably cut many `useMemo`/`useCallback` usages; keep the ref patterns for D3 interop.

---

## 7. Patterns to preserve

- `userReady` gating.
- Cookie-based auth (HTTP-only).
- localStorage as a write-through cache for `sapling_user` (fast first paint).
- `sessionStorage` for the one-shot onboarding-pending handoff.
- `?suggest=` query-param contract across four pages.
- The "mutate local state after success" pattern when response shape is known.
- Root-layout-mounted context providers (`UserProvider`, `ToastProvider`).
- `ErrorBoundary` wrapping the main area + `app/error.tsx` for framework-level errors.

## 8. Patterns to rework

- Introduce a query library (React Query / SWR) to stop refetching everything on navigation.
- Split `UserContext` into smaller slices (identity / cosmetics / roles) so cosmetic changes don't invalidate everything.
- Polling on `/pending`.
- Consistent error surfacing — replace silent `console.error` catches with `showToast`.
- A single "feedback cooldown" state rather than 4 localStorage keys.
- Consolidate inline `useIsMobile` definitions into one hook.

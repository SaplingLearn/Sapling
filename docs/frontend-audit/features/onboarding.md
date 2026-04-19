# Feature · Onboarding

> Covers: `OnboardingFlow.tsx` — the 6-step sign-up experience rendered on top of the landing page. Mounted from `src/app/page.tsx:941`. Auth hand-off is documented in `features/auth.md`.

---

## 1. Overview

Sapling's onboarding is a six-step form that a new user fills out **after** Google OAuth but **before** first real use of the app. The flow is rendered as a full-viewport overlay on the landing page, not a dedicated route. This is unusual for a rebuild target — most products put onboarding behind `/onboarding` or `/signup`. The current implementation entangles the onboarding UI with the landing-page 3D canvas animation; the rebuild can (and probably should) disentangle them.

The six steps (`src/components/OnboardingFlow.tsx:9-16`):

| # | id | Label | Purpose |
|---|---|---|---|
| 0 | `google` | Account | "Continue with Google" button → hard-redirects to `${API}/api/auth/google` |
| 1 | `name` | Name | First + last name, both required |
| 2 | `school` | School | Hardcoded "Boston University" + class-year picker (Freshman/Sophomore/Junior/Senior/Graduate/Other) |
| 3 | `academics` | Academics | Major(s) (required, ≥1) + Minor(s) (optional), both searchable across hardcoded BU lists |
| 4 | `courses` | Courses | Course search via backend `/api/onboarding/courses?q=`, debounced 200ms, ≥1 required |
| 5 | `style` | Learning Style | Radio-ish picker: Visual / Reading-Writing / Auditory / Hands-On / Mixed |

On step 5 completion, `handleNext()` calls `onFinish(...)` which in `src/app/page.tsx:552-588` POSTs to `/api/onboarding/profile` and triggers a ~4-second outro animation before `router.replace('/dashboard')`.

---

## 2. User flows

### 2.1 Flow: brand-new visitor walks through all 6 steps

Trigger: user lands on `/` while signed out.

1. **Landing-page intro overlay** plays (orbit ring of colored dots, `src/app/page.tsx:597-610`). When `heroMounted=true`, the overlay fades out and the hero canvas/text scramble-animates in.
2. **Step 0 rendered by default** (`activeStep === 0`) because `OnboardingFlow` is always mounted — visibility is controlled by a CSS `opacity` transition (`OnboardingFlow.tsx:290-299`).
3. User clicks **Continue with Google** → `handleGoogleSignIn()` sets `sessionStorage.sapling_onboarding_pending='true'` and hard-navigates to `${API_URL}/api/auth/google`.
4. Google OAuth round-trip. Backend redirects to `/signin/callback?user_id&name&avatar&is_approved&auth_token`.
5. `/signin/callback` calls `setActiveUser` + `POST /api/auth/session` (cookie set), sees `sapling_onboarding_pending`, **does not** call `/api/auth/me`, `router.replace('/')`.
6. Landing page mounts again. `useEffect` (`page.tsx:67-86`) detects `isAuthenticated && sapling_onboarding_pending`:
   - Clears the flag.
   - Instantly scrolls to top.
   - `setActiveStep(1)` — jumps past step 0 (Google), which is now done.
   - `setCompleted(new Set([0]))`.
   - Activates the 3D-canvas zoom (`zoomActiveRef.current = true`, `canvasZoomRef.current = 2.5`, `clusterProgressRef.current = 1`) — visually the canvas pulls in and the onboarding card slides into view.
   - `setOnboardingPhase('active')`.
7. User fills steps 1→5. On each step, `canAdvance()` (`OnboardingFlow.tsx:194-204`) gates the "Continue" button. Pressing Continue calls `handleNext()`:
   - Marks current step as `completed` in the `Set<number>`.
   - `activeStep < STEPS.length - 1` → `setActiveStep(activeStep + 1)`.
8. On step 5 (Learning Style), the Continue button label changes to **"Launch Sapling"** (`OnboardingFlow.tsx:721-724`). Pressing it calls `onFinish(payload)`.
9. `handleOnboardingComplete(payload)` (`src/app/page.tsx:552-588`):
   - `await fetch('/api/onboarding/profile', {POST, JSON.stringify(...)} )` — saves `user_id`, `first_name`, `last_name`, `year`, `majors`, `minors`, `course_ids`, `learning_style`. Errors logged, not surfaced to user (silent failure — see edge cases).
   - Starts the outro animation sequence (4 sequential `setTimeout`s):
     - t=1400ms: `setOutroText('in')` — outro text fades in.
     - t=3050ms: `setOutroText('out')` + `zoomOutroRef.current = true` — zoom accelerates outward.
     - t=3450ms: `setOutroOverlay(true)` — white overlay fades in.
     - t=4250ms: `router.replace('/dashboard')`.
10. User lands on `/dashboard`.

### 2.2 Flow: returning user who never finished onboarding

Trigger: user signs in via Google but has `onboarding_completed: false` on the backend (e.g., closed the browser during step 3 last time).

1. Backend redirects to `/signin/callback?...&is_approved=true`.
2. `/signin/callback` sets `sapling_session` cookie, reads `/api/auth/me`, sees `onboarding_completed: false`, sets `sapling_onboarding_pending='true'`, `router.replace('/')`.
3. Landing page applies the same "resume onboarding" effect. **However**, `OnboardingFlow` internal state (`formData`) is NOT persisted — it was wiped on navigation. The user starts over from step 1.
4. Completing step 5 re-POSTs `/api/onboarding/profile` (idempotent server-side — the backend upserts).

**Gap for the rebuild:** form state is lost on mid-flow exit. Consider persisting `formData` to `localStorage.sapling_onboarding_draft` keyed by `userId` and hydrating on mount.

### 2.3 Flow: close / abort

Trigger: user presses Escape or clicks the X button at top-right during any step.

- **Escape** (`OnboardingFlow.tsx:148`) → `onClose()` (the landing page's `closeOnboarding`, `page.tsx:539-550`).
- **X button** (`OnboardingFlow.tsx:302-312`) → same `onClose()`.
- `closeOnboarding` cancels pending timers, triggers the "nodes fade out" death animation (`obNodesRef.current.forEach(n => n.dyingAt = t)`), and sets `onboardingPhase='out'` → after 700ms → `'idle'`.
- The landing page is now in the normal pre-auth state (but the user is still logged in).
- **No data is saved** if the user aborts. No session data either (the onboarding form's state is in React, not localStorage).
- Because `setCompleted` is state on the landing page (not `OnboardingFlow`), the user can re-open the flow in the future and it will remember completed steps within that session only.

Flag for rebuild: escape/close during onboarding leaves the user in an ambiguous state — signed in but with no profile. They can reach `/dashboard` via the URL bar, but many features will show empty states because `/api/onboarding/profile` was never called. Recommend: make onboarding a real route (`/onboarding`) that gates all protected routes until completed, rather than a dismissible overlay.

---

## 3. Step-by-step detail

### Step 0 — Account (`OnboardingFlow.tsx:380-404`)
- Heading: "Let's get started"
- Subtitle: "Sign in with Google to create your Sapling account. A valid .edu email is required to register."
- CTA: styled Google button (inline SVG logo).
- Behavior on click: `handleGoogleSignIn()`:
  ```ts
  sessionStorage.setItem('sapling_onboarding_pending', 'true');
  window.location.href = `${API_URL}/api/auth/google`;
  ```
- Step 0 has no "Back" or step indicator (the top-left progress UI is gated by `activeStep > 0`, `OnboardingFlow.tsx:315`).

### Step 1 — Name (`OnboardingFlow.tsx:406-423`)
- Heading: "What's your name?"
- Two side-by-side inputs, first autofocused.
- Validation: both must be non-empty after `.trim()`. `canAdvance()` gates the Continue button.

### Step 2 — School (`OnboardingFlow.tsx:425-502`)
- Heading: "Where do you study?"
- **Hardcoded** "Boston University" read-only field (`formData.school = 'Boston University'` is set in the initial state, `OnboardingFlow.tsx:135-138`).
- Year picker: custom dropdown button, `YEAR_OPTIONS = ['Freshman', 'Sophomore', 'Junior', 'Senior', 'Graduate', 'Other']`. `selectYear(option)` stores `option.toLowerCase()` in `formData.year`.
- Custom dropdown handles ARIA `role="listbox"` / `role="option"` / `aria-selected` and keyboard (`handleOptionKeyDown` — Enter/Space triggers selection).
- Blur closes the dropdown with a 150ms delay (`onBlur={() => setTimeout(..., 150)}`) to allow the onMouseDown on the option to fire first.
- Validation: `formData.school && formData.year`.

### Step 3 — Academics (`OnboardingFlow.tsx:504-593`)
- Heading: "What's your major?" — subtitle mentions optional minors.
- **Hardcoded lists**:
  - `BU_MAJORS` — 120+ BU majors (`OnboardingFlow.tsx:18-57`).
  - `BU_MINORS` — 90+ BU minors (`OnboardingFlow.tsx:59-82`).
- Rendered as two searchable-tag-input clones (majors then minors). Search is client-side — filters the hardcoded array with `.includes(query.toLowerCase())`, capped at 8 results.
- Selecting a suggestion adds it as a pill; clicking the X on a pill removes it.
- Validation: `formData.majors.length > 0` (minors optional).

### Step 4 — Courses (`OnboardingFlow.tsx:595-663`)
- Heading: "What are you studying?"
- Input debounced 200ms, queries backend `/api/onboarding/courses?q=<value>` (`OnboardingFlow.tsx:234-250`).
- Returned courses have `{id, course_code, course_name}`. Displayed as `course_code` bold + `course_name` dim (when different).
- Selecting a suggestion adds a pill with `course_code`.
- Validation: `formData.courses.length > 0`.
- **No fallback UI for empty API response.** If the backend returns zero matches, the suggestions list just doesn't render. User might think the feature is broken. Consider an "No matches — try different keywords" affordance in the rebuild.

### Step 5 — Learning Style (`OnboardingFlow.tsx:665-688`)
- Heading: "How do you learn best?"
- 5 stacked cards (`LEARNING_STYLES`, `OnboardingFlow.tsx:85-91`):
  | id | Label | Description |
  |---|---|---|
  | `visual` | Visual | Diagrams, charts, and visual maps |
  | `reading` | Reading / Writing | Notes, textbooks, and written summaries |
  | `auditory` | Auditory | Lectures, discussions, verbal explanations |
  | `hands-on` | Hands-On | Practice problems and active experimentation |
  | `mixed` | Mixed | A combination of multiple styles |
- Single selection — clicking a card sets `formData.style = ls.id`.
- Validation: `formData.style.length > 0`.
- Continue-button label becomes **"Launch Sapling"** on this step.

---

## 4. Component interface

```ts
interface Props {
  visible: boolean;                        // Drives opacity + pointerEvents
  onClose: () => void;                     // Escape/X handler — landing page triggers close animation
  onFinish: (data: { firstName; lastName; school; year; majors; minors; course_ids; style }) => void;
  activeStep: number;                      // Lifted state — landing page owns which step
  completed: Set<number>;                  // Lifted state — which steps are "done"
  setActiveStep: (s: number) => void;
  setCompleted: (s: Set<number>) => void;
}
```

Notes:
- `activeStep` and `completed` are **owned by the landing page**, not `OnboardingFlow`. That's because the landing page's 3D canvas reads them (via refs `clusterActiveStepRef` and `clusterCompletedRef`, `src/app/page.tsx:102-103`) to drive the node coloring/positioning animation. Extract this coupling during the rebuild.
- `formData` (the actual form answers) is **internal** to `OnboardingFlow` — not exposed until `onFinish` fires.
- `visible` is an animation gate (opacity 0↔1 + pointer-events), not a mount/unmount gate. The component stays mounted across the landing-page phases.

---

## 5. State storage

| Storage | Key | Purpose | Lifetime |
|---|---|---|---|
| `sessionStorage` | `sapling_onboarding_pending` | Bridge between Google OAuth redirect and landing-page onboarding resumption | Single browser session; cleared on landing-page consume (`page.tsx:71`) |
| React state | `OnboardingFlow.formData` | Current answers | Lost on unmount or page navigation |
| React state (on landing page) | `activeStep`, `completed`, `onboardingPhase` | Step progression + animation state | Lost on unmount |
| (none) | draft persistence | — | ❌ Not persisted; mid-flow abort = lost work |

---

## 6. API calls

| Endpoint | When | Payload |
|---|---|---|
| `GET ${API_URL}/api/onboarding/courses?q=<query>` | Step 4 course search (debounced 200ms) | — |
| `POST ${API_URL}/api/onboarding/profile` | On step 5 completion (`onFinish`) | `{user_id, first_name, last_name, year, majors, minors, course_ids, learning_style}` — note snake_case |
| `GET ${API_URL}/api/auth/google` | Step 0 CTA (full-page redirect, not fetch) | — |

No optimistic updates, no retries. If `/api/onboarding/profile` fails, the error is `console.error`-only (`page.tsx:569-571`) and the user is taken to `/dashboard` regardless.

---

## 7. Interactive UI patterns

| Pattern | Implementation | File:line |
|---|---|---|
| Escape-to-close | `window.addEventListener('keydown', ... key === 'Escape' ...)` | `OnboardingFlow.tsx:142-154` |
| Custom dropdown (Year) | `button` + conditional `div role="listbox"` with `role="option"` children, `aria-selected`; onBlur with 150ms delay to allow onMouseDown | `OnboardingFlow.tsx:442-500` |
| Autocomplete with tag-pills (Majors/Minors/Courses) | Inline search input + absolute-positioned suggestion panel; pills with X-remove | `OnboardingFlow.tsx:510-591`, `595-663` |
| Debounced server search (Courses) | `setTimeout(..., 200)` cleared on each keystroke, stored in `courseDebounceRef` | `OnboardingFlow.tsx:234-250` |
| Animated step card entrance | `key={activeStep}` on the content `div` + `@keyframes ob-card-in` CSS | `OnboardingFlow.tsx:378` |
| Segmented progress bar | Math-based segment widths with a filled-width overlay | `OnboardingFlow.tsx:331-357` |
| Body scroll-lock | `document.body.style.overflow = 'hidden'` while `onboardingPhase !== 'idle'` | `src/app/page.tsx:99-101` |

---

## 8. Accessibility notes

- The year picker and autocomplete panels use `role="listbox"` / `role="option"` / `aria-selected` / `aria-label`. Keyboard handling exists (`handleOptionKeyDown` — Enter/Space activate). ✅
- The step card uses `h3` for headings. No `aria-live` for step-change announcements — a screen-reader user may not hear that the step changed. Add `aria-live="polite"` on the card container or announce the new step label in the rebuild.
- The X close button has `<X />` icon but no `aria-label`. Add `aria-label="Close onboarding"`.
- Google-button SVG lacks `aria-hidden`. On step 0 there's `<svg>` without accessibility attributes.
- Tab order through the form is natural. Autofocus is applied to the first input of each step (`autoFocus` attribute).
- Pills with Remove buttons use `<button>` elements so they are keyboard-reachable. ✅

---

## 9. Components involved

| Component | File | Role |
|---|---|---|
| `OnboardingFlow` | `src/components/OnboardingFlow.tsx` | The entire six-step form |
| Landing page | `src/app/page.tsx` | Hosts the flow; owns `activeStep`/`completed`/`onboardingPhase` + outro animation |

Nothing else — no nested components, no toasts, no modals layered on top.

---

## 10. Edge cases

1. **Silent POST failure.** `POST /api/onboarding/profile` errors only `console.error` (`page.tsx:569-571`). User proceeds to `/dashboard` thinking they're set up, but their profile was never saved. Add surfaced error + retry.
2. **Mid-flow abort.** No draft persistence. Closing and re-opening onboarding restarts the form. Persist `formData` to `localStorage` keyed by `userId`.
3. **Hardcoded BU affiliation.** `school` is pre-filled "Boston University" in state and cannot be changed. `BU_MAJORS`/`BU_MINORS` are hardcoded. A multi-school rollout needs these to come from the backend.
4. **No back-button from step 0 to marketing.** Once onboarding activates, `document.body.style.overflow = 'hidden'`. Only Escape or the X button exits.
5. **Session-storage flag leaks across users on a shared browser.** See `features/auth.md` §2.3 edge cases / Q11.
6. **Silent course-search failure.** If `fetch /api/onboarding/courses` throws, `setCourseSuggestions([])` runs but the user sees no error. They may type harder.

---

## 11. Things to preserve in the rebuild

- **Six-step structure.** Name → School → Academics (majors+minors) → Courses → Learning Style. These six inputs are what the backend expects (`POST /api/onboarding/profile` payload — see §6).
- **Debounced backend course search** (200ms).
- **Typeahead pills** for majors, minors, and courses — with X-to-remove.
- **Custom dropdown** for class-year with keyboard support and ARIA roles — don't regress to a native `<select>` unless you also fit it into the visual system.
- **"Continue" button gated by `canAdvance()`** — no free-walking through incomplete steps.
- **Escape-to-close and the X button** — but ensure the user can resume (solve the draft-persistence gap).
- **`sessionStorage.sapling_onboarding_pending` bridge** — otherwise Google's redirect always goes to `/dashboard` and onboarding never runs on first sign-in.
- **Outro animation beat** from `handleOnboardingComplete` is a 4-second polished moment. If you want to keep the "welcome animation", 4s is probably too long for a rebuild — consider 1.5s.
- **Learning-style IDs** (`visual`/`reading`/`auditory`/`hands-on`/`mixed`) — this vocabulary is baked into the backend prompt system (see `CLAUDE.md` §Architecture Notes). Don't rename without coordinating.

## 12. Things to rework / decisions for the rebuild

- Move onboarding to a real route (`/onboarding`) and gate it in `middleware.ts` so unfinished users are *forced* there instead of being ejected onto an overlay over the marketing site.
- Source majors / minors / school list from the backend (`GET /api/onboarding/schools/:school/academics` or similar) so multi-school support is configuration rather than a code change.
- Persist `formData` to `localStorage.sapling_onboarding_draft` keyed by `userId`.
- Surface `POST /api/onboarding/profile` errors with a Toast + retry button.
- Decouple form state from the landing page's 3D canvas entirely — the `activeStep`/`completed` coupling is an artifact of that decision and will disappear with the landing-page refresh.

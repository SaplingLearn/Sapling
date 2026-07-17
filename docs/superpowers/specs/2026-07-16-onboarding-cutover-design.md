# Onboarding cutover: `/onboarding` becomes the signup flow, `OnboardingFlow.tsx` deleted (#292)

**Issue:** [#292 — frontend: delete dead OnboardingFlow.tsx](https://github.com/SaplingLearn/Sapling/issues/292)

## Problem

Issue #292 was filed as "delete dead code," but the premise is stale. The tracker
(`docs/superpowers/followups/2026-06-30-token-unification-followups.md`, corrected 2026-07-07)
re-scoped it: `components/OnboardingFlow.tsx` (36 KB, old landing DNA) is **live** — it is the
signup flow rendered by the active landing route `app/(public)/page.tsx` behind an elaborate
phase machine (canvas zoom, intro/outro text, scroll lock). Deleting it outright breaks the build
and the signup path. Scope is therefore **unwire, then delete**.

Meanwhile a second, complete onboarding already exists at `/onboarding`
(`components/screens/Onboarding.tsx`): 6-step card flow in the app's design language, localStorage
draft persistence, auth guard, same `submitOnboardingProfile` payload, `/dashboard` redirect with a
toast — but nothing navigates to it. This change makes it the one onboarding.

## Design

### Route/entry changes

| Entry point | Before | After |
|---|---|---|
| Landing "Get Started" (nav + final CTA), authenticated | in-page phase machine → `OnboardingFlow` | `router.push('/onboarding')` |
| Landing "Get Started", unauthenticated | set `sapling_onboarding_pending` + open SignInModal; flow resumes on landing after sign-in | open SignInModal (modal routes after sign-in) |
| `SignInModal` success, onboarding incomplete | set `sapling_onboarding_pending`, stay on `/` | `router.replace('/onboarding')` |
| `auth/callback`, onboarding incomplete | set `sapling_onboarding_pending`, `router.replace('/')` | `router.replace('/onboarding')` |

The `sapling_onboarding_pending` sessionStorage flag is removed everywhere, including its sign-out
cleanup in `UserContext.tsx`.

### Landing page (`app/(public)/page.tsx`) strip-down

Remove, keeping the idle canvas graph and all marketing content byte-identical in behavior:

- Phase state: `onboardingPhase`, `introText`, `outroText`, `outroOverlay`, `activeStep`, `completed`.
- Onboarding refs (`onboardingTimeoutRef`, `introTimeoutsRef`, `canvasZoomRef`, `zoomActiveRef`,
  `zoomOutroRef`, `onboardingPhaseRef`, `clusterProgressRef`, `clusterActiveStepRef`,
  `clusterCompletedRef`, `obNodesRef`, `obInitStepsRef`, `obDoneStepsRef`) and their sync effects.
- The pending-resume effect, onboarding scroll lock, timeout-cleanup effect.
- `startOnboarding` phase choreography, `closeOnboarding`, `handleOnboardingComplete`.
- Canvas loop: OB-node spawn/draw blocks, `OB_STEP_*` constants, zoom/cluster-fade machinery
  (`zoom` pinned to 1, link/fog alpha no longer modulated by `clusterProgress`).
- JSX: intro title reveal, outro "Welcome to Sapling," white outro overlay, `<OnboardingFlow>`
  render, and every `onboardingPhase !== 'idle'` conditional opacity/pointer-events style
  (nav, floating cards, hero content, scroll indicator, features wrapper).
- Now-unused imports: `OnboardingFlow`, `submitOnboardingProfile`, `OnboardingProfilePayload`,
  `userId` from `useUser`.

### Deletions

- `frontend/src/components/OnboardingFlow.tsx` (the whole point).
- `globals.css` OnboardingFlow-only styles, each verified unreferenced tree-wide first:
  `ob-pulse-outer` / `ob-pulse-inner` / `ob-card-in` keyframes (defined twice),
  `.ob-pulse-outer` / `.ob-pulse-inner` / `.ob-card-in` classes, `.landing-modal-panel`
  (duplicated), `.sapling-upload-spinner`.

### Docs

- Tick P2-I in `docs/superpowers/followups/2026-06-30-token-unification-followups.md` with a note.
- Fix the stale `frontend/Dockerfile` comment naming OnboardingFlow.

## Behavior changes (intended)

- Signup happens on `/onboarding` (app-DNA card flow) instead of the landing canvas cinematic.
  The intro/outro choreography is gone — that old-DNA presentation is what #292 targets.
- Submit-failure handling improves: the old flow logged and continued to `/dashboard` anyway;
  `/onboarding` toasts the error and preserves the draft.
- Escape/close on `/onboarding` signs out and returns to `/` (pre-existing `screens/Onboarding`
  behavior, unchanged).

## Error handling

No new error paths. Routing changes are client-side navigations; `screens/Onboarding` already
guards unauthenticated access (`router.replace('/')`).

## Testing

- `npm run build` — Next + TS catch any dangling import/reference.
- Frontend vitest suite.
- Backend `pytest` (untouched by this change; run per request to verify no regression anywhere).
- Tree-wide grep for `OnboardingFlow` and `sapling_onboarding_pending`: zero code references remain.

## Risks

- Overlaps open landing-redesign #344, but only deletes code the redesign would also delete.
- The landing canvas keeps rendering in idle mode; the strip-down must not disturb the background
  node/cluster animation (verified by build + eyeballing the landing page if run).

# Token Unification — Deferred Follow-ups

**Phase 1 (token layer + `(public)` group) landed** on branch `refactor/token-unification`.
The frontend now runs on **one** token system: the warm app palette is canonical in `:root`,
the pre-auth surface adds a small named **marketing layer** (`--display-hero`, `--surface-hero`,
`--brand-glow`, `--bg-mesh`) via the `.public-surface` route-group layout, and the five competing
greens are collapsed to `--brand-forest` (+ bright + derived glow). Zero retired-token references
remain tree-wide.

These items consume the now-unified tokens and were **intentionally deferred** from Phase 1.
Each is its own plan / PR. Severity tags map to `docs/frontend-rhythm-audit.md`.

## Component re-skins (the visible "feels different" fixes)

- [ ] **[P0-B] Beta CTA button species.** Replace the rounded-full pill + infinite `beta-glow`
      animation with the app button language (rectangular, `--r-sm`, solid `--brand-forest`).
      Convert the perpetual glow into a single finite entrance using `--brand-glow`.
      Files: `app/(public)/page.tsx`, `globals.css` (`.beta-glow-btn`).
- [ ] **[P1-E] Extract one hero-card primitive from `--surface-hero`.** Replace the duplicated
      inline 24px warm-gradient box in the beta modal (`app/(public)/page.tsx`) and
      `components/SignInModal.tsx` with a single shared component backed by `--surface-hero` /
      `--surface-hero-shadow`.
- [ ] **[P1-C] Re-home onboarding** (`components/screens/Onboarding.tsx`) into the app's
      layout/spacing/type — `--pad-*` spacing, the shell type scale — instead of a centered
      card floating in a radial-gradient void.
- [ ] **[P1-D] Re-home `pending`** (`app/pending/page.tsx`) onto app surfaces (`.card`) and add a
      brief "you're in ✓" confirmation beat so the beta→pending transition isn't glow→silence.
- [ ] **[P2-G] Normalize pre-auth motion** to one or two finite, purposeful moments
      (mesh blobs `sapling-blob`, `landing-card-float`, shimmer are currently infinite loops).
- [ ] **[P2-I] Delete dead code** `components/OnboardingFlow.tsx` (36 KB, unused old-DNA onboarding
      not imported by the active route).

## Directory / structural hygiene

- [ ] **Flatten `components/`** (~50 files in one folder) into responsibility-grouped subfolders;
      co-locate the pre-auth components (`HowItWorks`, `SignInModal`, landing sections) under
      `components/marketing/`.
- [ ] **Optional cosmetic:** the marketing scope is currently expressed as two classes
      (`.public-surface` for tokens, `.landing-page` for the landing's mesh visual + `.landing-*`
      utilities). Consider renaming `.landing-page` → a clearer name now that it's layout-hosted,
      and/or folding the two into one once the component re-skins land.

## References
- Audit + visual companion: `docs/frontend-rhythm-audit.md` (+ `.html`)
- Design spec: `docs/superpowers/specs/2026-06-30-token-unification-design.md`
- Implementation plan: `docs/superpowers/plans/2026-06-30-token-unification.md`

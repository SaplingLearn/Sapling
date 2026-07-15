# Design Spec — Frontend Token Unification (Phase 1: the foundation)

**Date:** 2026-06-30
**Status:** Approved design, pending spec review → implementation plan
**Companion audit:** `docs/frontend-rhythm-audit.md` (+ `.html`)
**Scope owner decisions:** shared base + marketing layer · token layer + green collapse · add `(public)` route group · alias-then-migrate

---

## 1. Problem

The frontend runs **two parallel design systems** in one stylesheet (`frontend/src/app/globals.css`):

- **App shell (source of truth):** warm forest/ink editorial tokens in `:root`.
- **Pre-auth (`.landing-page` scope):** a cooler "main" palette that **re-declares the same semantic token names with different values**.

Because identical token names (`--border`, `--text`, `--text-muted`, `--shadow-*`, `--dur-fast`, `--dur-slow`, `--bg-panel`) resolve to **warm values in-app and cool values in pre-auth**, the same class renders as a different product on either side of the sign-in boundary. There is also a **duplicate namespace** (`--r-*` vs `--radius-*`, `--ease` vs `--ease-out`, `--dur` vs `--dur-base`) and **five greens** competing for "primary." This is documented tech debt (`globals.css:726–732`): *"to be revisited and consolidated… in a follow-up pass."* This spec is that pass.

## 2. Goals / Non-goals

**Goals (this plan):**
1. **One token layer.** No scope ever re-declares a core semantic token. Kill the same-name-different-value shadowing (the crux).
2. **A deliberate, additive marketing layer** so the public surface keeps a confident hero moment without flattening into the app — expressed as *new, named* tokens, never as redefinitions.
3. **Collapse the greens** to one canonical primary system.
4. **Give the marketing layer a structural home** via a `(public)` route group + layout, replacing the ad-hoc `.landing-page` class as the scoping mechanism.

**Non-goals (explicit — tracked follow-up, not this plan):**
- Component **shape/motion** re-skins: the beta CTA's rounded-full pill + infinite glow, de-duplicating the inline modal card, re-homing onboarding/pending, normalizing pre-auth motion. (Audit findings B, D, E, G.)
- Deleting dead code `OnboardingFlow.tsx` (audit I).
- Flattening the ~50-file `components/` directory (general hygiene).
- Dark mode, new visual design, or any change to the app-shell appearance.

> The token changes will make the pre-auth surface **warm up automatically** (it reads the tokens). Shapes/motion stay as-is until the follow-up. That is expected and acceptable for Phase 1.

## 3. Target architecture — a 3-layer token model

### Layer 1 · Core (`:root`) — single source of truth
The existing warm app tokens stay **exactly as they are** and become canonical:
`--ink-*`, `--brand-forest`, `--brand-forest-bright`, `--accent` (+variants), `--bg`/`--bg-panel`/`--bg-subtle`/`--bg-soft`/`--bg-input`/`--bg-inset`/`--bg-topbar`, `--border`/`--border-strong`, `--text`/`--text-dim`/`--text-muted`, `--shadow-sm/md/lg` (green-tinted), `--r-xs…--r-xl`, `--ease`, `--dur`/`--dur-fast`/`--dur-slow`, `--pad-*`, `--row-h`, the status/state/category/grade/rarity palettes.

**Invariant:** after this change, **no selector other than `:root` may assign these names.** A lint note/comment enforces it socially; CI enforcement is out of scope.

### Layer 2 · Marketing layer — additive, named, opt-in
A **small set of new tokens** (not redefinitions) used only by the public surface, applied via the `(public)` layout (see §5). Initial set:

| New token | Purpose | Source value |
|---|---|---|
| `--bg-mesh` | pre-auth ambient mesh background | keep `#f0f4f2` (5 real consumers) |
| `--display-hero` | the big marketing Playfair scale/weight | tokenize the current inline 44–48px / 700–800 |
| `--surface-hero` | the richer hero card (one definition; beta + sign-in share it) | the warm gradient, re-tinted to a **green** shadow `rgba(19,38,16,…)` to match core |
| `--brand-glow` | derived accent glow for the (future, finite) button entrance | `color-mix(in oklch, var(--brand-forest) …)` — replaces orphan `rgba(74,158,92)` |

The marketing layer **may not** redefine any Layer-1 name. If the public surface wants a different value for something structural, that is a signal the design — not the token — needs revisiting.

### Layer 3 · Retired
Delete or re-point (consumer counts grep-verified 2026-06-30):

| Token | Refs | Action |
|---|---|---|
| `--brand-success`, `--brand-progress`, `--brand-struggle`, `--brand-text1/2`-as-brand, `--bg-sidebar`, `--bg-space`, `--bg-glass` | 0 (except text1/2) | **delete** the dead ones outright |
| `--brand-primary` | 2 (`.glass-input:focus`, `--rarity-uncommon`) | re-point both to `var(--brand-forest)`, delete token |
| `--brand-teal` | 1 (`--rarity-rare`) | inline concrete `#2b8c96` into `--rarity-rare`, delete brand token |
| `--brand-text1` | 11 | migrate consumers → `var(--text)` (`#1a1a1a`→warm `#1a1814`) |
| `--brand-text2` | 34 | migrate consumers → `var(--text-dim)` / `--text-muted` (the largest Phase-2 chunk) |
| `--radius-sm/md/lg/full` | `--radius-lg`,`--radius-sm` only | alias → `--r-*`, migrate refs, delete |
| `--dur-base` | 0 | delete |
| `--ease-out`, `--ease-in-out` | 5 | **default:** alias → `--ease` and migrate the 5 refs; only promote to a named Layer-2 token if a reviewer confirms a distinct curve is intentional |
| `.landing-page` re-declarations of `--border`,`--text*`,`--shadow-*`,`--bg-panel`,`--bg-subtle`,`--accent*`,`--border*` | — | **delete** so they inherit `:root` |

**Two declaration sites.** The cool palette is declared in **both** `:root` (the "Landing-page brand tokens" block, `globals.css:95–105`) **and** inside `.landing-page` (`733–799`). Both sites get cleaned: delete the dead `--brand-*` duplicates in each; relocate `--bg-mesh` from `:root` into the Layer-2 marketing layer; the harmless `--font-inter: var(--font-sans)` alias may stay.

## 4. Green collapse (audit finding A)

Canonical primary green system after this work:
- `--brand-forest #1B6C42` — primary (unchanged; `.btn--primary`, 52 refs)
- `--brand-forest-bright #2D8F5C` — bright/hover (unchanged)
- `--brand-glow` — derived from `--brand-forest` (replaces the orphan glow green)

`--accent #8a9a5b` (sage) **stays** — it is a *different role* (highlights/focus), not a primary green. Its role boundary gets a one-line comment so it isn't "consolidated" by mistake. `--brand-primary`/`--brand-success` are removed per §3.

## 5. Directory change — `(public)` route group

Introduce `frontend/src/app/(public)/` with its own `layout.tsx` that applies the Layer-2 marketing tokens to its subtree.

**Moves (route groups are URL-transparent — paths unchanged):**
- `app/page.tsx` (landing) → `app/(public)/page.tsx`
- `app/about` → `app/(public)/about`
- `app/careers` → `app/(public)/careers`
- `app/privacy` → `app/(public)/privacy`
- `app/terms` → `app/(public)/terms`

**Stay put:** `onboarding`, `pending` (transitional, already app-token; their re-home is the deferred follow-up), `auth`, `api`, and the `(shell)` group.

`(public)/layout.tsx` becomes the scoping mechanism (carries `--bg-mesh`, `--display-hero`, `--surface-hero`, `--brand-glow` and the mesh background). The `.landing-page` class is retired as a *token* host; if its `.landing-*` utility classes are still needed for component styling, they get re-scoped under the `(public)` layout wrapper or kept as plain utility classes that now read canonical tokens.

## 6. Migration mechanics — alias-then-migrate

**Phase 1 — alias (small, reviewable, mostly deletions):**
1. Delete the `.landing-page` re-declarations of core tokens (§3 bottom row) → pre-auth inherits warm `:root` values immediately.
2. Alias the duplicate namespace: `--radius-sm: var(--r-sm)` etc., `--brand-primary: var(--brand-forest)`, `--dur-base`/`--ease-out` as decided.
3. **Checkpoint:** load landing / beta modal / sign-in / about — confirm they render warm and intact. Capture before/after screenshots.

**Phase 2 — migrate references & finalize:**
4. Rewrite `.landing-*` class internals + pre-auth inline styles to use canonical token names (the `--brand-text1/2` → `--text`/`--text-dim` swap is the bulk).
5. Stand up `(public)/layout.tsx` + the Layer-2 marketing tokens; move the routes (§5).
6. Re-point the finite Layer-3 consumers (`.glass-input:focus`, rarity tokens).
7. Delete all aliases + dead declarations.
8. **Checkpoint:** full pre-auth + dashboard visual pass.

The exhaustive, grep-verified consumer list per token is produced by the **implementation plan** (writing-plans step), not here.

## 7. Verification

No visual-regression harness exists in the repo, so verification is a **manual visual checkpoint** at each phase boundary:
- Screenshot **before & after** via browser tooling: landing, beta modal, sign-in modal, `about`, `careers`, `onboarding`, `pending`, dashboard.
- Confirm: pre-auth reads warm and consistent with the dashboard; no token resolves to `unset`/empty (no missing-var fallbacks); URLs unchanged after the route moves; `npm run build` / typecheck pass.
- The dashboard/app-shell appearance must be **byte-identical** before/after (Layer 1 is untouched) — a good regression anchor.

## 8. Risks & mitigations

| Risk | Mitigation |
|---|---|
| Deleting a `.landing-page` token that *was* doing real work → broken pre-auth color | Phase-1 checkpoint screenshots before deleting aliases; aliases first, deletions last |
| `--brand-text2` (34 refs) migration misses a consumer → stray cool slate | grep-verified list in the plan; final Phase-2 visual pass |
| Route-group move breaks an import path or a `Link` | route groups don't change URLs; fix relative imports during the move; build check |
| Frontend CI already red repo-wide (pre-existing) | verify **locally**; don't attribute pre-existing CI failures to this change; note baseline state in the PR |
| Scope creep into component re-skins | non-goals (§2) are explicit; Phase 2 renames tokens only, never shapes/motion |

## 9. Out of scope → follow-up plan (tracked)

A second plan covers the **consumer-side** cleanups that the unified tokens enable: beta CTA → app button language + finite glow (B), de-dup modal card into `--surface-hero` component (E), re-home onboarding/pending into app layout/spacing + add a "you're in" confirmation (C, D), normalize pre-auth motion (G), delete `OnboardingFlow.tsx` (I), and (separately) the `components/` directory hygiene.

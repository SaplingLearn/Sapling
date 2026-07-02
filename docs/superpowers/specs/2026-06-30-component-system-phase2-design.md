# Design Spec — Shared UI Primitives + Green Consolidation (Phase 2)

**Date:** 2026-06-30
**Status:** Approved design, pending spec review → implementation plan
**Companion audit:** `docs/frontend-component-consistency-audit.md`
**Builds on:** Phase 1 token unification (branch `refactor/token-unification`, PR #286)
**User decisions:** sharp 6px primary buttons (+ dedicated `lg` hero size) · retire sage `--accent` toward the forest family · merge status greens into one `--positive` · scope = primitives + high-impact surfaces (long tail incremental)

---

## 1. Problem

Phase 1 unified the *token values*. This phase fixes the *component layer* the audit found underneath:

- **No shared primitives** → 5 distinct button shapes and **18+** pill/badge implementations; every surface reinvents them.
- **Greens split by accident, not role** → 5 active greens; sage `--accent` (125×) competes with the forest brand; `--grade-a` (#3e8030) and `--brand-forest` (#1B6C42) are 9 hex apart and indistinguishable; `#1a5c2a` isn't even a token.

## 2. Goals / Non-goals

**Goals:**
1. One **`<Button>`** primitive — variants + sizes, **6px radius always**, a dedicated **`lg` hero size** (so de-pilled landing CTAs keep presence: ~15–16px text, 600 weight, generous padding).
2. One **`<Toggle>`** segmented control (replaces the 3 ad-hoc toggles).
3. **`<Chip>`** + **`<Badge>`** primitives (collapse the 18 pill/badge implementations).
4. **Green-by-role consolidation** (token-level): forest = brand/action; one `--positive` = status (mastery + grade-A); `--accent` re-homed into the forest family; tokenize `#1a5c2a`.
5. Migrate the **high-impact surfaces** to the new primitives; leave the long tail on the still-working `.btn` CSS for incremental migration.

**Non-goals (deferred / incremental):**
- Migrating all ~211 `.btn` call-sites and every one of the 18 pill sites in this pass.
- Re-skinning onboarding/pending, the beta glow, modal de-dup (those remain follow-ups #287–#293).
- Any change to the app-shell *layout* or the Phase-1 token namespace.

## 3. The primitives

> All live under `frontend/src/components/ui/`. Each is a **thin wrapper over the existing `globals.css` classes** — the CSS stays the source of truth, the component enforces consistent usage. Un-migrated call-sites keep working.

### `<Button>` — `components/ui/Button.tsx`
```
type ButtonProps = {
  variant?: 'primary' | 'secondary' | 'ghost' | 'danger';  // default 'secondary'
  size?: 'sm' | 'md' | 'lg';                                // default 'md'
  // ...plus native button props, asChild?/href? optional for link-buttons
}
```
- Maps to classes: `btn` + `btn--{variant}` + `btn--{size}`. `secondary` = base `.btn` (no modifier).
- **Radius 6px for every variant/size.** Pills are never a Button.
- New CSS needed: `.btn--lg` (the hero size — see §4) and `.btn--secondary` alias (= base, for explicitness). `.btn--primary/ghost/danger/sm` already exist.

### `<Toggle>` — `components/ui/Toggle.tsx`
- A segmented control: `options: {value,label}[]`, `value`, `onChange`. Pill container (`--r-full`), active segment filled forest. One implementation to replace `Learn.tsx:473`, `Learn.tsx:562`, `ModelToggle.tsx`.

### `<Chip>` — `components/ui/Chip.tsx`
- `variant?: 'neutral' | 'accent' | 'positive' | 'warn' | 'err' | 'info'`, optional leading dot/icon. Maps to the `.chip` + `.chip--*` classes. Replaces inline status pills, term pills, room-code chips, filter chips.

### `<Badge>` — `components/ui/Badge.tsx`
- For rarity / role / grade. Takes a semantic `tone` (or rarity tier) and centralizes the `color-mix` logic currently duplicated in `RoleBadge.tsx`, `TitleFlair.tsx`, and the Achievements inline badges.

## 4. Token changes (`globals.css`)

| Token | Now | After | Notes |
|---|---|---|---|
| `--accent` | `#8a9a5b` (sage) | a **brighter forest** (start: `#2D8F5C` = `--brand-forest-bright`; tune in build) | re-homes 125 usages into forest; brighter than `--brand-forest` so highlights/focus ≠ primary buttons |
| `--accent-soft` | `--sap-50` (`#f1f6ee`) | unchanged (already a forest tint) | soft highlight bg |
| `--accent-border` | `--sap-200` | unchanged | already forest-family |
| `--state-mastery` `#4a7d5c` + `--grade-a`/`--c-sage` `#3e8030` | two near-forest greens | **`--positive`** (start: `#3a7d4e`; tune) — one status green | mastery + grade-A render identically; a mid-green, distinct from both action-forest (darker) and accent (brighter) |

**Three distinct forest-family greens by role:** `--brand-forest #1B6C42` (primary action, darkest) · `--accent #2D8F5C` (highlight/focus, brightest) · `--positive #3a7d4e` (status, mid). One hue family, three legible weights.
| `#1a5c2a` (hard-coded ×12) | not a token | `--brand-forest` (or add `--brand-forest-deep`) | landing logo / TopNav |

`.btn--lg`: `padding: 13px 26px; font-size: 15px; font-weight: 600; border-radius: var(--r-sm);` (final values tuned against the hero CTA visually).

> Exact green hexes are **tuned during the build with a side-by-side visual check** (the audit + comparison page give the reference). The spec fixes the *roles and consolidation*, not the final pixel of each hue.

## 5. High-impact migration list (this phase)

- **Landing CTAs** (`app/(public)/page.tsx:705, 781, 911`) → `<Button variant="primary" size="lg">`, sharp 6px (de-pill).
- **Gradebook modal buttons** (`LetterScaleEditor:107`, `SyllabusUploadFlow:220`, `AssignmentModal:346`, `EditWeightsModal:268`, `Gradebook/Course:186`) → `<Button>` (kills the hard-coded `borderRadius:6`).
- **Study flashcard ratings** (`Study.tsx:593`) → `<Button>` family (off the 10px).
- **The 3 toggles** (`Learn.tsx:473`, `Learn.tsx:562`, `ModelToggle.tsx`) → `<Toggle>`.
- **Worst pills** on gradebook/social/achievements → `<Chip>`/`<Badge>` (term pills, filter chips, rarity badges, room-code chip).

## 6. Verification

Same as Phase 1 — no component test harness for visuals, so: `npm run build` + `npx eslint .` (0 errors) + `npm run test` (vitest 68 passing) + **manual before/after screenshots** of gradebook, social, achievements, landing, and a couple of in-app screens (dashboard unchanged as anchor). Each green-token change is eyeballed against the comparison reference.

## 7. Risks

| Risk | Mitigation |
|---|---|
| `--accent` re-point makes the UI monochrome-forest / loses hierarchy | choose a **brighter/lighter** forest for accent so highlights still separate from primary; visual review on dashboard + social |
| `lg` hero size looks wrong after de-pilling | tune padding/size against the landing CTA live before committing |
| Component migration breaks a call-site’s custom props | migrate incrementally, build + screenshot each surface; `.btn` CSS keeps working for un-migrated sites |
| eslint suppressions keyed on moved/edited files | run `npx eslint .` per surface; re-home suppressions if a file’s grandfathered errors resurface (Phase-1 lesson) |
| Scope creep into the long tail | §2 non-goals explicit; only the §5 list is in-scope |

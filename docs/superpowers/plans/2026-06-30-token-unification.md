# Frontend Token Unification — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Collapse the two parallel CSS design systems into one canonical warm token layer plus a small additive "marketing layer," so the same class name renders identically on both sides of the sign-in boundary.

**Architecture:** The warm app tokens in `:root` (`globals.css`) become the single source of truth. The pre-auth surface stops re-declaring core token names and instead gets a small set of *new, additive* marketing tokens, scoped through a new `(public)` route-group layout. Migration is **alias-then-migrate**: alias the old names to canonical first (instant warm consistency, reviewable diff), migrate references, then delete the aliases.

**Tech Stack:** Next.js (App Router, route groups), Tailwind v4 (`@import "tailwindcss"`), plain CSS custom properties in `frontend/src/app/globals.css`. No test framework covers CSS tokens — verification is **grep assertions + `npm run build`/typecheck + manual before/after screenshots** (the dashboard must stay byte-identical as the regression anchor).

**Spec:** `docs/superpowers/specs/2026-06-30-token-unification-design.md`

## Global Constraints

- **No selector other than `:root` may assign a Layer-1 core token** (`--border`, `--text*`, `--shadow-*`, `--bg-panel`, `--bg-subtle`, `--accent*`, `--r-*`, `--ease`, `--dur*`, `--brand-forest*`). The marketing layer may only *add* new names.
- **App-shell appearance must not change.** `:root` tokens are untouched; the dashboard is the regression anchor and must be byte-identical before/after.
- **Route groups are URL-transparent** — `/`, `/about`, `/careers`, `/privacy`, `/terms` must resolve unchanged after the moves.
- **Commit convention:** end every commit message with `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`.
- **Scope is Phase 1 (foundation) only.** No component shape/motion changes (beta pill, infinite glow, modal-card de-dup, onboarding/pending re-home), no dead-code deletion, no `components/` flattening — those are filed as follow-ups in the final task.
- **Fish shell:** quote grep globs (`--include='*.css'`), or the shell expands them.

---

## File Structure

| File | Responsibility | Touched by |
|---|---|---|
| `frontend/src/app/globals.css` | the entire token layer — all edits to `:root`, `.landing-page`, rarity, `.glass-input` | Tasks 2, 3, 7 (sequential — single file) |
| `frontend/src/app/(public)/layout.tsx` | **new** — wraps the public subtree, applies the marketing-layer scope | Task 4 |
| `frontend/src/app/(public)/{page,about,careers,privacy,terms}/…` | **moved** from `app/` (content unchanged by the move) | Task 4 (move), Task 6 (content migration) |
| `frontend/src/components/HowItWorks.tsx`, `SignInModal.tsx` | pre-auth components — retired-token → canonical swaps | Task 6 (parallel) |
| `docs/superpowers/followups/2026-06-30-token-unification-followups.md` (or GitHub issues) | the deferred-work tracker | Task 8 |

## Parallelization Map (subagent-driven)

```
Task 1  baseline screenshots          ── sequential (setup)
Task 2  strip + alias (globals.css)   ── sequential ┐ single file → one agent, in order
Task 3  marketing layer + greens      ── sequential ┘
Task 4  (public) group + route moves  ── sequential (structural; depends on 2–3)
Task 5  verify aliased build is warm  ── sequential checkpoint (barrier)
Task 6  consumer migration            ── ▶▶ PARALLEL: one subagent per file (7 independent files)
Task 7  delete aliases + dead tokens  ── sequential barrier (only after ALL of Task 6 lands)
Task 8  verify + file follow-ups      ── sequential (close-out)
```

Only **Task 6** fans out. Per the project convention (parallel implementer dispatch on independent files; sequential only on real conflict), the seven pre-auth files in Task 6 have no shared state and are dispatched concurrently. Everything else is serialized because it edits the single `globals.css` or depends on the prior structural change.

---

## Task 1: Baseline screenshots (regression anchor)

**Files:** none modified. Output to `/tmp/claude-*/scratchpad/token-baseline/`.

**Interfaces:**
- Produces: a set of before-screenshots used by Tasks 5, 7, 8 for visual diffing.

- [ ] **Step 1: Create a branch off main**

```bash
cd /home/andresl/Projects/sapling
git fetch origin
git switch -c refactor/token-unification origin/main
```

- [ ] **Step 2: Start the frontend dev server (background)**

```bash
cd /home/andresl/Projects/sapling/frontend && npm run dev
```
Expected: server on `http://localhost:3000` (or the configured port; note it).

- [ ] **Step 3: Capture baseline screenshots**

Using the browser tools, navigate to and screenshot each surface, saving to disk:
`/` (landing), the beta-signup modal, the sign-in modal, `/about`, `/careers`, `/privacy`, `/terms`, `/onboarding`, `/pending`, `/dashboard`.
Save as `token-baseline/<surface>.png`.

- [ ] **Step 4: Commit a marker (no code yet)**

No code changed; record the branch point.
```bash
git commit --allow-empty -m "chore: baseline before token unification

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: Strip core-token shadowing + add aliases (`globals.css`)

**Files:**
- Modify: `frontend/src/app/globals.css` — the `:root` duplicate brand block (`95–105`), the `.landing-page` token block (`733–799`).

**Interfaces:**
- Produces: pre-auth renders with warm `:root` values; duplicate-namespace tokens (`--radius-*`, `--ease-out`, `--brand-primary`) resolve to canonical via alias.

- [ ] **Step 1: Alias the consumed `:root` cool tokens to canonical; delete only the 0-ref ones**

In the `:root` block (`globals.css:95–105`), the cool palette is declared here AND re-declared in `.landing-page`. Tokens with live consumers must be **aliased** (not deleted) so nothing renders uncolored before Task 6 migrates the references. Replace the seven lines (`97–103`) with:
```css
  /* Temporary aliases → canonical; consumers migrated in Task 6, aliases removed in Task 7. */
  --brand-primary: var(--brand-forest);   /* 2 consumers (glass-input, rarity) */
  --brand-text1:   var(--text);            /* 11 consumers (marketing copy) */
  --brand-text2:   var(--text-dim);        /* 34 consumers (marketing copy) */
  --brand-teal:    #2b8c96;                /* 1 consumer (--rarity-rare); re-pointed in Task 3 */
```
That deletes `--brand-success`, `--brand-progress`, `--brand-struggle` (0 refs — safe). Keep `--bg-mesh: #f0f4f2;` and `--font-inter: var(--font-sans);` for now (relocated/cleaned later).

> **Why alias, not delete:** `--brand-text1/2` have 11+34 live consumers (migrated in Task 6). Deleting them now would render that text uncolored at the Task 5 checkpoint. Aliasing resolves them to warm values immediately, keeping every intermediate state correct.

- [ ] **Step 2: In `.landing-page` (`733–799`), delete every re-declaration of a Layer-1 core token**

Delete these lines from inside `.landing-page { … }` so the subtree inherits `:root`:
```css
  --bg-panel:     #f8fbf8;
  --bg-sidebar:   #dfe8df;
  --bg-topbar:    #dce6dc;
  --bg-input:     #f8fbf8;
  --bg-subtle:    #e9efe9;
  --bg-space:     var(--bg-mesh);
  --bg-glass:     rgba(255, 255, 255, 0.35);
  --accent:           #8a9a5b;
  --accent-hover:     #9aab6c;
  --accent-dim:       rgba(138, 154, 91, 0.08);
  --accent-border:    rgba(138, 154, 91, 0.3);
  --accent-active:    rgba(138, 154, 91, 0.7);
  --accent-glow:      rgba(138, 154, 91, 0.12);
  --text:               #111827;
  --text-primary:       #111827;
  --text-secondary:     #374151;
  --text-muted:         #4b5563;
  --text-dim:           #6b7280;
  --text-placeholder:   #9ca3af;
  --border:             rgba(107, 114, 128, 0.18);
  --border-light:       rgba(107, 114, 128, 0.10);
  --border-mid:         rgba(107, 114, 128, 0.25);
  --border-glass:       rgba(107, 114, 128, 0.15);
  --shadow-sm:   0 1px 3px rgba(15, 23, 42, 0.06), 0 1px 2px rgba(15, 23, 42, 0.04);
  --shadow-md:   0 4px 12px rgba(15, 23, 42, 0.08), 0 2px 4px rgba(15, 23, 42, 0.04);
  --shadow-lg:   0 12px 32px rgba(15, 23, 42, 0.10), 0 4px 8px rgba(15, 23, 42, 0.06);
```
Also delete the cool brand re-declarations inside `.landing-page` (`--brand-primary … --bg-mesh`, `738–742`). **Keep** for now: `--radius-*`, `--ease-out`, `--ease-in-out`, `--dur-fast`, `--dur-base`, `--dur-slow`, and the `color`/`font-family`/layout properties at the bottom of the block (`790–799`).

- [ ] **Step 3: Convert the kept duplicate-namespace tokens to aliases**

Replace the `.landing-page` radius/ease/dur block (`779–789`) with aliases to canonical:
```css
  /* Aliases → canonical app tokens (temporary; removed in Task 7). */
  --radius-sm:   var(--r-sm);
  --radius-md:   var(--r-md);
  --radius-lg:   var(--r-lg);
  --radius-full: var(--r-full);
  --ease-out:    var(--ease);
  --ease-in-out: var(--ease);
  --dur-fast:    var(--dur-fast);
  --dur-base:    var(--dur);
  --dur-slow:    var(--dur-slow);
```
(`--dur-fast`/`--dur-slow` now inherit `:root`; the explicit lines may simply be deleted instead of self-aliased — either is fine. `--dur-base` aliases to `:root`'s `--dur`.)

- [ ] **Step 4: Verify the build compiles and no core token is double-declared**

```bash
cd /home/andresl/Projects/sapling/frontend
npm run build 2>&1 | tail -20
grep -n 'var(--bg-glass)\|var(--bg-space)\|var(--bg-sidebar)' src --include='*.tsx' -r
```
Expected: build succeeds; the grep prints nothing (those tokens had 0 consumers).

- [ ] **Step 5: Visual checkpoint**

Screenshot `/`, the beta modal, the sign-in modal. Expected: they now render **warm** (paper background, warm borders/text) instead of cool slate, with layout intact.

- [ ] **Step 6: Commit**

```bash
git add src/app/globals.css
git commit -m "refactor(css): stop pre-auth from shadowing core tokens; alias the duplicate namespace

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: Marketing layer + green collapse + consumer re-point (`globals.css`)

**Files:**
- Modify: `frontend/src/app/globals.css` — `.landing-page` block, rarity block (`693–705`), `.glass-input:focus` (`634–638`).

**Interfaces:**
- Consumes: the aliases from Task 2.
- Produces: `--bg-mesh`, `--display-hero`, `--surface-hero`, `--brand-glow` as additive marketing tokens scoped to `.landing-page`; rarity + glass-input no longer reference retired brand tokens.

- [ ] **Step 1: Add the additive marketing-layer tokens inside `.landing-page`**

At the top of the `.landing-page { … }` rule, add:
```css
  /* ── Marketing layer (Layer 2): additive only — never redefine a :root token. ── */
  --bg-mesh:       #f0f4f2;
  --display-hero:  clamp(2.5rem, 5vw, 3rem);      /* big Playfair marketing headings */
  --display-hero-weight: 700;
  --surface-hero:  linear-gradient(145deg, #d5e8d8 0%, #e8f0e3 45%, #f0ebe0 100%);
  --surface-hero-shadow: 0 20px 60px rgba(19, 38, 16, 0.12), inset 0 0 0 1px rgba(255,255,255,0.5);
  --brand-glow:    color-mix(in oklch, var(--brand-forest) 70%, white);
```
Then delete the now-orphaned `--bg-mesh` line from `:root` (`globals.css:104`).

- [ ] **Step 2: Re-point `.glass-input:focus` off the retired brand token**

`globals.css:634–638` — replace `--brand-primary`:
```css
.glass-input:focus {
  outline: none;
  border-color: var(--brand-forest);
  box-shadow: 0 0 0 2px rgba(27, 109, 66, 0.2);
}
```

- [ ] **Step 3: Re-point the rarity tokens off the retired brand tokens**

`globals.css:699` and `701` — inline concrete values so deleting `--brand-primary`/`--brand-teal` is safe:
```css
  --rarity-uncommon:     var(--brand-forest);
  --rarity-uncommon-bg:  rgba(46, 125, 82, 0.08);
  --rarity-rare:         #2b8c96;
```

- [ ] **Step 4: Add the green-role guard comment**

Above `--accent:` in `:root` (`globals.css:65`), add:
```css
  /* --accent (sage) is a distinct ROLE (highlights/focus), NOT a primary green.
     Do not consolidate into --brand-forest. */
```

- [ ] **Step 5: Verify no retired token is referenced from CSS anymore (except via the temporary aliases)**

```bash
cd /home/andresl/Projects/sapling/frontend
grep -rn 'var(--brand-teal)\|var(--brand-success)\|var(--brand-progress)\|var(--brand-struggle)' src --include='*.css'
npm run build 2>&1 | tail -5
```
Expected: the grep prints nothing; build succeeds.

- [ ] **Step 6: Commit**

```bash
git add src/app/globals.css
git commit -m "refactor(css): add additive marketing-layer tokens; collapse greens; re-point rarity + glass-input

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: Create the `(public)` route group + move routes

**Files:**
- Create: `frontend/src/app/(public)/layout.tsx`
- Move: `app/page.tsx`, `app/about/`, `app/careers/`, `app/privacy/`, `app/terms/` → under `app/(public)/`
- Modify: the moved landing `page.tsx` (drop its own `.landing-page` wrapper to avoid double-wrapping).

**Interfaces:**
- Consumes: the `.landing-page` marketing scope from Task 3.
- Produces: every public route renders inside the marketing layer via the layout; URLs unchanged.

- [ ] **Step 1: Create the `(public)` layout that hosts the marketing scope**

Create `frontend/src/app/(public)/layout.tsx`:
```tsx
import React from "react";

// Wraps the public/pre-auth surface so the marketing-layer tokens
// (defined under .landing-page in globals.css) apply to the whole subtree.
export default function PublicLayout({ children }: { children: React.ReactNode }) {
  return <div className="landing-page">{children}</div>;
}
```

- [ ] **Step 2: Move the routes with `git mv` (preserves history; URLs unchanged)**

```bash
cd /home/andresl/Projects/sapling/frontend/src/app
mkdir -p "(public)"
git mv page.tsx "(public)/page.tsx"
git mv about "(public)/about"
git mv careers "(public)/careers"
git mv privacy "(public)/privacy"
git mv terms "(public)/terms"
```

- [ ] **Step 3: Remove the now-redundant inner `.landing-page` wrapper from the landing page**

In `(public)/page.tsx`, the top-level element currently applies `className="landing-page"` (or wraps in a div that does). Remove that wrapper class/div — the layout now provides it. Keep all inner content. Verify there is exactly one `.landing-page` ancestor.

- [ ] **Step 4: Verify all public URLs still resolve**

```bash
cd /home/andresl/Projects/sapling/frontend
npm run build 2>&1 | tail -20
```
Then with the dev server, load `/`, `/about`, `/careers`, `/privacy`, `/terms` — all render (200, correct content), now on the warm marketing background.

- [ ] **Step 5: Commit**

```bash
cd /home/andresl/Projects/sapling
git add frontend/src/app
git commit -m "refactor(routing): add (public) route group + layout as the marketing-layer host

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 5: Checkpoint — aliased build is warm and intact (barrier)

**Files:** none.

**Interfaces:**
- Consumes: Tasks 2–4.
- Produces: go/no-go gate before the parallel consumer migration.

- [ ] **Step 1: Full pre-auth screenshot pass**

Screenshot `/`, beta modal, sign-in modal, `/about`, `/careers`, `/privacy`, `/terms`. Compare to `token-baseline/`.
Expected: same layout/typography; **warmer** palette (paper bg, warm borders, warm text). No element is invisible or unstyled.

- [ ] **Step 2: Confirm the dashboard is unchanged (regression anchor)**

Screenshot `/dashboard`; diff against baseline. Expected: byte-identical (Layer 1 untouched).

- [ ] **Step 3: If anything regressed, STOP and fix in the relevant earlier task before proceeding.** Otherwise continue.

---

## Task 6: Consumer migration — retired token names → canonical (PARALLEL)

> **Dispatch one subagent per file, concurrently.** The seven files share no state; there is no ordering between them. Each subagent performs the same mechanical swap on its single file and commits independently.

**Files (one subagent each):**
1. `frontend/src/app/(public)/page.tsx`
2. `frontend/src/app/(public)/about/page.tsx`
3. `frontend/src/app/(public)/careers/page.tsx`
4. `frontend/src/app/(public)/privacy/page.tsx`
5. `frontend/src/app/(public)/terms/page.tsx`
6. `frontend/src/components/HowItWorks.tsx`
7. `frontend/src/components/SignInModal.tsx`

**Interfaces:**
- Consumes: canonical tokens (already in `:root`).
- Produces: zero references to `--brand-text1`, `--brand-text2`, `--radius-*`, `--ease-out`, `--ease-in-out` in these files.

**Per-file subagent instructions (identical for each):**

- [ ] **Step 1: Find the retired-token references in THIS file**

```bash
grep -n 'var(--brand-text1)\|var(--brand-text2)\|var(--radius-\|var(--ease-out)\|var(--ease-in-out)\|var(--brand-primary)' <file>
```

- [ ] **Step 2: Apply the canonical swaps (exact mappings)**

| Retired | Canonical |
|---|---|
| `var(--brand-text1)` | `var(--text)` |
| `var(--brand-text2)` | `var(--text-dim)` |
| `var(--radius-sm)` | `var(--r-sm)` |
| `var(--radius-md)` | `var(--r-md)` |
| `var(--radius-lg)` | `var(--r-lg)` |
| `var(--radius-full)` | `var(--r-full)` |
| `var(--ease-out)` | `var(--ease)` |
| `var(--ease-in-out)` | `var(--ease)` |
| `var(--brand-primary)` | `var(--brand-forest)` |

Use exact string replacement for each occurrence. Do **not** change any other styling, layout, class, or markup (shape/motion changes are a separate follow-up).

- [ ] **Step 3: Verify the file is clean**

```bash
grep -n 'brand-text1\|brand-text2\|var(--radius-\|ease-out\|ease-in-out\|var(--brand-primary)' <file>
```
Expected: nothing.

- [ ] **Step 4: Commit (per file)**

```bash
git add <file>
git commit -m "refactor(css): migrate <file basename> to canonical tokens

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

**Barrier:** after all seven subagents report done, the orchestrator runs:
```bash
cd /home/andresl/Projects/sapling/frontend
grep -rn 'var(--brand-text1)\|var(--brand-text2)\|var(--radius-\|var(--ease-out)\|var(--ease-in-out)\|var(--brand-primary)' src --include='*.tsx' --include='*.ts'
npm run build 2>&1 | tail -5
```
Expected: grep prints nothing across the whole tree; build succeeds. If any file remains, dispatch a follow-up subagent for it before Task 7.

---

## Task 7: Delete aliases + dead declarations (barrier; `globals.css`)

**Files:**
- Modify: `frontend/src/app/globals.css`

**Interfaces:**
- Consumes: Task 6 (all consumers migrated — deletion is now safe).
- Produces: the final, single-namespace token layer.

- [ ] **Step 1: Confirm zero remaining consumers tree-wide**

```bash
cd /home/andresl/Projects/sapling/frontend
grep -rn 'var(--brand-primary)\|var(--brand-text1)\|var(--brand-text2)\|var(--radius-\|var(--ease-out)\|var(--ease-in-out)\|var(--dur-base)\|var(--brand-teal)\|var(--brand-success)\|var(--brand-progress)\|var(--brand-struggle)' src
```
Expected: nothing. (If anything prints, fix that consumer first.)

- [ ] **Step 2: Delete the temporary aliases and any remaining dead declarations**

Remove from `globals.css`: the `--brand-primary: var(--brand-forest);` alias added in Task 2; the `--radius-*`/`--ease-out`/`--ease-in-out`/`--dur-base` alias block in `.landing-page`; and the leftover `--font-inter` line if no consumer remains (grep `var(--font-inter)` / `font-inter` first — keep the `.font-inter` utility class if still referenced).

- [ ] **Step 3: Verify build + that the dead tokens are gone from declarations too**

```bash
grep -n 'brand-primary\|brand-success\|brand-progress\|brand-struggle\|brand-teal\|--radius-\|--ease-out\|--ease-in-out\|--dur-base' src/app/globals.css
npm run build 2>&1 | tail -5
```
Expected: grep prints nothing (or only an intentional comment); build succeeds.

- [ ] **Step 4: Commit**

```bash
git add src/app/globals.css
git commit -m "refactor(css): remove token aliases and dead pre-auth palette declarations

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 8: Final verification + file the follow-up issues

**Files:**
- Create: `docs/superpowers/followups/2026-06-30-token-unification-followups.md` (and/or GitHub issues)

**Interfaces:**
- Consumes: the completed Phase 1.
- Produces: the close-out verification + the tracked backlog for deferred work.

- [ ] **Step 1: Full final visual pass**

Screenshot every surface from Task 1 and compare to `token-baseline/`:
`/`, beta modal, sign-in modal, `/about`, `/careers`, `/privacy`, `/terms`, `/onboarding`, `/pending`, `/dashboard`.
Confirm: pre-auth reads warm and consistent with the dashboard; `/dashboard` byte-identical; no unstyled/invisible elements; all URLs resolve.

- [ ] **Step 2: Confirm the single-namespace invariant holds**

```bash
cd /home/andresl/Projects/sapling/frontend
# No core token assigned outside :root (manual scan of matches):
grep -n '\-\-border:\|\-\-text:\|\-\-shadow-sm:\|\-\-bg-panel:' src/app/globals.css
```
Expected: each appears only inside the `:root` block.

- [ ] **Step 3: Write the follow-up tracker**

Create `docs/superpowers/followups/2026-06-30-token-unification-followups.md`:
```markdown
# Token Unification — Deferred Follow-ups

Phase 1 (token layer + (public) group) landed on branch `refactor/token-unification`.
These consume the unified tokens and were intentionally deferred. Each is its own plan/PR.

## Component re-skins (from the rhythm audit)
- [ ] **B — Beta CTA button species.** Replace the rounded-full pill + infinite `beta-glow`
      with the app button language; convert the glow to a single finite entrance using `--brand-glow`.
- [ ] **E — De-dup the hero card.** Extract one component backed by `--surface-hero`;
      replace the duplicated inline 24px gradient box in the beta modal (`app/(public)/page.tsx`)
      and `SignInModal.tsx`.
- [ ] **C — Re-home onboarding** into the app's layout/spacing/type (`--pad-*`, shell type scale)
      instead of a centered card in a radial void.
- [ ] **D — Re-home pending** onto app surfaces (`.card`) and add a "you're in ✓" confirmation beat.
- [ ] **G — Normalize pre-auth motion** to one or two finite moments (mesh blobs, card-float, shimmer).
- [ ] **I — Delete dead code** `components/OnboardingFlow.tsx` (unused old-DNA onboarding).

## Directory / structural hygiene
- [ ] **Flatten `components/`** (~50 files in one folder) into responsibility-grouped subfolders;
      co-locate the pre-auth components under `components/marketing/`.
- [ ] **Optional cosmetic:** rename the `.landing-page` scope class to `.public-surface`
      (and its `.landing-*` utilities) now that it is layout-hosted, not page-bolted.

Reference: `docs/frontend-rhythm-audit.md`, `docs/superpowers/specs/2026-06-30-token-unification-design.md`.
```

- [ ] **Step 4: File GitHub issues (if `gh` is available and the repo wants issues)**

```bash
gh auth status >/dev/null 2>&1 && for t in \
  "frontend: beta CTA button to app button language (+ finite glow)" \
  "frontend: extract shared hero card from --surface-hero (de-dup beta/sign-in modal)" \
  "frontend: re-home onboarding into app layout/spacing/type" \
  "frontend: re-home pending onto app surfaces + add confirmation beat" \
  "frontend: normalize pre-auth motion to finite moments" \
  "frontend: delete dead OnboardingFlow.tsx" \
  "frontend: flatten components/ directory + co-locate marketing components"; do
    gh issue create --title "$t" --body "Deferred from token-unification Phase 1. See docs/superpowers/followups/2026-06-30-token-unification-followups.md" --label "frontend,refactor"
done
```
If `gh` is not authenticated or labels don't exist, skip and rely on the markdown tracker (note this in the PR).

- [ ] **Step 5: Commit + open the PR**

```bash
cd /home/andresl/Projects/sapling
git add docs/superpowers/followups
git commit -m "docs: track deferred token-unification follow-ups

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
git push -u origin refactor/token-unification
```
Then open a PR summarizing Phase 1, noting the dashboard is unchanged and CI's pre-existing red state is not caused by this change.

---

## Self-Review

**Spec coverage:**
- 3-layer model → Tasks 2 (strip/alias), 3 (marketing layer), 7 (delete) ✓
- Green collapse → Task 3 Steps 1–4 ✓
- `(public)` route group + layout → Task 4 ✓
- Alias-then-migrate → Tasks 2 (alias) → 6 (migrate) → 7 (delete) ✓
- Retirement table (grep-verified consumers) → Tasks 3 (rarity/glass-input), 6 (text1/2, radius, ease), 7 (delete) ✓
- Verification (manual screenshots, dashboard anchor, no harness) → Tasks 1, 5, 8 ✓
- Non-goals deferred + tracked → Task 8 ✓

**Placeholder scan:** No "TBD"/"handle appropriately." Each CSS edit shows exact before/after; each verification shows the exact grep/build command and expected output. ✓

**Type/name consistency:** Marketing tokens (`--bg-mesh`, `--display-hero`, `--surface-hero`, `--brand-glow`) introduced in Task 3 and referenced consistently in Task 8's follow-up. The `.landing-page` scope class is consistent across Tasks 2–4. The retired-token swap table in Task 6 matches the consumers enumerated in Tasks 2–3. ✓

**Open item folded in:** the `--font-inter` keep/delete decision is gated on a grep in Task 7 Step 2 rather than left ambiguous. ✓

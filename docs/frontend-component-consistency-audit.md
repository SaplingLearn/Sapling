# Frontend Component Consistency Audit — Buttons, Greens, Pills

**Date:** 2026-06-30
**Scope:** the *component-level* styling the token-unification (Phase 1) deliberately did **not** touch — button shapes, the green-by-role mess, and the pill/badge zoo. Grounded in code inventory + live screenshots of gradebook / social / achievements.

## TL;DR

Phase 1 fixed *which value a token resolves to*. This is the layer underneath: **there are no shared UI primitives**, so every surface reinvents buttons and pills with slightly different radii and greens. Two problems compound:

1. **No shared `<Button>` / `<Pill>` / `<Badge>`** → 5 distinct button shapes, **18+** separate pill/badge implementations.
2. **Too many greens with overlapping roles** → **5 active semantic greens**, two pairs visually indistinguishable, and the *most-used* "green" (`--accent` sage, 125 uses) isn't even the brand green.

You can see all of it on one gradebook screen: a sage "Upload syllabus" button, a forest "Spring 2026" pill, a grade-A green card, and grade-band percentages — four greens, two button shapes.

---

## 1. Buttons — 5 shapes where there should be ~2

The canonical `.btn` (globals.css) is **6px** (`--r-sm`) and ~211 buttons use it correctly. But a large minority go bespoke:

| Shape bucket | Radius | Where | Verdict |
|---|---|---|---|
| **Canonical** | 6px `.btn` | Dashboard/Learn primary CTAs, most modals | ✅ the standard |
| **Hard-coded 6px** | 6px (inline) | 5 Gradebook modal buttons (`LetterScaleEditor:107`, `SyllabusUploadFlow:220`, `AssignmentModal:346`, `EditWeightsModal:268`, `Gradebook/Course:186`) | ⚠️ right pixel, **bypasses `.btn`** — no hover/transition inheritance |
| **Study 10px** | 10px `--r-md` | flashcard rating buttons (`Study.tsx:593`) — the most-tapped study control | ❌ off-standard, high-friction |
| **Onboarding** | 8/12/14/100px | `OnboardingFlow.tsx` (multiple) | ❌ bespoke wizard (also dead code — see follow-up #292) |
| **Pills** | 999px / `rounded-full` | landing CTAs (`(public)/page.tsx:705,781,911`), Learn mode toggles, ModelToggle | ⚠️ intentional for toggles, but the **landing primary CTAs** are pills while the **app primary CTAs** are 6px |

**Worst inconsistency — the primary-action identity is split.** "Start learning" / "Start quiz" in the app are sharp 6px; "Get Started" / "Sign up for Beta" on the landing are fully-rounded pills. A user's first button (pill) contradicts every in-app button (6px).

**Second — three separate toggle/segmented controls** (`Learn.tsx:473`, `Learn.tsx:562`, `ModelToggle.tsx:66`), all `--r-full` but with different padding/font. No shared `<Toggle>`.

---

## 2. Greens — 5 active, two pairs indistinguishable

12 greens exist (8 tokens + 4 hard-coded); **5 are in active semantic use**:

| Green | Token | Uses | Role | Problem |
|---|---|---|---|---|
| `#1B6C42` | `--brand-forest` | 45 | primary brand / action / rarity-uncommon | — |
| `#8a9a5b` | `--accent` (sage) | **125** | UI accents, reactions, focus, "Upload syllabus" btn | **the most-used "green" is sage, not the brand forest** — this is the main "greens feel inconsistent" culprit |
| `#3e8030` | `--c-sage` = `--grade-a` | 4 | grade-A display | **9 hex points from forest** — indistinguishable; on gradebook it reads as the brand green |
| `#4a7d5c` | `--state-mastery` | 3 | dashboard mastery | barely used; a 4th near-forest green |
| `#1a5c2a` | *(hard-coded, no token)* | 12 | landing logo, TopNav | **not in the token system** — brand drift risk |

**The core issue:** "a green affordance" renders as forest in one place, sage in another, grade-green in a third — because the greens are split by *accidental history*, not by *role*. The 125-use sage `--accent` makes the app's de-facto "main green" a muted yellow-green that clashes with the forest brand.

**Proposed green-by-role collapse (3 roles):**
1. **Brand / primary action** → `--brand-forest` (one green for all primary buttons, active nav, brand marks). Tokenize the hard-coded `#1a5c2a` into it.
2. **Positive status** (mastery, grade-A, success) → **one** status-green. Merge `--grade-a`/`--c-sage` and `--state-mastery` into a single `--positive` (distinct enough from forest to read as "status", or just = forest if we want them unified).
3. **Decorative accent** → decide sage's fate: either keep `--accent` sage as a deliberately *different* hue (not green-family) so it stops competing with forest, or retire it toward forest. Recommend: **shift accent off the green family** (it's currently a near-green that muddies everything) OR rename it so its role is explicit.

---

## 3. Pills / badges — 18+ implementations → 3–4 components

| # | Implementation | File |
|---|---|---|
| 1–5 | `.chip` + `--accent/--warn/--err/--info` | globals.css |
| 6 | `Pill.tsx` (generic, `color` prop) | components/Pill.tsx |
| 7 | `RoleBadge.tsx` (color-mix) | components/RoleBadge.tsx |
| 8 | `TitleFlair.tsx` (rarity tokens) | components/TitleFlair.tsx |
| 9–18+ | inline pills: Achievement rarity badges, Social reaction pills, Study badges, course category filters, graph badges, AI-disclaimer chip, term pills, filter chips… | many |

**Proposed consolidation → 3 components:**
- **`<Chip>`** — neutral / status / accent pills (replaces the `.chip` variants + most inline pills). One radius, one padding scale, variant prop.
- **`<Badge>`** — rarity / role / grade badges (replaces `RoleBadge` + `TitleFlair` + achievement inline badges); centralizes the color-mix logic.
- **(optional) `<StatPill>`** — mastery / grade / status indicators if they need distinct treatment.

Estimated ~70–80% reduction in pill/badge code.

---

## Recommended approach (shared components to simplify)

The order that de-risks and pays off fastest:

1. **`<Button>` primitive** — wrap the `.btn` system in a React component with `variant` (primary/secondary/ghost/danger) + `size`, kill the 5 hard-coded gradebook radii and the off-standard Study 10px, and **pick one primary-action shape** (recommend 6px everywhere; pills reserved for true toggles). Migrate inline buttons to it.
2. **`<Toggle>` / segmented control** — one component for the 3 mode/model toggles.
3. **Green-by-role token cleanup** — collapse to brand / positive / accent; tokenize `#1a5c2a`; decide sage's role.
4. **`<Chip>` + `<Badge>`** — collapse the 18 pill/badge implementations.

Each is independently shippable and shrinks the codebase. (1) + (3) deliver the most visible consistency for the least risk.

## Decision needed
- **Primary-action shape:** sharp 6px everywhere (app's current identity) vs. soft pill everywhere (landing's identity)? Pick one — they can't coexist as "the primary button."
- **Sage `--accent`:** keep as a deliberately non-green accent, or retire toward forest?

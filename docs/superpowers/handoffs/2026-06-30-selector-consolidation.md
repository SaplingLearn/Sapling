# Handoff — consolidate selector/sort/filter controls (continues PR #294)

> Paste this into a fresh chat to continue the work. It carries the context, the concrete worklist, the design forks to resolve, and the gotchas.

---

You're continuing frontend design-consistency work on the Sapling repo at `/home/andresl/Projects/sapling` (Next.js app in `frontend/`). **Work on the existing branch `refactor/component-system`** (do NOT create a new branch) and update **PR #294**. Two phases already shipped: Phase 1 = token unification (PR #286), Phase 2 = shared UI primitives + green consolidation (PR #294, this branch).

## Honor these decisions (already made with the user)
- **Buttons are sharp 6px everywhere; pills are ONLY for true toggles/chips.**
- **Greens by role:** `--brand-forest #1B6C42` (primary action) · `--accent #2D8F5C` (highlight/focus — the BRIGHT forest) · `--positive #3a7d4e` (status: mastery/grade). Sage retired. **Never use `--accent` as a button FILL** (use `--brand-forest`); it's for active-state highlights only.
- **Don't force-consolidate specialized controls.** If a control has animation, per-option color semantics, or a11y needs that a generic primitive would degrade, LEAVE IT. (Precedents we set: kept `ModelToggle` for its sliding animation + Fast/Smart colors; kept rarity badges' a11y-neutral text because colored text fails 4.5:1.)

## Shared primitives (in `frontend/src/components/ui/`, import from `@/components/ui`)
- `<Button variant size>` — `variant`: primary|secondary|ghost|danger; `size`: sm|md|lg|xl; always 6px.
- **`<Toggle options value onChange size>`** — `options: {value,label,title?}[]`, single-select **connected segmented pill** control, forest-filled active segment, `size`: sm|md. **This is the main primitive for this task.**
- `<Chip variant icon>` — wraps the `.chip` classes.
- `<Badge color bg>` — a11y-correct tinted badge (hue on border, neutral text).

## YOUR TASK
Consolidate the **selector / sort / filter / view-toggle / tab** controls across these 8 surfaces onto consistent shared components, committing per-surface, updating PR #294.

## Inventory (verify each file:line before editing — counts/lines may have drifted)

| Surface | Control | File:line | Current pattern | Target |
|---|---|---|---|---|
| Gradebook | Semester selector (Spring/Fall) | `components/Gradebook/SemesterChips.tsx:13–48` | custom pill buttons, accent-border active | `<Toggle>` |
| Social | Overview/Chat/Study Match/Activity tabs | `components/screens/Social.tsx:1059–1073` | button row, accent-soft active | `<Toggle>` |
| Achievements | all/activity/social/milestone/special filter | `components/screens/Achievements.tsx:210–214` | `<Pill>` row | filter-pills (see fork) |
| Calendar | month/week/day/table view | `components/screens/Calendar.tsx:192–207` | button row in border, accent-soft active | `<Toggle>` |
| Library | category filter (7, incl. dynamic) | `components/screens/Library.tsx:186–189` | `<Pill>` row | filter-pills (see fork) |
| Library | grid/list view toggle | `components/screens/Library.tsx:196–209` | 2 buttons in border, accent-soft active | `<Toggle>` |
| Study | Study Guide/Flashcards mode | `components/screens/Study.tsx:84–113` | **Framer-Motion spring** toggle | DECIDE (animation lost if migrated) |
| Study | topic filter (All + dynamic) | `components/screens/Study.tsx:526–529` | `<Pill>` row | filter-pills (see fork) |
| Tree | mastery tier (all/mastered/learning/struggling/unexplored) | `components/screens/Tree.tsx:270–275` | `<Pill>` row, **per-tier colors** | filter-pills + color (see fork) |
| Tree | course filter (All + courses w/ colored dots) | `components/screens/Tree.tsx:293–308` | `<Pill>` row, **colored dots** | likely leave-specialized |
| Quiz | question count (5/10/15) | `components/QuizPanel.tsx:186` | `<CustomSelect>` dropdown | DECIDE (Toggle vs keep) |
| Quiz | difficulty (easy/med/hard/adaptive) | `components/QuizPanel.tsx:190` | `<CustomSelect>` dropdown | DECIDE (Toggle vs keep) |

## Resolve these design forks FIRST (ask the user)
1. **Two families, one or two components?** There are (a) **fixed segmented controls** (2–5 fixed options: Social tabs, Calendar views, Library grid/list, Gradebook semester, Study mode) that fit `<Toggle>` directly, and (b) **filter-pill groups** ("All" + N, often *dynamic/wrapping*: Achievements, Library categories, Study topics, Tree tiers) where a fixed connected segmented control does NOT fit — they need a **wrapping row of selectable pills**. Decide: add a wrapping/`variant="pills"` mode to `<Toggle>`, OR build a small `<FilterPills>`/`<ChipGroup>`. (The existing `<Pill>` component already exists — you may just standardize on it for family (b) and reserve `<Toggle>` for family (a).)
2. **Per-option colors.** Tree's tier filter encodes state via color; Tree's course filter uses colored dots. The filter-pills component needs optional per-option `color`/`dot` support, or Tree's course filter stays specialized.
3. **Study mode toggle** has a Framer-Motion spring animation — keep it specialized (like ModelToggle) or accept the plain `<Toggle>`? Get the user's call.
4. **Quiz selectors** are `<CustomSelect>` dropdowns with small option sets (3–4) — convert to `<Toggle>` for visibility, or keep as dropdowns for consistency with other CustomSelect usage? User's call.

## Process (mirror what worked this session)
- Dev server: `cd frontend && npm run dev` (port 3000). The user is signed in, so authed pages (gradebook/social/etc.) load.
- Migrate **one surface at a time**; after each, **screenshot it live and confirm the control still switches/filters correctly** (preserve every `onClick`/state handler — these are interactive). Commit per surface with a clear message.
- Verify per change: `npx tsc --noEmit` (filter out stale `.next/types` route-validator errors — they're harmless), `npx eslint .` (**must be 0 errors**; ~37 warnings are fine), `npm run test` (vitest, **68 passing**).
- Push to update **PR #294** after a coherent chunk; don't push on every micro-tweak.

## Gotchas (learned this session)
- `npm run build` sometimes exits **144** in this env — that's a resource/timeout kill, NOT a code error. Just retry; it passes. Don't run it concurrently with `next dev` (they fight over `.next`).
- Stale `.next/types/validator.ts` typecheck errors appear after route moves — harmless, regenerate on build; grep them out of typecheck output.
- `frontend/eslint-suppressions.json` keys on file **paths**. If you move/rename a file that has grandfathered (suppressed) lint errors, re-home its suppression entry to the new path or CI's eslint step fails (this exact thing bit us in Phase 1).
- Shell is **fish** — quote grep globs: `grep -r 'x' --include='*.tsx'`.
- Reference docs on the branch: `docs/frontend-component-consistency-audit.md`, `docs/superpowers/specs/2026-06-30-component-system-phase2-design.md`, `docs/changes-tour.html` (guided tour of changes), `docs/button-shape-comparison.html`.

Start by reading `components/ui/Toggle.tsx` and 2–3 of the inventory files to ground yourself, then ask the user the 4 forks above before editing.

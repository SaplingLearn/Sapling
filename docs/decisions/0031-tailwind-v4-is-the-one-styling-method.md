# 0031: Tailwind v4 is the one styling method

- Status: proposed
- Date: 2026-11-26
- Supersedes: none

## Context

The frontend styled things four ways at once: 3,995 inline `style={{}}`
blocks (about 15,400 declarations), CSS modules, a 3,181-line `globals.css`,
and Tailwind v4, which was installed but used in about seven files. Tokens
existed (`--sap-*`, `--ink-*`, `--bg-*`, `--fs-*`, `--r-*`), but about 2,000
raw hex colours sat next to them. Around 40 files drew their own modal
overlay, most with their own Escape listener and scroll lock, and some with
no focus handling at all.

Inline styles can't express hover, focus or breakpoints, can't be linted for
token use, and are what coding agents copy when they add a screen. Most of the
UI is now written by agents, so whatever pattern is most common grows.

## Decision

1. **Styling is Tailwind classes on Sapling's tokens.** `src/styles/tokens.css`
   holds every value; `src/styles/theme.css` maps them onto Tailwind's
   namespaces and clears Tailwind's defaults, so only Sapling's names exist
   (`bg-bg-panel`, `text-text-dim`, `text-md` = 13px, `rounded-md` = 10px,
   `shadow-sm`, `font-display`). `bg-blue-500` doesn't compile.
2. **Inline `style` is for runtime values only**: a computed position or
   width, a course colour from data, or a CSS variable a class reads.
3. **Layers replace specificity.** `globals.css` is an import list:
   tokens, theme, `base.css` (`@layer base`) and `components.css`
   (`@layer components`). Every other stylesheet is wrapped in
   `@layer components` too, so a utility always beats a component class, the
   way an inline style did. That is what let 3,500 elements move from inline
   styles to classes without a visual change.
4. **One modal engine.** Modals are `Dialog`, `Sheet` or `ui/PanelModal`, or
   take `useOverlayBehaviour` for a custom panel. Menus are `ui/Menu`
   (Radix DropdownMenu). Radix is added for menus, popovers and tooltips;
   `Dialog`/`Sheet` keep `useOverlayBehaviour`, which already does focus,
   Escape, the Tab trap and the app's own scroll lock.
5. **Lint holds the line.** `no-restricted-syntax` in `eslint.config.mjs`
   rejects static inline styles, raw hex in classes, `role="menu"` outside
   `ui/`, and hand-built `fixed inset-0` overlays. Existing hits are in
   `eslint-suppressions.json` and only shrink.

The migration was a codemod (`frontend/scripts/codemods/`), checked in a real
browser: every converted element was rendered twice in Chromium, inline and
with its classes, and all ~3,000 unique cases matched on every computed
property. Public and signed-in screens were then screenshot-diffed against
`main`.

## Consequences

- New UI is written in classes; agents read `frontend/CLAUDE.md` and the
  theme comment for the names.
- Unit tests can't see classes in jsdom: use `toHaveTwStyle` (vitest.setup.ts)
  or `twStyle(el)` (`src/test-utils/twStyle.ts`), which read what the classes
  set from a map built from the real stylesheet.
- The codemods stay in the repo. A branch that predates the migration is
  brought over by taking its version of a file and re-running
  `inline-style-to-tailwind.mjs` on it.
- About 380 inline styles remain, all runtime values, plus static ones on
  components that merge their own inline style (Skeleton, FadeIn, Glyph).
- CSS modules and the legacy component classes (`.btn`, `.card`, `.chip`)
  remain, layered, and move to `components/ui` over time.

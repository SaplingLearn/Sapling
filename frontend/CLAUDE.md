# Sapling frontend

Next.js 16 + React 19 on Cloudflare Workers. Styling decision: `docs/decisions/0031-tailwind-v4-is-the-one-styling-method.md`.

## Styling rules

- **Style with Tailwind classes on Sapling's tokens.** Names are in the comment at the top of `src/styles/theme.css`; values live in `src/styles/tokens.css`. Common ones:
  - colour: `bg-bg`, `bg-bg-panel`, `bg-bg-subtle`, `text-text`, `text-text-dim`, `text-text-muted`, `border-border`, `bg-accent`, `text-err`, `bg-sap-100`, `text-ink-600`; public pages use `moss-*`, `leaf-*`, `paper-*`
  - type: `text-2xs` 10px, `text-xs` 11px, `text-sm` 12px, `text-md` 13px (body), `text-base` 14px, `text-lg` 16px … `text-5xl` 32px. These are NOT Tailwind's default sizes.
  - radius `rounded-xs`…`rounded-xl` (4/6/10/16/22px), shadow `shadow-sm|md|lg`, fonts `font-sans` (UI), `font-serif`, `font-display`, `font-code`
  - spacing is Tailwind's 4px step (`p-3` = 12px, `gap-1.5` = 6px)
- **`style={{}}` only for runtime values** (computed positions, widths from data, a course colour). Never a literal. Lint rejects static inline styles and raw hex in classes.
- No new colour as hex: add a token to `tokens.css` and its `--color-*` alias to `theme.css`.
- Merge classes with `cn()` from `@/lib/cn` (clsx + tailwind-merge configured for our theme). A later class wins.
- Class-based stylesheets (`components.css`, CSS modules) are in `@layer components`: a utility always beats them. Don't add new global classes; build a component.

## Components

- Check `src/components/ui/` first (`index.ts` exports): Button, Chip, Badge, Toggle, Switch, SegmentedControl, Sheet, EmptyState, InlineBanner, Menu, PanelModal, Tooltip …
- Modals: `Dialog` (`@/components/Dialog`), `Sheet`, `ui/PanelModal`, or `useOverlayBehaviour` for a custom panel. Never hand-build `fixed inset-0` overlays.
- Menus: `Menu`/`MenuTrigger`/`MenuContent`/`MenuItem` from `@/components/ui/Menu` (Radix). Never hand-build `role="menu"`.

## Tests

- jsdom applies no stylesheet. Assert styles with `expect(el).toHaveTwStyle({ padding: "12px" })`, or read `twStyle(el).minHeight` (`@/test-utils/twStyle`). Both see classes and inline style together.
- `npm test`, `npm run lint`, `npm run typecheck`. Ratchets: `npm run complexity`, `npm run max-lines`.

## Codemods

`scripts/codemods/` moved inline styles to classes and can do it again (e.g. on a branch from before the migration):

```
node scripts/codemods/inline-style-to-tailwind.mjs --dry --log /tmp/cases.json src/components/Foo.tsx
PW_CHROMIUM=<chromium> node scripts/codemods/verify-inline-style.mjs /tmp/cases.json   # every element, computed-style equal
node scripts/codemods/inline-style-to-tailwind.mjs src/components/Foo.tsx
```

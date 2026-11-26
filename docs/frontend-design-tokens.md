# Frontend design tokens, motion, and the hardcode ratchet

Every colour, space, type size, radius, shadow, layer and timing in the signed-in
app comes from a token in `frontend/src/app/globals.css`. A component writes the
token (`var(--sp-4)`, `var(--z-modal)`, `var(--dur)`), never the value. The
pre-auth landing scope (`.landing-page`, `.public-surface`, `.landing-dc`,
`.landing-v5`) keeps its own token set and is out of scope here.

## Token families

All live in the first `:root` block of `globals.css`. Light theme only; the one
scope that redefines tokens is `html[data-density]` (the `--pad-*` insets and
`--row-h`).

| Family | Tokens | For |
|---|---|---|
| Neutrals | `--ink-0` … `--ink-900` | the warm paper/ink ramp the surface tokens are built from |
| Brand | `--sap-50` … `--sap-900`, `--brand-forest(-hover)`, `--brand-forest-bright(-hover)`, `--sidenav-*` | the green ramp and the brand fills |
| Surfaces and text | `--bg`, `--bg-panel`, `--bg-subtle`, `--bg-soft`, `--bg-input`, `--bg-inset`, `--bg-topbar`, `--border(-strong)`, `--text`, `--text-dim`, `--text-muted`, `--accent(-fg/-soft/-border)` | what most components need |
| State | `--warn(-soft)`, `--err(-soft)`, `--info(-soft)`, `--positive`, `--state-mastery/-progress/-struggle/-neutral`, `--alert-*` | status, verdicts, mastery |
| Categorical | `--c-crimson` … `--c-ink`, `--grade-a` … `--grade-f`, `--rarity-*` | course colours, grade bands, achievement tiers |
| Role colours | `--text-on-fill`, `--scrim`, `--focus-ring`, `--focus-halo`, `--tool-quiz(-soft)`, `--series-compare` | white text on a saturated fill, the modal backdrop, keyboard focus, an input's focus ring, the Quiz tool's hue, a second person's series |
| Type | `--fs-2xs` (10px) … `--fs-5xl` (32px), `--font-display/-serif/-sans/-mono` | font sizes (body is `--fs-md`, 13px) and faces |
| Spacing | `--sp-1` (2px) … `--sp-16` (32px), `--sp-20` (40), `--sp-24` (48), `--sp-28` (56), `--sp-32` (64) | margin, padding and gap. `--sp-N` is N × 2px, so the name tells the size. Odd px values have no step: round to a neighbour |
| Insets | `--pad-sm/-md/-lg/-xl`, `--row-h` | a panel's inset and a list row's height; density-aware (`html[data-density]`), steps of the spacing scale by default |
| Radius | `--r-xs` (4) `--r-sm` (6) `--r-md` (10) `--r-lg` (16) `--r-xl` (22) `--r-full` | corners |
| Shadow | `--shadow-sm/-md/-lg/-inset` | elevation |
| Layers | `--z-base` (0), `--z-raised` (1), `--z-sticky` (20), `--z-popover` (100), `--z-overlay` (150), `--z-modal` (200), `--z-toast` (1000) | z-index by role: a raised sibling, sticky chrome, menus and selects, full-screen takeovers, modals and their backdrops, toasts. A layer between two roles is a new role: name it in `globals.css` |
| Motion | `--dur-instant` (60ms), `--dur-fast` (140), `--dur` (220), `--dur-slow` (420), `--dur-slower` (600); `--ease`, `--ease-out`, `--ease-in`, `--ease-in-out`, `--ease-emphasized` | `--ease-out` for entrances, `--ease-in` for exits, `--ease-in-out` for moving between two places, `--ease-emphasized` for an entrance meant to be noticed, `--ease` the default |

Components may also declare local tokens for their own surface (the quiz's
`--answer-*`, the flashcards' `--deck*`); build them from the global ones.

## Numbers in code: `lib/designTokens.ts`

Where `var()` does not resolve (framer-motion, canvas/WebGL, a timer that must
end with a CSS transition, z-index arithmetic), import the mirror:

- `MOTION.duration` (seconds: `instant`, `fast`, `base`, `slow`, `slower`),
  `MOTION.ease` (cubic-bezier arrays: `standard`, `out`, `in`, `inOut`,
  `emphasized`), plus the TS-only `MOTION.stagger`, `MOTION.offset` (how far
  things travel) and `MOTION.spring` (`gentle`, `snappy`, `bouncy`).
- `Z`, the layers as numbers.
- `cssBezier(points)` writes a curve back as CSS.

`src/lib/designTokens.test.ts` parses `globals.css` and fails when the two
sides drift, or when a `--dur*`, `--ease*` or `--z-*` token exists on one side
only. Change both in the same commit.

## Motion: `lib/motion.ts`

```tsx
import { motion, AnimatePresence } from "framer-motion";
import { useMotionPresets } from "@/lib/motion";

const m = useMotionPresets();          // resolved for the user's reduced-motion setting
<motion.div {...m.fadeUp} />            // also fade, scaleIn
<AnimatePresence>{open && <motion.div {...m.collapse} />}</AnimatePresence>
<motion.ul variants={m.list.container} initial="hidden" animate="shown">
  {rows.map(r => <motion.li key={r.id} variants={m.list.item} />)}
</motion.ul>
<motion.span key={attempt} {...m.pulse(isRight ? "correct" : "wrong")} />  // re-key to replay
```

- `fade`, `fadeUp`, `scaleIn`, `collapse` are `{ initial, animate, exit,
  transition }` to spread onto a `motion.*` element; `list` is a
  `{ container, item }` pair of variants; `pulse(verdict)` is a one-shot
  scale pulse (right) or shake (wrong); `transition` has `fast`, `base`,
  `slow`, `exit` and the springs for a hand-built animation.
- `motionPresets(reduced)` is the same set without the hook (tests, non-React
  code). `MotionProvider` sets app-wide defaults (MOTION's base duration and
  curve, `reducedMotion="user"`); mount it once around a tree that uses
  framer-motion. Importing `lib/motion` also sets framer's test-mode skip
  (`MotionGlobalConfig.skipAnimations` under `NEXT_PUBLIC_TEST_MODE`), which
  every framer consumer needs.
- Reduced motion means no movement: entrances become a short opacity fade, a
  collapse snaps, a list appears at once, the verdict pulse is an opacity
  blink, and every hand-built transition is instant. `lib/motion.test.ts`
  pins this.
- Animate between the states a component already has. Every preset rests on
  identity (no transform, full opacity, natural height), so adding one never
  changes how the component looks at rest. Do not change a resting layout to
  make an animation easier.
- CSS animations use the motion tokens directly (`transition: opacity
  var(--dur) var(--ease-out)`); the global `prefers-reduced-motion` rule in
  `globals.css` collapses them.

## The hardcode ratchet

`frontend/scripts/hardcode-ratchet.mjs` counts hand-written design values per
git-tracked file under `frontend/src`, in four categories:

| Category | Counts |
|---|---|
| `color` | `#hex`, `rgb[a](`, `hsl[a](` in a CSS declaration or a TS/TSX string literal |
| `css-size` | in CSS: non-zero px/rem in `margin*`, `padding*`, `gap`, `font-size`, `*-radius`, `box-shadow`; a literal `z-index`; times and `cubic-bezier()` in `transition*` / `animation*` |
| `inline-style` | in a React style object (`style={{…}}`, a `style:` property, an object typed or asserted `CSSProperties`): non-zero literal numbers, and px/rem or colours inside strings. Unitless properties (`flex`, `opacity`, `fontWeight`, `lineHeight`, …) are skipped |
| `url` | `http(s)://` URLs and `localhost` in TS/TSX string literals (XML namespaces skipped) |

Not measured: tests, `__snapshots__/`, `__fixtures__/`, JSON (golden files
included), `lib/designTokens.ts`, the `--*` token definitions in
`globals.css`, and the landing scope (its files under `app/(public)/`,
`components/{landing,landing-v5,marketing,companion}/`, `lib/landing/`, and its
rules and sections in `globals.css`).

`frontend/hardcode-baseline.json` holds today's count for every
`<file>::<category>`. A count may not rise and a new key may not appear: use
the token. A count that drops does not fail (two PRs converting parts of one
file must not leave main red between them) but should be locked in.

```
npm run hardcode                 # report and the top 25 files; exit 1 on growth
npm run hardcode -- --file <path>  # every hit in one file, with its line
npm run hardcode:shrink          # lower the baseline to today's numbers
```

`scripts/hardcode-ratchet.test.ts` runs the same check inside `npm test`, which
the Frontend CI job already runs: no separate workflow. `--shrink` only lowers
or deletes entries; raising one is a hand edit to the JSON that a reviewer has
to accept.

# Frontend UI Audit

_Generated 2026-06-07 · scope: `frontend/` (Next.js 16 App Router, Tailwind v4, CSS-custom-property token system, light-mode only)._

This is a **technical** quality audit across five dimensions, scored against WCAG 2.1 AA and the project's own design contract in `.impeccable.md`. Every finding is cited to `file:line` and verified against the code. It documents what's wrong — it does not change code.

## Health score

| # | Dimension | Score | Key finding |
|---|-----------|:-----:|-------------|
| 1 | Accessibility | **2 / 4** | Shared token contrast failures (`--text-muted`, `--accent` buttons, accent chips) + `outline:none` strips focus from most inputs |
| 2 | Performance | **3 / 4** | Strong bundle/lazy-load discipline; weak runtime animation (landing RAF, atmospheric backdrop, d3-tick re-renders) and no `next/image` |
| 3 | Theming | **2 / 4** | Canonical brand green `#1B6C42` is not a token (hard-coded ~90×); 10 competing "greens"; two parallel token systems |
| 4 | Responsive | **2 / 4** | 100% JS-hook breakpoints at a single 768px; Admin/Gradebook/Settings desktop-only; touch targets < 44px; SSR paints desktop |
| 5 | Anti-Patterns | **1 / 4** | Landing/onboarding violate **four of the project's own hard bans**: glassmorphism, gradient text, hero-metric cards, dark-mode stylesheet |
| | **Total** | **10 / 20** | **Acceptable — significant work needed** |

**Rating bands:** 18–20 Excellent · 14–17 Good · **10–13 Acceptable** · 6–9 Poor · 0–5 Critical.

## Anti-patterns verdict (start here)

**Does this look AI-generated? — FAIL, on the landing/onboarding surface.** The signed-in app shell has distinctive editorial bones (the feature catalog at `page.tsx:858-895` is hairline rows with bare inline icons — exactly the type-hierarchy approach the brand demands). But the first thing a new user sees — the public hero and onboarding — is a near-perfect reproduction of the 2024–2025 AI-SaaS template `.impeccable.md` explicitly names as its anti-reference: frosted-glass floating cards orbiting a gradient-animated headline, with big-number "68% mastered / 2,413 nodes" stat tiles. The app shell alone would pass; the marketing surface does not.

## Executive summary

- **Health: 10/20 (Acceptable).** No issues block basic task completion, but there are real WCAG AA violations and systemic brand-spec breaches.
- **Issue counts:** 4 × P0, 15 × P1, 19 × P2, 9 × P3.
- **Top 5 issues:**
  1. **[P0] Glassmorphism system** (`globals.css:443-530`) — the single most-banned aesthetic in the contract, rendered front-and-center on the hero and onboarding.
  2. **[P0] Gradient text on every landing heading** (`page.tsx:673,791,844,937`) — a named anti-reference, on the brand's biggest typographic moments.
  3. **[P0] Brand green `#1B6C42` is not a token** — hard-coded ~90× across 6 files; ten competing greens with no single source of truth.
  4. **[P1] Token-level contrast failures** — `--text-muted` (~3.6:1, used ~224×), white-on-`--accent` buttons (3.06:1), accent chips (2.80:1) all fail WCAG 1.4.3.
  5. **[P1] `outline:none` with no replacement** on ~13 inputs/textareas — keyboard focus is invisible on the primary chat box and most form fields.
- **Recommended sequence:** brand-spec cleanups first (glass, gradient text, dark-mode orphan — they're deletions that immediately raise the worst-scoring dimension), then the theming token consolidation that unblocks the contrast fixes, then responsive and performance passes.

## Detailed findings by severity

### Accessibility — 2/4

- **[P1] `--text-muted` body text fails contrast** — `globals.css:58` (`#8a8372`) — used ~224× (captions, descriptions, placeholders, `CustomSelect`). Measured **3.77:1 on white**, **3.55:1 on paper**, **3.41:1 on `--bg-inset`**. WCAG 1.4.3. Fix: darken to ~`#6f6857` or darker.
- **[P1] Primary button text fails contrast** — `globals.css:180` (`.btn--primary`, white on `--accent #8a9a5b`) — **3.06:1**. WCAG 1.4.3. Fix: darken `--accent` for button backgrounds (e.g. `--sap-600`), or only use white-on-accent at ≥18.66px bold.
- **[P1] Accent chip text fails contrast** — `globals.css:168` (`.chip--accent`, `--accent` on `--accent-soft`) — **2.80:1**. WCAG 1.4.3.
- **[P1] ModelToggle active labels fail contrast** — `ModelToggle.tsx:64,119` — active "Fast" `#3B82F6` = **3.26:1**, "Smart" `#8A63D2` = **3.88:1** at 12px. WCAG 1.4.3.
- **[P1] Focus indicator removed on inputs with no replacement** — `ChatPanel.tsx:175`, `screens/Social.tsx:527`, `(shell)/notetaker/page.tsx:705,922,956,1179,1573,1828`, `screens/Learn.tsx:819,1059`, `flashcards/ParsedCardsTable.tsx:86,93`, `page.tsx:1159` — inline `outline:"none"` overrides the global `:focus-visible`; no `:focus-within` fallback exists. WCAG 2.4.7. Fix: add a `:focus-within` ring on the wrapper.
- **[P1] ChatPanel message input has no accessible name** — `ChatPanel.tsx:157` — bare `<textarea>` with only a placeholder. WCAG 4.1.2 / 3.3.2. Fix: `aria-label="Message"`.
- **[P2] SignInModal doesn't trap or restore focus** — `SignInModal.tsx:75-80,195` — has `role="dialog"`/Escape/scroll-lock but never moves focus in, traps Tab, or restores on close (unlike the shared `Dialog.tsx`). WCAG 2.4.3 / 1.4.13. Fix: reuse `Dialog.tsx`.
- **[P2] FunctionPlot & MermaidBlock have no text alternative** — `FunctionPlot.tsx:123-136`, `MermaidBlock.tsx:98` — rendered SVG with no `role="img"`/`aria-label`/`<title>`. WCAG 1.1.1.
- **[P2] KnowledgeGraph 2D canvas has no text alternative / keyboard access** — `KnowledgeGraph2D.tsx:372` — pointer-only, no `role`/label/off-screen node list (the 3D variant already provides an `SR_ONLY` list at `KnowledgeGraph3D.tsx:203` — mirror it). WCAG 1.1.1, 2.1.1.
- **[P2] Several form controls lack accessible names** — `ManageCoursesModal.tsx:115-119` (search), `screens/Calendar.tsx:738,753` (select-all / row checkboxes). WCAG 3.3.2 / 4.1.2.
- **[P2] Clickable `<div>` not keyboard-operable** — `page.tsx:696` (logo `<div onClick>`). WCAG 2.1.1.
- **[P3] CustomSelect listbox lacks `aria-activedescendant`** — `CustomSelect.tsx:147-205`. WCAG 4.1.2.
- **[P3] ModelToggle radiogroup missing arrow-key navigation** — `ModelToggle.tsx:80-124`.

_Good baselines to preserve:_ `Dialog.tsx` focus trap + restore + Escape; global `:focus-visible` (`globals.css:220`); skip link (`:228`); `prefers-reduced-motion` block (`:250`) + JS guards; ChatPanel `role="log"` live region; `<nav>`/`<main>` landmarks.

### Performance — 3/4

- **[P2] Landing hero canvas: O(N²) link pass + per-node `shadowBlur`, no reduced-motion guard** — `page.tsx:404-446` — 60fps RAF runs a nested loop over all nodes and sets `ctx.shadowBlur` per node; no `prefers-reduced-motion` check anywhere in `page.tsx`. Fix: gate RAF behind reduced-motion; drop `shadowBlur` for a pre-rendered glow sprite; cap the link pass.
- **[P2] Floating-cards RAF does `querySelectorAll` every frame** — `page.tsx:507-516` — re-queries `.floating-card` and re-parses `dataset` floats each frame. Fix: resolve the NodeList + parse once in the effect.
- **[P2] AtmosphericBackdrop repaints 14 full-viewport radial gradients every frame, forever** — `AtmosphericBackdrop.tsx:93-139` — mounted on the whole authenticated shell (`ShellFrame.tsx:30,66`); `clearRect` + 14× `createRadialGradient` over the full viewport at 60fps on a CPU canvas. Reduced-motion handled; everyone else never throttles. Fix: pre-bake each orb to an offscreen canvas + `drawImage`; consider ~30fps cadence.
- **[P2] KnowledgeGraph2D re-renders the whole SVG on every sim tick and pointer move** — `KnowledgeGraph2D.tsx:172-174,306` — d3 `.on("tick", forceRerender)` reconciles all nodes each tick; `onPointerMove` calls `setTooltipPos` on every move; edges do O(E·N) `find()` lookups (`:397-398`). Fix: drive positions via refs/direct DOM writes; only set tooltip when hovered; precompute an id→node Map.
- **[P2] No `next/image`; user images eager, unoptimized, unsized** — `Avatar.tsx:46`, `AvatarFrame.tsx:23`, `screens/Social.tsx:420`, `screens/Settings.tsx:855,867`, `screens/Admin.tsx:988`, `TopNav.tsx:169`, `SideNav.tsx:109` — every image is a raw `<img>` (0 `next/image`), no `loading="lazy"`, no width/height → wasted bytes + layout shift. Fix: add `loading="lazy"` + intrinsic dimensions; consider a Cloudflare Images loader.
- **[P3] framer-motion eagerly imported into landing + Study** — `HowItWorks.tsx:10` (rendered at `page.tsx:917`), `screens/Study.tsx:5` — ~30-50KB gz statically pulled into the marketing bundle. Fix: `next/dynamic` the motion subtrees or use the existing CSS keyframes.
- **[P3] Spotlight card reads `getBoundingClientRect` on every mousemove** — `page.tsx:543-547`. Fix: cache rect on `mouseenter`/resize.

_Verified-good:_ MarkdownChat / KnowledgeGraph3D / three.js / mermaid / function-plot all lazy-loaded; expensive components `React.memo`'d; 2D graph pauses via IntersectionObserver; achievement watcher polls 60s with cleanup; `UserContext` value memoized; CSS keyframes animate only transform/opacity.

### Theming — 2/4

- **[P0] Canonical brand green `#1B6C42` is not a token** — ~90 occurrences across 6 files (`page.tsx` 24×, `HowItWorks.tsx` 19×, `OnboardingFlow.tsx` 5×, `SignInModal.tsx` 4×, `globals.css:371,870,989`). A brand-color change requires editing 90 call sites. Fix: define `--brand-forest: #1B6C42` and reference it; reconcile with `--sap-*`.
- **[P0] Ten competing "brand greens" with no single source of truth** — see the table below. Fix: collapse to one canonical token + a defined tint scale.
- **[P1] Orphaned dark-mode block can still activate** — `globals.css:603-650` (`html.dark{…}`, `color-scheme:dark`) + a `["light","dark"]` Theme toggle at `screens/Settings.tsx:405`. Dead today (nothing adds `.dark`) but one wire from an off-spec theme. Fix: delete the block + the "dark" option.
- **[P1] Mastery/progress/struggle defined three different ways** — landing tokens `--brand-success/-progress/-struggle` (`globals.css:74-77`) vs inline graph hex `#4a7d5c/#c89b5e/#b25855/#9a9a9a` repeated in `Dashboard.tsx:457-460`, `Tree.tsx:20-23`, `notetaker/page.tsx:57-60` vs rarity greens. Fix: promote one `--state-*` token set.
- **[P1] Glassmorphism token system contradicts the spec** — `globals.css:443-530,784-813` (`.liquid-glass*`, `.glass-panel`, `.glass-input` with `backdrop-filter:blur`). See Anti-Patterns P0.
- **[P1] `Inter` loaded and rendered though outside the approved font set** — `layout.tsx:3,23-27,58`; `--font-inter` + `.font-inter` render on `page.tsx:654,848,894` and `HowItWorks.tsx`. `.impeccable.md` sanctions only Playfair/Spectral/DM Sans. Fix: drop Inter, map `--font-inter` → `var(--font-sans)`.
- **[P2] `bg-clip-text` gradient headings** — `page.tsx:673,791,844,937`. See Anti-Patterns P0; also smuggles in `#2D8F5C` (7×) and `#155A35` (2×).
- **[P2] Duplicated knowledge-graph status palette inline** — `Dashboard.tsx:457-460`, `Tree.tsx:20-23`, `notetaker/page.tsx:57-60`. Fix: single shared constant/token.
- **[P2] One-off alert colors off-system** — `Dashboard.tsx:144` `#e87734`, `:159` `#e94b5c` bypass `--warn`/`--err`.
- **[P3] Hard-coded greens in nav/legal/onboarding** — `#1a5c2a` / `rgba(26,92,42,…)` in `TopNav.tsx`, `SideNav.tsx`, `SignInModal.tsx`, `OnboardingFlow.tsx`, terms/privacy/about/careers, `globals.css:759`.

**The competing greens:**

| Value | Defined as | Where used |
|---|---|---|
| `#1B6C42` | **not a token** (canonical brand) | hard-coded ~90× |
| `#2e7d52` | `--brand-primary` | glass-input focus, rarity override, landing |
| `#3a6a2c` | `--sap-600` | brand scale (app shell) |
| `#4e873c` | `--sap-500` = `--c-sage` = `--rarity-uncommon` | charts, inline hex |
| `#8a9a5b` | `--accent` (olive/sage) | the app's actual UI accent, 177× |
| `#22c55e` | `--brand-success` | landing "success" |
| `#2D8F5C` | **not a token** | gradient-text headings |
| `#1a5c2a` / `#155A35` / `#4a7d5c` | **not tokens** | spinner, nav, hover, graph "mastered" |

### Responsive — 2/4

**Total CSS responsive queries in the entire codebase: 2 `@media` (both `prefers-reduced-motion`), 0 width-based `@media`, 0 `@container`.** All viewport adaptation lives in `useIsMobile.ts` (`matchMedia(max-width:767px)`), used in 7 files.

- **[P1] Admin pages don't reflow on mobile** — `screens/Admin.tsx:398,629,904` — hard-coded `gridTemplateColumns:"minmax(280px,360px) 1fr"`, no `isMobile` branch; overflows ≤375px. Fix: collapse to `1fr` below 768px.
- **[P1] Gradebook is entirely non-responsive** — `Gradebook/*` (0 `useIsMobile` hits); modals at fixed `minWidth:420/460/360` (`AssignmentModal.tsx:76`, `EditWeightsModal.tsx:62`, `SyllabusUploadFlow.tsx:102`, `LetterScaleEditor.tsx:50`) overflow phones. Fix: `width:min(420px,100%-32px)`; route through `Dialog`.
- **[P1] SSR/first-paint renders desktop layout on mobile** — `useIsMobile.ts:8` (`useState(false)`) → desktop shell then a hydration snap (FOUC/CLS). Fix: a CSS `@media` for initial paint, or mobile-first.
- **[P2] Mobile nav touch targets below 44×44** — `TopNav.tsx:141-143` (hamburger ~28-40px), `:472-475` (menu links ~37px), `:217-218,233-234` (settings/admin icons 32×32). Fix: ≥44px hit areas.
- **[P2] SideNav rows / collapse controls sub-44px** — `SideNav.tsx:307` (~31px rows), `:239-240` (24×24 collapse), `:269` (28px expand).
- **[P2] Modals don't lock body scroll** — `Dialog.tsx` (no `useBodyScrollLock`) + all Gradebook modals → scroll-bleed behind overlays on mobile. The `useBodyScrollLock` hook exists but is used by only 5 components. Fix: call it inside `Dialog`.
- **[P3] Settings uses a fixed 180px label column** — `screens/Settings.tsx:259,311`. Fix: stack below ~600px.
- **[P3] Chat/study prose line length not capped** — `MarkdownChat.tsx:203,373`, `screens/Learn.tsx:461`, `about/page.tsx:97` (~110ch). Fix: cap at ~68ch.

_Good:_ consumer flows (Dashboard, Learn, Tree, Study, Library, Calendar, Social) explicitly branch on `isMobile` and reflow well; code blocks / Mermaid / FunctionPlot use `overflowX:auto`; `Dialog` close button is a proper 44×44.

### Anti-Patterns — 1/4

- **[P0] Liquid Glass system — directly named, hard-banned** — `globals.css:443-530,783-813` (`.liquid-glass*`, `.glass-panel`, `.glass-input` with `backdrop-filter:blur(24/40/12px)`); consumed on hero floating cards (`page.tsx:722,734,755,768,772,776`) and onboarding (`OnboardingFlow.tsx:271,313,411,705,723,737`). Violates "No glassmorphism — completely off the table." Fix: solid `--bg-panel` + `--shadow-md`, or delete the floating cards and let the graph canvas carry the hero ("the background IS the personality").
- **[P0] Gradient text on every major heading** — `page.tsx:673,791,844,937` (`bg-gradient-to-r … bg-clip-text text-transparent`, hero + CTA also animate it). Violates "Gradient text on headings (bg-clip-text)." Fix: solid `#1B6C42`/`--ink-800`; reserve green for the words that mean "growth/mastery."
- **[P1] Dark-mode stylesheet despite light-mode-only mandate** — `globals.css:599-650` (`html.dark`, with `--accent-glow` glowing-chrome tokens) + Theme toggle `screens/Settings.tsx:405`; contradicts the file's own comment at `globals.css:127-129`. Fix: delete both.
- **[P1] Hero-metric stat cards** — `page.tsx:726-730,738-751,760-763` (frosted cards: `2,413` nodes, `68% mastered`). Violates "Hero metric layouts." Combines glass + hero-metric. Fix: drop the fabricated stats; use one editorial line if social proof is needed.
- **[P2] Colored side-stripe borders (top universal tell)** — `AchievementUnlockToast.tsx:31` (`borderLeft:3px`), `screens/Social.tsx:380` (`borderLeft:2px`), `flashcards/ParsedCardsTable.tsx:79` (`borderLeft:3px`). Fix: leading dot, tinted background, or icon color instead. (1px structural dividers are fine.)
- **[P2] Blue/cyan accents on light hero cards** — `page.tsx:726,728,760` (`#3B82F6`). Reads as the neon-blue SaaS palette. Fix: shift toward `--info #3e6f8a`.
- **[P2] Pure-white panels instead of tinted** — `globals.css:48,51` (`--bg-panel`/`--bg-input` = `#ffffff`) + ~64 raw `#fff`/`#000` in TSX, while base `--bg` is warm paper. Fix: tint panels a hair off-white.
- **[P3] Overshoot/elastic easing** — `globals.css:410,893` (`cubic-bezier(0.175,0.885,0.32,1.275)`, control point >1) on `.landing-icon-container` hover. Fix: use `--ease`.
- **[P3] Gradient name-color cosmetic** — `screens/Settings.tsx:875` — borderline, but it's an opt-in gamification cosmetic. Note only; acceptable if kept user-selectable.

_Genuine bright spot:_ the feature section (`page.tsx:858-895`) and the app-shell screens already use editorial type hierarchy + hairline dividers rather than tiled icon+heading+body cards — the brand's intended approach is proven out there, so the landing's glass/gradient treatment is an inconsistency to delete, not a system to invent. The single radial `accent-soft → bg` backdrops (`OnboardingFlow`, `pending/page.tsx`, `SignInModal`) are purposeful atmospheric washes and are acceptable.

## Systemic patterns

1. **The pre-auth surface fights the brand; the app shell embodies it.** Glassmorphism, gradient text, hero-metric cards, and the dark-mode orphan are concentrated in the landing + onboarding. The signed-in screens are already on-spec. The fix is mostly **deletion**, not redesign.
2. **The brand green has no canonical token.** Eight greens stand in for "brand/primary/mastery"; `#1B6C42` (the documented primary) is hard-coded ~90×. This is the root cause behind both theming and several anti-pattern findings.
3. **Contrast is a token problem, not a per-component one.** Four shared tokens/classes (`--text-muted`, `--accent` button bg, `.chip--accent`, ModelToggle) drive hundreds of AA failures — fix the tokens once.
4. **Responsiveness is JS-only at one breakpoint.** Zero CSS width queries means SSR always paints desktop (CLS) and there's no tablet tier; data-dense Admin/Gradebook/Settings never got the `useIsMobile` hook.
5. **A good shared primitive exists but isn't adopted.** `Dialog.tsx` (focus trap, responsive width, scroll-lock candidate, 44px close) is the model; ~6 hand-rolled modals bypass it. Same story for `useBodyScrollLock`.
6. **Bundle discipline is genuinely strong** — the team internalized lazy-loading and memoization; the perf gap is hand-rolled RAF/canvas animation, not architecture.

## Positive findings

- `Dialog.tsx` is a well-built accessible modal primitive (focus trap + restore, Escape, `aria-modal`, 44px touch target).
- `prefers-reduced-motion` is respected in CSS **and** in the JS animation loops (AtmosphericBackdrop, KnowledgeGraph3D) — except the landing page.
- Heavy libraries (three.js, mermaid, d3, katex, highlight.js, react-force-graph-3d) are all lazy-loaded; expensive components are `React.memo`'d.
- The app-shell screens use editorial type hierarchy instead of bubble-panel card grids — the brand's intended aesthetic.
- A coherent token system (`--ink-*`, `--sap-*`, `--c-*`, radii, shadows, pads) is consistently used in the signed-in app (177 `var(--accent)`, no raw scale leakage there).

## Recommended actions (priority order)

1. **[P0] `/distill`** — delete the Liquid Glass system + hero-metric stat cards from landing/onboarding; let the graph canvas carry the hero.
2. **[P0] `/typeset`** — replace gradient-text headings with solid brand color.
3. **[P0] theming** — tokenize `#1B6C42` as `--brand-forest`, collapse the 8 greens + 3 status palettes, delete the orphaned dark-mode block + Settings toggle.
4. **[P1] `/audit` → contrast** — darken `--text-muted`, `--accent`-as-button-bg, `.chip--accent`, ModelToggle labels to AA.
5. **[P1] a11y** — restore `:focus-within` rings on inputs; add labels to ChatPanel/search/checkbox controls; give `SignInModal` the `Dialog` focus trap; add `role="img"` + labels to graph/plot/diagram.
6. **[P1] `/adapt`** — make Admin/Gradebook/Settings responsive; route modals through `Dialog`; add `useBodyScrollLock` to `Dialog`; fix sub-44px touch targets; address SSR desktop FOUC.
7. **[P2] `/optimize`** — gate landing RAF behind reduced-motion, drop per-node `shadowBlur`, pre-bake atmospheric orbs, fix the d3-tick re-render, add `loading="lazy"`/`next/image` to user images.
8. **[P2] `/polish`** — side-stripe borders → dots/tints; tint pure-white panels; `--ease` instead of overshoot; map `--font-inter` → DM Sans.

_Re-run `/audit` after fixes to track the score._

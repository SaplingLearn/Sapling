# Sapling — Design Context for Wireframes

This file gives Claude (or any designer/agent) the minimum context needed to
produce **on-brand wireframes** for the Sapling app shell — specifically the
**SideNav** component and a **basic Dashboard wireframe**. It captures
design tokens, layout primitives, IA, and the structural anatomy of both
surfaces. **No functional logic, no data fetching — wireframe only.**

Source of truth (do not duplicate, just reference):
- Tokens: `frontend/src/app/globals.css`
- Sidebar component: `frontend/src/components/SideNav.tsx`
- Shell frame (sidebar + main split): `frontend/src/components/ShellFrame.tsx`
- Dashboard screen: `frontend/src/components/screens/Dashboard.tsx`

---

## 1. Brand voice (visual)

- **Editorial × botanical.** Warm paper neutrals, forest greens, serif
  for soul, sans for function. Calm, not corporate.
- **Light-mode default.** Dark mode tokens exist but the wireframe targets
  light mode only.
- **"Serif for soul, sans for function":** display headings in Playfair
  Display, long-form body in Spectral, all UI chrome in DM Sans, numerals
  and code in JetBrains Mono.
- No gradients on UI chrome. No heavy shadows. Hairline 1px borders at
  ~10% ink opacity.

---

## 2. Design tokens

### 2.1 Typography

| Token            | Stack                                         | Use                            |
|------------------|-----------------------------------------------|--------------------------------|
| `--font-display` | `'Playfair Display', 'Spectral', serif`       | Hero headlines, h1, brand     |
| `--font-serif`   | `'Spectral', 'Playfair Display', serif`       | Long-form prose, tutor voice  |
| `--font-sans`    | `'DM Sans', system-ui, sans-serif`            | All UI chrome, default body   |
| `--font-mono`    | `'JetBrains Mono', ui-monospace, monospace`   | Numerals, micro-labels, code  |

Helper classes:
- `.h-serif` — display heading (Playfair, weight 500, letter-spacing -0.015em)
- `.h-sans` — sans heading (DM Sans, weight 600, letter-spacing -0.005em)
- `.body-serif` — Spectral body for reading surfaces
- `.label-micro` — uppercase mono micro-label, 10px, letter-spacing 0.14em, color `--text-muted`
- `.mono` — JetBrains Mono, ss01 numerals, letter-spacing -0.02em

Body base: 14px, line-height 1.5, color `--text`.

### 2.2 Color — neutrals (warm paper)

| Token       | Hex       | Role                          |
|-------------|-----------|-------------------------------|
| `--ink-0`   | `#faf8f3` | App background (paper)        |
| `--ink-50`  | `#f4f1ea` | Subtle bg, sidebar bg, topbar |
| `--ink-100` | `#ebe6dc` | Soft bg (hovers, chips)       |
| `--ink-200` | `#ddd6c6` | —                             |
| `--ink-300` | `#b9b1a0` | —                             |
| `--ink-400` | `#8a8372` | Muted text                    |
| `--ink-500` | `#5d5749` | —                             |
| `--ink-600` | `#3f3b31` | Dim text                      |
| `--ink-700` | `#2a271f` | —                             |
| `--ink-800` | `#1a1814` | Primary text                  |
| `--ink-900` | `#12110d` | —                             |

### 2.3 Color — brand greens (Sap)

| Token       | Hex       |
|-------------|-----------|
| `--sap-50`  | `#f1f6ee` |
| `--sap-100` | `#e0ecd8` |
| `--sap-200` | `#c3d8b3` |
| `--sap-300` | `#9cbd86` |
| `--sap-400` | `#74a25d` |
| `--sap-500` | `#4e873c` |
| `--sap-600` | `#3a6a2c` |
| `--sap-700` | `#2b5221` |
| `--sap-800` | `#1f3e18` |
| `--sap-900` | `#132610` |

### 2.4 Semantic tokens (light)

| Token              | Value                        | Role                                  |
|--------------------|------------------------------|---------------------------------------|
| `--bg`             | `--ink-0`                    | Page background                       |
| `--bg-panel`       | `#ffffff`                    | Card / panel surface                  |
| `--bg-subtle`      | `--ink-50`                   | Sidebar bg, subtle fills              |
| `--bg-soft`        | `--ink-100`                  | Hover fills, chips                    |
| `--bg-input`       | `#ffffff`                    | Inputs                                |
| `--bg-inset`       | `#f7f3eb`                    | Inset wells                           |
| `--bg-topbar`      | `--ink-50`                   | Topbar surface                        |
| `--border`         | `rgba(42,39,31,0.10)`        | Hairline divider                      |
| `--border-strong`  | `rgba(42,39,31,0.18)`        | Stronger divider                      |
| `--text`           | `--ink-800`                  | Primary copy                          |
| `--text-dim`       | `--ink-600`                  | Secondary copy                        |
| `--text-muted`     | `--ink-400`                  | Muted / labels                        |
| `--accent`         | `#8a9a5b`                    | Sage accent (CTAs, focus, selection)  |
| `--accent-fg`      | `#ffffff`                    | Foreground on accent                  |
| `--accent-soft`    | `--sap-50`                   | Soft accent fill                      |
| `--accent-border`  | `--sap-200`                  | Accent border                         |

Status colors:

| Token         | Hex       | Soft variant     |
|---------------|-----------|------------------|
| `--warn`      | `#b4562c` | `--warn-soft` `#f7e6d8` |
| `--err`       | `#a83a3a` | `--err-soft`  `#f5d8d3` |
| `--info`      | `#3e6f8a` | `--info-soft` `#dfe9ef` |

Mastery palette (for the knowledge graph):

| State        | Hex       |
|--------------|-----------|
| mastered     | `#4a7d5c` |
| learning     | `#c89b5e` |
| struggling   | `#b25855` |
| unexplored   | `#9a9a9a` |

### 2.5 Radii

| Token       | px  |
|-------------|-----|
| `--r-xs`    | 4   |
| `--r-sm`    | 6   |
| `--r-md`    | 10  |
| `--r-lg`    | 16  |
| `--r-xl`    | 22  |
| `--r-full`  | 999 |

### 2.6 Spacing & rows

| Token       | px (default) | compact | spacious |
|-------------|--------------|---------|----------|
| `--pad-sm`  | 10           | 8       | 14       |
| `--pad-md`  | 16           | 12      | 20       |
| `--pad-lg`  | 22           | 16      | 28       |
| `--pad-xl`  | 32           | 22      | 44       |
| `--row-h`   | 40           | 34      | 48       |

### 2.7 Shadows

- `--shadow-sm` — card resting (1px ambient + 1px contact, ink-tinted)
- `--shadow-md` — hovered card / popover
- `--shadow-lg` — modal / overlay
- `--shadow-inset` — inset rim highlight

All shadows use a tinted `rgba(19,38,16, ...)` (sap-900 alpha), never neutral black.

### 2.8 Motion

| Token        | Value                             |
|--------------|-----------------------------------|
| `--ease`     | `cubic-bezier(0.2, 0.7, 0.2, 1)`  |
| `--dur-fast` | 140ms                             |
| `--dur`      | 220ms                             |
| `--dur-slow` | 420ms                             |

Hover/focus transitions use `--dur-fast var(--ease)`. Layout shifts use `--dur var(--ease)`.

---

## 3. UI primitives (used in sidebar + dashboard)

### 3.1 Card

```
.card {
  background: var(--bg-panel);
  border: 1px solid var(--border);
  border-radius: var(--r-lg);   /* 16px */
  box-shadow: var(--shadow-sm);
}
```

### 3.2 Buttons

- `.btn` — base: 8/14 padding, `--r-sm` radius, 13px DM Sans 500, white panel + hairline border.
- `.btn--primary` — sage `--accent` bg, white fg, no border.
- `.btn--ghost` — transparent bg + border, hover fills with `--bg-soft`.
- `.btn--danger` — `--err` text, light err border.
- `.btn--sm` — 5/10 padding, 12px.

### 3.3 Chips

- `.chip` — pill, mono 11px uppercase, `--bg-soft` bg, `--text-dim` text.
- Variants: `.chip--accent`, `.chip--warn`, `.chip--err`, `.chip--info`.

### 3.4 Skeleton

- `.skeleton` — shimmering gradient between `--bg-soft` and `--bg-subtle`.

### 3.5 Focus ring

`outline: 2px solid var(--accent); outline-offset: 2px; border-radius: 3px;`

---

## 4. Sidebar (SideNav) — wireframe spec

The sidebar is the primary nav for the signed-in app. It has two states:
**expanded (232px)** and **collapsed (64px)**, with width persisted to
localStorage. It uses warm paper bg, a hairline right border, and 4 grouped
sections of icon-+-label nav links.

### 4.1 Geometry

| Token / value          | Expanded | Collapsed |
|------------------------|----------|-----------|
| Width                  | 232 px   | 64 px     |
| Padding                | 16/10    | 16/6      |
| Background             | `--bg-subtle` | same |
| Right border           | 1px `--border` | same |
| Height                 | `100vh`  | `100vh`   |
| Section gap            | 2 px     | 2 px      |
| Width transition       | `width var(--dur) var(--ease)` | — |

### 4.2 Anatomy (top → bottom)

```
┌──────────────────────┐
│  [icon]  Sapling     │  ← Logo block
│  ─────────────────   │     32px sap icon + Playfair "Sapling" 20px
│                      │     (logo only, no wordmark when collapsed)
│  LEARN               │  ← .label-micro (10px mono uppercase, muted)
│  ⌂  Dashboard        │  ← NavLink — active: --bg-soft fill + --text + 600
│  🧠  Tutor           │     Inactive: transparent + --text-dim + 400
│  ⚗  Quiz             │     Hover: text → --text (no bg change)
│  🌳  Tree            │
│  ⚡  Study           │
│                      │
│  ORGANIZE            │
│  📖  Library         │
│  📅  Calendar        │
│                      │
│  COMMUNITY           │
│  👥  Social          │
│  🏆  Achievements    │
│                      │
│  TOOLS               │
│  ⭐  Grades          │
│  ✏  Notetaker        │
│  📋  Course Planner  │
│                      │
│        (flex spacer) │
│                      │
│  ⚙   Settings        │  ← Pinned to bottom
│  🛡   Admin          │     (admin row only if isAdmin)
│  ───────────────     │
│  [avatar] Name    >  │  ← Footer: avatar 30px + name + role
│           Account    │     "Account" sub-line (11px muted)
│                      │     Chevron toggles collapse
└──────────────────────┘
```

NavLink anatomy:
- Padding: `8px 12px` expanded, `8px 0` collapsed (icon-only, centered).
- Border-radius: `--r-sm` (6px).
- Icon size: 15 px. Label size: 13 px DM Sans.
- Active state: bg `--bg-soft`, color `--text`, weight 600.
- Inactive state: transparent, color `--text-dim`, weight 400.
- Tooltip (`title=`) shows label when collapsed.

Section labels (`LEARN`, `ORGANIZE`, etc.):
- Use `.label-micro` (10px mono uppercase, `--text-muted`).
- Padding `4px 10px` for first, `14px 10px 4px` for following.
- Replaced by a 1px hairline divider when collapsed.

Footer:
- 1px top border, padding `10px 6px 4px`.
- Avatar (30px circle) + name + "Account" sub-line.
- Collapse/expand chevron button: 24×24, ghost hover.

### 4.3 Navigation IA (full list, in order)

| Section    | Items                                  |
|------------|----------------------------------------|
| Learn      | Dashboard · Tutor · Quiz · Tree · Study|
| Organize   | Library · Calendar                     |
| Community  | Social · Achievements                  |
| Tools      | Grades · Notetaker · Course Planner    |
| Footer     | Settings · Admin (conditional)         |

Active-route logic: a route is "active" if pathname equals href OR starts with `href + "/"`. Dashboard is also active at `/`.

---

## 5. Dashboard — basic wireframe spec

The dashboard is the **arrival page**. It opens with a typed greeting +
quote, then presents a 2-column layout: knowledge graph on the left,
streak/sessions/upcoming on the right. (A 3-column legacy variant exists
for the top-nav layout — out of scope for this wireframe.)

### 5.1 Page chrome

- Lives inside `ShellFrame` (sidebar + scrollable `<main>`).
- Page padding: `18px 32px 24px` desktop, `8px 20px 16px` mobile.
- Outer layout: vertical flex column, `min-height: 100%`.

### 5.2 Two-column grid (default sidebar layout)

```
gridTemplateColumns: minmax(0, 1fr) minmax(280px, 360px)
gap: 16
align-items: stretch
```

Mobile (< 768px): single column, sections stacked.

### 5.3 Anatomy — left column ("mainColumn")

```
┌─────────────────────────────────────────────────┐
│  Good morning, Andres                          │  ← Hero (h-serif, 42px)
│   ↑ typewriter, sage cursor "|" weight 200      │
│                                                 │
│  "Learning is the only thing the mind never     │  ← Quote (body-serif, italic, 14px, --text-dim)
│   exhausts…" — da Vinci                         │     fades in 300ms after typing finishes
├─────────────────────────────────────────────────┤
│  ┌───────────────────────────────────────────┐  │
│  │ YOUR KNOWLEDGE GRAPH        [⤢ fullscreen]│  │  ← Card header
│  │ 124 concepts across 4 courses             │  │     label-micro + h-serif 20px
│  │ ─────────────────────────────────────────  │  │
│  │                                           │  │
│  │            ●                              │  │
│  │       ●  ─ ● ─ ●                          │  │  ← Knowledge graph canvas
│  │           ●                               │  │     min-height 260, flex: 1
│  │                                           │  │
│  │                       ┌──────────────────┐│  │
│  │                       │  MY COURSES   +  ││  │  ← Floating courses key
│  │                       └──────────────────┘│  │     (collapsible, no card chrome)
│  │  ● mastered  ● learning  ● struggling…    │  │  ← Legend (bottom-left, 11px muted)
│  └───────────────────────────────────────────┘  │
└─────────────────────────────────────────────────┘
```

Greeting block:
- Heading: `.h-serif`, 42px desktop / 34px mobile, `--text`, letter-spacing `-0.02em`.
- Greeting text format: `"Good morning, {firstName}"` (or `"Welcome back"` if no name). Time-of-day prefix: morning < 12, afternoon < 17, else evening.
- Typewriter: 55 ms/char, sage `|` cursor (weight 200) blinks 530 ms then disappears 300 ms after completion.
- Quote: `.body-serif`, 14px italic, `--text-dim`, max-width 640, fades + slides in once typing settles.

Graph card:
- `.card` with padding 0, overflow hidden.
- Header: 16/22 padding, hairline bottom border.
- Header left: `.label-micro` "Your knowledge graph" + `.h-serif` 20px count line.
- Header right: ghost icon button (fullscreen).
- Canvas: flex: 1, min-height 260.
- Legend pinned bottom-left, 11px `--text-muted`, color dots 10px.
- Optional courses-key panel pinned bottom-right (no card chrome — uses white text-stroke for legibility over graph).

### 5.4 Anatomy — right column ("rightPanel")

A vertical stack of 3 cards + an action row at top.

#### Action row (desktop only)
- Right-aligned, gap 8.
- `[🔍 Search]` ghost btn → /library
- `[✨ Start learning]` primary btn → /learn

#### Card 1 — Streak + Mastered (split 50/50 grid)

```
┌─────────────────────────┬──────────────────────┐
│  STREAK                 │  MASTERED            │
│                         │                      │
│  7 days                 │  42                  │
│  ↑ h-serif 32px, --warn │  ↑ h-serif 32px      │
│  Personal best: 7       │  of 124 concepts     │
└─────────────────────────┴──────────────────────┘
```

- Card padding: 0 outer, 16/18 each cell.
- Cells separated by 1px `--border`.
- Big numbers: `.h-serif` 32px, weight 600, line-height 1.
- Streak count is `--warn` if > 0, else `--text`.
- Sub-line: 11 px `--text-muted`.

#### Card 2 — Where you left off (recent sessions)

```
┌──────────────────────────────────────────────┐
│  TODAY                            [View all] │
│  Where you left off                          │  ← .h-serif 16px
│                                              │
│  [🧠] Photosynthesis                       › │  ← Each item: bg --bg-subtle,
│       BIO-101 · socratic · 2h ago            │     padding 10/12, radius --r-md
│                                              │
│  [🧠] Linear Algebra Basics                › │
│       MAT-220 · explain · yesterday          │
│                                              │
│  [🧠] Romanticism                          › │
│       ENG-201 · quiz · 3d ago                │
└──────────────────────────────────────────────┘
```

- `.card`, padding `var(--pad-lg)`.
- Header: `.label-micro` left, ghost btn right.
- Items: button rows on `--bg-subtle` fill, 6px gap, ellipsised topic + meta.
- Empty state: 12px `--text-muted` line.

#### Card 3 — Upcoming assignments

```
┌──────────────────────────────────────────────┐
│  UPCOMING                       [Calendar →] │
│  ─────────────────────────────────────────── │
│  Lab Report 3                       [3D]     │  ← chip--info
│  CHEM-200 · lab                              │
│  ─────────────────────────────────────────── │
│  Problem Set 7                      [12H]    │  ← chip--err  (≤24h)
│  MAT-220 · problem set                       │
│  ─────────────────────────────────────────── │
│  Essay Outline                      [2D]     │  ← chip--warn (≤2d)
│  ENG-201 · essay                             │
│  ─────────────────────────────────────────── │
│  Reading                            [OVERDUE]│  ← chip--err
│  HIS-101 · reading                           │
└──────────────────────────────────────────────┘
```

- `.card`, padding `var(--pad-lg)`.
- Each row: 8/0 padding, 1px `--border` bottom.
- Title: 13px weight 500. Meta: 11px muted.
- Status chip (right):
  - Overdue → `chip--err` "OVERDUE"
  - ≤ 1h → `chip--err` "NOW"
  - ≤ 24h → `chip--err` "{H}H"
  - ≤ 2 days → `chip--warn` "{D}D"
  - else → `chip--info` "{D}D"

### 5.5 Optional "Try this next" suggest banner

Placed between hero and graph when present. Accent-soft fill, accent border.

```
┌─────────────────────────────────────────────────────────────┐
│ ✨  Try this next: Photosynthesis · Biology  [Start quiz]✕  │
└─────────────────────────────────────────────────────────────┘
```

- `.card.fade-in`, padding 14/18, gap 14, align center.
- Background `--accent-soft`, border `--accent-border`.
- Right side: primary "Start quiz" + ghost "Dismiss".

### 5.6 Skeleton / loading state

While first load runs, render `<DashboardSkeleton />` (shimmer blocks
matching the 2-column layout). Empty states use 12px `--text-muted` copy
with an inline CTA.

---

## 6. Icon system

Icons are line-based, 14–16px in chrome. Used throughout sidebar + dashboard:

| Name      | Use                                |
|-----------|------------------------------------|
| `home`    | Dashboard nav                      |
| `brain`   | Tutor / Learn                      |
| `flask`   | Quiz                               |
| `tree`    | Tree (knowledge map)               |
| `bolt`    | Study / quick actions              |
| `book`    | Library                            |
| `cal`     | Calendar                           |
| `users`   | Social                             |
| `trophy`  | Achievements                       |
| `star`    | Grades                             |
| `pencil`  | Notetaker                          |
| `planner` | Course Planner                     |
| `cog`     | Settings / manage                  |
| `shield`  | Admin                              |
| `chev`    | Chevron / expand-collapse          |
| `search`  | Library / search CTA               |
| `sparkle` | Start learning / "try this next"   |
| `max`     | Fullscreen                         |
| `plus`/`x`| Add / close                        |

---

## 7. Wireframe deliverable checklist

When generating the wireframe, the output should:

- [ ] Use the **light** palette only (paper bg `--ink-0`, panels white).
- [ ] Render the **sidebar at 232px expanded** with all 4 sections + footer.
- [ ] Render the **dashboard 2-column grid** (graph on left, 3 cards on right).
- [ ] Use **DM Sans** for chrome, **Playfair Display** for hero, `.label-micro` (uppercase mono) for section labels.
- [ ] Match radii: `--r-lg` (16px) on cards, `--r-sm` (6px) on buttons + nav rows, `--r-full` on chips and progress bars.
- [ ] Hairline 1px `--border` (~10% ink) for all dividers — never solid black.
- [ ] Shadows are subtle (`--shadow-sm`) and tinted with sap-900 alpha, not neutral black.
- [ ] Show **active nav state** on Dashboard row: `--bg-soft` fill, `--text` color, weight 600.
- [ ] No gradients on UI chrome. No emoji. No dark mode.
- [ ] **Wireframe scope only** — placeholder copy, no live data, no interactions, no logic.

---

## 8. Quick reference snippets

```css
/* Card */
background: var(--bg-panel);
border: 1px solid var(--border);
border-radius: var(--r-lg);
box-shadow: var(--shadow-sm);

/* Section label (sidebar + dashboard) */
font-family: var(--font-mono);
font-size: 10px;
letter-spacing: 0.14em;
text-transform: uppercase;
color: var(--text-muted);

/* Hero greeting */
font-family: var(--font-display);  /* Playfair Display */
font-size: 42px;
font-weight: 600;
letter-spacing: -0.02em;
line-height: 1.15;
color: var(--text);

/* Active nav row */
background: var(--bg-soft);
color: var(--text);
font-weight: 600;
border-radius: var(--r-sm);
padding: 8px 12px;

/* Idle nav row */
background: transparent;
color: var(--text-dim);
font-weight: 400;
```

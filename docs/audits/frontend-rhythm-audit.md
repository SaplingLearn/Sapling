# Frontend Rhythm & Consistency Audit

**Date:** 2026-06-30
**Scope:** `frontend/src` — the public/pre-auth surface (landing + beta signup), the onboarding ("get started") flow, the `pending`/waitlist screen, and the signed-in app shell.
**Method:** Read the design-token source (`globals.css`), the route/layout structure, and characterized the styling DNA of each zone against a fixed baseline.
**Baseline / source of truth (per your direction):** the **dashboard + inner app shell**. Everything else is measured against it.

---

## TL;DR

The app isn't running on one design system — it's running on **two**, plus a **transitional no-man's-land** between them. A new user crosses **three** different visual rhythms before they reach the app:

```
  ZONE 1 — Pre-auth / marketing        ZONE 2 — Transition           ZONE 3 — The app (source of truth)
  landing + beta modal + sign-in       onboarding + pending          dashboard, learn, library, …
  ──────────────────────────────       ────────────────────          ──────────────────────────────────
  cool "main" palette                  app palette (warm)            warm forest/ink editorial
  Playfair 44–48px, italic accents     .h-serif 32/26px (bespoke)    .h-serif 30/42px (token scale)
  rounded-full pill + INFINITE glow     plain .btn / .btn--primary    .btn--primary, 6px radius
  mesh blobs, shimmer, float (∞)        calm transitions              calm, event-driven only
  inline 24px-radius warm-gradient box  centered card in a void       .card, 16px, in shell layout
  cool slate shadows rgba(15,23,42)     —                             green shadows rgba(19,38,16)
  HIGH marketing energy                 quiet, orphaned               calm, gridded, structured
```

The root cause is **documented tech debt** in `globals.css:726–732`:

> *"PRE-AUTH (sign-in / landing) THEME — scoped to `.landing-page` only. This block themes the public, pre-auth surface … and intentionally does NOT touch the signed-in app shell tokens. **To be revisited and consolidated with the rest of the design system in a follow-up pass.**"*

That follow-up pass never happened. Your instinct is correct, and it's traceable to a specific architectural seam — not a vague "feels off."

---

## The crux: same token name, different value

Because the pre-auth surface re-declares semantic tokens **inside the `.landing-page` scope**, identical class names render differently on either side of the sign-in boundary. This is *why* it feels like two products even where the markup matches.

| Token | App shell value (`:root`) | Pre-auth value (`.landing-page`) | Effect |
|---|---|---|---|
| `--border` | `rgba(42,39,31,0.10)` (warm) | `rgba(107,114,128,0.18)` (cool slate) | borders read warm in-app, gray in pre-auth |
| `--text-muted` | `#6f6857` (warm taupe) | `#4b5563` (cool slate) | secondary text changes temperature |
| `--text` | `--ink-800 #1a1814` (warm near-black) | `#111827` (cool near-black) | even the primary ink is a different hue |
| `--shadow-sm/md/lg` | green-tinted `rgba(19,38,16,…)` | slate-tinted `rgba(15,23,42,…)` | shadows are warm in-app, cool in pre-auth |
| `--dur-fast` | `140ms` | `120ms` | same-named timing token, different speed |
| `--dur-slow` | `420ms` | `350ms` | motion is subtly snappier in pre-auth |
| `--bg-panel` | `#fdfcf9` | `#f8fbf8` | surface white shifts warm→cool |

`globals.css:60–64, 135–138, 146–149, 762–789`

And the radius tokens don't even share names — the app uses `--r-xs…--r-xl`, the pre-auth uses `--radius-sm…--radius-full` (`globals.css:128–133` vs `779–782`) — despite holding the **same values**. Pure duplication that guarantees drift.

> **Takeaway:** a component literally cannot be moved between the two zones without being re-tokenized. The seam is baked into the variable layer.

---

## Source of truth — the app-shell "house style"

This is the rhythm everything should converge toward.

| Dimension | Canonical pattern | Where |
|---|---|---|
| **Layout** | Shell with `SideNav`/`TopNav` + scrolling `<main>`; content left-aligned, page padding `18px 32px 24px`, constrained by grids (e.g. `minmax(0,1fr) 320px`) | `ShellFrame.tsx`, `Dashboard.tsx:962`, `TopBar.tsx` |
| **Page titles** | **always** `.h-serif` (Playfair) — TopBar h1 `30/500`, hero `42/600` | `TopBar.tsx:35`, `Dashboard.tsx:633` |
| **Eyebrow labels** | `.label-micro` (mono, 10px, uppercase, `0.14em`) | `globals.css:219`, `Dashboard.tsx:393` |
| **Body / chrome** | DM Sans for all UI; Spectral (`.body-serif`) only for tutor prose; JetBrains Mono for numerals | `globals.css:179–184` |
| **Primary button** | `.btn--primary` → solid `--brand-forest #1B6C42`, radius `--r-sm` (6px), 13px, **no** animation | `globals.css:205`, `Dashboard.tsx:493` |
| **Secondary** | `.btn--ghost` / `.btn--sm`; danger = `.btn--danger` | `globals.css:207–210` |
| **Cards** | `.card` → `--bg-panel`, 1px `--border`, radius `--r-lg` (16px), `--shadow-sm`, padding from `--pad-*` | `globals.css:212–215` |
| **Spacing** | `--pad-*` tokens, **density-aware** via `data-density="compact"` | `globals.css:140–161` |
| **Color** | warm ink neutrals + forest green primary + sage `--accent #8a9a5b` | `globals.css:40–67` |
| **Motion** | brief, event-driven: `.fade-in`/`.slide-up` 220–420ms, staggered `.anim-d*`. **No infinite loops, no glow, no mesh.** | `globals.css:224–237` |

**Voice in one line:** *warm, paper-like, serif-titled, calm, gridded, left-aligned.*

---

## Documented inconsistencies

Severity: **P0** breaks product identity / first impression · **P1** clearly visible rhythm break · **P2** systemic drift / rot · **P3** polish.

### [P0] A. Three (really five) different greens for "primary"
The single most brand-defining color is inconsistent across the funnel.

| Where | Green | Token / source |
|---|---|---|
| App primary CTA | `#1B6C42` | `--brand-forest` (`.btn--primary`) |
| Beta CTA fill | `#2D8F5C` | `--brand-forest-bright` (`app/page.tsx:783`) |
| Beta glow ring | `≈#4A9E5C` | `rgba(74,158,92,…)` — matches **neither** (`globals.css:1002`) |
| Pre-auth "main" primary | `#2e7d52` | `--brand-primary` (`globals.css:738`) |
| Pre-auth "success" | `#22c55e` | `--brand-success` (near-neon) (`globals.css:739`) |

Plus sage `--accent #8a9a5b` for highlights. A first-time user's *first* green (glowing beta pill) is a different green from their *first in-app* green (flat forest rectangle).
**Fix:** collapse to one primary (`--brand-forest`) + one bright hover; delete `--brand-primary`/`--brand-success` or alias them to the canonical scale; derive the glow from the same token.

### [P0] B. The button is a different *species* before vs after sign-in
- **Beta CTA** (`app/page.tsx:779–787`): `rounded-full` pill, `px-10 py-4`, 16px, `--brand-forest-bright`, `.landing-btn-shimmer` **+ infinite `.beta-glow-btn` pulse** (`beta-glow 2.2s … infinite`, `globals.css:1005`).
- **App primary** (`globals.css:205`): rectangular, 6px radius, 13px, solid forest, **no motion**.

The first button a user ever clicks sets the expectation for "what a button is here" — and it's contradicted two screens later.
**Fix:** the beta CTA should be a confident, *static* forest button in the app's button language (lose the infinite glow; a one-shot entrance is fine). Reserve "pill" for genuine pill contexts only.

### [P1] C. Onboarding is color-correct but **structurally orphaned**
The *active* flow (`screens/Onboarding.tsx`) actually uses app tokens (`.card`, `.btn--primary`, `.h-serif`, `var(--accent)`) — good. But:
- It's a **centered card floating in a radial-gradient void** (`background: radial-gradient(ellipse at top, var(--accent-soft)…)`, `Onboarding.tsx:164`), with **no shell chrome**. The app is left-aligned and gridded; onboarding is centered-in-space. Different *layout paradigm*.
- **Hard-coded px spacing** (`40px 20px`, `40px 36px`, `marginTop:32`, `gap:6` — `Onboarding.tsx:171,179,245`) instead of `--pad-*`. Not density-aware; drifts from the system.
- **Bespoke type scale** (`.h-serif` at 32/26px) that matches neither TopBar's 30 nor any documented step.

So it reads as "adjacent to" the app rather than "part of" it.
**Fix:** adopt `--pad-*` spacing + the shell's type scale; consider rendering onboarding inside a real shell-like frame (or at least the app's left-aligned container) rather than a centered void.

### [P1] D. The `pending`/waitlist page is a product-identity whiplash
Beta signup = *"come join the movement"* (warm gradient box, Playfair 44px, pulsing glow). Two seconds later, `pending` = *"wait quietly"* — bare centered flex, `.h-serif 36px`, plain `.btn`, radial-gradient void, **no card, no shell, no confirmation moment** (`pending/page.tsx:15–40`). Same user, same minute, two products. There's no "you're in ✓" beat bridging the energy drop.
**Fix:** give `pending` the same surface language as the rest (a `.card`, app spacing) and add a brief success/confirmation moment so the glow resolves into something rather than vanishing into silence.

### [P1] E. "The box that holds content" has 3+ treatments
- App: `.card` → 16px radius, warm `--border`, green-tinted `--shadow-sm`, `--bg-panel`.
- Beta modal (`app/page.tsx:975`) & sign-in modal (`SignInModal.tsx:224`): inline `borderRadius: 24`, warm gradient `linear-gradient(145deg,#d5e8d8,#e8f0e3,#f0ebe0)`, **cool** `rgba(15,23,42,…)` shadow, two-column grid — and the two duplicate the same inline block instead of sharing a component.
- Onboarding: `.card`, but centered in a void.
- Pending: no container at all.

**Fix:** one surface primitive. If pre-auth wants a richer "hero card," make it a named variant of `.card`, not an inline one-off copied twice.

### [P1] F. Typography access pattern + scale diverges
Same fonts, two systems:
- App uses **semantic classes** (`.h-serif`, `.label-micro`, `.body-serif`) at a controlled scale.
- Pre-auth uses **utility classes** (`.font-playfair`, `.font-jetbrains`) with **inline px** at much heavier weights (Playfair 44–48px / **700–800** with italic brand-green words — `app/page.tsx:1022,1070`).

The marketing weight/scale is legitimately "louder," but nothing in the type ramp connects the two, so the hand-off is abrupt.
**Fix:** define the display scale once as tokens/classes; let pre-auth use the *top* of the same ramp rather than a parallel one.

### [P2] G. Animation energy is inverted at the worst moment
The **only** persistent motion in the entire product lives in the pre-auth zone: `beta-glow` (∞), `sapling-blob` mesh (`10s` ∞, `globals.css:831`), `landing-card-float` (∞), shimmer. The app itself is deliberately still. So the experience *peaks* in restlessness right before dropping into calm — the reverse of a settling arc.
**Fix:** dial pre-auth motion down to one or two purposeful, finite moments; let the calm of the app feel *earned*, not like the lights got turned off.

### [P2] H. Two token namespaces guarantee future drift
`--r-*` vs `--radius-*`, `--ease` vs `--ease-out/--ease-in-out`, `--dur` vs `--dur-base`, and the value-shadowing in the crux table above. Every new shared component has to pick a side.
**Fix:** one namespace. Map pre-auth's needs onto the app tokens (or vice-versa) and delete the duplicates. This is the structural fix that makes A–G *stay* fixed.

### [P2] I. Dead / duplicated implementations (rot)
- `components/OnboardingFlow.tsx` (**36 KB, unused**) — an older onboarding with the *landing* DNA (hard-coded hex, `var(--font-playfair)`, text-shadows, `.ob-card-in`). Not imported by the active route. Risk: someone edits the wrong onboarding.
- Beta modal and sign-in modal duplicate the same inline gradient card (see E).
**Fix:** delete `OnboardingFlow.tsx` (or fold its good ideas into the active flow); extract the shared pre-auth card.

### [P3] J. Modal-first patterns for high-intent moments
Beta signup and sign-in are both modals over the landing. Per the project's own design guidance, modals are a last resort. Not urgent, but worth questioning whether "sign up for beta" deserves a dedicated, on-brand page rather than a glowing-pill-triggered overlay.

---

## Remediation sequence (suggested)

**Structural (do these first — they make the rest stick):**
1. **Unify the token layer (H + crux).** One namespace, one set of semantic values; stop re-declaring `--border`/`--text`/`--shadow`/`--dur` inside `.landing-page`. If pre-auth needs a cooler palette, that should be a *deliberate* sub-theme, not an accidental shadow of the same names.
2. **Collapse the greens (A).** One primary, one bright, one derived glow.

**Visible wins:**
3. **Re-skin the beta CTA + signup to the app's button/surface language (B, E).** Lose the infinite glow; share one card primitive with sign-in.
4. **Re-home onboarding + pending into the app's layout/spacing/type (C, D).** Add the missing "you're in" confirmation beat.

**Cleanup:**
5. **Delete `OnboardingFlow.tsx`; extract the shared pre-auth card (I).**
6. **Normalize pre-auth motion to finite, purposeful moments (G).**

---

## Note on what's already *right*

- The active onboarding flow is **token-disciplined** (no hard-coded hex, uses `.card`/`.btn--primary`) — it's closer to correct than it feels; its problem is *layout*, not *color*.
- The `pending` page correctly uses **app tokens** rather than the landing set — it just needs the app's *surfaces*.
- Glassmorphism was already removed (#102) and the class names kept as solid surfaces — good discipline.
- The app shell itself is genuinely cohesive: a clear warm-editorial voice with disciplined `.h-serif` titles, one button family, and a real spacing token system. It is a strong source of truth to converge on.

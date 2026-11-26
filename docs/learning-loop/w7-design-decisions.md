# W7.D1 — Quiz reskin design decisions

**Status:** resolved for W7.1 (2026-11-23)  
**Branch:** `feat/learning-loop-reland`  
**Inputs:** `quiz-shell-port-map.md`, design package `HANDOFF.md` + `notes/repo-findings.md`, production `globals.css` / quiz CSS, plan § W7  

Closes the open product questions that were blocking shell CSS. W7.1 agents follow the **W7.1 now** column; deferred items stay out of the first chrome PR.

---

## Decisions table

| # | Question | Decision | Rationale (design system + loop) | W7.1 now? |
|---|---|---|---|---|
| 1 | Brand-forest accent vs `--quiz-accent` | **Split.** Session chrome / primary actions / progress fill use brand forest (`--brand-forest` / `--accent`). Keep binding `--quiz-accent` to the active **course colour** for identity only (meta course label, concept pill / blob tint, results course rule). Do **not** paint Check, wager-on, or the top progress bar with the course tint. | Handoff + plan: focus session accent = forest, not old per-course chrome. Design system: forest = growth / primary CTA; course colours already mean “which class” on Tree / Hub. Loop integrity: multi-course or queue hops must not rebrand the whole shell. Production already has the `--quiz-accent` seam — narrow its role, don’t delete it. | **Yes — follow split** |
| 2 | XP / streak in session top bar | **Drop from session top bar.** Keep XP · streak on **session summary / `QuizResults`** only (existing `useGamificationDelta` / submit payload). Top bar = X · course+topic · Question N of M + bar · `?`. | Live mid-session XP is design-kit demo math (per-question wager lines); production awards on submit. Loop core rule: graded checks / mastery, not XP, are the belief signal — a live tally pulls attention off the item. Results already own the honest delta. Revisit only if product ships per-question award on the wire. | **Yes — omit XP/streak chrome** |
| 3 | Question container: card vs open | **Open** for Practice / default shell. Question column sits on `--bg` (type + spacing hierarchy). Reserve `.card` for **feedback / hint / leave / drawers** (interaction panels), matching today’s verdict card. Exam Twin may later use a framed “sheet” (kit already has `cardBg` / radius overrides) — that is **W7.8**, not W7.1. | Design system audit: “hierarchy through type, not cards.” Handoff defaulted to a card only because the question was undecided. Tall kit states scrolling inside a card fights focus-mode full-bleed. Open matches current `question.css` column. | **Yes — open body; no question card wrapper** |
| 4 | Definitive / Mixed / Conceptual selector | **Stay omitted.** Do not add that three-way control to home, launcher, or session. Unrelated: keep existing **answer Format** control (MC / short / numeric / algebra / Mixed) in `QuizSettings`. | Handoff user “go ahead” + plan § W7 “already accepted.” Pedagogy of item kind is planner / generation / flags, not a student Definitive↔Conceptual dial. | **Yes — omit** |
| 5 | MATH 151 concept list (launcher empty / new-course) | **Resolved in W7.D3** — see [`w7-d3-launcher-map.md`](./w7-d3-launcher-map.md). Design fixtures may show only **Derivatives** / **Chain Rule** (or real seed/catalog). Production never invents a fake MATH 151 list — empty course → honest `HomeStates`. | Port-map hard rule: empty library ≠ fake concepts. Full concept inventory is data (upload graph / seed packs / catalog), not shell chrome. Blocks Map empty-course polish (W7.10), not focus-mode chrome. | **No — out of W7.1** |

---

## Detail notes (for implementers)

### 1 — Accent split (CSS contract)

```text
--accent / --brand-forest     → Check, primary buttons, progress fill, wager “on”, focus rings on actions
--quiz-accent (= course hex)  → course identity chips, concept pill accent, results left rule when course-tinted
fallback: var(--quiz-accent, var(--accent)) stays valid for primitives used outside a bound quiz root
```

`QuizScreen` continues to set `--quiz-accent` from `colorFor` / course colour. Shell tokens that were course-tinted in the old rail should be retargeted to forest where they are chrome, not identity.

### 2 — Gamification placement

| Surface | XP / streak |
|---|---|
| Focus session top bar (W7.1) | Absent |
| Per-question feedback panel | No invented XP line (wager UI maps to A132 confidence only — W7.4) |
| `QuizResults` / session summary | Keep existing “+N XP · K-day streak” |

### 3 — Card budget

- **In:** verdict / hint / leave dialog / study-guide drawer panels.  
- **Out:** wrapping the stem + answer options in `.card` for Practice.  
- **Later (W7.8):** Exam Twin may opt into a framed sheet without flipping Practice to card.

### 4 — Selector naming trap

“Mixed” in Settings = **answer format mix**. It is not the omitted Definitive / Mixed / Conceptual taxonomy. Do not merge them in copy or controls.

### 5 — Empty / new-course states

Until W7.D3 supplies design frames + a seed-backed list:

- Launcher / home empty → existing honest empty copy (`HomeStates`).  
- Design-only MATH 151 frames → Derivatives + Chain Rule is enough; do not expand inventively in docs or code.

---

## W7.D1 browser verify checklist (human)

Open these under  
`~/Downloads/Design system audit and implementation (1)/`  
in a normal browser tab (single-frame / `only=` where needed; avoid zoom-capturing 30+ frame pages — handoff gotcha). No automation required for this pass.

| Priority | File | Why |
|---|---|---|
| P0 | `Quiz Shell.dc.html` | Session chrome reference for W7.1 (confirm open vs card feel, top bar without relying on XP) |
| P0 | `Quiz Session.dc.html` | Start / leave / generating / summary |
| P0 | `Quiz Component Library.dc.html` | Tokens, empty states, mastery blobs |
| P1 | `Quiz Components 7.1-7.3.dc.html` | Already had a clipping pass; spot-check open layout |
| P1 | `Quiz Components 7.4-7.6.dc.html` | Unchecked |
| P1 | `Quiz Components 7.7-7.9.dc.html` | Unchecked |
| P1 | `Quiz Components 7.10-7.12.dc.html` | Unchecked |
| P1 | `Quiz Components 7.13-7.15.dc.html` | Unchecked |
| P2 | `Quiz Components 7.16-7.18.dc.html` + `Sapling Quiz Components 7.16-7.18.html` | Icons / mic; bundler warned on assets |
| Soft (W7.9) | `Study Hub.dc.html`, `Study Guide.dc.html`, `Settings.dc.html` | Soft for W7.1; product contract in [`w7-d2-hub-guide-settings.md`](./w7-d2-hub-guide-settings.md) |

Supporting (do not treat as pixel source of truth for React): `quiz-kit.js`, `quiz-data-4.js`, `quiz-data-5.js`, `sapling-graph.js` (graph already ported in-app).

---

## Supersedes / pointers

- Resolves open rows in `quiz-shell-port-map.md` §5 (accent, XP/streak, card vs open, Definitive selector) and MATH 151 **deferral**.  
- Aligns with plan § W7 “Design decisions already accepted” and tightens the accent/XP/card rows that still said “confirm”.  
- W7.D5 (Ask / confidence / loop flags in shell) remains a separate integration checklist — not reopened here beyond “wager → A132, no mid-session XP”.

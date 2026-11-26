# W7.D2 — Hub / Guide / Settings quiz design

**Status:** resolved for W7.9 (2026-11-23)  
**Branch:** `feat/learning-loop-reland`  
**Inputs:** `w7-design-decisions.md` (W7.D1), `quiz-shell-port-map.md`, design package `HANDOFF.md` §4A + `notes/repo-findings.md`, plan § W7.9 / W8.3 / W8.6  
**Design frames (reference only):** `~/Downloads/Design system audit and implementation (1)/` — `Study Hub.dc.html`, `Study Guide.dc.html`, `Settings.dc.html` (work visual additions on **copies**; do not treat recreation originals as the port source of truth)

Closes HANDOFF steps 8–9 product questions so W7.9 can ship without a parallel ranking brain or a second prefs store. W7.1 shell chrome stays unblocked. Pixel polish of DC copies may continue in parallel; this doc is the **integrity contract**.

---

## Decisions table

| # | Surface | Decision | Rationale (tokens + loop) | W7.9 now? |
|---|---|---|---|---|
| 1 | Study Hub header **Quiz** button | **Open Quiz home / launcher for the active course** — same path as today: `useToolNav.toolHome("quiz")` → `buildQuizHref({ course }, { kind: "link", returnTo: study })` with **no** `start=1`. Once W7.3 / W7.10 land, that home *is* the launcher (plan-ranked list + Map). Do **not** add `/quiz/launcher` or a second ranking client. | HANDOFF: “header Quiz button opens the Launcher.” Port-map hard rule: launcher reuses `getQuizPlan` / `useQuizHome` (or a thin shared `useQuizPlan`). `hide_quiz` still hides the tool. Course tint on the hub tool chip (`#EBDDEE` / plum) stays identity chrome; session chrome stays brand forest (W7.D1 #1). | **Yes — keep href; label/copy may say “Quiz” → launcher feel after home reskin** |
| 2 | Hub **Focus** CTA (“Start next session” vs “Start quiz”) | **Keep one Up Next Focus concept** (already `getStudyNext` / `learner_next` when `learning_loop` + `quiz_concept_plan` on). Primary CTA stays a **concept deep link with `start=1`** (`nav.quizHref`). Spec copy “Start next session” may replace “Start quiz” when those flags are on; it still means “start Practice on this Focus concept,” not “open empty launcher.” A 3-item Focus list is **out** until product reopens it. | HANDOFF folded Focus into existing panels; W8.3 already wires Focus / Due Reviews to the same buckets as quiz plan. A multi-item Focus list would fork ranking. Due Reviews’ Quiz secondary (W8.3b) already opens the lead due concept with `start=1` — leave that. | **Yes — copy/flag polish OK; no new Focus list** |
| 3 | Hub **Resume** card | **Defer hub-native Resume.** Incomplete attempts surface on **Quiz home** (`ResumeStrip`). Header Quiz → home already shows Resume when one exists. | HANDOFF “with / without Resume” is a launcher/home state, not a second hub card. Duplicating resume on Study splits discard/resume UX. | **No — W7.9 uses Quiz-home Resume only** |
| 4 | Guide **“Quiz this concept”** | **Ship a real Quiz deep link** (concept id → `buildQuizHref` + `start=1`, return to the guide). Keep it **separate** from tutor Ask prompts. Prefer label **“Quiz this concept”** for the Quiz tool; leave “Quiz me on this” only if it remains a **tutor** message (or retire it to avoid two quiz verbs). Anchor: concept-map tile actions / section callout near the concept — not a new mastery writer. | Loop integrity: graded quiz path only; tutor chat never writes mastery. Same `from=link` + safe `return=` pattern as Hub/Tree (W8.2). `hide_quiz` / `hide_study` must hide or no-op the action. | **Yes — deep link + copy split** |
| 5 | Guide **“You struggled here”** marker | **Show only from real signals** — graph tier `struggling`, or an open misconception / recent graded miss already on the guide’s mistake / mastery inputs. **No** invented marker from prose. Exact pip/chip art deferred to DC copy + W7.9 UI; formula detail can ride amendments if needed. | Core rule: belief from graded checks. Fake struggle badges break trust and diverge from Tree / Hub tier language (four tiers + optional Stale). | **Partial — gate on real data; art in W7.9** |
| 6 | Guide **collapsed Mastered** section | **Keep** existing `MasteredSection` (one-line + expand). No redesign required for W7.D2. | Already matches HANDOFF “collapsed Mastered section.” Tokens: leaf + `reader.module.css` mastered row. | **Yes — already done; no rewrite** |
| 7 | Settings **Quiz** section | **Add under Preferences** a Quiz block that reads/writes the **same client prefs** as Adjust (`lib/quiz/prefs.ts` → Length / Difficulty / Answers / Format). Options for count / difficulty / format still come from `GET /api/quiz/config` (R-2). Do **not** add `user_settings` quiz columns in W7.9. | HANDOFF step 9 + plan W7.9 “length/wager defaults.” One prefs seam avoids home vs Settings drift. Settings row chrome matches existing Preferences (label + `CustomSelect` / segmented control on Sapling tokens). Hidden when `hide_quiz` on. | **Yes — Preferences Quiz subsection ↔ `prefs.ts`** |
| 8 | Settings **default wager / confidence** | **Defer.** Wager UI maps to per-question stated confidence (A132 / W7.4). No durable “default wager” in Settings until product defines server or prefs persistence. | Mid-session XP/wager math is kit demo; production awards on submit. A Settings default would invent a second confidence store. | **No — out of W7.9** |
| 9 | Definitive / Mixed / Conceptual in Settings | **Stay omitted** (W7.D1 #4). Settings Format **Mixed** = answer-format mix only. | Already accepted; naming trap unchanged. | **Yes — omit** |

---

## Integrity contract (do not break)

```text
learner_next / getStudyNext     → Hub Focus + Due Reviews ranking
GET /api/quiz/plan + useQuizHome → Quiz home / launcher ranking (same order family)
buildQuizHref / useToolNav       → every Quiz CTA (Hub header, Focus start, Guide, Tree)
lib/quiz/prefs.ts                → Adjust dialog + Settings Quiz section (one store)
```

- No second plan HTTP client, no hub-local “recommended concepts” sort, no Settings mirror of plan order.  
- Flag-off (`learning_loop` / `quiz_concept_plan` off): Hub Focus stays pre-loop behaviour; header Quiz still opens course home.  
- Empty course / empty graph: honest empty states (`HomeStates` / Hub empty) — never seed MATH 151 fixtures into production (W7.D1 #5 / W7.D3).

---

## Production anchors (today → W7.9)

| Concern | Today | W7.9 change |
|---|---|---|
| Header Quiz | `useToolNav.ts` `TOOL_HOME.quiz` — course home, no start | Keep; ensure home reads as launcher after W7.3 |
| Focus primary | `FocusCard` “Start quiz” → `nav.quizHref(id)` | Optional flag-on copy “Start next session”; same href |
| Due Reviews Quiz | `dueReviewsQuizHref` / W8.3b | Unchanged |
| Guide quiz verb | `ConceptMapBlockView` “Quiz me on this” → **tutor** `askTutor` | Add Quiz tool link; split tutor vs quiz copy |
| Guide mastered | `SectionView` `MasteredSection` | Keep |
| Guide struggle | Tier marks / `MistakesBlock`; no inline “struggled here” | Marker only when tier/misconception/mistake evidence exists |
| Settings Quiz | Absent; prefs only via Adjust / localStorage | Preferences subsection ↔ `loadPrefs` / `savePrefs` |
| Wager default | None | Deferred |

Optional one-line `// W7.D2:` TODOs may point at this file from `useToolNav.ts`, `ConceptMapBlockView.tsx`, and `Settings.tsx` — **no** UI rewrite in the design-doc PR.

---

## Design-package work (parallel, soft)

HANDOFF §4A still asks for **copies** of the three DC recreations with the visual additions. That work does not change the table above:

| Copy (suggested name) | Show |
|---|---|
| `Study Hub v2.dc.html` | Header Quiz affordance → launcher; Focus CTA copy; **no** duplicate Resume if home owns it |
| `Study Guide v2.dc.html` | Callout + struggle marker + “Quiz this concept”; mastered collapse already in v1 |
| `Settings v2.dc.html` | Preferences → Quiz section (Length / Difficulty / Answers / Format); no wager row |

Browser-verify the v1 recreations before pixel-matching (W7.D1 soft checklist). Capture single frames; do not zoom-capture multi-frame pages.

---

## Out of scope / pointers

- **W7.D3** — Launcher Map + empty-course: [`w7-d3-launcher-map.md`](./w7-d3-launcher-map.md) (no fake MATH 151).  
- **W7.D4** — 17.3 clickable prototype (E2E preferred).  
- **W7.1–W7.8** — Session shell, types, plan wire, wager-in-session, Exam Twin.  
- **W8.2 / W8.6** — Tree actions and shared learner-next helper already constrain Hub/Guide links; do not fork.

Supersedes the open “steps 8–9” row in HANDOFF §4A for product behaviour; visual DC copies remain optional polish before/during W7.9.

# Alvar trilogy → Sapling A+ implementation plan

**Status:** plan (not yet executed)  
**Branch / PR:** `feat/learning-loop-reland` / [#866](https://github.com/SaplingLearn/Sapling/pull/866)  
**HEAD at authorship:** `9f5c0111` (2026-11-23)  
**Updated:** 2026-11-23 — added quiz design-system reskin (W7) + cross-feature coherence (W8)  
**Audience:** implementation + review against the three Eero Alvar videos that shaped (and still under-realize) the learning system, **and** the quiz reskin / design-system audit that must land coherent with that loop.

This document is the single scoreboard and build plan for bringing Sapling’s learning system to **A+ incorporation** of everything those videos contribute that Sapling should own — including enabling what is already built but flagged off, strengthening what is weak, and building what is missing — **without** breaking the evidence rules the direction audit already settled (`docs/research/learning-loop/notes/direction/design_choices.md`, `2026-11-07-direction-audit.md`).

It also covers the **quiz feature reskin** (design-system audit + clickable prototype handoff, 2026-11-23) and the **product coherence** requirement: the learning loop must visibly drive Tutor, Knowledge Tree, Quiz, Study (review / flashcards / retention), Study Guide, and Library — one learner model, one graph, one evidence writer.
---

## 0. What “A+” means here

A+ is **not** “byte-for-byte LearnHarness.” Sapling is a multi-student course product with graded-only belief, Bastani-style withholding, FSRS measurement, and encrypted storage. Several Alvar harness features were **researched and deliberately refused or narrowed** (per-step prediction, free-text as mastery, proposition-chain ontology as mastery, “feels obviously true” as a stop rule).

| Grade | Meaning |
|---|---|
| **A+** | Claim is on by default for loop students (or equivalent always-on), eval-gated where required, E2E-covered, and does the pedagogical job the video intended *or* the evidence-aligned Sapling substitute that the research chose. |
| **A** | Strong in code when the loop is on; may still need Claude eval re-record or a child flag. |
| **B** | Partial: adjacent mechanism exists; student experience or pedagogy incomplete. |
| **C / D** | Weak or absent as pedagogy or product. |
| **N/A (settled non-goal)** | Video claim considered; evidence says do not build (or build only as low-trust UX). Documented so it is not re-opened as a “gap.” |

**North star for this plan:** every row that is not a settled non-goal reaches **A+**. Settled non-goals stay N/A with an explicit substitute score of A+.

---

## 1. The trilogy (source claims)

| # | Video | Role in Sapling DNA |
|---|---|---|
| **V1** | [How I Learn Difficult Things](https://www.youtube.com/watch?v=ciC6ffUqI8k) | Philosophy: safe anchors → motivated edges → understanding as structure/compression; work at the edge. |
| **V2** | [How I Use AI to Learn Things](https://www.youtube.com/watch?v=kzcI5F4tGiU) | First harness: one-to-one; probe → plan → teach; logistics absorbed; struggle on material; engineered trust; one interface. |
| **V3** | [Agent Harness for Learning Things](https://www.youtube.com/watch?v=nfTDljFG2g0) | Full system: teach vs practice; thinking fields; predict→teach→check; cue dials; confidence; persistent graph; visuals/subagents. |

Repo anchors that already name this lineage:

- Spec A138–A141 and `docs/superpowers/specs/2026-09-26-learning-loop-design.md`
- `docs/research/learning-loop/notes/direction/design_choices.md` (six harness features vs Sapling)
- `backend/learning/surface.py` (explicit Eero Alvar cue-familiarity dial)
- `docs/learning-loop/flag-rollout.md` (child flags + eval blockers)

**Quiz design-system source (external handoff, 2026-11-23):**  
`~/Downloads/Design system audit and implementation (1)/` — start with `HANDOFF.md`, then `notes/repo-findings.md`, `github.md`. Prototype artifacts: `Quiz Component Library.dc.html`, `Quiz Shell.dc.html`, `Quiz Components 7.*.dc.html`, `Quiz Session.dc.html`, plus recreations of Study Hub / Study Guide / Knowledge Tree / Settings. Spec build order 17.2; remaining steps 8–10 + 17.3 prototype. Maps to repo under `frontend/src/components/quiz/**`, `study/**`, `graph/**`, `studyGuide/**`.

---

## 1b. Cross-feature coherence (the learning system as product spine)

The loop is not a Tutor-only feature. When `learning_loop` is on, **one learner model** (`learner_state` BKT + FSRS + misconceptions) and **one graph writer** (`apply_graph_update`) should make Library, Tree, Tutor/Learn, Quiz, Study, Flashcards, and Study Guide feel like one system. Today the *backend* wiring is largely present (often behind child flags); the *UI* still reads as separate tools. W7–W8 close that gap.

### Dataflow (as built on #866)

```text
Library upload
  → index course_chunks (RAG)
  → extract concepts (+ prereq edges if upload_prereq_edges)
  → draft check_items (align + blind key) if uploader has loop on
  → graph_nodes / edges

                    ┌── Tutor / Learn (probe→plan→teach⇄check) ── graded checks ──┐
Knowledge graph ────┤                                                              ├── apply_graph_update
 learner_state ─────┤── Quiz (plan / planned Qs / gates / misconceptions / results)┤      │
 misconceptions ────┤                                                              │      ▼
                    ├── Study review queue + retention (FSRS) + Focus / Roadmap ────┘  node_mastery_events
                    ├── Flashcards (FSRS fields; integrity guard with loop)
                    └── Study Guide ("Ask tutor" → guide_ask origin; quiz callouts in W7)

Quiz generation (when flags on):
  quiz_concept_plan     ← FSRS-due → open misconceptions → ready fringe (same planner inputs as Learn)
  quiz_planned_questions ← difficulty + misconception distractors from learner model
  quiz_item_gates       ← concept check + blind solve (same family as check_items gates)
  submit                ← apply_graph_update + optional misconception open/close + results routing
```

### Connection scoreboard (coherence, not Alvar pedagogy)

| Link | Backend today | UI today | Target A+ |
|---|---|---|---|
| Library → graph / check bank | Strong (upload pipeline) | Weak (upload success ≠ “now in your map / quiz”) | Surface drafting status + Tree refresh; W8 |
| Graph → Tutor plan / SessionMap | Strong | Partial (list + map; not plan DAG) | W3.1–W3.2 |
| Graph → Quiz home neighbourhood | Partial (`LiveNeighbourhood`, concept plan flag off) | Partial | W5.E1/E3 + W7 launcher Map |
| Graph → Study Focus / Roadmap | Partial (hub reads graph mastery) | Partial (tiers; not FSRS-due language) | W7 hub + W8 |
| Tutor checks → mastery | Strong | Strong in Tutor V2 | Keep |
| Quiz submit → mastery | Strong when loop on | Results learning block flag off | W5.E3 + W7 summary |
| Quiz ↔ Tutor Ask | Exists (`quiz-ask`, guide_ask) | Panel exists; redesign must keep | W7 shell |
| Study review ↔ same FSRS as Learn plan | Strong | Split surfaces | W3.3 Practice mode + W7 hub Focus |
| Flashcards ↔ FSRS / integrity | Partial (course-level signals; integrity with loop) | Separate tool | W8 flashcard due = same learner_state story |
| Study Guide ↔ quiz / tutor / struggle markers | Ask-tutor exists; quiz callouts in design only | Spec steps 8 | W7.A |
| Results → next Study / Learn / Tree | `quiz_results_routing` | Flag off; old results UI | W5.E3 + W7 summary CTAs |

**Invariant for all of W7–W8:** no second mastery writer; no quiz-only shadow graph; every “Start quiz on this concept” / “Review due” / “Open on Tree” deep-link carries the same `course_id` / concept ids the loop planner uses.

---

## 2. Scoreboard — current → target

Status is for **loop-on students** (master `learning_loop` on). Child flags default off today unless noted.

### 2.1 Video 1 — philosophy of understanding

| ID | Claim | Now | Target | Path to A+ |
|---|---|---|---|---|
| Z | First-principles / safe-anchor teach before contingent facts | **C** (weak) | **A+** | Prompt policy + novice band; see W1 |
| AA | Motivated derivation as default teach spine (“why this move”) | **C** | **A+** | Prompt policy + evals; see W1 |
| AB | Understanding as compression / generative cores | **C** | **A+** | Pedagogy + optional generative checks; not full proposition ontology; see W1 |
| A | Teach / practice at the edge (ZPD) | **A** | **A+** | Claude eval + trial band calibration; master flag rollout |
| EX2 | Band target ~65–85% success | **A** | **A+** | Measurement in trial |
| AG | Spaced / FSRS durability (Sapling ahead of Alvar) | **A** | **A+** | Keep; pair with learning-gain reporting |

### 2.2 Video 2 — session machine & trust

| ID | Claim | Now | Target | Path to A+ |
|---|---|---|---|---|
| B | Adaptive probe edge map | **A** | **A+** | Optional `probe_matched_pretest` at trial |
| C | Minimal dependency plan | **A** | **A+** | Enable `upload_prereq_edges` so fringe is real |
| D | Plan shown as structure (graph), not only a list | **B** | **A+** | Plan DAG UI; see W3 |
| E | One reasoning step / turn shape | **A** | **A+** | Keep served-text evals green |
| F | Checks during teach | **A** | **A+** | Enable `loop_tutor_v2` for check framing |
| G | Graded-only belief; chat never mastery | **A** | **A+** | Keep invariant; do not regress for Alvar |
| H | Answer withholding / productive struggle | **A** | **A+** | Claude leak evals |
| I | Help ladder + attempt gates / fading | **A** | **A+** | Enable `help_gate_strict` at trial |
| J | Logistics absorbed by system | **A** | **A+** | Keep; improve handoffs (K) |
| K | One trusted interface over many sources | **B** | **A+** | Unify handoffs Learn↔Study↔Quiz; see W3 |
| L | Fact-check of **teach prose** | **B** | **A+** | Optional grounded-cite pass; see W4 |
| M | Item key verify (align + blind solve) | **A** | **A+** | Claude evals; enable `quiz_item_gates` |
| N | Struggle on material, not logistics | **A** | **A+** | Same as H/I/J/K |
| AJ | Uploads → tutor material + check bank | **A** | **A+** | Loop on for uploaders |
| AR | Trust engineered (reliability → learning) | **B** | **A+** | Surface “verified item / grounded turn” to student; avoid “trust the AI” copy |
| AL | Tutor v2 framing | **built_off** | **A+** | Eval → enable |

### 2.3 Video 3 — harness sensing & practice

| ID | Claim | Now | Target | Path to A+ |
|---|---|---|---|---|
| O | Teach installs; practice solidifies cues | **B** | **A+** | Practice stream + dials on; see W2/W3 |
| P | Cue-familiarity dial (Alvar-named) | **built_off** | **A+** | Eval → `varied_isomorphs` |
| Q | Combine-ideas dial | **built_off** | **A+** | Eval → `multi_concept_items` (+ prereqs) |
| R | Varied surfaces / isomorphs | **built_off** | **A+** | Same as P |
| U | Predict → reveal → explain (segment) | **built_off** | **A+** | Eval → `segment_prequestion` |
| U2 | Predict before **every** reasoning step | **N/A** | **N/A** | Settled: evidence weak; do **not** build |
| V | Self-explanation prompts | **built_off** | **A+** | Eval → `self_explanation_prompts` |
| W | Self-explain text updates mastery | **N/A** | **N/A** | Settled: do not; false-alarm PPV |
| S | Thinking fields update routing | **D** | **A+*** | *A+ = evidence-aligned substitute: reason-before-submit on free checks + optional low-trust next-probe hint; never mastery. See W2 |
| T | Stated confidence as process signal | **A** | **A+** | Ensure on all graded surfaces; calibration report |
| AF | Misconception process diagnosis | **A** | **A+** | Enable `quiz_misconceptions` after quiz gates |
| X | Persistent graph across sessions | **A** | **A+** | Enrich with `upload_prereq_edges` |
| Y | Proposition + reasoning-chain ontology | **N/A** | **N/A** | Settled weak ROI; substitute = concept/prereq + learner-constructed map activity (W5) |
| AQ | Graph shows covered vs understood | **B** | **A+** | Dual encoding UI; see W3 |
| AP | Practice as distinct cue-demand stream | **B** | **A+** | First-class Practice mode; see W3 |
| AI | Confusable interleave | **A** | **A+** | Stronger with prereqs + misconceptions |
| AH | Delayed retention / post-test | **A** | **A+** | Trial flags `retention_due_badge`, matched pretest |
| AC | Real visuals / SVG / demos | **D** | **A+** | New visual pipeline; see W4 |
| AD | Visual verification | **D** | **A+** | After AC |
| AE | Researcher / PDF / SVG / demo subagents | **D** | **A+** | Scoped agent slots; see W4 |
| AN | Student-editable teaching philosophy | **N/A** | **N/A** | Integrity risk; staff/admin variants only if ever |
| AO | Dictation / think-while-reading mic | **N/A** | **N/A** | Blocked by Permissions-Policy; optional later product decision |
| EX1 | Novice worked-example-first (A122) | **A** | **A+** | Record Claude eval cases |

\*For S, “A+” means the **Sapling-aligned** sensing channel is strong, not that Alvar’s every-step think-aloud drives mastery.

### 2.4 Headline scoreboard (roll-up)

| Layer | Now | Target after this plan |
|---|---|---|
| Session machine (V2) | A | **A+** |
| Anti–illusion / struggle | A | **A+** |
| Practice / cues / FSRS | A− (dials off) | **A+** |
| One materials interface | A− | **A+** |
| Edge / ZPD mechanics | A | **A+** |
| Model of *how* they think | C+ | **A+** (aligned substitute) |
| First principles + motivated discovery | C | **A+** |
| Visual / demo harness | D | **A+** |
| Reasoning-chain ontology | C (absent by choice) | **N/A** + substitute A+ |
| Quiz UX (design system) | B (old shell; prototype exists) | **A+** (W7) |
| Cross-feature coherence (visible spine) | B (backend yes, UI fragmented) | **A+** (W8 + W7 hooks) |

---

## 3. What is already incorporated (do not rebuild)

These are **done** when `learning_loop` is on. Work is enable / eval / polish, not greenfield.

1. Probe → plan → teach ⇄ check → feedback → close  
2. Code-owned fringe planner + student approve  
3. H0–H6 ladder, ceilings, attempt gates, leak cut, help ledger  
4. Graded-only belief via `apply_graph_update`; chat never mastery credit  
5. Structured turns (`key_idea` / `body` / one `question`); ≤5 sentences  
6. Band controller + novice worked-example-first (A122)  
7. FSRS-6 review, confusable interleave, delayed post-test / retention check  
8. Upload → chunks → check-item draft → align + blind key solve  
9. Misconception slip vs hold + confront path  
10. Stated confidence on graded attempts (diagnosis, not weight)  
11. Code for A138–A141, tutor v2, strict help gate, quiz learning pack (flags off)  
12. Explicit Alvar cue dial in `learning/surface.py` (behind `varied_isomorphs`)

**Sapling already exceeds Alvar** on: FSRS + delayed measurement, Bastani withholding, graded-only belief, blind key verify, second-opinion grader, integrity guard.

---

## 4. What is missing / weak / off (implementation backlog)

### Workstream W0 — Foundation (unblock everything)

**Goal:** Loop can be trusted on Claude; master flag can roll out.

| Task | Type | Effort | Acceptance |
|---|---|---|---|
| W0.1 Claude eval re-record (A111) for `loop_tutor*`, `grader*`, `learning_decision`, `check_items*` | eval | L | Slots leave `LOOP_SLOTS_PENDING_CLAUDE_EVAL`; CI evals green |
| W0.2 Record novice worked-example-first + confront H4 cases | eval | M | Datasets pass served gates |
| W0.3 Record flag-path datasets (`LOOP_EVAL_FLAGS=1`, `LOOP_EVAL_VARIANT=v2`) | eval | M | `__flags` + v2 cassettes replay in CI |
| W0.4 Roll out `learning_loop` per `flag-rollout.md` (self → class → all) | enable | S | Default lane E2E stays green; kill-switch / flag-off lanes still pass |
| W0.5 Keep kill switch + three E2E lanes | measurement | S | Documented in PR test plan |

**Depends on:** nothing (starts now).  
**Blocks:** every enable below.

#### W0 readiness (2026-11-23 kickoff)

**Verdict:** Ready to record when Anthropic spend is accepted. `ANTHROPIC_API_KEY` is set; no cassettes recorded this kickoff.

Pending slots (`LOOP_SLOTS_PENDING_CLAUDE_EVAL`): `check_items`, `grader`, `grader_second`, `learning_decision`, `loop_tutor_lite`, `loop_tutor`, `loop_tutor_deep`. Procedure: `backend/tests/evals/README.md` (3 live records + `floors.py`; never hand-edit floors). Clear a slot only after green gates: add its Claude model to `EVALUATED_MODELS` and remove it from the pending set.

Record order (`cd backend`, each dataset 3× `SAPLING_EVAL_MODE=record` then `floors.py`): `loop_tutor.py` (+ companion `misconception_confront.py`) → `grader.py` → `check_items.py` → `decisions.py` → flag-path (`LOOP_EVAL_FLAGS=1`) → v2 (`LOOP_EVAL_VARIANT=v2`). Optional: `SAPLING_EVAL_USAGE_LOG`, `LOOP_EVAL_SLOTS=loop_tutor_lite`.

**Blockers:** live Anthropic cost (Sonnet `check_items`; Opus judges); multi-hour wall clock; CI fails closed on Gemini cassettes until Claude cassettes + `baselines.json` land with the pending-set clear.

---

### Workstream W1 — P0 philosophy into the teach spine (V1 → A+)

**Goal:** Teaching *drives* first principles and motivated derivation, not only ZPD location.

| Task | Type | Effort | Acceptance |
|---|---|---|---|
| W1.1 Add **Safe-anchor** instructions to `loop_tutor` (all tiers): for novices / new concepts, open with lockable definitions or universal statements before contingent procedure; forbid “because the lecture says” as the only warrant | prompt_policy | M | New eval cases `teach_safe_anchor_*`; no leak regressions |
| W1.2 Add **Motivated derivation** instructions: every teach `body` must make the *problem that forces the next move* explicit; `question` asks the student for the next motivated step when ceiling allows | prompt_policy | M | Eval cases `teach_motivated_step_*`; v2 compatible |
| W1.3 Add **Compression / generative core** beat at segment close: one check that asks the student to regenerate the idea from the core definition (teachback / free), not re-recognize the surface | prompt_policy + practice | M | Format rotation includes generative core item; E2E journey |
| W1.4 Wire safe-anchor preference into novice / worked-first band copy (A122) so scaffolding and philosophy agree | prompt_policy | S | Pins in `test_loop_tutor*` |
| W1.5 Document pedagogy in `docs/learning-loop/glossary.md` + amendments (spec §13) | docs | S | Named “Alvar V1 pedagogy”; not “feels obviously true” (forbidden stop rule — design_choices Q5) |

**Explicit non-goal:** do **not** use learner “feels obvious” as mastery stop (Deslauriers / Bastani). Stop = graded check.

**Files (expected):** `backend/agents/loop_tutor.py`, `backend/learning/policy.py` (band format strings if needed), `backend/tests/evals/loop_tutor.py`, `docs/learning-loop/amendments.md`.

---

### Workstream W2 — P1 harness sensing, evidence-aligned (V3 → A+)

**Goal:** Close the sensing gap without violating Q3 (free text ≠ mastery).

| Task | Type | Effort | Acceptance |
|---|---|---|---|
| W2.1 Enable `segment_prequestion` after W0.3 | enable | S | Flag default or targeted rollout; E2E A138 green in default lane |
| W2.2 Enable `self_explanation_prompts` after W0.3 | enable | S | E2E A139 green; admin self-explain report live |
| W2.3 **Reason-before-submit** on free / teachback checks: short optional “show your reasoning” field; stored encrypted; **not** evidence; grader still uses answer + rubric | new_feature | M | UI + API; never writes mastery; E2E |
| W2.4 Optional **low-trust next-probe hint** from reason/self-explain text: may only choose *which check to pose next*, never bump `p_known` | new_feature | L | Unit + invariant test: no mastery mutation path |
| W2.5 Confidence on every graded check/review surface (already on probe/quiz); hypercorrection dwell on high-confidence wrong | ui + policy | S | Spec A132 coverage; help/feedback dwell |
| W2.6 Do **not** implement per-step predict (U2) or self-explain→mastery (W) | non-goal | — | Invariants + plan checklist |

**Research binding:** design_choices Q1–Q4. A+ for “thinking fields” = W2.3–W2.5, not Alvar’s every-step mastery routing.

---

### Workstream W3 — P2/P3 structure UX + practice stream

**Goal:** Student *sees* understanding-as-structure; practice is a first-class cue stream.

| Task | Type | Effort | Acceptance |
|---|---|---|---|
| W3.1 **Plan dependency view**: for today’s approved concepts, show prereq edges among them (and up to goal), not only a numbered list; keep list for approve UX | ui | M | PlanPanel + SessionPanel; a11y; E2E |
| W3.2 **Covered vs understood** on SessionMap: dual encoding (seen/revealed or “practiced” vs `p_known` / band) | ui | M | Legend + testids; E2E |
| W3.3 **Practice mode** entry from Study / wrap-up: cue-demand stream using due + unfamiliar surfaces + multi-concept when open; not a second Learn teach | ui + services | L | Journeys; oracles |
| W3.4 Clear Learn → Study → Quiz handoffs so “one interface” feels true (K) | ui | M | Copy + deep links; hide-flag safe |
| W3.5 Learner-constructed mini map activity (evidence-backed graph use from Q6): occasional “connect these ideas” generative task | new_feature | M | Optional; never auto-extract propositions into mastery |

---

### Workstream W4 — P3 representation & teach-prose trust

**Goal:** Multi-representation and trust match the harness *where product-safe*.

| Task | Type | Effort | Acceptance |
|---|---|---|---|
| W4.1 Real **figure** path for `surface_representation=visual`: generate or attach SVG/diagram from source passages; render in LoopLearn | new_feature | XL | Sandboxed render; no raw script |
| W4.2 **Visual verify** agent: check figure against item key / source claim before serve | new_feature | L | Fail closed → text fallback |
| W4.3 Optional **grounded teach** mode: teach turn must cite retrieved chunk ids; UI shows sources; contradiction with passages → rewrite or withhold | new_feature | L | Eval + E2E; cost budgeted |
| W4.4 Trust chrome: “Key verified” / “Grounded in your materials” chips (AR) | ui | S | No “trust the AI” framing |
| W4.5 Scoped subagents only as needed for W4.1–W4.3 (not a full personal researcher swarm) | agents | L | New slots in `_providers.py` + function handlers |

---

### Workstream W5 — Flag enable program (built_off → A+)

Order follows `flag-rollout.md`, tightened for Alvar A+.

| Phase | Flags | Gate |
|---|---|---|
| **E0** | `learning_loop` rollout | W0 + three E2E lanes |
| **E1** (read-only / safety) | `quiz_concept_plan`, `quiz_results_routing`, `item_reports`, then `crisis_support` | Copy review for crisis |
| **E2** (prompt / Alvar sensing) | `loop_tutor_v2`, `segment_prequestion`, `self_explanation_prompts` | W0.3 flag datasets |
| **E3** (quiz learning) | `quiz_planned_questions` → `quiz_item_gates` → `quiz_misconceptions` | Planned/gates evals |
| **E4** (drafting / Alvar dials) | `varied_isomorphs`, `upload_prereq_edges`, then `multi_concept_items` | Varied/combo/relations evals |
| **E5** (trial measurement) | `help_gate_strict`, `probe_matched_pretest`, `retention_due_badge` | Trial boundary only |

**Rule:** a flag is not A+ until: eval green (if required) + default or targeted `on` for the intended population + E2E journey in the default lane (or dedicated flag-on journey) + ops watch from `flag-rollout.md`.

---

### Workstream W6 — Settled non-goals (document, do not build as Alvar)

Track these so they are not re-filed as gaps:

| Video claim | Decision | A+ substitute |
|---|---|---|
| Predict before every reasoning step | Do not build | Segment prequestion (U) |
| Free-text thinking → mastery | Do not build | Reason-before-submit + graded check (S/W2) |
| “Feels obviously true” stop rule | Do not build | Graded check stop (G) |
| Auto proposition / reasoning-chain graph as knowledge | Do not build as mastery store | Concept/prereq graph + optional learner-built map (Y/W3.5) |
| Student-editable system prompts | Do not build | Staff prompt versions / flags (AN) |
| Dictation mic think-aloud | Defer; security blocks mic | Optional typed think-while-reading later (AO) |

Update `docs/learning-loop/amendments.md` with a short “Alvar trilogy: adopted / narrowed / refused” table pointing at design_choices Q1–Q6.

---

### Workstream W7 — Quiz design-system reskin (handoff → production)

**Source:** `HANDOFF.md` + `notes/repo-findings.md` in the design audit package.  
**Goal:** Ship the new quiz UX on Sapling tokens, **wired to the learning-loop quiz algorithm** (A143–A147), not a parallel toy quiz. Practice vs Exam Twin, launcher Map, session summary, and hub/guide hooks must read the same learner model and graph as Tutor/Study.

#### Design decisions already accepted (do not re-litigate)

- Mastery = app four tiers (Unexplored / Struggling / Learning / Mastered) + hand-drawn blob; spec plant stages remapped; Wilting → Stale badge (“Last seen N days ago”).
- Dark frames skipped; Definitive/Mixed/Conceptual selector omitted.
- Sample prototype data: BIO 201 / MATH 151 / PHIL 110, Maya Ellis, frozen “today” Wed Nov 11 2026 (production uses real enrollments + rich seed).
- Fonts: Aleo / SUSE / IBM Plex Mono; no Gummi in repo.
- Session = full-screen focus on `--bg`; accent = brand forest (not per-course quiz accent of the old shell — confirm against product before coding if course tint must remain for multi-course sessions).

#### Prototype inventory → production map

| Handoff artifact | Spec steps | Production target |
|---|---|---|
| `Quiz Component Library.dc.html` | 1 | Tokens + empty states + mastery nodes in `frontend/src/components/quiz/**` + shared `ConceptNode` |
| `Quiz Shell.dc.html` | 2–3 | Question chrome: top bar, meta row, hint/skip/wager, feedback, study-guide drawer, prereq banner |
| `Quiz Components 7.1–7.18*.dc.html` | 4–5 | Question-type components (sort, sequence, label, build, calculate, compare, explain, dialogue, exam twin, …) |
| `Quiz Session.dc.html` | 6–7 | Start (Practice / Exam Twin), leave, generating, summary |
| Study Hub / Guide / Settings recreations | 8–9 (copies) | Hub Focus + Quiz launcher entry; Guide quiz callouts / struggle markers; Settings → Quiz section |
| Launcher (not built) | 10 | Concept list + Map view reusing Tree graph (`sapling-graph.js` → `KnowledgeGraph2D` / `ConceptNode`) |
| Clickable prototype | 17.3 | Optional; production E2E journeys supersede |

#### Remaining design work before / in parallel with code

| Task | From HANDOFF | Notes |
|---|---|---|
| W7.D1 | Verify unchecked component pages in browser | 7.4–7.15, Study Guide, Settings |
| W7.D2 | Steps 8–9 on **copies** of hub/guide/settings | Do not edit recreation originals as source of truth once porting |
| W7.D3 | Step 10 Launcher states | Need MATH 151 concept list for new-course empty state; Map = Tree graph |
| W7.D4 | Step 17.3 clickable prototype | Nice-to-have once launcher exists |
| W7.D5 | Resolve open product questions | Card vs open question container; keep Ask-tutor / confidence / loop flags in shell |

#### Production implementation tasks

| Task | Type | Effort | Acceptance |
|---|---|---|---|
| W7.1 Port shell tokens + session chrome into `quiz/` (TopBar focus mode, meta row with blob concept pill, progress, XP/streak only if product keeps gamification) | ui | L | Visual match to Shell frames; a11y; no new color system |
| W7.2 Port question-type kit (7.1–7.18) behind real attempt JSON; **MC / short / numeric / algebra first**, interactive types (sort, label, dialogue…) phased | ui | XL | Each shipped type round-trips generate → answer → submit |
| W7.3 **Hook generation to loop algorithm:** home/launcher consumes `GET /api/quiz/plan` when `quiz_concept_plan` on; Adjust/Start pass planned concept ids; generation path uses `quiz_planned_questions` + gates when on | integrate | M | E2E `quiz-learning.spec.ts` + new launcher journeys; flag-off = pre-loop quiz |
| W7.4 Confidence / wager UI maps to existing stated-confidence API (A132) — do not invent a second confidence store; align “Certain / Fairly sure / Unsure” with `guessing` / `fairly_sure` / `sure` | integrate | S | Pins in quiz-journeys confidence test |
| W7.5 Hint / skip / study-guide drawer: hints must not become answer leaks (same Bastani rule as Tutor); study-guide drawer deep-links concept; Skip respects attempt rules | integrate | M | No mastery from hint-only; E2E |
| W7.6 Prereq banner: when planner/gates say prereq weak, show banner **and** prefer posing that concept (same fringe logic as Learn) | integrate | M | **done** — `prefer_pose` + generate redirect + `quiz-prereq-banner`; flag `quiz_concept_plan`; empty edges inert |
| W7.7 Session summary: mastery delta + learning block (A147) + CTAs → Tree concept, Study review, Tutor `guide_ask` / Learn on weak concept, Study Guide section | integrate | M | `quiz_results_routing` on; deep links tested |
| W7.8 Practice vs Exam Twin: Practice = learning evidence path (gates/misconceptions as flagged); Exam Twin = timed, post-test-like (tool-light) — **must not** double-count daily evidence | product + backend | L | Spec + invariants; oracle |
| W7.9 Hub / Guide / Settings additions (spec 8–9): Focus list “Start next session” → launcher or due review; Guide “Quiz this concept” / struggle marker; Settings Quiz section for length/wager defaults | ui | M | Hide-flag safe (`hide_study` etc.) |
| W7.10 Launcher Map view = Knowledge Tree graph component (covered vs understood encoding from W3.2 when ready) | ui | M | Same `ConceptNode` / mastery palette |
| W7.11 Kill legacy quiz chrome once parity: home/question/results replaced or behind short-lived flag `quiz_shell_v2` | chore | M | Default lane E2E green; flag-off lane if needed |

**Hard wiring rules for W7**

1. Question text and keys still come from quiz generation agents / planned writer — the design kit’s demo prompts are **fixtures for UI only**.  
2. Mastery chips and blob nodes read `graph_nodes` / submit deltas — never local prototype mastery.  
3. “Returning concept” / exam-distance pips derive from learner_state (last review, FSRS due, or times_studied) — define the formula in amendments before coding.  
4. Ask-about-this / Tutor handoff keeps existing origins (`quiz-ask`); do not drop the panel in the reskin.  
5. Library-grounded quizzes continue to use course materials via existing grounding; empty library → honest empty state (design empty components).

---

### Workstream W8 — Cross-feature coherence (make the spine visible)

**Goal:** A student can feel that Library → Tree → Tutor → Quiz → Study are one system. Complements W3/W5/W7.

| Task | Surfaces | Effort | Acceptance |
|---|---|---|---|
| W8.1 After upload, show “Concepts added / checks drafting” and link to Tree + “Quiz these concepts” when items ready | Library, documents UI | M | Status from `check_items_status`; E2E |
| W8.2 Tree node panel actions: Teach (Learn/Tutor), Quiz, Flashcards, Study Guide — all deep-link same concept id | Tree | M | useToolNav pattern; E2E |
| W8.3 Study Focus / Quick Reviews label **FSRS-due** and open Review or Quiz launcher with those concepts (not a separate ranking) | Study Hub | M | Matches `quiz_concept_plan` / Learn plan due set |
| W8.4 Flashcard generate/review writes that Study can explain in the same mastery language; integrity guard remains | Flashcards | M | No divergent “mastery” |
| W8.5 Tutor wrap-up / Quiz summary / Retention empty states cross-link each other with one copy system (“Due on Study”, “Continue in Tutor”, “See on your map”) | Tutor, Quiz, Study | S | Copy doc + testids |
| W8.6 Shared “learner next” API or client helper: one function returns due reviews, fringe ready, open misconceptions for Hub / Quiz launcher / Dashboard | lib + optional route | M | Single source; unit tests |
| W8.7 Dashboard / nav: retention badge (A126) and Learn-next already loop-aware — keep aligned with W8.6 | Dashboard | S | Flag-on E2E |

---

## 5. Dependency graph (build order)

```text
W0 (Claude evals + master flag)
 ├─► W1 (pedagogy prompts) ──► re-record affected tutor evals
 ├─► W5.E2 (v2, prequestion, self-explain)
 ├─► W5.E3 (quiz pack) ───────────────┐
 ├─► W5.E4 (varied, prereqs, multi)    │
 ├─► W2 (reason-before-submit)        │
 ├─► W3 (plan DAG, practice mode)     ├──► W7 quiz reskin (shell → types → launcher)
 ├─► W8 coherence deep-links / next ──┘         │
 ├─► W5.E5 (trial flags)                        │
 └─► W4 (visuals + grounded teach)              ▼
                                      W7.11 retire legacy quiz chrome
```

**Critical path to “Alvar dials on”:** W0 → W5.E2 → W5.E4.  
**Critical path to “philosophy A+”:** W0 → W1 → tutor eval re-record.  
**Critical path to “harness spectacle A+”:** W0 → W4 (XL).  
**Critical path to “coherent quiz product”:** W0 → W5.E1/E3 (algorithm flags) ∥ W7.D\* (finish design) → W7.1–W7.10 → W8.  
**Parallelism:** W7 UI port can start on flag-off quiz behavior; **do not** ship launcher/summary CTAs that claim learner-model routing until W5.E1/E3 are on for dogfood.
---

## 6. PR #866 inclusion strategy

#866 is already the learning-system reland. This plan does **not** require stuffing XL work into the same merge if it blocks ship.

| Slice | Goes into #866? | Rationale |
|---|---|---|
| This plan doc | **Yes** | Orient reviewers + follow-on work |
| W0 eval re-records | **Yes if blocking CI**; else immediate follow-on | PR body already lists A111 pending |
| W5 enable of child flags | **No by default** — enable post-merge via admin rollout after evals | Flags must stay off until evals; code already in tree |
| W1 pedagogy prompts | **Follow-on PR(s)** on top of #866 | Touches tutor prompts + evals |
| W2 reason-before-submit | **Follow-on** | New API/UI |
| W3 plan DAG / practice mode | **Follow-on** | Frontend + services |
| W4 visuals | **Separate epic** | XL; new agents |
| W6 amendments | **Yes** (small docs PR or #866 docs commit) | Locks non-goals |
| W7 quiz design reskin | **Follow-on epic** (can stack on #866 after merge) | Large frontend; depends on quiz learning flags for full coherence |
| W8 coherence deep-links | **Follow-on**, can land early slices with W7 | Small API/helper + nav actions |

**Ship rule:** merge #866 with loop **code** complete and flags **off**; execute W0 then W5 rollout; land W1–W4 and **W7–W8** as sequenced PRs that reference this plan’s task IDs. Quiz reskin PRs must cite W7.3–W7.8 so algorithm hooks are reviewed, not only CSS.
---

## 7. Test / proof plan (every A+ row)

| Layer | Proof |
|---|---|
| Static | ruff, lint-imports, code-size, type ratchets |
| Unit / integration | Existing loop + new pedagogy / reason-field invariants |
| Evals | Claude live record 3×; flag and v2 namespaces |
| E2E default | Existing learn-loop / varied / quiz-learning / confidence / retention |
| E2E new | Safe-anchor journey; plan DAG; reason-before-submit; practice mode; visual serve; **quiz shell** (launcher → session → summary → Tree/Study/Tutor); Library→Tree→Quiz handoff |
| E2E off lanes | Kill-switch + flag-off remain green (including pre-loop quiz chrome until W7.11) |
| Oracles | `learn_loop` with `--expect-loop-activity` on main journey |
| Design QA | Browser pass on W7.D1 pages; single-frame captures only (handoff gotcha) |
| Product | Learning-gain / post-test funnel before declaring outcome A+ |

---

## 8. Effort roll-up (rough)

| Workstream | Effort | Outcome |
|---|---|---|
| W0 Foundation | L | Unblocks all enables |
| W1 Philosophy prompts | M–L | V1 A+ |
| W2 Sensing (aligned) | M–L | V3 sensing A+ without mastery regression |
| W3 Structure UX + practice | L | D/K/AP/AQ A+ |
| W4 Visuals + grounded teach | XL | AC/AD/AE/L A+ |
| W5 Flag enables | M (calendar) | built_off → on |
| W6 Docs / non-goals | S | Prevent thrash |
| W7 Quiz design reskin | XL | New quiz UX ↔ loop algorithm |
| W8 Cross-feature coherence | L | Library↔Tree↔Tutor↔Quiz↔Study feel one |

---

## 9. Owner checklist — “everything from the videos”

Use this as the merge/readiness checklist. Every row must be **Done (A+)**, **N/A (settled)**, or **Scheduled (task ID)**.

### V1
- [x] Safe-anchor teach (W1.1) — prompts + `PEDAGOGY_CASES`; Claude/`__pedagogy` cassette still open (W0)  


- [x] Motivated derivation default (W1.2) — prompts + `teach_motivated_step_*` case; cassette still W0  
- [x] Compression / generative core checks (W1.3) — policy + prompt; E2E/eval still open  

- [x] Edge / ZPD (exists; polish W0/W5)  
- [x] Durable structure via FSRS/post-test (exists; AH trial flags)  
- [x] N/A logged: no “feels obvious” stop (W6)

### V2
- [x] Probe → plan → teach → check  
- [x] Logistics absorbed  
- [x] Struggle on material / withholding  
- [x] Plan-as-structure UI (W3.1)  
- [x] One-interface handoffs (W3.4) — see [`w3-handoffs.md`](w3-handoffs.md)  

- [x] Teach-prose grounding chrome (W4.3) — `materials_grounded` label  
- [x] Key-verified chrome (W4.4) — `key_verified` on pose when `canonical_verified` (no SVG / no new LLM)  

- [x] Item verification (enable quiz gates W5.E3)  
- [ ] Tutor v2 on (W5.E2)

### V3
- [ ] Segment predict→reveal on (W5.E2)  
- [ ] Self-explain on (W5.E2)  
- [x] Reason-before-submit (W2.3) — see [w2-reason-before-submit.md](./w2-reason-before-submit.md)  
- [x] Low-trust routing hint only (W2.4) — helper + decrypt wire + `next_probe_hint` flag; see [w2-next-probe-hint.md](./w2-next-probe-hint.md)  

- [ ] Varied isomorphs on (W5.E4)  
- [ ] Multi-concept on (W5.E4)  
- [ ] Upload prereqs on (W5.E4)  
- [x] Practice mode (W3.3) — entry + multi-due `scope=due&queue=` cue stream; richer stream still later  

- [x] Covered vs understood map (W3.2) — practiced outline + mastery fill  

- [ ] Real visuals + verify (W4)  
- [x] N/A logged: per-step predict, text→mastery, proposition ontology, editable prompts, mic (W6)

### Quiz design system + coherence
- [x] Design verification pass (W7.D1) — decisions locked; human HTML verify still optional  

- [x] Hub / Guide / Settings additions designed (W7.D2) — see [`w7-d2-hub-guide-settings.md`](w7-d2-hub-guide-settings.md); W7.9 impl done  


- [x] Launcher + Map designed (W7.D3) — see [`w7-d3-launcher-map.md`](w7-d3-launcher-map.md); W7.10 Map pane shipped  

- [x] Quiz shell in production (W7.1) — focus SessionTop + Check bar; Hint/Skip/forest CTAs deferred  

- [x] Core question types shipped + interactive types phased (W7.2) — first slice (MC/short/numeric/algebra on SessionTop); interactive kit still phased  
- [x] Launcher/home wired to `quiz_concept_plan` / planned generation (W7.3)  
- [x] Confidence ↔ A132 (W7.4)  
- [x] Hints / guide drawer leak-safe (W7.5) — Skip + StudyGuideDrawer; Hint disabled (no leak-safe API)  

- [x] Prereq banner ↔ graph fringe (W7.6)  
- [x] Summary CTAs → Tree / Study / Tutor (W7.7)  

- [x] Practice vs Exam Twin evidence rules (W7.8) — [`w7-practice-exam-twin.md`](w7-practice-exam-twin.md)  

- [x] Hub Focus + Guide “Quiz this concept” + Settings Quiz (W7.9)  

- [x] Launcher Map = Tree graph (W7.10)  
- [x] Library → Tree / Quiz after upload (W8.1)  
- [x] Tree node → Teach / Quiz / Cards / Guide (W8.2)  
- [x] Study due = same FSRS set as quiz plan (W8.3)  
- [x] Shared “learner next” helper (W8.6)  


---

## 10. First 30 days (suggested execution)

| Days | Focus |
|---|---|
| 1–7 | W0.1–W0.3 Claude + flag-path evals; land this doc + W6 amendments; **W7.D1** browser verify design pages |
| 8–14 | W1 pedagogy prompts + re-record; W5.E2 dogfood; **W7.D2–D3** finish hub/guide/launcher design; start **W7.1** shell port |
| 15–21 | W2.3 reason-before-submit; W3.1 plan DAG; W5.E4 dogfood; **W7.3** wire plan API into new home/launcher; **W8.6** learner-next helper |
| 22–30 | W5.E3 quiz pack dogfood; **W7.2** MC/short types on new shell; **W7.7/W7.9** summary + hub hooks; **W8.1–W8.3** Library/Tree/Study links; W4 design spike only |

### Day 1 parallel launch (2026-11-23)

Five concurrent tracks kicked off from this plan. **No flag enables** until W0 evals clear.

| Track | Scope | Mode |
|---|---|---|
| W6 + W1.5 | `amendments.md` Alvar adopted/narrowed/refused table; glossary + README pointer | **done** |
| W1.1 / W1.2 / W1.4 | Safe-anchor + motivated-derivation in `loop_tutor.py`; band copy alignment | **done** (eval cases still open) |
| W8.6 | Shared `learner_next` helper (due / fringe / misconceptions) | **done** (Hub/Dashboard wire still open) |
| W0 + W7 kickoff | Eval re-record runbook (no API spend yet); `quiz-shell-port-map.md` | **done** (record still blocked on spend) |
| W3.1 spike | Plan dependency view data + UX note (`w3-plan-dependency-spike.md`); `GET /plan` `prereq_edges` | **done** (UI still open) |

**Day 1 tracks:** all five complete (docs / prompts / learner-next / port map / plan `prereq_edges`).

**Day 2 Wave A+B:** all ten tracks landed (see compliance audit for PARTIAL vs PASS).

**Day 3 gap closure:** product/measurement tracks done; **W0 blocked** on invalid Anthropic API key (user refreshing; then record lite → full + `LOOP_EVAL_PEDAGOGY=1`).

### Day 4 parallel launch (no-Anthropic continuation — 2026-11-23)

| Track | Scope | Notes |
|---|---|---|
| W3.2b | SessionMap dual encoding (practiced outline vs mastery fill) | **done** (`practicedIds` + legend) |
| W8.7 | Dashboard Learn-next / retention ← `learner_next` | **done** (Learn-next via `/study/.../next`; A126 retention badge unchanged) |
| W8.1c | Library callers pass concept node ids into `libraryNext` | **done** (list stamps `node_id`; upload via `getGraph`) |
| W2.5 | Confidence + hypercorrection dwell on loop check surfaces | **done** (`feedback_dwell_ms` on Sure+wrong) |
| W3.3 | Practice mode spike (Study cue stream) | **done** (spike); **W3.3b entry landed** → [`w3-practice-mode-spike.md`](w3-practice-mode-spike.md) |
| W7.D2 | Hub / Guide / Settings quiz design brief | **done** → [`w7-d2-hub-guide-settings.md`](w7-d2-hub-guide-settings.md) |
| E2E | Exercise new learn-loop stubs under function mode | **partial** — vitest/pytest green (279+19); Playwright needs `e2e-up` in this checkout (slot 1 held elsewhere) |

**Day 4:** all no-Anthropic tracks complete. **Still blocked on key:** W0 cassettes, W5 flag enables, pedagogy `__pedagogy` live scoring.

**Day 5:** complete (W7.5–7.7, W7.9, W7.D3, W3.4, W2.4, W7.6).

### Day 6 parallel launch (remaining no-Anthropic checklist — 2026-11-23)

| Track | Scope |
|---|---|
| W7.10 | Launcher Map pane (KnowledgeGraph2D; select≠start) per D3 | **done** |
| W7.3 | Confirm/finish home ↔ `quiz_concept_plan` / planned generation | **done** (course plan keep + Start/Adjust pins) |
| W7.4 | Quiz confidence A132 parity on new shell | **done** (SessionTop + confidence coexist) |
| W7.8 | Practice vs Exam Twin evidence rules (UI + evidence path) | **done** → [`w7-practice-exam-twin.md`](w7-practice-exam-twin.md) |
| W4.3 | Teach-prose “Grounded in your materials” chrome (no SVG agent) | **done** (`materials_grounded`) |
| W3.3b | Practice-mode entry from Study wrap-up / Hub (cue stream slice) | **done** → [`w3-practice-mode-spike.md`](w3-practice-mode-spike.md) §7 |

**Day 6:** W7.3/4/8/10, W4.3, W3.3b done. **Still skipped (need key):** W0, W5.*, W4 SVG agent.

### Day 7 parallel launch (remaining no-key — 2026-11-23)

| Track | Scope |
|---|---|
| W7.2 | Core types on new shell: MC / short / numeric / algebra polish (not 7.1–7.18 kit) — **done** (first slice: SessionTop + testids/a11y/layout; interactive kit phased) |
| W4.4 | Key-verified chrome when blind-key/verify already succeeded (no SVG agent) | **done** (`key_verified` ← `canonical_verified` on pose) |
| W2.4b | Decrypt reasoning → `next_probe_hint` prefer (flagged; never mastery) | **done** → [`w2-next-probe-hint.md`](w2-next-probe-hint.md) |
| W3.3c | Practice cue stream: multi-due quiz queue from `learner_next` | **done** (`scope=due&queue=` + `start=1` → `queueStartRequest`) |
| W8.7 verify | Confirm Dashboard Learn-next + document retention vs FSRS due | **done** (Learn-next = `getStudyNext`/`learner_next` when `learning_loop`+`quiz_concept_plan`; A126 badge = `GET /posttest/due`, not FSRS) |

### Day 5 parallel launch (no-Anthropic remaining checklist — 2026-11-23)

| Track | Scope |
|---|---|
| W7.9 | Implement Hub Quiz / Guide “Quiz this concept” / Settings Quiz per D2 | **done** |
| W7.7 | Quiz results summary CTAs → Tree / Study / Tutor | **done** |
| W7.6 | Prereq-weak banner + fringe preference | **done** |
| W3.4 | Learn ↔ Study ↔ Quiz handoff copy + deep links | **done** → [`w3-handoffs.md`](w3-handoffs.md) |
| W7.D3 | Launcher + Map design brief | **done** → [`w7-d3-launcher-map.md`](w7-d3-launcher-map.md) |
| W7.5 | Wire Hint/Skip slots + leak-safe study-guide drawer scaffold | **done** (Skip + drawer; Hint disabled) |
| W2.4 | Low-trust next-probe hint from reasoning (flagged; never mastery) | **done** (`next_probe_hint` off; W2.4b decrypt wire) → [`w2-next-probe-hint.md`](w2-next-probe-hint.md) |

**Skipped this wave (need key / evals):** W0, W5.*, W1 cassette scoring, W4 SVG agent.

### Day 3 parallel launch (gap closure — 2026-11-23)

| Track | Scope | Closes |
|---|---|---|
| W1 eval cases | `teach_safe_anchor_novice_open`, `teach_safe_anchor_lecture_says`, `teach_motivated_step_develop`, `teach_generative_core_close` in `tests/evals/loop_tutor.py` (`PEDAGOGY_CASES` / `<slot>__pedagogy`); W0 must record before CI scores | W1 PARTIAL (cases listed; cassette still open) |
| W7.1b | Forest chrome / progress / Check CTAs per `w7-design-decisions.md` | **done** |
| W8.1b | Library Tree `?course=` + Quiz concept-aware when ids exist | **done** (pass `conceptIds` when callers have node ids) |
| W8.3b | Hub Due Reviews deep-link Quiz/Study (not only Flashcards) | **done** (Flashcards + Quiz split CTA) |
| W3.1b | SessionPanel shows kept `prereq_edges` | **done** (`PlanDeps` + `session-plan-deps`) |
| W2.3b | Series invariant scan + Playwright journey stub | **done** (`test_inv_31_*` + learn-loop E2E stubs; stack not run) |
| W0 bounded | Record `loop_tutor_lite` Claude cassette (first slot) | **blocked** — Anthropic 401 invalid `ANTHROPIC_API_KEY` (refresh key, then retry) |

### Day 2 parallel launch (2026-11-23)

**Wave A (product slices — in flight)**

| Track | Scope | Mode |
|---|---|---|
| W3.1 UI | PlanPanel dependency block on `prereq_edges` | **done** |
| W7.1 | Quiz focus-mode session chrome (first slice) | **done** (Hint/Skip/wager still deferred; forest retarget in W7.1b) |
| W1.3 | Generative-core / compression check beat | **done** (E2E + Claude eval cases still open) |
| W8.3 | Study Hub Focus ← `services.learner_next` | **done** (+ W8.3b Due→Quiz CTA) |
| W2.3 | Reason-before-submit (encrypted, not evidence) | **done** (E2E still open) → [`w2-reason-before-submit.md`](w2-reason-before-submit.md) |

**Wave B (coherence + design — launched after Wave A)**

| Track | Scope | Mode |
|---|---|---|
| W8.1 | Library → Tree / Quiz post-upload CTAs | **done** (+ W8.1b course/concept hrefs) |
| W8.2 | Tree node → Teach / Quiz / Cards / Guide | **done** |
| W3.2 | Covered vs understood SessionMap spike | **done** (+ W3.2b UI: `practicedIds`) → [`w3-covered-vs-understood-spike.md`](w3-covered-vs-understood-spike.md) |
| W4 | Visual / SVG / demo pipeline spike | **done** → [`w4-visual-pipeline-spike.md`](w4-visual-pipeline-spike.md) |
| W7.D1 | Quiz design open questions → decisions doc | **done** → [`w7-design-decisions.md`](w7-design-decisions.md) |

**Orchestration (how these compose):** one learner model (`apply_graph_update` / BKT+FSRS) → `learner_next` buckets → Learn plan (`prereq_edges`) + Quiz plan + Study Hub Focus; teach spine (W1 pedagogy + W1.3 generative core) and sensing (W2.3 reasoning field) never write mastery from prose; Quiz shell (W7) and Tree/Library links (W8) are the visible spine over the same data.

**Compliance re-audit (2026-11-23):** [`day2-plan-compliance-audit.md`](day2-plan-compliance-audit.md) — PASS / PARTIAL / SPIKE / BLOCKED vs each acceptance row.

**Still blocked on spend:** W0.1–W0.3 Claude cassette re-record (blocks flag enables + clears W1 prompt-hash drift). **Not in these waves:** W5 enables, W4 build, full W7 question kit.

---

## 11. References

- Videos: V1 `ciC6ffUqI8k`, V2 `kzcI5F4tGiU`, V3 `nfTDljFG2g0`
- `docs/research/learning-loop/notes/direction/design_choices.md`
- `docs/research/learning-loop/2026-11-07-direction-audit.md`
- `docs/learning-loop/flag-rollout.md`, `README.md`, `flows.md`, `glossary.md`
- `backend/learning/surface.py`, `backend/agents/loop_tutor.py`, `backend/services/feature_flags.py`
- `backend/services/quiz/plan.py`, `generation.py`, `submission.py` (A143–A147)
- W8.6 learner-next: `backend/learning/learner_next.py` (pure) + `backend/services/learner_next.py` (IO)
- Repos Alvar published: `amosblomqvist/learn`, `amosblomqvist/learnharness` (inspiration only; not a dependency)
- Quiz design audit package: `HANDOFF.md`, `notes/repo-findings.md`, `github.md` (local Downloads folder, 2026-11-23)
- Quiz shell port map (W7 kickoff): [`quiz-shell-port-map.md`](quiz-shell-port-map.md)
- W7.D2 Hub/Guide/Settings brief: [`w7-d2-hub-guide-settings.md`](w7-d2-hub-guide-settings.md)
- W3.1 plan dependency spike: [`w3-plan-dependency-spike.md`](w3-plan-dependency-spike.md)
- W3.2 covered vs understood spike: [`w3-covered-vs-understood-spike.md`](w3-covered-vs-understood-spike.md)
- W3.3 practice mode spike: [`w3-practice-mode-spike.md`](w3-practice-mode-spike.md)
- W4 visual / grounded-teach spike: [`w4-visual-pipeline-spike.md`](w4-visual-pipeline-spike.md)

---

## 12. One-line summary

**Enable and eval the Alvar dials, teach with V1 philosophy, add evidence-safe sensing, show structure in the UI, reskin Quiz so it is driven by the same learner model/graph as Tutor and Study, and make Library→Tree→Tutor→Quiz→Study one coherent spine — without breaking graded-only belief or the settled Alvar refusals.**

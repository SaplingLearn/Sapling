# Inventory — /dashboard, /learn, /tree

Paths relative to `frontend/src/` unless noted; specs in `frontend/e2e/`; seed = `backend/db/seed_local_rich.py`.

**Seed users:** `rich-user-active` (6 courses, graph in all 4 tiers, sessions `rich-sess-cs-recursion` 4 msgs + `rich-sess-math-vectors` 2 msgs, streak 12) · `rich-user-second` (2 courses) · `rich-user-new` (no enrollments → empty states). Frozen clock 2026-03-11.

**Global switches (localStorage):** `sapling_layout` = `sidebar` (default) | `topnav` (legacy 3-col dashboard) · `sapling.kg.mode` = `2d|3d` · `sapling_disclaimer_ack=true` · `sapling_model_pref` = `fast|smart` · `sapling_shared_ctx` · `sapling_learn_rail_open` = `1|0`. Mobile = < 768px (`lib/useIsMobile.ts`). Route transitions show `app/(shell)/loading.tsx` (`shell-loading`). No flag/role gating in these three screens. `components/companion/*` is public-pages only.

## Shared: KnowledgeGraph

| State id | What the user sees | Trigger | File:line | testids |
|---|---|---|---|---|
| graph/2d-populated | SVG force graph, course hubs, concept nodes (opacity by tier), zoom panel (+ − ⟲), "2D" pill | seeded user | graph/KnowledgeGraph2D.tsx:481-708 | graph-container, graph-node, graph-edge, graph-zoom-*, graph-mode-toggle, graph-node-activate |
| graph/2d-empty | Blank canvas + zoom panel + toggle, no empty copy | `rich-user-new` / filters exclude all | KnowledgeGraph2D.tsx:481 | graph-container |
| graph/node-hover-tooltip | Card: name, course dot + subject, Mastery % bar, tier · last studied | hover node | KnowledgeGraph2D.tsx:710-775 | — |
| graph/highlight-pulse | Animated ring on highlighted node | `highlightId` (suggest/selection) | KnowledgeGraph2D.tsx:573-582 | — |
| graph/node-dragging | Node pinned, tooltip hidden | drag node | KnowledgeGraph2D.tsx:366-377 | — |
| graph/3d | WebGL sphere graph, toggle "3D" | toggle / `sapling.kg.mode=3d` | graph/KnowledgeGraph3D.tsx:160-203 | graph-mode-toggle |
| graph/no-webgl | 2D, toggle dimmed "3D requires WebGL" | stub webgl2 → null | graph/KnowledgeGraph.tsx:264-300 | graph-mode-toggle[aria-disabled] |
| graph/crash-fallback | "The graph couldn't render here." + Try again | renderer throws (inject) | KnowledgeGraph.tsx:160-207 | graph-crash-fallback, graph-crash-retry |

## /dashboard (`components/screens/Dashboard.tsx`)

| State id | What the user sees | Trigger | File:line | testids |
|---|---|---|---|---|
| dashboard/loading | DashboardSkeleton (hero bars + graph card) | delay `GET /api/graph/{uid}` | Dashboard.tsx:392-398; Skeleton.tsx:210 | — |
| dashboard/error | "Couldn't load dashboard" + error + Retry | first-load 500 on graph / courses / calendar upcoming / learn sessions | Dashboard.tsx:400-410 | — |
| dashboard/populated-sidebar | Typewriter greeting + quote; graph card "N concepts across M courses"; right col Review/Search/Start learning, Streak/Mastered, Where you left off (≤3), Upcoming (≤4) | `rich-user-active`, desktop | Dashboard.tsx:974-1041, 518-715 | dashboard-review-due, dashboard-resume-{id} |
| dashboard/greeting-typing | Greeting mid-type, blinking cursor, quote hidden | first ~1–2s | Dashboard.tsx:62-126, 694-713 | — |
| dashboard/greeting-no-name | "Welcome back" | user w/o name | Dashboard.tsx:343-348 | — |
| dashboard/review-due-count | "⚡ Review what's due · N" | due nodes | Dashboard.tsx:513-516 | dashboard-review-due |
| dashboard/review-quiz | "⚡ Quiz" | none due | Dashboard.tsx:516 | dashboard-review-due |
| dashboard/streak-zero / streak-active | "0 days" default / orange number | streak 0 / >0 | Dashboard.tsx:551-566 | — |
| dashboard/mastered-empty | "0 · no concepts yet" | 0 nodes | Dashboard.tsx:575-577 | — |
| dashboard/sessions-empty | "No recent sessions — start learning…" | no sessions | Dashboard.tsx:593-596 | — |
| dashboard/upcoming-empty | "No upcoming assignments." | upcoming → [] | Dashboard.tsx:640-642 | — |
| dashboard/upcoming-chips | OVERDUE / NOW / Nh / Nd warn / Nd info chips | due offsets vs clock | Dashboard.tsx:643-669 | — |
| dashboard/empty-new-student | All empties combined | `rich-user-new` | — | — |
| dashboard/courses-key-collapsed | Bottom-right "MY COURSES ＋" | courses exist | Dashboard.tsx:1183-1291 | dashboard-courses-key-toggle |
| dashboard/courses-key-expanded | 300px overlay: dot, code, %, 4-seg bar, cog, × | click toggle | Dashboard.tsx:1293-1355 | dashboard-courses-manage, dashboard-course-code |
| dashboard/courses-key-empty-term | "Nothing enrolled this semester." | active term with no courses | Dashboard.tsx:1349-1353 | — |
| dashboard/courses-key-hidden | No overlay | 0 courses | Dashboard.tsx:1200 | — |
| dashboard/suggest-banner | "Try this next: {concept}" + Start quiz + Dismiss; node pulses | `?suggest=<name>` | Dashboard.tsx:763-783 | — |
| dashboard/fullscreen-graph | Fullscreen overlay + Esc hint + × | "Fullscreen graph" btn | Dashboard.tsx:1044-1070 | — (aria-label) |
| dashboard/manage-courses-modal | Semester pills, course rows (color, delete), add-course search, "Personal learning · Coming soon" | cog / topnav "Courses & Semesters" | ManageCoursesModal.tsx:108-262 | dashboard-courses-manage |
| dashboard/manage-courses-modal-empty | "No semesters yet…" / "No courses in this semester yet." / "No matches." | `rich-user-new` | ManageCoursesModal.tsx:135-208 | — |
| dashboard/manage-courses-searching | "Searching…", results Add / Adding… / Already taken | type in search | ManageCoursesModal.tsx:205-241 | — |
| dashboard/toast-* | Color updated / Removed X / Failed… | modal actions (500 for failures) | ManageCoursesModal.tsx:285-299; ToastProvider.tsx:100-150 | role=status |
| dashboard/topnav-populated | 3-col legacy: courses+upcoming / hero+graph / actions, week streak strip, MiniStats, Learn next | `sapling_layout=topnav` | Dashboard.tsx:807-972 | dashboard-review-due |
| dashboard/topnav-streak-strip | 7 day marks done/today/missed/future + copy | last_studied dates this week | Dashboard.tsx:887-916, 131-182 | — |
| dashboard/topnav-learn-next-empty | "Nothing suggested yet — start a session." | recommendations [] / 500 | Dashboard.tsx:936-938 | — |
| dashboard/topnav-courses-empty | "No enrolled courses yet." / "Nothing enrolled this semester." | 0 courses | Dashboard.tsx:816-822 | — |
| dashboard/mobile-sidebar | Single column hero, full-width review, Library+Start row, graph, stats | < 768 | Dashboard.tsx:717-761 | dashboard-review-due |
| dashboard/mobile-topnav-courses / -stats | Tab bar "My Courses \| Stats & More" | < 768 + topnav | Dashboard.tsx:976-1018 | — |

**Transitions:** loading→populated|error · error –Retry→ loading · key toggle ↔ expanded · expanded –cog→ manage modal –×/Esc→ back · modal term pill → scoped (maybe empty-term) · Fullscreen ↔ × · graph node → `/learn?topic=…&mode=socratic&course=…` · review-due → `/quiz?scope=due&from=dashboard&return=/dashboard` (or `/quiz?from=dashboard`) · Search/Library → /library · Start learning / View all → /learn · resume-{id} → `/learn?resume={id}` · Calendar → → /calendar · suggest Start quiz → `/quiz?concept={id}&from=dashboard`; Dismiss strips param · topnav Tree → /tree, Learn-next → /learn?topic, Study room → /social · mobile tabs ↔.

## /learn (`components/screens/Learn.tsx`, `components/chat/*`, `DisclaimerModal.tsx`)

| State id | What the user sees | Trigger | File:line | testids |
|---|---|---|---|---|
| learn/suspense-loading | "Loading…" | Suspense (brief) | Learn.tsx:327-333 | — |
| learn/disclaimer-modal | "Heads up / Sapling uses AI", Terms/Privacy, Got it | no `sapling_disclaimer_ack` | DisclaimerModal.tsx:35-110 | role=dialog |
| learn/entry-populated | "Start a session": course select, topic picker, mode toggle (Socratic/Expository/Teach-back), Class intel switch, Start; Recent sessions card | `rich-user-active` | Learn.tsx:1249-1316 | tutor-topic-picker, tutor-start, tutor-session-resume-{id} |
| learn/entry-empty | Only "No course", "No recent sessions yet.", Start disabled | `rich-user-new` | Learn.tsx:1299-1309 | tutor-start[disabled] |
| learn/entry-topic-prefilled | Picker filled, mode/course preselected | `?topic=X&mode=…&course=…` | Learn.tsx:346-353 | tutor-topic-picker |
| learn/entry-course-select-open | CustomSelect dropdown | click select | Learn.tsx:1270-1278 | — |
| learn/topic-picker-open | Search + "General" row + concept list | click picker | Learn.tsx:2059-2158 | tutor-topic-search |
| learn/topic-picker-custom | "Use custom topic: "…"" | unmatched query | Learn.tsx:2113-2124 | — |
| learn/topic-picker-empty-course / -empty-graph | "No concepts in this course yet…" / "No concepts in your graph yet." | 0 nodes | Learn.tsx:2125-2131 | — |
| learn/topic-general-selected | "General — pick what's next in {CODE}" | pick General | Learn.tsx:2007-2018 | — |
| learn/shared-ctx-off / -tooltip | Switch grey / 240px tooltip | toggle / hover | SharedContextToggle.tsx:103-170 | role=switch |
| learn/ai-chip-tooltip / -modal | "AI powered learning…" tooltip / disclaimer | hover / click chip | AIDisclaimerChip.tsx:46-83 | — |
| learn/session-row-renaming | Inline input | pencil | Learn.tsx:1891-1922 | — |
| learn/session-row-delete-armed | Red "Confirm" 3s | × once | Learn.tsx:1955-1963 | — |
| learn/toast-session-deleted / -delete-failed / -rename-failed | toasts | DELETE/PATCH 500 | Learn.tsx:700-730 | — |
| learn/resume-loading | "Loading…" | `?resume={id}` | Learn.tsx:1238-1247 | tutor-resume-loading |
| learn/resume-failed | Entry + toast | resume 404/500 | Learn.tsx:674-676 | — |
| learn/starting-thinking | Chat, "Thinking…" bubble, Stop, input disabled | Start; delay start-session/stream | Learn.tsx:584-652; ChatPanel.tsx:126-146 | tutor-messages, tutor-stop |
| learn/streaming-status | "Searching your course materials…" / "Checking your progress…" / "Reviewing this conversation…" / "Updating your knowledge graph…" | SSE progress events | ChatPanel.tsx:22-38, 339 | — |
| learn/streaming-text | Bubble growing, Stop, composer disabled | send (E2E_SLOW_STREAM ~6s) | ChatPanel.tsx:126-157 | tutor-stop, tutor-input[disabled] |
| learn/greeting-failed | Entry w/ topic + toast | start stream + JSON 500 | Learn.tsx:643-646 | — |
| learn/active-idle | Breadcrumb, title, "CODE · Socratic Tutor · N Messages", Class intel, End session; mode chips, AI chip, Fast/Smart; message log; Hint/Confused/Skip + textarea + Send; rail 400px | resume seeded session | Learn.tsx:1322-1400 | tutor-back-to-learn, tutor-input, tutor-send, tutor-action-* |
| learn/active-finished-reply | Final reply, Stop gone | stream done | Learn.tsx:850-852 | — |
| learn/interrupted-stopped | Dimmed partial + "Interrupted" + Retry | Stop mid-stream | ChatPanel.tsx:348-377 | tutor-interrupted, tutor-retry |
| learn/interrupted-error | Same + error toast | stream fails after tokens | Learn.tsx:810-829 | tutor-interrupted |
| learn/json-fallback-pending | User bubble, no Thinking/Stop | abort chat/stream | Learn.tsx:830-842 | — |
| learn/action-loading / -failed | "(Requested a hint)" + Thinking / removed + toast | action btn / POST action 500 | Learn.tsx:894-916 | tutor-action-* |
| learn/mode-switched / -failed | Chip active + transition msg / revert + toast | mode chip / 500 | Learn.tsx:918-935 | — |
| learn/model-fast / -smart / -tooltip | Blue Fast / purple Smart slider / tooltip | click / hover | ModelToggle.tsx:72-151 | role=radiogroup |
| learn/end-armed | Red "Confirm end" 3s | End session once | Learn.tsx:956, 1358-1364 | — |
| learn/summary-modal | Session summary: minutes, concepts chips, mastery changes, recommended next, Done | confirm end | SessionSummary.tsx:12-118 | — |
| learn/summary-minimal | "Session wrapped." + Done | empty summary | SessionSummary.tsx:47-111 | — |
| learn/end-failed | toast | end-session 500 | Learn.tsx:951-953 | — |
| learn/markdown-rich | Headings, lists, tables, code, KaTeX, images | rich assistant content | chat/MarkdownChat.tsx:150-415 | — |
| learn/markdown-mermaid | Rendering… → diagram / Mermaid error | mermaid fence | chat/MermaidBlock.tsx:67-100 | — |
| learn/markdown-plot | Function plot / Plot error | plot fence | chat/FunctionPlot.tsx:104-125 | — |
| learn/rail-open-concept | KNOWLEDGE MAP, course graph + legend, Focused concept card, In this branch, Elsewhere chips, ＋ Add concept | resumed Recursion | Learn.tsx:1403-1691 | tutor-focus-concept-description |
| learn/rail-focus-current / -other | Only Remove / Start or Resume session + Remove | focus = topic / other node | Learn.tsx:1010-1020, 1514-1541 | graph-node-activate |
| learn/rail-tier-badges | Mastered / In progress / Needs work / Not started | each tier | Learn.tsx:73-78 | — |
| learn/rail-desc-variants | stored / AI blurb / fallback copy | concept-description ok/fail | Learn.tsx:1155-1169 | — |
| learn/rail-focused-course | "Focused course" card | course but non-node topic | Learn.tsx:1471-1511 | — |
| learn/rail-bare | Topic header only | free text, no course | Learn.tsx:1435-1446 | — |
| learn/rail-add-composer / -merged / -failed | input + Add / merged toast / error | ＋ Add concept; POST nodes | Learn.tsx:1177-1224, 1630-1669 | — |
| learn/rail-streamed-node | Placeholder node appears mid-stream | SSE graph_update | Learn.tsx:446-452 | graph-node-item |
| learn/rail-collapsed / -dragging | Edge tab only / intermediate width | edge tab / drag | Learn.tsx:1026-1056, 1694-1757 | aria "Toggle knowledge map" |
| learn/suggest-highlight | Rail node pulses | `?suggest=` | Learn.tsx:398-408 | — |
| learn/mobile-entry / -chat-tab / -graph-tab | 1-col entry / "Chat \| Graph" tabs | < 768 | Learn.tsx:1262, 1326-1407 | — |

**Transitions:** first visit → disclaimer –Got it→ underlying · picker → prefilled –Start→ thinking → streaming → active-idle (or greeting-failed) · resume row → active-idle · send → status → text → finished · Stop → interrupted –Retry→ streaming · actions → action-loading → idle/failed · mode chip → mode-switched · End → armed –click 3s→ summary –Done→ entry; recommended chip → prefilled · back-to-learn → entry · rail node click → focus-other –Start/Resume or dbl-click→ new session · Remove · ＋Add → composer · edge tab ↔ collapsed · mobile tabs ↔.

## /tree (`components/screens/Tree.tsx`, `TopicChecklistPanel.tsx`)

| State id | What the user sees | Trigger | File:line | testids |
|---|---|---|---|---|
| tree/loading | Toolbar "0 nodes", GraphPanelSkeleton | before graph GET | Tree.tsx:577-579 | — |
| tree/populated | Search, tier pills (All/Mastered/Learning/Struggling/Unexplored), "N nodes", course pills, graph | `rich-user-active` | Tree.tsx:441-603 | graph-container, graph-course-filter-{id} |
| tree/empty | "All courses" only, 0 nodes, blank canvas (ALSO the load-error state) | `rich-user-new` | Tree.tsx:107-131 | — |
| tree/search-filtered / filtered-zero | Reduced graph / 0 nodes | type search | Tree.tsx:245-260 | — |
| tree/tier-filtered | Tier pill colored | click tier | Tree.tsx:480-491 | — |
| tree/course-filtered | Course pill filled, ＋ Add concept, Topic checklist bar | course pill | Tree.tsx:508-566 | graph-add-concept, topic-checklist-toggle |
| tree/add-concept-composer | Input + Add | ＋ Add concept | Tree.tsx:526-551 | graph-add-concept-input/-submit |
| tree/toast-added / -merged / -add-failed | toasts | POST nodes | Tree.tsx:175-194 | — |
| tree/checklist-loading | "Updating checklist…" | delay checklist GET | TopicChecklistPanel.tsx:96-115 | topic-checklist, topic-checklist-refresh |
| tree/checklist-populated | Topic rows w/ status, mastery, description, gaps, assessments, sources | cs101 seed | TopicChecklistPanel.tsx:119-139 | topic-checklist-topic-{id}, -check-{id}, -filter |
| tree/checklist-semester-select | Extra Semester select | multi-term, no active semester | TopicChecklistPanel.tsx:101-106 | topic-checklist-semester |
| tree/checklist-stale / -warnings / -empty-filter / -error | stale notice / warnings / "No topics match this view." / alert | needs_refresh / warnings / filter / 500 | TopicChecklistPanel.tsx:47-122 | — |
| tree/detail-concept | 320px aside: mastery, tier, last studied, Learn this, Quick quiz, Delete, Recent quizzes, Sessions | click node | Tree.tsx:325-439 | tree-node-recent-quizzes |
| tree/detail-quizzes-loading / -empty / -rows | Loading… / No quizzes yet / rows "4/5 · +12% mastery" | attempts GET | Tree.tsx:380-409 | tree-node-recent-quiz-{id} |
| tree/detail-delete-armed | "Click again to confirm" | Delete once | Tree.tsx:363-376 | — |
| tree/toast-deleted / -delete-failed | toasts | DELETE node | Tree.tsx:313-323 | — |
| tree/detail-subject-root | Panel without Delete/quizzes | click hub | Tree.tsx:363, 377 | — |
| tree/node-param / suggest-param | Panel open on load / pulse | `?node=` / `?suggest=` | Tree.tsx:203-227 | — |
| tree/fullscreen | Fullscreen overlay | Fullscreen btn | Tree.tsx:626-644 | — |
| tree/mobile-bottom-sheet | Slide-up sheet (80vh) | < 768 + select | Tree.tsx:605-624 | — |

**Transitions:** loading → populated|empty · tier/search/course filters ↔ · course-filtered → add composer → toast · checklist toggle → loading → populated; check box / refresh · node → detail (desktop) / sheet (mobile) –×→ populated · Learn this → `/learn?topic=…` · Quick quiz → `/quiz?concept={id}&from=tree&return=/tree?node={id}` · session row → `/learn?resume=` · Delete → armed → toast · Fullscreen ↔ · /quiz exit → `/tree?node=`.

## Uncertain / needs a human
1. Dashboard error banner only on first-load failure with no cached courses.
2. Tree has no error state (looks identical to empty) — design one that doesn't exist in code?
3. No graph shows empty-state copy anywhere.
4. Missing testids: fullscreen buttons, disclaimer Got it, mode chips, model toggle, End session, summary modal → prototype hotspots anchor by text/role.
5. "Personal best" always equals current streak — placeholder?
6. Mid-stream states (progress labels, graph_update nodes, crash fallback) need a mocked SSE body.
7. Typewriter/quote are timed — separate typing vs settled frames.
8. ManageCoursesModal internals only skimmed.
9. Pending-user gating not confirmed for these routes.

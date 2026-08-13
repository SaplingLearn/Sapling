# Frontend `data-testid` convention

Browser tests (Playwright, #385) must anchor on `data-testid`. They must **not**
anchor on CSS classes or copy: the app is mid-redesign, classes are utility-ish
(`btn btn--primary btn--sm`) and non-unique, and every copy tweak would break a
selector. `data-testid` is the one attribute that exists purely as a test
contract and can be kept stable across visual churn.

Introduced by #382. Scope today is the six surfaces the Chapter-1 regression
suite drives, plus the authed app-shell anchor added with the Playwright
harness (#385); this is deliberately **not** a whole-app sweep.

## Naming

Kebab-case, `<surface>-<element>`:

```
signin-google-button
pending-gate
upload-modal-dropzone
tutor-input
tutor-send
quiz-answer-option-A
graph-container
```

Rules:

1. **Surface prefix first.** One prefix per surface (`signin`, `pending`,
   `upload-modal`, `tutor`, `quiz`, `graph`). The prefix names the user-facing
   surface, not the React component — `tutor-input` lives in `ChatPanel.tsx`
   because that is where the tutor composer renders.
2. **Element name describes the role, not the markup or the copy.**
   `quiz-submit-answer`, not `quiz-primary-btn` and not `quiz-submit-answer-button`
   for a `<button>`. Suffix with `-button` / `-input` only when it disambiguates
   (`signin-google-button` vs. the `signin-trigger` on the landing nav).
3. **Container roots get a bare noun**: `signin-modal`, `upload-modal`,
   `quiz-panel`, `graph-container`, `pending-gate`.
4. **Lowercase and hyphens only**, except for a stable id suffix (below).
5. **Stable across redesigns.** A testid is API. Renaming one is a breaking
   change to the browser suite — do it in the same PR as the test update.

## Repeated / list items

A repeated element gets the base name plus a suffix. Pick, in order of
preference:

1. **A stable domain id** the test can predict or read from the payload.
   Quiz answers use the option's own label (`A`/`B`/`C`/`D`), so:
   `quiz-answer-option-${o.label}` → `quiz-answer-option-A`. Catalog courses use
   the catalog id: `upload-modal-course-result-${c.id}`.
2. **A render index** when there is no stable id worth exposing. Upload rows key
   on the queue position: `upload-modal-file-row-${idx}`,
   `upload-modal-file-remove-${idx}`.

Never suffix with a user-visible string (file name, course title, question
text) — that is copy-anchoring by another route.

When a list needs a "the whole list" handle, add a plural container testid next
to the items: `quiz-answer-options` wraps `quiz-answer-option-*`.

## Where the testids live

The surface prefix is a UX concept; the attribute goes on the file that actually
renders the element.

| Surface | Prefix | Owning file(s) |
| --- | --- | --- |
| Sign-in | `signin` | `frontend/src/components/marketing/SignInModal.tsx` (+ the trigger in `src/app/(public)/page.tsx`) |
| Approval gate | `pending` | `frontend/src/app/pending/page.tsx` |
| Onboarding | `onboarding` | `frontend/src/components/screens/Onboarding.tsx` (the first-run funnel, rendered bare outside `(shell)`) |
| Upload modal | `upload-modal` | `frontend/src/components/DocumentUploadModal.tsx` |
| Tutor | `tutor` | `frontend/src/components/chat/ChatPanel.tsx` (rendered by `screens/Learn.tsx`; + the session-resume rows in `src/components/screens/Learn.tsx` itself) |
| Quiz | `quiz` | `frontend/src/components/QuizPanel.tsx` (rendered by `screens/Quiz.tsx`) |
| Knowledge graph | `graph` | `frontend/src/components/graph/KnowledgeGraph.tsx` (wrapper: container root + mode toggle) plus `KnowledgeGraph2D.tsx`/`KnowledgeGraph3D.tsx` (the render/data-layer seam — hidden a11y node list, SVG node/edge marks, zoom controls — added with the #395 graph-integrity journey) |
| App shell | `app` | `frontend/src/components/ShellFrame.tsx` (the authed layout frame every `(shell)` route renders inside) |
| Study rooms | `social` | `frontend/src/components/screens/Social.tsx` (rooms sidebar, chat, overview, study match, directory — added with the #394 two-context journey) |
| Dashboard | `dashboard` | `frontend/src/components/screens/Dashboard.tsx` (rendered by `(shell)/dashboard/page.tsx`) |
| Library | `library` | `frontend/src/components/screens/Library.tsx` (the `/library` document screen — upload trigger, document cards/rows, filters, detail panel) |
| Calendar | `calendar` | `frontend/src/components/screens/Calendar.tsx` (the `/calendar` screen — today just the #185 load-failure banner + retry) |
| Gradebook | `gradebook` | `frontend/src/components/screens/Gradebook/Landing.tsx` + `Course.tsx` (the `/gradebook` screens), `frontend/src/components/Gradebook/TranscriptModal.tsx` (the transcript modal), `frontend/src/components/Gradebook/CourseCard.tsx` (the term-aware card links), `frontend/src/components/Gradebook/AssignmentList.tsx` + `AssignmentModal.tsx` (the add-assignment flow the #468 mutation leg drives) — added with the #139 term-switcher/transcript journey |
| Admin analytics | `admin-analytics` | `frontend/src/components/screens/AdminAnalytics.tsx` (the `/admin/analytics` dashboard — range presets/inputs, cost group-by toggle, per-panel retry) — added with the #121 data layer |
| Landing knowledge graph demo | `landing-graph` | `frontend/src/components/marketing/graph/KnowledgeGraphDemo.tsx` (the pre-auth landing page's interactive course-picker + laid-out concept graph, wearing the `landing-surface` chrome with an inspector rail and mastery legend since #344 step 3) |
| Landing feature bands | `landing-band` | `frontend/src/components/marketing/FeatureBand.tsx` (the three full-width bands below the graph; content + side-alternation in `featureBands.tsx`, #344 step 2) |
| Landing surface bento | `landing-bento` | `frontend/src/components/marketing/SurfaceBento.tsx` (the four-tile grid of built product surfaces, #344 step 2) |
| Landing product surfaces | `landing-surface` | `frontend/src/components/marketing/surfaces/*.tsx` (the seven in-page recreations the bands and bento mount, #344 step 2) |
| Admin feedback | `adminfb` | `frontend/src/components/screens/Admin.tsx` (the `feedback` tab — decrypted-server-side feedback + issue-report review, #520) |
| Profile | `profile` | `frontend/src/components/ProfileView.tsx` (the add-friend action rendered on another user's profile — `Settings.tsx` and `app/(shell)/profile/[userId]/page.tsx` both mount `ProfileView`, but the interactive control lives in this one file) — added with the gamification/friends work (Task 16/17) |
| Achievements | `achievements` (see note below) | `frontend/src/components/screens/Achievements.tsx` (tab bar, showcase) + `frontend/src/components/screens/achievements/HeroCard.tsx` (level/XP hero) + `LeaderboardTab.tsx` + `ActivityTab.tsx` — the `/achievements` screen added across Tasks 13–14, testids added with the Task 17 E2E journey |

Two surfaces do **not** carry their testids in the screen file named by the
route:

- **Tutor.** `screens/Learn.tsx` passes `onSend` to `ChatPanel`; the `<textarea>`
  and the send `<button>` render in `ChatPanel.tsx`. `ChatPanel` has exactly one
  consumer (Learn), so tagging it there is unambiguous. The notetaker's chat is
  a separate `AIChatPanel` and is out of scope.
- **Quiz.** `screens/Quiz.tsx` only fetches concepts and mounts `QuizPanel`;
  every answer/submit control renders in `QuizPanel.tsx`.

## Current inventory

### `signin`

| testid | element |
| --- | --- |
| `signin-trigger` | landing-nav "Sign In" button that opens the modal |
| `signin-modal` | modal panel root (`role="dialog"`) |
| `signin-close` | × close button |
| `signin-google-button` | "Continue with Google" |
| `signin-cancel` | "Cancel" (only while waiting on the popup) |
| `signin-error` | error banner |

### `pending`

| testid | element |
| --- | --- |
| `pending-gate` | approval-gate page root |
| `pending-signout` | "Sign out" |
| `onboarding-gate` | first-run onboarding page root |
| `onboarding-continue` | primary advance button ("Continue" / "Enter Sapling →") |
| `onboarding-back` | "Back" (absent on step 0) |
| `onboarding-close` | "×" close/exit control |
| `onboarding-input` | the shared `TextInput` default; every simultaneous instance overrides it (below) |
| `onboarding-first-name` / `onboarding-last-name` | the two name fields — they render side by side |
| `onboarding-school` | school field (disabled; BU-only today) |
| `onboarding-chip-input-${field}` / `onboarding-chip-add-${field}` | majors/minors editor — `field` is `majors` or `minors`, since both render at once |
| `onboarding-chip-remove-${field}-${value}` | one chip's remove control |
| `onboarding-course-search` | course search field |
| `onboarding-course-result-${course.id}` | one course search result |
| `onboarding-course-remove-${course_code}` | one selected-course chip's remove control |
| `onboarding-learning-style-${style.id}` | one learning-style radio option (5 render at once) |

### `upload-modal`

| testid | element |
| --- | --- |
| `upload-modal` | modal card root |
| `upload-modal-close` | header × |
| `upload-modal-dropzone` | drag & drop target |
| `upload-modal-browse` | "Browse" label wrapping the file input |
| `upload-modal-file-input` | the hidden `<input type="file">` (use `setInputFiles`) |
| `upload-modal-course-search` | "+ Add a course" search input |
| `upload-modal-course-result-{courseId}` | a course search result |
| `upload-modal-file-row-{idx}` | a queued file row |
| `upload-modal-file-remove-{idx}` | remove that row |
| `upload-modal-file-reanalyze-{idx}` | "Re-analyze" (processed rows) |
| `upload-modal-file-retry-{idx}` | "Retry" (error/aborted rows) |
| `upload-modal-file-copy-request-id-{idx}` | "copy" the support reference |
| `upload-modal-cancel` | footer "Cancel" |
| `upload-modal-submit` | footer "Start upload" |
| `upload-modal-done` | footer "Done" (replaces submit once every row finished) |

### `tutor`

| testid | element |
| --- | --- |
| `tutor-messages` | conversation log (`role="log"`) |
| `tutor-input` | message `<textarea>` |
| `tutor-send` | send button |
| `tutor-stop` | stop-streaming button (visible only while a streamed reply is in flight, #349) |
| `tutor-action-hint` | "Hint" |
| `tutor-action-confused` | "I'm confused" |
| `tutor-action-skip` | "Skip" |
| `tutor-session-resume-{sessionId}` | a "Recent sessions" row's resume button (`screens/Learn.tsx`), suffixed with the session's own id per the stable-domain-id rule |
| `tutor-interrupted` | the "Interrupted" marker inside a stopped/failed assistant bubble (ADR 0020, #356; the partial text stays in the bubble itself) |
| `tutor-retry` | the Retry button inside that marker — re-dispatches the interrupted turn |
| `tutor-back-to-learn` | the chat header's breadcrumb back to the session picker (`screens/Learn.tsx::BackToLearnLink`) |
| `tutor-resume-loading` | the transient loading state while a `/learn?resume=` deep link hydrates (#164) |
| `tutor-focus-concept-description` | the knowledge-map rail's "Focused concept" card description text (`screens/Learn.tsx`) — stored `description` if the node has one, else the AI-fetched blurb (`POST /api/graph/{user}/concept-description`, #446), else the connected-concepts fallback sentence |
| `tutor-topic-picker` | the entry screen's topic dropdown trigger (`screens/Learn.tsx::TopicPicker`) — opens the concept/custom-topic search |
| `tutor-topic-search` | the search input inside the open topic dropdown; Enter picks the first match, or the typed text as a custom topic |
| `tutor-start` | the entry screen's "Start learning" button — dispatches the streamed session opener (#151a greeting journey) |

### `quiz`

| testid | element |
| --- | --- |
| `quiz-panel` | panel root (all phases) |
| `quiz-cancel` | "Cancel" (select phase) |
| `quiz-start` | "Start quiz" |
| `quiz-answer-options` | answer radiogroup |
| `quiz-answer-option-{label}` | one answer choice, suffixed with its label (`A`…) |
| `quiz-submit-answer` | "Submit answer" |
| `quiz-exit` | "Exit" (active phase) |
| `quiz-review-verdict` | "Correct." / "Not quite." banner |
| `quiz-explain-concept` | "Explain this" |
| `quiz-next` | "Next question" / "See results" |
| `quiz-results-score` | the score percentage |
| `quiz-results-mastery` | the "X / Y correct · mastery B% → A%" line |
| `quiz-retake` | "Retake" |
| `quiz-done` | "Done" |

### `graph`

| testid | element |
| --- | --- |
| `graph-container` | graph wrapper root (sized box holding 2D or 3D) |
| `graph-mode-toggle` | 2D ⇄ 3D toggle |
| `graph-node-items` | hidden a11y node list (`<ul>`) — the whole-list handle; mirrors the rendered nodes 1:1 (2D and 3D) |
| `graph-node-item` | one a11y list entry (`<li>`); carries `data-node-id={node.id}` so tests assert by node identity, never by label — concept names are only unique per course (2D and 3D) |
| `graph-node-activate` | the activation `<button>` inside an a11y entry (when the graph is clickable) |
| `graph-node` | 2D SVG node group (`<g>`); carries `data-node-id={node.id}` |
| `graph-node-circle` | the main circle inside a 2D node group — the mark that encodes the mastery tier as `opacity` |
| `graph-edge` | one 2D SVG edge `<line>` |
| `graph-zoom-in` / `graph-zoom-out` / `graph-zoom-reset` | 2D zoom controls |
| `graph-add-concept` | Tree toolbar: "＋ Add concept" opener (#330) — rendered only when a single course pill is selected (the "all" filter gives no course to attribute the node to) |
| `graph-add-concept-input` | the concept-name `<input>` (Enter submits, Escape cancels) |
| `graph-add-concept-submit` | the "Add" button — POSTs create-or-merge, toasts, reloads the graph |
| `graph-crash-fallback` | graph-local crash placeholder (#538) — rendered by the wrapper's error boundary when a renderer throws; never contains a graph |
| `graph-crash-retry` | "Try again" button inside the crash placeholder — wired to the boundary's reset |

`graph-node-item` / `graph-node` carry the node id as a separate
`data-node-id` attribute instead of a testid suffix (the repeated-items rule
above): graph node ids are long seeded/UUID strings, and the pair
`[data-testid="graph-node-item"][data-node-id="…"]` keeps both the "all
items" handle and the exact-id handle selectable. The 2D and 3D variants
share these testids — only one implementation mounts at a time, so they
never collide in the DOM.

### `app`

| testid | element |
| --- | --- |
| `app-shell` | authed shell root — the scrolling `<main id="main-content">` in `ShellFrame.tsx`, present in both (top-nav and sidebar) layout variants; the Playwright harness smoke spec (#385) anchors on it as the "authed shell mounted" signal |
| `error-fallback` | root `ErrorFallback` surface (`ErrorBoundary.tsx`) — the whole-app "We hit a snag" page; journeys assert its ABSENCE (#538) so the check survives copy rewording |

### `social`

| testid | element |
| --- | --- |
| `social-create-room` | sidebar "Create" (opens the room-name input) |
| `social-join-room` | sidebar "Join" (opens the invite-code input) |
| `social-create-join-input` | shared create/join text input |
| `social-create-join-submit` | "Go" |
| `social-create-topic` / `social-create-course` | create-mode optional labeling inputs (#405) |
| `social-create-public` | create-mode "Public" checkbox (#405) — public rooms are joinable without an invite |
| `social-public-join-{roomId}` | "Join" on a discovered public room (stable domain id, #405) |
| `social-room-item-{roomId}` | a room in the sidebar list (stable seeded/domain id) |
| `social-room-name` | active room title in the header |
| `social-invite-copy` | invite-code copy chip in the header |
| `social-directory-open` | sidebar "Browse directory" |
| `social-directory-search` | directory search input |
| `social-chat-messages` | chat scroll log (the "messages render here" container) |
| `social-chat-message-{messageId}` | one message row (server UUID suffix) |
| `social-chat-load-earlier` | "Load earlier messages" |
| `social-chat-input` | message composer `<textarea>` |
| `social-chat-send` | send button |
| `social-chat-attach` | attach-image button |
| `social-chat-image-input` | hidden `<input type="file">` (use `setInputFiles`) |
| `social-chat-reply-cancel` | × on the "Replying to…" bar |
| `social-chat-mention-{userId}` | an @mention autocomplete option |
| `social-chat-message-react` | per-message menu: open emoji picker (one menu open at a time) |
| `social-chat-message-reply` | per-message menu: reply |
| `social-chat-message-edit` | per-message menu: edit (own messages) |
| `social-chat-message-delete` | per-message menu: delete (own messages) |
| `social-chat-emoji-{emoji}` | an option in the emoji picker grid |
| `social-chat-reaction-{emoji}` | an existing reaction chip on a message (scope by the message row) |
| `social-chat-edit-input` | inline edit input |
| `social-chat-edit-save` | inline edit "Save" |
| `social-chat-edit-cancel` | inline edit cancel |
| `social-room-leave` | overview "Leave room" |
| `social-member-{userId}` | a member row on the overview |
| `social-member-kick-{userId}` | "Kick" on that member row (leader only) |
| `social-match-run` | "Find matches" on the study-match tab |
| `social-friend-row-{userId}` | a friend row in the Friends panel (`FriendsPanel`/`FriendRow`, Task 16) |
| `social-friend-remove-{userId}` | "Remove" on that friend row (two-click confirm) |
| `social-friend-incoming-{requestId}` | an incoming friend-request row |
| `social-friend-accept-{requestId}` | "Accept" on an incoming request |
| `social-friend-decline-{requestId}` | "Decline" on an incoming request |
| `social-friend-outgoing-{requestId}` | an outgoing (pending) friend-request row |

### `dashboard`

| testid | element |
| --- | --- |
| `dashboard-courses-key-toggle` | expand/collapse toggle of the "My courses" key overlay on the graph panel (default sidebar layout; the key starts collapsed) |
| `dashboard-course-code` | a course row's code/name label inside the expanded key — repeated per course with **no suffix** (deliberate deviation from the suffix rule above: journeys select a row by seeded content, `getByTestId(…).filter({ hasText })`, so no per-row identity is exposed) |
| `dashboard-courses-manage` | the cog inside the expanded key that opens the Courses & Semesters hub (the hub's own semester tabs are plain text buttons — journeys select them by role/name, e.g. "All semesters" / "Fall 2025") |
| `dashboard-resume-{sessionId}` | a "Where you left off" card — deep-links to `/learn?resume={sessionId}` (#164), suffixed with the session's own id per the stable-domain-id rule |

### `calendar`

Added with the #185 load-failure fix (a failed initial fetch must be
distinguishable from a genuinely empty calendar).

| testid | element |
| --- | --- |
| `calendar-load-error` | the load-failure banner (`role="alert"`) rendered instead of the calendar views when the initial assignments/courses fetch fails |
| `calendar-load-retry` | the banner's "Try again" button — re-runs the load through the skeleton state |

### `gradebook`

Added with the #139 term-switcher/transcript journey. The landing's semester
chips and the course cards stay untagged on purpose: chips are `Toggle`
buttons selected by role/name (the term label is seeded DATA, not copy —
same posture as the Courses & Semesters hub tabs), and the cards are links
inside the `role="grid"` "Courses" grid.

| testid | element |
| --- | --- |
| `gradebook-term-gpa` | landing: the selected term's credit-weighted GPA next to the chips (absent while the term has no graded work) |
| `gradebook-transcript-open` | landing: "Transcript" button opening the transcript modal |
| `gradebook-transcript-gpa` | transcript modal: the cumulative GPA value |
| `gradebook-transcript-retry` | transcript modal: inline "Try again" after a failed load (#463 catch+toast pattern) |
| `gradebook-add-assignment` | course page: "+ Add Assignment" (`AssignmentList.tsx`) — opens the assignment modal |
| `gradebook-assignment-title` | assignment modal: the required title `<input>` |
| `gradebook-assignment-save` | assignment modal: the Save button |

### `admin-analytics`

Added with the #121 data layer (raw tables; #122 replaces the tables with
charts on the same testids). Every interactive element is tagged — the file
entered the lint block new, so there is no baselined backlog.

| testid | element |
| --- | --- |
| `admin-analytics-range-7d` / `-30d` / `-90d` | the last-N-days range presets — each re-queries every panel |
| `admin-analytics-range-from` / `-to` | the custom date inputs (UTC day start/end) |
| `admin-analytics-cost-group-feature` / `-user` / `-model` | the LLM-cost group-by toggle (drives the `group_by` query) |
| `admin-analytics-usage-retry` / `-users-retry` / `-cost-retry` / `-errors-retry` | per-panel "Try again" after a failed load (`error && !data` gate) |
| `admin-analytics-users-sort-events` / `-cost` / `-tokens` | Top-users table column-sort headers (#122) — first click sorts desc, second flips |

### `profile`

Added with the Task 16/17 friends work — the add-friend action rendered on
someone else's profile (`AddFriendAction` in `ProfileView.tsx`).

| testid | element |
| --- | --- |
| `profile-friend-status` | "Friends" chip shown in place of the button once already friends |
| `profile-add-friend` | "Add friend" / disabled "Request sent" button |

### `achievements`

Added with the Task 17 E2E journey over the `/achievements` screen
(`Achievements.tsx` + `screens/achievements/*.tsx`, built in Tasks 13–14).
The surface spans four files, and — unlike every other multi-file surface
above — the testids are **not** all `achievements-`-prefixed: the hero/level/
XP readout uses a `gamification-` prefix (the XP/level system's own name,
reused verbatim from the spec this journey was written against) and the
leaderboard/activity tab panels prefix with their own tab name
(`leaderboard-`, `activity-`) since each panel is a distinct, self-contained
sub-view a test targets independently of the `achievements-tab-*` control
that opens it. Treat this as the fixed vocabulary for the `/achievements`
screen; don't add a fifth prefix here without a reason as strong as these.

| testid | element |
| --- | --- |
| `achievements-tab-achievements` / `-leaderboard` / `-activity` | the three tab-bar buttons (`Achievements.tsx::TabBar`) |
| `achievements-showcase-remove-{achievementId}` | the showcase card's "×" remove-from-showcase button, suffixed with the achievement id |
| `gamification-hero` | the hero card root (`achievements/HeroCard.tsx`) — level ring, growth-stage art, XP bar |
| `gamification-level` | the "LVL {n}" pill on the hero card |
| `gamification-total-xp` | the plain numeric total-XP readout on the hero card (no thousands separator, so tests can `Number()` it directly) |
| `leaderboard-row-you` | the current viewer's row in the leaderboard list (`achievements/LeaderboardTab.tsx::RankRow`), present only when `row.is_you` |
| `activity-week-total` | the "Week total" stat tile's value on the Activity tab (`achievements/ActivityTab.tsx`) |

### `library`

Added with the upload → SSE → library journey (#387).

| testid | element |
| --- | --- |
| `library-upload` | TopBar "Upload" button that opens the upload modal (disabled with zero courses) |
| `library-search` | TopBar "Search documents…" input |
| `library-course-scan` | TopBar "Scan <course>" button (only while a course filter is active) |
| `library-doc-{docId}` | one document card (grid view) / row (list view), suffixed with the document's id |
| `library-course-filter-all` | sidebar "All" course filter |
| `library-course-filter-uncategorized` | sidebar "Uncategorized" course filter |
| `library-course-filter-{courseId}` | sidebar per-course filter row |
| `library-detail-close` | detail panel × close |
| `library-detail-scan` | detail panel "Scan" / "Re-scan" concept-scan button |
| `library-detail-delete` | detail panel "Delete document" (click-twice confirm) |
| `library-concepts-toggle-all` | detail panel "Expand all" / "Collapse all" |
| `library-concept-toggle-{idx}` | one concept accordion toggle (render index) |

### `landing-graph`

Added with the #344 landing-page knowledge-graph demo. Ships the static,
fully laid-out render (chips to switch course, nodes/edges for the selected
graph), the helical assembly animation, and hover interaction (detail-panel
swap + copy fade on first engagement); click-to-expand is a later task in the
same spec and will reuse these same testids.

Step 3 wrapped the whole thing in the same `landing-surface` chrome the bands
and bento use — a titled bar over a `--bg-mesh` canvas, an inspector rail and a
mastery legend — so the ids below split into the section's own controls and the
screen's panes.

| testid | element |
| --- | --- |
| `landing-graph` | demo section root (`aria-label` names the selected course) |
| `landing-graph-chip-{courseId}` | one course-picker chip, per `COURSE_GRAPHS` entry — `aria-pressed` marks the active course |
| `landing-graph-copy` | the section's instructional copy block (eyebrow label + heading) — `data-engaged` flips `"true"` on the visitor's first node hover and stays that way across course switches |
| `landing-graph-eyebrow` | the "Your knowledge, mapped" eyebrow label — deliberately *not* faded on engagement (WCAG AA at 0.7rem) |
| `landing-graph-headline` | the "Pick a course. Watch it grow." heading — carries the engagement fade (`ENGAGED_HEADLINE_OPACITY`) |
| `landing-graph-surface` | the product-chrome frame the whole screen sits in (`landing-surface`) |
| `landing-graph-meta` | the chrome bar's right-hand status — `{code} · {conceptCount} concepts · {n}% mastery`, all read off the selected `CourseGraph` |
| `landing-graph-svg` | the `<svg>` itself — its `viewBox` is the desktop or the phone `GraphView` (`graph/layout.ts`), swapped at the mobile breakpoint |
| `landing-graph-node-{nodeId}` | one SVG node group (`<g>`) in the selected course's graph. Its **first `<circle>` is the tier-painted disc at the full node radius** — the phone legibility gate measures that element, so nothing may be drawn in front of it |
| `landing-graph-detail` | the inspector rail's frame. Never empty: with nothing hovered it shows the course (the root node) |
| `landing-graph-detail-name` | the inspected node's name |
| `landing-graph-detail-tier` | its mastery tier as a labelled chip (`Course` for the root, which is an anchor rather than a status) |
| `landing-graph-detail-mastery` | its mastery as a percentage |
| `landing-graph-blurb` | the reserved-height paragraph in the panel that shows the inspected node's one-sentence blurb |
| `landing-graph-legend` | the mastery legend pinned to the foot of the rail |
| `landing-graph-legend-{tier}` | one legend row — `mastered`, `learning`, `struggling` or `unexplored`, each with the tier's own count of drawn concepts |

### `landing-band` / `landing-bento` / `landing-surface`

Added with the #344 step-2 build (feature bands + surface bento). These
surfaces are **static recreations** of shipped product screens — there is
deliberately not a single `<button>`, `<input>` or `<textarea>` among them
(the spec's "no per-tile buttons"), so the lint block below is satisfied
vacuously and stays as a guard on anything added later.

| testid | element |
| --- | --- |
| `landing-band-{bandId}` | one feature band's `<section>` — `bandId` is `upload`, `quiz` or `review` (a stable content id, per the repeated-items rule). Carries `data-surface-side="left"\|"right"`, the resolved alternation |
| `landing-band-{bandId}-eyebrow` | that band's mono micro-label |
| `landing-bento` | the four-tile grid's `<section>` root |
| `landing-bento-eyebrow` | the bento's mono micro-label |
| `landing-surface-upload` | Document Library ingest queue (band 1) |
| `landing-surface-quiz` | an Adaptive Quizzes question mid-answer (band 2) |
| `landing-surface-review` | the Study screen's spaced review + rating trio (band 3) |
| `landing-surface-tutor` | a Tutor exchange (bento) |
| `landing-surface-notes` | a Notetaker note with its linked concepts (bento) |
| `landing-surface-rooms` | a Study Rooms conversation (bento) |
| `landing-surface-gradebook` | a Gradebook course header + assignment rows (bento) |

The `landing-surface-*` ids suffix the *surface* rather than a render index
because each one mounts exactly once and the surface name is the stable
domain id here.

### `adminfb`

Added with the #520 admin feedback tab. Reads the two decrypting admin
endpoints (`GET /api/admin/feedback`, `GET /api/admin/issue-reports`) and
renders them read-only — there are no interactive elements (no
button/input/textarea), just the two list cards and their rows.

| testid | element |
| --- | --- |
| `adminfb-feedback-card` | feedback list card root |
| `adminfb-feedback-row` | one feedback entry (repeated, no suffix — read-only list, no per-row action to select) |
| `adminfb-issues-card` | issue-report list card root |
| `adminfb-issue-row` | one issue report (repeated, no suffix) |

## Enforcement

`frontend/eslint.config.mjs` has a per-file `no-restricted-syntax` block scoped
to the owning files listed above. It errors on any `<button>`, `<input>` or
`<textarea>` in those files that has no `data-testid` attribute:

```js
{
  files: [ /* the surface files */ ],
  rules: {
    "no-restricted-syntax": ["error", {
      selector:
        'JSXOpeningElement[name.name=/^(button|input|textarea)$/]' +
        ':not(:has(JSXAttribute[name.name="data-testid"]))',
      message: "E2E surface (#382): …",
    }],
  },
}
```

It is intentionally narrow:

- **Only the listed owning files.** A repo-wide version would be pure noise; the
  rest of the app has no browser coverage to protect.
- **Only intrinsic interactive elements.** Custom components (`<CustomSelect>`,
  `<Button>`) are not matched — a testid on a component is a prop the component
  has to forward, which is a code change, not an attribute. Tag the element
  inside the component instead.
- **Container roots are not enforced**, only added by convention. A selector for
  "the root `<div>` of this component" is not expressible without false
  positives.

There is no lint coverage on `signin-trigger` in `src/app/(public)/page.tsx` —
the landing page has dozens of buttons that are not part of any browser test, so
that file stays out of the `files` list. The trigger is documented here instead.

There is likewise no lint coverage on `adminfb-*` in `Admin.tsx`. `FeedbackTab`
(the tab that owns them) has zero `<button>`/`<input>`/`<textarea>` elements,
so nothing there needs the rule — but `Admin.tsx` as a whole stays out of the
`files` list deliberately: enrolling it would flag 51 pre-existing untagged
elements across the file's other tabs (Users, Roles, Achievements, Cosmetics,
Allowlist, Audit), none of which have browser coverage today. Revisit when an
admin journey lands.

`screens/Dashboard.tsx` joined the `files` list with the `dashboard` surface
(#386) carrying 25 pre-existing untagged intrinsic elements; those are
baselined in `eslint-suppressions.json` (the repo's legacy-debt mechanism —
see the header of `eslint.config.mjs`), so only **new** interactive elements
in the file must carry a testid. Tag baselined elements as they get browser
coverage and regenerate with `npm run lint:baseline`.

`src/components/screens/Learn.tsx` (the session-resume rows, #392) is in the
`files` list with the same treatment: its 21 pre-existing untagged elements are
baselined, so only NEW interactive elements there must carry a testid.

`screens/Tree.tsx` (#330) gets the same treatment: its 8 pre-existing
untagged elements — the search input, the five detail-panel actions
(close / learn / quiz / delete / resume), and the two fullscreen toggles —
are baselined in `eslint-suppressions.json`; only NEW interactive elements
there must carry a testid (the `graph-add-concept*` trio entered tagged).
Note the `graph-zoom-*` controls live in `KnowledgeGraph2D.tsx`, not here.

The `gradebook` surface files (#139/#468) get the same treatment:
`screens/Gradebook/Course.tsx`, `Landing.tsx`, `Gradebook/AssignmentList.tsx`
and `Gradebook/AssignmentModal.tsx` carry pre-existing untagged
buttons/inputs that are baselined in `eslint-suppressions.json`; only NEW
interactive elements there must carry a testid.

`ProfileView.tsx` (`profile` surface) and `screens/Achievements.tsx` +
`screens/achievements/HeroCard.tsx`/`LeaderboardTab.tsx`/`ActivityTab.tsx`
(`achievements` surface, Task 17) joined the `files` list with no baselined
backlog: `ProfileView.tsx`'s buttons already carried testids from Task 16,
and `Achievements.tsx`'s one pre-existing untagged button (showcase
"remove") was tagged (`achievements-showcase-remove-{achievementId}`)
rather than baselined.

### Adding a surface

1. Pick a prefix, add the row to the table above and the testids to the
   inventory.
2. Add the owning file to the `files` array in the lint block.
3. Run `npm run lint` from `frontend/` — it will list every interactive element
   in the new file that still needs a testid.

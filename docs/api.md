# Sapling API reference

Every route is mounted under `/api/<name>` in `backend/main.py`. Unless noted, routes require a signed-in session cookie and act only on the caller's own data. The grouped sections below describe the main routes. The [complete route index](#complete-route-index) at the end lists every route in the OpenAPI schema, and FastAPI serves the same list interactively at `http://localhost:5000/docs` when the backend runs locally. Server-to-server and test-only routes (`/api/internal/*`, `/api/auth/test-login`, `/api/auth/local-seed`) are left out of the schema on purpose.

**Learn**

- `POST` `/api/learn/start-session` — Start a tutoring session
- `POST` `/api/learn/chat` — Send a chat message
- `POST` `/api/learn/action` — Send a structured action (e.g. quiz, recap)
- `POST` `/api/learn/end-session` — End a session
- `GET` `/api/learn/sessions/{user_id}` — List past sessions

**Graph**

- `GET` `/api/graph/{user_id}` — Fetch the user's knowledge graph
- `GET` `/api/graph/{user_id}/recommendations` — Get next-concept recommendations
- `GET` `/api/graph/{user_id}/courses` — List courses

**Quiz**

- `POST` `/api/quiz/generate` — Generate an adaptive quiz
- `POST` `/api/quiz/submit` — Submit answers and update mastery

**Flashcards**

- `POST` `/api/flashcards/generate` — Generate and store flashcards for a topic: body `{user_id, topic, count, session_id?, semester?, course_id?}`. With a `course_id` the cards are grounded in that course's documents, prioritise only that course's weak concepts, and are filed under the selected `semester`'s offering of it (else the student's enrolled offering). Answers `{flashcards: [...], context_used}`; each card carries the `course_id` it was filed under (`null` when none)
- `POST` `/api/flashcards/import/parse` — Parse cards from paste, file, URL, or photo (no save)
- `POST` `/api/flashcards/import/generate` — AI-generate cards from a topic / prompt
- `POST` `/api/flashcards/import/cleanup` — Clean up parsed cards before commit
- `POST` `/api/flashcards/import/cloze` — Convert sentences into cloze-deletion cards
- `POST` `/api/flashcards/import/commit` — Commit parsed cards to the user's deck
- `GET` `/api/flashcards/user/{user_id}` — Fetch a user's flashcards (optional `?topic=`, `?semester=`). Each card has a derived `course_id` and a `due_at` that is always `null` until a review scheduler exists
- `POST` `/api/flashcards/rate` — Rate a card (Easy / Hard / Forgot)
- `DELETE` `/api/flashcards/{card_id}` — Delete a card
- `GET` `/api/flashcards/sets/{user_id}` — List a user's saved sets (optional `?course_id=`)
- `POST` `/api/flashcards/sets` — Save a set (name, course, concept names, options)
- `POST` `/api/flashcards/sets/suggest` — Describe a set in a sentence and get the concepts it should hold (a suggestion; nothing is saved): body `{user_id, description, course_id?}` (description 3 to 300 characters), answers `{name, concepts: [{name, course_id, source, confidence}], considered, backend}` where `source` is `named` (the description says it) or `model`. 422 for the description's length; 429 with `Retry-After` past 10 model-backed requests a minute
- `PATCH` `/api/flashcards/sets/{set_id}` — Change a saved set's name, concepts, options, or exam
- `DELETE` `/api/flashcards/sets/{set_id}` — Delete a saved set (its cards stay)

**Gradebook**

- `GET` `/api/gradebook/summary` — Per-course grade summary across the user's courses (filter by `semester`)
- `GET` `/api/gradebook/courses/{course_id}` — Full gradebook for a course (categories, assignments, current grade)
- `POST` `/api/gradebook/courses/{course_id}/categories` — Create a category
- `PATCH` `/api/gradebook/courses/{course_id}/categories` — Bulk-update categories (weights, names)
- `DELETE` `/api/gradebook/categories/{category_id}` — Delete a category
- `POST` `/api/gradebook/assignments` — Create an assignment
- `PATCH` `/api/gradebook/assignments/{assignment_id}` — Update an assignment (grade, weight, due date)
- `DELETE` `/api/gradebook/assignments/{assignment_id}` — Delete an assignment
- `PATCH` `/api/gradebook/courses/{course_id}/scale` — Override the per-course letter-grade scale
- `POST` `/api/gradebook/syllabus/apply` — Apply a parsed syllabus (replaces categories, dedupes assignments)

**Gradescope**

The backend runs on Railway; the frontend uses the existing Cloudflare
same-origin `/api` proxy. `backend/Dockerfile` installs Chromium and its Linux
dependencies for BU SSO. The browser runs on the backend, never in the frontend
worker. Saved credentials are verified when opening Gradescope setup; expired
sessions prompt reconnection. Course linking, link listing, unlinking, and sync
accept an optional `semester` term label so retakes import into the selected
gradebook. Failed imports do not advance the last-successful-sync timestamp.

- `POST` `/api/gradescope/credentials` — Test a Gradescope login, then save encrypted email/password credentials
- `POST` `/api/gradescope/credentials/bu-sso` — Live BU SSO sign-in via headless Chromium (WebLogin + Duo), storing session cookies
- `DELETE` `/api/gradescope/credentials` — Remove stored credentials
- `GET` `/api/gradescope/status` — Whether credentials are saved and when the user last synced
- `GET` `/api/gradescope/courses` — List the user's Gradescope student courses (live)
- `GET` `/api/gradescope/links` — List Sapling-course → Gradescope-course mappings
- `POST` `/api/gradescope/link` — Create or update a course mapping
- `DELETE` `/api/gradescope/link/{sapling_course_id}` — Remove a course mapping
- `POST` `/api/gradescope/sync/{sapling_course_id}` — Pull assignments from the linked Gradescope course and upsert grades into the gradebook (`202 {pending}` when a queued sync outlasts the wait)
- `GET` `/api/gradescope/sync/{sapling_course_id}/status` — Poll a queued sync: 202 while it runs, then the POST's answer

**Study**

The Study hub's Daily Goal panel. Minutes are an estimate from timestamps the app already records, not a logged timer: each completed quiz attempt (start to finish, capped at 30 minutes, on the day it was completed); half a minute per flashcard reviewed that day (a card counts only on its latest review day); and tutor chat from message times (per session, per day: its first to its last message that day, capped at 60 minutes, so a chat opened last week counts on each day it is used). Each activity is rounded to whole minutes (never 0 when there was any), and a day's `minutes` is the sum of the three. Both routes are hidden with the rest of Study by the `hide_study` flag.

- `GET` `/api/study/{user_id}/daily` — Estimated study minutes for the last seven local days, oldest first, plus the goal: `{goal_minutes, today, days: [{date, minutes, quiz, flashcards, tutor, quizzes, cards, sessions}]}`. Optional `?tz_offset_min=` is the browser's `Date#getTimezoneOffset()` (minutes behind UTC, default `0`; clamped to real-world offsets)
- `PATCH` `/api/study/{user_id}/daily-goal` — Set the daily goal: body `{minutes}` (5 to 600), answers `{goal_minutes}`

**Study Guide**

- `GET` `/api/study-guide/{user_id}/guide` — Get (or generate) a study guide for an exam
- `GET` `/api/study-guide/{user_id}/cached` — List all cached study guides
- `GET` `/api/study-guide/{user_id}/courses` — List courses for guide generation
- `GET` `/api/study-guide/{user_id}/exams` — List exam-type assignments
- `POST` `/api/study-guide/regenerate` — Invalidate cache and regenerate a guide

**Calendar**

- `POST` `/api/calendar/extract` — Extract assignments from a syllabus
- `GET` `/api/calendar/upcoming/{user_id}` — Fetch upcoming assignments
- `POST` `/api/calendar/save` — Save extracted assignments

**Documents**

- `POST` `/api/documents/upload` — **Streaming SSE upload.** Runs the agentic pipeline (classifier → parallel summary/concepts/syllabus → graph merge) and emits typed SSE events the client renders as live progress: `status:start`, `progress:classify`, `progress:classified`, `progress:extract`, `progress:extracted`, `progress:graph_update`, `progress:graph_updated`, `result:finalize`, `status:done`. Errors emit `error:failed` (terminal). Idempotent on `X-Request-ID` — a retry with the same ID returns the previously persisted document without re-running the pipeline.
- `POST` `/api/documents/upload/sync` — Non-streaming JSON upload. Same orchestrator under the hood, returns the persisted document as a single JSON response. Used by callers that don't need progress events.
- `GET` `/api/documents/user/{user_id}` — List a user's documents
- `DELETE` `/api/documents/doc/{doc_id}` — Delete a document
- `POST` `/api/documents/doc/{doc_id}/scan-concepts` — Re-extract concepts from a stored document into the course graph
- `POST` `/api/documents/course/{course_id}/scan-concepts` — Extend a course's concept graph from its label alone

**Notes**

- `GET` `/api/notes/user/{user_id}` — List a user's notes (filter by `course_id`)
- `POST` `/api/notes` — Create a note
- `GET` `/api/notes/{note_id}` — Fetch a single note
- `PATCH` `/api/notes/{note_id}` — Update a note (title, body, tags, course)
- `DELETE` `/api/notes/{note_id}` — Delete a note
- `GET` `/api/notes/{note_id}/concepts` — List concepts linked to a note
- `POST` `/api/notes/{note_id}/concepts` — Link a graph concept to a note
- `DELETE` `/api/notes/{note_id}/concepts/{concept_node_id}` — Unlink a concept
- `POST` `/api/notes/{note_id}/summarize` — AI-summarize the note (agent-backed)
- `POST` `/api/notes/{note_id}/extract-concepts` — Extract concepts, merge into the graph, link back to the note
- `POST` `/api/notes/{note_id}/chat` — Ask a question grounded in the note (agent-backed)
- `POST` `/api/notes/{note_id}/send-to-tutor` — Build a tutor handoff (topic + preface) from the note
- `POST` `/api/notes/{note_id}/generate-quiz` — Pick the note's weakest linked concept to quiz on

**Social**

- `POST` `/api/social/rooms/create` — Create a study room
- `POST` `/api/social/rooms/join` — Join a study room by invite code
- `GET` `/api/social/rooms/{user_id}` — List a user's rooms
- `GET` `/api/social/rooms/{room_id}/overview` — Room overview with AI-generated group summary
- `GET` `/api/social/rooms/{room_id}/activity` — Recent activity feed for a room
- `POST` `/api/social/rooms/{room_id}/match` — Find study partners within a room
- `POST` `/api/social/rooms/{room_id}/leave` — Leave a room
- `DELETE` `/api/social/rooms/{room_id}/members/{member_id}` — Kick a member (room leader only)
- `GET` `/api/social/rooms/{room_id}/messages` — Fetch room chat messages
- `POST` `/api/social/rooms/{room_id}/messages` — Send a chat message
- `POST` `/api/social/school-match` — Find study partners school-wide
- `GET` `/api/social/students` — List all students with mastery stats

**Auth**

- `GET` `/api/auth/google` — Redirect to Google OAuth consent screen
- `GET` `/api/auth/google/callback` — OAuth callback, issues session token
- `GET` `/api/auth/me` — Get current user from session token

**Onboarding**

- `GET` `/api/onboarding/courses` — Search courses by name or code
- `POST` `/api/onboarding/profile` — Save onboarding profile data

**Profile**

- `GET` `/api/profile/{user_id}` — Public profile with roles, achievements, cosmetics
- `PUT` `/api/profile/{user_id}` — Update profile fields (bio, major, links, etc.)
- `PUT` `/api/profile/{user_id}/settings` — Update user settings
- `POST` `/api/profile/{user_id}/avatar` — Upload a profile avatar
- `POST` `/api/profile/{user_id}/equip` — Equip or unequip a cosmetic item
- `PUT` `/api/profile/{user_id}/featured-role` — Set featured role on profile
- `PUT` `/api/profile/{user_id}/featured-achievements` — Set featured achievements
- `DELETE` `/api/profile/{user_id}` — Delete account

**Admin**

- `GET`/`POST` `/api/admin/roles` — List / create roles
- `PATCH`/`DELETE` `/api/admin/roles/{role_id}` — Update / delete a role
- `POST`/`DELETE` `/api/admin/roles/assign` · `/api/admin/roles/revoke` — Assign / revoke a role
- `GET`/`POST`/`DELETE` `/api/admin/roles/cosmetics` (+ `/api/admin/roles/{role_id}/cosmetics`) — Link cosmetics to roles
- `GET`/`POST` `/api/admin/achievements` — List / create achievements
- `PATCH`/`DELETE` `/api/admin/achievements/{achievement_id}` — Update / delete an achievement
- `POST` `/api/admin/achievements/grant` — Manually grant an achievement
- `GET`/`POST`/`PATCH`/`DELETE` achievement triggers (`/api/admin/achievements/{achievement_id}/triggers`, `/api/admin/achievements/triggers`, `/api/admin/achievements/triggers/{trigger_id}`)
- `GET`/`POST`/`DELETE` `/api/admin/achievements/cosmetics` (+ `/api/admin/achievements/{achievement_id}/cosmetics`) — Link cosmetics to achievements
- `GET`/`POST` `/api/admin/cosmetics` — List / create cosmetic items
- `PATCH`/`DELETE` `/api/admin/cosmetics/{cosmetic_id}` — Update / delete a cosmetic
- `GET` `/api/admin/users` — Paginated, searchable user list
- `PATCH` `/api/admin/users/{user_id}/approve` · `/unapprove` — Approve / unapprove a user
- `POST` `/api/admin/allowlist/approve` · `/api/admin/allowlist/revoke` — Manage the email allowlist
- `GET` `/api/admin/audit` — Paginated admin audit log (filter by action / target)
- `GET` `/api/admin/analytics/overview` — Totals, 30-day series, and role counts
- `GET` `/api/admin/jobs` — Job-queue overview per type and status (`jobs_overview()`)
- `GET`/`PUT` `/api/admin/llm/budgets` (+ `DELETE /api/admin/llm/budgets/{scope}/{subject}`, `GET /api/admin/llm/budgets/status/{user_id}`) — Per-user daily LLM token budgets
- `GET` `/api/admin/llm/drill` — State of the `llm_outage_drill` flag

**Feedback**

- `POST` `/api/feedback` — Submit session or general feedback
- `POST` `/api/issue-reports` — Submit a bug/issue report (+ `POST /api/issue-reports/screenshot`)

**Newsletter**

- `POST` `/api/newsletter/subscribe` — Add an email to the beta / newsletter list

## Complete route index

Generated from the app's OpenAPI schema (`app.openapi()` in `backend/main.py`) on 2026-11-09 (236 operations then; 243 in the schema as of 2026-11-12); the five `/api/flashcards/sets` routes (`suggest` included) were added by hand on 2026-11-12; so were the two `/api/study` routes. Regenerate it from the running backend's `/openapi.json` when routers change.

<details><summary><code>/api/admin</code> (71)</summary>

- `GET /api/admin/accounts/meta`
- `POST /api/admin/accounts/{user_id}/copy`
- `GET /api/admin/accounts/{user_id}/copy-preview`
- `POST /api/admin/accounts/{user_id}/seed`
- `GET /api/admin/accounts/{user_id}/summary`
- `POST /api/admin/accounts/{user_id}/wipe`
- `GET /api/admin/achievements`
- `POST /api/admin/achievements`
- `POST /api/admin/achievements/cosmetics`
- `DELETE /api/admin/achievements/cosmetics`
- `POST /api/admin/achievements/grant`
- `POST /api/admin/achievements/triggers`
- `PATCH /api/admin/achievements/triggers/{trigger_id}`
- `DELETE /api/admin/achievements/triggers/{trigger_id}`
- `PATCH /api/admin/achievements/{achievement_id}`
- `DELETE /api/admin/achievements/{achievement_id}`
- `GET /api/admin/achievements/{achievement_id}/cosmetics`
- `POST /api/admin/achievements/{achievement_id}/icon`
- `GET /api/admin/achievements/{achievement_id}/triggers`
- `GET /api/admin/allowlist`
- `POST /api/admin/allowlist/approve`
- `POST /api/admin/allowlist/approve-bulk`
- `POST /api/admin/allowlist/revoke`
- `GET /api/admin/analytics/db-scope`
- `GET /api/admin/analytics/errors`
- `GET /api/admin/analytics/llm/cost`
- `GET /api/admin/analytics/llm/cost-per-active-user`
- `GET /api/admin/analytics/overview`
- `GET /api/admin/analytics/usage/by-user`
- `GET /api/admin/analytics/usage/summary`
- `GET /api/admin/audit`
- `GET /api/admin/cosmetics`
- `POST /api/admin/cosmetics`
- `PATCH /api/admin/cosmetics/{cosmetic_id}`
- `DELETE /api/admin/cosmetics/{cosmetic_id}`
- `GET /api/admin/documents/unindexed`
- `POST /api/admin/documents/{document_id}/reindex`
- `GET /api/admin/email/audiences`
- `GET /api/admin/email/broadcasts`
- `POST /api/admin/email/broadcasts`
- `POST /api/admin/email/broadcasts/preview`
- `POST /api/admin/email/broadcasts/test`
- `POST /api/admin/email/broadcasts/{broadcast_id}/resume`
- `GET /api/admin/email/status`
- `POST /api/admin/email/suppressions/remove`
- `GET /api/admin/feedback`
- `GET /api/admin/flags`
- `PATCH /api/admin/flags/{key}`
- `GET /api/admin/flags/{key}/explain`
- `PUT /api/admin/flags/{key}/targets`
- `DELETE /api/admin/flags/{key}/targets/{target_type}/{target_id}`
- `GET /api/admin/issue-reports`
- `GET /api/admin/jobs`
- `GET /api/admin/llm/budgets`
- `PUT /api/admin/llm/budgets`
- `GET /api/admin/llm/budgets/status/{user_id}`
- `DELETE /api/admin/llm/budgets/{scope}/{subject}`
- `GET /api/admin/llm/drill`
- `GET /api/admin/roles`
- `POST /api/admin/roles`
- `POST /api/admin/roles/assign`
- `POST /api/admin/roles/cosmetics`
- `DELETE /api/admin/roles/cosmetics`
- `DELETE /api/admin/roles/revoke`
- `PATCH /api/admin/roles/{role_id}`
- `DELETE /api/admin/roles/{role_id}`
- `GET /api/admin/roles/{role_id}/cosmetics`
- `GET /api/admin/users`
- `PATCH /api/admin/users/{user_id}/unapprove`
- `GET /api/admin/xp-rules`
- `PATCH /api/admin/xp-rules/{key}`

</details>

<details><summary><code>/api/auth</code> (6)</summary>

- `GET /api/auth/google`
- `GET /api/auth/google/callback`
- `GET /api/auth/me`
- `POST /api/auth/pending/join`
- `POST /api/auth/pending/status`
- `GET /api/auth/realtime-token`

</details>

<details><summary><code>/api/calendar</code> (14)</summary>

- `GET /api/calendar/all/{user_id}`
- `PATCH /api/calendar/assignments/{assignment_id}`
- `DELETE /api/calendar/assignments/{assignment_id}`
- `GET /api/calendar/auth-url`
- `GET /api/calendar/callback`
- `DELETE /api/calendar/disconnect/{user_id}`
- `POST /api/calendar/export`
- `POST /api/calendar/extract`
- `GET /api/calendar/import/{user_id}`
- `POST /api/calendar/save`
- `GET /api/calendar/status/{user_id}`
- `POST /api/calendar/suggest-study-blocks`
- `POST /api/calendar/sync`
- `GET /api/calendar/upcoming/{user_id}`

</details>

<details><summary><code>/api/careers</code> (1)</summary>

- `POST /api/careers/apply`

</details>

<details><summary><code>/api/documents</code> (7)</summary>

- `POST /api/documents/course/{course_id}/scan-concepts`
- `DELETE /api/documents/doc/{document_id}`
- `PATCH /api/documents/doc/{document_id}`
- `POST /api/documents/doc/{document_id}/scan-concepts`
- `POST /api/documents/upload`
- `POST /api/documents/upload/sync`
- `GET /api/documents/user/{user_id}`

</details>

<details><summary><code>/api/email</code> (2)</summary>

- `GET /api/email/unsubscribe`
- `POST /api/email/unsubscribe`

</details>

<details><summary><code>/api/extract</code> (3)</summary>

- `GET /api/extract/health`
- `POST /api/extract/image`
- `POST /api/extract/pdf`

</details>

<details><summary><code>/api/feedback</code> (1)</summary>

- `POST /api/feedback`

</details>

<details><summary><code>/api/flags</code> (1)</summary>

- `GET /api/flags`

</details>

<details><summary><code>/api/flashcards</code> (14)</summary>

- `POST /api/flashcards/generate`
- `POST /api/flashcards/import/cleanup`
- `POST /api/flashcards/import/cloze`
- `POST /api/flashcards/import/commit`
- `POST /api/flashcards/import/generate`
- `POST /api/flashcards/import/parse`
- `POST /api/flashcards/rate`
- `POST /api/flashcards/sets`
- `POST /api/flashcards/sets/suggest`
- `DELETE /api/flashcards/sets/{set_id}`
- `PATCH /api/flashcards/sets/{set_id}`
- `GET /api/flashcards/sets/{user_id}`
- `GET /api/flashcards/user/{user_id}`
- `DELETE /api/flashcards/{card_id}`

</details>

<details><summary><code>/api/gamification</code> (3)</summary>

- `GET /api/gamification/activity`
- `GET /api/gamification/leaderboard`
- `GET /api/gamification/me`

</details>

<details><summary><code>/api/gemini-test</code> (1)</summary>

- `GET /api/gemini-test`

</details>

<details><summary><code>/api/gradebook</code> (12)</summary>

- `POST /api/gradebook/assignments`
- `PATCH /api/gradebook/assignments/{assignment_id}`
- `DELETE /api/gradebook/assignments/{assignment_id}`
- `DELETE /api/gradebook/categories/{category_id}`
- `GET /api/gradebook/courses/{course_id}`
- `POST /api/gradebook/courses/{course_id}/categories`
- `PATCH /api/gradebook/courses/{course_id}/categories`
- `PATCH /api/gradebook/courses/{course_id}/curve`
- `PATCH /api/gradebook/courses/{course_id}/scale`
- `GET /api/gradebook/gpa`
- `GET /api/gradebook/summary`
- `POST /api/gradebook/syllabus/apply`

</details>

<details><summary><code>/api/gradescope</code> (10)</summary>

- `GET /api/gradescope/courses`
- `POST /api/gradescope/credentials`
- `DELETE /api/gradescope/credentials`
- `POST /api/gradescope/credentials/bu-sso`
- `POST /api/gradescope/link`
- `DELETE /api/gradescope/link/{sapling_course_id}`
- `GET /api/gradescope/links`
- `GET /api/gradescope/status`
- `POST /api/gradescope/sync/{sapling_course_id}`
- `GET /api/gradescope/sync/{sapling_course_id}/status`

</details>

<details><summary><code>/api/graph</code> (10)</summary>

- `GET /api/graph/{user_id}`
- `POST /api/graph/{user_id}/concept-description`
- `GET /api/graph/{user_id}/courses`
- `POST /api/graph/{user_id}/courses`
- `DELETE /api/graph/{user_id}/courses/{course_id}`
- `PATCH /api/graph/{user_id}/courses/{course_id}/color`
- `POST /api/graph/{user_id}/nodes`
- `DELETE /api/graph/{user_id}/nodes/{node_id}`
- `PATCH /api/graph/{user_id}/nodes/{node_id}/color`
- `GET /api/graph/{user_id}/recommendations`

</details>

<details><summary><code>/api/health</code> (1)</summary>

- `GET /api/health`

</details>

<details><summary><code>/api/issue-reports</code> (2)</summary>

- `POST /api/issue-reports`
- `POST /api/issue-reports/screenshot`

</details>

<details><summary><code>/api/learn</code> (11)</summary>

- `POST /api/learn/action`
- `POST /api/learn/chat`
- `POST /api/learn/chat/stream`
- `POST /api/learn/end-session`
- `POST /api/learn/mode-switch`
- `PATCH /api/learn/sessions/{session_id}`
- `DELETE /api/learn/sessions/{session_id}`
- `GET /api/learn/sessions/{session_id}/resume`
- `GET /api/learn/sessions/{user_id}`
- `POST /api/learn/start-session`
- `POST /api/learn/start-session/stream`

</details>

<details><summary><code>/api/newsletter</code> (1)</summary>

- `POST /api/newsletter/subscribe`

</details>

<details><summary><code>/api/notes</code> (13)</summary>

- `POST /api/notes`
- `GET /api/notes/user/{user_id}`
- `GET /api/notes/{note_id}`
- `PATCH /api/notes/{note_id}`
- `DELETE /api/notes/{note_id}`
- `POST /api/notes/{note_id}/chat`
- `GET /api/notes/{note_id}/concepts`
- `POST /api/notes/{note_id}/concepts`
- `DELETE /api/notes/{note_id}/concepts/{concept_node_id}`
- `POST /api/notes/{note_id}/extract-concepts`
- `POST /api/notes/{note_id}/generate-quiz`
- `POST /api/notes/{note_id}/send-to-tutor`
- `POST /api/notes/{note_id}/summarize`

</details>

<details><summary><code>/api/onboarding</code> (2)</summary>

- `GET /api/onboarding/courses`
- `POST /api/onboarding/profile`

</details>

<details><summary><code>/api/profile</code> (15)</summary>

- `GET /api/profile/username/check`
- `GET /api/profile/{user_id}`
- `PATCH /api/profile/{user_id}`
- `DELETE /api/profile/{user_id}/account`
- `GET /api/profile/{user_id}/achievements`
- `POST /api/profile/{user_id}/avatar`
- `GET /api/profile/{user_id}/cosmetics`
- `GET /api/profile/{user_id}/cosmetics/catalog`
- `POST /api/profile/{user_id}/equip`
- `POST /api/profile/{user_id}/export`
- `POST /api/profile/{user_id}/featured-achievements`
- `POST /api/profile/{user_id}/featured-role`
- `GET /api/profile/{user_id}/roles`
- `GET /api/profile/{user_id}/settings`
- `PATCH /api/profile/{user_id}/settings`

</details>

<details><summary><code>/api/quiz</code> (7)</summary>

- `GET /api/quiz/attempts`
- `GET /api/quiz/attempts/{attempt_id}`
- `POST /api/quiz/attempts/{attempt_id}/abandon`
- `POST /api/quiz/attempts/{attempt_id}/answer`
- `GET /api/quiz/config`
- `POST /api/quiz/generate`
- `POST /api/quiz/submit`

</details>

<details><summary><code>/api/semesters</code> (1)</summary>

- `GET /api/semesters`

</details>

<details><summary><code>/api/social</code> (24)</summary>

- `POST /api/social/friends/request`
- `GET /api/social/friends/requests`
- `DELETE /api/social/friends/requests/{request_id}`
- `POST /api/social/friends/requests/{request_id}/accept`
- `POST /api/social/friends/requests/{request_id}/decline`
- `DELETE /api/social/friends/{friend_id}`
- `GET /api/social/friends/{user_id}`
- `GET /api/social/public-rooms`
- `POST /api/social/public-rooms/{room_id}/join`
- `POST /api/social/rooms/create`
- `POST /api/social/rooms/join`
- `GET /api/social/rooms/{room_id}/activity`
- `POST /api/social/rooms/{room_id}/leave`
- `POST /api/social/rooms/{room_id}/match`
- `DELETE /api/social/rooms/{room_id}/members/{member_id}`
- `GET /api/social/rooms/{room_id}/messages`
- `POST /api/social/rooms/{room_id}/messages`
- `DELETE /api/social/rooms/{room_id}/messages/{message_id}`
- `PATCH /api/social/rooms/{room_id}/messages/{message_id}`
- `POST /api/social/rooms/{room_id}/messages/{message_id}/reactions`
- `GET /api/social/rooms/{room_id}/overview`
- `GET /api/social/rooms/{user_id}`
- `POST /api/social/school-match`
- `GET /api/social/students`

</details>

<details><summary><code>/api/study</code> (2)</summary>

- `GET /api/study/{user_id}/daily`
- `PATCH /api/study/{user_id}/daily-goal`

</details>

<details><summary><code>/api/study-guide</code> (5)</summary>

- `POST /api/study-guide/regenerate`
- `GET /api/study-guide/{user_id}/cached`
- `GET /api/study-guide/{user_id}/courses`
- `GET /api/study-guide/{user_id}/exams`
- `GET /api/study-guide/{user_id}/guide`

</details>

<details><summary><code>/api/topic-checklist</code> (3)</summary>

- `GET /api/topic-checklist/{user_id}/courses/{course_id}`
- `POST /api/topic-checklist/{user_id}/courses/{course_id}/refresh`
- `PATCH /api/topic-checklist/{user_id}/courses/{course_id}/topics/{topic_id}`

</details>

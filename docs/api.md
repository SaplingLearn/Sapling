# Sapling API reference

Every route is mounted under `/api/<name>` in `backend/main.py`. Unless noted, routes require a signed-in session cookie and act only on the caller's own data. FastAPI also serves interactive docs at `http://localhost:5000/docs` when the backend runs locally.

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

- `POST` `/api/flashcards/generate` — Generate flashcards for a topic
- `POST` `/api/flashcards/import/parse` — Parse cards from paste, file, URL, or photo (no save)
- `POST` `/api/flashcards/import/generate` — AI-generate cards from a topic / prompt
- `POST` `/api/flashcards/import/cleanup` — Clean up parsed cards before commit
- `POST` `/api/flashcards/import/cloze` — Convert sentences into cloze-deletion cards
- `POST` `/api/flashcards/import/commit` — Commit parsed cards to the user's deck
- `GET` `/api/flashcards/user/{user_id}` — Fetch a user's flashcards
- `POST` `/api/flashcards/rate` — Rate a card (Easy / Hard / Forgot)
- `DELETE` `/api/flashcards/{card_id}` — Delete a card

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

- `POST` `/api/feedback/feedback` — Submit session or general feedback
- `POST` `/api/feedback/issue-reports` — Submit a bug/issue report

**Newsletter**

- `POST` `/api/newsletter/subscribe` — Add an email to the beta / newsletter list

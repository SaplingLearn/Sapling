# Personal data inventory

**As of:** 2026-11-14, branch `sec/privacy-ops` (base `02772601`).
**Scope:** every database table, storage bucket and outside service that holds or receives personal
data about a Sapling user. Users are students, and some of them are minors. Catalog tables (schools,
terms, courses, offerings, achievements, cosmetics, roles, XP rules, growth stages) hold no personal
data and are left out, except where a row points at a user.

**How this was built.**

1. The schema was rebuilt by replaying `backend/db/migrations/*.sql` in runner order (the 48 `NNNN_`
   files first, then the timestamped files), applying every later `ALTER … ADD/DROP/RENAME COLUMN`,
   `DROP TABLE` and `RENAME TO`. Many baseline tables were dropped and recreated in
   `0021_gradebook.sql`, `0023_graph_integrity.sql`, `0025_study_integrity.sql` and `0026_ops.sql`.
   Columns below are the final shape after the replay.
2. Encryption status comes from the encrypted-column list in `CLAUDE.md` (Gotchas), the `ENCRYPTED` map
   in `backend/services/account_bundle.py`, and the `encrypt*` call sites in `backend/services` and
   `backend/routes`.
3. Readers, retention and outside recipients were traced through the code paths cited in each row.
   No live database was queried. The E2E stack was not run.

**Not on this branch.** `CLAUDE.md` in the main checkout describes learning-loop tables (check items,
evidence voids, misconceptions, help ledger, item reports, key audits, checklist budgets). None of
them exists in this branch's migrations or code (`backend/learning/` is absent). They are therefore
not inventoried here. Re-run this inventory when that work merges.

Related: `docs/audits/student-data-inventory.md` (2026-08-12) lists student signals for quiz
personalisation. It is not a privacy inventory.

## Legend

| Column | Meaning |
|---|---|
| **Encrypted** | **Yes**: AES-256-GCM in the application, with a fresh nonce per value (`services/encryption.py`). The database and its backups hold only ciphertext. **No**: plaintext in Postgres. Supabase encrypts storage at rest at the disk level, which this table does not count. **Partial**: only the listed columns. |
| **Readers** | **Owner**: the student, through the API named. **Peers**: other signed-in users. **Admin**: `/api/admin/*` (behind `require_admin`). **Service**: only backend code running as `service_role`. |
| **Retention** | What deletes the data today. **Wipe** means `services/account_wipe.py::wipe_account_data`, the admin-only tool at `POST /api/admin/accounts/{id}/wipe`. **Kept on wipe** means the wipe leaves the row in place. |
| **Third parties** | **ANT** Anthropic (Claude), **GEM** Google Gemini (embeddings), **PH** PostHog, **LF** Logfire, **RS** Resend, **GCal** Google Calendar, **GS** Gradescope, **JEV** TypeSafe/Jev. Supabase, Railway and Cloudflare carry or host everything (see Third parties) and are not repeated per row. |
| **Verified** | `M:` checked against the migration named. `C:` checked in the code named. `unverified`: inferred and not traced end to end. |

## Facts that apply to every table

| Fact | Verified |
|---|---|
| The backend reaches PostgREST as `service_role`, which bypasses row-level security. RLS is on for every table, and 137 per-user policies exist for the `authenticated` role. Those policies only take effect for requests that carry a backend-minted user JWT, which needs the `db_user_scope` flag. Whether that flag is on in each environment is not visible in the repo. Until then, access control is the API's checks (`require_self` / `require_admin`). | M: `20261108094129_rls_policies.sql` (header); C: `db/connection.py` |
| `users.id` is `user_<Google account id>`. Every table that stores `user_id` therefore stores the student's Google account ID in plaintext, as do PostHog's distinct id and the Logfire request spans. | C: `services/auth/signin.py:124` |
| **Self-delete** (`DELETE /api/profile/{id}/account`, confirmation word `DELETE`) is a soft delete under the current policy. It sets `users.deleted_at`, refuses future sign-ins, and schedules a PostHog person + event delete. It does not erase any table below. | C: `routes/profile.py:449-484`, `services/auth/signin.py:93` |
| **Admin wipe** deletes study data and resets the gamification counters. It keeps `users`, `user_profiles`, `user_settings`, `user_roles`, `oauth_tokens`, `gradescope_credentials`, `user_cosmetics`, everything social, `feedback`, `issue_reports`, `events`, `llm_usage` and `admin_audit_log`. | C: `services/account_wipe.py` (docstring + `_USER_TABLES`) |
| **Self-export** (`POST /api/profile/{id}/export`, `require_self`) streams one decrypted JSON document: the profile, settings, roles, achievements and cosmetics, plus every table the admin bundle moves (graph + mastery, documents with extracted text/summary/concept notes, enrollments, gradebook/calendar assignments, topic checklists, notes, flashcards, tutor sessions + messages, study guides, quiz attempts/responses/context, XP), the student's OWN room messages and memberships, Gradescope course links, feedback and issue reports. It never reads `oauth_tokens` or `gradescope_credentials`, drops secret-named columns, and leaves out shared chunks, room summaries, friendships and telemetry (listed in its `not_included` key). A soft-deleted account cannot export at all. | C: `services/profile/full_export.py`, `routes/profile.py` (`export_data`); tests `tests/test_self_export.py` |
| **Admin copy** (`/api/admin/accounts/{id}/copy`, `/api/internal/account-sync`) moves a decrypted account bundle between the staging and prod environments. | C: `services/account_bundle.py` docstring |
| No table has a date of birth, age or guardian column. Nothing in the code marks an account as belonging to a minor. | C: grep for `birth`/`dob`/`coppa`/`parental` found nothing relevant |

---

## 1. Identity and account

| Table | Personal columns | Purpose | Encrypted | Readers | Retention | Third parties | Verified |
|---|---|---|---|---|---|---|---|
| `users` | `id` (Google id), `email`, `google_id`, `auth_provider`, `is_approved`, `deleted_at`, `last_sign_in_at`, `last_active_date`, `streak_count`, `longest_streak`, `total_xp`, `level`, `daily_goal_xp`, `welcomed_at`, `created_at` | Account identity, approval and activity | Partial: only `email` (set at sign-in). `google_id` and the activity columns are plaintext. | Owner (`/api/auth/me`, profile); Admin (`/api/admin/users` decrypts the email); Peers see stats on a public profile | Never deleted by app code. Soft delete only. The wipe resets the counters. | PH (`id` as distinct_id); LF (id in paths) | M: `0001`, `0005`, `0010`, `0024`, `20260731193214`, `20261022063145`; C: `services/auth/signin.py:111,142` |
| `user_profiles` | `name`, `first_name`, `last_name`, `username`, `avatar_url`, `bio`, `location`, `website`, `year`, `majors`, `minors`, `learning_style` | Profile | Partial: `name`, `first_name`, `last_name`, `bio`, `location`. `username`, `avatar_url` (the Google photo URL or a public-bucket URL), `website`, `year`, `majors`, `minors` and `learning_style` are plaintext. | Owner; Peers and **anonymous callers** via `GET /api/profile/{id}`. With the default `profile_visibility='public'`, that returns name, year, majors, minors, school, bio, location, website and stats. `school` limits this to same-school viewers. `private` returns a stub. | Kept on wipe and on self-delete | ANT (display name in the quiz-context prompt; room members' names in the room-summary prompt) | M: `0024_identity_split.sql`; C: `services/profile/public.py:17-80`, `services/quiz/submission.py:451`, `services/social/overview.py:49-61` |
| `user_settings` | `profile_visibility` (default `public`), `activity_status_visible` (default true), `share_class_context` (default **true**), `analytics_opt_out` (default **false**), `notification_*`, `daily_goal_minutes`, theme and cosmetic ids | Privacy, consent and preferences | No | Owner (`/api/profile/{id}/settings`); Service (consent checks) | Kept on wipe (`featured_achievement_ids` is emptied). Not carried by the admin copy. | none | M: `0001`, `0031`, `0037`, `20261016064813`; C: `services/account_wipe.py` |
| `oauth_tokens` | `access_token`, `refresh_token`, `expires_at` | Google sign-in and Calendar access | Yes (both tokens) | Service only | Deleted by `DELETE /api/calendar/disconnect/{id}`. Otherwise kept, including on wipe and self-delete. | Used against Google APIs | M: `0001`, `0034`; C: `services/auth/signin.py:158-167`, `routes/calendar.py:441-445` |
| `gradescope_credentials` | `email_encrypted`, `password_encrypted`, `cookies_encrypted`, `auth_mode`, `last_sync_error`, `needs_reauth` | Logging in to Gradescope for the student | Yes (email, password, cookies) | Service only | Deleted by the Gradescope disconnect route. Kept on wipe. | GS (sent to gradescope.com to log in) | M: `0027_gradescope.sql`, `20261106055333`; C: `services/gradescope/credentials.py:159-180`, `routes/gradescope.py:314` |
| `user_roles` | `user_id`, `role_id`, `granted_by` | Staff and earned roles | No | Owner; Peers (signed-in) see roles; Admin | Kept on wipe | none | M: `0001`; C: `services/profile/public.py:25` |
| `feature_flag_targets` | `target_id` (a user id when `target_type` is a user), `created_by` | Per-user flag overrides | No | Admin (`/api/admin/flags`) | Until an admin removes it | none | M: `20260928022711` |
| `llm_budgets` | `subject` (a `users.id` when `scope='user'`), `note`, `updated_by` | Daily token caps | No | Admin (`/api/admin/llm`) | Until an admin removes it | none | M: `20261108213311` (lines 7-10) |
| `rate_limit_hits` | `key` (embeds the user id, e.g. `ocr:{user_id}`), `hit_at` | Shared rate limiting | No | Service only | Rows older than 1 day are pruned by the claim function | none | M: `20261108220438` (lines 105-135); C: `routes/extract.py:32` |

## 2. Documents and RAG

| Table | Personal columns | Purpose | Encrypted | Readers | Retention | Third parties | Verified |
|---|---|---|---|---|---|---|---|
| `documents` | `file_name`, `summary`, `concept_notes`, `extracted_text` (full OCR text of the upload), `flashcards` (jsonb), `category`, `shareability`, `index_error` | Uploaded course material and student work | Partial: `summary`, `concept_notes`, `extracted_text`. `file_name`, `flashcards` and `category` are plaintext. | Owner (`/api/documents/*`); Admin (`/api/admin/documents/unindexed`: ids and status) | Student delete is a **soft delete** (`deleted_at`) that also withdraws the document's chunks. The row and its text stay. The wipe hard-deletes. | ANT (full text to the classifier, summary, concepts, syllabus, concept-scan, flashcard and study-guide agents; page images to `ocr_vision` if `GEMINI_VISION_OCR_ENABLED`); GEM (text sample for `course_relevance`) | M: `0025`, `0030`, `20260920080526`, `20260921063714`; C: `services/documents/library.py:60-76`, `services/rag_service.py:153` |
| `document_uploads` | `file_data` (the raw file), `file_name`, `result`, `error_code` | Queued upload pipeline | Partial: `file_data` (`encrypt_bytes`) and `result`. `file_name` is plaintext. | Owner (upload progress); Service | `file_data` is cleared at a terminal stage (per CLAUDE.md, unverified). Terminal rows are pruned after 2 days by `prune_document_uploads`, which `jobs.prune` calls. Wiped. | as `documents` | M: `20261108212226`; C: `services/document_jobs.py:271,933`, `services/jobs.py:313-320` |
| `course_chunks` | `chunk_text`, `embedding`, `uploader_id`, `doc_id`, `visibility` | RAG chunk store, shared across a course | Yes (`chunk_text`). `embedding` (768-d vector of the plaintext) is not encrypted. | Owner (own private rows). **Peers**: rows with `visibility='shared'` are retrieved into classmates' tutor and quiz prompts. A row is shared only for `course_material` above the confidence floor, when the uploader's `share_class_context` is true. | Withdrawn on document delete and when consent changes. Private orphans are deleted on wipe. Shared rows that another live document also produces stay. | GEM (chunk text embedded at index time); ANT (retrieved chunks go into prompts, the classmates' included) | M: `0039`, `20260920072705`; C: `services/chunk_visibility.py`, `services/tutor/run.py:343` |
| `course_chunk_contributors`, `course_chunk_sources` | `user_id` / `doc_id` per chunk | Joint ownership, so a student can withdraw their chunks | No | Owner; Service | Removed by withdrawal and the wipe | none | M: `20260920072705`, `20261106055333` |
| Redis OCR cache (optional, off unless `REDIS_URL` is set) | Extracted text keyed by `sha256(file bytes)` | Avoid re-running OCR | **No**: plaintext in Redis | Service | 30-day TTL | Redis host (provider not in the repo) | C: `services/extraction_service.py:390,427-439` |

## 3. Notes

| Table | Personal columns | Purpose | Encrypted | Readers | Retention | Third parties | Verified |
|---|---|---|---|---|---|---|---|
| `notes` | `title`, `body`, `last_summary`, `tags` | Student notetaker | Partial: `title`, `body`, `last_summary`. `tags` is plaintext. | Owner (`/api/notes`) | Student delete is a soft delete (`deleted_at`). The wipe hard-deletes. | ANT (`note_summary`, `note_concepts`, `note_chat` receive the note body) | M: `0025`; C: `services/notes_service.py:85-140`, `routes/notes.py:279` |
| `note_concepts` | `note_id` ↔ `concept_node_id` | Links a note to a graph concept | No | Owner | Cascades from notes and graph nodes | none | M: `0025` |

## 4. Tutor chat

| Table | Personal columns | Purpose | Encrypted | Readers | Retention | Third parties | Verified |
|---|---|---|---|---|---|---|---|
| `sessions` | `topic`, `name`, `mode`, `summary_json`, `started_at`, `ended_at` | Tutor sessions | Partial: `summary_json`. `topic` and `name` (student-chosen) are plaintext. | Owner (`/api/learn/sessions*`) | Student delete is a **hard** delete (`DELETE /api/learn/sessions/{id}`). Wiped. | ANT (topic in the tutor prompt); PH/events (topic only as a 16-hex fingerprint) | M: `0025`; C: `services/tutor/sessions.py:302-303` |
| `messages` | `content`, `role`, `graph_update_json` | Chat transcript | Partial: `content`. `graph_update_json` (concept names, mastery deltas) is plaintext. | Owner | Cascades from sessions | ANT (history and the latest message go into every tutor turn); GEM (each student message is embedded as the RAG query); JEV (the latest message and recent turns in cleartext, only when the `decision_router` flag routes to `jev`) | M: `0025`; C: `services/tutor/messages.py:79`, `services/tutor/run.py:343`, `services/tutor_router.py:167` |
| `tutor_pending_sessions` | `topic`, `assistant_reply`, `graph_update`, `use_shared_context` | Sessions not yet started, plus end/delete tombstones | Partial: `assistant_reply`. `topic` and `graph_update` are plaintext. | Service | Pruned by TTL and a size cap at each stash. Wiped. | as above | M: `20261109024225`; C: `services/tutor_sessions.py:182-188` |

## 5. Quizzes

| Table | Personal columns | Purpose | Encrypted | Readers | Retention | Third parties | Verified |
|---|---|---|---|---|---|---|---|
| `quiz_attempts` | `questions_json`, `answers_json`, `score`, `total`, `difficulty`, `mastery_before/after`, `exam_days_away`, `abandoned_at` | Quiz history | Partial: `questions_json`, `answers_json`. The score columns are plaintext. | Owner (`/api/quiz/*`) | No student delete found. Wiped. | ANT (quiz generation and grading context) | M: `0025`, `20260813013547`, `20260822090747` |
| `quiz_responses` | `answer_text`, `selected_index`, `is_correct`, `time_ms`, `confidence` | Per-question answers | Partial: `answer_text`. Timing and confidence are plaintext. | Owner | Cascades from attempts | ANT (written answers are graded) | M: `20260812214402`, `20261018010000` |
| `quiz_context` | `context_json` | Model-written learner profile per concept | Yes | Owner; Service | Wiped | ANT (the prompt includes the student's **display name**) | M: `0025`; C: `services/quiz/submission.py:451`, `prompts/quiz_context_update.txt` |

## 6. Knowledge graph and mastery

| Table | Personal columns | Purpose | Encrypted | Readers | Retention | Third parties | Verified |
|---|---|---|---|---|---|---|---|
| `graph_nodes` | `concept_name`, `subject`, `mastery_score`, `mastery_tier`, `times_studied`, `last_studied_at` | Per-student mastery model | No | Owner (`/api/graph`); **Peers**: every member of a study room receives every other member's full graph in the room overview | Student delete per node (`DELETE /api/graph/{id}/nodes/{node}`), hard. Wiped. | ANT (tutor, quiz and study-guide prompts; room members' mastered and struggling lists with names in the room-summary prompt) | M: `0023`; C: `services/social/overview.py:43-61,91` |
| `graph_edges` | concept relations per user | Graph structure | No | Owner | Cascades | ANT | M: `0023` |
| `node_mastery_events` | `delta`, `reason`, `event_type` | Append-only mastery journal | No | Owner; Service | Cascades from nodes. Never edited. | none | M: `0023`, `20260814051517` |
| `offering_concept_stats`, `offering_summary` | Class aggregates: per-concept counts, % struggling, `common_misconceptions`, `summary_text` | Class Intel, derived from enrolled students' graphs | No | Peers: students enrolled in the offering | Rebuilt on refresh. Purged when no consenting student remains. | ANT (the `course_summary` agent writes `summary_text` from the aggregates) | M: `0022`; C: `services/course_context_service.py:230-260` |

## 7. Study tools

| Table | Personal columns | Purpose | Encrypted | Readers | Retention | Third parties | Verified |
|---|---|---|---|---|---|---|---|
| `flashcards` | `front`, `back`, `topic`, `times_reviewed`, `last_rating` | Flashcards | Partial: `front`, `back`. `topic` is plaintext. | Owner (`/api/flashcards`) | Student delete route exists. Wiped. | ANT (generation from documents, pasted text and weak concepts) | M: `0025`; C: `routes/flashcards.py:234` |
| `flashcard_sets` | `name`, `concepts`, `options` | Saved selections | No | Owner | Student delete route exists. Wiped. | none | M: `20261112060028` |
| `study_guides` | `content`, `previous_content`, `answers`, `goal`, `depth`, `feedback`, `material_ids`, `read_sections` | Generated study guides and the student's check answers | Partial: `content`, `previous_content`, `answers` | Owner (`/api/study-guide`) | No student delete route found. Wiped. | ANT (documents, mastery and quiz history when `use_history`) | M: `0025`, `20261112094239` |
| `topic_checklists`, `topic_checklist_progress` | `content` (outline from the student's materials), `reviewed_at` | Topic checklist | Partial: `content` | Owner (`/api/topic-checklist`) | Cascades from enrollments. Wiped. | ANT | M: `20261019005643` |

## 8. Academics and gradebook

| Table | Personal columns | Purpose | Encrypted | Readers | Retention | Third parties | Verified |
|---|---|---|---|---|---|---|---|
| `enrollments` | `user_id`, `offering_id`, `nickname`, `color`, `letter_scale`, `curve_*`, `syllabus_doc_id` | Which courses a student takes (reveals school, term and schedule) | No | Owner (`/api/graph/{id}/courses`, `/api/gradebook`); Service (classmate directory and matching by school/course) | Hard delete via `DELETE /api/graph/{id}/courses/{course}`. Wiped. | none | M: `0001`→`0020` rename |
| `assignments` | `title`, `due_date`, `notes`, `points_possible`, `points_earned`, `google_event_id`, `gradescope_assignment_id`, `curve_class_mean/sd` | Gradebook and calendar | Partial: `notes`, `points_possible`, `points_earned`. `title` and `due_date` are plaintext. | Owner (`/api/gradebook`, `/api/calendar`) | Cascades from enrollments. Wiped. | GCal (on sync/export, title and **decrypted notes** are written to the student's Google Calendar); GS (grades imported from Gradescope) | M: `0021`, `0042`; C: `routes/calendar.py:520-590`, `services/calendar_service.py:96` |
| `gradebook_categories` | `name`, `weight`, `drop_lowest` | Gradebook | No | Owner | Cascades | none | M: `0021` |
| `gradescope_course_links`, `gradescope_syncs` | `gradescope_course_id`, `stage`, `error_code`, `counts` | Gradescope linkage and queued syncs | No | Owner; Service | Cascades from enrollments. Terminal syncs are pruned after 2 days. | GS | M: `0027`, `20261108214227` |
| Google Calendar import (not stored) | Event `summary` and `description` from the student's primary calendar | Pre-fill assignments | n/a | Owner | Returned to the browser. Stored only if the student saves it. | GCal (scope `calendar.readonly`) | C: `routes/calendar.py:450-490`, `config.py:46-49` |

## 9. Social and rooms

| Table | Personal columns | Purpose | Encrypted | Readers | Retention | Third parties | Verified |
|---|---|---|---|---|---|---|---|
| `rooms` | `name`, `topic`, `course`, `invite_code`, `owner_id`, `is_public` (default false) | Study rooms | No | Members; anyone when `is_public` | Owner delete cascades to members, messages, reactions and activity | none | M: `0001`, `0032`, `0038`, `20261106055333` |
| `room_members`, `room_bans` | membership and bans | Rooms | No | Members; owner | Leave or kick deletes the row | none | M: `0001`, `20261106055333` |
| `room_messages` | `text`, `user_name`, `image_url`, `image_width/height`, `reply_to_id`, `edited_at` | Room chat | Partial: `text`. **`user_name` (display name) is plaintext**, while the same name is encrypted on `user_profiles`. `image_url` is client-supplied. | Members (API and Supabase Realtime) | Student delete is a soft delete: `text` and `image_url` are nulled, and the row and `user_name` stay. Kept on wipe. | none | M: `0001`, `0040`; C: `services/social/messages.py:142-151,185` |
| `room_reactions`, `room_activity` | emoji; `activity_type`, `concept_name`, `detail` | Engagement feed | No | Members | Cascades from rooms. Kept on wipe. | none | M: `0001` |
| `room_summaries` | `summary` (AI summary of members' strengths), `member_hash` | Cached room summary | Partial: `summary` | Members | Kept on wipe | ANT (names plus mastered and struggling concepts per member) | M: `0001`; C: `services/social_cache_service.py:41` |
| `friend_requests`, `friendships` | user pairs, `status` | Friends | No | Both parties | Student delete routes exist. Kept on wipe. | none | M: `20260731193214`; C: `routes/social.py:245-255` |

## 10. Gamification

| Table | Personal columns | Purpose | Encrypted | Readers | Retention | Third parties | Verified |
|---|---|---|---|---|---|---|---|
| `xp_events` | `rule_key`, `amount`, `source_type`, `source_id`, `idempotency_key` | XP ledger (an activity log) | No | Owner (`/api/gamification`) | Wiped | none | M: `20260731193214`, `20261108063442` |
| `user_achievements`, `user_cosmetics` | earned and owned items, `is_featured` | Badges and cosmetics | No | Owner; Peers (featured, on a public profile) | Achievements wiped; cosmetics kept | none | M: `0001` |

## 11. Telemetry and analytics

| Table | Personal columns | Purpose | Encrypted | Readers | Retention | Third parties | Verified |
|---|---|---|---|---|---|---|---|
| `events` | `user_id`, `event_type`, `request_id`, `payload` (ids, counts, routes, scores; for some events a concept or course id), `content_fp` (16-hex fingerprint of chat or topic text) | Product and error telemetry | No (by design it holds no raw text) | Admin (`/api/admin/analytics`); `canopy_metrics()` reads aggregates only | **Indefinite: no deletion code found.** Kept on wipe. | PH (mirrored per event, only for a consenting student) | M: `0035`; C: `services/events_service.py:15-100,330-363` |
| `llm_usage` | `user_id`, `feature`, `task`, `model`, tokens, `cost_usd` | AI cost accounting | No | Admin | **Indefinite: no deletion code found.** Kept on wipe. | PH (`$ai_generation`: model, provider, tokens, cost and trace id; never content) | M: `0035`, `20261016063803` |
| `feedback` | `comment`, `topic`, `rating`, `selected_options`, `session_id` | In-app feedback | Partial: `comment`, `topic` | Admin (`/api/admin/feedback`, decrypted) | **Indefinite.** Kept on wipe. | none | M: `0026`; C: `routes/feedback.py:59-61`, `services/admin/feedback.py` |
| `issue_reports` | `topic`, `description`, `screenshot_urls` | Bug reports | Partial: `topic`, `description`. Screenshots sit in the private `issues-media-files` bucket. | Admin (decrypted) | **Indefinite.** Kept on wipe. | none | M: `0026`, `0029`; C: `routes/feedback.py:76-108` |

## 12. Email

| Table | Personal columns | Purpose | Encrypted | Readers | Retention | Third parties | Verified |
|---|---|---|---|---|---|---|---|
| `newsletter_emails` | `email`, `first_name`, `approved_at`, `joined_user_id`, `joined_at` | Waitlist and allowlist | Partial: `first_name`. **`email` is plaintext by design** (ADR 0026: uniqueness and lookups). `joined_user_id` links the plaintext address to the account. | Admin (`/api/admin/allowlist`) | **Indefinite.** A revoke clears the approval and keeps the row. | RS | M: `0008`, `0019`, `20261022062444`, `20261023212748`; C: `services/admin/allowlist.py:225-256` |
| `email_sends` | `recipient_hash` (HMAC-SHA256 of the normalised address, with a derived key), `kind`, `status`, `provider_message_id`, `error` | Send ledger and dedupe | Hashed, not stored as an address | Admin (`/api/admin/email`) | Indefinite (needed for the "never twice" rule) | RS | M: `20261022063145`; C: `services/email_service.py:118-127` |
| `email_suppressions` | `recipient_hash`, `reason` | Unsubscribes and bounces | Hashed | Admin; public unsubscribe (HMAC token) | Indefinite by design | none | M: `20261022063145` |
| `email_alert_suppressions` | `recipient_hash`, `reason` | Unsubscribes from the operational (admin) alerts only | Hashed | Admin; public unsubscribe (HMAC token scoped to `ops_alert`) | Indefinite by design | none | M: `20261114230351` |
| `email_broadcasts` | `subject`, `body` (admin-written, may contain `{{first_name}}`), `created_by` | Broadcasts | No | Admin | Indefinite | RS | M: `20261022063145` |

## 13. Admin and operations

| Table | Personal columns | Purpose | Encrypted | Readers | Retention | Third parties | Verified |
|---|---|---|---|---|---|---|---|
| `admin_audit_log` | `actor_id`, `target_id`, `payload`. Allowlist actions record the **plaintext email** in `target_id` and `payload` (bulk approve stores the whole list). | Admin audit trail | No | Admin (`/api/admin/audit`) | Indefinite. Kept on wipe. | none | M: `0010`; C: `services/admin/allowlist.py:171-256` |
| `job_applications` | `full_name`, `email`, `phone`, `linkedin_url`, `resume` (path in the private `application_resumes` bucket), `portfolio_link` | Public careers form (applicants, not students) | **No** | Service only (no admin route found; read through the Supabase dashboard, unverified) | **Indefinite: no deletion code found** | none | M: `0001`, `0029`; C: `routes/careers.py:50-95` |
| `jobs` | `payload` (ids only, per CLAUDE.md, unverified), `last_error` | Postgres job queue | No | Admin (`/api/admin/jobs`, counts) | Succeeded jobs pruned after 14 days. Dead letters are never pruned. | none | M: `20261108095241`, `20261108213623`; C: `services/jobs.py:292-320` |
| `encryption_key_check`, `app_leases`, `feature_flags`, `feature_flags_version`, `schema_migrations` | none (`feature_flags.updated_by` is an admin id) | Ops | n/a | Service/Admin | n/a | none | M: as named (`schema_migrations` is created by `db/migrate.py`) |

## Storage buckets (Supabase Storage)

| Bucket | Contents | Public? | Retention | Verified |
|---|---|---|---|---|
| `avatars` | `avatars/{user_id}/avatar.{ext}` (user photos), plus cosmetic and achievement icons | **Public**: anyone with the URL, and the path embeds the user id | Overwritten on re-upload. No deletion on wipe or self-delete was found. | M: `0011`, `0041`; C: `services/storage_service.py:125-154` |
| `issues-media-files` | Issue-report screenshots (they may show student screens) | Private (5 MB, image types only) | Indefinite: no deletion code found | M: `0029`; C: `routes/feedback.py:21,108` |
| `application_resumes` | Applicant résumés | Private | Indefinite: no deletion code found | M: `0029`; C: `routes/careers.py:10,50` |

Uploaded documents are not kept in Storage. Their bytes sit encrypted in `document_uploads.file_data` until the pipeline finishes, and their text is kept in `documents.extracted_text` (C: `services/document_jobs.py:271`).

---

## Third parties

| Service | What it receives | Why | Where configured | Verified |
|---|---|---|---|---|
| **Anthropic (Claude)** | Every agent prompt. That means: full extracted document text and syllabus text, page images when Gemini-vision OCR is enabled, notes, tutor messages with history, the student's graph and quiz history, retrieved RAG chunks (classmates' shared chunks included), written quiz answers, the student's **display name** in quiz-context updates, room members' **names** with their mastered and struggling concepts, and class aggregates. Every slot defaults to Claude (Haiku 5.5, Sonnet 5.5 for the tutor). | Classification, summaries, tutoring, quizzes, study tools | `agents/_providers.py` (`_DEFAULTS`, `SAPLING_MODEL_<TASK>`); `ANTHROPIC_API_KEY` | C: `agents/_providers.py:79-114`, `services/quiz/submission.py:451`, `services/social/overview.py:56-80` |
| **Google Gemini** | (1) Embeddings: every chunk's plaintext at indexing, every tutor message and quiz query at retrieval, and an upload sample for course relevance (`gemini-embedding-001`). (2) Full prompts for any slot an operator points at `gemini-*`, or for the Gemini fallback when the `llm_fallback` flag is on and Claude is unavailable. The learning-loop slots that `CLAUDE.md` says still default to Gemini do not exist on this branch. | RAG; fallback | `services/rag_service.py` (`GEMINI_API_KEY`); `_GEMINI_FALLBACKS` in `agents/_providers.py` | C: `services/rag_service.py:31-116`, `agents/_providers.py:118-140` |
| **PostHog (US)** | Backend: the `events` mirror (event type, payload ids and counts, templated route; `distinct_id` = user id) and `$ai_generation` (model, provider, tokens, cost, trace id; no content), plus 500-error frame summaries. Only for a consenting, non-deleted student. Nothing is sent under DNT/GPC, `error.4xx` is never sent, and no event goes out without a person. Frontend: `$pageview`/`$pageleave` only. No autocapture or session replay. Memory persistence. Identified by account id. Query strings stripped, other users' ids masked in paths, client IP withheld by the `/ingest` proxy. Erasure: `delete_person` on self-delete. | Product analytics | `services/posthog_client.py`, `services/analytics_consent.py`; `frontend/src/lib/analytics.ts`, `frontend/src/lib/ingestProxy.ts`; `POSTHOG_*` env | C: as named |
| **Logfire (Pydantic)** | Span metadata from `instrument_pydantic_ai(include_content=False)` and `instrument_fastapi()`: route, timing, status, model names and token counts. Prompts, model output, system instructions and tool-call arguments/results are not captured; any other content attribute the scrubber is routed arrives only as a length plus a SHA-256 fingerprint, and URL query strings are stripped (`services/logfire_scrubber.py`, tests `tests/test_logfire_scrubber.py`). URL **paths** are kept, so path parameters (opaque `user_<google id>` ids, document ids) do reach Logfire. Sends only when `LOGFIRE_TOKEN` is set. | Tracing and LLM cost attribution | `main.py:88-104,253`, `config.py`, `services/logfire_scrubber.py` | C: `main.py` (`logfire.configure`, `instrument_*`), `services/logfire_scrubber.py` |
| **Resend** | Recipient address, subject and rendered body (may include the first name) for waitlist, welcome and broadcast mail | Email delivery | `services/email_service.py` (`RESEND_API_KEY`, `EMAIL_FROM`) | C: `services/email_service.py:61,475` |
| **Supabase** | The whole primary database and the Storage buckets above. It sees ciphertext only for encrypted columns. Region and backup retention are not recorded in the repo. | Primary datastore | `db/connection.py`; `SUPABASE_URL`, `SUPABASE_SERVICE_KEY`, `SUPABASE_DB_URL` | C: `db/connection.py`; region/backups unverified |
| **Cloudflare** | Every browser request and response in cleartext at the edge (TLS terminates there): the frontend Worker (`@opennextjs/cloudflare`), the `/ingest` PostHog proxy, and Cloudflare Access on staging | Frontend hosting, TLS | `frontend/wrangler.toml`, `SECURITY.md:238` | C: `SECURITY.md`, `frontend/src/lib/ingestProxy.ts`; log retention unverified |
| **Railway** | Hosts the backend API and the job worker, so all decrypted data passes through in memory, along with environment secrets (`ENCRYPTION_KEY`) and stdout logs | Backend hosting | `docs/deploy/railway.md` | C: `docs/deploy/railway.md:317-318`; log contents and retention unverified |
| **Google (OAuth + Calendar)** | Google sign-in returns email, name, avatar and Google id. Calendar scopes `calendar.events` + `calendar.readonly`: the import reads primary-calendar events, and sync/export writes assignment titles and **decrypted assignment notes** into the student's calendar. | Sign-in; calendar | `config.py:46-60`, `routes/calendar.py`, `services/auth/signin.py` | C: as named |
| **Gradescope** | The student's Gradescope email and password, or session cookies, to log in. It returns course and grade data imported into `assignments`. | Grade import | `services/gradescope/client.py` (`https://www.gradescope.com` only) | C: `services/gradescope/client.py:37,115` |
| **TypeSafe / Jev** | The latest tutor message and a clipped recent history, in cleartext over https. Only when the `decision_router` flag selects `jev`. The router only observes and acts on nothing. | Typed decision experiment | `services/typesafe_client.py` (`TYPESAFE_API_KEY`, `TYPESAFE_BASE_URL`), `services/tutor_router.py` | C: `services/tutor_router.py:167-304`, `services/typesafe_client.py:96-101` |
| **Redis (optional)** | Plaintext OCR text for 30 days, only if `REDIS_URL` is set | Cross-worker cache | `services/cache.py`, `services/extraction_service.py` | C: `services/extraction_service.py:390-439`; host unverified |
| **Canopy dashboard** | Aggregate counts only (active users, windowed totals) from `canopy_metrics()`. No per-user rows. | Internal metrics | `routes/internal_metrics.py`, `CANOPY_METRICS_TOKEN` | M: `20260921055024` |

## Gaps and open questions

These are observations from reading the code. None was tested against a live environment.

1. **Profiles are public by default and readable without signing in.** `profile_visibility` defaults
   to `public`. `GET /api/profile/{id}` resolves an anonymous viewer and returns name, year, majors,
   minors, school, bio, location, website and stats. Only the frontend middleware requires sign-in.
   For students who may be minors, the default and the anonymous API path both stand out.
   (`services/profile/public.py:17-80`, `0001` default)
2. **Opt-out defaults for consent.** `share_class_context` defaults to true, so uploads can enter the
   class RAG pool and Class Intel aggregates. `analytics_opt_out` defaults to false, so PostHog is on
   unless the student opts out. Nothing records age or guardian consent.
3. **No retention limit on telemetry and support data.** `events`, `llm_usage`, `feedback`,
   `issue_reports` (and their screenshots), `admin_audit_log`, `newsletter_emails`, `email_sends`,
   `job_applications` and résumés have no deletion or TTL code. The wipe also keeps the telemetry.
4. **Self-delete erases nothing.** Under the current policy self-delete
   hides the account. All study data, OAuth and Gradescope credentials, avatars and room messages
   stay until an admin runs the wipe. Even the wipe keeps `oauth_tokens`, `gradescope_credentials`,
   `user_profiles`, room messages and telemetry. A soft-deleted account cannot export. (The
   self-export now covers the study data; it still omits `events` / `llm_usage` telemetry.)
5. **Plaintext personal fields beside encrypted twins.**
   - `room_messages.user_name` copies the display name in plaintext.
   - `admin_audit_log` stores waitlist emails in plaintext.
   - `newsletter_emails.email` with `joined_user_id` maps a plaintext address to an account, which
     undoes much of what `users.email` encryption protects.
   - Student-typed or derived text is plaintext in `sessions.topic`/`name`,
     `tutor_pending_sessions.topic`, `documents.file_name`, `document_uploads.file_name`,
     `notes.tags`, `flashcards.topic`, `assignments.title`, `messages.graph_update_json`,
     `graph_nodes.concept_name` and `room_activity.detail`.
   - `user_profiles.website`/`year`/`majors`/`minors`/`learning_style` are plaintext.
6. **Google account id is everywhere.** `users.id = user_<google id>` is stored in every table and in
   the public avatar URL path, and sent to PostHog as the distinct id and to Logfire in route paths.
7. **Peers see more than a profile.** Every room member receives every other member's full knowledge
   graph (concept names and mastery tiers) in the room overview. Their names and struggling concepts
   are also sent to Anthropic for the room summary. Class aggregates (`offering_concept_stats`,
   `offering_summary`) have no minimum class size, so a course with one or two consenting students
   exposes near-individual data to classmates. (`services/course_context_service.py:258` sets
   `student_count = len(user_ids)` with no threshold found.)
8. **Embeddings and caches sit outside encryption.** `course_chunks.embedding` is a plaintext vector
   of encrypted text. Vectors can leak content through inversion. The optional Redis OCR cache holds
   plaintext text for 30 days.
9. **Soft deletes keep content.** A deleted document keeps `extracted_text` and `summary`, a deleted
   note keeps `body`, a deleted room message keeps its row and `user_name`, and no purge job hard-
   deletes them later.
10. **Avatars are public objects.** The `avatars` bucket is public. Nothing deletes a user's avatar on
    wipe or self-delete.
11. **Data leaves the platform into the student's own accounts.** Calendar sync writes decrypted
    assignment notes into Google Calendar. That is intended, but it is a copy no deletion path reaches.
12. **Open questions (not answerable from the repo):** Supabase region and backup retention (backups
    hold soft-deleted rows and plaintext columns); Anthropic and Google API data-retention terms in
    force; Railway and Cloudflare log retention; whether `db_user_scope` is on in prod; and the
    Redis provider if `REDIS_URL` is set anywhere.

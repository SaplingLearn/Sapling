# Audit: what Sapling actually knows about a student

**Purpose.** Honest inventory of the signals available to personalize the quiz, ahead of the #537
redesign: what exists, what's reachable at request time, what's affordable, what we'd have to start
capturing.

**Audited at:** `origin/main @ 7681c481` (2026-08-12), in a clean read-only worktree.
**Delta since pin:** #540/#547 (`6081ec58`) merged to main *during* this audit. Verified scope of
that delta: `backend/routes/quiz.py`, `backend/agents/quiz.py`, and migration
`20260812204809_quiz_attempts_adaptive_difficulty.sql` only — it adds an `adaptive` requested
difficulty (widening the `quiz_attempts.difficulty` CHECK), `GET /api/quiz/config`,
`resolved_difficulty` reporting, and a `QuizAPIError` envelope. Nothing else in this document is
affected by it; where a finding is changed by #540 it is flagged inline.

**Verification method legend** (per the ground rules, every claim states how it was produced):
- **[M]** migration DDL read (`backend/db/migrations/`)
- **[C]** code read (file:line cited)
- **[S]** seed-script static analysis (`backend/db/seed_staging.py` = 1 demo student,
  `backend/db/seed_local_rich.py` = 5 users; exact row counts read from the scripts,
  cross-checked by three independent sweep agents)
- **[G]** GitHub issue/PR read
- **Live-DB check: not performed, deliberately.** The local Supabase stack is a machine singleton
  that another session was using under the flock for the whole audit window, and main advanced past
  the audit pin mid-audit (#540's migration) — a fresh replay would have verified a different schema
  than the one audited. [S] is the honest substitute: both seeds are deterministic scripts, so
  "populated" below means "the seed script inserts these rows", not "observed in a live table".

**States used throughout** — never blurred:
- **exists** — in the migration-replayed schema
- **populated** — seed writes rows (with counts)
- **used** — a named reader consumes it today (file:line), else "nothing reads it"

---

## 1. Executive summary

1. Sapling stores far more per-student signal than the quiz consumes: 55 live tables, ~25 of them
   student-touching, essentially all keep-forever (no TTL, rollup, or archival job exists anywhere).
2. The quiz agent on main sees exactly five inputs: per-concept mastery (weakest-first, with
   `last_reviewed_at`), the last 5 completed attempts per concept, an LLM-written mistake digest
   (`quiz_context`), anonymized class misconceptions, and a RAG "COURSE MATERIAL" block.
3. **Two of those five are silently broken in production**: `quiz_context` writes have 42P10'd into a
   swallowed `except: pass` since migration 0025 (#529), and the misconceptions tool filters
   `offering_concept_stats.offering_id` with the *abstract course id* — near-certainly zero rows.
4. So the "adaptive" quiz today actually runs on: mastery + last-5 accuracy + RAG. That's it.
5. The cheapest wins are already in the database and unread: `answers_json` (which distractor was
   chosen) is written on every submit and **nothing ever reads it back**; past `questions_json` is
   never re-read (repetition risk); `assignments.due_date` is plaintext, indexed, and no code
   computes "exam in N days"; learning velocity, `times_studied`, flashcard review state, and tutor
   recency are each one indexed owner-scoped query away.
6. Genuinely missing captures: per-question response time, confidence, question identity/provenance
   (chunks and prompt version are discarded at generation), cross-student item statistics,
   per-question feedback, skip/revise events, and entry context (Tree vs Notes vs exam pressure).
7. Privacy posture is strong at rest (AES-256-GCM manifest, ciphertext oracle) but the public
   privacy policy's encryption enumeration and `SECURITY.md` §3.3 are both stale (pre-#518/#520/#521),
   and RAG `chunk_text` is plaintext with encryption accepted-but-unimplemented (ADR 0025).
8. Cross-student flows are few and known: class aggregates (anonymized, opt-out via
   `share_class_context`, **no k-anonymity floor**), study rooms (disclosed), leaderboards
   (name+XP+streak, `profile_visibility` gate only), and the shared per-course RAG chunk pool.
9. Consent surface: ToS grants processing "solely for the purpose of providing the Service to you"
   and promises no model training on uploads; privacy policy explicitly covers "AI content tailored
   to your performance" and "anonymized class-wide insights". Grades-driven personalization and
   item-level cross-student stats are *not* clearly covered. FERPA is never named in the repo.
10. Recommended order: fix the two silent breaks (they unlock machinery already built), then read
    `answers_json` into the digest, then add question identity/provenance + submit-time telemetry,
    then exam-aware generation. A ~4–5k-token context budget fits the quiz's flash-lite slot.

---

## 2. Catalog (Part 1)

Encryption legend: 🔒 = AES-256-GCM app-layer ciphertext at rest (`backend/services/encryption.py`);
everything unmarked is plaintext. Volume = rich-seed rows for the primary student [S] → order of
magnitude for a real semester (estimate). Retention: nothing below is ever auto-deleted or rolled
up unless stated; deletions are user CRUD or `ON DELETE CASCADE` off `users` [C].

### 2.1 Learning state (knowledge graph + mastery)

| Table | Shape (key columns) | Written by | Read by |
|---|---|---|---|
| `graph_nodes` [M 0023:8–25] | `user_id`, abstract `course_id` (nullable, SET NULL), `concept_name`, `mastery_score` float 0–1, `mastery_tier` CHECK unexplored/struggling/learning/mastered/subject_root, `times_studied`, `last_studied_at`, `color`; UNIQUE NULLS NOT DISTINCT (user_id, course_id, concept_name) | Single chokepoint `graph_service.apply_graph_update` (backend/services/graph_service.py:637–823): tutor tools (agents/tools/graph.py:100–182), quiz submit (routes/quiz.py:473–486), document pipeline (routes/documents.py:890, 515–529), notes extraction (routes/notes.py:404–406), manual add (graph_service.py:561–634) [C] | Tree API `get_graph` (graph_service.py:139–294); recommendations (:826–856); tutor context block (services/graph_context.py:152–193); tutor+quiz `read_concepts_for_user` (agents/tools/graph_read.py:35–112); flashcards weak-concepts <0.4 (routes/flashcards.py:176–199); class aggregation (course_context_service.py:210–213); room summaries (routes/social.py:258–262) [C] |
| `graph_edges` [M 0023:37–50] | `user_id`, source/target node FKs, `relationship_type` CHECK related/prerequisite/builds_on/part_of, `strength` float; UNIQUE 4-tuple | same chokepoint (graph_service.py:782–792) | Tree API; tutor context block; `read_graph_neighborhood` (graph_read.py:147–333) |
| `node_mastery_events` [M 0023:28–35] | append-only: `node_id` FK CASCADE, `delta`, `reason`, `created_at`; idx (node_id, created_at) | `apply_graph_update` only (graph_service.py:740–746). **The computed `event_type` (correct/partial/confusion, routes/quiz.py:459–465) is dropped at write** [C] | `get_graph` only: 14-day `learning_velocity` + last-5 echo (graph_service.py:110–136, 181–198). **The quiz never reads it** [C] |

- Encrypted: nothing — all learning state is plaintext [M].
- Freshness: per-event (every tutor turn with a mastery tool call, every quiz submit, every upload).
- Volume: 13 nodes / 7 edges / 6 events seeded [S] → ~50–150 nodes, 100s–1000s events per real semester (estimate).
- Mastery formula at quiz submit: `after = clamp01(before + score*0.03 − (total−score)*0.02)` (routes/quiz.py:456) [C]. The scalar is independent read-modify-write; the event log is a journal, not a source of truth — nothing replays it [C graph_service.py:730–746].
- Tier thresholds: canonical 0.75/0.45/0.1 (backend/config.py:95–102); a deliberately divergent second set 0.7/0.4 in the tutor's `read_user_progress` (agents/tools/chat_context.py:391–396); flashcards use ad-hoc <0.4 [C].
- Retention: keep-forever; node delete cascades events [M 0023:30].

### 2.2 Quiz

| Table | Shape | Written by | Read by |
|---|---|---|---|
| `quiz_attempts` [M 0025:93–106] | plaintext scalars `score`, `total`, `difficulty` CHECK easy/medium/hard (widened by #540 post-pin), `completed_at`, `created_at`, `user_id`, `concept_node_id` (SET NULL); 🔒 `questions_json`, 🔒 `answers_json` (#521/#527, ciphertext string inside JSONB); idx user, idx concept | generate inserts in-flight row (routes/quiz.py:354–360); submit claims `completed_at` atomically then writes score/total/answers (routes/quiz.py:408–415, 488–496) [C] | `read_recent_quiz_attempts` tool — last 5 completed, scalars only (agents/tools/quiz_history.py:36, 130–219); achievements count rows (achievement_service.py:58–59 — **counts unsubmitted attempts too**); e2e oracles. **`answers_json`: nothing ever reads it back. Past `questions_json`: never re-read** [C] |
| `quiz_context` [M 0025:108–114] | `user_id`, `concept_node_id`, 🔒 `context_json` (#521), `updated_at`. **UNIQUE (user_id, concept_node_id) existed in 0001:146–153, silently lost in the 0025 recreate; no index on the pair at all** [M — exact DDL verified] | post-submit BackgroundTask `_update_context` → `save_quiz_context` upsert `on_conflict="user_id,concept_node_id"` → **Postgres 42P10, swallowed by `except Exception: pass`** (routes/quiz.py:517–527; services/quiz_context_service.py:28–38) — **#529 verified: every live write fails silently** [C] | quiz submit prompt (routes/quiz.py:506), quiz-history tool (quiz_history.py:110–128), class aggregation (course_context_service.py:256–308) |

- `questions_json` wire shape (routes/quiz.py:47–61, 66–118): `{id, question, options:[{label A–F, text, correct:bool}], explanation, concept_tested, difficulty}`. **No provenance** — no chunk ids, no model, no prompt version (prompt hash exists only in trace metadata, agents/quiz.py:160,176) [C].
- `answers_json` shape: `[{question_id, selected_label}]` — distractor identity **is** recoverable by joining against `questions_json`; timing/confidence/skip/revise are not captured anywhere (frontend/src/components/QuizPanel.tsx:142–148 is one-shot) [C].
- `context_json` intended shape (agents/quiz_context.py:22–45): `{weak_areas[], common_mistakes[], questions_seen_summary, recommended_difficulty, notes}`. Dead even when rows exist: `recommended_difficulty` has no reader, and the digest coercer looks for `misconceptions/weak_areas/common_errors` while the agent writes `common_mistakes` (quiz_history.py:60–86) [C].
- Misconception source: `offering_concept_stats.common_misconceptions` — see §2.10.
- Freshness: per-attempt. Volume: 3 attempts + 1 context row seeded [S] → 10s–100s attempts/semester (estimate). Retention: keep-forever; in-flight rows (NULL `completed_at`) orphan with no sweep (#542 tracks this) [C][G].

### 2.3 Tutor

| Table | Shape | Written by | Read by |
|---|---|---|---|
| `sessions` [M 0025:70–81] | `user_id`, `offering_id` (nullable = general), `mode` CHECK socratic/expository/teachback, `topic` (plaintext), `name`, 🔒 `summary_json`, `started_at`, `ended_at` | lazy insert on first turn (routes/learn.py:308–341); `ended_at` + encrypted summary at end (learn.py:988–991, 1032–1058) | session list w/ per-session message_count (learn.py:1084–1112); resume (1167–1219). `summary_json`'s only later reader: flashcard generation when a session_id is passed (routes/flashcards.py:97–112, 213–215). `sessions.name`: seed-only, **nothing reads it** [C] |
| `messages` [M 0025:83–91] | `session_id`, `role`, 🔒 `content`, **plaintext `graph_update_json`** (concept names of the turn's mastery writes — beside encrypted content), `created_at` | per turn (learn.py:725–727, 796–814) | history replay into agent (decrypt at learn.py:238–273); `graph_update_json` read only by `end_session` (1011–1030) |

- Mode: stored once at session creation; **`POST /mode-switch` never updates it** — per-turn mode comes from the request body (learn.py:1289–1306, 525) [C].
- Per-turn injected context (learn.py:507–592): catalog chunk, RAG top-5 on the user message, the student's own graph-context block (≤12 concepts, 1.5k chars, services/graph_context.py:152–193), full decrypted history. **Notes are never injected. No class-aggregate tool is registered on the tutor** — the opt-out constraint string guards a future tool (learn.py:567–571; agents/chat_tutor.py:152–167) [C].
- Tutor writes mastery in-band: `update_mastery_tool` schema-bounded to [−0.1, +0.3] (agents/tools/graph.py:42–50). Teach-back has no separate grading — same tool, different system prompt [C].
- summary_json shape as written: `{concepts_covered, mastery_changes: [], new_connections: [], time_spent_minutes, recommended_next: []}` — three of five fields always empty (learn.py:1032–1038) [C].
- Freshness: per-turn / per-session. Volume: 2 sessions / 6 messages seeded [S] → 100s–1000s messages/semester (estimate). Retention: user-initiated hard delete of a session removes its messages (learn.py:1162–1163); nothing automatic.

### 2.4 Notes

| Table | Shape | Written by | Read by |
|---|---|---|---|
| `notes` [M 0025:33–47] | `user_id`, `offering_id` NOT NULL, 🔒 `title`, 🔒 `body`, plaintext `tags[]` (deliberate, for PostgREST filters — but **no server-side tag filter exists anywhere**), 🔒 `last_summary`, `last_summary_at`, `deleted_at` soft delete | CRUD (routes/notes.py:182–257 → services/notes_service.py:49–137); summarize agent writes `last_summary` (notes.py:364–382) | list/read routes; note-chat agent's `read_active_note` tool (agents/tools/note_context.py:32–51); send-to-tutor preface = `last_summary` + first 1500 chars (notes.py:459–481) |
| `note_concepts` [M 0025:49–54] | (note_id, concept_node_id) PK, FKs CASCADE | concept extraction → `link_concept` (notes.py:385–415); manual link/unlink (:279–307) | `list_linked_concepts` decorated with live mastery (notes_service.py:230–257); **generate-quiz picks the lowest-mastery linked concept** (notes.py:484–503) |

- The notes→quiz path passes only `{concept_node_id, concept_name}` — **note text never reaches quiz generation** [C notes.py:499–503].
- Populated: 3 notes seeded, **0 `note_concepts` rows in either seed** [S]. Freshness: per-edit. Retention: soft delete only.

### 2.5 Documents / RAG

| Table | Shape | Written by | Read by |
|---|---|---|---|
| `documents` [M 0025:15–31, 0030:7–8] | `user_id`, `offering_id` NOT NULL, `file_name`, `category` CHECK (syllabus/lecture_notes/slides/reading/assignment/study_guide/other), 🔒 `summary`, 🔒 `concept_notes`, 🔒 `extracted_text` (0030), dead `flashcards` JSONB, `request_id` (its 0018 idempotency UNIQUE was **not recreated** by 0025), `processed_at`, `deleted_at` | SSE upload pipeline (routes/documents.py:665–1016): classify → summarize+concepts (+syllabus) → persist → post-roll RAG index. Sync twin `/upload/sync` **never indexes chunks and never stores extracted_text** (:656–658) [C] | course-material block for flashcards/study guides (summaries, not chunks); tutor `search_course_materials` tool — **broken on a replayed schema: filters dropped column `documents.course_id`, error swallowed → always []** (agents/tools/chat_context.py:149, 156–161) [C] |
| `course_chunks` [M 0039:28–52] | content-addressed `id` = sha256(course_code::document::text), **BU `course_code` partition key** (not the Sapling course id), `doc_id`/`uploader_id` last-writer-wins, **plaintext `chunk_text`**, `embedding VECTOR(768)` (gemini-embedding-001), ivfflat cosine; `match_course_chunks` RPC | `_index_document_chunks` post-roll (documents.py:1044–1136) with a 0.35 catalog-relevance gate; catalog ingest script | **quiz generation** `_course_material_block` (routes/quiz.py:176–206): catalog chunk + `retrieve_chunks(concept_name, k=5, min_sim 0.55)`; tutor per-turn retrieval (learn.py:546–551) |

- **Cross-student by construction**: N students uploading the same slides dedup to one chunk row; every student's quiz COURSE MATERIAL block can contain text from documents other students uploaded for that course code [C rag_service.py:161–177].
- `chunk_text` plaintext while the same text is encrypted in `documents.extracted_text` — ADR 0025 accepts encrypting it but is explicitly **unimplemented** ("Implementation (not done here)") [C docs/decisions/0025-encrypt-rag-chunk-text.md:90].
- Chunks are not term-scoped (`semester` hardcoded "current", rag_service.py:214) and are **never deleted** — soft-deleting a document leaves its chunks retrievable forever [C].
- Embedding client is `model_mode()`-gated (#439): in function mode retrieval returns `[]` and indexing indexes 0 — **RAG is structurally empty in every E2E run and in both seeds (0 chunk rows)** [C][S].
- Coverage per course: derivable (`documents` per offering, `course_chunks` per course_code — both indexed) but **no rollup query exists anywhere**; admin analytics has zero document/chunk rollups [C].
- Retention: chunks forever; 30-day Redis TTL on the OCR extraction cache (full plaintext of the document, keyed by content hash — cross-user by design, off unless REDis_URL set) [C extraction_service.py:322–364].

### 2.6 Course context (enrollment / semesters / offerings)

- `terms`, `courses` (abstract catalog), `course_offerings` UNIQUE (course_id, term_id, section), `schools` [M 0019/0020]. `enrollments`: `user_id`, `offering_id`, plaintext `color`, `nickname` (student free text), `enrolled_at`, `letter_scale` JSONB, curve columns, `syllabus_doc_id`; UNIQUE (user_id, offering_id) [M 0001:48–61, 0020:84–88].
- Resolvers in `services/academics.py` (current_term :28–44, resolve_offering :93–167, offering_course_id lru-cached :170–182, enrollment auto-create :337–383) [C].
- **Active semester is client-side only**: `localStorage sapling_active_semester`, "All semesters" default (#360 veto of auto-scoping); arrives per-request as a `semester` query param; the backend never stores it (frontend/src/lib/useActiveSemester.ts:5, 52–56) [C]. Consequence for the quiz: the server cannot know the student's semester focus except per-request.
- **#449 duplicate-offering shape: fixed on main; issue is stale-open** — `get_courses` collapses to one row per abstract course with `enrollment_ids` + `terms` arrays (graph_service.py:299–379, docstring cites #449) [C][G].
- Populated: 5 enrollments (incl. same course across two terms) [S]. Freshness: onboarding + manual course management. Retention: keep.

### 2.7 Schedule & assessment

- **No calendar-events table exists** [M full inventory]. Schedule = `assignments.due_date` (plaintext DATE, indexed) + Google Calendar sync (`google_event_id`, `oauth_tokens` 🔒).
- `assignments` [M 0021:30–57, 0042]: enrollment-keyed (nullable = calendar-only), plaintext `title`/`due_date`/`assignment_type` (homework/exam/reading/project/quiz/other)/`source` (manual/syllabus/gradescope), 🔒 `notes`/`points_possible`/`points_earned` (`decrypt_numeric` at read), plaintext curve class stats.
- Writers: syllabus-extraction agent (services/calendar_service.py:34–65, 130), manual CRUD (routes/calendar.py:324–399; routes/gradebook.py:387–462), gradebook syllabus apply (:467–550), Gradescope sync upsert (routes/gradescope.py:562–599) [C].
- Readers: calendar upcoming/all (next 20 by due_date, routes/calendar.py:341–352), gradebook grade math (pure functions, decrypt-first), study-guide exam picker (`assignment_type == "exam"` or title keywords, routes/study_guide.py:300–314), achievements grade-A stat (achievement_service.py:307–313) [C].
- **"Exam in N days": does not exist.** No urgency/proximity computation anywhere; closest is the upcoming list and per-assignment study-block suggestions ("Due <date>", routes/calendar.py:402–419) [C].
- **No grade value reaches any LLM prompt** — exhaustive grep of points columns across agents/services: zero hits; `SECURITY.md` §3.5's prompt-boundary enumeration deliberately excludes the gradebook [C].
- Populated: 11 assignments (3 ungraded, 2 future-dated) [S]. Freshness: per-edit/per-sync. Retention: keep.

### 2.8 Gamification (#505)

- `xp_events` append-only ledger (UNIQUE idempotency key), `xp_rules` (6 seeded; `flashcards_reviewed_10` and `daily_goal_met` are **dead — nothing awards them**), `growth_stages` (11), `users.total_xp/level/daily_goal_xp/longest_streak` caches (`daily_goal_xp` inert — nothing writes it), `achievements` (30 live badges) + `achievement_triggers`, `user_achievements`, `friendships`/`friend_requests` [M 20260731193214, 20260731194102] [C routes/gamification.py:106–108].
- XP awards: quiz submit 30 XP (routes/quiz.py:535), session end, document upload, note create, achievement unlock — single path `xp_service.award_xp`, ledger-recomputed caches [C].
- Streaks: `users.streak_count/longest_streak/last_active_date`, advanced on mastery updates and session end (graph_service.py:753–758; learn.py:1009); login does not touch it [C].
- Leaderboard: computed from `xp_events` (no table); exposes other students' `user_id`, decrypted display name, level, stage, `total_xp`, `week_xp`, `streak` — **no anonymization**, only a `profile_visibility='private'` hide (routes/gamification.py:161–234) [C].
- `quizzes_completed` achievement stat counts **all** attempts incl. unsubmitted (achievement_service.py:58–59) [C].
- Populated: **zero gamification rows in both seeds** (only migration-seeded catalogs); seeded `streak_count` values lack `last_active_date` so first touch resets to 1 [S]. Freshness: per-event. Retention: ledger forever.

### 2.9 Social

- `rooms` (+`is_public`, `owner_id`), `room_members`, `room_messages` (🔒 `text`, denormalized plaintext `user_name`, realtime-published), `room_reactions`, `room_summaries` (🔒 `summary`, plaintext `member_hash` cache key), `room_activity` (**baseline table; never seeded; no reader found — flagged as dead**) [M 0001, 0032, 0038, 0040].
- Cross-student flow: room roster + messages (disclosed in the privacy policy); the AI room summary is generated from members' mastered/struggling concept-name lists off `graph_nodes` and cached encrypted keyed on a mastery-hash (routes/social.py:255–282; services/social_cache_service.py) [C]. One payload deliberately excludes mastery ("carries **no mastery data**", social.py:607) [C].
- Populated: 2 rooms, 6 messages, 1 summary [S]. Retention: keep.

### 2.10 Class aggregates (the misconception source)

- `offering_concept_stats` [M 0022:7–21]: per (offering, concept): `student_count`, `avg_mastery_score`, `pct_mastered/struggling/unexplored`, `common_misconceptions[]`, `effective_explanations[]` (**never produced by the writer — always empty**), `prerequisite_gaps[]`. `offering_summary` [M 0022:23–32]: counts, top lists, LLM `summary_text`.
- Writer: `course_context_service.update_course_context` (:155–401) — **synchronous** after every graph write touching the course (so inside quiz-submit request path, including a possible Gemini summary call, graph_service.py:794–804; course_context_service.py:372–380); sources = enrolled *consenting* students' `graph_nodes` + decrypted `quiz_context.context_json` (`common_mistakes` → `common_misconceptions`) [C].
- Consent: `user_settings.share_class_context` (0037, default true) enforced at this single write chokepoint (`_filter_shared_context_users` :35–59); flipping it re-aggregates and all-opt-out purges. The 0037 header records that it previously gated only the read path (#72 — now fixed at write) [M][C].
- Anonymization: no user ids stored; strings pooled, deduped, capped 20; **no k-anonymity floor** — a 1-student offering's "aggregate" is that student's data [C].
- Readers: quiz agent's `read_misconceptions_for_course` (graph_read.py:345–423) — **but see the id-space mismatch in §3**; `offering_summary.summary_text` and `get_course_context` have **no production reader** [C].
- Populated: neither seed writes aggregates; they materialize only at runtime [S].

### 2.11 Profile & preferences

- `user_profiles` [M 0024:6–22]: 🔒 `name/first_name/last_name/bio/location`; plaintext `username`, `avatar_url`, `website`, `year`, `majors[]`, `minors[]`, `learning_style`. Written at onboarding (routes/onboarding.py:75–78). **No agent prompt consumes year/majors/learning_style** — read only by profile routes [C].
- `user_settings` [M 0001:422–445, 0031, 0037]: `profile_visibility` (public/school/private), notification/theme/font prefs, cosmetics/featured, `share_class_context`. No accessibility-specific fields beyond `font_size`/`theme` [M].
- AI-disclaimer acknowledgement: **client-side only** — `localStorage sapling_disclaimer_ack` (frontend/src/components/DisclaimerModal.tsx:7, 22–32); never stored server-side [C].
- Display names resolve via `services/profiles.py` (decrypt off `user_profiles`); the quiz uses it once — the student's first name goes into the quiz-context agent prompt (routes/quiz.py:504) [C].

### 2.12 Telemetry

- `events` [M 0035:25–34]: nullable `user_id` (no FK by design), `event_type`, `category` usage/audit/error, `payload` (ids/counts/enums only), `content_fp` 16-hex fingerprint — **raw text never stored**. Frozen 14-type taxonomy (services/events_service.py:31–91): `error.4xx/5xx`, `auth.login`, `auth.permission_denied`, `document.upload`, `document.processed`, `quiz.started`, `quiz.completed` (payload incl. `mastery_delta`), `chat.message_sent`, `note.created`, `session.started`, `session.ended` (incl. `time_spent_minutes`), `rag.retrieval_failed`, `rag.chunks_dropped`. Emitters cited per event in the sweep (e.g. quiz routes/quiz.py:363–374, 546–557) [C].
- `llm_usage` [M 0035:41–54]: `feature`, `task`, served `model`, provider, token triple, `cost_usd`, optional `user_id`, `request_id` — written by `record_agent_usage` around every agent call (agents/usage.py:90–121) [C].
- Readers: admin-only rollups (`/api/admin/analytics` usage summary, by-user incl. per-user LLM cost, errors feed) [C routes/admin_analytics.py:314–479].
- Fire-and-forget bounded queue; kill switch env; never blocks a request [C]. Freshness: per-event. Retention: forever, no rollup. Populated: neither seed writes events [S].

### 2.13 Misc student-adjacent

- `feedback` (🔒 comment/topic, has `session_id`), `issue_reports` (🔒 topic/description) [M 0026]; admin-only decrypt surface (routes/admin.py:622–651).
- `gradescope_credentials` (🔒 email/password/cookies; BU SSO passwords used in-memory only, never persisted), `gradescope_course_links` (enrollment-keyed) [C routes/gradescope.py:241–341].
- `oauth_tokens` (🔒 Google tokens). `newsletter_emails` plaintext by ADR 0026. `admin_audit_log`. Flagged dead/unread: `room_activity`, `documents.flashcards` column, `achievement_cosmetics`, `user_cosmetics` (no later writer), `sessions.name`, `offering_summary.summary_text`, `quiz_context.recommended_difficulty` [C — "nothing reads it" verified by grep].

---

## 3. Signal matrix (Part 2)

State: **now** = reaches the quiz agent today · **derivable** = one query away, code change only ·
**capture** = needs new collection. Privacy: **own** = never leaves owner · **class** = anonymized
aggregate · **cross** = identifiable cross-student. Cost assumes the existing per-user indexes;
"decrypt" = AES-GCM app-layer decryption needed.

| # | Signal | Source | State | Reaches model today? | Access cost | Staleness risk | Privacy | Value for quiz personalization |
|---|---|---|---|---|---|---|---|---|
| 1 | Per-concept mastery (weakest-first) + last_reviewed_at | `graph_nodes` | now | **Yes** — `read_concepts_for_user` (cap 25) | 1 indexed query, no decrypt | Low (per-event writes) | own | **High** — the backbone of targeting; already drives concept selection + spaced repetition |
| 2 | Recent attempt accuracy per concept | `quiz_attempts` scalars | now | **Yes** — last 5 via `read_recent_quiz_attempts` | 1 indexed query, no decrypt | Low | own | **High** — drives the prompt's difficulty rules |
| 3 | Personal mistake digest | `quiz_context.context_json` | now (broken) | Wired, but **empty in prod** — #529 write failure + `common_mistakes` key never surfaced | 1 query + decrypt | Currently infinite (writes fail) | own | **High once fixed** — the intended personalization memory |
| 4 | Class misconceptions | `offering_concept_stats.common_misconceptions` | now (broken) | Wired, but tool passes abstract course id as `offering_id` → ~zero rows (graph_read.py:412 vs routes/quiz.py:311); writer also starved by #529 | 1 indexed query, no decrypt | High until both fixed | class (opt-out, no k-floor) | **High once fixed** — distractor material |
| 5 | Course material grounding | `course_chunks` via `retrieve_chunks(concept_name)` | now | **Yes** — COURSE MATERIAL block, primary source of truth per prompt | Embedding call (60s-bounded, in request path) + RPC | Med: never term-scoped, never deleted, empty for unindexed courses | cross (shared per course code) | **High** — keeps questions on-syllabus; query is only the concept name today |
| 6 | Which distractor was chosen, per question | `quiz_attempts.answers_json` ⋈ `questions_json` | derivable | **No — written every submit, never read by anything** | 1 query + decrypt + join in code | Low | own | **High** — the raw material for personal misconception mining without new capture |
| 7 | Questions already seen | past `quiz_attempts.questions_json` | derivable | No — never re-read; repetition risk is real | 1 query + decrypt (N rows) | Low | own | **Med-High** — avoid repeats, enable "retake what I missed" (#537 wants this) |
| 8 | Mastery trajectory / learning velocity | `node_mastery_events` (14-day velocity already computed in `get_graph`) | derivable | No | 1 indexed query + small aggregation | Low | own | **Med** — distinguishes "recovering" from "stuck" at same mastery score |
| 9 | times_studied per concept | `graph_nodes.times_studied` | derivable | No (column not selected by the tool) | free (add to existing select) | Low | own | **Med** — exposure count vs mastery separates "never tried" from "tried and failing" |
| 10 | Exam proximity | `assignments.due_date` + type/title heuristic (exists in study_guide picker) | derivable | No — nothing computes "exam in N days" anywhere | 1 indexed query, no decrypt | Low (syllabus/manual/sync updates) | own | **High** — cheap, plaintext, changes what a quiz should emphasize |
| 11 | Tutor recency + concepts discussed | `sessions.started_at/mode/topic` + `messages.graph_update_json` (plaintext names) | derivable | No | 2 indexed queries, no decrypt for the names | Low | own | **Med** — "you studied X with the tutor yesterday" targeting |
| 12 | Session summaries | `sessions.summary_json` | derivable | No (only flashcards read it) | query + decrypt | Med (3 of 5 fields always empty) | own | **Low-Med** as-is |
| 13 | Flashcard review state | `flashcards.times_reviewed/last_rating/last_reviewed_at` | derivable | No | 1 indexed query, no decrypt | Low | own | **Med** — independent recall evidence per topic |
| 14 | Note-linked concepts | `note_concepts` ⋈ `graph_nodes` | now (entry only) | Only as the generate-quiz entry point (lowest-mastery pick); note text never reaches generation | 1 query | Low | own | **Med** — "quiz me on my notes" scope exists; content grounding would need decrypt+consent thought |
| 15 | RAG coverage per course | count(`course_chunks`) by course_code | derivable | No — no rollup exists | 1 count query | Low | class | **Med** — decide grounded vs general-knowledge mode instead of silently ungrounded |
| 16 | Engagement intensity / streak | `users.streak_count` + `xp_events` per-day mix | derivable | No | 1–2 indexed queries | Low | own | **Low-Med** — session-length/pacing hints, not question content |
| 17 | Abandonment | `quiz_attempts` where `completed_at IS NULL`; `quiz.started` w/o `quiz.completed` events | derivable | No | 1 query | Med (no status field, #542) | own | **Med** — "you bailed at question 3" resume/retune |
| 18 | Profile: year / majors / learning_style | `user_profiles` | derivable | No — no prompt consumes them | 1 query, plaintext | High (one-time onboarding, self-reported) | own | **Low** — weak, stale, stereotyping risk |
| 19 | Grades / gradebook | `assignments.points_*` 🔒 | derivable (policy-gated) | **No — verified: no grade reaches any prompt** | query + `decrypt_numeric` | Med | own (FERPA-adjacent) | **Med** but consent/FERPA flags first (§5) |
| 20 | Class mastery distribution | `offering_concept_stats.avg_mastery/pct_struggling`, `prerequisite_gaps` | derivable | No (only misconception strings are wired) | 1 indexed query | Med (sync rebuild per graph write) | class | **Med** — "the whole class struggles here" weighting |
| 21 | Per-question response time | — | **capture** | No | client capture + payload field | — | own | **High** — fluency vs guessing; certainty proxy |
| 22 | Confidence per answer | — | **capture** | No | UI change + payload field | — | own | **Med-High** — calibration signals, confident-wrong ≫ unsure-wrong |
| 23 | Question identity + provenance (chunk ids, model, prompt version) | — | **capture** (assembled then discarded today) | No | shape change inside `questions_json` at write | — | own→class | **High** — prerequisite for item stats, repetition control, grounding audits |
| 24 | Item-level difficulty stats across students | — | **capture** (needs #23 first) | No | new aggregate keyed on question_hash | — | class | **Med-High** — calibrated difficulty instead of the model's claim |
| 25 | Distractor↔misconception tag | — | **capture** (agent could emit at generation) | No | schema field in agent output | — | own/class | **Med-High** — turns #6 into labeled misconception evidence |
| 26 | Per-question student feedback ("confusing/wrong") | — | **capture** | No | UI + endpoint + (question_hash) | — | own→class | **Med** — quality loop; #544-adjacent |
| 27 | Skip / revise events | — | **capture** (UI is one-shot today) | No | UI change + payload | — | own | **Low-Med** |
| 28 | Entry context (Tree? Notes? exam nearby?) | — | **capture** (deep-links exist, source not recorded) | No | one field on generate | — | own | **Med** — intent-aware generation |

### What the quiz agent is currently blind to that it could see cheaply today

Ranked, all requiring only code (no schema change, no new capture):

1. **Its own graded history** — `answers_json` ⋈ `questions_json`: which distractor this student picks,
   per concept, across attempts. Written on every submit since #521; zero readers. (decrypt + join)
2. **Questions it already asked** — past `questions_json` stems for repetition avoidance and
   "retake the ones I missed" (#537 explicitly wants this).
3. **Exam proximity** — `assignments.due_date` is plaintext and indexed; the exam-detection heuristic
   already exists in the study-guide picker (routes/study_guide.py:300–314). One query, one prompt line.
4. **`times_studied`** — already in the row the concepts tool reads; just not selected.
5. **Mastery trajectory** — the 14-day velocity computation exists in `get_graph`; the quiz could
   distinguish improving-from-low from flat-at-low.
6. **Tutor recency** — plaintext `graph_update_json` concept names from the last sessions.
7. **Flashcard review state** — plaintext, indexed, per-topic recall evidence.
8. **RAG coverage** — a count query before generation, so "ungrounded" is a decision, not an accident.
9. **Abandonment** — in-flight attempts for this concept.

And the two **repairs** that beat everything above in value-per-line: the #529 UNIQUE restoration
(makes signals 3 and 4's write side live again) and the abstract-course-id→offering-id fix in the
misconceptions tool (makes signal 4's read side return rows).

---

## 4. Missing capture (Part 3), ranked by value-to-effort

Per the spec's list; "already store?" is exact.

| Rank | Item | Already store? | What capturing it costs |
|---|---|---|---|
| 1 | **Which distractor was chosen** | **Yes** — `answers_json` `[{question_id, selected_label}]` + labels in `questions_json` [C routes/quiz.py:492]. | Nothing to capture. Cost is a **reader**: decrypt + join in the digest job. |
| 2 | **Question provenance** (chunk ids, model, prompt version) | No. Retrieved chunks are discarded after prompt assembly (quiz.py:258–265); `prompt_version` lives only in trace metadata (agents/quiz.py:176); served model only in `llm_usage`. | Small: extend the wire/`questions_json` shape (inside the encrypted blob → **no migration**); pass chunk ids through `_course_material_block`. Write-path only. |
| 3 | **Skip, revise, abandon within an attempt** | Skip/revise: no (UI is one-shot, QuizPanel.tsx:142–148). Abandon: derivable (NULL `completed_at`; `quiz.started` w/o `quiz.completed`) but no status/sweep (#542). | UI state change + fields on the submit payload; abandon needs the #542 status column + sweep (already planned). |
| 4 | **Per-question response time** | No — nothing client- or server-side. | Client timer + `elapsed_ms` per answer in the submit payload; shape change inside encrypted `answers_json` → no migration. Request shape change only. |
| 5 | **Session context at quiz time** (came from Tree? Notes? exam in N days?) | No — Tree/Notes deep-links exist (`?concept=`/`?topic=`, notes generate-quiz) but the source is never recorded; exam proximity never computed. | One `source` field on generate + one due-date query server-side. Trivial write cost; store in `questions_json` envelope or an events payload. |
| 6 | **Distractor tagged with its misconception** | No — the agent is *prompted* to build distractors from misconception strings but the mapping is never emitted or stored. | Add `misconception` per option to the agent output schema (output-schema change + function-mode handler update per CLAUDE.md). No DB change (lives in `questions_json`). |
| 7 | **Confidence / certainty per answer** | No. | UI affordance + field in `answers_json`. Cheap technically; the real cost is UX friction — consider sampling it. |
| 8 | **Student feedback on a question** | No — `feedback` table is app/session-scoped, not question-scoped [M 0026:7–18]. | Needs question identity (item 2) to be worth anything; then a small endpoint + UI affordance. |
| 9 | **Item-level statistics** (how often *this question* is missed across students) | No — and **impossible today**: questions are per-generation ephemeral with no stable identity across students. | Needs item 2's `question_hash` first; then either an event payload per graded question or a small aggregate table keyed (course, question_hash). This is the only item that likely wants a **new table/migration**, and it's cross-student → consent framing in §5. |
| 10 | Sweep-suggested extras | — | (a) an `attempt status` enum (#542, planned); (b) `quiz_context` schema versioning so digest keys stop drifting (the `common_mistakes` vs `common_errors` bug class); (c) an `event_type` column on `node_mastery_events` — currently computed and dropped at write (graph_service.py:740–746). |

Items 1–5 need **zero migrations** (encrypted JSONB shapes are ours to evolve; read paths already
tolerate shape drift per the #521 rollout invariant). Item 9 is the only genuinely new
infrastructure.

---

## 5. Constraints (Part 4)

### 5.1 Cross-student flow — the complete list

| Path | What crosses | Anonymization | Cite |
|---|---|---|---|
| Class aggregates → quiz | Other consenting students' mastery %s + LLM-digested mistake strings (`common_misconceptions`) per offering/concept | No user ids; pooled, deduped, cap 20; opt-out `share_class_context` enforced at the single write chokepoint (0037 fixed #72's write-path gap); **no k-anonymity floor** — 1-student offerings expose that student's digest verbatim | course_context_service.py:35–59, 155–401; graph_read.py:345–423 |
| Shared RAG chunk pool → quiz + tutor | Plaintext text of documents uploaded by *any* student of the course code, retrievable by every other student of that course; `uploader_id` on the row (not exposed in prompts) | Content-addressed dedup; no per-user scoping by design; ADR 0025 encryption accepted, unimplemented | rag_service.py:161–177; 0039:28–42 |
| Study rooms | Display name, avatar, messages (🔒 at rest), and mastered/struggling concept-name lists per member feeding the AI room summary | Disclosed in privacy policy §4; summary itself carries no ids; one payload deliberately excludes mastery | routes/social.py:255–282, 607 |
| Leaderboard | user_id, decrypted display name, level, total/week XP, streak — school and everyone scopes | **None** — only `profile_visibility='private'` hides a row | routes/gamification.py:161–234 |
| OCR cache | Full extracted plaintext of a document served to any user uploading identical bytes | Content-keyed by design; Redis, 30-day TTL, off by default | extraction_service.py:322–364 |
| Admin surfaces | Decrypted emails/names (user search), decrypted feedback/issue text, per-user usage + LLM cost | `require_admin` gate; **no admin route reads grades or per-student mastery** (verified zero-match grep) | routes/admin.py:538–651; admin_analytics.py:314–375 |

Not cross-student, worth stating: the tutor currently has **no** class-aggregate tool (chat_tutor.py:152–167), and no grade value reaches any prompt for any user.

### 5.2 Consent surface — what students are actually told

Operative lines, quoted:

- **Disclaimer modal** (frontend/src/components/DisclaimerModal.tsx:64–72): "Responses are generated
  by a large language model and can be wrong… **Your conversations may be used to improve the
  product.** Don't share passwords, IDs, or private info." Acknowledgement = `localStorage
  sapling_disclaimer_ack` only — **never recorded server-side**.
- **ToS §4 User Content** (frontend/src/app/(public)/terms/page.tsx:40): "…you grant us a limited
  license to process and analyze that content **solely for the purpose of providing the Service to
  you. We do not use your uploaded materials to train AI models.**"
- **ToS §5 AI-Generated Content** (:44): "Sapling uses Google Gemini to generate tutoring responses,
  quizzes, flashcards, and study guides."
- **Privacy §1** (privacy/page.tsx:36–39): collects "Knowledge graph data (concepts studied, mastery
  scores, session history)", "Quiz responses and performance data".
- **Privacy §2** (:54–55): uses data to "**personalize the Service, including updating your knowledge
  graph and generating AI content tailored to your performance**" and to "Enable study room and
  social features, including **anonymized class-wide insights**."
- **Privacy §4** (:69): "Your display name, avatar, and knowledge graph data are visible to other
  members of study rooms you join. **Class-wide data shared with other users is anonymized.**"
- **Privacy §5** (:75): retention "for as long as your account is active"; deletion on request.

**Covered today**: own-data quiz personalization (§2 explicitly), anonymized class aggregates (§2/§4),
Gemini as processor (§4).

**Gaps to flag before #537 builds on them:**
1. The privacy policy's §6 encryption enumeration (:82) is **stale** — omits quiz JSON (#521),
   flashcards/study guides/room summaries (#518), feedback/issue text (#520), `extracted_text`
   (0030); "Last updated: May 3, 2026". `SECURITY.md` §3.3 has the same staleness. Not a consent
   blocker, but it's the public accuracy statement.
2. **Cross-student item statistics** (missing-capture #9) and misconception mining from
   `answers_json` are arguably inside "anonymized class-wide insights", but the policy nowhere says
   *quiz answers* feed class-visible signals — today only `quiz_context` digests do. Tighten the
   wording when that ships.
3. **Grade-derived personalization** (signal 19) is *not* covered by any current language; §2 covers
   performance-tailored AI content, but grades are a different sensitivity class (see 5.3).
4. The shared RAG pool means one student's upload text surfaces verbatim to classmates. §4's "class-wide
   data … is anonymized" is the closest covering line; document text isn't obviously "anonymized data".
5. Disclaimer acknowledgement is client-local; an institution-facing deployment would want a
   server-side record.

### 5.3 Institutional context (FERPA-adjacent) — flags only

- **FERPA is never named anywhere in the repo** (repo-wide grep: zero hits; same for GDPR/COPPA/CCPA).
- Grades (`assignments.points_*`, GPA endpoints incl. cumulative "transcript" scope,
  routes/gradebook.py:603–649) and Gradescope-synced scores are the FERPA-shaped records. Today they
  are: encrypted at rest, `require_self`-only, absent from every prompt, absent from admin surfaces.
  That's a defensible baseline.
- **No instructor/teacher role exists** (roles = early-adopter/moderator/admin/verified/vip,
  0002_roles.sql:28–34). The one instructor-framed artifact — `agents/course_summary.py` ("You are an
  expert education analyst summarizing a course for instructors") — writes
  `offering_summary.summary_text`, which **no route serves to anyone**. A school pilot that adds an
  instructor viewer flips this whole audit's privacy tier for class aggregates: flag for legal review
  before any instructor-visible surface ships.
- Anything that moves grades into prompts, class aggregates, or achievements visible to others
  (the `course_grade_a` badge already computes from decrypted grades — achievement_service.py:287–323,
  and badges are featured on profiles) deserves a pass in that review.

### 5.4 Prompt budget

The quiz slot is `gemini-2.5-flash-lite` (ADR 0008; models/__init__.py:53–56) — cheap tokens, so the
budget constraint is attention and latency, not cost. Current request-path spend per generate, rough
token estimates (verifiable against `llm_usage.prompt_tokens`, which already records the truth per
call — use it before trusting these numbers):

- System prompt (agents/quiz.py:83–159): ~800 tokens, fixed.
- COURSE MATERIAL block: catalog chunk + up to 5 chunks × 50–400 words → **up to ~2,600 tokens**,
  today's dominant variable cost.
- Tool returns: concepts ≤25 rows (~250), misconceptions ≤20 strings (~200, currently ~0),
  attempts 5 + digest (~200).
- Total today: ~2–4k in. Headroom is real.

Proposed budget for the redesign (~4–5k in): 
- **Always** (~1.2k): target concept + top-12 mastery snapshot with `times_studied` and a velocity
  flag; last-5 attempts; the personal digest (fixed #529).
- **Conditional** (~2.5k): RAG block only when coverage check says chunks exist, capped at k=4
  (measured by `llm_usage`, trim from the top); misconceptions block only when `use_shared_context`
  and the offering fix lands; one exam-proximity line when an exam is within ~10 days; a
  "recently-asked, don't repeat" list of the last ~15 question stems.
- **Precompute, don't fetch raw**: distractor-choice history, seen-question stems, and velocity
  belong **inside the `quiz_context` digest**, refreshed by the existing post-submit background task —
  that is exactly what `quiz_context` was built to be before 0025 broke it (#529). Raw
  `answers_json`/`questions_json` decryption stays out of the generate path; the digest is one
  decrypt.
- Guardrail from #544: keep everything above measurable via `llm_usage` (feature=quiz) and add the
  spend guard there.

---

## 6. Five recommendations

1. **Repair the two silent breaks before building anything new.**
   Signal: personal digest (#3) + class misconceptions (#4). → The quiz's two highest-leverage
   personalization inputs start flowing again, retroactively justifying machinery already built.
   → Cost: one migration (dedupe + restore `UNIQUE (user_id, concept_node_id)` — already scoped in
   #529) and a course→offering resolution in the misconceptions tool path (graph_read.py:412), plus
   killing the `except: pass` (routes/quiz.py:524–525) so the next silent failure isn't silent.

2. **Mine `answers_json` into the digest — the data is already there.**
   Signal: per-student distractor history (#6) + seen questions (#7). → Distractors targeted at *this
   student's* actual error patterns; no repeated questions; "retake the ones I missed" (#537 ask).
   → Cost: reader-only code in the post-submit digest task (decrypt + join, off the request path);
   extend the digest schema — and fix its key-drift bug (`common_mistakes` never surfaced,
   quiz_history.py:60–86) while in there. No migration.

3. **Give questions an identity and a provenance at write time.**
   Signal: `question_hash`, source chunk ids, model, `prompt_version` inside `questions_json` (#23).
   → Unlocks repetition control, grounding audits ("was this from our materials?"), per-question
   feedback, and is the prerequisite for item statistics (#24) and distractor↔misconception tags (#25).
   → Cost: write-path shape change inside the already-encrypted blob (no migration); pass chunk ids
   through `_course_material_block`; function-mode handler constants updated in the same PR.

4. **Capture attempt telemetry in the submit payload.**
   Signal: per-question `elapsed_ms`, `changed_answer`, skip (#21/#27) + entry `source` on generate
   (#28). → Fluency-aware difficulty (fast-wrong vs slow-wrong), abandonment-aware resume (#542
   pairs), intent-aware generation (Tree vs Notes vs exam prep). → Cost: QuizPanel state + two
   request-shape changes; lands inside encrypted `answers_json`; no migration. Confidence (#22) can
   ride the same shape later if the UX cost is accepted.

5. **Make quizzes deadline-aware.**
   Signal: exam proximity from `assignments.due_date` (#10). → "Exam Thursday" quizzes weight the
   exam's concepts, raise coverage breadth, and can say why; the due-date data is plaintext, indexed,
   and already flowing from syllabus extraction + Gradescope sync. → Cost: one server-side query at
   generate + one prompt line; reuse the study-guide exam heuristic (routes/study_guide.py:300–314).
   Pair with the §5.2 consent-wording touch-ups if any grade *values* (not dates) ever join the
   prompt.

---

*Method note: assembled from seven parallel read-only code sweeps over the pinned worktree plus
inline verification; each claim carries its file:line or migration citation and a method tag.
Two findings are code-verified but not live-DB-verified (the misconceptions id mismatch and the
#529 42P10) — both are deterministic from the cited code and DDL, and #529 is independently
confirmed by issue history [G].*

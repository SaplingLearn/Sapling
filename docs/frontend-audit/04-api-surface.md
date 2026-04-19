# Sapling Frontend Audit — 04 · API Surface

> Every backend endpoint consumed by the frontend. All HTTP through `lib/api.ts` unless noted. Base URL: `process.env.NEXT_PUBLIC_API_URL` (dev default `http://localhost:5000`). Realtime + Storage calls bypass `lib/api.ts` and use the Supabase client directly.

---

## 1. Authoring rules

`lib/api.ts` has one internal helper:

```ts
async function fetchJSON<T>(path, options?): Promise<T> {
  if (IS_LOCAL_MODE) return handleLocalRequest(path, options) as T;
  const res = await fetch(`${API_URL}${path}`, {
    headers: { 'Content-Type': 'application/json', ...options?.headers },
    ...options,
  });
  if (!res.ok) throw new Error((await res.text()) || `HTTP ${res.status}`);
  return res.json();
}
```

Conventions:
- JSON bodies use snake_case (matches FastAPI Pydantic).
- The session cookie is sent automatically (same-origin — `/api/*` rewrites to `BACKEND_URL` via `next.config.ts`).
- Error shape: plain text fallback, or FastAPI's `{detail: string | ValidationError[]}`. A few call sites (`addCourse`, `beginSession`) parse `JSON.parse(err.message).detail` defensively.
- Local mode (`NEXT_PUBLIC_LOCAL_MODE=true`) routes everything to `handleLocalRequest` in `lib/localData.ts`.

---

## 2. Endpoint inventory

### 2.1 Auth

| Method | Path | Caller | Purpose |
|---|---|---|---|
| GET | `/api/auth/google` | `signin/page.tsx:95`, `OnboardingFlow:208`, middleware fallbacks | Start OAuth (hard redirect, not fetch) |
| GET | `/api/auth/google/callback` | Backend only (redirect target) | Receives Google auth code, redirects to `/signin/callback?...` |
| GET | `/api/auth/me?user_id=` | `UserContext.fetchProfileData`, `middleware.ts` (2x), `/api/auth/session` fallback, `/signin/callback`, `/signin` | Session validity + `is_approved` + `onboarding_completed` + roles/cosmetics |
| GET | `/api/users` | `UserContext` | List users (for `userName` reconciliation) |

**Next.js route handler** (local):
| Method | Path | Caller | Purpose |
|---|---|---|---|
| POST | `/api/auth/session` | `/signin` (localStorage re-exchange), `/signin/callback` | Verify `authToken` (fast path, HMAC) or `userId` (slow path, backend round-trip); issue `sapling_session` cookie |
| DELETE | `/api/auth/session` | `UserContext.signOut` | Clear `sapling_session` cookie |

### 2.2 Graph / Courses

| Method | Path | Caller | Purpose |
|---|---|---|---|
| GET | `/api/graph/:userId` | `/dashboard`, `/learn`, `/tree`, `/study-guide` flow (indirectly) | `{nodes, edges, stats}` |
| GET | `/api/graph/:userId/recommendations` | `/dashboard`, `Navbar` "What should I learn next?" | `{recommendations}` |
| GET | `/api/graph/:userId/courses` | `/dashboard`, `/learn`, `/library`, `/calendar`, `FlashcardsPanel`, `/flashcards`, `/tree`, `DocumentUploadModal` | `{courses: EnrolledCourse[]}` |
| POST | `/api/graph/:userId/courses` | `/dashboard`, `DocumentUploadModal` | Add course `{course_id, color?, nickname?}` → `{course_id, already_existed, error?}` |
| PATCH | `/api/graph/:userId/courses/:courseId/color` | `/dashboard` (color picker) | `{color}` |
| DELETE | `/api/graph/:userId/courses/:courseId` | `/dashboard` (manage courses) | Remove course |

### 2.3 Learn (chat tutoring)

| Method | Path | Caller | Purpose |
|---|---|---|---|
| POST | `/api/learn/start-session` | `/learn.beginSession` | `{session_id, initial_message, graph_state}` |
| POST | `/api/learn/chat` | `/learn.handleSend` | `{reply, graph_update, mastery_changes}` |
| POST | `/api/learn/action` | `/learn.handleAction` (hint/confused/skip) | `{reply, graph_update}` |
| POST | `/api/learn/mode-switch` | `/learn.handleModeChange` | `{reply}` |
| POST | `/api/learn/end-session` | `/learn.handleEndSession` | `{summary}` |
| GET | `/api/learn/sessions/:userId?limit=` | `/learn` mount | `{sessions}` |
| GET | `/api/learn/sessions/:id/resume` | `/learn.handleResumeSession` | `{session, messages}` |
| DELETE | `/api/learn/sessions/:id?user_id=` | `/learn.handleDeleteSession` | Remove session |

**Streaming note**: CLAUDE.md describes this as SSE but the frontend uses regular `fetch` → `.json()`. See QUESTIONS Q16.

### 2.4 Quiz

| Method | Path | Caller | Purpose |
|---|---|---|---|
| POST | `/api/quiz/generate` | `QuizPanel.startQuiz` | `{quiz_id, questions}` |
| POST | `/api/quiz/submit` | `QuizPanel.finishQuiz` | `{score, total, mastery_before, mastery_after, results}` |

### 2.5 Calendar / Assignments

| Method | Path | Caller | Purpose |
|---|---|---|---|
| GET | `/api/calendar/upcoming/:userId` | `/dashboard` | Top N upcoming assignments |
| GET | `/api/calendar/all/:userId` | `/calendar` | All assignments |
| POST | `/api/calendar/save` | `AssignmentTable` commit (via `saveAssignments`) | Bulk save edits |
| POST | `/api/calendar/extract` | `extractSyllabus` (raw fetch, not fetchJSON — multipart) | **Used directly?** — confirm; library uploads go through `/api/documents/upload` |
| GET | `/api/calendar/auth-url?user_id=` | Connect flow | `{url}` for Google OAuth |
| GET | `/api/calendar/status/:userId` | `/calendar` mount | `{connected, expires_at?}` |
| POST | `/api/calendar/sync` | `/calendar.handleSync` | `{synced_count}` export assignments to Google |
| POST | `/api/calendar/export` | (defined — `exportToGoogleCalendar`, potentially used by Multi-select sync) | `{exported_count, skipped_count}` |
| GET | `/api/calendar/import/:userId?days_ahead=` | `/calendar.handleImportGoogle` | `{events, count}` |
| DELETE | `/api/calendar/disconnect/:userId` | `/calendar.handleDisconnectGoogle` | `{disconnected}` |

### 2.6 Documents / Library

| Method | Path | Caller | Purpose |
|---|---|---|---|
| GET | `/api/documents/user/:userId` | `/library` mount | `{documents}` |
| DELETE | `/api/documents/doc/:id?user_id=` | `/library.handleDelete`, `DocumentUploadModal.handleReanalyze` | Remove document |
| PATCH | `/api/documents/doc/:id` | `DocumentUploadModal.handleConfirm` (category override) | `{category, user_id}` |
| POST | `/api/documents/upload` | `DocumentUploadModal` (multipart, raw fetch with AbortController 4min) | Upload PDF/DOCX/PPTX |

### 2.7 Flashcards

| Method | Path | Caller | Purpose |
|---|---|---|---|
| POST | `/api/flashcards/generate` | `/flashcards`, `FlashcardsPanel` | `{flashcards, context_used?}` |
| GET | `/api/flashcards/user/:userId?topic=` | Both flashcard surfaces | `{flashcards}` |
| POST | `/api/flashcards/rate` | Both | `{ok}` |
| DELETE | `/api/flashcards/:id?user_id=` | Both | `{ok}` |

### 2.8 Study Guide (`/study` — raw fetch, not via `lib/api.ts`)

| Method | Path | Caller | Purpose |
|---|---|---|---|
| GET | `/api/study-guide/:userId/courses` | `/study` | `{courses}` |
| GET | `/api/study-guide/:userId/exams?course_id=` | `/study` | `{exams}` |
| GET | `/api/study-guide/:userId/guide?course_id=&exam_id=` | `/study` | `{guide, generated_at}` |
| GET | `/api/study-guide/:userId/cached` | `/study` | `{guides}` |
| POST | `/api/study-guide/regenerate` | `/study.handleRegenerate` | `{guide, generated_at}` |

### 2.9 Onboarding

| Method | Path | Caller | Purpose |
|---|---|---|---|
| GET | `/api/onboarding/courses?q=` | `OnboardingFlow` step 4, `/dashboard` course typeahead | `{courses}` |
| POST | `/api/onboarding/profile` | landing-page `handleOnboardingComplete` | `{user_id, first_name, last_name, year, majors, minors, course_ids, learning_style}` |

### 2.10 Social / Rooms

| Method | Path | Caller | Purpose |
|---|---|---|---|
| POST | `/api/social/rooms/create` | `RoomList.handleCreate` | `{room_id, invite_code}` |
| POST | `/api/social/rooms/join` | `RoomList.handleJoin` | `{room}` |
| GET | `/api/social/rooms/:userId` | `/social` mount | `{rooms}` |
| GET | `/api/social/rooms/:roomId/overview` | `/social` (on room switch) | Room data incl. members + AI summary + graph |
| GET | `/api/social/rooms/:roomId/activity` | `/social` (activity tab) | `{activities}` |
| POST | `/api/social/rooms/:roomId/match` | `StudyMatch.handleFindMatches` | `{matches}` |
| POST | `/api/social/school-match` | (defined — not wired) | `{matches}` |
| GET | `/api/social/students` | `SchoolDirectory` | `{students}` |
| POST | `/api/social/rooms/:roomId/leave` | `RoomMembers.handleLeave` | `{left}` |
| DELETE | `/api/social/rooms/:roomId/members/:memberId?requester_id=` | `RoomMembers.handleKick` | `{kicked}` |
| GET | `/api/social/rooms/:roomId/messages` | `RoomChat` mount | Full message history |
| POST | `/api/social/rooms/:roomId/messages` | `RoomChat.sendMessage` | `{message}` |
| DELETE | `/api/social/rooms/:roomId/messages/:messageId?user_id=` | `RoomChat.handleDeleteMessage` | `{deleted}` (soft-delete) |
| PATCH | `/api/social/rooms/:roomId/messages/:messageId` | `RoomChat.handleStartEdit → sendMessage` | Edit `{user_id, text}` |
| POST | `/api/social/rooms/:roomId/messages/:messageId/reactions` | `RoomChat.handleToggleReaction` | Toggle reaction `{user_id, emoji}` → `{added}` |

Plus **Supabase Realtime** (direct, not HTTP):
- `postgres_changes` on `room_messages` (INSERT + UPDATE).
- `postgres_changes` on `room_reactions` (INSERT + DELETE).
- Presence channel `presence:room:<roomId>` for typing indicators.

### 2.11 Profile / Settings / Cosmetics

| Method | Path | Caller | Purpose |
|---|---|---|---|
| GET | `/api/profile/:userId` | `/settings` profile preview | `UserProfile` |
| PATCH | `/api/profile/:userId` | `/settings.saveProfile`, `/settings.checkUsername` (unintentionally) | Update profile fields |
| POST | `/api/profile/:userId/avatar?user_id=` | `/settings.handleAvatarUpload` (multipart) | `{avatar_url}` |
| GET | `/api/profile/:userId/settings?user_id=` | `/settings` mount | `UserSettings` |
| PATCH | `/api/profile/:userId/settings?user_id=` | `/settings.saveSettings` | Partial update |
| POST | `/api/profile/:userId/equip?user_id=` | `CosmeticsManager.handleEquip` | `{slot, cosmetic_id | null}` → `{equipped}` |
| POST | `/api/profile/:userId/featured-role?user_id=` | Settings role picker (if wired) | `{role_id | null}` |
| POST | `/api/profile/:userId/featured-achievements?user_id=` | Settings showcase editor | `{achievement_ids}` |
| GET | `/api/profile/:userId/achievements` | `/achievements`, settings preview | `{earned, available}` |
| GET | `/api/profile/:userId/cosmetics?user_id=` | `CosmeticsManager` mount | `{cosmetics, equipped}` |
| GET | `/api/profile/:userId/roles` | (defined — `fetchRoles`; not currently wired) | `{roles}` |
| DELETE | `/api/profile/:userId/account?user_id=` | `/settings.handleDeleteAccount` | `{deleted}` with body `{confirmation: 'DELETE'}` |
| POST | `/api/profile/:userId/export?user_id=` | `/settings.handleExport` | User data dump (JSON) |

### 2.12 Admin

All require admin auth (server-enforced via `services/auth_guard.py`).

| Method | Path | Caller | Purpose |
|---|---|---|---|
| GET | `/api/admin/users` | `/admin` Users tab | `{users}` |
| PATCH | `/api/admin/users/:id/approve` | `/admin.handleApprove` | `{approved}` |
| POST | `/api/admin/roles` | `/admin.handleCreateRole` | Create role |
| POST | `/api/admin/roles/assign` | (defined — no UI) | Assign role to user |
| DELETE | `/api/admin/roles/revoke` | (defined — no UI) | Revoke role |
| POST | `/api/admin/achievements` | `/admin.handleCreateAchievement` | Create achievement |
| POST | `/api/admin/achievements/grant` | `/admin.handleGrantAchievement` | Grant to user |
| POST | `/api/admin/cosmetics` | `/admin.handleCreateCosmetic` | Create cosmetic |

### 2.13 Feedback / Issue reports

| Method | Path | Caller | Purpose |
|---|---|---|---|
| POST | `/api/feedback` | `FeedbackFlow` + `SessionFeedbackFlow` | `{user_id, type, rating, selected_options, comment?, session_id?, topic?}` |
| POST | `/api/issue-reports` | `ReportIssueFlow` | `{user_id, topic, description, screenshot_urls}` |

### 2.14 Careers (out of scope)

Listed for completeness only; these are part of the marketing `/careers` flow:
- `POST /api/careers/apply` (multipart with optional resume PDF)
- Static data: `src/app/careers/jobs.ts`

---

## 3. Supabase direct calls

Bypass `lib/api.ts`. Require `NEXT_PUBLIC_SUPABASE_URL` + `NEXT_PUBLIC_SUPABASE_ANON_KEY` (lazy-initialized client in `lib/supabase.ts`).

### 3.1 Realtime (chat) — `RoomChat.tsx`

```ts
supabase.channel(`room_messages:${roomId}`)
  .on('postgres_changes', { event:'INSERT', table:'room_messages', filter:`room_id=eq.${roomId}` }, handler)
  .on('postgres_changes', { event:'UPDATE', table:'room_messages', filter:`room_id=eq.${roomId}` }, handler)
  .on('postgres_changes', { event:'INSERT', table:'room_reactions' }, handler)  // no filter — listens to all rooms' reactions
  .on('postgres_changes', { event:'DELETE', table:'room_reactions' }, handler)
  .subscribe();

supabase.channel(`presence:room:${roomId}`, { config: { presence: { key: userId } } })
  .on('presence', { event: 'sync' }, handler)
  .subscribe();
```

**Observation**: the reactions subscription is **not filtered by room**. Every client gets every reaction event for every room. The handler filters in-memory by matching `message_id`. Fine at small scale, noisy if the app grows.

### 3.2 Storage (issue screenshots) — `ReportIssueFlow.tsx`

```ts
supabase.storage.from('issues-media-files').upload(`${userId}/${ts}_${rand}.${ext}`, file);
supabase.storage.from('issues-media-files').getPublicUrl(path);
```

Bucket name: `issues-media-files`. Uses anon key — bucket must allow authenticated uploads (or anon uploads, depending on bucket RLS).

---

## 4. Direct fetch (not via `lib/api.ts`)

Code that uses `fetch` directly instead of `lib/api.ts`:

| Caller | Endpoint | Why |
|---|---|---|
| `/signin/callback` | `${API_URL}/api/auth/me?user_id=` | Mid-callback before UserContext is ready |
| `middleware.ts` | `${API_URL}/api/auth/me?user_id=` | Edge runtime — can't import app code |
| `/api/auth/session` route handler | `${API_URL}/api/auth/me?user_id=` | Edge runtime |
| `UserContext.fetchProfileData` | `${API_URL}/api/auth/me?user_id=` | Legacy — could migrate to `lib/api.ts` |
| `UserContext` mount effect | `${API_URL}/api/users` | Legacy — could migrate |
| `/dashboard` course typeahead | `${API_URL}/api/onboarding/courses?q=` | Legacy — could migrate |
| `OnboardingFlow` step 4 | `${API_URL}/api/onboarding/courses?q=` | Component-local, could migrate |
| `/study/StudyClient` | `/api/study-guide/*` | Anomaly — this whole feature skips `lib/api.ts` |
| `RoomChat` / `ReportIssueFlow` | Supabase (not HTTP) | Correct — different transport |

Rebuild: route *everything* through a single HTTP layer (with local-mode support) unless a different transport is required.

---

## 5. Notable backend-return shapes

(Not exhaustive — cherry-picked for rebuild awareness.)

- `EnrolledCourse` (`lib/api.ts:40-51`): `{enrollment_id, course_id, course_code, course_name, school, department, color: string|null, nickname: string|null, node_count, enrolled_at}`.
- `Session` (`lib/api.ts:108-117`): `{id, topic, mode, course_id, started_at, ended_at, message_count, is_active}`.
- `UploadedDoc` (`DocumentUploadModal.tsx:23-32`): `{id, course_id, file_name, category, summary, key_takeaways, flashcards, created_at}`.
- `RoomMessageRow` (backend shape used by `RoomChat.dbRowToMessage`): `{id, user_id, user_name, text, image_url, created_at, reactions: [{emoji, user_ids}], reply_to_id, reply_to: {id, user_name, text} | null, is_deleted, edited_at}`.
- `Assignment` (`lib/api.ts:186-197`): `{id, user_id, title, due_date, assignment_type?, notes?, google_event_id?, course_id?, course_code?, course_name?}`.

Full types live in `src/lib/types.ts`.

---

## 6. Local mode (`NEXT_PUBLIC_LOCAL_MODE=true`)

`lib/api.ts:13-14` routes `fetchJSON` through `handleLocalRequest(path, options)` in `lib/localData.ts`. `localData.ts` pattern-matches URL paths and returns canned data (see `lib/localData.ts:255-305` for the matcher). Works for:
- graph + recommendations + courses
- calendar assignments
- flashcards CRUD
- profile/settings/cosmetics/achievements/roles
- rooms / matches / messages (partial)
- documents (partial)

**Does not** work for:
- Study-guide endpoints (StudyClient uses raw fetch).
- Supabase Realtime (subscriptions will silently never fire).
- Supabase Storage uploads.

Rebuild should either:
- Replace `localData.ts` with an MSW-based mock server (covers all endpoints uniformly), or
- Keep `localData.ts` but extend it with study-guide stubs and a Realtime mock.

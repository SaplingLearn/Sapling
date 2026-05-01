# Sapling Frontend Audit — 06 · Realtime & Async

> Realtime subscriptions, polling, background refreshes, and any other non-request/response async behavior in the frontend.

---

## 1. What the frontend uses

Supabase Realtime is the only **push** channel. Everything else is request/response with no polling.

### 1.1 Supabase Realtime — chat (`RoomChat.tsx`)

Channel: `supabase.channel('room_messages:' + roomId)`.

Subscriptions:
- `postgres_changes` **INSERT** on `room_messages` with filter `room_id=eq.<roomId>`. Appends new messages. Own messages are suppressed in the handler (`if (row.user_id === userId) return`) because the optimistic UI added them already.
- `postgres_changes` **UPDATE** on `room_messages` with same filter. Applies edits and soft-deletes (`is_deleted=true`).
- `postgres_changes` **INSERT** on `room_reactions` (**no filter** — listens to all rooms). Handler matches `message_id` to the current message list and appends the reaction.
- `postgres_changes` **DELETE** on `room_reactions` (**no filter**). Same matching logic.

**Note on the missing filter**: `room_reactions` subscriptions are not scoped to the current room. Every connected client receives every reaction event across every room. Handlers no-op on non-matching `message_id`. At scale this is wasteful — should add `filter: room_id=eq.<roomId>` in the rebuild (requires the reaction row to have `room_id`, or use a different table/scheme).

Cleanup on unmount: `supabase.removeChannel(channel)`.

### 1.2 Supabase Realtime — presence (`RoomChat.tsx`)

Channel: `supabase.channel('presence:room:' + roomId, { config: { presence: { key: userId } } })`.

Behavior:
- `broadcastTyping(true)` → `channel.track({userId, userName, typing: true})`.
- On input idle (3-second timeout) → `broadcastTyping(false)`.
- `presence` → `{event: 'sync'}` handler reads `channel.presenceState()` and filters to other users with `typing: true`.

Cleanup: `supabase.removeChannel(ch)` on roomId/userId change (not just unmount — `[roomId, userId]` deps in `useEffect`).

### 1.3 Supabase Storage — `ReportIssueFlow.tsx`

Not realtime, but a direct-browser-to-storage write. Uploads to `issues-media-files` bucket via the anon key:

```ts
supabase.storage.from('issues-media-files').upload(path, file);
supabase.storage.from('issues-media-files').getPublicUrl(path);
```

Bucket permissions must allow anon writes (or the user must be authenticated through Supabase — but the app doesn't use Supabase auth, only the anon key). **Verify bucket RLS policy**.

---

## 2. What the frontend does NOT use

No WebSocket connections other than Supabase Realtime's. No SSE consumers (despite CLAUDE.md calling `/api/learn/chat` streaming — see QUESTIONS Q16). No server-sent push notifications. No service worker. No background sync.

No polling anywhere. Notable places where polling would be a natural fit:
- `/pending` does not poll for approval status (see `features/auth.md` §2.4).
- `/calendar` does not re-check Google Calendar status after the user disconnects (`googleConnected` is set purely by client-side state).
- `/social` room overviews don't refresh when another user joins/leaves (outside of what Realtime pushes for chat).

---

## 3. Async patterns per feature

| Feature | Async mechanism |
|---|---|
| Auth | Request/response + middleware live re-check on every navigation |
| Onboarding | Request/response only |
| Dashboard | Request/response only. No refresh on visibility change. |
| Learn | Request/response per chat turn. No streaming (despite backend possibly supporting SSE). Graph refetch after each turn. |
| Quiz | Request/response; client does local correctness check for instant feedback. |
| Study | Request/response. "Generating your study guide..." spinner can run for many seconds. |
| Flashcards | Request/response. Optimistic rating update. |
| Library | Per-file concurrent uploads with 4-minute AbortController timeout. Otherwise request/response. |
| Calendar | Request/response. Google OAuth round-trip via redirect. |
| Social — Rooms | Request/response for overview/activity/match. **Realtime for chat + presence.** |
| Settings | Request/response with optimistic state for toggles. |
| Achievements | Request/response on mount. |
| Admin | Request/response per action. |
| Feedback | Request/response, fire-and-forget (`.catch(() => {})`). |

---

## 4. Animation / RAF loops

Not realtime, but worth documenting because they share mental bandwidth with the chat subscription:

- **KnowledgeGraph drift animation** — `requestAnimationFrame` loop running on every mounted graph (Dashboard center panel, full-screen overlay, Tree, Learn graph pane, Social comparison graph). Never pauses. Minor CPU cost.
- **Landing-page 3D canvas** (`app/page.tsx`) — out of scope, but consumes significant RAF time while the landing page is visible.
- **`FlashcardsPanel` / `/flashcards` study mode** — CSS transitions only, no RAF.
- **`SessionFeedbackFlow` + `FeedbackFlow`** — CSS keyframe animations (`sfSlideUp`/`sfSlideDown`). No RAF.

---

## 5. Things to preserve

- Supabase Realtime subscriptions for chat INSERT/UPDATE and reactions INSERT/DELETE.
- Supabase presence channel for typing indicators.
- Supabase Storage uploads for issue-report screenshots.
- Cleanup on unmount / dep change via `removeChannel`.
- Optimistic chat send with `tmp_${Date.now()}` ID and rollback on error.
- Realtime filters by `room_id` where possible.

## 6. Things to rework

- **Filter `room_reactions` subscriptions by room.** Either add `room_id` to the `room_reactions` table (if missing) or subscribe per-message. Current scheme is a traffic amplifier.
- **Add polling on `/pending`** (every 30s?) or a Realtime subscription on the user's own row for `is_approved` changes.
- **Implement real SSE/streaming** for `/api/learn/chat` — the UX win of token-by-token reply rendering is significant.
- **Periodic refresh on `/social` room overviews** when another user joins/leaves.
- **Pause the KnowledgeGraph RAF** when the graph is off-screen or hidden (mobile tab toggles, fullscreen close).

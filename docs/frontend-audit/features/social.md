# Feature · Social (Study Rooms, Chat, Study Match, School Directory)

> Covers: `/social/page.tsx`, `RoomList`, `RoomOverview`, `RoomChat`, `RoomMembers`, `StudyMatch`, `SchoolDirectory`. The heaviest feature area outside `/learn` and the only place the frontend talks directly to Supabase (Realtime for chat).

---

## 1. Overview

Social is a hub of peer-collaboration features.

Layout:
- **Left sidebar** (`RoomList`): "Study Rooms" header with + Create / Join buttons; list of the user's rooms; "My School" link at the bottom.
- **Main area**: one of:
  - `SchoolDirectory` (when "My School" is selected)
  - `RoomOverview` / `RoomChat` / `StudyMatch` / Activity feed, selected via tabs (Overview / Chat / Study Match / Activity)
  - Members panel (`RoomMembers`), toggled by a Members button (top-right of the main panel)
  - Empty state ("Create or join a room to get started.") when no room is selected

Realtime chat is powered by **Supabase Realtime** subscribed directly from the browser (not via the FastAPI backend). The backend exposes REST endpoints for message persistence / reactions / deletion; the Supabase client receives postgres_changes events on `room_messages` and `room_reactions` tables plus a presence channel for typing indicators.

---

## 2. User flows

### 2.1 Flow: create a room

1. `RoomList` "Create" tab → inline form with room name input.
2. `handleCreate()` → `createRoom(userId, roomName)` → `{room_id, invite_code}`.
3. Displays the invite code with a Copy button (2s "Copied!" state); adds to `rooms` and auto-selects.

### 2.2 Flow: join a room

1. `RoomList` "Join" tab → invite-code input (default empty).
2. `handleJoin()` → `joinRoom(userId, inviteCode)` → `{room}`.
3. Prepends to `rooms` unless already present; auto-selects.
4. On invalid code → generic "Invalid invite code." error.

### 2.3 Flow: overview tab (`RoomOverview`)

Props: `{room, members, aiSummary, myUserId, suggestNodeId, suggestConcept, onSuggestDismiss, onSuggestAccept}`.

- Header: room name, invite code chip with Copy (same 2s "Copied!" pattern).
- AI-generated room summary.
- Comparison viewer: a `CustomSelect` picks another member → `KnowledgeGraph` renders with `comparison={partnerNodes}`. The graph component draws outline rings on each node indicating relative mastery:
  - Cyan (`#38bdf8`) — you know it, they don't.
  - Orange (`#fb923c`) — they know it, you don't.
  - Red (`#f87171`) — both unknown.
  - Green (`#34d399`) — both mastered.
- AI recommendation popup (if `suggestConcept` passed in). Accept routes to `/learn?topic=<>&mode=quiz`; Dismiss clears `?suggest=` from the URL.
- ResizeObserver on the graph container tracks width.

### 2.4 Flow: chat tab (`RoomChat`)

By far the most complex component. 677 lines. Features:

- **Message history**: `getRoomMessages(roomId)` on mount.
- **Supabase Realtime subscriptions**:
  - `postgres_changes` INSERT on `room_messages` (own messages already added optimistically; skipped on `user_id === userId`).
  - `postgres_changes` UPDATE on `room_messages` (handles edits and soft-delete — `is_deleted=true`).
  - `postgres_changes` INSERT/DELETE on `room_reactions` — optimistically updates the target message's `reactions` array.
- **Presence channel** (`supabase.channel('presence:room:' + roomId, {config:{presence:{key:userId}}})`):
  - On input change: `broadcastTyping(true)` → `ch.track({userId, userName, typing:true})`.
  - 3s idle timeout → `broadcastTyping(false)`.
  - On sync, reads `ch.presenceState()` → `typingUsers` state for any non-self presence with `typing:true`.
- **Message optimism**:
  - User sends → prepend a `tmp_${Date.now()}` message with `replyTo` snapshot.
  - On success, server event arrives; on failure, remove by tempId.
- **@mentions**:
  - Regex-detects `@(\w*)$` in the textarea prefix; opens a suggestion dropdown filtered by `name.toLowerCase().startsWith(query)`, excluding self.
  - ArrowUp / ArrowDown / Tab / Enter navigate + insert. Escape dismisses.
  - `renderText` re-escapes member names and highlights them differently based on own-message vs other (`#a7f3d0` for own, `#1a5c2a` for others).
- **Reply**: "Reply" context menu action sets `replyingTo`. Compose bar shows the snippet above the textarea; sending includes `reply_to_id`.
- **Edit**: "Edit" context menu action enters edit mode for own messages. Saving replaces the message text via `editRoomMessage`.
- **Delete**: "Delete" context menu action sets `is_deleted=true` optimistically; server call via `deleteRoomMessage`. Reverts on error.
- **Reactions**: 50-emoji grid picker (`EMOJI_GRID`). Click a message to open the reaction picker; each emoji calls `toggleRoomReaction(roomId, msgId, userId, emoji)`.
- **Image attachments**: `FileReader.readAsDataURL` converts locally to a data URL → sent as `image_url` in the message payload (not uploaded to Supabase Storage — sent inline).
- **Outside-click dismissal**: `document.addEventListener('mousedown', handleClick)` closes pickers when the click lands outside.
- **Auto-scroll to bottom** on new messages (`bottomRef.current?.scrollIntoView`).
- **Keyboard**: Enter sends (Shift+Enter for newline); `handleKeyDown` branches when `@mention` menu is open to intercept arrows/Tab/Enter.

### 2.5 Flow: study match tab (`StudyMatch`)

- "Find Study Partners" button → `findStudyMatches(roomId, userId)` → `{matches}`.
- Each match has `partner` + `compatibility_score`. Sorted descending, top match gets a featured popup modal on first appearance (dismissible; shown once per matches fetch).
- Match cards show partner info + score. Best match gets a highlighted badge.

### 2.6 Flow: activity tab

Inline (`social/page.tsx:287-307`): renders `activity` fetched via `getRoomActivity(roomId)`. Each item: user name, activity type + concept + detail, formatted relative time (just now / Nh ago / Nd ago).

### 2.7 Flow: members panel (`RoomMembers`)

- Triggered by the "👥 {count}" button in the top-right of the main panel.
- Shows list of members with Avatar + name + "Leader" tag for the creator.
- **Leader actions**: kick per-member with two-step confirm.
- **Non-leader actions**: "Leave room" with two-step confirm.
- Updates propagate via `onMembersChange` / `onLeave` props.

### 2.8 Flow: school directory (`SchoolDirectory`)

- Click "My School" in `RoomList` → main area switches to `SchoolDirectory`.
- Lists all students in the user's school (`getSchoolStudents`).
- Each card: initials avatar, name, course pills, top-concepts pills.
- "You" chip on self.
- No interaction — informational only.

---

## 3. State

### `SocialPageInner`
- `rooms`, `activeRoomId`, `overviewData`, `activity`, `matches`
- `tab`: `'overview' | 'chat' | 'match' | 'activity'`
- `schoolView`, `showRooms` (mobile), `showMembers`
- Loading / error flags per section
- `searchParams.suggestConcept`, derived `suggestNodeId`

### `RoomChat` (non-exhaustive — see code for full list)
- `messages`, `historyLoading`, `input`, `pendingImage`, `sending`
- `showEmojiPicker`, `reactionPickerFor`, `contextMenuFor`
- `replyingTo`, `editingMessage`
- `typingUsers`, `typingTimeoutRef`, `presenceChannelRef`
- `mentionQuery`, `mentionIndex`

### `RoomList`
- `panel`: `'none'|'create'|'join'`
- `roomName`, `inviteCode`, `newCode`, `copied`, `loading`, `error`

### `RoomOverview`
- `copied`, `compareWith`, `isMobile`, `graphWidth`

### `RoomMembers`
- `confirmLeave`, `confirmKickId`, `kickingId`, `leavingLoading`

### `StudyMatch`
- `showPopup`

---

## 4. API calls

Rooms:
- `getUserRooms(userId)` / `createRoom` / `joinRoom` / `leaveRoom` / `kickMember`
- `getRoomOverview(roomId)` / `getRoomActivity(roomId)`

Match:
- `findStudyMatches(roomId, userId)` / `findSchoolMatches(userId)` / `getSchoolStudents()`

Chat (REST + Supabase Realtime):
- `getRoomMessages(roomId)` — initial history
- `sendRoomMessage(roomId, userId, userName, text, imageUrl?, replyToId?)`
- `deleteRoomMessage(roomId, messageId, userId)`
- `editRoomMessage(roomId, messageId, userId, text)`
- `toggleRoomReaction(roomId, messageId, userId, emoji)`
- `supabase.channel('room_messages:' + roomId)` — Realtime INSERT/UPDATE
- `supabase.channel('presence:room:' + roomId)` — typing presence

---

## 5. Components involved

| Component | Role |
|---|---|
| `RoomList` | Sidebar: rooms + create/join + "My School" entry |
| `RoomOverview` | Overview tab with comparison graph and AI summary |
| `RoomChat` | Realtime chat with reactions/mentions/reply/edit |
| `RoomMembers` | Members list + kick/leave actions |
| `StudyMatch` | Study-partner matching UI |
| `SchoolDirectory` | Read-only student directory |
| `KnowledgeGraph` | Embedded inside `RoomOverview` with `comparison` prop |
| `Avatar` | Member avatars throughout |

---

## 6. Edge cases

1. **Own-message suppression** on Realtime INSERT — avoids double-render from optimistic + subscription echo. Correct but brittle; if `userId` is misread from the Realtime payload, duplicates appear.
2. **Image attachments are data URLs.** Large images bloat the message payload and the DB. Rebuild should upload to Supabase Storage (the same bucket `ReportIssueFlow` uses) and send the public URL.
3. **Presence is not cleaned up on route leave** — the channel's `track` state persists server-side briefly. Supabase auto-expires presence when the channel closes, which happens in the effect cleanup (`supabase.removeChannel(ch)`). Verify in Phase 4.
4. **No message pagination.** `getRoomMessages(roomId)` returns everything. For large rooms this will blow up the client.
5. **@mention regex** (`@(\w*)$`) only works at the end of the text. Typing `@Alice and @Bo` → second mention detection fires when cursor is after `@Bo`, which is fine. But user names with spaces or special chars won't match — the regex in `renderText` escapes metachars but `@(\w*)$` in input still only picks word chars. Known limitation.
6. **Typing indicators timeout at 3s** — if a user pauses, "typing" disappears even if they come back. Standard UX.
7. **Emoji picker is static 50-emoji grid** — no search, no skin tones, no "frequently used". Acceptable for now.
8. **Comparison outline rings apply only when a comparison partner is selected.** Switching `compareWith` recomputes `getComparisonOutlineColor` per node in `KnowledgeGraph`.
9. **`leaveRoom` client-state** (in social page's `handleLeaveRoom`) filters the room out locally *before* the API call. If the call fails, the room disappears from the UI but not the server. Rare.
10. **Kick-member confirm state** is one-at-a-time (`confirmKickId: string | null`). Opening another kick confirm closes the first. Fine.

---

## 7. Interactive patterns

| Pattern | Impl |
|---|---|
| Supabase Realtime `postgres_changes` subscriptions | `supabase.channel(...).on('postgres_changes', filter, handler)` |
| Supabase presence | `channel.track({typing})` + `presenceState()` |
| Optimistic mutations with rollback | tempId messages removed on error |
| @mention autocomplete with keyboard navigation | Arrow/Tab/Enter/Escape handling |
| Reply to message | Reply snippet above textarea; `reply_to_id` in send payload |
| Message edit | Drops the reply; pre-fills textarea; `editRoomMessage` on send |
| Soft-delete messages | UPDATE event with `is_deleted=true`; UI shows "Message deleted" |
| Emoji reactions | 50-emoji grid + `toggleRoomReaction` |
| Image attachment | FileReader → data URL (not Storage) |
| Typing indicator | Presence channel + 3s debounce |
| 2-step kick/leave confirm | `confirmKickId`, `confirmLeave` state |
| Comparison graph outline colors | `getComparisonOutlineColor` inside `KnowledgeGraph` |
| 50-emoji picker grid | Static array |
| Invite code Copy button with "Copied!" flash (2s) | `setTimeout` state toggle |

---

## 8. Things to preserve in the rebuild

- Supabase Realtime-based chat (the backend doesn't mediate chat traffic — too latency-sensitive).
- Presence-driven typing indicators with a 3s idle timeout.
- Optimistic UI for sends + reactions + soft-delete.
- @mention with Arrow/Tab/Enter/Escape.
- Reply-with-snippet, Edit, Delete, Reactions.
- The 4-color comparison outline ring on the shared-knowledge graph.
- Invite-code-based join flow with "Copied!" affordance.
- Two-step kick/leave confirms.
- School-wide directory as a read-only discovery surface.

## 9. Things to rework

- Upload images to Supabase Storage (`issues-media-files` or a dedicated bucket) instead of data URLs in message text.
- Paginate message history.
- Replace the 50-emoji grid with a searchable picker (or use `emoji-mart`).
- Consider pushing `postgres_changes` subscription state into a hook (`useRoomChannel`) to make testing easier.

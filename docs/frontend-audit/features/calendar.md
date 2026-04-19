# Feature · Calendar

> Covers: `/calendar/page.tsx` + `AssignmentTable.tsx` + Google Calendar sync + `DocumentUploadModal` syllabus side-effect.

---

## 1. Overview

Calendar surfaces the user's upcoming assignments across courses. Three views (month/week/day) with per-type color coding. Integrated with Google Calendar: connect, sync out (export), import back, disconnect.

Top bar: back arrow, title, sync buttons. Body: `CalendarGrid` with view switcher. Sidebar (or below on mobile): `AssignmentTable` (editable) + upload syllabus button.

---

## 2. User flows

### 2.1 Flow: load + view switch

- Mount: fetch `getAllAssignments`, `getCalendarStatus`, `getCourses` in parallel (`calendar/page.tsx:332-343`).
- Assignments normalized via `normalizeAssignments` (defaults missing fields — `id` falls back to `missing-id-${index}`).
- `CalendarGrid` owns `view` (`'month' | 'week' | 'day'`) and `current` date.
- View switcher buttons (pill-style) toggle `view`.
- `current` navigates via prev/next arrows; "Today" resets.

**`current` starts null** for SSR consistency; then a mount effect sets it to `new Date()` (`calendar/page.tsx:74-80`). Without this, calendar output would differ between server and client render.

### 2.2 Flow: display assignments on the grid

- Assignments are bucketed by `due_date` (YYYY-MM-DD prefix).
- Each cell renders up to N `AssignmentChip`s (tooltip = `${a.title} — ${a.course_name}\n${a.notes}`).
- Color coding by `assignment_type` (`exam` / `project` / `homework` / `quiz` / `reading` / `other`) — `TYPE_COLORS` map at `page.tsx:23-30`.

### 2.3 Flow: Google Calendar OAuth

1. User clicks "Connect Google Calendar" (somewhere in the header).
2. Frontend calls `getCalendarAuthUrl(userId)` → redirect to Google.
3. Google redirects back to backend, which redirects to `/calendar?connected=true`.
4. Mount effect detects `?connected=true` → `setGoogleConnected(true)` (`page.tsx:346-350`).

### 2.4 Flow: sync out (export to Google)

- `handleSync()` → `syncToGoogleCalendar(userId)` → `{synced_count}`. Sets `syncedCount`. Refetches assignments so newly-set `google_event_id` values appear.
- "Sync N events" feedback shown inline.

### 2.5 Flow: import from Google

- `handleImportGoogle()` → `importGoogleEvents(userId, 60)` (60 days ahead). Stores in `googleEvents` (not assignments — imported events are displayed separately). Alert on error.

### 2.6 Flow: disconnect Google

- `handleDisconnectGoogle()` uses `window.confirm` ("Disconnect from Google Calendar? Synced events will not be removed.") — native browser confirm dialog.
- On confirm: `disconnectGoogleCalendar(userId)` → clears local Google state.
- Alert on error.

### 2.7 Flow: upload syllabus from Calendar

- "Upload syllabus" button opens `DocumentUploadModal`.
- `handleUploadClose(uploaded)` (`page.tsx:357-364`): if any uploaded doc has `category === 'syllabus'`, `refreshAssignments()` immediately and again after 1.5s (insert race).
- The uploaded syllabus's AI-extracted assignments appear in the grid.

### 2.8 Flow: `AssignmentTable` editing

`AssignmentTable.tsx` (319 lines) supports:

- **Sort**: by `Manual order` (default), `Due date`, `Course`, `Title`, `Type`. Only Manual order allows drag reorder.
- **Drag reorder** (when `sortKey === 'custom'`): HTML5 drag-and-drop; `draggingIndex` state.
- **Inline edit**: double-click or click to edit `title`/`course_name`/`due_date`/`assignment_type`/`notes`. Changes propagate via `onChange(updated)`.
- **Add row**: button appends a blank `Assignment` with a temp ID (`temp_${Date.now()}`).
- **Delete row**: trash icon.
- **"Due soon" badge**: derived from `isDueSoon(dueDate)` — within 24 hours.
- **Multi-select**: `selectedIds?` + `onToggleSelect?` props drive a checkbox column. Used by the sync-to-Google flow to select which to export.

`saveAssignments(userId, assignments)` persists user edits (`POST /api/calendar/save`). `exportToGoogleCalendar(userId, ids)` sends a subset.

---

## 3. State

`CalendarGrid`:
- `view`: `'month'|'week'|'day'`
- `current: Date | null`
- `today: string`

`CalendarInner`:
- `assignments`, `googleEvents`
- `syncing`, `syncedCount`, `googleConnected`, `importingGoogle`
- `courses`
- `showUpload`

`AssignmentTable`:
- `sortKey`, `sortDirection`
- `draggingIndex`

---

## 4. API calls

- `getAllAssignments(userId)` → `GET /api/calendar/all/:userId`
- `getUpcomingAssignments(userId)` → `GET /api/calendar/upcoming/:userId` (used by Dashboard, not here)
- `getCalendarStatus(userId)` → `GET /api/calendar/status/:userId`
- `getCalendarAuthUrl(userId)` → `GET /api/calendar/auth-url?user_id=` (starts OAuth)
- `syncToGoogleCalendar(userId)` → `POST /api/calendar/sync`
- `exportToGoogleCalendar(userId, ids)` → `POST /api/calendar/export`
- `importGoogleEvents(userId, days)` → `GET /api/calendar/import/:userId?days_ahead=`
- `disconnectGoogleCalendar(userId)` → `DELETE /api/calendar/disconnect/:userId`
- `saveAssignments(userId, assignments[])` → `POST /api/calendar/save`
- `extractSyllabus(formData, userId)` → `POST /api/calendar/extract` (used internally by the upload flow? — confirm in Phase 4)

---

## 5. Components involved

- `CalendarGrid` (inline in `page.tsx`)
- `AssignmentChip` (inline)
- `AssignmentTable`
- `DocumentUploadModal`

---

## 6. Edge cases

1. **`?connected=true` is never cleared from the URL** after processing. Refreshing repeats the side-effect. Low-stakes since setting `googleConnected=true` twice is harmless.
2. **`window.confirm` for disconnect** — blocks the main thread and is inaccessible. Replace with a styled modal in the rebuild.
3. **`alert()` for error surfacing** — use `useToast` instead.
4. **`missing-id-${index}` fallback** (`normalizeAssignments`) — if the backend ever omits an id, React keys become unstable on reorder. Flag, not urgent.
5. **Syllabus upload refetch races** — mitigated with a 1.5s delayed refetch; good-enough hack.
6. **Import-from-Google shows events but doesn't convert them to assignments** — `googleEvents` is a separate list. Unclear if the UI surfaces a "promote to assignment" action — to check in Phase 4.
7. **Timezone handling** — assignments use YYYY-MM-DD strings; `CalendarGrid` uses local Date math. A user traveling across time zones may see off-by-one due dates. Not fixed in current code.

---

## 7. Interactive patterns

- Month/week/day view switcher.
- Prev / next / Today navigation on the grid header.
- Drag-and-drop row reordering (Manual order only).
- Inline editing (text inputs styled to look like plain text until focused).
- Bulk select + export to Google.

---

## 8. Things to preserve in the rebuild

- Three views (month/week/day) with per-type color coding.
- Google Calendar integration (connect / sync-out / import / disconnect).
- `?connected=true` redirect target for OAuth success.
- Syllabus upload refreshes the calendar automatically.
- Editable `AssignmentTable` with drag-reorder in Manual order mode.
- "Due soon" 24-hour badge.

## 9. Things to rework

- Replace `window.confirm` / `alert` with Toasts + styled modals.
- Import-from-Google flow needs clearer UX (currently a side list with no obvious next step).
- Timezone-safe date math.
- Clear `?connected=true` after processing.

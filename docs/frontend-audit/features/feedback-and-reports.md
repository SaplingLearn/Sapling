# Feature · Feedback & Issue Reporting

> Covers: `FeedbackFlow.tsx` (global periodic feedback), `SessionFeedbackFlow.tsx` (post-session feedback), `SessionFeedbackGlobal.tsx` (navigate-away trigger), `ReportIssueFlow.tsx` (user-initiated bug reports). `FeedbackFlow` and `SessionFeedbackGlobal` are mounted in the root layout and run everywhere.

---

## 1. Overview

Four related surfaces, all using the same `POST /api/feedback` or `POST /api/issue-reports` contracts:

| Surface | Trigger | Mounted | Cooldown |
|---|---|---|---|
| `FeedbackFlow` | 45s after page mount, any route | Root layout via `Suspense` | 3 days (localStorage) |
| `SessionFeedbackFlow` | (a) every 5th `endSession()` in `/learn`, (b) navigate-away from `/learn` | Used inline by `/learn` + globally via `SessionFeedbackGlobal` | Navigate-away: 3 days (localStorage) |
| `SessionFeedbackGlobal` | Wraps `SessionFeedbackFlow`, detects `/learn → elsewhere` navigation | Root layout | 3 days |
| `ReportIssueFlow` | Triggered by the Navbar "Report issue" link | Navbar (on-demand) | n/a — user-initiated |

Only `/learn` populates the `sapling_learn_had_session` flag, so `SessionFeedbackGlobal` only fires when the user has actually held a Learn session before leaving.

---

## 2. User flows

### 2.1 Flow: passive global feedback (`FeedbackFlow`)

Source: `src/components/FeedbackFlow.tsx`.

- Mount effect: if `?testFeedback=global` — show immediately (QA escape hatch). Else read `localStorage.sapling_feedback_last_shown`; if `<3 days` ago, skip. Otherwise set a 45-second `setTimeout` to show.
- Slide-up bottom-right card (matches `SessionFeedbackFlow` visually).
- Steps:
  1. **Emoji rating** (5 emojis: Frustrated / Unhappy / Neutral / Good / Loving it).
  2. **Improvement options** (7 choices, plural checkbox). Options include: "AI explanations could be clearer", "Navigation is confusing", "Missing features I need", "Knowledge graph is hard to read", "Quiz difficulty feels off", "Performance / loading is slow", "Something else".
  3. **Optional comment** (textarea). Submit button.
  4. **Submitted** state: auto-dismiss after 1800ms.
- `submitFeedback({user_id, type:'global', rating, selected_options, comment})`. Fire-and-forget.
- Stamps `localStorage.sapling_feedback_last_shown = Date.now()` on dismiss/submit.

### 2.2 Flow: post-session feedback (every 5 sessions) — see `features/learn.md` §2.7

### 2.3 Flow: navigate-away feedback — see `features/learn.md` §2.9

### 2.4 Flow: report issue (`ReportIssueFlow`)

Source: `src/components/ReportIssueFlow.tsx`.

- Triggered by Navbar "Report issue" button.
- Three-step full-screen modal (backdrop + center panel):
  1. **Topics**: 9 one-topic radio options (`AI / Learning Assistant`, `Library / Resources`, `Study Tools`, `Calendar`, `Social / Rooms`, `Account / Profile`, `Performance / Speed`, `UI / Display`, `Other`). Only one selectable at a time (`checked: string | null`).
  2. **Details**: description textarea + up to 5 screenshot attachments (drag / pick, previews with remove X).
  3. **Done**: thank-you, auto-dismiss after 2000ms.
- On submit:
  - Uploads each screenshot to Supabase Storage bucket `issues-media-files` with path `${userId}/${timestamp}_${random}.{ext}`.
  - Collects public URLs via `supabase.storage.from(...).getPublicUrl(path)`.
  - `submitIssueReport({user_id, topic, description, screenshot_urls})`. Fire-and-forget (`.catch(() => {})`).
- Upload errors are `console.error`'d — not surfaced.

Screenshots go **directly to Supabase Storage from the browser**, using the anon key. This is the only place in the app that writes to Storage client-side.

---

## 3. State

### `FeedbackFlow`
- `visible`, `closing` — animation state
- `step`: `1 | 2 | 3`
- `rating`, `checked: Set<string>`, `comment`
- `submitted`, `hovered`

### `SessionFeedbackFlow` — see `features/learn.md` §2.8

### `SessionFeedbackGlobal`
- `visible`
- `prevPathname` ref

### `ReportIssueFlow`
- `step`: `'topics' | 'details' | 'done'`
- `checked` (topic)
- `comment`, `screenshots: File[]`, `screenshotPreviews: string[]`, `screenshotTypes: string[]`
- `closing`, `submitting`

---

## 4. API calls

- `submitFeedback({user_id, type: 'global' | 'session', rating, selected_options, comment?, session_id?, topic?})` → `POST /api/feedback`.
- `submitIssueReport({user_id, topic, description, screenshot_urls})` → `POST /api/issue-reports`.
- `supabase.storage.from('issues-media-files').upload(path, file)` — screenshot upload.
- `supabase.storage.from('issues-media-files').getPublicUrl(path)` — public URL.

---

## 5. Components involved

- `FeedbackFlow` — global passive card
- `SessionFeedbackFlow` — post-session card (used by both `/learn` and `SessionFeedbackGlobal`)
- `SessionFeedbackGlobal` — route-change watcher wrapping `SessionFeedbackFlow`
- `ReportIssueFlow` — full-screen issue modal
- `Navbar` - opens `ReportIssueFlow`

---

## 6. Edge cases

1. **Three feedback surfaces share localStorage keys**:
   - `sapling_feedback_last_shown` (FeedbackFlow)
   - `sapling_session_end_count` (every-5-sessions)
   - `sapling_learn_had_session`, `sapling_session_feedback_nav_last_shown` (navigate-away)
   Each has its own 3-day cooldown (in different units: days vs ms — same outcome).
2. **All submissions are fire-and-forget** (`.catch(() => {})`). A failed backend means lost feedback.
3. **Screenshot upload** doesn't handle Supabase auth — uses anon key, uploads succeed if bucket policy allows anonymous writes. Verify bucket config.
4. **`?testFeedback=global` / `?testFeedback=session`** are QA backdoors — the rebuild can keep them or remove them.
5. **Mobile responsiveness** — bottom-right 340px fixed card may be too wide for narrow screens. (Not yet audited visually.)
6. **`SessionFeedbackGlobal` + inline `/learn` SessionFeedbackFlow both render**. The inline one is only visible on `/learn` when conditions match; the global one is always mounted but `visible=false` until triggered. No duplicate firing risk because they track different state.
7. **`ReportIssueFlow` uploads synchronously, one at a time, in a `for` loop**. For 5 large files this serializes — rebuild can parallelize.

---

## 7. Interactive patterns

- Slide-up bottom-right toast card with `@keyframes sfSlideUp/Down` (shared animation vocabulary across both feedback flows).
- Emoji row with hover scale.
- Checkbox/toggle list with custom-drawn checkmarks (inline SVG).
- Auto-dismiss "Thanks!" step with success emoji (🌱 / 🙏).
- Full-screen modal with backdrop click-to-dismiss for `ReportIssueFlow`.
- Drag-and-drop / file picker for screenshots with previews.

---

## 8. Things to preserve in the rebuild

- Three-tier feedback system (passive periodic + session-specific + navigate-away).
- 3-day cooldowns on passive and navigate-away triggers (tunable but keep the concept).
- 45-second delay before showing passive feedback (don't nag instantly).
- Emoji-based rating for quick captures.
- Multi-checkbox improvement-area selection + free-text comment.
- Issue-report topic routing + up to 5 screenshot attachments → Supabase Storage.
- `?testFeedback=global|session` dev override.

## 9. Things to rework

- Surface submission errors with a retry instead of swallowing them.
- Parallelize screenshot uploads.
- Consider a single unified feedback store instead of four localStorage keys.

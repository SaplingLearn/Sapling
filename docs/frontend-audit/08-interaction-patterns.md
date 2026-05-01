# Sapling Frontend Audit — 08 · Interaction Patterns

> Cross-cutting interaction primitives: modals, toasts, tooltips, dropdowns, drag-and-drop, keyboard shortcuts, loading states, animations. Consolidated so the rebuild can implement each one coherently.

---

## 1. Modals

### 1.1 Standard centered modal

Used by: `SessionSummary`, `DocumentUploadModal`, Dashboard "Manage Courses", `DisclaimerModal`, `StudyMatch` best-match popup.

Pattern:
- Fixed-position backdrop: `rgba(0,0,0,0.40)` or `.45`. Click-to-close via `onClick={e => { if (e.target === e.currentTarget) close() }}`.
- Center-aligned content card: rounded corners (`border-radius: 12-14px`), `box-shadow: 0 20px 60px rgba(0,0,0,0.15)` or `0 24px 64px`.
- Width 440–520px, `max-width: 95vw`, `max-height: 80–88vh`, `overflow-y: auto`.
- Close button top-right (either `✕` text or `<X>` Lucide).

`DisclaimerModal` and `ToastProvider`'s toasts are the only modals that use `createPortal`. Others render in-tree.

**Inconsistencies**:
- Close button style / placement varies (position, size, icon).
- Some modals disable backdrop close during loading (`DocumentUploadModal`'s `hasActiveUploads` guard, `/learn` Quiz while `loading`).
- No consistent focus trap / focus restore.
- No consistent `role="dialog"` / `aria-modal`.

### 1.2 Bottom-right card modals

Used by: `FeedbackFlow`, `SessionFeedbackFlow`, `ToastProvider` toasts.

Pattern:
- `position: fixed; bottom: 28px; right: 28px; width: 340px` (feedback cards) or `top: 60px; right: 16px` (toasts).
- `@keyframes sfSlideUp/Down` CSS entrance + exit.
- Z-index 9998 (feedback) or 9999 (toasts).

### 1.3 Full-viewport overlay

Used by: `OnboardingFlow` (landing), `/dashboard` graph fullscreen, `/flashcards` / `/study` flashcard study mode.

Pattern:
- `position: fixed; inset: 0` (or `position: fixed; top:0; left:0; width:100vw`).
- `document.body.style.overflow = 'hidden'` during lifetime (Dashboard fullscreen only — not all).
- Escape key exits (Dashboard fullscreen, `OnboardingFlow`).

---

## 2. Toasts

Single implementation: `ToastProvider` + `useToast()`. Covered in `02-components.md §6`.

- Auto-dismiss after 5000ms (default).
- Manual dismiss via `×` button.
- Content is `ReactNode` — richer than text.
- Top-right stack via `createPortal`.

Inconsistency: some features use `window.alert()` or inline error banners instead (`/calendar` disconnect, `/calendar` sync errors). Rebuild should standardize on Toast.

---

## 3. Tooltips

No dedicated tooltip component. Three styles coexist:

- **Hover card** (`ModeSelector`, `AIDisclaimerChip`, `SharedContextToggle`): absolute-positioned div, `pointer-events: none`, fixed width (240–290px), gradient/glass background. Not accessible via keyboard.
- **`title` attribute** — native browser tooltip. Used by `AssignmentChip` hover, `RoleBadge` description, emoji buttons in `SessionFeedbackFlow`.
- **In-graph tooltip** (`KnowledgeGraph`) — custom div positioned via `event.clientX/Y`, shown on `mouseover`, hidden on `mouseout`.

Rebuild should standardize on one accessible tooltip primitive (e.g., Radix `Tooltip`).

---

## 4. Dropdowns & selects

### 4.1 `CustomSelect`

Primary dropdown component. Portal-rendered; supports upward open, delete-per-item, compact variant. Used in 10+ places. Preserve.

### 4.2 Native `<select>`

Used in `/admin` (category / rarity / type selectors). Inconsistent with the rest of the app — rebuild should migrate to `CustomSelect`.

### 4.3 Autocomplete/typeahead

Used by:
- `OnboardingFlow` (majors / minors / courses).
- `/dashboard` manage-courses modal (courses).
- `RoomChat` (`@mentions`).

All three implement their own dropdown with `onBlur`-delayed-close pattern (to allow `onMouseDown` on options to fire first, 150ms). Keyboard support varies: `RoomChat` has Arrow/Tab/Enter/Escape; the others are mouse-only.

Rebuild should extract a shared autocomplete primitive with full keyboard support.

---

## 5. Drag-and-drop

- **File drops**: `UploadZone` (dead), `DocumentUploadModal` (pick step), `ReportIssueFlow` (screenshots).
- **Row reorder**: `AssignmentTable` (HTML5 drag events, Manual-order only).
- **Graph nodes**: `KnowledgeGraph` supports drag via `d3.drag`.

All use native HTML5 drag events (not `react-dnd` or `@dnd-kit`).

---

## 6. Keyboard shortcuts

| Scope | Key | Action |
|---|---|---|
| Global | Escape (in Dashboard fullscreen graph) | Exit fullscreen |
| Global | Escape (`OnboardingFlow`) | Close onboarding |
| Global | Escape (Navbar menu) | Close user menu |
| Global | Escape (Navbar mobile nav) | Close nav |
| `ChatPanel` | Enter | Send message |
| `ChatPanel` | Shift+Enter | Newline |
| `RoomChat` | Enter | Send message |
| `RoomChat` | Shift+Enter | Newline |
| `RoomChat` (mention menu open) | ArrowUp / ArrowDown | Navigate mention suggestions |
| `RoomChat` (mention menu open) | Tab / Enter | Insert selected mention |
| `RoomChat` (mention menu open) | Escape | Dismiss mention menu |
| `OnboardingFlow` dropdowns | Enter / Space | Select option |
| Add-course in `DocumentUploadModal` | Enter | Submit add-course |

**Missing**:
- No flashcard shortcuts (Space to flip, 1/2/3 to rate).
- No quiz shortcuts (A/B/C/D to select option, Enter to submit).
- No `/` to focus the search in `/tree`.
- No global keyboard nav between tabs.

Rebuild should be more generous here.

---

## 7. Confirmations

Two patterns:

### 7.1 Two-step button confirm

- First press: flips state to `confirm...` mode, button text changes to Cancel / Confirm.
- Second press on Confirm: executes.
- Pressing Cancel or clicking away resets.

Used for: delete course (Dashboard modal), delete flashcard (✕ hover gated), delete document (Library), kick member / leave room (Social), delete chat message (soft, via context menu), delete session (via `CustomSelect.onDelete` — implicit single-click, maybe needs a confirm in rebuild).

### 7.2 Typed phrase confirm

- Dangerous actions require typing a specific word.
- Only use: `/settings` Delete Account requires typing "DELETE".

### 7.3 Native `window.confirm`

Used once in `/calendar` for disconnect. Inaccessible and jarring. Replace with typed confirm or two-step button in the rebuild.

---

## 8. Copy-to-clipboard

Pattern:
- `navigator.clipboard.writeText(value)`.
- Flip local state to `copied = true`; revert after 2000ms.
- Button label changes to "Copied!".

Used by: `RoomList` newly-created invite code, `RoomOverview` invite code, probably admin IDs (not verified).

---

## 9. Loading states

Standard page-level loading:

- Plain text "Loading your dashboard…" / "Loading settings…" / "Loading achievements…".
- Centered, gray (`#9ca3af`).
- Full-height container.

Spinner: inline `@keyframes spin` + CSS border trick (32×32 px, 2px borders) — used by `StudyClient` guide loading and a few others.

Skeletons: **none**. Every loading state is a spinner or a dim text line.

Rebuild opportunity: add skeleton placeholders for card grids.

---

## 10. Empty states

Consistent visual: centered text with large emoji (`🃏 No flashcards yet`, etc.), fontSize 13–14px gray, plus an instruction ("Generate some using the panel on the left.").

Inconsistency: some empty states are just text, some have emoji, some have a CTA button.

---

## 11. Error states

Per-feature patterns:
- **Full-page error** (Dashboard, Social overview): centered card with title + message + Retry button.
- **Inline banner** (Learn session error): red bordered banner above the content.
- **Toast** (most mutations via `useToast`).
- **`alert()`** (Calendar disconnect / sync errors — out of style).
- **Silent `console.error`** (Navbar recommendations, Chat send failures, many).

Standardize on Toast + inline banner in the rebuild.

---

## 12. Animations

| Animation | Implementation |
|---|---|
| Panel slide-in (Dashboard, Learn, Calendar, Social left panels) | `.panel-in` + `.panel-in-1/2/3` CSS classes (in `globals.css`) |
| Bottom-right card slide-up / slide-down | `@keyframes sfSlideUp/Down` inline in component |
| Flip card | CSS `perspective` + `transform: rotateY` + `backface-visibility: hidden` |
| KnowledgeGraph drift | RAF loop with per-node sin/cos |
| KnowledgeGraph node entry | D3 `.transition().duration(400)` on opacity |
| KnowledgeGraph tier change | D3 `.transition().duration(500)` on fill-opacity |
| Typewriter greeting | `setInterval(55ms)` appending chars |
| Blinking cursor | `setInterval(530ms)` toggling visibility |
| Scramble text (landing — OOS) | Custom char-by-char randomization |
| Onboarding step card entrance | CSS `@keyframes ob-card-in` (0.38s cubic-bezier) |
| Toast enter | `.toast-enter` class (defined in globals.css, not confirmed) |
| Spinner | Inline `@keyframes spin` |

Rebuild: consolidate animations into a shared Motion primitive (Framer Motion / Motion One) or keep handwritten keyframes. Either way, document the duration tokens (300ms, 400ms, 500ms, 0.55s, etc.) as CSS variables (`--dur-fast`, `--dur-base`) so they're editable in one place.

---

## 13. Accessibility gaps (noted across all features)

Consolidated list:

- No focus trap on modals. No focus restore on close.
- `role="dialog"` / `aria-modal` / `aria-labelledby` missing on most modals.
- Tooltips with `pointer-events: none` are not keyboard-reachable.
- `ChatPanel` / `RoomChat` message containers lack `role="log"` / `aria-live`.
- Native `window.confirm` / `alert` used in `/calendar`.
- Quiz options lack `role="radiogroup"` / `role="radio"`.
- Drag-and-drop has no keyboard alternative.
- Some icon-only buttons lack `aria-label` (e.g., some `×` close buttons on the onboarding flow).
- No skip-to-content link.
- Color contrast not explicitly audited; several muted-text colors may fail AA.
- No live region for the typewriter greeting or step-change in `OnboardingFlow`.

Rebuild should audit with axe / Lighthouse and close these gaps systematically.

---

## 14. Responsive behavior — summary

Breakpoint: **768px** (hardcoded in every inline `useIsMobile` hook).

- Above 768: desktop layouts with side panels, wide grids.
- Below 768: stacked layouts, collapsible tabs, bottom-sheet panels in place of side sheets, hamburger nav.

No true "tablet" breakpoint. No landscape-vs-portrait handling.

---

## 15. Notable one-offs

- **Dashboard**: typewriter greeting, random quote, blinking cursor, Monday-first weekly streak strip with 🔥 emoji dots.
- **Learn**: markdown+KaTeX in chat bubbles; prefill input after mode switch.
- **Social**: reply-to snippet preview above textarea.
- **KnowledgeGraph**: drift animation + comparison outline rings.
- **Settings**: double-RAF pattern to mount-then-animate the profile preview modal.

Don't lose these polish details in the rebuild — they're the personality of the product.

---

## 16. Things to preserve

- Standardized toast system via `useToast`.
- Two-step delete confirms for irreversible-ish actions.
- Typed-phrase confirm for the nuclear option (account deletion).
- Copy-to-clipboard with 2s "Copied!" flash.
- Body scroll-lock on full-viewport overlays.
- Portal-rendered tooltips/dropdowns/toasts escaping overflow-hidden containers.

## 17. Things to rework

- Standardize modal chrome (close button, backdrop behavior, focus trap).
- Standardize tooltip (accessible, keyboard-reachable).
- Replace every `alert()` and `window.confirm` with in-app affordances.
- Add keyboard shortcuts to flashcards (Space/1/2/3), quiz (A–D + Enter), and search (`/`).
- Add skeleton loading states for card grids.
- Consolidate empty-state vocabulary.

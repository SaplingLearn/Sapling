# Frontend `data-testid` convention

Browser tests (Playwright, #385) must anchor on `data-testid`. They must **not**
anchor on CSS classes or copy: the app is mid-redesign, classes are utility-ish
(`btn btn--primary btn--sm`) and non-unique, and every copy tweak would break a
selector. `data-testid` is the one attribute that exists purely as a test
contract and can be kept stable across visual churn.

Introduced by #382. Scope today is the six surfaces the Chapter-1 regression
suite drives, plus the authed app-shell anchor added with the Playwright
harness (#385); this is deliberately **not** a whole-app sweep.

## Naming

Kebab-case, `<surface>-<element>`:

```
signin-google-button
pending-gate
upload-modal-dropzone
tutor-input
tutor-send
quiz-answer-option-A
graph-container
```

Rules:

1. **Surface prefix first.** One prefix per surface (`signin`, `pending`,
   `upload-modal`, `tutor`, `quiz`, `graph`). The prefix names the user-facing
   surface, not the React component — `tutor-input` lives in `ChatPanel.tsx`
   because that is where the tutor composer renders.
2. **Element name describes the role, not the markup or the copy.**
   `quiz-submit-answer`, not `quiz-primary-btn` and not `quiz-submit-answer-button`
   for a `<button>`. Suffix with `-button` / `-input` only when it disambiguates
   (`signin-google-button` vs. the `signin-trigger` on the landing nav).
3. **Container roots get a bare noun**: `signin-modal`, `upload-modal`,
   `quiz-panel`, `graph-container`, `pending-gate`.
4. **Lowercase and hyphens only**, except for a stable id suffix (below).
5. **Stable across redesigns.** A testid is API. Renaming one is a breaking
   change to the browser suite — do it in the same PR as the test update.

## Repeated / list items

A repeated element gets the base name plus a suffix. Pick, in order of
preference:

1. **A stable domain id** the test can predict or read from the payload.
   Quiz answers use the option's own label (`A`/`B`/`C`/`D`), so:
   `quiz-answer-option-${o.label}` → `quiz-answer-option-A`. Catalog courses use
   the catalog id: `upload-modal-course-result-${c.id}`.
2. **A render index** when there is no stable id worth exposing. Upload rows key
   on the queue position: `upload-modal-file-row-${idx}`,
   `upload-modal-file-remove-${idx}`.

Never suffix with a user-visible string (file name, course title, question
text) — that is copy-anchoring by another route.

When a list needs a "the whole list" handle, add a plural container testid next
to the items: `quiz-answer-options` wraps `quiz-answer-option-*`.

## Where the testids live

The surface prefix is a UX concept; the attribute goes on the file that actually
renders the element.

| Surface | Prefix | Owning file(s) |
| --- | --- | --- |
| Sign-in | `signin` | `frontend/src/components/SignInModal.tsx` (+ the trigger in `src/app/(public)/page.tsx`) |
| Approval gate | `pending` | `frontend/src/app/pending/page.tsx` |
| Upload modal | `upload-modal` | `frontend/src/components/DocumentUploadModal.tsx` |
| Tutor | `tutor` | `frontend/src/components/ChatPanel.tsx` (rendered by `screens/Learn.tsx`) |
| Quiz | `quiz` | `frontend/src/components/QuizPanel.tsx` (rendered by `screens/Quiz.tsx`) |
| Knowledge graph | `graph` | `frontend/src/components/KnowledgeGraph.tsx` (wrapper only — not the 2D/3D internals) |
| App shell | `app` | `frontend/src/components/ShellFrame.tsx` (the authed layout frame every `(shell)` route renders inside) |
| Study rooms | `social` | `frontend/src/components/screens/Social.tsx` (rooms sidebar, chat, overview, study match, directory — added with the #394 two-context journey) |

Two surfaces do **not** carry their testids in the screen file named by the
route:

- **Tutor.** `screens/Learn.tsx` passes `onSend` to `ChatPanel`; the `<textarea>`
  and the send `<button>` render in `ChatPanel.tsx`. `ChatPanel` has exactly one
  consumer (Learn), so tagging it there is unambiguous. The notetaker's chat is
  a separate `AIChatPanel` and is out of scope.
- **Quiz.** `screens/Quiz.tsx` only fetches concepts and mounts `QuizPanel`;
  every answer/submit control renders in `QuizPanel.tsx`.

## Current inventory

### `signin`

| testid | element |
| --- | --- |
| `signin-trigger` | landing-nav "Sign In" button that opens the modal |
| `signin-modal` | modal panel root (`role="dialog"`) |
| `signin-close` | × close button |
| `signin-google-button` | "Continue with Google" |
| `signin-cancel` | "Cancel" (only while waiting on the popup) |
| `signin-error` | error banner |

### `pending`

| testid | element |
| --- | --- |
| `pending-gate` | approval-gate page root |
| `pending-signout` | "Sign out" |

### `upload-modal`

| testid | element |
| --- | --- |
| `upload-modal` | modal card root |
| `upload-modal-close` | header × |
| `upload-modal-dropzone` | drag & drop target |
| `upload-modal-browse` | "Browse" label wrapping the file input |
| `upload-modal-file-input` | the hidden `<input type="file">` (use `setInputFiles`) |
| `upload-modal-course-search` | "+ Add a course" search input |
| `upload-modal-course-result-{courseId}` | a course search result |
| `upload-modal-file-row-{idx}` | a queued file row |
| `upload-modal-file-remove-{idx}` | remove that row |
| `upload-modal-file-reanalyze-{idx}` | "Re-analyze" (processed rows) |
| `upload-modal-file-retry-{idx}` | "Retry" (error/aborted rows) |
| `upload-modal-file-copy-request-id-{idx}` | "copy" the support reference |
| `upload-modal-cancel` | footer "Cancel" |
| `upload-modal-submit` | footer "Start upload" |
| `upload-modal-done` | footer "Done" (replaces submit once every row finished) |

### `tutor`

| testid | element |
| --- | --- |
| `tutor-messages` | conversation log (`role="log"`) |
| `tutor-input` | message `<textarea>` |
| `tutor-send` | send button |
| `tutor-action-hint` | "Hint" |
| `tutor-action-confused` | "I'm confused" |
| `tutor-action-skip` | "Skip" |

### `quiz`

| testid | element |
| --- | --- |
| `quiz-panel` | panel root (all phases) |
| `quiz-cancel` | "Cancel" (select phase) |
| `quiz-start` | "Start quiz" |
| `quiz-answer-options` | answer radiogroup |
| `quiz-answer-option-{label}` | one answer choice, suffixed with its label (`A`…) |
| `quiz-submit-answer` | "Submit answer" |
| `quiz-exit` | "Exit" (active phase) |
| `quiz-review-verdict` | "Correct." / "Not quite." banner |
| `quiz-explain-concept` | "Explain this" |
| `quiz-next` | "Next question" / "See results" |
| `quiz-results-score` | the score percentage |
| `quiz-retake` | "Retake" |
| `quiz-done` | "Done" |

### `graph`

| testid | element |
| --- | --- |
| `graph-container` | graph wrapper root (sized box holding 2D or 3D) |
| `graph-mode-toggle` | 2D ⇄ 3D toggle |

### `app`

| testid | element |
| --- | --- |
| `app-shell` | authed shell root — the scrolling `<main id="main-content">` in `ShellFrame.tsx`, present in both (top-nav and sidebar) layout variants; the Playwright harness smoke spec (#385) anchors on it as the "authed shell mounted" signal |

### `social`

| testid | element |
| --- | --- |
| `social-create-room` | sidebar "Create" (opens the room-name input) |
| `social-join-room` | sidebar "Join" (opens the invite-code input) |
| `social-create-join-input` | shared create/join text input |
| `social-create-join-submit` | "Go" |
| `social-room-item-{roomId}` | a room in the sidebar list (stable seeded/domain id) |
| `social-room-name` | active room title in the header |
| `social-invite-copy` | invite-code copy chip in the header |
| `social-directory-open` | sidebar "Browse directory" |
| `social-directory-search` | directory search input |
| `social-chat-messages` | chat scroll log (the "messages render here" container) |
| `social-chat-message-{messageId}` | one message row (server UUID suffix) |
| `social-chat-load-earlier` | "Load earlier messages" |
| `social-chat-input` | message composer `<textarea>` |
| `social-chat-send` | send button |
| `social-chat-attach` | attach-image button |
| `social-chat-image-input` | hidden `<input type="file">` (use `setInputFiles`) |
| `social-chat-reply-cancel` | × on the "Replying to…" bar |
| `social-chat-mention-{userId}` | an @mention autocomplete option |
| `social-chat-message-react` | per-message menu: open emoji picker (one menu open at a time) |
| `social-chat-message-reply` | per-message menu: reply |
| `social-chat-message-edit` | per-message menu: edit (own messages) |
| `social-chat-message-delete` | per-message menu: delete (own messages) |
| `social-chat-emoji-{emoji}` | an option in the emoji picker grid |
| `social-chat-reaction-{emoji}` | an existing reaction chip on a message (scope by the message row) |
| `social-chat-edit-input` | inline edit input |
| `social-chat-edit-save` | inline edit "Save" |
| `social-chat-edit-cancel` | inline edit cancel |
| `social-room-leave` | overview "Leave room" |
| `social-member-{userId}` | a member row on the overview |
| `social-member-kick-{userId}` | "Kick" on that member row (leader only) |
| `social-match-run` | "Find matches" on the study-match tab |

## Enforcement

`frontend/eslint.config.mjs` has a per-file `no-restricted-syntax` block scoped
to the owning files listed above. It errors on any `<button>`, `<input>` or
`<textarea>` in those files that has no `data-testid` attribute:

```js
{
  files: [ /* the surface files */ ],
  rules: {
    "no-restricted-syntax": ["error", {
      selector:
        'JSXOpeningElement[name.name=/^(button|input|textarea)$/]' +
        ':not(:has(JSXAttribute[name.name="data-testid"]))',
      message: "E2E surface (#382): …",
    }],
  },
}
```

It is intentionally narrow:

- **Only the listed owning files.** A repo-wide version would be pure noise; the
  rest of the app has no browser coverage to protect.
- **Only intrinsic interactive elements.** Custom components (`<CustomSelect>`,
  `<Button>`) are not matched — a testid on a component is a prop the component
  has to forward, which is a code change, not an attribute. Tag the element
  inside the component instead.
- **Container roots are not enforced**, only added by convention. A selector for
  "the root `<div>` of this component" is not expressible without false
  positives.

There is no lint coverage on `signin-trigger` in `src/app/(public)/page.tsx` —
the landing page has dozens of buttons that are not part of any browser test, so
that file stays out of the `files` list. The trigger is documented here instead.

### Adding a surface

1. Pick a prefix, add the row to the table above and the testids to the
   inventory.
2. Add the owning file to the `files` array in the lint block.
3. Run `npm run lint` from `frontend/` — it will list every interactive element
   in the new file that still needs a testid.

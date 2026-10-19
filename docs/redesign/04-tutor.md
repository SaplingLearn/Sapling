# Redesign prompt 04: the Clov tutor

Implementation record for the Fetch-inspired tutor. Branch `feat/redesign-tutor`
on top of `feat/redesign-learn`. Design source:
https://app.pen.dev/s/sxEA2n5Ikk7KWUOanWPghMWYFFS0SbPgbkwkIm9dLYA (frames
s3Kxuz/wRolX, ULhG3/rIzSa, W14qiJ/QgtPP, Z0WKXz/lzEyB, HHU6e, WCplx, cSgSE, hgkZT).

## One controller, two views

The tutor is a view of `/learn`, not a second engine.

| | Learning studio (prompt 02) | Clov tutor (this prompt) |
| --- | --- | --- |
| URL | `/learn` | `/learn?view=tutor` |
| Offered when | always (loop on) | the `tutor_view` flag is `on` (`services/feature_flags.py`); off, the param is ignored |
| Controller | `learn/LoopLearn.tsx` | the same `LoopLearn` (presentation in `learn/TutorView.tsx`) |
| Session / goal / plan / phase | `useReducer(reduceLoopEvent)` + the loop clients | the same state and requests |
| No session open | starts a check-in (unchanged) | shows the welcome; nothing starts until the student chooses |

- Switching views (`loop-view-tutor`, or the tutor menu's "Switch to the
  Learning studio") changes only the URL's `view` param and the layout. It
  sends nothing and keeps the session.
- `?view=` is not a deep link: it survives the one-time deep-link cleanup.
- Discovery waits for the flag answer when `view=tutor` was asked for, so a
  tutor visit never auto-starts a check-in the welcome should have offered.

## Nav proposal (not implemented)

`fa26/Navigation.tsx` is untouched. Today the rail has one `/learn` entry ("Clov").

Recommended: keep the one rail entry while the flag is in rollout. If Learn and
Tutor get separate entries (the wireframes' pencil and tree), point them at
`/learn` and `/learn?view=tutor`, keep both under `hide_tutor`
(`navFlagForPath('/learn')`), and mark the active entry by `view`. Neither
entry needs a new route or store. No phone bottom tab bar was added.

## Retry and Stop

- Stop aborts the turn's `AbortController`. Partial text stays, marked
  "You stopped this reply." Later events of that stream are ignored (generation
  plus controller ownership).
- An interrupted conversational turn records its text and owning session.
  Retry runs only for the latest turn of the current session, while no other
  turn or retry runs and chat is not paused.
- Persistence: the loop saves a turn's user row and reply together, only on
  completion (`_LoopTurn.complete`). A turn that broke off normally left
  nothing. A Stop can still race the server's save, so Retry first reads the
  stored transcript (`resumeSession`, an existing client):
  - the turn is there: the stored rows replace the pair, status is reconciled,
    nothing is sent again;
  - it is not: the pair is replaced by ONE re-send through `streamLoopChat`;
  - the read failed: nothing is sent.
- Graded submissions are never replayed. A broken feedback stream or a 409
  "already graded" reads `GET /status` first (`loop-recovery-note`), and the
  existing Continue is the way on. There is no feedback-only regeneration
  contract, so none is faked.

## Unsupported affordances and how they map

| Wireframe | Mapping |
| --- | --- |
| Composer "Materials" | Opens the Materials context: this course's real Library documents and "Open course Library". No attachment, no citation. |
| Material rows' open arrow | Not shipped: there is no original-file URL. Rows name the document; Library opens it. |
| "Course chat" / "Guided learning" composer labels | Omitted: the loop has one conversation mode. |
| Map "2 classes · 20 concepts" | Shows the current course and its real concept count. |
| Knowledge check "· PRAGMATICS" concept tag | Omitted: the served pose has no concept name. |
| "Review" stage | Labelled "Wrap-up" (closing is not a delayed retention check). |

## Known gaps

- After a reload mid-teach the Goal & plan list shows the goal concepts only:
  `GET /plan` requires the plan phase, so no read-only plan read exists.
- ~~Library does not read `?course=`; Materials links to `/library`.~~ Resolved in
  prompt 05: Library pre-selects `?course=` and Materials links to
  `/library?course=<course_id>` (see `05-review-package.md`).

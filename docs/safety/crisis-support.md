# Crisis support

Status: **built, flag OFF, copy pending owner review.**

When a student writes something that reads as suicidal ideation, self-harm
or acute danger to an AI surface in Sapling, the surface does not run the
model and does not carry on with the lesson. It shows a fixed, warm card with
crisis resources instead, and records nothing of the turn.

(First built on the learning loop and removed with it by the revert
e5a08d47; this is the same path re-landed on the surfaces main has. The loop
re-land, PR #866, should screen its own routes the same way: see "Adding a
surface" below.)

## What it does

1. **Screen.** On every covered route the student-written text goes through
   `backend/services/crisis_detection.py::detect`. That is pure,
   deterministic phrase matching: no model call, no I/O, microseconds for a
   chat message.

   **Screening precedes every rate limit, budget and quota check.** A
   student in crisis must never get a 429 instead of the card, and a crisis
   turn runs no model, so no limiter has anything to protect. The screen is
   one call at the very top of the route handler
   (`crisis_support.screen_async(request, user_id, surface, *texts)`, or
   `screen` in a sync `def` route). The notes routes screen the note they
   read, so their screen sits right after that read; nothing between the
   handler's start and the screen limits anything. The per-user LLM budget
   (`services/llm_budget.py`, flag `llm_budget`) is checked at the model
   chokepoint, which a crisis turn never reaches. A crisis turn consumes no
   rate-limit slot, budget token or quota unit and writes no `llm_usage` row.
2. **Authenticate, on a match only.** The screen runs before the handler's
   own auth, so on a match it checks the caller itself (`require_self` on the
   body's `user_id`): a stranger gets the route's 401/403 before anything is
   read or recorded about anyone. Ordinary text pays for detection only.
3. **Flag.** Then the `crisis_support` flag is read for that student. It is
   `off` by default and fails closed, so with the flag off every route
   behaves exactly as before.
4. **Respond.** On a match with the flag on, the route returns the card
   instead of its result:
   - JSON routes: `{"reply": <the copy as text>, "crisis_support": {...}}`
     plus the route's own neutral keys (`graph_update: {}`, `session_id:
     null`, `cards: []`, `concepts: []`, ...), so a client that ignores the
     card still reads a well-formed, empty result.
   - Streams: one `done` event whose `data` is that same body. That is the
     tutor streams' normal terminal event, so the existing stream consumer
     resolves it like any turn.
   - The frontend renders `crisis_support` as a calm card
     (`frontend/src/components/safety/CrisisSupportCard.tsx`): inline in a
     conversation; as a dialog where there is none (the tutor's start screen,
     a note action, a flashcard generator, the study guide's "ask the
     tutor").
5. **Record.** One `safety.crisis_support_shown` event (category `system`)
   with `surface`, `category` (`acute_danger` / `suicidal_ideation` /
   `self_harm`) and `tier` (`explicit` / `mention`), and the user id. It
   lives only in our own `events` table. It is not mirrored to PostHog
   (`posthog_client._NOT_MIRRORED`): it is mental-health information about a
   named student, not product analytics. Category `system` also keeps it out
   of admin analytics' usage rollups. For staff follow-up, count and list it
   in SQL:
   `select user_id, created_at, payload->>'surface', payload->>'category' from events
   where event_type = 'safety.crisis_support_shown' order by created_at desc;`

A crisis turn makes no model call and writes nothing a turn writes: no
message row, lazy tutor session, summary, concept, card or graph change.
Because no message row is written, the exchange is not in the transcript
after a reload, and the tutor's next turn does not see it in its history.

The triggering text is never stored, logged, fingerprinted (the event has no
`content=`, so no `content_fp`) or sent anywhere: not to a model, not to
PostHog, not to Logfire.

## Surfaces covered

| Surface (`event.payload.surface`) | Route(s) | Text screened | Instead of |
|---|---|---|---|
| `tutor_chat` | `POST /api/learn/chat`, `/chat/stream` | `message` | a tutor turn (also the quiz's "Ask about this" panel and the study guide's "ask the tutor", which ride it) |
| `tutor_start` | `POST /api/learn/start-session`, `/start-session/stream` | `topic` | opening a session |
| `note_chat` | `POST /api/notes/{id}/chat` | `message` (first), then the note title + body | a note-chat reply (the agent reads the note) |
| `note_send_to_tutor` | `POST /api/notes/{id}/send-to-tutor` | note title + body | handing the note to the tutor |
| `note_summarize` | `POST /api/notes/{id}/summarize` | note title + body | a summary |
| `note_extract_concepts` | `POST /api/notes/{id}/extract-concepts` | note title + body | concept extraction |
| `flashcard_set_suggest` | `POST /api/flashcards/sets/suggest` | `description` | sorting a described set |
| `flashcard_import_paste` | `POST /api/flashcards/import/generate` (`source: "paste"`) | `text` | generating cards from pasted text |
| `flashcard_import_cloze` | `POST /api/flashcards/import/cloze` | `paragraph` | generating cloze cards |

Frontend surfaces that render the card: the tutor (`Learn.tsx`: chat turns
inline, a session start as a dialog over the picker), the quiz's "Ask about
this" panel (`AskPanel`), the study guide's "ask the tutor"
(`useTutorHandoff`, a dialog; the tutor is not opened), the notetaker (chat
inline; Summarize, Extract concepts and Send to tutor as a dialog), and the
flashcards hero ("What do you want to study?"), AI-generate tab and cloze tab
(dialogs).

**Checked and not covered** (no student-written text reaches a model there):

- `/api/learn/action` and `/mode-switch` carry no free text.
- Quiz generation takes a concept id; quiz answers (multiple choice and
  written) are graded deterministically (`services/quiz/grading.py`).
  Written answers do reach the post-submit `quiz_context` agent as a
  BackgroundTask, but no reply is shown, so there is nothing to answer in
  place of. **Owner decision:** whether a crisis phrase typed as a quiz
  answer should also show the card (it would need the answer route to
  return it alongside the grade).
- `/api/notes/{id}/generate-quiz` picks a linked concept; no model runs.
- Study guides take choices (scope, goal, depth, materials), not text; their
  "ask the tutor" rides the tutor chat, which is covered.
- `/api/flashcards/generate` and `/api/graph/{user}/concept-description` take
  a concept name off the student's map, not a message.
- Uploaded course material is not screened: document uploads, library
  documents (`import/generate` with `source: "library_doc"`), Anki / xlsx /
  URL / OCR imports (`import/parse`) and their clean-up (`import/cleanup`).
  Screening course readings would mostly flag the readings.
- Study-room chat (`/api/social/rooms/{id}/messages`) is peer to peer. No
  model reads it.
- Feedback and issue reports reach no model.

## Where things live

| What | File |
|---|---|
| Detection + every phrase list | `backend/services/crisis_detection.py` |
| **All user-facing copy (owner review)** | `backend/services/crisis_support_copy.py` |
| Campus counseling, per school | `CAMPUS_COUNSELING` in that same copy file |
| Screen, flag, event, response builders | `backend/services/crisis_support.py` |
| The screens | the first statement of each handler in `routes/learn.py`, `routes/notes.py`, `routes/flashcards.py` |
| Flag registration | `backend/services/feature_flags.py::REGISTRY["crisis_support"]` |
| Event taxonomy / PostHog exclusion | `services/events_service.py::EVENT_TAXONOMY`, `services/posthog_client.py::_NOT_MIRRORED` |
| The card | `frontend/src/components/safety/CrisisSupportCard.tsx`, `frontend/src/lib/crisisSupport.ts` |
| Tests | `backend/tests/test_crisis_detection.py`, `backend/tests/test_crisis_support_routes.py`, the `crisis` cases in the frontend vitest suites |

## Adding a surface (or a limiter)

- **A new route that hands student-written text to a model** adds a
  `Surface` to `crisis_support.py`, calls the screen as its handler's first
  statement, returns the card with the route's neutral keys, adds a `Case` to
  `test_crisis_support_routes.py` (`test_every_surface_is_covered` fails
  until it does) and renders the card on its frontend surface.
- **A new limiter on a covered route** (rate limit, budget, quota) goes
  AFTER the screen. `test_the_screen_precedes_every_limiter_on_the_route`
  fails if any call whose name reads as a limit, budget, quota or throttle
  sits above the screen in the handler, or if the route gains a route-level
  dependency (a dependency runs before the handler body, so before the
  screen). A limiter that must be a dependency needs the screen as a
  dependency listed before it: the original build had one
  (`crisis_support.screened` + a `CrisisAnswered` exception handler, commit
  d7a0cd45), dropped here because no covered route on main has a limiter
  dependency.

## Detection

`detect` matches three lists over a normalized form of the text (case and
accents folded, apostrophes dropped, punctuation turned into spaces or
sentence breaks, stretched letters squeezed):

- **EXPLICIT** phrases match anywhere: first-person statements such as "kill
  myself", "end my life", "want to die", "hurt myself on purpose", "took a
  bunch of pills", "I'm suicidal". Spacing and common misspellings are
  covered ("kill my self", "killmyself", "myslef", "wanna die", "want 2
  die", "kms" after an intent word).
- **MENTIONS** ("suicide", "suicidal", "self-harm") count only when the same
  sentence speaks in the first person: "I've been thinking about suicide"
  matches; "Why did Romeo commit suicide?" and a bare concept name
  "Suicide" do not.
- **GUARDS** veto any match they overlap: idioms ("killing myself laughing",
  "cut myself some slack", "the hill I want to die on"), negations ("I don't
  want to die", "I'm not suicidal"), and technical compounds ("suicide squad",
  "suicide inhibitor", "suicide burn"). "this problem is killing me", "kill
  the process", "dying to know", "dead code", "kill switch" and "die roll"
  never match anything. **TOPIC_GUARDS** ("Durkheim", "euthanasia", "Hamlet",
  "theory of suicide", "essay on suicide", ...) veto MENTIONS in a text that
  names coursework. They never veto an explicit first-person phrase.

When several categories match, the most severe is reported: `acute_danger`,
then `suicidal_ideation`, then `self_harm`.

**To extend:** add a `Phrase` to `EXPLICIT` (choose its category, write the
pattern against the normalized form, reuse `_MYSELF` / `_INTENT`), or a
pattern to `GUARDS` / `TOPIC_GUARDS` for a new false positive. Then add an
example to `backend/tests/test_crisis_detection.py`. The suite fails if a
phrase has no positive example, or if a guard vetoes none of the pinned
negatives.

## Limits

- **Deterministic phrases miss indirect language.** "I just want everything
  to stop", "I won't be a problem much longer", "I've been giving my things
  away" and "I can't do this anymore" do not match. Leetspeak ("k1ll") and
  spaced-out letters do not match either. English only.
- **False positives remain.** A literature or psychology question that uses
  an explicit first-person phrase ("the speaker says 'I want to die'") gets
  the card. So can a quiz option about suicide quoted in the quiz's "Ask
  about this" opening message, pasted notes or a poem with a first-person
  line, or a first-person sentence in lecture notes that names suicide with
  no topic word. The card says the student can keep studying, and their next
  message is screened afresh.
- **A model-based screen** would catch indirect language. It would also need
  its own labelled eval set, measured false-negative and false-positive
  rates, eval spend, and a latency budget on every turn. It would also send
  the student's crisis text to a model provider, which this path never does.
  It would be a separate decision.
- **Only auth comes first.** An unauthenticated or foreign request gets its
  401/403 (and a hidden nav feature its 404, `nav_feature_gate`) before the
  card. Those refusals say who you are and whether the feature exists, never
  that you used too much.
- **No human in the loop.** Nobody is notified and nothing follows up
  automatically. The event is a record for staff to query (the SQL above),
  not an alerting channel. Sapling is a study tool, not a crisis service, and
  the copy says so.
- **Campus counseling** is the generic default for every student until
  `CAMPUS_COUNSELING` has verified entries *and* `courses.school_id` is
  populated (the student's school is read through their enrollments; today
  that column is empty).

## Owner review checklist

Before turning the flag on:

- [ ] Read `backend/services/crisis_support_copy.py` top to bottom: the title,
      intro, resources heading, each resource's name / detail / action
      labels, closing lines and the dismiss button. The card renders nothing
      else.
- [ ] Confirm the US resources are current: 988 Suicide & Crisis Lifeline
      (call or text 988), Crisis Text Line (text HOME to 741741), 911,
      findahelpline.com.
- [ ] Decide the order of resources (`resources()` in the copy file).
- [ ] Add your school's counseling service to `CAMPUS_COUNSELING` with a
      phone number and URL checked on the school's own site, or accept the
      generic default. A wrong number is worse than none.
- [ ] Decide whether `courses.school_id` should be populated so the
      per-school entry is used (until then everyone sees the default).
- [ ] Read the phrase lists and guards in
      `backend/services/crisis_detection.py`. In particular, decide on the
      first-person rule for bare mentions and on the hyperbole that still
      matches ("I want to die lol", "this class makes me want to kms").
- [ ] Decide on the surfaces: the flashcard paste and cloze generators are
      screened (the student's own pasted text, like a note), uploaded
      material is not, and quiz answers are not (see "Checked and not
      covered").
- [ ] Decide who reads `safety.crisis_support_shown` and how often; nothing
      alerts anyone today.
- [ ] Optionally try your own phrasings:
      `cd backend && venv/bin/python -c "from services.crisis_detection import detect; print(detect('...'))"`.
- [ ] Bump `COPY_VERSION` if you changed any string, and set
      `REVIEW_STATUS = "approved"`. A test pins the draft status, so update
      it in `test_the_copy_is_pending_owner_review` in the same change.

## Turning it on

The flag is `crisis_support` (`off` / `on`), server-side only. Nothing on
the frontend reads it; the card renders whenever a response carries it.

1. Deploy the backend and the frontend together. An older frontend renders
   the card's text `reply` as an ordinary message on chat surfaces, but not
   the card itself.
2. In `/admin` → feature flags, add a role or user rule `crisis_support = on`
   for staff and check each surface with a test account. Use the phrases in
   `test_crisis_support_routes.py`: the card shows, and a
   `safety.crisis_support_shown` row appears in `events` (the SQL above).
3. Set the default to `on`.

`SAPLING_FLAG_CRISIS_SUPPORT=on|off` in the backend environment overrides
everything (kill switch). Flag reads are cached for 30 s per process.

## Function-mode seam

A crisis turn makes no model call, so it needs no handler in
`agents/function_handlers_e2e.py`, and none was added.
`test_function_mode_the_scripted_model_is_never_called_on_a_crisis_message`
registers a counting handler for every agent task, sends crisis text to every
surface under `SAPLING_MODEL_MODE=function`, and asserts zero calls. Its
control turn proves the counter does see a model call when one is made.

## Verifying

- Backend: `cd backend && venv/bin/python -m pytest tests/test_crisis_detection.py tests/test_crisis_support_routes.py -q`.
- Frontend: `cd frontend && npx vitest run crisis` and the touched suites
  (`ChatPanel`, `Learn.sessionState`, `AskPanel`,
  `notetaker/page.crisisSupport`, `flashcards/crisisSupport`,
  `useTutorHandoff.crisis`).
- E2E (flag off, so behaviour is unchanged): `tutor`, `streaming`,
  `quiz-journeys`, `study-guide`, `feature-flags`, `analytics`, `events`. Once
  the copy is approved, add a crisis journey and the card's a11y scan
  (`frontend/e2e/a11y.spec.ts`, spec §13 A135) with
  `SAPLING_FLAG_CRISIS_SUPPORT=on` in the stack. The card uses the
  `--info` / `--info-soft` / `--text` / `--text-dim` tokens and the shared
  `Dialog` (focus moves into it and returns on close), but it has not been
  through the axe lane yet.

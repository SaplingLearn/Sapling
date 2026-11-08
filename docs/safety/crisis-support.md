# Crisis support

Status: **built, flag OFF, copy pending owner review.**

When a student writes something that reads as suicidal ideation, self-harm
or acute danger to any AI surface in Sapling, the surface does not run the
model and does not continue the lesson. It shows a fixed, warm card with
crisis resources instead, and records nothing of the turn.

## What it does

1. **Screen.** On every covered route, right after authentication, the
   student-written text goes through
   `backend/services/crisis_detection.py::detect`. That is pure,
   deterministic phrase matching: no model call, no I/O, microseconds for a
   chat message.

   **Screening precedes every rate limit, budget and quota check.** A
   student in crisis must never get a 429 or a pause instead of the card, and
   a crisis turn runs no model, so no limiter has anything to protect. On the
   loop routes whose rate limit is a route dependency, the screen is a
   dependency placed before it (`crisis_support.screened`, right after the
   kill switch). Everywhere else it is the handler's first statement after
   auth, ahead of every inline check. A crisis turn consumes no rate-limit,
   budget or tutor-call unit, and the loop's chat composer stays usable
   during a budget pause so a paused student's message can still reach the
   screen.
2. **Flag.** Only on a match is the `crisis_support` flag read for that
   student. It is `off` by default and fails closed, so with the flag off
   every route behaves exactly as before.
3. **Respond.** On a match with the flag on, the route returns the card
   instead of its turn:
   - JSON routes: `{"reply": <the copy as text>, "crisis_support": {...}}`
     plus the route's own neutral keys (`graph_update: {}`, `session_id:
     null`, `graded: false`, ...).
   - Streams: one `done` event whose `data` is that same body. That is the
     tutor streams' normal terminal event, so the existing stream consumer
     resolves it like any turn.
   - The frontend renders `crisis_support` as a calm card
     (`frontend/src/components/safety/CrisisSupportCard.tsx`): inline in a
     conversation; where there is none (a note action, an answer box, the
     tutor's start screen) as a dialog; and on the learning loop's session
     start in the place the session would have filled, with "Back to
     studying" starting a fresh session on the course.
4. **Record.** One `safety.crisis_support_shown` event (category `system`)
   with `surface`, `category` (`acute_danger` / `suicidal_ideation` /
   `self_harm`) and `tier` (`explicit` / `mention`), and the user id. It
   lives only in our own `events` table. It is not mirrored to PostHog
   (`posthog_client._NOT_MIRRORED`): it is mental-health information about a
   named student, not product analytics. Category `system` also keeps it out
   of admin analytics' usage rollups, so count it in SQL:
   `select payload->>'surface', payload->>'category', count(*) from events
   where event_type = 'safety.crisis_support_shown' group by 1, 2;`

A crisis turn makes no model call and writes nothing a turn writes: no
learning evidence, grade, grading claim, hint rung, help-ledger row, message
row, lazy session, summary, concept, XP or streak. Everything is left as it
was: an answered check item stays posed, and the student can carry on
studying whenever they're ready. Because no message row is written, the
exchange is not in the transcript after a reload, and the tutor's next turn
does not see it in its history.

The triggering text is never stored, logged, fingerprinted (the event has no
`content=`, so no `content_fp`) or sent anywhere: not to a model, not to
PostHog, not to Logfire.

## Surfaces covered

| Surface (`event.payload.surface`) | Route(s) | Text screened | Instead of |
|---|---|---|---|
| `tutor_chat` | `POST /api/learn/chat`, `/chat/stream` | `message` | a tutor turn (also the loop turn it delegates to) |
| `tutor_start` | `POST /api/learn/start-session`, `/start-session/stream` | `topic`, `goal.text` | opening a session |
| `loop_chat` | `POST /api/learn/loop/chat`, `/chat/stream` | `message` | a loop tutor turn |
| `loop_start` | `POST /api/learn/loop/start-session`, `/start-session/stream` | `topic`, `goal.text` | opening a session |
| `loop_goal` | `POST /api/learn/loop/goal` | `goal.text` | storing the goal (it rides every later tutor prompt) |
| `loop_check_answer` | `POST /api/learn/loop/check/answer`, `/check/answer/stream` | `answer`, `reason` | grading + the feedback turn |
| `loop_step_attempt` | `POST /api/learn/loop/step/attempt` | `attempt_text` | counting an attempt toward a hint |
| `loop_probe_answer` | `POST /api/learn/loop/probe/answer` | `answer`, `reason` | grading the probe item |
| `loop_review_answer` | `POST /api/learn/loop/review/answer` | `answer`, `reason` | grading the review item |
| `loop_posttest_answer` | `POST /api/learn/loop/posttest/answer` | `answer`, `reason` | grading the retention check |
| `note_chat` | `POST /api/notes/{id}/chat` | `message`, note title + body | a note-chat reply (the agent reads the note) |
| `note_send_to_tutor` | `POST /api/notes/{id}/send-to-tutor` | note title + body | handing the note to the tutor |
| `note_summarize` | `POST /api/notes/{id}/summarize` | note title + body | a summary |
| `note_extract_concepts` | `POST /api/notes/{id}/extract-concepts` | note title + body | concept extraction |

Frontend surfaces that render the card: the tutor (`Learn.tsx`), the learning
loop (`LoopLearn.tsx`: chat, check answers, start, goal, probe, hints), the
quiz's "Ask about this" panel, Study's review queue (`DueQueue`), the
retention check, and the notetaker (chat, Summarize, Extract concepts, Send to
tutor). While a card is on screen it holds the shell's feedback prompts
(`frontend/src/lib/feedbackPacing.ts`), so no survey opens over it. On the
notes actions the crisis screen runs before the learning loop's integrity
guard (spec §13 A125): a student in crisis gets the card, never an integrity
refusal.

**Checked and not covered** (no student text reaches a model there):

- Study-room chat (`/api/social/rooms/{id}/messages`) is peer to peer. No
  model reads it; the room summary agent sees only members' concept names.
- Quiz answers are graded deterministically (`services/quiz_grading.py`);
  quiz generation takes a concept id.
- `/api/learn/action`, `/api/learn/loop/action`, `/hint` and `/mode-switch`
  carry no free text.
- Document uploads, flashcard imports (pasted text, URLs) and syllabus
  imports are course material, not messages. Screening course readings would
  mostly flag the readings.
- Feedback and issue reports reach no model.

## Where things live

| What | File |
|---|---|
| Detection + every phrase list | `backend/services/crisis_detection.py` |
| **All user-facing copy (owner review)** | `backend/services/crisis_support_copy.py` |
| Campus counseling, per school | `CAMPUS_COUNSELING` in that same copy file |
| Flag, event, response builders, the screen dependency (`screened`) | `backend/services/crisis_support.py` |
| Screen-before-rate-limit wiring on the loop | `backend/routes/learn_loop.py::_screened` |
| Flag registration | `backend/services/feature_flags.py::REGISTRY["crisis_support"]` |
| Event taxonomy / PostHog exclusion | `services/events_service.py::EVENT_TAXONOMY`, `services/posthog_client.py::_NOT_MIRRORED` |
| The card | `frontend/src/components/safety/CrisisSupportCard.tsx`, `frontend/src/lib/crisisSupport.ts` |
| Tests | `backend/tests/test_crisis_detection.py`, `backend/tests/test_crisis_support_routes.py`, the `crisis` cases in the frontend vitest suites |

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
  about this" opening message, or a first-person sentence in lecture notes
  that names suicide with no topic word. The card says the student can keep
  studying, and their next message is screened afresh.
- **A model-based screen** would catch indirect language. It would also need
  its own labelled eval set, measured false-negative and false-positive
  rates, eval spend, and a latency budget on every turn. It would also send
  the student's crisis text to a model provider, which this path never does.
  It would be a separate decision.
- **Only auth and the loop's kill switch come first.** An unauthenticated or
  foreign request (401/403) and a loop route while the loop is switched off
  (404) are refused before the screen. Those refusals say who you are and
  whether the feature exists, never that you used too much.
- **No human in the loop.** Nobody is notified and nothing follows up. The
  event is a count for admins, not an alerting channel. Sapling is a study
  tool, not a crisis service, and the copy says so.
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
  (`ChatPanel`, `LoopLearn`, `Learn.sessionState`, `AskPanel`, `DueQueue`,
  `RetentionCheck`, `notetaker/page.crisisSupport`).
- E2E (flag off, so behaviour is unchanged): `tutor`, `streaming`,
  `learn-loop`, `learn-grade-recovery`, `quiz-journeys`, `quiz-integration`,
  `quiz-errors`, `study-semester`, `feature-flags`, `analytics`. A crisis
  journey spec should be added once the copy is approved, with
  `SAPLING_FLAG_CRISIS_SUPPORT=on` in the stack.

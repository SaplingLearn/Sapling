# Crisis support

Status: **built, flag OFF, copy pending owner review.**

When a student writes something that reads as suicidal ideation, self-harm
or acute danger to an AI surface in Sapling, the surface does not run the
model and does not carry on with the lesson. It shows a fixed, warm card with
crisis resources instead, and records nothing of the turn.

One kind of text is handled differently: a note the student STORED, read by
the notes agent actions (Summarize, Extract concepts, the note chat, Send to
tutor). A match in a note's title or body never blocks the action. The
action runs as usual and the same card is shown BESIDE its result. A note
is often material the student is quoting (a patient, a play, a poem), and
no phrase list can tell a quoted patient from a student quoting themselves,
so the student gets what they asked for and the resources with it. What the
student TYPES (a chat message, the note chat's message, a topic, a
description) still blocks, on every surface. The one topic that does not is
Send to tutor's: the tutor opens on the note's title, and a session started
on that title unchanged is the note's content too, so it starts with the
card beside it.

(First built on the learning loop and removed with it by the revert
e5a08d47, then re-landed on main's surfaces. The loop re-land, PR #866,
screens the learning loop's routes the same way: see "Surfaces covered".)

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
   `screen` in a sync `def` route). The per-user LLM budget
   (`services/llm_budget.py`, flag `llm_budget`) is checked at the model
   chokepoint, which a crisis turn never reaches. A crisis turn consumes no
   rate-limit slot, budget token or quota unit and writes no `llm_usage` row.

   The learning loop's routes whose rate limit is a ROUTE DEPENDENCY
   (`routes/learn_loop.py::_RATE_LIMITED`) cannot screen in the handler,
   which runs after that dependency: their screen is a dependency placed
   right after the loop's kill switch and before the rate limit
   (`crisis_support.screened`, via `learn_loop._screened`). On a match it
   authenticates the caller (the body's `user_id`, else the session user),
   reads the flag and raises `CrisisAnswered`, whose finished response
   `main.py`'s `answered_handler` returns as-is, so neither the rate limit
   nor the handler runs. The loop's other routes (goal, probe, review) screen
   inline, first thing after the loop's gate. A loop crisis turn consumes no
   tutor-call unit either (the A20 budget), and the loop's chat composer
   stays usable during a budget pause so a paused student's message can
   still reach the screen.

   The notes routes screen the note they read with
   `crisis_support.screen_content_async`, right after that read and still
   before any limit. It answers with a `ContentScreen`, never a card: the
   blocking builders (`json_body`, `turn_json`, `start_json`,
   `sse_response`) refuse it, and the only thing that takes it is
   `crisis_support.alongside(screen, action())`. The action is limited and
   budgeted as usual (it runs a model), so it can be refused with a 429.
   When the action raises (a 429, a 413, a 500), `alongside` leaves the card
   on the request's state (`request.state.crisis_support_card`) and
   re-raises, so the error reaches the app's own handler, and an unexpected
   one reaches ServerErrorMiddleware, the server's error log and the trace,
   exactly as without a match. `crisis_support.ErrorCardMiddleware`, wrapped
   around the whole middleware stack by `install_error_card` in `main.py`
   (outside every ServerErrorMiddleware, so the generic 500 passes it too),
   adds the card to that JSON error body in the `crisis_support` key. The
   status, detail, `Retry-After` and envelope are exactly what the same
   error gets without a match, and no exception handler needs to know about
   the card. The student never gets a refusal without the card.

   A tutor start (`/api/learn/start-session` and its stream) screens its
   topic as typed, with one exception. Send to tutor opens
   `/learn?topic=<the note's title>&note=<its id>`, and a start on that
   title unchanged sends `from_note_id`. Only when the topic matched does the
   route check that claim (`services/tutor/note_topic.py::note_title_version` (through `crisis_support.screen_tutor_start_async`)):
   the note must be the student's own, and the topic must be exactly what
   Send to tutor derives from its title (`notes_service.tutor_topic`). If
   both hold, the session starts through `alongside`, with the card beside it
   (in the stream's `done` data). If anything is doubtful (no id, another
   student's or a deleted note, an edited topic, a failed read), the topic
   blocks as typed.
2. **Authenticate, on a match only.** The screen runs before the handler's
   own auth, so on a match it checks the caller itself (`require_self` on the
   body's `user_id`): a stranger gets the route's 401/403 before anything is
   read or recorded about anyone. Ordinary text pays for detection only.
3. **Flag.** Then the `crisis_support` flag is read for that student. It is
   `off` by default, so with the flag off every route behaves exactly as
   before. While the flag store is unreadable the read answers from the last
   snapshot the process read (`feature_flags.last_known_flag_on`), so an
   outage cannot silently switch off a card the owner turned on; a process
   that never read the store still answers off. Independently of the flag,
   the tutor and note-chat system prompts carry a model-side backstop
   (`crisis_support_copy.MODEL_SAFETY_PROMPT`, built from the same resource
   strings) for whatever the phrase screen misses.
4. **Respond.** On a match with the flag on, the route returns the card
   instead of its result (a note's content: beside it, see below):
   - JSON routes: `{"reply": <the copy as text>, "crisis_support": {...}}`
     plus the route's own neutral keys (`graph_update: {}`, `session_id:
     null`, `cards: []`, `concepts: []`, ...), so a client that ignores the
     card still reads a well-formed, empty result.
   - Streams: one `done` event whose `data` is that same body. That is the
     tutor streams' normal terminal event, so the existing stream consumer
     resolves it like any turn.
   - A note's content (and a tutor start on Send to tutor's note title): the
     action's normal result plus `crisis_support` and
     `crisis_support_alongside: true` (no card `reply`: the note chat's
     `reply` is the agent's), for the streamed start in its `done` event's
     data; or its error body plus `crisis_support` (a streamed start that
     ends in an `error` event carries it in that event's data).
   - The frontend renders `crisis_support` as a calm card
     (`frontend/src/components/safety/CrisisSupportCard.tsx`): inline in a
     conversation; as a dialog where there is none (the tutor's start screen,
     a note action, a flashcard generator, the study guide's "ask the
     tutor"); and on the learning loop's session start in the place the
     session would have filled, with "Back to studying" starting a fresh
     session on the course. With `crisis_support_alongside` the notetaker shows the result
     too (the new summary, the linked concepts, the chat reply under the
     card) and opens the tutor for Send to tutor once the card is closed.
     The tutor's start screen shows the card over the session it started, except for the start Send to tutor just handed over after the student closed that note's card (a one-shot, per-tab mark, `lib/crisisSupport.ts::markNoteCardShown`/`takeNoteCardShown`, valid ten minutes): that start does not pop the same card up again. A card instead of a session always shows.
5. **Record.** One `safety.crisis_support_shown` event (category `system`)
   with `surface`, `category` (`acute_danger` / `suicidal_ideation` /
   `self_harm`) and `tier` (`explicit` / `mention`), and the user id. It
   lives only in our own `events` table. It is not mirrored to PostHog
   (`posthog_client._NOT_MIRRORED`): it is mental-health information about a
   named student, not product analytics. Category `system` also keeps it out
   of admin analytics' usage rollups. The note chat re-reads its note every
   turn, so it shows the card beside every reply but records the event at
   most once a day per student, note and note version (`updated_at`), per
   process (`screen_content_async(..., once_a_day=...)`, a hash of the ids
   only). For staff follow-up, count and list it in SQL:
   `select user_id, created_at, payload->>'surface', payload->>'category' from events
   where event_type = 'safety.crisis_support_shown' order by created_at desc;`

A crisis turn makes no model call and writes nothing a turn writes: no
message row, lazy tutor session, summary, concept, card or graph change, and
on the learning loop no learning evidence, grade, grading claim, hint rung,
help-ledger row, XP or streak. An answered check item stays posed, and the
student can carry on studying whenever they're ready. (A
note action whose note matched is not a crisis turn: it runs, writes and is
limited exactly as without the card.)
Because no message row is written, the exchange is not in the transcript
after a reload, and the tutor's next turn does not see it in its history.

The triggering text is never stored, logged, fingerprinted (the event has no
`content=`, so no `content_fp`) or sent anywhere: not to a model, not to
PostHog, not to Logfire.

## Surfaces covered

| Surface (`event.payload.surface`) | Route(s) | Text screened | The card |
|---|---|---|---|
| `tutor_chat` | `POST /api/learn/chat`, `/chat/stream` | `message` | instead of a tutor turn (also the quiz's "Ask about this" panel and the study guide's "ask the tutor", which ride it) |
| `tutor_start` | `POST /api/learn/start-session`, `/start-session/stream` | `topic`, the learning loop's `goal.text` | instead of opening a session |
| `loop_chat` | `POST /api/learn/loop/chat`, `/chat/stream` | `message` | instead of a loop tutor turn |
| `loop_start` | `POST /api/learn/loop/start-session`, `/start-session/stream` | `topic`, `goal.text` | instead of opening a session |
| `loop_goal` | `POST /api/learn/loop/goal` | `goal.text` | instead of storing the goal (it rides every later tutor prompt) |
| `loop_check_answer` | `POST /api/learn/loop/check/answer`, `/check/answer/stream` | `answer`, `reason` | instead of grading + the feedback turn |
| `loop_step_attempt` | `POST /api/learn/loop/step/attempt` | `attempt_text` | instead of counting an attempt toward a hint |
| `loop_probe_answer` | `POST /api/learn/loop/probe/answer` | `answer`, `reason` | instead of grading the probe item |
| `loop_review_answer` | `POST /api/learn/loop/review/answer` | `answer`, `reason` | instead of grading the review item |
| `loop_posttest_answer` | `POST /api/learn/loop/posttest/answer` | `answer`, `reason` | instead of grading the retention check |
| `loop_prequestion_answer` | `POST /api/learn/loop/prequestion/answer`, `/prequestion/answer/stream` | `answer`, `reason` | instead of revealing and explaining the segment prequestion (spec §13 A138) |
| `loop_self_explain` | `POST /api/learn/loop/self-explain` | `reply` | instead of recording a self-explanation (spec §13 A139) |
| `note_chat` | `POST /api/notes/{id}/chat` | `message` (first), then the note title + body + tags | the message: instead of a reply; the note: beside the reply (the agent reads the note, tags included, as A125's integrity guard does) |
| `note_send_to_tutor` | `POST /api/notes/{id}/send-to-tutor` | note title + body | beside handing the note to the tutor |
| `note_summarize` | `POST /api/notes/{id}/summarize` | note title + body | beside the summary |
| `note_extract_concepts` | `POST /api/notes/{id}/extract-concepts` | note title + body | beside concept extraction |
| `flashcard_set_suggest` | `POST /api/flashcards/sets/suggest` | `description` | instead of sorting a described set |
| `flashcard_import_paste` | `POST /api/flashcards/import/generate` (`source: "paste"`) | `text` | instead of generating cards from pasted text |
| `flashcard_import_cloze` | `POST /api/flashcards/import/cloze` | `paragraph` | instead of generating cloze cards |
| `flashcard_generate` | `POST /api/flashcards/generate` | `topic` | instead of generating cards for a typed topic; beside the cards when the topic is one of the student's own graph concepts (`concept_topic.topic_is_graph_concept`, checked only on a match) |

Frontend surfaces that render the card: the tutor (`Learn.tsx`: chat turns
inline, a session start as a dialog over the picker), the learning loop
(`LoopLearn.tsx`: chat, check answers, start, goal, probe, hints, the
prequestion and self-explanation), Study's review queue (`DueQueue`), the
retention check (`RetentionCheck`), the quiz's "Ask about
this" panel (`AskPanel`), the study guide's "ask the tutor"
(`useTutorHandoff`, a dialog; the tutor is not opened), the notetaker (chat
inline, the reply under the card when the note matched; Summarize, Extract
concepts and Send to tutor as a dialog over their result, or over the error
toast when the answer was a 429 carrying the card), and the
flashcards hero ("What do you want to study?"), AI-generate tab, cloze tab
and the review start that generates cards (dialogs; a concept's cards that
come back with the card beside them show it once per Start and the review
goes on). While a card is on screen, in either form, it holds the shell's
feedback prompts (`frontend/src/lib/feedbackPacing.ts`), so no survey opens
over it. On the notes actions the crisis screen runs before the learning
loop's integrity guard (spec §13 A125): a student in crisis gets the card,
never an integrity refusal.

**Checked and not covered** (no student-written text reaches a model there):

- `/api/learn/action`, `/api/learn/loop/action`, `/hint` and `/mode-switch`
  carry no free text.
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
- `/api/graph/{user}/concept-description` takes a concept name off the
  student's map, not a message.
- Uploaded course material is not screened: document uploads, library
  documents (`import/generate` with `source: "library_doc"`), Anki / xlsx /
  URL / OCR imports (`import/parse`). Screening course readings would mostly
  flag the readings.
- The AI clean-up of an imported deck (`import/cleanup`) is not screened
  either: the cards are imported third-party study material (Anki, xlsx, a
  URL, OCR), not the student's own writing. A nursing deck's "Patient states
  I want to die. First nursing action?" would otherwise get the card and the
  deck could never be cleaned up. The student's own words reach a screen on
  the tutor, notes and flashcard-generate surfaces. Clean-up also checks the
  caller (`require_self`) before it reads a card.
- Study-room chat (`/api/social/rooms/{id}/messages`) is peer to peer. No
  model reads it.
- Feedback and issue reports reach no model.

## Where things live

| What | File |
|---|---|
| Detection + every phrase list | `backend/services/crisis_detection.py` |
| **All user-facing copy (owner review)** | `backend/services/crisis_support_copy.py` |
| Campus counseling, per school | `CAMPUS_COUNSELING` in that same copy file |
| Screen, flag, event, response builders, the screen dependency (`screened`) | `backend/services/crisis_support.py` |
| Screen-before-rate-limit wiring on the loop | `backend/routes/learn_loop.py::_screened` |
| The screens | the first statement of each handler in `routes/learn.py`, `routes/notes.py`, `routes/flashcards.py` (the notes actions: right after the note read, `screen_content_async` + `alongside`; a tutor start on a note's title: `crisis_support.screen_tutor_start_async` (`tutor.note_title_version`) + `alongside`; a flashcard generation on a graph concept: `concept_topic.topic_is_graph_concept` + `alongside`) |
| Flag registration | `backend/services/feature_flags.py::REGISTRY["crisis_support"]` |
| Event taxonomy / PostHog exclusion | `services/events_service.py::EVENT_TAXONOMY`, `services/posthog_client.py::_NOT_MIRRORED` |
| The card | `frontend/src/components/safety/CrisisSupportCard.tsx`, `frontend/src/lib/crisisSupport.ts` |
| Tests | `backend/tests/test_crisis_detection.py`, `backend/tests/test_crisis_support_routes.py`, the `crisis` cases in the frontend vitest suites |

## Adding a surface (or a limiter)

- **A new route that hands student-written text to a model** adds a
  `Surface` to `crisis_support.py`, calls the screen as its handler's first
  statement, returns the card with the route's neutral keys, adds a `Case` to
  `test_crisis_support_routes.py` (`test_every_surface_is_covered` fails
  until it does) and renders the card on its frontend surface. A route that
  reads text the student STORED rather than typed (like the notes actions)
  uses `screen_content_async` and runs its work through `alongside`
  instead, so the card shows beside the result (and beside any error it
  raises, whichever handler answers it); its `Case` sets
  `note_field`, which makes it a non-blocking (`CONTENT`) case.
  `test_no_student_text_reaches_a_model_unscreened` reads every write route
  of the modules that run a model (`MODEL_ROUTE_MODULES`): a route whose body
  carries free text must call the screen or be listed in `NOT_SCREENED` with
  why no model reads that text.
- **A new limiter on a covered route** (rate limit, budget, quota) goes
  AFTER the screen. `test_the_screen_precedes_every_limiter_on_the_route`
  fails if any call whose name reads as a limit, budget, quota or throttle
  sits above the screen in the handler, or if the route gains a route-level
  dependency (a dependency runs before the handler body, so before the
  screen). A limiter that must be a dependency needs the screen as a
  dependency listed before it: `crisis_support.screened` (+ the
  `CrisisAnswered` exception handler in `main.py`), as the learning loop's
  `_RATE_LIMITED` routes use it.
  `test_a_screen_dependency_precedes_every_rate_limit_dependency` pins those
  (after the kill switch, before the rate limit), and
  `test_an_inline_loop_screen_precedes_every_inline_limiter` the loop routes
  that limit inline.

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
  "cut myself some slack", "the hill I want to die on"), someone else's wish
  asked about ("Why does Hamlet want to die?", never the speaker's own: "I
  can't do this anymore, I want to die" matches), and technical compounds
  ("suicide squad", "suicide inhibitor", "suicide burn"). "this problem is
  killing me", "kill the process", "dying to know", "dead code", "kill
  switch" and "die roll" never match anything. **TOPIC_GUARDS** ("Durkheim",
  "euthanasia", "Hamlet", "theory of suicide", "essay on suicide", ...) veto
  MENTIONS in a text that names coursework. They never veto an explicit
  first-person phrase.
- **NEGATION_GUARDS** veto a phrase the student negates ("I don't want to
  die", "I'm not suicidal", "I would never kill myself"). The rules:
  - A negation reaches only within its own clause, at most two words: a
    comma, dash, bracket, "but"/"and"/"so" or a new "I" ends it, so "I'm not
    okay, I'll kill myself" and "I won't lie, I'm suicidal" match. It
    crosses a short aside set off on both sides right after the negation
    word: "I'm not, like, suicidal", "I am not (really) suicidal", "I am not,
    and never will be, suicidal" are negations; "I'm not, I swear, okay,
    I'll kill myself" (a new "I") and "not, want to kill myself" (a bare
    comma) are not. It also crosses a filler's comma ("like", "really",
    "honestly", "even", "you know", ...) right after the negation, straight
    into "suicidal": "I'm not like, suicidal", "I'm not really, suicidal",
    "I'm not even, like, suicidal" are negations. A filler completes nothing,
    so its comma is not a clause break; a content word completes the clause,
    so "I'm not okay, honestly, suicidal again" and "I'm not like, okay,
    suicidal" are two clauses and match. Past a filler's comma only
    "suicidal" is negated, since an act there can be a clause of its own:
    "Not really, kill myself" matches.
  - A hedge or a recovery about how much is still a negation: "I'm not so
    suicidal anymore", "I'm not too / that / as suicidal as last year",
    "I'm not more suicidal than usual", "I don't want to die more than
    anything", "I don't want to die so badly".
  - Only these say the phrase IS there, and negate nothing: "never (been |
    felt) (more | this | so | as) <phrase>" ("I have never been more
    suicidal"); "never wanted to <phrase> more (than) / so badly / as much
    as" ("I've never wanted to kill myself more than today"); a fear of the
    act or of stopping it right after the negation, adjective or verb ("I'm
    no longer afraid to kill myself", "I wouldn't hesitate to kill myself",
    "I don't fear killing myself", "I won't stop hurting myself", "I've never
    stopped being suicidal"; "not / never / won't hesitate to" is also an
    intent frame, so "I don't hesitate to hurt myself" matches); a negated
    negation ("I can't not think about killing myself"); and "this", which
    points at the state now ("I'm not usually this suicidal"). The
    comparative readings belong to "never" alone: "not as suicidal as" is a
    negation.
  - An idiom that introduces a statement ("I won't lie", "not gonna lie",
    "not gonna sugarcoat it", "I'm not kidding") negates nothing: "not gonna
    lie suicidal thoughts every day" matches.
  - A hedge about one's own STATE is a negation in its common forms: "I
    don't think I'm suicidal", "I'm not thinking I'm suicidal", "I don't
    (really) feel like / feel that I'm suicidal", "I don't think that I'm
    suicidal", "I don't believe I've been suicidal". One about an act or a
    plan ("I don't think I'll kill myself tonight", "I don't mean I'll kill
    myself") and "I'm not saying I'm suicidal" are not.
  - A negation the same sentence takes back does not veto: after "but",
    "though", "although", "except" or "yet" (within about 100 characters of
    the phrase), a first-person modal or intent that stands for the phrase —
    "I don't want to kill myself but I might", "(but I think I will)", "I
    don't want to die but I think I'm going to", "I'm not suicidal but I
    think about it a lot", "I won't kill myself but I'll probably do it". The
    modal has to end its clause (or carry only "do it", "anyway", "probably",
    "be", ...), so "I'm not suicidal but I'm stressed", "I don't want to die,
    but I am tired of exams", "but I could use some help" and "but I might
    drop out" keep the negation. The take-back reads across a comma, a dash
    or an ellipsis, which trail off inside the sentence ("I'm not
    suicidal... but I might be", "I don't want to die - but I might"), never
    across a full stop.

A comparative counts as the speaker's own state only with a first-person
lead: "I'm more suicidal than ever" is an explicit phrase, but "teens end up
feeling more suicidal on SSRIs" and "patients getting more suicidal" are
pharmacology, read as a mention (no first person, so no match). The price is
a subjectless fragment: "Never been this suicidal before" still matches
because it opens its sentence, but "been more suicidal lately" with no "I"
does not.

When several categories match, the most severe is reported: `acute_danger`,
then `suicidal_ideation`, then `self_harm`.

**A quotation is just text.** Crisis language inside quotation marks
matches exactly like the same words outside them, in a typed message and in
a note alike: 'a patient says "I want to kill myself"' matches. (An earlier
draft set a note's quotations aside when someone else was said to speak
them. Review kept finding the student's own words read as someone else's:
'Skipped the doctor appointment again, "I want to kill myself"', a chat log
pasted into a note. No phrase list can tell a quoted patient from a student
quoting themselves, so the exception was removed.) What makes a lecture
note quoting a patient or a play workable is the response, not the
detector: a match in a note shows the card beside the summary instead of
replacing it.

**To extend:** add a `Phrase` to `EXPLICIT` (choose its category, write the
pattern against the normalized form, reuse `_MYSELF` / `_INTENT`), or a
pattern to `GUARDS` / `NEGATION_GUARDS` / `TOPIC_GUARDS` for a new false
positive. Then add an example to `backend/tests/test_crisis_detection.py`.
The suite fails if a phrase has no positive example, or if a guard vetoes
none of the pinned negatives.

**Changing the detector safely.** Every fix to a phrase list risks breaking
sentences it was not written for, and review rounds of this detector did
exactly that. `backend/tests/crisis_corpus.py` is the check: several hundred
sentences (everyday, recovery and hedging text that must not match; clinical
third-person text that must not match; first-person crisis statements that
must match; the known misses and false positives, pinned), plus every string
the unit tests use. `crisis_corpus_base.json` stores what #890's first
reviewed detector (`BASE_COMMIT`) answered for each, and
`INTENDED_CHANGES_FROM_BASE` lists every sentence whose answer now differs,
with the reason. The suite fails on a sentence with the wrong outcome, on a
difference from the base that is not listed, and on a listed one that no
longer differs. To change the detector: add the motivating sentence to its
group, make the change, run `python -m tests.crisis_corpus` from `backend/`
(it prints base vs now for every differing sentence; `--all` for every
sentence) and list each new difference you meant, with its reason. A new
corpus sentence needs its base answer: `python -m tests.crisis_corpus
--write-base` (runs the base checkout's detector; `CRISIS_BASE_BACKEND`
points at it).

## Limits

- **Deterministic phrases miss indirect language.** "I just want everything
  to stop", "I won't be a problem much longer", "I've been giving my things
  away" and "I can't do this anymore" do not match. Leetspeak ("k1ll") and
  spaced-out letters do not match either. English only.
- **A filler's comma is crossed only into "suicidal".** "I'm not like,
  going to kill myself" is read as two clauses and matches; the filler list
  is closed, so an unlisted filler's comma ends the clause too.
- **A take-back is read only inside the negation's sentence and only in the
  listed forms.** An ellipsis or a dash does not end the sentence for this;
  a full stop does. "I'm not suicidal. But I might be" (a new sentence), "I'm
  not suicidal but I think about death a lot" (no "it" pointing back) and a
  reversal more than about 100 characters after the phrase keep the
  negation, so they do not match.
- **False positives remain, and cost the most on typed text.** A literature
  or psychology question TYPED to the tutor that uses an explicit
  first-person phrase ("the speaker says 'I want to die'") gets the card
  instead of an answer. So can a quiz option about suicide quoted in the
  quiz's "Ask about this" opening message.
- **A note's false positive costs the student nothing but the card.** A
  psychology or literature note that quotes a patient or a play ("a patient
  says 'I want to kill myself'", "Macbeth: 'I want to die'"), or names
  suicide in a first-person sentence with no topic word, shows the
  resources beside its summary (its concepts, its chat reply, its trip to
  the tutor) every time an AI action reads it, and logs a
  `safety.crisis_support_shown` event each time (the note chat, which
  re-reads the note every turn, at most once a day per note version).
  Nothing is withheld.
- **Send to tutor carries the note's title.** The tutor opens with the
  note's first title line as its topic. A start on that title unchanged,
  verified server-side as the student's own note's title, starts the
  session with the card beside it; if the student edits the topic first, it
  is typed text and blocks like any other.
- **A flashcard concept's name is course material.** The Flashcards page
  generates one concept per call with the concept's name as the topic. A
  name that matches one of the student's own graph concepts
  (`concept_topic.topic_is_graph_concept`, read only on a match) makes its
  cards with the card beside them, shown once per Start. A concept the
  student added by name that is not on their map is screened as typed and
  blocks.
- **A model-based screen** would catch indirect language. It would also need
  its own labelled eval set, measured false-negative and false-positive
  rates, eval spend, and a latency budget on every turn. It would also send
  the student's crisis text to a model provider, which this path never does.
  It would be a separate decision.
- **Only auth (and on the loop, its kill switch) comes first.** A loop
  route while the loop is switched off (404) is refused before the screen
  too. An unauthenticated or foreign request gets its
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
      material and the clean-up of an imported deck are not, and quiz
      answers are not (see "Checked and not covered").
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
blocking surface under `SAPLING_MODEL_MODE=function`, and asserts zero calls.
Its control turn proves the counter does see a model call when one is made.
A notes action whose note matched DOES run its model (the card is shown
beside the result), so under function mode it uses the notes tasks'
ordinary registered handlers.

## Verifying

- Backend: `cd backend && venv/bin/python -m pytest tests/test_crisis_detection.py tests/test_crisis_support_routes.py -q`.
- Frontend: `cd frontend && npx vitest run crisis` and the touched suites
  (`ChatPanel`, `LoopLearn`, `Learn.sessionState`, `AskPanel`, `DueQueue`,
  `RetentionCheck`, `notetaker/page.crisisSupport`, `flashcards/crisisSupport`,
  `useTutorHandoff.crisis`).
- E2E (flag off, so behaviour is unchanged): `tutor`, `streaming`,
  `learn-loop`, `learn-grade-recovery`, `quiz-journeys`, `study-guide`, `feature-flags`, `analytics`, `events`. Once
  the copy is approved, add a crisis journey and the card's a11y scan
  (`frontend/e2e/a11y.spec.ts`, spec §13 A135) with
  `SAPLING_FLAG_CRISIS_SUPPORT=on` in the stack. The card uses the
  `--info` / `--info-soft` / `--text` / `--text-dim` tokens and the shared
  `Dialog` (focus moves into it and returns on close), but it has not been
  through the axe lane yet.

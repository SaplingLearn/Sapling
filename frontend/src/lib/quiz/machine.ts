/**
 * The quiz session state machine — a pure reducer, no React, no network.
 *
 * Every effect (generate / answer / submit / navigate / persist) lives in
 * `useQuizSession`; this file only decides what the session looks like after an
 * event. That split is what makes the six invariants in §4 of the contract
 * testable at all: "nothing walks out of a live quiz by accident" is a property
 * of the transition table, not of a component tree.
 *
 * Unhandled events return the SAME object, so a caller can compare by identity
 * to see whether an event was accepted.
 */

import type { StudentConfidence } from "@/lib/api";
import { QUIZ_ERROR_COPY } from "./errors";
import type { EntryRequest } from "./source";
import type {
  AnswerResult,
  AttemptDetail,
  GenerateResult,
  Phase,
  QuizConfig,
  QuizIntent,
  QuizItem,
  QuizPrefs,
  QuizScope,
  QuizSession,
  SubmitResult,
  WireQuestion,
} from "./types";
import type { QuizError } from "./errors";
import { isWrittenType } from "./types";

/** What a "start this quiz" affordance has to say: the target and its framing. */
export interface StartRequest {
  intent: QuizIntent;
  scope: QuizScope;
  conceptId: string;
  courseId: string | null;
  /**
   * G5: the attempt whose misses this quiz re-serves. Omitted by every start
   * affordance — a fresh quiz practises nothing — and set only by `retry()`
   * re-issuing a practice run whose generation failed. `PRACTISE_MISSED` sets
   * it from the session instead; this is the one path that has to restate it,
   * because `START` deliberately clears it.
   */
  sourceAttemptId?: string | null;
}

export type SessionConfig = QuizSession["config"];

export type QuizEvent =
  | { type: "CONFIGURE"; open: boolean }
  | { type: "START"; start: StartRequest; config: SessionConfig }
  | { type: "GENERATED"; result: GenerateResult }
  | { type: "GENERATE_FAILED"; error: QuizError }
  | { type: "SELECT"; index: number }
  | { type: "WRITE"; text: string }
  /**
   * Learning-loop spec §13 A132: the current question's optional stated
   * confidence (A127's "Guessing" / "Fairly sure" / "Sure"; null takes a
   * choice back). Answer state like SELECT and WRITE: it lives on the item
   * until `/answer` carries it, so choosing makes no request and Submit never
   * waits on it. Accepted only while the current item is live (`active`, no
   * verdict) — once recorded, the server keeps the first response, so a
   * change afterwards would describe an answer it never went with.
   */
  | { type: "CONFIDENCE"; level: StudentConfidence | null }
  | { type: "SUBMIT_ANSWER" }
  | { type: "ANSWER_RECORDED"; result: AnswerResult }
  | { type: "ANSWER_FAILED"; error: QuizError }
  | { type: "NEXT" }
  /** Show question `index` — back to one already answered, or ahead to skip. */
  | { type: "GO_TO"; index: number }
  | { type: "REQUEST_LEAVE" }
  | { type: "CANCEL_LEAVE" }
  | { type: "CONFIRM_LEAVE" }
  | { type: "RESUME"; detail: AttemptDetail; stored: QuizSession | null }
  | { type: "FINISH" }
  | { type: "SUBMITTED"; result: SubmitResult; xp: QuizSession["xp"] }
  | { type: "SUBMIT_FAILED"; error: QuizError }
  /** `numQuestions` is already clamped to `/config`'s min/max by the caller —
   *  the reducer must never know those bounds. */
  | { type: "PRACTISE_MISSED"; missedCount: number; numQuestions: number }
  | { type: "NEXT_IN_QUEUE" }
  | { type: "EXIT" }
  /**
   * #760: the student stops waiting on a request. Before this, `generating` and
   * `submitting` had no way out at all — a `/generate` that never answered left
   * the skeleton up for good. From `generating` it goes home (nothing was
   * created that the client knows about); from `submitting` it goes BACK INTO
   * the quiz, on the final verdict, so the attempt stays live and the ordinary
   * exits (See results again, or Leave with its confirmation) still apply —
   * invariant 1 holds. The hook aborts the request; this only moves the phase.
   */
  | { type: "CANCEL" }
  | { type: "FLAG" }
  | { type: "DISMISS_ERROR" }
  // ── Two events beyond §4's list, both forced by effects that have nowhere
  //    else to land. Documented as such rather than smuggled in.
  /**
   * A failure with no phase of its own: `resume` 409s on an attempt that has
   * been closed (the 24h sweep, or a Discard on another device — G4), or the
   * initial load falls over. §4 lists a failure event
   * for generate, answer and submit but not for these, and swallowing a
   * `QUIZ_ATTEMPT_ABANDONED` would leave the resume strip permanently broken
   * with no explanation. Only accepted from a phase with nothing live.
   */
  | { type: "FAILED"; error: QuizError }
  /**
   * The Adjust dialog's "Done" (§5 B1.6) changes length/difficulty/feedback
   * WITHOUT starting a quiz, so the choice has to live somewhere before the
   * next `START` carries it. Only accepted where no attempt is in flight.
   */
  | { type: "SET_CONFIG"; config: SessionConfig };

/**
 * The count used before `GET /api/quiz/config` resolves. Not an option list —
 * the pickers render nothing until the real config arrives — just the scalar the
 * "5 questions, medium" line shows for the first paint. It matches the server's
 * own default (`GenerateQuizBody.num_questions = 5`).
 */
const PRE_CONFIG_COUNT = 5;
/** Likewise `GenerateQuizBody.difficulty = "medium"`. */
const PRE_CONFIG_DIFFICULTY = "medium";
const DEFAULT_FEEDBACK: SessionConfig["feedback"] = "at-end";

/** Session config from stored prefs, falling back to config-derived defaults
 *  (§5 B1): 5 questions if offered else the middle option; "medium" if offered
 *  else the first difficulty. */
export function defaultConfigFor(config: QuizConfig | null, prefs: QuizPrefs): SessionConfig {
  const options = config?.num_questions.options ?? [];
  const difficulties = config?.difficulties ?? [];
  const count =
    prefs.count
    ?? (options.includes(PRE_CONFIG_COUNT)
      ? PRE_CONFIG_COUNT
      : options[Math.floor(options.length / 2)] ?? PRE_CONFIG_COUNT);
  const difficulty =
    prefs.difficulty
    ?? (difficulties.includes(PRE_CONFIG_DIFFICULTY)
      ? PRE_CONFIG_DIFFICULTY
      : difficulties[0] ?? PRE_CONFIG_DIFFICULTY);
  return { count, difficulty, feedback: prefs.feedback ?? DEFAULT_FEEDBACK,
    ...(prefs.questionFormat && config?.question_types.includes(prefs.questionFormat) ? { questionFormat: prefs.questionFormat } : {}) };
}

function scopeForEntry(entry: EntryRequest): QuizScope {
  if (entry.scope === "due") return { kind: "due", queue: [] };
  if (entry.course) return { kind: "course", courseId: entry.course, queue: [] };
  return { kind: "concept", conceptId: entry.concept ?? "" };
}

/**
 * The session a fresh mount starts from: quiz home, nothing generated, the
 * entry's source already recorded so every later exit can honour it.
 *
 * Queues are left empty — `useQuizHome` fills them once the graph has loaded,
 * because the reducer has no access to the node list.
 */
export function initialSession(
  entry: EntryRequest,
  config: QuizConfig | null,
  prefs: QuizPrefs,
): QuizSession {
  return {
    intent: "practice",
    scope: scopeForEntry(entry),
    source: entry.source,
    config: defaultConfigFor(config, prefs),
    conceptId: entry.concept ?? "",
    courseId: entry.course ?? null,
    attemptId: null,
    items: [],
    cursor: 0,
    queueIndex: 0,
    phase: "home",
    error: null,
    result: null,
    xp: null,
    deliveredShort: false,
    sourceAttemptId: null,
    reserved: null,
  };
}

// ── Pure predicates the screens and the hook share ─────────────────────────

export function queueOf(scope: QuizScope): string[] {
  return scope.kind === "course" || scope.kind === "due" ? scope.queue : [];
}

/** Not yet recorded. A multiple-choice item restored from the server can
 *  carry its selection without a verdict, so a selection alone counts as
 *  recorded there — which is why GO_TO drops an unsubmitted draft selection
 *  when the student moves off it. */
export function isUnanswered(item: QuizItem): boolean {
  return !item.verdict && (isWrittenType(item.question.type) || item.selectedIndex === null);
}

export function firstUnansweredIndex(items: QuizItem[]): number {
  return items.findIndex(isUnanswered);
}

/** The next question still to answer after `from`, wrapping round to any the
 *  student skipped; -1 once every question is answered. */
export function nextUnansweredIndex(items: QuizItem[], from: number): number {
  for (let step = 1; step <= items.length; step++) {
    const index = (from + step) % items.length;
    if (isUnanswered(items[index])) return index;
  }
  return -1;
}

export function isLastItem(session: QuizSession, index = session.cursor): boolean {
  return index >= session.items.length - 1;
}

/** Submitting an answer needs a live question with a chosen option. */
export function canSubmitAnswer(session: QuizSession): boolean {
  if (session.phase !== "active") return false;
  const item = session.items[session.cursor];
  return item !== undefined && (isWrittenType(item.question.type)
    ? Boolean(item.answerText?.trim()) : item.selectedIndex !== null);
}

/** Leaving for another screen. False for every phase where an attempt is live —
 *  those exit through the leave dialog (CONFIRM_LEAVE) or the submit path, and
 *  `submitting` through CANCEL back into the quiz first.
 *
 *  `generating` is exitable (#760): no attempt exists client-side yet, so
 *  there is nothing live to walk out of — only a request, which the hook aborts.
 *  Refusing it left a hung `/generate` with no way off the skeleton. */
export function canExit(session: QuizSession): boolean {
  return session.phase !== "active"
    && session.phase !== "answered"
    && session.phase !== "confirm-leave"
    && session.phase !== "submitting";
}

/** A request owns the phase: its outcome event is the only thing that should
 *  move it (besides CANCEL). */
function awaitingRequest(session: QuizSession): boolean {
  return session.phase === "generating" || session.phase === "submitting";
}

/** The phase a live quiz rests on when nothing is pending: on the current
 *  item's verdict if it has one (as CANCEL_LEAVE and RESUME also decide). */
function settledPhase(session: QuizSession): Phase {
  return session.items[session.cursor]?.verdict != null ? "answered" : "active";
}

/**
 * Where `DISMISS_ERROR` puts the student back.
 *
 * Derived rather than stored, so `QuizSession` stays exactly the §2 shape. The
 * three failures are distinguishable from the session alone: a generate failure
 * has no attempt and no items; a submit failure has a verdict on every item
 * (the submit path is only reachable once the last answer is recorded); an
 * answer failure leaves the current item without one.
 */
export function errorReturnPhase(session: QuizSession): Phase {
  if (session.attemptId === null || session.items.length === 0) return "home";
  return session.items.every(i => i.verdict !== null) ? "submitting" : "active";
}

// ── The reducer ────────────────────────────────────────────────────────────

function itemsFor(questions: WireQuestion[]): QuizItem[] {
  return questions.map((question, index) => ({
    index,
    question,
    selectedIndex: null,
    verdict: null,
    flagged: false,
    confidence: null,
  }));
}

/** The state every fresh generation starts from: attempt, items, verdicts,
 *  result and XP all cleared, so a failure can never show the previous quiz. */
function generatingFrom(
  session: QuizSession,
  patch: Partial<QuizSession>,
): QuizSession {
  return {
    ...session,
    // G5: a generation practises a past attempt only when the patch says so —
    // which is why this one sits BEFORE the spread and the rest below it.
    // Leaving the previous session's source in place would make the NEXT quiz
    // re-serve the same items.
    sourceAttemptId: null,
    ...patch,
    phase: "generating",
    attemptId: null,
    items: [],
    cursor: 0,
    error: null,
    result: null,
    xp: null,
    deliveredShort: false,
    reserved: null,
  };
}

function withItem(session: QuizSession, index: number, patch: Partial<QuizItem>): QuizSession {
  return {
    ...session,
    items: session.items.map((item, i) => (i === index ? { ...item, ...patch } : item)),
  };
}

/** Where an answered item goes next: hold on the verdict, step forward, or
 *  finish. `at-end` never stops on `answered` — that's the whole of R-2's
 *  client-side half. */
function advanceAfterAnswer(session: QuizSession, index: number): QuizSession {
  if (session.config.feedback === "as-you-go") {
    return { ...session, phase: "answered", cursor: index };
  }
  // At-end moves straight on — to the next question still unanswered, which
  // is not always index + 1 once the student can skip around. Submitting
  // waits until every question is answered, not until the last one is.
  const next = nextUnansweredIndex(session.items, index);
  return next < 0
    ? { ...session, phase: "submitting", cursor: index }
    : { ...session, phase: "active", cursor: next };
}

type QuizEventType = QuizEvent["type"];
type EventOf<T extends QuizEventType> = Extract<QuizEvent, { type: T }>;
type Handler<T extends QuizEventType> = (session: QuizSession, event: EventOf<T>) => QuizSession;

function inPhase(session: QuizSession, ...phases: Phase[]): boolean {
  return phases.includes(session.phase);
}

function onConfigure(session: QuizSession, event: EventOf<"CONFIGURE">): QuizSession {
  if (!inPhase(session, "home", "configuring")) return session;
  return { ...session, phase: event.open ? "configuring" : "home" };
}

function onStart(session: QuizSession, event: EventOf<"START">): QuizSession {
  if (!inPhase(session, "home", "configuring", "results")) return session;
  // `source` is deliberately not settable here: invariant 2 (source is
  // identical on entry and on every terminal transition) holds structurally
  // because no event can overwrite it except RESUME's stored restore.
  return generatingFrom(session, {
    intent: event.start.intent,
    scope: event.start.scope,
    conceptId: event.start.conceptId,
    courseId: event.start.courseId,
    config: event.config,
    queueIndex: 0,
    // `?? null`, never the bare optional: an explicit `undefined` in the
    // patch would overwrite `generatingFrom`'s own null and put a value
    // outside the type into the session.
    sourceAttemptId: event.start.sourceAttemptId ?? null,
  });
}

function onGenerated(session: QuizSession, event: EventOf<"GENERATED">): QuizSession {
  if (session.phase !== "generating") return session;
  const { result } = event;
  if (result.questions.length === 0) {
    // The route 502s rather than serving an empty quiz (R1 §C), so this is
    // belt and braces — but a blank, control-less panel is exactly the #184
    // bug, and it is cheap to make impossible.
    return {
      ...session,
      phase: "error",
      error: {
        code: "QUIZ_GENERATION_FAILED",
        message: QUIZ_ERROR_COPY.QUIZ_GENERATION_FAILED,
        retryable: true,
      },
    };
  }
  return {
    ...session,
    phase: "active",
    attemptId: result.quiz_id,
    items: itemsFor(result.questions),
    cursor: 0,
    error: null,
    deliveredShort: result.delivered_count < result.requested_count,
    // G5: absent whenever the request didn't name a source attempt, which
    // is the same thing as "there is nothing to claim about re-serving".
    reserved: result.source
      ? {
        reservedCount: result.source.reserved_count,
        regeneratedCount: result.source.regenerated_count,
      }
      : null,
  };
}

function onGenerateFailed(session: QuizSession, event: EventOf<"GENERATE_FAILED">): QuizSession {
  if (session.phase !== "generating") return session;
  return { ...session, phase: "error", error: event.error };
}

function onWrite(session: QuizSession, event: EventOf<"WRITE">): QuizSession {
  if (session.phase !== "active") return session;
  const item = session.items[session.cursor];
  if (!item || item.verdict || !isWrittenType(item.question.type)) return session;
  return withItem(session, session.cursor, { answerText: event.text.slice(0, 2000) });
}

function onSelect(session: QuizSession, event: EventOf<"SELECT">): QuizSession {
  if (session.phase !== "active") return session;
  if (!session.items[session.cursor]) return session;
  return withItem(session, session.cursor, { selectedIndex: event.index });
}

function onConfidence(session: QuizSession, event: EventOf<"CONFIDENCE">): QuizSession {
  if (session.phase !== "active") return session;
  const item = session.items[session.cursor];
  if (!item || item.verdict) return session;
  if ((item.confidence ?? null) === event.level) return session;
  return withItem(session, session.cursor, { confidence: event.level });
}

function onSubmitAnswer(session: QuizSession): QuizSession {
  // State-neutral by design: the network call is the hook's job and the
  // "pending" look is local to the footer button. `canSubmitAnswer` is the
  // predicate that actually gates it, in the hook and on the button alike.
  return session;
}

function onAnswerRecorded(session: QuizSession, event: EventOf<"ANSWER_RECORDED">): QuizSession {
  if (session.phase !== "active") return session;
  const index = event.result.question_index;
  const target = session.items[index];
  if (!target) return session;
  // A response for an item already left behind can only be a duplicate or a
  // late arrival. `advanceAfterAnswer` positions the cursor from the
  // RESPONDED index, so honouring one would drag the quiz backwards under
  // the student — re-revealing an old verdict in as-you-go, or re-asking a
  // question in at-end. `/answer` is idempotent server-side, so there is
  // nothing to reconcile: drop it.
  if (index < session.cursor || target.verdict !== null) return session;
  // `recorded: false` is an idempotent replay or a lost race — the answer
  // still stands, so it advances exactly like a fresh record (invariant 6).
  const scored = withItem(session, index, {
    ...(event.result.answer_text !== undefined ? { answerText: event.result.answer_text } : {}),
    verdict: {
      isCorrect: event.result.is_correct,
      correctIndex: event.result.correct_index,
      correctAnswer: event.result.correct_answer,
      explanation: event.result.explanation,
    },
  });
  return advanceAfterAnswer(scored, index);
}

function onAnswerFailed(session: QuizSession, event: EventOf<"ANSWER_FAILED">): QuizSession {
  if (session.phase !== "active") return session;
  return { ...session, phase: "error", error: event.error };
}

function onNext(session: QuizSession): QuizSession {
  if (session.phase !== "answered") return session;
  // On to the next question still unanswered (skipped ones included);
  // results once there are none.
  const next = nextUnansweredIndex(session.items, session.cursor);
  return next < 0
    ? { ...session, phase: "submitting" }
    : { ...session, phase: "active", cursor: next };
}

function onGoTo(session: QuizSession, event: EventOf<"GO_TO">): QuizSession {
  // Moving between questions, either way. Never mid-request or mid-dialog:
  // only from a question that is on screen and waiting.
  if (!inPhase(session, "active", "answered")) return session;
  const target = session.items[event.index];
  if (!target || event.index === session.cursor) return session;
  // An unsubmitted multiple-choice pick is dropped on the way out: a
  // selection with no verdict reads as RECORDED (see isUnanswered), and a
  // draft must never be mistaken for an answer the server has. A written
  // draft is kept — its text never counts as recorded.
  const current = session.items[session.cursor];
  const left = current && !current.verdict && !isWrittenType(current.question.type) && session.phase === "active"
    ? withItem(session, session.cursor, { selectedIndex: null })
    : session;
  return { ...left, cursor: event.index, phase: isUnanswered(target) ? "active" : "answered" };
}

function onFinish(session: QuizSession): QuizSession {
  if (!inPhase(session, "active", "answered")) return session;
  if (session.items.length === 0) return session;
  if (session.items.some(i => i.selectedIndex === null && !i.verdict)) return session;
  return { ...session, phase: "submitting" };
}

function onRequestLeave(session: QuizSession): QuizSession {
  if (!inPhase(session, "active", "answered")) return session;
  return { ...session, phase: "confirm-leave" };
}

function onCancelLeave(session: QuizSession): QuizSession {
  if (session.phase !== "confirm-leave") return session;
  // A verdict on the current item means it was on screen when the dialog
  // opened — in `at-end` mode the cursor always sits on a fresh item.
  const showing = session.items[session.cursor]?.verdict != null;
  return { ...session, phase: showing ? "answered" : "active" };
}

function onConfirmLeave(session: QuizSession): QuizSession {
  if (session.phase !== "confirm-leave") return session;
  return { ...session, phase: "paused" };
}

function onResume(session: QuizSession, event: EventOf<"RESUME">): QuizSession {
  if (!inPhase(session, "paused", "home")) return session;
  return resumeFrom(session, event.detail, event.stored);
}

function onSubmitted(session: QuizSession, event: EventOf<"SUBMITTED">): QuizSession {
  if (session.phase !== "submitting") return session;
  return { ...session, phase: "results", result: event.result, xp: event.xp, error: null };
}

function onSubmitFailed(session: QuizSession, event: EventOf<"SUBMIT_FAILED">): QuizSession {
  if (session.phase !== "submitting") return session;
  return { ...session, phase: "error", error: event.error };
}

function onPractiseMissed(session: QuizSession, event: EventOf<"PRACTISE_MISSED">): QuizSession {
  if (session.phase !== "results") return session;
  // A new attempt on the same concept (R-5), naming the attempt just
  // finished as its source: G5 re-serves the items that were actually
  // missed rather than writing new ones (backend #537 G5). What comes
  // back may still be regenerated in part or in whole — the results
  // eyebrow reads `reserved` and says which happened.
  return generatingFrom(session, {
    intent: "review",
    scope: {
      kind: "missed",
      conceptId: session.conceptId,
      missedCount: event.missedCount,
    },
    config: { ...session.config, count: event.numQuestions },
    sourceAttemptId: session.attemptId,
  });
}

function onNextInQueue(session: QuizSession): QuizSession {
  if (session.phase !== "results") return session;
  const queue = queueOf(session.scope);
  const next = session.queueIndex + 1;
  if (next >= queue.length) return session;
  return generatingFrom(session, {
    queueIndex: next,
    conceptId: queue[next],
    // A `course` queue stays inside its course. A `due` queue spans them,
    // and the reducer has no node list to look the new one up in — so the
    // honest answer is "unknown" rather than the previous concept's course.
    // Nothing on screen reads this: the screens resolve the course (and the
    // accent) from the graph by concept id.
    courseId: session.scope.kind === "course" ? session.courseId : null,
  });
}

function onExit(session: QuizSession): QuizSession {
  if (!canExit(session)) return session;
  // A genuinely clean home session. `source` survives (invariant 2) and so
  // do the student's config choices; the TARGET does not. "Done" stays on
  // /quiz, so a session still pointing at the concept just finished would
  // keep the accent — and anything else that prefers the session over the
  // proposal — pinned to a quiz that is over.
  //
  // Callers must therefore read the exit destination from the session
  // BEFORE dispatching this (`returnToSource` needs `conceptId`).
  return {
    ...session,
    phase: "home",
    scope: { kind: "concept", conceptId: "" },
    conceptId: "",
    courseId: null,
    attemptId: null,
    items: [],
    cursor: 0,
    queueIndex: 0,
    error: null,
    result: null,
    xp: null,
    deliveredShort: false,
    sourceAttemptId: null,
    reserved: null,
  };
}

function onCancel(session: QuizSession): QuizSession {
  if (session.phase === "generating") {
    // Back to the same concept on home, minus any practice framing: the
    // student asked to stop, not to keep "the ones you missed" queued.
    return { ...session, phase: "home", error: null, sourceAttemptId: null, reserved: null };
  }
  if (session.phase === "submitting") {
    return { ...session, phase: settledPhase(session), error: null };
  }
  return session;
}

function onFlag(session: QuizSession): QuizSession {
  const item = session.items[session.cursor];
  if (!item) return session;
  return withItem(session, session.cursor, { flagged: !item.flagged });
}

function onDismissError(session: QuizSession): QuizSession {
  if (session.phase !== "error") return session;
  return { ...session, phase: errorReturnPhase(session), error: null };
}

function onFailed(session: QuizSession, event: EventOf<"FAILED">): QuizSession {
  // Never over a live attempt — an in-flight quiz has ANSWER_FAILED /
  // SUBMIT_FAILED, which keep the items so DISMISS_ERROR can go back to them.
  // Nor over a request's own phase: a stale resume failing mid-generate must
  // not replace the generation the student is waiting on.
  if (!canExit(session) || awaitingRequest(session)) return session;
  if (session.phase === "error") return session;
  return { ...session, phase: "error", error: event.error };
}

function onSetConfig(session: QuizSession, event: EventOf<"SET_CONFIG">): QuizSession {
  if (!inPhase(session, "home", "configuring", "results")) return session;
  return { ...session, config: event.config };
}

/** One handler per event type. The `satisfies` makes a missing (or misspelt)
 *  event type a compile error rather than a silently ignored event. */
const HANDLERS = {
  CONFIGURE: onConfigure,
  START: onStart,
  GENERATED: onGenerated,
  GENERATE_FAILED: onGenerateFailed,
  WRITE: onWrite,
  SELECT: onSelect,
  CONFIDENCE: onConfidence,
  SUBMIT_ANSWER: onSubmitAnswer,
  ANSWER_RECORDED: onAnswerRecorded,
  ANSWER_FAILED: onAnswerFailed,
  NEXT: onNext,
  GO_TO: onGoTo,
  FINISH: onFinish,
  REQUEST_LEAVE: onRequestLeave,
  CANCEL_LEAVE: onCancelLeave,
  CONFIRM_LEAVE: onConfirmLeave,
  RESUME: onResume,
  SUBMITTED: onSubmitted,
  SUBMIT_FAILED: onSubmitFailed,
  PRACTISE_MISSED: onPractiseMissed,
  NEXT_IN_QUEUE: onNextInQueue,
  EXIT: onExit,
  CANCEL: onCancel,
  FLAG: onFlag,
  DISMISS_ERROR: onDismissError,
  FAILED: onFailed,
  SET_CONFIG: onSetConfig,
} satisfies { [T in QuizEventType]: Handler<T> };

export function reduce(session: QuizSession, event: QuizEvent): QuizSession {
  // An event type with no handler (only reachable through a cast) is
  // unhandled like any other: the same object back.
  if (!Object.prototype.hasOwnProperty.call(HANDLERS, event.type)) return session;
  const handler = HANDLERS[event.type] as (s: QuizSession, e: QuizEvent) => QuizSession;
  return handler(session, event);
}

// ── Resume ─────────────────────────────────────────────────────────────────

type WireResponse = AttemptDetail["responses"][number];

/** A written answer's verdict as the resume payload alone can state it: it
 *  carries `is_correct` but no correct index and no explanation. */
function wireVerdict(question: WireQuestion, response: WireResponse | undefined): QuizItem["verdict"] {
  return isWrittenType(question.type) && response
    ? { isCorrect: response.is_correct, correctIndex: -1, explanation: "" }
    : null;
}

/** §13 A132: an answered question's stated confidence is the one its recorded
 *  response carries (null = none was stated) — the server's word, like the
 *  answer itself. An unanswered one keeps the choice this browser saved before
 *  it left. */
function resumedConfidence(previous: QuizItem | undefined, response: WireResponse | undefined): StudentConfidence | null {
  if (response) return response.confidence ?? null;
  return previous?.confidence ?? null;
}

function resumedItem(
  question: WireQuestion,
  index: number,
  previous: QuizItem | undefined,
  response: WireResponse | undefined,
): QuizItem {
  const selected = response?.selected_index;
  return {
    index,
    question,
    selectedIndex: selected ?? previous?.selectedIndex ?? null,
    answerText: response?.answer_text ?? previous?.answerText,
    verdict: selected === undefined ? null : previous?.verdict ?? wireVerdict(question, response),
    flagged: previous?.flagged ?? false,
    confidence: resumedConfidence(previous, response),
  };
}

function resumedItems(detail: AttemptDetail, matching: QuizSession | null): QuizItem[] {
  const storedById = new Map((matching?.items ?? []).map(i => [i.question.id, i]));
  const responsesByIndex = new Map((detail.responses ?? []).map(r => [r.question_index, r]));
  return (detail.questions ?? []).map((question, index) =>
    resumedItem(question, index, storedById.get(question.id), responsesByIndex.get(index)));
}

function resumedPosition(items: QuizItem[]): { cursor: number; phase: Phase } {
  const unanswered = firstUnansweredIndex(items);
  if (unanswered >= 0) return { cursor: unanswered, phase: "active" };
  // Every question already answered but the attempt never submitted (the last
  // `/answer` landed and then the tab went away). Park on the final verdict so
  // "See results" is one press away, rather than deadlocking on an empty cursor.
  const cursor = Math.max(items.length - 1, 0);
  return { cursor, phase: items[cursor]?.verdict != null ? "answered" : "active" };
}

function resumedConfig(
  session: QuizSession,
  detail: AttemptDetail,
  matching: QuizSession | null,
): SessionConfig {
  return matching
    ? matching.config
    : { ...session.config, difficulty: detail.difficulty || session.config.difficulty };
}

/** The framing only the stored session knows, falling back to the session's
 *  own (or the wire's concept) when nothing for this attempt was stored. */
function resumedFraming(
  session: QuizSession,
  detail: AttemptDetail,
  matching: QuizSession | null,
): Pick<QuizSession, "intent" | "scope" | "source" | "conceptId" | "courseId" | "queueIndex"> {
  return {
    intent: matching?.intent ?? session.intent,
    scope: matching?.scope ?? { kind: "concept", conceptId: detail.concept_node_id },
    source: matching?.source ?? session.source,
    conceptId: detail.concept_node_id || matching?.conceptId || session.conceptId,
    courseId: matching?.courseId ?? session.courseId,
    queueIndex: matching?.queueIndex ?? 0,
  };
}

/** G5: only the stored session knows this attempt was a practice run and what
 *  it re-served — the resume payload has no idea. Without the carry a resumed
 *  practice quiz would lose its eyebrow. */
function resumedPractice(
  matching: QuizSession | null,
): Pick<QuizSession, "deliveredShort" | "sourceAttemptId" | "reserved"> {
  return {
    deliveredShort: matching?.deliveredShort ?? false,
    sourceAttemptId: matching?.sourceAttemptId ?? null,
    reserved: matching?.reserved ?? null,
  };
}

/**
 * Rebuilds a live session off `GET /api/quiz/attempts/{id}` plus whatever the
 * browser had stored.
 *
 * The wire is the authority on which questions exist and which are answered;
 * the stored session is the only place the verdicts, the scope, the queue and
 * the original source survive (the resume payload carries `is_correct` but no
 * `correct_index` and no explanation, and the questions are keyless). A stored
 * record for a DIFFERENT attempt is ignored entirely.
 */
function resumeFrom(
  session: QuizSession,
  detail: AttemptDetail,
  stored: QuizSession | null,
): QuizSession {
  const matching = stored && stored.attemptId === detail.quiz_id ? stored : null;
  const items = resumedItems(detail, matching);
  return {
    ...session,
    ...resumedFraming(session, detail, matching),
    config: resumedConfig(session, detail, matching),
    attemptId: detail.quiz_id,
    items,
    ...resumedPosition(items),
    error: null,
    result: null,
    xp: null,
    ...resumedPractice(matching),
  };
}

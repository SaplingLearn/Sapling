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

/** What a "start this quiz" affordance has to say: the target and its framing. */
export interface StartRequest {
  intent: QuizIntent;
  scope: QuizScope;
  conceptId: string;
  courseId: string | null;
}

export type SessionConfig = QuizSession["config"];

export type QuizEvent =
  | { type: "CONFIGURE"; open: boolean }
  | { type: "START"; start: StartRequest; config: SessionConfig }
  | { type: "GENERATED"; result: GenerateResult }
  | { type: "GENERATE_FAILED"; error: QuizError }
  | { type: "SELECT"; index: number }
  | { type: "SUBMIT_ANSWER" }
  | { type: "ANSWER_RECORDED"; result: AnswerResult }
  | { type: "ANSWER_FAILED"; error: QuizError }
  | { type: "NEXT" }
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
  | { type: "FLAG" }
  | { type: "DISMISS_ERROR" }
  // ── Two events beyond §4's list, both forced by effects that have nowhere
  //    else to land. Documented as such rather than smuggled in.
  /**
   * A failure with no phase of its own: `resume` 409s on an attempt the 24h
   * sweep abandoned, or the initial load falls over. §4 lists a failure event
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
  return { count, difficulty, feedback: prefs.feedback ?? DEFAULT_FEEDBACK };
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
  };
}

// ── Pure predicates the screens and the hook share ─────────────────────────

export function queueOf(scope: QuizScope): string[] {
  return scope.kind === "course" || scope.kind === "due" ? scope.queue : [];
}

export function firstUnansweredIndex(items: QuizItem[]): number {
  return items.findIndex(i => i.selectedIndex === null);
}

export function isLastItem(session: QuizSession, index = session.cursor): boolean {
  return index >= session.items.length - 1;
}

/** Submitting an answer needs a live question with a chosen option. */
export function canSubmitAnswer(session: QuizSession): boolean {
  if (session.phase !== "active") return false;
  const item = session.items[session.cursor];
  return item !== undefined && item.selectedIndex !== null;
}

/** Leaving for another screen. False for every phase where an attempt is live —
 *  those exit through the leave dialog (CONFIRM_LEAVE) or the submit path. */
export function canExit(session: QuizSession): boolean {
  return session.phase !== "active"
    && session.phase !== "answered"
    && session.phase !== "confirm-leave"
    && session.phase !== "generating"
    && session.phase !== "submitting";
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
    ...patch,
    phase: "generating",
    attemptId: null,
    items: [],
    cursor: 0,
    error: null,
    result: null,
    xp: null,
    deliveredShort: false,
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
  return isLastItem(session, index)
    ? { ...session, phase: "submitting", cursor: index }
    : { ...session, phase: "active", cursor: index + 1 };
}

export function reduce(session: QuizSession, event: QuizEvent): QuizSession {
  switch (event.type) {
    case "CONFIGURE": {
      if (session.phase !== "home" && session.phase !== "configuring") return session;
      return { ...session, phase: event.open ? "configuring" : "home" };
    }

    case "START": {
      if (session.phase !== "home" && session.phase !== "configuring" && session.phase !== "results") {
        return session;
      }
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
      });
    }

    case "GENERATED": {
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
      };
    }

    case "GENERATE_FAILED": {
      if (session.phase !== "generating") return session;
      return { ...session, phase: "error", error: event.error };
    }

    case "SELECT": {
      if (session.phase !== "active") return session;
      if (!session.items[session.cursor]) return session;
      return withItem(session, session.cursor, { selectedIndex: event.index });
    }

    case "SUBMIT_ANSWER": {
      // State-neutral by design: the network call is the hook's job and the
      // "pending" look is local to the footer button. `canSubmitAnswer` is the
      // predicate that actually gates it, in the hook and on the button alike.
      return session;
    }

    case "ANSWER_RECORDED": {
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
        verdict: {
          isCorrect: event.result.is_correct,
          correctIndex: event.result.correct_index,
          explanation: event.result.explanation,
        },
      });
      return advanceAfterAnswer(scored, index);
    }

    case "ANSWER_FAILED": {
      if (session.phase !== "active") return session;
      return { ...session, phase: "error", error: event.error };
    }

    case "NEXT": {
      if (session.phase !== "answered") return session;
      return isLastItem(session)
        ? { ...session, phase: "submitting" }
        : { ...session, phase: "active", cursor: session.cursor + 1 };
    }

    case "FINISH": {
      if (session.phase !== "active" && session.phase !== "answered") return session;
      if (session.items.length === 0) return session;
      if (session.items.some(i => i.selectedIndex === null)) return session;
      return { ...session, phase: "submitting" };
    }

    case "REQUEST_LEAVE": {
      if (session.phase !== "active" && session.phase !== "answered") return session;
      return { ...session, phase: "confirm-leave" };
    }

    case "CANCEL_LEAVE": {
      if (session.phase !== "confirm-leave") return session;
      // A verdict on the current item means it was on screen when the dialog
      // opened — in `at-end` mode the cursor always sits on a fresh item.
      const showing = session.items[session.cursor]?.verdict != null;
      return { ...session, phase: showing ? "answered" : "active" };
    }

    case "CONFIRM_LEAVE": {
      if (session.phase !== "confirm-leave") return session;
      return { ...session, phase: "paused" };
    }

    case "RESUME": {
      if (session.phase !== "paused" && session.phase !== "home") return session;
      return resumeFrom(session, event.detail, event.stored);
    }

    case "SUBMITTED": {
      if (session.phase !== "submitting") return session;
      return { ...session, phase: "results", result: event.result, xp: event.xp, error: null };
    }

    case "SUBMIT_FAILED": {
      if (session.phase !== "submitting") return session;
      return { ...session, phase: "error", error: event.error };
    }

    case "PRACTISE_MISSED": {
      if (session.phase !== "results") return session;
      // A new attempt on the same concept (R-5). The repetition guard means the
      // questions differ; the UI labels that honestly.
      return generatingFrom(session, {
        intent: "review",
        scope: {
          kind: "missed",
          conceptId: session.conceptId,
          missedCount: event.missedCount,
        },
        config: { ...session.config, count: event.numQuestions },
      });
    }

    case "NEXT_IN_QUEUE": {
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

    case "EXIT": {
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
      };
    }

    case "FLAG": {
      const item = session.items[session.cursor];
      if (!item) return session;
      return withItem(session, session.cursor, { flagged: !item.flagged });
    }

    case "DISMISS_ERROR": {
      if (session.phase !== "error") return session;
      return { ...session, phase: errorReturnPhase(session), error: null };
    }

    case "FAILED": {
      // Never over a live attempt — an in-flight quiz has ANSWER_FAILED /
      // SUBMIT_FAILED, which keep the items so DISMISS_ERROR can go back to them.
      if (!canExit(session)) return session;
      if (session.phase === "error") return session;
      return { ...session, phase: "error", error: event.error };
    }

    case "SET_CONFIG": {
      if (session.phase !== "home" && session.phase !== "configuring" && session.phase !== "results") {
        return session;
      }
      return { ...session, config: event.config };
    }

    default:
      return session;
  }
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
  const storedById = new Map((matching?.items ?? []).map(i => [i.question.id, i]));
  const selectedByIndex = new Map(
    (detail.responses ?? []).map(r => [r.question_index, r.selected_index]),
  );

  const items: QuizItem[] = (detail.questions ?? []).map((question, index) => {
    const previous = storedById.get(question.id);
    const selected = selectedByIndex.get(index);
    return {
      index,
      question,
      selectedIndex: selected ?? previous?.selectedIndex ?? null,
      verdict: selected === undefined ? null : previous?.verdict ?? null,
      flagged: previous?.flagged ?? false,
    };
  });

  const unanswered = firstUnansweredIndex(items);
  // Every question already answered but the attempt never submitted (the last
  // `/answer` landed and then the tab went away). Park on the final verdict so
  // "See results" is one press away, rather than deadlocking on an empty cursor.
  const cursor = unanswered >= 0 ? unanswered : Math.max(items.length - 1, 0);
  const phase: Phase =
    unanswered >= 0 ? "active" : items[cursor]?.verdict != null ? "answered" : "active";

  return {
    ...session,
    intent: matching?.intent ?? session.intent,
    scope: matching?.scope ?? { kind: "concept", conceptId: detail.concept_node_id },
    source: matching?.source ?? session.source,
    config: matching
      ? matching.config
      : { ...session.config, difficulty: detail.difficulty || session.config.difficulty },
    conceptId: detail.concept_node_id || matching?.conceptId || session.conceptId,
    courseId: matching?.courseId ?? session.courseId,
    queueIndex: matching?.queueIndex ?? 0,
    attemptId: detail.quiz_id,
    items,
    cursor,
    phase,
    error: null,
    result: null,
    xp: null,
    deliveredShort: matching?.deliveredShort ?? false,
  };
}

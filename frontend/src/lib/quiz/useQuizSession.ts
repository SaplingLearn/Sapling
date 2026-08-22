"use client";

/**
 * The only place quiz effects happen: generate, answer, submit, navigate,
 * persist.
 *
 * `machine.ts` decides what the session looks like after an event and nothing
 * else. This hook drives it — it applies an event, reads the state that came
 * back, and fires whatever that state calls for. Chaining off the RETURNED
 * session rather than off a phase-watching `useEffect` is deliberate: an effect
 * keyed on `phase === "submitting"` re-fires whenever that phase is re-entered
 * (a dismissed submit error does exactly that), and double-submitting an attempt
 * is a 409 the student would have to read.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { answerQuestion, generateQuiz, getAttempt, submitQuiz } from "./api";
import { QUIZ_ERROR_COPY, describeQuizError, type QuizError } from "./errors";
import { returnToSource } from "./exits";
import {
  canExit,
  canSubmitAnswer,
  defaultConfigFor,
  errorReturnPhase,
  initialSession,
  reduce,
  type QuizEvent,
  type SessionConfig,
  type StartRequest,
} from "./machine";
import { loadPrefs, savePrefs } from "./prefs";
import { clearSession, persistSession, loadSession } from "./session";
import type { EntryRequest } from "./source";
import { useGamificationDelta } from "./useGamificationDelta";
import { useQuizConfig } from "./useQuizConfig";
import type { QuizConfig, QuizSession, SubmitResult } from "./types";

export interface QuizActions {
  configure(open: boolean): void;
  setConfig(config: SessionConfig): void;
  start(request: StartRequest, config?: SessionConfig): void;
  select(index: number): void;
  submitAnswer(): void;
  next(): void;
  finish(): void;
  requestLeave(): void;
  cancelLeave(): void;
  confirmLeave(): void;
  resume(attemptId: string): void;
  practiseMissed(): void;
  nextInQueue(): void;
  exit(target?: string): void;
  flag(): void;
  dismissError(): void;
  retry(): void;
}

export interface QuizSessionHandle {
  session: QuizSession;
  /** A quiz call is in flight. The phase alone can't say so — `active` covers
   *  both "waiting for you" and "waiting for the server". */
  pending: boolean;
  config: QuizConfig | null;
  actions: QuizActions;
}

function clamp(value: number, min: number, max: number): number {
  return Math.min(Math.max(value, min), max);
}

/**
 * Tell any mounted graph that mastery just moved.
 *
 * Refreshing the tree after a quiz has always been purely navigational — leave
 * the quiz, land on `/tree`, and its own mount-time `getGraph` picks up the new
 * score (R5 §C). That still works, but it is nothing for a graph already on
 * screen, so submit announces itself. Cheap and advisory: nothing listens today
 * and nothing has to.
 *
 * Dispatched here rather than from the results screen because this is the one
 * place that knows a submit actually LANDED — a component firing it on render
 * would repeat it on every re-render of the same result.
 */
function announceGraphChanged(conceptId: string, result: SubmitResult): void {
  if (typeof window === "undefined") return;
  window.dispatchEvent(
    new CustomEvent("sapling:graph-changed", {
      detail: {
        conceptId,
        masteryBefore: result.mastery_before,
        masteryAfter: result.mastery_after,
      },
    }),
  );
}

/**
 * Retries exactly once, and only for a transport failure.
 *
 * `/answer` is idempotent on `(attempt_id, question_index)`, so a retry after a
 * dropped connection is safe: if the first call actually landed, the second
 * returns the recorded response with `recorded: false`, which the machine
 * advances on regardless (invariant 6). A 4xx is never retried — repeating a
 * rejected request just spends the student's rate limit.
 */
async function withNetworkRetry<T>(call: () => Promise<T>): Promise<T> {
  try {
    return await call();
  } catch (err) {
    if (describeQuizError(err).code !== "NETWORK") throw err;
    return call();
  }
}

export function useQuizSession(userId: string, entry: EntryRequest): QuizSessionHandle {
  const router = useRouter();
  const { config } = useQuizConfig();
  const gamification = useGamificationDelta(userId);

  const [session, setSession] = useState<QuizSession>(() =>
    initialSession(entry, null, loadPrefs()),
  );
  const [pending, setPending] = useState(false);

  // The async chains read the session through this ref: a closure captured at
  // render time is one event behind by the time an await resolves.
  const sessionRef = useRef(session);
  const submittingRef = useRef<string | null>(null);
  // The item whose `/answer` is in flight, as `attemptId:index`. Without it a
  // double-click fires the request twice: the phase stays `active` for the whole
  // round trip, so neither `canSubmitAnswer` nor a `phase !== "active"` disabled
  // check rules the second press out.
  const answeringRef = useRef<string | null>(null);
  const generationRef = useRef(0);
  const configAppliedRef = useRef(false);
  const autoResumedRef = useRef(false);

  /** Apply one event, persist the outcome, and hand it back so the caller can
   *  decide what the new phase requires. */
  const apply = useCallback((event: QuizEvent): QuizSession => {
    const next = reduce(sessionRef.current, event);
    if (next !== sessionRef.current) {
      sessionRef.current = next;
      setSession(next);
      persistSession(next);
    }
    return next;
  }, []);

  // Once `/config` lands, adopt its defaults — but only while nothing is in
  // flight and only if the student hasn't already chosen. The first paint uses
  // the pre-config scalar so the "5 questions, medium" line isn't blank.
  //
  // `SET_CONFIG` is refused mid-quiz, so the flag is set only once the machine
  // ACCEPTED it and the effect re-runs on the phase: a `/config` that resolves
  // during a fast start or a `?attempt=` auto-resume would otherwise mark itself
  // applied while being dropped, and the defaults would never land.
  useEffect(() => {
    if (!config || configAppliedRef.current) return;
    const desired = defaultConfigFor(config, loadPrefs(config));
    if (apply({ type: "SET_CONFIG", config: desired }).config === desired) {
      configAppliedRef.current = true;
    }
  }, [config, apply, session.phase]);

  // Persist on unmount and on a tab close, so "answered then navigated away" is
  // resumable even though no transition fired on the way out.
  useEffect(() => {
    const flush = () => persistSession(sessionRef.current);
    window.addEventListener("beforeunload", flush);
    return () => {
      window.removeEventListener("beforeunload", flush);
      flush();
    };
  }, []);

  const runGenerate = useCallback(
    async (from: QuizSession) => {
      if (!from.conceptId) {
        // Defensive: every start affordance names a concept. If one ever
        // doesn't, say something true rather than "something went wrong on our
        // side" — the student's move is to pick a different concept.
        apply({
          type: "GENERATE_FAILED",
          error: {
            code: "QUIZ_CONCEPT_NOT_FOUND",
            message: QUIZ_ERROR_COPY.QUIZ_CONCEPT_NOT_FOUND,
            retryable: false,
          },
        });
        return;
      }
      const token = generationRef.current + 1;
      generationRef.current = token;
      // Snapshot XP now so the results screen has a "before" to subtract from.
      void gamification.snapshotBefore();
      setPending(true);
      try {
        const result = await generateQuiz({
          userId,
          conceptNodeId: from.conceptId,
          numQuestions: from.config.count,
          difficulty: from.config.difficulty,
        });
        if (generationRef.current !== token) return;
        apply({ type: "GENERATED", result });
      } catch (err) {
        if (generationRef.current !== token) return;
        apply({ type: "GENERATE_FAILED", error: describeQuizError(err) });
      } finally {
        if (generationRef.current === token) setPending(false);
      }
    },
    [apply, gamification, userId],
  );

  const runSubmit = useCallback(
    async (from: QuizSession) => {
      const attemptId = from.attemptId;
      if (!attemptId || submittingRef.current === attemptId) return;
      submittingRef.current = attemptId;
      setPending(true);
      try {
        // Belt and braces: the server reconciles against `quiz_responses` and a
        // recorded row always wins, so this payload only covers questions whose
        // `/answer` call was lost.
        const answers = from.items
          .filter(i => i.selectedIndex !== null)
          .map(i => ({
            question_id: i.question.id,
            selected_label: i.question.options[i.selectedIndex as number]?.label ?? "",
          }));
        const result = await submitQuiz(attemptId, answers);
        const xp = await gamification.deltaAfterSubmit();
        apply({ type: "SUBMITTED", result, xp });
        clearSession();
        announceGraphChanged(from.conceptId, result);
      } catch (err) {
        apply({ type: "SUBMIT_FAILED", error: describeQuizError(err) });
      } finally {
        submittingRef.current = null;
        setPending(false);
      }
    },
    [apply, gamification],
  );

  const runResume = useCallback(
    async (attemptId: string) => {
      setPending(true);
      try {
        const detail = await getAttempt(attemptId);
        if (!detail.resumable) {
          apply({
            type: "FAILED",
            error: {
              code: "QUIZ_ATTEMPT_NOT_RESUMABLE",
              message: QUIZ_ERROR_COPY.QUIZ_ATTEMPT_NOT_RESUMABLE,
              retryable: false,
            } satisfies QuizError,
          });
          return;
        }
        const stored = loadSession();
        apply({ type: "RESUME", detail, stored });
        void gamification.snapshotBefore();
      } catch (err) {
        apply({ type: "FAILED", error: describeQuizError(err) });
      } finally {
        setPending(false);
      }
    },
    [apply, gamification],
  );

  const submitAnswer = useCallback(async () => {
    // SUBMIT_ANSWER is the machine's own guard against a submit with nothing
    // selected; dispatching it keeps the transition table honest even though it
    // is state-neutral, and `canSubmitAnswer` is the same predicate the footer
    // button disables on.
    const current = apply({ type: "SUBMIT_ANSWER" });
    if (!canSubmitAnswer(current) || !current.attemptId) return;
    const item = current.items[current.cursor];
    const attemptId = current.attemptId;
    const inFlight = `${attemptId}:${item.index}`;
    if (answeringRef.current === inFlight) return;
    answeringRef.current = inFlight;
    setPending(true);
    try {
      const result = await withNetworkRetry(() =>
        answerQuestion(attemptId, {
          questionIndex: item.index,
          selectedIndex: item.selectedIndex as number,
          questionId: item.question.id,
        }),
      );
      const next = apply({ type: "ANSWER_RECORDED", result });
      if (next.phase === "submitting") await runSubmit(next);
    } catch (err) {
      apply({ type: "ANSWER_FAILED", error: describeQuizError(err) });
    } finally {
      answeringRef.current = null;
      setPending(false);
    }
  }, [apply, runSubmit]);

  // A `?attempt=<id>` entry (the resume strip, or a leave-and-return link) picks
  // the quiz back up without a stop on home.
  useEffect(() => {
    if (autoResumedRef.current || !entry.attempt || !userId) return;
    autoResumedRef.current = true;
    void runResume(entry.attempt);
  }, [entry.attempt, userId, runResume]);

  const actions = useMemo<QuizActions>(() => {
    const start = (request: StartRequest, override?: SessionConfig) => {
      const next = apply({
        type: "START",
        start: request,
        config: override ?? sessionRef.current.config,
      });
      if (next.phase === "generating") void runGenerate(next);
    };

    return {
      configure: open => {
        apply({ type: "CONFIGURE", open });
      },

      setConfig: next => {
        const applied = apply({ type: "SET_CONFIG", config: next });
        if (applied.config === next) {
          savePrefs({ count: next.count, difficulty: next.difficulty, feedback: next.feedback });
        }
      },

      start,

      select: index => {
        apply({ type: "SELECT", index });
      },

      submitAnswer: () => {
        void submitAnswer();
      },

      next: () => {
        const next = apply({ type: "NEXT" });
        if (next.phase === "submitting") void runSubmit(next);
      },

      finish: () => {
        const next = apply({ type: "FINISH" });
        if (next.phase === "submitting") void runSubmit(next);
      },

      requestLeave: () => {
        apply({ type: "REQUEST_LEAVE" });
      },

      cancelLeave: () => {
        apply({ type: "CANCEL_LEAVE" });
      },

      confirmLeave: () => {
        const next = apply({ type: "CONFIRM_LEAVE" });
        if (next.phase !== "paused") return;
        // `apply` already persisted it; the push is what makes the answers
        // recoverable from anywhere the student lands next.
        router.push(returnToSource(next));
      },

      resume: attemptId => {
        void runResume(attemptId);
      },

      practiseMissed: () => {
        const current = sessionRef.current;
        const result = current.result;
        if (!result) return;
        const missed = Math.max(result.total - result.score, 1);
        const min = config?.num_questions.min ?? 1;
        const max = config?.num_questions.max ?? missed;
        const next = apply({
          type: "PRACTISE_MISSED",
          missedCount: result.total - result.score,
          numQuestions: clamp(missed, min, max),
        });
        if (next.phase === "generating") void runGenerate(next);
      },

      nextInQueue: () => {
        const next = apply({ type: "NEXT_IN_QUEUE" });
        if (next.phase === "generating") void runGenerate(next);
      },

      exit: target => {
        const current = sessionRef.current;
        if (!canExit(current)) return;
        const next = apply({ type: "EXIT" });
        clearSession();
        router.push(target ?? returnToSource(next));
      },

      flag: () => {
        apply({ type: "FLAG" });
      },

      dismissError: () => {
        apply({ type: "DISMISS_ERROR" });
      },

      retry: () => {
        const failed = sessionRef.current;
        if (failed.phase !== "error") return;
        const back = errorReturnPhase(failed);
        const next = apply({ type: "DISMISS_ERROR" });
        if (back === "submitting") void runSubmit(next);
        else if (back === "home" && next.conceptId) {
          const generating = apply({
            type: "START",
            start: {
              intent: next.intent,
              scope: next.scope,
              conceptId: next.conceptId,
              courseId: next.courseId,
            },
            config: next.config,
          });
          if (generating.phase === "generating") void runGenerate(generating);
        } else if (back === "active") void submitAnswer();
      },
    };
  }, [apply, config, router, runGenerate, runResume, runSubmit, submitAnswer]);

  return { session, pending, config, actions };
}

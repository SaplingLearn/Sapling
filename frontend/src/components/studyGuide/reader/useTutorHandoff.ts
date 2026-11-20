"use client";
/**
 * Hand a question to the tutor: start a session on a topic, send the first
 * message, then open the tutor on that session. The tutor API has no
 * attachment field, so the guide's context travels inside the message.
 */
import React from "react";
import { useRouter } from "next/navigation";

import {
  ABORTED,
  chatWithFallback,
  openTutorSession,
  turnPauseOf,
  type TurnProgress,
} from "@/components/quiz/question/askTurn";
import { tutorPauseMessage } from "@/components/learn/BudgetPausedBanner";
import { useToast } from "@/components/ToastProvider";
import { useCrisisSupport } from "@/components/safety/CrisisSupportCard";
import { newTurnId, type GuideAskOrigin } from "@/lib/api";

/** #866 K01: the origin a guide's Ask opens its session with. */
const GUIDE_ASK: GuideAskOrigin = { guide: true };

export type AskTutor = (topic: string, message: string) => Promise<void>;

export function useTutorHandoff(
  userId: string,
  courseId: string,
): { ask: AskTutor; busy: boolean; crisisDialog: React.ReactNode } {
  const router = useRouter();
  const toast = useToast();
  const [busy, setBusy] = React.useState(false);
  const controller = React.useRef<AbortController | null>(null);
  // docs/safety/crisis-support.md: the crisis screen answered the question.
  // The card shows here, and the tutor is not opened (the turn was not kept).
  const crisis = useCrisisSupport();

  React.useEffect(() => () => controller.current?.abort(), []);

  const ask: AskTutor = async (topic, message) => {
    if (busy) return;
    const { signal } = (controller.current = new AbortController());
    const progress: TurnProgress = { sawToken: false, partial: "" };
    setBusy(true);
    try {
      // K01: a guide ask teaches from the first turn (no check-in to answer first)
      const sid = await openTutorSession(userId, topic, courseId, signal, GUIDE_ASK);
      if (sid === ABORTED) return;
      if (typeof sid === "object" && sid !== null) { crisis.intercept({ crisis_support: sid.crisis }); return; }
      if (!sid) throw new Error("The tutor did not start a session.");
      const reply = await chatWithFallback(
        { sid, userId, message, turnId: newTurnId(), signal, progress },
        { onToken: () => void (progress.sawToken = true) },
        () => {},
      );
      if (reply === ABORTED) return;
      if (typeof reply === "object") { crisis.intercept({ crisis_support: reply.crisis }); return; }
      router.push(`/learn?resume=${encodeURIComponent(sid)}`);
    } catch (err) {
      if (signal.aborted) return;
      // The learning loop paused the tutor for the student's AI budget (the
      // stream's `budget` end, or a 429 "ai budget reached"): a state of their
      // day, not a failure — say until when, and offer no retry.
      const paused = turnPauseOf(err);
      if (paused) toast.warn(tutorPauseMessage(paused.resetAt, paused.sessionCapped));
      else toast.error("The tutor could not be opened. Try again.");
    } finally {
      if (!signal.aborted) setBusy(false);
    }
  };

  return { ask, busy, crisisDialog: crisis.dialog };
}

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
  type TurnProgress,
} from "@/components/quiz/question/askTurn";
import { useToast } from "@/components/ToastProvider";
import { newTurnId } from "@/lib/api";

export type AskTutor = (topic: string, message: string) => Promise<void>;

export function useTutorHandoff(userId: string, courseId: string): { ask: AskTutor; busy: boolean } {
  const router = useRouter();
  const toast = useToast();
  const [busy, setBusy] = React.useState(false);
  const controller = React.useRef<AbortController | null>(null);

  React.useEffect(() => () => controller.current?.abort(), []);

  const ask: AskTutor = async (topic, message) => {
    if (busy) return;
    const { signal } = (controller.current = new AbortController());
    const progress: TurnProgress = { sawToken: false, partial: "" };
    setBusy(true);
    try {
      const sid = await openTutorSession(userId, topic, courseId, signal);
      if (sid === ABORTED) return;
      if (!sid) throw new Error("The tutor did not start a session.");
      const reply = await chatWithFallback(
        { sid, userId, message, turnId: newTurnId(), signal, progress },
        { onToken: () => void (progress.sawToken = true) },
        () => {},
      );
      if (reply === ABORTED) return;
      router.push(`/learn?resume=${encodeURIComponent(sid)}`);
    } catch {
      if (!signal.aborted) toast.error("The tutor could not be opened. Try again.");
    } finally {
      if (!signal.aborted) setBusy(false);
    }
  };

  return { ask, busy };
}

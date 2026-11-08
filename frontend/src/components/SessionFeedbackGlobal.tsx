"use client";

import React, { useEffect, useRef, useState } from "react";
import { usePathname, useSearchParams } from "next/navigation";
import { useUser } from "@/context/UserContext";
import {
  mayPrompt,
  recordPrompt,
  releaseFeedbackSlot,
  takeEndedSession,
  tryClaimFeedbackSlot,
  whenFeedbackFree,
} from "@/lib/feedbackPacing";
import { SessionFeedbackFlow, type SessionFeedbackContext } from "./SessionFeedbackFlow";

const LEARN_PATH = "/learn";

/**
 * "How was that session?" — asked when the student leaves /learn after a
 * session's wrap-up (the ended session LoopLearn / Learn.tsx remember). Leaving
 * mid-session asks nothing: the session is not over. lib/feedbackPacing.ts
 * decides whether it opens: never while a learning activity holds prompts (it
 * waits for the release), at most one prompt per session, and the cooldowns.
 *
 * `?testFeedback=session` on /learn (the Figma recipes) skips the wrap-up and
 * pacing checks for the next leave; it is latched while on /learn because the
 * link out drops the query string.
 */
export function SessionFeedbackGlobal() {
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const { isAuthenticated } = useUser();
  const testOverride = searchParams.get("testFeedback") === "session";

  const [open, setOpen] = useState(false);
  const [context, setContext] = useState<SessionFeedbackContext | undefined>();
  const prevPath = useRef(pathname);
  const forcedOnLearn = useRef(false);
  const cancelWait = useRef<() => void>(() => {});

  useEffect(() => {
    const wasOnLearn = prevPath.current?.startsWith(LEARN_PATH) ?? false;
    const nowOnLearn = pathname?.startsWith(LEARN_PATH) ?? false;
    prevPath.current = pathname;
    if (nowOnLearn) {
      if (testOverride) forcedOnLearn.current = true;
      return;
    }
    const forced = forcedOnLearn.current || testOverride;
    forcedOnLearn.current = false;
    if (!isAuthenticated || !wasOnLearn) return;
    // Consumed on every leave: the wrap-up's natural break is this one.
    const ended = takeEndedSession();
    if (!ended && !forced) return;
    const sessionId = ended?.sessionId ?? null;
    cancelWait.current();
    cancelWait.current = whenFeedbackFree(() => {
      if (!forced && !mayPrompt("session", sessionId)) return;
      // One feedback prompt at a time (#762): if the pulse is up, skip this
      // one — nothing is recorded, so it isn't spent.
      if (!tryClaimFeedbackSlot("session")) return;
      recordPrompt("session", sessionId); // on open: a dismissal counts as shown
      setContext(ended ?? undefined);
      setOpen(true);
    });
  }, [pathname, isAuthenticated, testOverride]);

  useEffect(() => () => {
    cancelWait.current();
    releaseFeedbackSlot("session");
  }, []);

  const close = () => {
    setOpen(false);
    releaseFeedbackSlot("session");
  };

  return <SessionFeedbackFlow open={open} context={context} onClose={close} />;
}

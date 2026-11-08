"use client";

import React, { useEffect, useRef, useState } from "react";
import { usePathname, useSearchParams } from "next/navigation";
import { useUser } from "@/context/UserContext";
import { releaseFeedbackSlot, tryClaimFeedbackSlot } from "@/lib/feedbackSlot";
import {
  SessionFeedbackFlow,
  SESSION_COOLDOWN_MS,
  SESSION_COOLDOWN_KEY,
  type SessionFeedbackContext,
} from "./SessionFeedbackFlow";

const LEARN_PATH = "/learn";
// Written by Learn.tsx when a session ends.
const LAST_SESSION_CTX_KEY = "sapling_last_session_context";

export function SessionFeedbackGlobal() {
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const { isAuthenticated } = useUser();
  const testOverride = searchParams.get("testFeedback") === "session";

  const [open, setOpen] = useState(false);
  const [context, setContext] = useState<SessionFeedbackContext | undefined>();
  const prevPath = useRef(pathname);

  useEffect(() => {
    if (!isAuthenticated) {
      prevPath.current = pathname;
      return;
    }
    const wasOnLearn = prevPath.current?.startsWith(LEARN_PATH) ?? false;
    const nowOnLearn = pathname?.startsWith(LEARN_PATH) ?? false;
    if (wasOnLearn && !nowOnLearn) {
      const last = Number(localStorage.getItem(SESSION_COOLDOWN_KEY) ?? "0");
      const now = Date.now();
      // One feedback prompt at a time (#762): if the passive pulse is up,
      // skip this one — no cooldown recorded, so it isn't spent.
      if ((testOverride || !last || now - last > SESSION_COOLDOWN_MS) && tryClaimFeedbackSlot("session")) {
        let ctx: SessionFeedbackContext | undefined;
        try {
          const raw = sessionStorage.getItem(LAST_SESSION_CTX_KEY);
          if (raw) ctx = JSON.parse(raw);
          // Consumed: left in place it would label every later prompt this
          // tab shows with a session from long before (#762).
          sessionStorage.removeItem(LAST_SESSION_CTX_KEY);
        } catch {}
        setContext(ctx);
        setOpen(true);
      }
    }
    prevPath.current = pathname;
  }, [pathname, isAuthenticated, testOverride]);

  useEffect(() => () => releaseFeedbackSlot("session"), []);

  const close = () => {
    setOpen(false);
    releaseFeedbackSlot("session");
  };

  return <SessionFeedbackFlow open={open} context={context} onClose={close} />;
}

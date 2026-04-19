"use client";

import React, { useEffect, useRef, useState } from "react";
import { usePathname, useSearchParams } from "next/navigation";
import { useUser } from "@/context/UserContext";
import {
  SessionFeedbackFlow,
  SESSION_COOLDOWN_MS,
  SESSION_COOLDOWN_KEY,
  type SessionFeedbackContext,
} from "./SessionFeedbackFlow";

const LEARN_PATH = "/learn";

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
      if (testOverride || !last || now - last > SESSION_COOLDOWN_MS) {
        const raw = sessionStorage.getItem("sapling_last_session_context");
        let ctx: SessionFeedbackContext | undefined;
        if (raw) {
          try { ctx = JSON.parse(raw); } catch {}
        }
        setContext(ctx);
        setOpen(true);
      }
    }
    prevPath.current = pathname;
  }, [pathname, isAuthenticated, testOverride]);

  return <SessionFeedbackFlow open={open} context={context} onClose={() => setOpen(false)} />;
}

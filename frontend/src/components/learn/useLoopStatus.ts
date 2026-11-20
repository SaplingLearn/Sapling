"use client";
import { useCallback, useEffect, useState } from "react";

import { useFlagMap } from "@/context/FlagsContext";
import { getLoopStatus } from "@/lib/api";
import { LEARNING_LOOP_FLAG } from "@/lib/learningLoopFlag";

/** How long Learn waits for the loop probe before showing the retry state †. */
export const LOOP_STATUS_TIMEOUT_MS = 2_500;

/** How long a definitive probe answer is reused by a screen that opts in
 *  (`{ reuse: true }`, the quiz, #866 K46): it then asks the server nothing
 *  and shows its loop-only controls from the first render. Learn and Study
 *  always probe, and every definitive answer refreshes the memo. */
export const LOOP_STATUS_REUSE_MS = 5 * 60_000;

/** The last definitive probe answer per user, and when it came. */
const lastAnswer = new Map<string, { active: boolean; at: number }>();

function reusableAnswer(userId: string): { userId: string; active: boolean } | null {
  const hit = lastAnswer.get(userId);
  return hit && Date.now() - hit.at < LOOP_STATUS_REUSE_MS ? { userId, active: hit.active } : null;
}

export function __resetLoopStatusMemoForTests(): void {
  lastAnswer.clear();
}

/** Which Learn tree to render. `null` = unresolved; `true` = LoopLearn;
 *  `false` = the legacy tree (the student's `learning_loop` flag is "off", or
 *  the probe said so: the kill switch's `{active: false}`, or the gate's 404,
 *  which getLoopStatus resolves to `{active: false}`); `"error"` = the probe
 *  failed or timed out — Learn shows a retry state, NEVER the legacy tree. */
export type LoopStatus = boolean | "error" | null;

/** Learning loop (PKG-13; post-launch PKG-14b, spec §11.2 / §13 A14). Reads
 *  the `learning_loop` flag and the loop status probe — never
 *  `learning_loop_beta`, which no settings field carries (spec §7, §13 A31).
 *
 *  For a student the loop is on for, the backend delegates the legacy
 *  `/start-session` / `/chat` calls to the loop. So a failed probe
 *  must not fail OPEN to the legacy tree (a hybrid: typed answers never graded,
 *  loop phase/check events ignored, a smart/fast toggle that does nothing).
 *  Only a definitive inactive answer renders legacy. A 5xx, a network error or
 *  no answer within LOOP_STATUS_TIMEOUT_MS is `"error"`; `retry()` re-runs the
 *  GET. A late definitive answer still wins over a timeout's `"error"`.
 *
 *  The `learning_loop` flag comes first: while the flags load the answer is
 *  unresolved, and a flag map that says "off" is the legacy tree with NO probe
 *  (a flag-off student calls no loop endpoint). A map without the key (flags
 *  unreadable and nothing remembered, or an older backend) defers to the probe,
 *  which is the server's own answer — never a guess that could pair the legacy
 *  tree with a backend that delegates to the loop. */
export function useLoopStatus(
  userId: string,
  userReady: boolean,
  { reuse = false }: { reuse?: boolean } = {},
): { status: LoopStatus; retry: () => void } {
  // Keyed on the user (and the attempt) the answer is for, so a user switch or
  // a retry reads as unresolved until its own probe answers (no setState in the
  // effect body).
  const [attempt, setAttempt] = useState(0);
  const [resolved, setResolved] = useState<
    { userId: string; attempt: number; status: boolean | "error"; final: boolean } | null
  >(null);
  // A reusable answer is read once, when the screen mounts; a retry probes.
  const [reused] = useState(() => (reuse ? reusableAnswer(userId) : null));
  const reusing = reused !== null && reused.userId === userId && attempt === 0;
  const { flags, ready: flagsReady } = useFlagMap();
  const loopFlag = flags[LEARNING_LOOP_FLAG];
  const flagOff = loopFlag !== undefined && loopFlag !== "on";
  const probe = userReady && !!userId && flagsReady && !flagOff && !reusing;
  useEffect(() => {
    if (!probe) return;
    let cancelled = false;
    const timeout = setTimeout(() => {
      if (cancelled) return;
      setResolved((prev) =>
        prev?.userId === userId && prev.attempt === attempt && prev.final
          ? prev
          : { userId, attempt, status: "error", final: false },
      );
    }, LOOP_STATUS_TIMEOUT_MS);
    getLoopStatus(userId)
      .then((r) => {
        if (cancelled) return;
        clearTimeout(timeout);
        lastAnswer.set(userId, { active: Boolean(r.active), at: Date.now() });
        setResolved({ userId, attempt, status: Boolean(r.active), final: true });
      })
      .catch(() => {
        if (cancelled) return;
        clearTimeout(timeout);
        setResolved({ userId, attempt, status: "error", final: true });
      });
    return () => {
      cancelled = true;
      clearTimeout(timeout);
    };
  }, [userId, probe, attempt]);
  const retry = useCallback(() => setAttempt((a) => a + 1), []);
  if (!userReady) return { status: null, retry };
  if (!userId) return { status: false, retry };
  if (!flagsReady) return { status: null, retry };
  if (flagOff) return { status: false, retry };
  if (reusing) return { status: reused.active, retry };
  const status =
    resolved?.userId === userId && resolved.attempt === attempt ? resolved.status : null;
  return { status, retry };
}

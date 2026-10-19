"use client";
import { useCallback, useEffect, useState } from "react";

import {
  getLoopSessionStatus,
  listLoopSessionsFor,
  type LoopPhase,
  type LoopResumeSession,
  type LoopSessionStatus,
  type Session,
} from "@/lib/api";
import type { LearnerState, OpenLoopSession } from "@/lib/dashboard/nextStep";
import type { LoopStatus } from "@/components/learn/useLoopStatus";

/** A discovery that has not answered by now is reported as failed (with a
 *  Retry), never left spinning and never replaced by a new session. */
export const DISCOVERY_TIMEOUT_MS = 8_000;
/** How many recent open sessions are checked for a loop session before
 *  falling back to the target course's own list. */
const MAX_CANDIDATES = 3;

const PHASES: readonly LoopPhase[] = ["probe", "plan", "teach", "check", "feedback", "close"];
const asPhase = (p: string | null | undefined): LoopPhase | null =>
  p && (PHASES as readonly string[]).includes(p) ? (p as LoopPhase) : null;

/** GET /status's phase in the UI vocabulary — LoopLearn's `statusPhase`:
 *  `loop_phase` is probe | plan | teach | close and, while teaching, `phase`
 *  refines it into teach | check | feedback. */
export function phaseOfStatus(st: LoopSessionStatus): LoopPhase | null {
  return asPhase(st.loop_phase === "teach" ? st.phase : st.loop_phase);
}

function withTimeout<T>(p: Promise<T>, ms: number): Promise<T> {
  return new Promise<T>((resolve, reject) => {
    const t = setTimeout(() => reject(new Error("discovery timed out")), ms);
    p.then(
      (v) => {
        clearTimeout(t);
        resolve(v);
      },
      (e) => {
        clearTimeout(t);
        reject(e);
      },
    );
  });
}

export interface DiscoveryInput {
  userId: string;
  /** useLoopStatus: null = unresolved, true = loop, false = legacy, "error". */
  loop: LoopStatus;
  /** Recent sessions (GET /api/learn/sessions), newest first; null while unavailable. */
  sessions: Session[] | null;
  sessionsFailed: boolean;
  /** Enrolled course ids; null while unavailable. */
  courseIds: string[] | null;
  coursesFailed: boolean;
  /** Where a NEW check-in would start (scope course, else the latest
   *  session's course, else the first enrolled course). */
  targetCourseId: string | null;
  /** Concepts on the map for a course; null = unknown (graph not loaded). */
  conceptCount: (courseId: string) => number | null;
}

type LoopResult =
  | { kind: "open"; session: OpenLoopSession }
  | { kind: "none" }
  | { kind: "error" };

/**
 * Finds the student's resumable learning session READ-ONLY: GET
 * /api/learn/loop/sessions (with `resume=` for a named candidate, which
 * finds an open loop session in ANY course) and GET /status. It never calls
 * start-session, probe/next, check/next, goal, plan/approve, answer or close
 * — the arrival makes reads only, and so does a scope change or a Retry.
 */
export function useLearningDiscovery(input: DiscoveryInput): { state: LearnerState; stale: boolean; retry: () => void } {
  const { userId, loop, sessions, sessionsFailed, courseIds, coursesFailed, targetCourseId, conceptCount } = input;
  const [attempt, setAttempt] = useState(0);
  const [result, setResult] = useState<{ key: string; attempt: number; value: LoopResult } | null>(null);
  // Last successful loop answer for this user, kept up (flagged stale) when a
  // retry fails instead of wiping a valid "continue" action.
  const [lastGood, setLastGood] = useState<{ user: string; value: LoopResult } | null>(null);

  const candidates = (sessions ?? [])
    .filter((s) => s.is_active && s.course_id && (courseIds ?? []).includes(s.course_id))
    .slice(0, MAX_CANDIDATES)
    .map((s) => ({ id: s.id, courseId: s.course_id as string }));
  const candidateKey = candidates.map((c) => `${c.id}@${c.courseId}`).join(",");
  const ready = loop === true && sessions !== null && courseIds !== null && courseIds.length > 0;
  const key = ready ? `${userId}|${candidateKey}|${targetCourseId ?? ""}` : null;

  useEffect(() => {
    if (!key) return;
    let cancelled = false;
    const run = async (): Promise<LoopResult> => {
      let found: LoopResumeSession | null = null;
      for (const c of candidates) {
        const r = await withTimeout(listLoopSessionsFor(userId, c.courseId, c.id), DISCOVERY_TIMEOUT_MS);
        if (r.resume) {
          found = r.resume;
          break;
        }
      }
      if (!found && targetCourseId) {
        const r = await withTimeout(listLoopSessionsFor(userId, targetCourseId, null), DISCOVERY_TIMEOUT_MS);
        if (r.sessions[0]) found = { ...r.sessions[0], course_id: targetCourseId };
      }
      if (!found) return { kind: "none" };
      let status: LoopSessionStatus | null = null;
      try {
        status = await withTimeout(getLoopSessionStatus(found.session_id, userId), DISCOVERY_TIMEOUT_MS);
      } catch {
        status = null; // the listed session still resumes; its goal detail is just unavailable
      }
      const phase = (status && phaseOfStatus(status)) ?? asPhase(found.phase) ?? "teach";
      return {
        kind: "open",
        session: {
          sessionId: found.session_id,
          courseId: found.course_id,
          topic: found.topic,
          phase,
          goal: status?.goal ?? null,
          goalVersion: status?.goal_version ?? null,
          diagnosis: status?.diagnosis ?? null,
          goalProgress: status?.goal_progress ?? null,
          statusLoaded: status !== null,
        },
      };
    };
    run().then(
      (value) => {
        if (cancelled) return;
        setResult({ key, attempt, value });
        setLastGood({ user: userId, value });
      },
      () => {
        if (!cancelled) setResult({ key, attempt, value: { kind: "error" } });
      },
    );
    return () => {
      cancelled = true;
    };
    // `candidates` is fully described by `key` (candidateKey).
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, attempt]);

  const retry = useCallback(() => setAttempt((a) => a + 1), []);

  // ── Derive the learner state ────────────────────────────────────────────
  if (loop === null) return { state: { kind: "pending" }, stale: false, retry };
  if (loop === "error" || coursesFailed) return { state: { kind: "error" }, stale: false, retry };
  if (courseIds === null) return { state: { kind: "pending" }, stale: false, retry };
  if (courseIds.length === 0) return { state: { kind: "no-course" }, stale: false, retry };
  if (sessions === null) return sessionsFailed ? { state: { kind: "error" }, stale: false, retry } : { state: { kind: "pending" }, stale: false, retry };

  if (loop === false) {
    const open = sessions.find((s) => s.is_active);
    return {
      state: open
        ? { kind: "legacy-open", sessionId: open.id, topic: open.topic, courseId: open.course_id }
        : { kind: "legacy-none" },
      stale: false,
      retry,
    };
  }

  const current = result && result.key === key && result.attempt === attempt ? result.value : null;
  const toState = (v: LoopResult): LearnerState => {
    if (v.kind === "open") return { kind: "loop-open", session: v.session };
    if (v.kind === "error") return { kind: "error" };
    const target = targetCourseId ?? courseIds[0];
    const count = conceptCount(target);
    if (count === 0) return { kind: "no-concepts", courseId: target };
    const closed = sessions.find((s) => !s.is_active);
    return { kind: "loop-none", courseId: target, lastClosed: closed ? { id: closed.id, topic: closed.topic } : null };
  };
  if (!current) {
    // In flight: keep showing the last good answer for this user (a scope
    // change re-checks without flashing a new-session offer), else pending.
    if (lastGood && lastGood.user === userId) return { state: toState(lastGood.value), stale: false, retry };
    return { state: { kind: "pending" }, stale: false, retry };
  }
  if (current.kind === "error" && lastGood && lastGood.user === userId) {
    return { state: toState(lastGood.value), stale: true, retry };
  }
  return { state: toState(current), stale: false, retry };
}

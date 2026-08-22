"use client";

/**
 * Everything quiz home renders from: the graph, the courses, the attempt
 * history, the ranked proposals derived from all three, and whichever unfinished
 * quiz is waiting to be resumed.
 *
 * The bootstrap deliberately matches what `screens/Quiz.tsx` does today —
 * `getCourses` + `getGraph(userId, activeSemester || undefined)` in parallel,
 * held until the active semester has hydrated so returning users fetch scoped
 * once instead of unscoped-then-scoped — because the semester contract is the
 * same and re-deriving it would be a fourth divergent copy (R4 §4).
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { getCourses, getGraph, type EnrolledCourse } from "@/lib/api";
import { courseInTerm } from "@/lib/useActiveSemester";
import type { GraphEdge, GraphNode } from "@/lib/types";
import { describeConcept, getAttempt, listAttempts } from "./api";
import { describeQuizError, type QuizError } from "./errors";
import {
  alternativesOf,
  dueSet,
  groupByCourse,
  primaryOf,
  rankCandidates,
  type Candidate,
} from "./proposals";
import { isDismissed, loadSession } from "./session";
import type { AttemptDetail, AttemptSummary, QuizSession } from "./types";

/** One page of history is enough for both the resume sweep and the "missed N
 *  last time" join; the route clamps `limit` to 100 anyway. */
const HISTORY_LIMIT = 20;

export interface ResumableQuiz {
  attempt: AttemptDetail;
  /** The locally stored session for this attempt, when there is one. It is the
   *  only place the scope, queue, feedback mode and origin survive. */
  session: QuizSession | null;
  answered: number;
}

export interface QuizHome {
  status: "loading" | "ready" | "error";
  error: QuizError | null;
  nodes: GraphNode[];
  edges: GraphEdge[];
  courses: EnrolledCourse[];
  attempts: AttemptSummary[];
  candidates: Candidate[];
  primary: Candidate | null;
  alternatives: Candidate[];
  due: ReturnType<typeof dueSet>;
  byCourse: ReturnType<typeof groupByCourse>;
  resumable: ResumableQuiz | null;
  /** The AI one-liner for the PRIMARY proposal only (R-8). `null` while it is
   *  in flight or after a failure — the card falls back to a built sentence
   *  rather than blocking or showing an empty paragraph. */
  primaryDescription: string | null;
  refresh(): void;
}

/** The fallback definition when `concept-description` is slow or fails (R-8),
 *  the same shape Learn's focus card falls back to. */
export function fallbackDefinition(candidate: Candidate | null, connected: number): string {
  if (!candidate) return "";
  const course = candidate.course?.course_code ?? candidate.node.subject ?? "Your tree";
  const plural = connected === 1 ? "concept" : "concepts";
  return `${course} · ${candidate.node.mastery_tier} · ${connected} connected ${plural}`;
}

/**
 * Resume discovery (R-3), in two passes.
 *
 * The stored session names an attempt id without a round trip, so it goes first
 * — but it is only a hint, and `GET /attempts/{id}` is what decides whether the
 * attempt is really resumable (it may have been submitted elsewhere or swept
 * past the 24h TTL). The history page then covers the other-device case, where
 * this browser has no record at all. Discarded ids are skipped: there is no
 * abandon endpoint, so a discard is client-side only (gap G4).
 */
async function discoverResumable(
  attempts: AttemptSummary[],
  stored: QuizSession | null,
): Promise<ResumableQuiz | null> {
  const ids: string[] = [];
  if (stored?.attemptId) ids.push(stored.attemptId);
  for (const a of attempts) {
    if (a.status === "in_progress" && !ids.includes(a.quiz_id)) ids.push(a.quiz_id);
  }

  for (const id of ids) {
    if (isDismissed(id)) continue;
    try {
      const attempt = await getAttempt(id);
      if (!attempt.resumable) continue;
      return {
        attempt,
        session: stored?.attemptId === id ? stored : null,
        answered: attempt.responses?.length ?? 0,
      };
    } catch {
      // A 404 or a 409 means this one is not resumable after all; try the next.
    }
  }
  return null;
}

/**
 * @param userId  the signed-in student.
 * @param semester the active semester label, or `null` while it is still
 *   hydrating from localStorage — nothing is fetched until it resolves. The
 *   empty string means "All semesters" and fetches unscoped (#360).
 */
export function useQuizHome(userId: string, semester: string | null): QuizHome {
  const [status, setStatus] = useState<QuizHome["status"]>("loading");
  const [error, setError] = useState<QuizError | null>(null);
  const [nodes, setNodes] = useState<GraphNode[]>([]);
  const [edges, setEdges] = useState<GraphEdge[]>([]);
  const [courses, setCourses] = useState<EnrolledCourse[]>([]);
  const [attempts, setAttempts] = useState<AttemptSummary[]>([]);
  const [resumable, setResumable] = useState<ResumableQuiz | null>(null);
  const [nonce, setNonce] = useState(0);

  const refresh = useCallback(() => setNonce(n => n + 1), []);
  const liveRef = useRef(0);

  useEffect(() => {
    if (!userId || semester === null) return;
    const token = liveRef.current + 1;
    liveRef.current = token;
    let cancelled = false;
    setStatus("loading");
    setError(null);

    (async () => {
      try {
        // The three reads are independent; a failing history must not cost the
        // student their whole home screen, so only the graph pair is fatal.
        const [courseRes, graphRes, attemptRes] = await Promise.all([
          getCourses(userId),
          getGraph(userId, semester || undefined),
          listAttempts(userId, { limit: HISTORY_LIMIT }).catch(
            () => ({ total: 0, limit: HISTORY_LIMIT, offset: 0, attempts: [] as AttemptSummary[] }),
          ),
        ]);
        if (cancelled || liveRef.current !== token) return;

        setCourses(courseRes.courses ?? []);
        setNodes((graphRes.nodes ?? []) as GraphNode[]);
        setEdges((graphRes.edges ?? []) as GraphEdge[]);
        setAttempts(attemptRes.attempts ?? []);
        setStatus("ready");

        const found = await discoverResumable(attemptRes.attempts ?? [], loadSession());
        if (cancelled || liveRef.current !== token) return;
        setResumable(found);
      } catch (err) {
        if (cancelled || liveRef.current !== token) return;
        setError(describeQuizError(err));
        setStatus("error");
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [userId, semester, nonce]);

  // The graph fetch is already scoped server-side; this mirrors the Tree/Learn
  // pickers' defensive re-filter so a stale payload can't leak another term in.
  const scopedCourses = useMemo(
    () => (semester ? courses.filter(c => courseInTerm(c, semester)) : courses),
    [courses, semester],
  );
  const scopedNodes = useMemo(() => {
    if (!semester) return nodes;
    const allowed = new Set(scopedCourses.map(c => c.course_id));
    return nodes.filter(n => !n.course_id || allowed.has(n.course_id));
  }, [nodes, semester, scopedCourses]);

  const candidates = useMemo(
    () => rankCandidates(scopedNodes, scopedCourses, attempts),
    [scopedNodes, scopedCourses, attempts],
  );
  const primary = useMemo(() => primaryOf(candidates), [candidates]);
  const alternatives = useMemo(() => alternativesOf(candidates, primary), [candidates, primary]);
  const due = useMemo(() => dueSet(scopedNodes), [scopedNodes]);
  const byCourse = useMemo(
    () => groupByCourse(scopedNodes, scopedCourses),
    [scopedNodes, scopedCourses],
  );

  // One LLM call per home visit, for the one card that shows a paragraph (R-8).
  // `graph_nodes` has no `description` column, so there is nothing stored to
  // read; fetching this for every card would multiply the cost by the number of
  // rows on screen, which is exactly why it is scoped to the primary.
  const [primaryDescription, setPrimaryDescription] = useState<string | null>(null);
  const primaryId = primary?.node.id ?? null;
  const primaryName = primary?.node.concept_name ?? null;
  const primaryCourseLabel = primary?.course?.course_code ?? undefined;

  useEffect(() => {
    setPrimaryDescription(null);
    if (!userId || !primaryId || !primaryName) return;
    let cancelled = false;
    describeConcept(userId, primaryName, primaryCourseLabel).then(
      description => {
        if (!cancelled) setPrimaryDescription(description.trim() || null);
      },
      () => {
        // The card renders the built fallback sentence instead. A missing
        // definition must never hold up the Start button.
      },
    );
    return () => {
      cancelled = true;
    };
  }, [userId, primaryId, primaryName, primaryCourseLabel]);

  return {
    status,
    error,
    nodes: scopedNodes,
    edges,
    courses: scopedCourses,
    attempts,
    candidates,
    primary,
    alternatives,
    due,
    byCourse,
    resumable,
    primaryDescription,
    refresh,
  };
}

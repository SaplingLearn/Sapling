"use client";

/**
 * Everything quiz home renders from: the graph, the courses, the attempt
 * history, the ranked proposals derived from all three, and whichever unfinished
 * quiz is waiting to be resumed.
 *
 * The bootstrap is `getCourses` + `getGraph(userId, activeSemester || undefined)`
 * in parallel, held until the active semester has hydrated from localStorage.
 * That wait is the point: fetching before it resolves means a returning user
 * fetches unscoped and then immediately re-fetches scoped, and briefly sees
 * concepts from a term they are not looking at. The empty string means
 * "All semesters" and fetches unscoped (#360).
 *
 * Tree, Learn and Dashboard each run the same pair for themselves (R4 §4); this
 * is deliberately the same shape rather than a new one, so the semester contract
 * has one behaviour across every surface that reads the graph.
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import { getCourses, getGraph, type EnrolledCourse } from "@/lib/api";
import { courseInTerm } from "@/lib/useActiveSemester";
import type { GraphEdge, GraphNode } from "@/lib/types";
import { describeConcept, getAttempt, listAttempts } from "./api";
import { describeQuizError, type QuizError } from "./errors";
import {
  alternativesOf,
  dueSet,
  entrySelection,
  groupByCourse,
  primaryOf,
  queueFor,
  rankCandidates,
  type Candidate,
} from "./proposals";
import { isDismissed, loadSession } from "./session";
import type { EntryRequest } from "./source";
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
  /**
   * The concept the "Ready for you" card will actually show, which is NOT always
   * the ranked primary: a `?concept=`/`?topic=` deep link names its own, a
   * `?course=` entry opens on that course's weakest, and `?scope=due` opens on
   * the weakest due overall (§5 B1.2 "Entry overrides"). `null` before the graph
   * has loaded, or when there is nothing to propose.
   */
  cardConceptId: string | null;
  /**
   * The AI one-liner for the CARD's concept (R-8) — one call, for the one card
   * that shows a paragraph. `null` while it is in flight or after a failure: the
   * card falls back to a built sentence rather than blocking or showing an empty
   * paragraph.
   *
   * Also `null`, and never fetched, for the two queue-shaped entries. A
   * `?course=` or `?scope=due` card is headed "Practice {CODE}" / "Review
   * everything due" over a queue summary (§5 B1.2) — it has no definition slot,
   * so describing its first concept would be an LLM call for text nothing
   * renders.
   */
  cardDescription: string | null;
  /** @deprecated Alias of `cardDescription`, kept so the current home render
   *  keeps compiling. Read `cardDescription` — it is right for a deep-linked
   *  card too, which this name implies it is not. */
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

/** One resolved load, tagged with the request it answers. */
interface Loaded {
  key: string;
  nodes: GraphNode[];
  edges: GraphEdge[];
  courses: EnrolledCourse[];
  attempts: AttemptSummary[];
  error: QuizError | null;
}

const EMPTY_LOAD = {
  nodes: [] as GraphNode[],
  edges: [] as GraphEdge[],
  courses: [] as EnrolledCourse[],
  attempts: [] as AttemptSummary[],
};

/**
 * @param userId  the signed-in student.
 * @param semester the active semester label, or `null` while it is still
 *   hydrating from localStorage — nothing is fetched until it resolves. The
 *   empty string means "All semesters" and fetches unscoped (#360).
 */
export function useQuizHome(
  userId: string,
  semester: string | null,
  entry?: EntryRequest,
): QuizHome {
  const [loaded, setLoaded] = useState<Loaded | null>(null);
  const [resumable, setResumable] = useState<{ key: string; value: ResumableQuiz | null } | null>(
    null,
  );
  const [nonce, setNonce] = useState(0);

  const refresh = useCallback(() => setNonce(n => n + 1), []);

  // "Loading" is DERIVED from whether the resolved load answers the request
  // currently on screen, rather than stored and reset at the top of the effect:
  // a synchronous setState in an effect body is a cascading render, and the
  // stale-response guard falls out of the same key for free.
  // NUL-delimited so no id or term label can forge a collision. Written as an
  // ESCAPE, never a literal byte: a raw NUL makes git treat the whole file as
  // binary, and this one hid the resume-discovery hook from every diff.
  const key = semester === null || !userId
    ? ""
    : `${nonce}\u0000${userId}\u0000${semester}`;
  const current = loaded?.key === key ? loaded : null;
  const status: QuizHome["status"] = !key || !current
    ? "loading"
    : current.error
      ? "error"
      : "ready";

  useEffect(() => {
    if (!key) return;
    let cancelled = false;

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
        if (cancelled) return;

        const attempts = attemptRes.attempts ?? [];
        setLoaded({
          key,
          courses: courseRes.courses ?? [],
          nodes: (graphRes.nodes ?? []) as GraphNode[],
          edges: (graphRes.edges ?? []) as GraphEdge[],
          attempts,
          error: null,
        });

        const found = await discoverResumable(attempts, loadSession());
        if (cancelled) return;
        setResumable({ key, value: found });
      } catch (err) {
        if (cancelled) return;
        setLoaded({ key, ...EMPTY_LOAD, error: describeQuizError(err) });
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [key, userId, semester]);

  const { nodes, edges, courses, attempts } = current ?? EMPTY_LOAD;
  const error = current?.error ?? null;

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

  // Which concept the card will show. The entry overrides the ranking (§5 B1.2),
  // so describing the ranked primary would have paid for an LLM call about a
  // concept nobody is looking at — and left the deep-linked card with no
  // paragraph at all. An entry that can't be resolved (a link into a term the
  // student isn't viewing) falls through to the ranking rather than showing
  // nothing.
  //
  // `describable` rides along because the two queue-shaped entries produce a
  // card with no definition slot at all — the concept id is still needed (it is
  // what Start generates on, and what the accent comes from), but a paragraph
  // about the first concept in a queue is text nothing renders.
  const card = useMemo<{ conceptId: string | null; describable: boolean }>(() => {
    if (entry?.concept || entry?.topic) {
      const resolved = entrySelection(entry, scopedNodes, scopedCourses).conceptId;
      if (resolved) return { conceptId: resolved, describable: true };
    } else if (entry?.course) {
      const first = queueFor("course", scopedNodes, entry.course)[0];
      if (first) return { conceptId: first, describable: false };
    } else if (entry?.scope === "due") {
      const first = queueFor("due", scopedNodes)[0];
      if (first) return { conceptId: first, describable: false };
    }
    // An entry that resolved to nothing lands here too, so an unusable
    // `?course=` degrades to an ordinary primary card — description and all.
    return { conceptId: primary?.node.id ?? null, describable: true };
  }, [entry, scopedNodes, scopedCourses, primary]);
  const cardConceptId = card.conceptId;
  const describable = card.describable;

  // One LLM call per home visit, for the one card that shows a paragraph (R-8).
  // `graph_nodes` has no `description` column, so there is nothing stored to
  // read; fetching this for every row on screen would multiply the cost by the
  // length of the list, which is exactly why it is scoped to the card.
  // Tagged with the concept it describes, so changing cards drops the old
  // sentence without a synchronous reset in the effect body.
  const [described, setDescribed] = useState<{ id: string; text: string } | null>(null);
  const cardNode = useMemo(
    () => scopedNodes.find(n => n.id === cardConceptId) ?? null,
    [scopedNodes, cardConceptId],
  );
  const cardName = cardNode?.concept_name ?? null;
  const cardCourseLabel = cardNode?.course_id
    ? scopedCourses.find(c => c.course_id === cardNode.course_id)?.course_code
    : undefined;

  useEffect(() => {
    if (!userId || !cardConceptId || !cardName || !describable) return;
    let cancelled = false;
    describeConcept(userId, cardName, cardCourseLabel).then(
      description => {
        const text = description.trim();
        if (!cancelled && text) setDescribed({ id: cardConceptId, text });
      },
      () => {
        // The card renders the built fallback sentence instead. A missing
        // definition must never hold up the Start button.
      },
    );
    return () => {
      cancelled = true;
    };
  }, [userId, cardConceptId, cardName, cardCourseLabel, describable]);

  const cardDescription =
    describable && described?.id === cardConceptId ? described.text : null;

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
    resumable: resumable?.key === key ? resumable.value : null,
    cardConceptId,
    cardDescription,
    primaryDescription: cardDescription,
    refresh,
  };
}

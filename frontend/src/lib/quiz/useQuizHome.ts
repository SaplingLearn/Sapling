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

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useFlag } from "@/context/FlagsContext";
import { getCourses, getGraph, type EnrolledCourse } from "@/lib/api";
import { LEARNING_LOOP_FLAG } from "@/lib/learningLoopFlag";
import { courseInTerm } from "@/lib/useActiveSemester";
import type { GraphEdge, GraphNode } from "@/lib/types";
import { abandonAttempt, getAttempt, getQuizPlan, listAttempts } from "./api";
import { cachedDescription, loadDescription } from "./conceptDescriptions";
import { describeQuizError, type QuizError } from "./errors";
import {
  alternativesOf,
  courseQueueFromPlan,
  dueFromPlan,
  dueSet,
  entrySelection,
  groupByCourse,
  primaryOf,
  queueFor,
  rankCandidates,
  rankFromPlan,
  type Candidate,
} from "./proposals";
import { dismissAttempt, isDismissed, loadSession, QUEUE_MAX } from "./session";
import type { EntryRequest } from "./source";
import type { AttemptDetail, AttemptSummary, QuizPlan, QuizSession } from "./types";

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
  /** The concept ids "Review everything due" works through, in order. */
  dueQueue: string[];
  /**
   * Learning-loop spec §13 A143: the proposals, the card's suggestion and the
   * due queue come from the learner model's plan (`quiz_concept_plan` on and
   * `GET /api/quiz/plan` answered). False: the graph-tier ranking above.
   */
  planned: boolean;
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
  /**
   * The card's description is being fetched and nothing is remembered for it
   * yet. The card shows a placeholder rather than the built stand-in, so the
   * student never sees one sentence replaced by another a moment later; the
   * stand-in is only for a failed fetch.
   */
  cardDescriptionPending: boolean;
  /** Warm the description of a concept the student is about to pick (a row's
   *  hover or focus), so it is there when the card swaps to it. */
  prefetchDescription(conceptId: string): void;
  refresh(): void;
  /** Close an unfinished attempt for good — the resume strip's Discard. */
  discard(attemptId: string): void;
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
 * this browser has no record at all. Locally dismissed ids are skipped before
 * either pass spends a request on them — `discard` writes that flag the instant
 * the student presses the button, ahead of the abandon call that makes it
 * durable (G4).
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
  /** Spec §13 A143: the learner model's plan, or null (flag off, or it failed). */
  plan: QuizPlan | null;
  error: QuizError | null;
}

const EMPTY_LOAD = {
  nodes: [] as GraphNode[],
  edges: [] as GraphEdge[],
  courses: [] as EnrolledCourse[],
  attempts: [] as AttemptSummary[],
  plan: null as QuizPlan | null,
};

/** `quiz_concept_plan` for this student. Like every quiz learning flag it needs
 *  the student's `learning_loop` flag on as well (the server 404s the plan
 *  otherwise), so a flag-off student never asks for it. */
function useQuizPlanFlag(): boolean {
  const planFlag = useFlag("quiz_concept_plan");
  const loopFlag = useFlag(LEARNING_LOOP_FLAG);
  return planFlag === "on" && loopFlag === "on";
}

/**
 * @param userId  the signed-in student.
 * @param semester the active semester label, or `null` while it is still
 *   hydrating from localStorage — nothing is fetched until it resolves. The
 *   empty string means "All semesters" and fetches unscoped (#360).
 * @param picked  a concept the student chose from the home's topic list,
 *   which the card then shows (and this hook describes) in place of the
 *   entry's or the ranking's.
 */
export function useQuizHome(
  userId: string,
  semester: string | null,
  entry?: EntryRequest,
  picked?: string | null,
): QuizHome {
  const [loaded, setLoaded] = useState<Loaded | null>(null);
  const [resumable, setResumable] = useState<{ key: string; value: ResumableQuiz | null } | null>(
    null,
  );
  const [nonce, setNonce] = useState(0);
  // Spec §13 A143: the learner model's plan replaces the tier ranking. Read
  // once per load; while the flags are still loading this is "off", and the
  // load re-runs when it turns on.
  const planOn = useQuizPlanFlag();

  const refresh = useCallback(() => setNonce(n => n + 1), []);

  /**
   * Discard an unfinished attempt (G4): drop it from the strip here, and close
   * it server-side.
   *
   * `POST /attempts/{id}/abandon` is the durable half — it stamps
   * `abandoned_at`, so a reload and the student's other devices stop offering
   * the attempt (see `routes/quiz.py::abandon_attempt` for why that endpoint
   * exists). Everything else in here is about what THIS screen shows in the
   * meantime.
   *
   * NO `refresh()`. It used to fire one synchronously beside the POST, which
   * re-read courses + graph + history + a `getAttempt` per open attempt (and
   * re-fired `describeConcept`, since `cardConceptId` transits null through
   * the reload) — a full skeleton flash to change one row. Worse, the re-read
   * routinely OVERTOOK the write and came back `in_progress`, leaving the
   * strip hidden only by the localStorage flag: the single point of failure
   * G4 exists to retire, and one that fails outright in a private window.
   * Clearing the slot directly is both cheaper and the honest ordering —
   * nothing else on this screen derives from an unfinished attempt (the
   * ranking and the "missed N last time" join read COMPLETED attempts only,
   * `proposals.ts`).
   *
   * `dismissAttempt` still runs, and still first: it is what keeps the
   * attempt hidden across the NEXT load, before the abandon lands or if it
   * never does.
   *
   * A failed abandon is swallowed rather than surfaced. The student said
   * discard; putting the quiz back on screen — or a red toast over a discard
   * that visibly worked — would both be worse answers than letting
   * `_sweep_abandoned` collect the row on its own.
   */
  const discard = useCallback((attemptId: string) => {
    if (!attemptId) return;
    dismissAttempt(attemptId);
    setResumable(prev =>
      prev?.value?.attempt.quiz_id === attemptId ? { ...prev, value: null } : prev,
    );
    void abandonAttempt(attemptId).catch(err => {
      console.warn("quiz: abandon failed; the attempt will expire on its own", err);
    });
  }, []);

  // "Loading" is DERIVED from whether the resolved load answers the request
  // currently on screen, rather than stored and reset at the top of the effect:
  // a synchronous setState in an effect body is a cascading render, and the
  // stale-response guard falls out of the same key for free.
  // NUL-delimited so no id or term label can forge a collision. Written as an
  // ESCAPE, never a literal byte: a raw NUL makes git treat the whole file as
  // binary, and this one hid the resume-discovery hook from every diff.
  const key = semester === null || !userId
    ? ""
    : `${nonce}\u0000${userId}\u0000${semester}\u0000${planOn ? "plan" : ""}`;
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
        const [courseRes, graphRes, attemptRes, plan] = await Promise.all([
          getCourses(userId),
          getGraph(userId, semester || undefined),
          listAttempts(userId, { limit: HISTORY_LIMIT }).catch(
            () => ({ total: 0, limit: HISTORY_LIMIT, offset: 0, attempts: [] as AttemptSummary[] }),
          ),
          // A failed plan costs nothing but the plan: the tier ranking stands in.
          planOn ? getQuizPlan(userId).catch(() => null) : Promise.resolve(null),
        ]);
        if (cancelled) return;

        const attempts = attemptRes.attempts ?? [];
        setLoaded({
          key,
          courses: courseRes.courses ?? [],
          nodes: (graphRes.nodes ?? []) as GraphNode[],
          edges: (graphRes.edges ?? []) as GraphEdge[],
          attempts,
          plan,
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
  }, [key, userId, semester, planOn]);

  const { nodes, edges, courses, attempts, plan } = current ?? EMPTY_LOAD;
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
    () => (plan
      ? rankFromPlan(plan, scopedNodes, scopedCourses, attempts)
      : rankCandidates(scopedNodes, scopedCourses, attempts)),
    [plan, scopedNodes, scopedCourses, attempts],
  );
  // The plan's first concept IS the learner model's choice: no studied-first
  // tie-break on top of it (R-7's rule answers the tier ranking's blind spot).
  const primary = useMemo(
    () => (plan ? candidates[0] ?? null : primaryOf(candidates)),
    [plan, candidates],
  );
  const alternatives = useMemo(() => alternativesOf(candidates, primary), [candidates, primary]);
  const due = useMemo(
    () => (plan ? dueFromPlan(plan, scopedNodes) : dueSet(scopedNodes)),
    [plan, scopedNodes],
  );
  const dueQueue = useMemo(
    () => (plan ? due.conceptIds.slice(0, QUEUE_MAX) : queueFor("due", scopedNodes)),
    [plan, due, scopedNodes],
  );
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
    // A concept picked off the topic list outranks every entry: it is the
    // student's latest, explicit choice.
    if (picked && scopedNodes.some(n => n.id === picked)) {
      return { conceptId: picked, describable: true };
    }
    if (entry?.concept || entry?.topic) {
      const resolved = entrySelection(entry, scopedNodes, scopedCourses).conceptId;
      if (resolved) return { conceptId: resolved, describable: true };
    } else if (entry?.course) {
      const first = (plan
        ? courseQueueFromPlan(candidates, entry.course)
        : queueFor("course", scopedNodes, entry.course))[0];
      if (first) return { conceptId: first, describable: false };
    } else if (entry?.scope === "due") {
      const first = dueQueue[0];
      if (first) return { conceptId: first, describable: false };
    }
    // An entry that resolved to nothing lands here too, so an unusable
    // `?course=` degrades to an ordinary primary card — description and all.
    return { conceptId: primary?.node.id ?? null, describable: true };
  }, [entry, scopedNodes, scopedCourses, primary, picked, dueQueue, plan, candidates]);
  const cardConceptId = card.conceptId;
  const describable = card.describable;

  // One LLM call per concept, for the card that shows a paragraph (R-8), and
  // remembered (`conceptDescriptions`: localStorage, and the backend's Redis
  // cache across students) so a concept described once comes back instantly.
  // `graph_nodes` has no `description` column, so there is nothing stored to
  // read; fetching for every row on screen would multiply the cost by the
  // length of the list, which is why only the card fetches, plus a row the
  // student is pointing at (`prefetchDescription`).
  const [described, setDescribed] = useState<Record<string, string>>({});
  const [failed, setFailed] = useState<Record<string, true>>({});
  // Concepts whose hover prefetch failed: not retried on every hover. Kept
  // apart from `failed`, which is the CARD's verdict — a prefetch failure must
  // not stop a later pick from showing its placeholder while it retries.
  const prefetchFailed = useRef<Set<string>>(new Set());
  const labelFor = useCallback(
    (node: GraphNode | null | undefined) =>
      node?.course_id ? scopedCourses.find(c => c.course_id === node.course_id)?.course_code : undefined,
    [scopedCourses],
  );
  const cardNode = useMemo(
    () => scopedNodes.find(n => n.id === cardConceptId) ?? null,
    [scopedNodes, cardConceptId],
  );
  const cardName = cardNode?.concept_name ?? null;
  const cardCourseLabel = labelFor(cardNode);
  const remembered =
    cardConceptId !== null
      ? described[cardConceptId] ?? (cardName ? cachedDescription(userId, cardName, cardCourseLabel) : null)
      : null;

  useEffect(() => {
    if (!userId || !cardConceptId || !cardName || !describable || remembered) return;
    let cancelled = false;
    loadDescription(userId, cardName, cardCourseLabel).then(
      text => {
        if (!cancelled) setDescribed(d => ({ ...d, [cardConceptId]: text }));
      },
      () => {
        // The card renders the built fallback sentence instead. A missing
        // definition must never hold up the Start button.
        if (!cancelled) setFailed(f => ({ ...f, [cardConceptId]: true }));
      },
    );
    return () => {
      cancelled = true;
    };
  }, [userId, cardConceptId, cardName, cardCourseLabel, describable, remembered]);

  const cardDescription = describable && cardConceptId !== null ? remembered : null;
  const cardDescriptionPending =
    describable && cardConceptId !== null && !cardDescription && !failed[cardConceptId] && Boolean(userId);

  const prefetchDescription = useCallback(
    (conceptId: string) => {
      const node = scopedNodes.find(n => n.id === conceptId);
      // Already known either way: nothing to warm, and a failure is not retried
      // on every hover (the card itself retries if the concept is picked).
      if (!userId || !node || conceptId in described || prefetchFailed.current.has(conceptId)) return;
      if (cachedDescription(userId, node.concept_name, labelFor(node))) return;
      loadDescription(userId, node.concept_name, labelFor(node)).then(
        text => setDescribed(d => (d[conceptId] === text ? d : { ...d, [conceptId]: text })),
        () => {
          prefetchFailed.current.add(conceptId);
        },
      );
    },
    [userId, scopedNodes, labelFor, described],
  );

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
    dueQueue,
    planned: plan !== null,
    byCourse,
    resumable: resumable?.key === key ? resumable.value : null,
    cardConceptId,
    cardDescription,
    primaryDescription: cardDescription,
    cardDescriptionPending,
    prefetchDescription,
    refresh,
    discard,
  };
}

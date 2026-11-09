/**
 * Quiz home's derived view — the pure half of `QuizHome`.
 *
 * Everything here is a function of the hook's data, the arrival and the pick:
 * which shape the card has, what it says, which rows the topic list shows, and
 * the requests Start sends. No React, so each rule is unit-tested on its own
 * (`homeView.test.ts`); `useHomeCard` wires them to state.
 */

import type { EnrolledCourse } from "@/lib/api";
import type { SessionConfig, StartRequest } from "@/lib/quiz/machine";
import {
  colorFor,
  latestCompletedAttempt,
  metaLine,
  rationaleFor,
  type Candidate,
} from "@/lib/quiz/proposals";
import { QUEUE_COUNT, QUEUE_MAX } from "@/lib/quiz/session";
import type { EntryRequest } from "@/lib/quiz/source";
import type { AttemptSummary, QuizPrefs, SourceKind } from "@/lib/quiz/types";
import {
  fallbackDefinition,
  type QuizHome as QuizHomeData,
  type ResumableQuiz,
} from "@/lib/quiz/useQuizHome";
import type { GraphEdge, GraphNode } from "@/lib/types";

/** The card's three shapes (§5 B1.2). `course` and `due` run as queues. */
export type CardMode = "concept" | "course" | "due";

/** Which arrival the screen is rendering. */
export type HomeView = "error" | "loading" | "no-courses" | "empty-tree" | "home";

/** Why a deep-linked concept is the one on offer (§5 B1.2). */
const DEEP_LINK_RATIONALE: Partial<Record<SourceKind, string>> = {
  tree: "From your tree",
  notes: "From your note",
};
const DEFAULT_DEEP_LINK_RATIONALE = "Suggested for you";

/** What the entry asks the card to be, before anything is picked. */
export interface Arrival {
  /** The deep-linked concept, resolved (`entrySelection`). */
  conceptId: string | null;
  course?: string;
  scope?: EntryRequest["scope"];
  courseQueue: string[];
  dueQueue: string[];
}

/** A concept picked off the topic list, tied to the arrival it was made on. */
export interface TopicPick {
  entryKey: string;
  id: string;
}

export function entryKeyFor(entry: EntryRequest): string {
  return `${entry.concept ?? ""}|${entry.topic ?? ""}|${entry.course ?? ""}|${entry.scope ?? ""}`;
}

/** The pick, while it still belongs to this arrival and names a real concept. */
export function pickedIdFor(pick: TopicPick | null, entryKey: string, nodes: GraphNode[]): string | null {
  return pick && pick.entryKey === entryKey && nodes.some(n => n.id === pick.id) ? pick.id : null;
}

export function cardModeFor(pickedId: string | null, arrival: Arrival): CardMode {
  if (pickedId || arrival.conceptId) return "concept";
  if (arrival.course && arrival.courseQueue.length > 0) return "course";
  if (arrival.scope === "due" && arrival.dueQueue.length > 0) return "due";
  return "concept";
}

/**
 * The queue the arrival itself proposes ("Practice CS101", "Review everything
 * due"), or `null` when it proposes one concept. Unlike `cardModeFor`, a
 * `?course=` with nothing due never falls through to the due set here.
 */
export function arrivalQueue(arrival: Arrival): string[] | null {
  if (arrival.conceptId) return null;
  if (arrival.course) return arrival.courseQueue.length > 0 ? arrival.courseQueue : null;
  return arrival.scope === "due" && arrival.dueQueue.length > 0 ? arrival.dueQueue : null;
}

/**
 * A concept as the card and the dialogs want it. Ranked candidates come with
 * their rationale already resolved; anything else (a mastered concept picked
 * out of the list, say) is built the same way `rankCandidates` would.
 */
export function candidateOf(
  nodeId: string | null | undefined,
  home: Pick<QuizHomeData, "candidates" | "nodes" | "courses" | "attempts">,
): Candidate | null {
  if (!nodeId) return null;
  const ranked = home.candidates.find(c => c.node.id === nodeId);
  if (ranked) return ranked;
  const node = home.nodes.find(n => n.id === nodeId);
  if (!node) return null;
  const course = home.courses.find(c => c.course_id === node.course_id) ?? null;
  const lastAttempt = latestCompletedAttempt(node.id, home.attempts);
  return {
    node,
    course,
    color: colorFor(node, course),
    rationale: rationaleFor(node, lastAttempt),
    ...(lastAttempt ? { lastAttempt } : {}),
  };
}

// ── Copy ────────────────────────────────────────────────────────────────

export function cardCourseCode(
  mode: CardMode,
  entryCourse: EnrolledCourse | null,
  card: Candidate | null,
): string {
  return (mode === "course" ? entryCourse : card?.course)?.course_code ?? "";
}

export function cardTitle(mode: CardMode, courseCode: string, conceptName: string): string {
  if (mode === "course") return `Practice ${courseCode}`;
  if (mode === "due") return "Review everything due";
  return conceptName;
}

export function cardMeta(
  mode: CardMode,
  courseQueueLength: number,
  due: QuizHomeData["due"],
  card: Candidate | null,
): string {
  if (mode === "course") return `${courseQueueLength} concepts due`;
  if (mode === "due") {
    return `${due.count} concepts across ${due.courseCount} courses · starting with the ${Math.min(due.count, QUEUE_MAX)} weakest`;
  }
  return card ? metaLine(card.node) : "";
}

/** Only a deep link explains itself on the card: it is the one arrival whose
 *  proposal the student did not just get from the ranking. */
export function cardRationale(
  mode: CardMode,
  pickedId: string | null,
  conceptId: string | null,
  card: Candidate | null,
  sourceKind: SourceKind,
): string | null {
  if (mode !== "concept" || pickedId || !conceptId || !card) return null;
  return DEEP_LINK_RATIONALE[sourceKind] ?? DEFAULT_DEEP_LINK_RATIONALE;
}

/** The `n` in "{Course} · {tier} · {n} connected concepts" (R-8's fallback). */
export function connectedCount(edges: GraphEdge[], nodeId: string | undefined): number {
  return nodeId ? edges.filter(e => e.source === nodeId || e.target === nodeId).length : 0;
}

export interface CardDefinition {
  definition: string | null;
  pending: boolean;
}

/**
 * R-8's sentence, fetched by the hook for the concept the CARD shows — a deep
 * link included (A2 fix round 5). The two queued shapes show no definition at
 * all: it describes one concept and would read as a caption for the wrong
 * thing under "Practice CS101".
 *
 * The hook describes ITS card; for the frame between a pick here and the hook
 * catching up, the two can differ, and that frame counts as pending. The built
 * sentence is only for a description that could not be fetched: shown first
 * and replaced a moment later, it read as a glitch.
 */
export function cardDefinition(
  queued: boolean,
  card: Candidate | null,
  home: Pick<QuizHomeData, "cardConceptId" | "cardDescription" | "cardDescriptionPending" | "edges">,
): CardDefinition {
  const hookOnCard = home.cardConceptId === card?.node.id;
  const description = hookOnCard ? home.cardDescription : null;
  const pending = !queued && !description && (!hookOnCard || home.cardDescriptionPending);
  if (queued || pending) return { definition: null, pending };
  return {
    definition: description ?? (card ? fallbackDefinition(card, connectedCount(home.edges, card.node.id)) : ""),
    pending,
  };
}

export function configLineFor(queued: boolean, config: SessionConfig): string {
  const feedbackSuffix = config.feedback === "as-you-go" ? " · answers as you go" : "";
  return queued
    ? `${QUEUE_COUNT} questions each, ${config.difficulty}${feedbackSuffix}`
    : `${config.count} questions, ${config.difficulty}${feedbackSuffix}`;
}

/**
 * A queued session is QUEUE_COUNT questions per concept by default (R-4).
 * That is what the card starts with AND what its Adjust dialog opens on —
 * otherwise "Start · 5 medium" would quietly run three-question attempts.
 */
export function effectiveConfigFor(queued: boolean, config: SessionConfig): SessionConfig {
  return queued ? { ...config, count: QUEUE_COUNT } : config;
}

export function adjustSubtitle(conceptName: string, courseCode: string): string {
  return courseCode ? `${conceptName} · ${courseCode}` : conceptName;
}

/** The choices a dialog was started with, as remembered prefs (§5 B1.6). */
export function prefsFor(cfg: SessionConfig): QuizPrefs {
  return {
    count: cfg.count,
    difficulty: cfg.difficulty,
    feedback: cfg.feedback,
    ...(cfg.questionFormat ? { questionFormat: cfg.questionFormat } : {}),
  };
}

// ── Starting ────────────────────────────────────────────────────────────

export function conceptStartRequest(candidate: Candidate): StartRequest {
  return {
    intent: "practice",
    scope: { kind: "concept", conceptId: candidate.node.id },
    conceptId: candidate.node.id,
    courseId: candidate.node.course_id ?? null,
  };
}

/** A queue starts on its first concept (`/generate` is per concept, R-4). */
export function queueStartRequest(
  kind: "course" | "due",
  queue: string[],
  nodes: GraphNode[],
  courseId?: string,
): StartRequest {
  const first = queue[0];
  return {
    intent: kind === "due" ? "review" : "practice",
    scope:
      kind === "due"
        ? { kind: "due", queue }
        : { kind: "course", courseId: courseId ?? "", queue },
    conceptId: first,
    courseId: nodes.find(n => n.id === first)?.course_id ?? null,
  };
}

// ── Swapping the card ───────────────────────────────────────────────────

/**
 * Picking the suggestion's own concept IS going back to the suggestion —
 * except when the suggestion is a queue, where that one concept on its own is
 * a real choice (and the queue card has no other way to it).
 */
export function pickTargetFor(
  requested: string | null,
  suggestedIsQueue: boolean,
  suggestedId: string | undefined,
): string | null {
  return requested && !suggestedIsQueue && requested === suggestedId ? null : requested;
}

/** A queued card is titled for its course or the due set; its first concept
 *  never left the list, so there is no row to point back to. */
export function returnedIdFor(
  mode: CardMode,
  outgoingId: string | null,
  incomingId: string | null,
): string | null {
  return mode === "concept" && outgoingId !== incomingId ? outgoingId : null;
}

// ── The topic list ──────────────────────────────────────────────────────

/**
 * The card's own concept is not offered again beside it. A queued card is
 * titled for the course or the due set, not its first concept, so there the
 * first concept stays in the list. A search finds everything, the card's
 * concept included: hiding a match the student typed would read as missing.
 */
export function hiddenTopicFor(mode: CardMode, query: string, card: Candidate | null): string | undefined {
  return mode === "concept" && !query ? card?.node.id : undefined;
}

/** A narrowed course that has since left the list (a semester switch) falls
 *  back to every course rather than an empty list. */
export function courseFilterFor(byCourse: QuizHomeData["byCourse"], topicCourse: string): string {
  return byCourse.some(g => g.course.course_id === topicCourse) ? topicCourse : "all";
}

function topicMatches(node: GraphNode, courseCode: string, hiddenTopic: string | undefined, query: string): boolean {
  return (
    node.id !== hiddenTopic &&
    (!query ||
      node.concept_name.toLowerCase().includes(query) ||
      courseCode.toLowerCase().includes(query))
  );
}

export function filterTopicGroups(
  byCourse: QuizHomeData["byCourse"],
  courseFilter: string,
  hiddenTopic: string | undefined,
  query: string,
): QuizHomeData["byCourse"] {
  return byCourse
    .filter(g => courseFilter === "all" || g.course.course_id === courseFilter)
    .map(g => ({
      ...g,
      nodes: g.nodes.filter(n => topicMatches(n, g.course.course_code, hiddenTopic, query)),
    }))
    .filter(g => g.nodes.length > 0);
}

export function emptyTopicsCopy(topicQuery: string, narrowedCourse: EnrolledCourse | undefined): string {
  if (topicQuery.trim()) return `No concepts match “${topicQuery.trim()}”`;
  if (narrowedCourse) return `Nothing else in ${narrowedCourse.course_code} yet`;
  return "Nothing else on your tree yet";
}

// ── Regions ─────────────────────────────────────────────────────────────

export function homeViewFor(
  status: QuizHomeData["status"],
  courseCount: number,
  conceptCount: number,
): HomeView {
  if (status === "error") return "error";
  if (status === "loading") return "loading";
  if (courseCount === 0) return "no-courses";
  if (conceptCount === 0) return "empty-tree";
  return "home";
}

export function resumeNameFor(
  resumable: ResumableQuiz,
  nodes: GraphNode[],
  attempts: AttemptSummary[],
): string {
  return (
    nodes.find(n => n.id === resumable.attempt.concept_node_id)?.concept_name ??
    attempts.find(a => a.quiz_id === resumable.attempt.quiz_id)?.concept_name ??
    "a concept"
  );
}

export function resumeTotalFor(resumable: ResumableQuiz): number {
  return resumable.attempt.questions.length || resumable.attempt.total || 0;
}

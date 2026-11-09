"use client";

/**
 * Quiz home's card — the stateful half of `QuizHome`.
 *
 * What the card is about (the arrival, a pick off the topic list), what it
 * says, how it starts, and how a pick swaps it in place. The rules themselves
 * are the pure functions in `./homeView`; this wires them to React state with
 * the same memo/callback identities the screen had inline, so the
 * neighbourhood's memoised graph is not re-rendered on every search keystroke.
 */

import React from "react";
import { useToast } from "@/components/ToastProvider";
import type { SessionConfig } from "@/lib/quiz/machine";
import { entrySelection, queueFor, type Candidate } from "@/lib/quiz/proposals";
import type { EntryRequest } from "@/lib/quiz/source";
import type { QuizSession } from "@/lib/quiz/types";
import type { QuizHome as QuizHomeData } from "@/lib/quiz/useQuizHome";
import type { QuizActions } from "@/lib/quiz/useQuizSession";
import {
  arrivalQueue,
  candidateOf,
  cardCourseCode,
  cardDefinition,
  cardMeta,
  cardModeFor,
  cardRationale,
  cardTitle,
  conceptStartRequest,
  configLineFor,
  courseFilterFor,
  effectiveConfigFor,
  emptyTopicsCopy,
  entryKeyFor,
  filterTopicGroups,
  hiddenTopicFor,
  pickedIdFor,
  pickTargetFor,
  queueStartRequest,
  returnedIdFor,
  type Arrival,
  type CardMode,
  type TopicPick,
} from "./homeView";

/** How long a swapped-out concept's row stays tinted — `--quiz-home-returned-dur`. */
const RETURNED_TINT_MS = 1400;

/** §6: a link into a term the student isn't looking at. */
const UNRESOLVED_COPY = "That concept isn't in your current semester";

// ── What the card is about ──────────────────────────────────────────────

function useArrival(home: QuizHomeData, entry: EntryRequest) {
  const toast = useToast();
  const selection = React.useMemo(
    () => entrySelection(entry, home.nodes, home.courses),
    [entry, home.nodes, home.courses],
  );

  // A deep link naming something outside the active semester says so once and
  // then gets out of the way — the ordinary home renders underneath (§6).
  const toasted = React.useRef(false);
  React.useEffect(() => {
    if (toasted.current || home.status !== "ready" || !selection.unresolved) return;
    toasted.current = true;
    toast.info(UNRESOLVED_COPY);
  }, [home.status, selection.unresolved, toast]);

  const courseQueue = React.useMemo(
    () => (entry.course ? queueFor("course", home.nodes, entry.course) : []),
    [entry.course, home.nodes],
  );
  const dueQueue = React.useMemo(() => queueFor("due", home.nodes), [home.nodes]);
  const arrival: Arrival = {
    conceptId: selection.conceptId,
    course: entry.course,
    scope: entry.scope,
    courseQueue,
    dueQueue,
  };
  return { selection, arrival };
}

/**
 * A concept picked off the topic list (or the neighbourhood). It belongs to
 * the arrival it was made on: a new entry (another deep link) starts from
 * that entry's own card again, without an effect to reset it.
 */
function usePick(
  nodes: QuizHomeData["nodes"],
  entry: EntryRequest,
  onPickedChange: ((conceptId: string | null) => void) | undefined,
) {
  const entryKey = entryKeyFor(entry);
  const [pick, setPick] = React.useState<TopicPick | null>(null);
  const pickedId = pickedIdFor(pick, entryKey, nodes);

  React.useEffect(() => {
    onPickedChange?.(pickedId);
  }, [pickedId, onPickedChange]);

  return { entryKey, pickedId, setPick };
}

function useCardCandidates(home: QuizHomeData, entry: EntryRequest, arrival: Arrival, pickedId: string | null) {
  const candidateFor = React.useCallback(
    (nodeId: string | null | undefined): Candidate | null =>
      candidateOf(nodeId, {
        candidates: home.candidates,
        nodes: home.nodes,
        courses: home.courses,
        attempts: home.attempts,
      }),
    [home.candidates, home.nodes, home.courses, home.attempts],
  );

  /** The card the arrival itself proposes — what "Back to the suggestion"
   *  returns to. */
  const { conceptId, courseQueue, dueQueue } = arrival;
  const suggested = React.useMemo(() => {
    const queue = arrivalQueue({ conceptId, course: entry.course, scope: entry.scope, courseQueue, dueQueue });
    if (queue) return candidateFor(queue[0]);
    return candidateFor(conceptId) ?? home.primary;
  }, [conceptId, entry.course, entry.scope, courseQueue, dueQueue, candidateFor, home.primary]);

  const card = React.useMemo(
    () => (pickedId ? candidateFor(pickedId) : suggested),
    [pickedId, candidateFor, suggested],
  );

  const entryCourse = React.useMemo(
    () => home.courses.find(c => c.course_id === entry.course) ?? null,
    [home.courses, entry.course],
  );

  return { suggested, card, entryCourse };
}

// ── Starting ────────────────────────────────────────────────────────────

function useCardStart(
  actions: QuizActions,
  nodes: QuizHomeData["nodes"],
  mode: CardMode,
  arrival: Arrival,
  card: Candidate | null,
) {
  const startConcept = React.useCallback(
    (candidate: Candidate, cfg: SessionConfig) => {
      actions.start(conceptStartRequest(candidate), cfg);
    },
    [actions],
  );

  const startQueue = React.useCallback(
    (kind: "course" | "due", queue: string[], cfg: SessionConfig, courseId?: string) => {
      if (queue.length === 0) return;
      actions.start(queueStartRequest(kind, queue, nodes, courseId), cfg);
    },
    [actions, nodes],
  );

  /** The card's own Start, in whichever shape it currently has. */
  const { courseQueue, dueQueue, course } = arrival;
  const startCard = React.useCallback(
    (cfg: SessionConfig) => {
      if (mode === "course") return startQueue("course", courseQueue, cfg, course);
      if (mode === "due") return startQueue("due", dueQueue, cfg);
      if (card) startConcept(card, cfg);
    },
    [mode, startQueue, courseQueue, dueQueue, course, card, startConcept],
  );

  return { startQueue, startCard };
}

// ── Swapping the card ───────────────────────────────────────────────────
//
// Picking a concept makes it the card, in place: Start and Adjust then act
// on it. The swap is deliberately quiet: the card fades up into place (its
// neighbourhood re-settles around the new concept), and the row the old
// card's concept returns to is tinted for a moment so the eye finds it.
// Reduced motion: it just changes.

interface SwapInputs {
  mode: CardMode;
  card: Candidate | null;
  suggested: Candidate | null;
  suggestedIsQueue: boolean;
  pickedId: string | null;
  entryKey: string;
  setPick: (pick: TopicPick | null) => void;
  reducedMotion: boolean;
}

/** Stacked (phone), the card is above the list the student clicked in. */
function scrollCardIntoView(proposal: HTMLElement | null, reducedMotion: boolean) {
  if (window.matchMedia?.("(max-width: 900px)").matches) {
    proposal?.scrollIntoView({ behavior: reducedMotion ? "auto" : "smooth", block: "start" });
  }
}

function useCardSwap({ mode, card, suggested, suggestedIsQueue, pickedId, entryKey, setPick, reducedMotion }: SwapInputs) {
  const [swapped, setSwapped] = React.useState(false);
  /** The row a swapped-out concept returns to, flashed once. */
  const [returnedId, setReturnedId] = React.useState<string | null>(null);
  const proposalRef = React.useRef<HTMLElement>(null);

  // The tint lasts as long as its animation; cleared after, so a later
  // re-render of the list (a filter, a search) does not replay it.
  React.useEffect(() => {
    if (!returnedId) return;
    const timer = window.setTimeout(() => setReturnedId(null), RETURNED_TINT_MS);
    return () => window.clearTimeout(timer);
  }, [returnedId]);

  // Stable across renders that don't change what a pick means, so the
  // neighbourhood's memoised graph isn't re-rendered on every search keystroke.
  const choose = React.useCallback(
    (requested: string | null) => {
      const target = pickTargetFor(requested, suggestedIsQueue, suggested?.node.id);
      // Compare the PICK, not the concept on screen: a queue card shows its
      // first concept without that concept being picked.
      if (target === pickedId) return;
      const outgoingId = card?.node.id ?? null;
      const incomingId = target ?? suggested?.node.id ?? null;
      setPick(target ? { entryKey, id: target } : null);
      setSwapped(true);
      setReturnedId(returnedIdFor(mode, outgoingId, incomingId));
      scrollCardIntoView(proposalRef.current, reducedMotion);
    },
    [suggestedIsQueue, suggested, pickedId, card, entryKey, mode, reducedMotion, setPick],
  );

  return { swapped, returnedId, proposalRef, choose };
}

// ── Copy ────────────────────────────────────────────────────────────────

function cardCopy(
  home: QuizHomeData,
  entry: EntryRequest,
  session: QuizSession,
  view: { mode: CardMode; card: Candidate | null; pickedId: string | null; arrival: Arrival; entryCourse: QuizHomeData["courses"][number] | null },
) {
  const { mode, card, pickedId, arrival, entryCourse } = view;
  const queued = mode !== "concept";
  const conceptName = card?.node.concept_name ?? "";
  const courseCode = cardCourseCode(mode, entryCourse, card);
  const { definition, pending } = cardDefinition(queued, card, home);
  return {
    accent: card?.color ?? null,
    queued,
    conceptName,
    courseCode,
    title: cardTitle(mode, courseCode, conceptName),
    meta: cardMeta(mode, arrival.courseQueue.length, home.due, card),
    rationale: cardRationale(mode, pickedId, arrival.conceptId, card, entry.source.kind),
    definition,
    definitionPending: pending,
    configLine: configLineFor(queued, session.config),
    effectiveConfig: effectiveConfigFor(queued, session.config),
  };
}

export interface HomeCardInputs {
  home: QuizHomeData;
  entry: EntryRequest;
  session: QuizSession;
  actions: QuizActions;
  onPickedChange?: (conceptId: string | null) => void;
  reducedMotion: boolean;
}

/** Everything the card shows and does, for the arrival and the pick. */
export function useHomeCard({ home, entry, session, actions, onPickedChange, reducedMotion }: HomeCardInputs) {
  const { arrival } = useArrival(home, entry);
  const { entryKey, pickedId, setPick } = usePick(home.nodes, entry, onPickedChange);
  const mode = cardModeFor(pickedId, arrival);
  const { suggested, card, entryCourse } = useCardCandidates(home, entry, arrival, pickedId);
  const { startQueue, startCard } = useCardStart(actions, home.nodes, mode, arrival, card);
  const swap = useCardSwap({
    mode,
    card,
    suggested,
    suggestedIsQueue: arrivalQueue(arrival) !== null,
    pickedId,
    entryKey,
    setPick,
    reducedMotion,
  });
  const copy = cardCopy(home, entry, session, { mode, card, pickedId, arrival, entryCourse });
  return {
    mode,
    card,
    suggested,
    pickedId,
    /** The concept the link named, resolved on this term (`null`: none, or another term). */
    arrivalConceptId: arrival.conceptId,
    dueQueue: arrival.dueQueue,
    startQueue,
    startCard,
    ...swap,
    ...copy,
  };
}

/** The topic list's search and course filter, and the rows they leave. */
export function useTopicFilter(byCourse: QuizHomeData["byCourse"], mode: CardMode, card: Candidate | null) {
  const [topicQuery, setTopicQuery] = React.useState("");
  /** "all", or the one course the topic list is narrowed to. */
  const [topicCourse, setTopicCourse] = React.useState("all");

  const query = topicQuery.trim().toLowerCase();
  const hiddenTopic = hiddenTopicFor(mode, query, card);
  const courseFilter = courseFilterFor(byCourse, topicCourse);
  const topicGroups = React.useMemo(
    () => filterTopicGroups(byCourse, courseFilter, hiddenTopic, query),
    [byCourse, hiddenTopic, query, courseFilter],
  );
  const narrowedCourse = byCourse.find(g => g.course.course_id === courseFilter)?.course;

  return {
    topicQuery,
    setTopicQuery,
    courseFilter,
    setTopicCourse,
    topicGroups,
    emptyTopics: emptyTopicsCopy(topicQuery, narrowedCourse),
  };
}

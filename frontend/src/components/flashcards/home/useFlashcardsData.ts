"use client";
/**
 * The Flashcards page's reads, one hook per source. Each is "latest request
 * wins" (`useLatestRequest`), and each keeps what it loaded under the key it
 * was loaded for, so a course or term switch never shows the previous one's
 * answer while the new one is in flight.
 *
 *   cards ......... getFlashcards(userId, undefined, semester)
 *   concepts ...... getGraph(userId, semester) + getTopicChecklist (the Study
 *                   hub's roadmap, built by the hub's own functions)
 *   exams ......... getAllAssignments
 *   saved sets .... lib/flashcardSetsApi
 *
 * The outline is only READ here. Generating or refreshing it stays the Study
 * hub's job (it calls a model and is rate-limited).
 */
import React from "react";
import { getAllAssignments, getFlashcards, getGraph, type Assignment } from "@/lib/api";
import { humanizeError } from "@/lib/errorMessage";
import {
  createFlashcardSet,
  deleteFlashcardSet,
  listFlashcardSets,
  updateFlashcardSet,
  type FlashcardSet,
  type FlashcardSetPatch,
  type NewFlashcardSet,
} from "@/lib/flashcardSetsApi";
import { getTopicChecklist, type ChecklistTopic } from "@/lib/topicChecklistApi";
import { useLatestRequest } from "@/lib/useLatestRequest";
import { useToast } from "../../ToastProvider";
import { categoriesFromChecklist, conceptsForCourse, type Concept } from "../../study/studyModel";
import { examsForCourse, type Card, type ExamRef } from "./flashcardsModel";

// ── cards ────────────────────────────────────────────────────────────────────

export interface CardsState {
  cards: Card[];
  /** The first load has answered (or failed). */
  loaded: boolean;
  loading: boolean;
  /** The last load failed: what is shown is not the student's real deck. */
  failed: boolean;
  /** "Now" for due dates, as of the last load. */
  now: number;
  /** Re-reads the list; resolves with it, or null when it failed or a newer
   *  read took over. */
  reload: () => Promise<Card[] | null>;
}

/**
 * The student's cards for the active term. Fetches gate on `semesterReady` so
 * a stored term never double-fetches (#141), and a term switch or a reload
 * racing an older one resolves to the latest (#769).
 */
export function useCards(userId: string, semester: string, semesterReady: boolean, fixedNow?: Date): CardsState {
  const [cards, setCards] = React.useState<Card[]>([]);
  const [loaded, setLoaded] = React.useState(false);
  const [loading, setLoading] = React.useState(false);
  const [failed, setFailed] = React.useState(false);
  const [now, setNow] = React.useState(() => fixedNow?.getTime() ?? Date.now());
  const req = useLatestRequest();

  const reload = React.useCallback(async (): Promise<Card[] | null> => {
    if (!userId) return null;
    const run = req.begin();
    setLoading(true);
    try {
      const res = await getFlashcards(userId, undefined, semester || undefined);
      if (!run.isCurrent()) return null;
      const list: Card[] = res.flashcards || [];
      setCards(list);
      setFailed(false);
      setLoaded(true);
      setNow(fixedNow?.getTime() ?? Date.now());
      return list;
    } catch (err) {
      if (!run.isCurrent()) return null;
      console.error("flashcards load failed", err);
      setFailed(true);
      setLoaded(true);
      return null;
    } finally {
      if (run.isCurrent()) setLoading(false);
    }
  }, [userId, semester, req, fixedNow]);

  React.useEffect(() => {
    if (semesterReady) void reload();
  }, [reload, semesterReady]);

  return { cards, loaded, loading, failed, now, reload };
}

// ── concepts ─────────────────────────────────────────────────────────────────

/* eslint-disable @typescript-eslint/no-explicit-any -- getGraph is untyped (any[]) */
type Graph = { key: string; nodes: any[]; edges: any[] };
/* eslint-enable @typescript-eslint/no-explicit-any */
type Outline = { key: string; topics: ChecklistTopic[] };

export interface CourseConcepts {
  concepts: Concept[];
  /** The course's topic checklist (which concepts each exam covers). */
  outline: ChecklistTopic[];
  /** Both reads have answered for this course (or there is no course). */
  ready: boolean;
}

/** The course's concepts in the Study hub's roadmap groups. */
export function useCourseConcepts(
  userId: string,
  courseId: string,
  semester: string,
  semesterReady: boolean,
  today: Date,
): CourseConcepts {
  const toast = useToast();
  const [graph, setGraph] = React.useState<Graph | null>(null);
  const [outline, setOutline] = React.useState<Outline | null>(null);
  const graphReq = useLatestRequest();
  const outlineReq = useLatestRequest();
  const hasCourse = !!courseId;
  const graphKey = `${userId}|${semester}`;
  const outlineKey = `${userId}|${courseId}|${semester}`;

  // The graph is the student's whole term, so it is read once per term and
  // filtered per course below.
  React.useEffect(() => {
    if (!userId || !hasCourse || !semesterReady) return;
    const run = graphReq.begin();
    getGraph(userId, semester || undefined)
      .then(r => { if (run.isCurrent()) setGraph({ key: graphKey, nodes: r.nodes || [], edges: r.edges || [] }); })
      .catch(err => {
        if (!run.isCurrent()) return;
        console.error("flashcards graph load failed", err);
        setGraph({ key: graphKey, nodes: [], edges: [] });
        toast.error(humanizeError(err, "Couldn't load your concepts."));
      });
    return graphReq.cancel;
  }, [userId, hasCourse, semester, semesterReady, graphKey, graphReq, toast]);

  // A course with no outline (or a failed read) answers with nothing to
  // place: the columns fall back to the hub's prerequisite layers.
  React.useEffect(() => {
    if (!userId || !courseId || !semesterReady) return;
    const run = outlineReq.begin();
    getTopicChecklist(userId, courseId, semester || undefined)
      .then(r => { if (run.isCurrent()) setOutline({ key: outlineKey, topics: r.topics || [] }); })
      .catch(err => {
        if (!run.isCurrent()) return;
        console.error("flashcards outline load failed", err);
        setOutline({ key: outlineKey, topics: [] });
      });
    return outlineReq.cancel;
  }, [userId, courseId, semester, semesterReady, outlineKey, outlineReq]);

  const liveGraph = graph?.key === graphKey ? graph : null;
  const liveOutline = outline?.key === outlineKey ? outline : null;
  const concepts = React.useMemo(
    () => (liveGraph && liveOutline
      ? conceptsForCourse(liveGraph.nodes, liveGraph.edges, courseId, today, categoriesFromChecklist(liveOutline.topics))
      : []),
    [liveGraph, liveOutline, courseId, today],
  );
  const topics = React.useMemo(() => liveOutline?.topics ?? [], [liveOutline]);
  return { concepts, outline: topics, ready: !hasCourse || (!!liveGraph && !!liveOutline) };
}

// ── exams ────────────────────────────────────────────────────────────────────

/** The course's dated exams and quizzes. A failed read just leaves none. */
export function useCourseExams(userId: string, courseId: string): ExamRef[] {
  const [assignments, setAssignments] = React.useState<Assignment[]>([]);
  const req = useLatestRequest();
  React.useEffect(() => {
    if (!userId) return;
    const run = req.begin();
    getAllAssignments(userId)
      .then(r => { if (run.isCurrent()) setAssignments(r.assignments || []); })
      .catch(err => { if (run.isCurrent()) console.error("flashcards exams load failed", err); });
    return req.cancel;
  }, [userId, req]);
  return React.useMemo(() => examsForCourse(assignments, courseId), [assignments, courseId]);
}

// ── saved sets ───────────────────────────────────────────────────────────────

export interface SetsState {
  /** null: not loaded, or the list could not be read (the shelf is left out). */
  sets: FlashcardSet[] | null;
  /** The list has answered for this course, or failed, or there is no course. */
  settled: boolean;
  /** Each write toasts its own failure and resolves null/false. */
  create: (set: Omit<NewFlashcardSet, "course_id">) => Promise<FlashcardSet | null>;
  update: (setId: string, patch: FlashcardSetPatch) => Promise<FlashcardSet | null>;
  remove: (setId: string) => Promise<boolean>;
}

type SetsSlot = { key: string; sets: FlashcardSet[] | null };

export function useFlashcardSets(userId: string, courseId: string): SetsState {
  const toast = useToast();
  const [slot, setSlot] = React.useState<SetsSlot | null>(null);
  const req = useLatestRequest();
  const key = `${userId}|${courseId}`;

  React.useEffect(() => {
    if (!userId || !courseId) return;
    const run = req.begin();
    listFlashcardSets(userId, courseId)
      .then(r => { if (run.isCurrent()) setSlot({ key, sets: r.sets || [] }); })
      .catch(err => {
        if (!run.isCurrent()) return;
        // Not worth a toast: the page works without its shelf.
        console.error("flashcard sets load failed", err);
        setSlot({ key, sets: null });
      });
    return req.cancel;
  }, [userId, courseId, key, req]);

  const live = slot?.key === key ? slot : null;

  /** Applies a write to the list for the course it was made on. */
  const patch = React.useCallback((change: (sets: FlashcardSet[]) => FlashcardSet[]) => {
    setSlot(prev => ({ key, sets: change(prev?.key === key ? prev.sets ?? [] : []) }));
  }, [key]);

  const create = React.useCallback(async (set: Omit<NewFlashcardSet, "course_id">) => {
    try {
      const r = await createFlashcardSet(userId, { ...set, course_id: courseId });
      patch(sets => [r.set, ...sets.filter(s => s.id !== r.set.id)]);
      return r.set;
    } catch (err) {
      console.error("flashcard set save failed", err);
      toast.error(humanizeError(err, "Couldn't save that set."));
      return null;
    }
  }, [userId, courseId, patch, toast]);

  const update = React.useCallback(async (setId: string, change: FlashcardSetPatch) => {
    try {
      const r = await updateFlashcardSet(userId, setId, change);
      patch(sets => sets.map(s => (s.id === setId ? r.set : s)));
      return r.set;
    } catch (err) {
      console.error("flashcard set update failed", err);
      toast.error(humanizeError(err, "Couldn't save that set."));
      return null;
    }
  }, [userId, patch, toast]);

  const remove = React.useCallback(async (setId: string) => {
    try {
      await deleteFlashcardSet(userId, setId);
      patch(sets => sets.filter(s => s.id !== setId));
      return true;
    } catch (err) {
      console.error("flashcard set delete failed", err);
      toast.error(humanizeError(err, "Couldn't delete that set."));
      return false;
    }
  }, [userId, patch, toast]);

  return { sets: live?.sets ?? null, settled: !courseId || live !== null, create, update, remove };
}

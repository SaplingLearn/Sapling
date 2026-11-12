"use client";
/**
 * The Study hub's reads, one hook per lifetime. Each drops a reply that lands
 * after its inputs changed, so a course or term switch never shows the
 * previous one's answer.
 *
 *   concepts/edges ..... getGraph(userId, semester)          useConceptGraph
 *   flashcards ......... getFlashcards(userId, -, semester)  useConceptGraph
 *   exams/deadlines .... getAllAssignments                   useStudyRecords
 *   quiz history ....... listAttempts                        useStudyRecords
 *   study guides ....... getCachedStudyGuides                useStudyRecords
 *   daily minutes/goal . getStudyDaily / setStudyDailyGoal   useStudyRecords
 *   course outline ..... getTopicChecklist (+ refresh)       useCourseOutline
 */
import React from "react";
import {
  getAllAssignments,
  getCachedStudyGuides,
  getFlashcards,
  getGraph,
  type Assignment,
  type StudyGuideCacheEntry,
} from "@/lib/api";
import { humanizeError } from "@/lib/errorMessage";
import { listAttempts } from "@/lib/quiz/api";
import type { AttemptSummary } from "@/lib/quiz/types";
import { getStudyDaily, setStudyDailyGoal, type StudyDaily } from "@/lib/studyApi";
import { getTopicChecklist, refreshTopicChecklist, type ChecklistTopic } from "@/lib/topicChecklistApi";
import { useLatestRequest } from "@/lib/useLatestRequest";
import { useToast } from "../ToastProvider";
import { GOAL_MAX, GOAL_MIN } from "./dailyGoalModel";
import type { FlashcardRow } from "./hubModel";

// eslint-disable-next-line @typescript-eslint/no-explicit-any -- getGraph is untyped (any[])
export type StudyGraph = { nodes: any[]; edges: any[] };

/**
 * The term's knowledge graph and flashcards. `graph` is null until the first
 * answer; a failed read answers with an empty graph (and says so), so the hub
 * shows its "no concepts" state rather than a skeleton that never resolves.
 */
export function useConceptGraph(
  userId: string,
  semester: string,
  semesterReady: boolean,
): { graph: StudyGraph | null; cards: FlashcardRow[] } {
  const toast = useToast();
  const [graph, setGraph] = React.useState<StudyGraph | null>(null);
  const [cards, setCards] = React.useState<FlashcardRow[]>([]);

  React.useEffect(() => {
    if (!userId || !semesterReady) return;
    let live = true;
    getGraph(userId, semester || undefined)
      .then(r => { if (live) setGraph({ nodes: r.nodes || [], edges: r.edges || [] }); })
      .catch(err => {
        if (!live) return;
        console.error("study graph load failed", err);
        setGraph({ nodes: [], edges: [] });
        toast.error(humanizeError(err, "Couldn't load your concepts."));
      });
    getFlashcards(userId, undefined, semester || undefined)
      .then(r => { if (live) setCards(r.flashcards || []); })
      .catch(err => console.error("study flashcards load failed", err));
    return () => { live = false; };
  }, [userId, semester, semesterReady, toast]);

  return { graph, cards };
}

export interface StudyRecords {
  assignments: Assignment[];
  /** Re-reads the dated work (after the Exams and Deadlines editor writes). */
  reloadAssignments: () => Promise<void>;
  attempts: AttemptSummary[];
  guides: StudyGuideCacheEntry[];
  /** null until it loads (or when it failed). */
  daily: StudyDaily | null;
  /** Persist a new daily goal; resolves true when it saved. */
  saveGoal: (minutes: number) => Promise<boolean>;
}

/** What the student has on record across terms: dated work, quiz attempts,
 *  study guides and daily minutes. None of it is semester-scoped. */
export function useStudyRecords(userId: string): StudyRecords {
  const toast = useToast();
  const [assignments, setAssignments] = React.useState<Assignment[]>([]);
  const [attempts, setAttempts] = React.useState<AttemptSummary[]>([]);
  const [guides, setGuides] = React.useState<StudyGuideCacheEntry[]>([]);
  const [daily, setDaily] = React.useState<StudyDaily | null>(null);

  // Latest read wins: the first load can still be in flight when a save
  // re-reads the list, and must not land on top of the newer answer.
  const assignmentReads = useLatestRequest();
  const reloadAssignments = React.useCallback(async () => {
    if (!userId) return;
    const read = assignmentReads.begin();
    try {
      const r = await getAllAssignments(userId);
      if (read.isCurrent()) setAssignments(r.assignments || []);
    } catch (err) {
      console.error("study assignments load failed", err);
    }
  }, [userId, assignmentReads]);

  React.useEffect(() => {
    if (!userId) return;
    let live = true;
    reloadAssignments();
    listAttempts(userId, { limit: 100 })
      .then(r => { if (live) setAttempts(r.attempts || []); })
      .catch(err => console.error("study quiz history load failed", err));
    getCachedStudyGuides(userId)
      .then(r => { if (live) setGuides(r.guides || []); })
      .catch(err => console.error("study guides load failed", err));
    getStudyDaily(userId)
      .then(r => { if (live) setDaily(r); })
      .catch(err => console.error("study daily load failed", err));
    return () => { live = false; };
  }, [userId, reloadAssignments]);

  const saveGoal = React.useCallback(async (minutes: number): Promise<boolean> => {
    const valid = Number.isFinite(minutes) && minutes >= GOAL_MIN && minutes <= GOAL_MAX;
    if (!userId || !valid) {
      toast.warn(`Pick a goal between ${GOAL_MIN} and ${GOAL_MAX} minutes.`);
      return false;
    }
    try {
      const r = await setStudyDailyGoal(userId, minutes);
      // With no daily read to merge into (it failed), the saved goal still has
      // to show: an empty week under the goal that was just set.
      setDaily(d => ({ ...(d ?? { today: "", days: [] }), goal_minutes: r.goal_minutes }));
      return true;
    } catch (err) {
      console.error("daily goal save failed", err);
      toast.error(humanizeError(err, "Couldn't save your daily goal."));
      return false;
    }
  }, [userId, toast]);

  return { assignments, reloadAssignments, attempts, guides, daily, saveGoal };
}

/**
 * The selected course's topic checklist, which names the roadmap columns and
 * says which concepts each exam covers. `[]` means "asked, nothing usable":
 * the roadmap falls back to layers and readiness to the whole course.
 *
 * The outline is per course, so it reloads with the course dropdown. A course
 * with no enrollment or no generated checklist answers with nothing to place,
 * which is not an error the student needs to see.
 *
 * The hub is also what GENERATES the outline: when the read says the course
 * has material the saved outline does not reflect (`needs_refresh`), it asks
 * for a refresh and swaps the result in when it lands. What the read returned
 * shows meanwhile and stays if the refresh fails (it is rate-limited and calls
 * a model), silently. One attempt per course and semester: `refreshes` keeps
 * each, so coming back to a course whose refresh is still running picks up
 * that one instead of starting another. An attempt that has already FINISHED
 * is never applied over a later read, which is at least as new as it.
 *
 * `reload(courseId)` is for when the course's evidence changed under the page
 * (an exam added or removed): it forgets that course's attempt, so the outline
 * may be generated again, and re-reads the selected course. What is on screen
 * stays until the new answer lands.
 */
type OutlineRefresh = { settled: boolean; topics: Promise<ChecklistTopic[] | null> };

export function useCourseOutline(
  userId: string,
  cid: string,
  semester: string,
  semesterReady: boolean,
): { outline: ChecklistTopic[]; reload: (courseId: string) => void } {
  const [outline, setOutline] = React.useState<ChecklistTopic[]>([]);
  const [reads, setReads] = React.useState(0);
  const refreshes = React.useRef(new Map<string, OutlineRefresh>());
  /** The course and term whose outline is on screen ("" for none). */
  const shownFor = React.useRef("");

  React.useEffect(() => {
    if (!userId || !cid || !semesterReady) { shownFor.current = ""; setOutline([]); return; }
    // Latest request wins: a course or semester change, or a reload, drops
    // everything the previous read still has in flight, its refresh included.
    let live = true;
    const key = `${userId}|${cid}|${semester}`;
    if (shownFor.current !== key) setOutline([]);
    shownFor.current = key;
    const sem = semester || undefined;
    /** The course's one refresh attempt, if it can still add to this read:
     *  started now, or already under way. null once it has finished. */
    const pendingRefresh = (): Promise<ChecklistTopic[] | null> | null => {
      const started = refreshes.current.get(key);
      if (started) return started.settled ? null : started.topics;
      const attempt: OutlineRefresh = {
        settled: false,
        topics: refreshTopicChecklist(userId, cid, sem)
          .then(
            f => f.topics || [],
            err => { console.error("study checklist refresh failed", err); return null; },
          )
          .then(topics => { attempt.settled = true; return topics; }),
      };
      refreshes.current.set(key, attempt);
      return attempt.topics;
    };
    getTopicChecklist(userId, cid, sem)
      .then(r => {
        if (!live) return;
        setOutline(r.topics || []);
        if (!r.needs_refresh) return;
        pendingRefresh()?.then(topics => { if (live && topics) setOutline(topics); });
      })
      .catch(err => { if (live) console.error("study checklist load failed", err); });
    return () => { live = false; };
  }, [userId, cid, semester, semesterReady, reads]);

  const reload = React.useCallback((courseId: string) => {
    refreshes.current.delete(`${userId}|${courseId}|${semester}`);
    setReads(n => n + 1);
  }, [userId, semester]);

  return { outline, reload };
}

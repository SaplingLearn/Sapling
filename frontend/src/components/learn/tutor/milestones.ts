"use client";
// Milestones in the Tutor (Tutor redesign, behind `milestones`): a course's
// dated exams, quizzes and homework, each with the concepts it covers and how
// ready the student is. No new data: the same reads and rules as the Study
// hub's exam tabs (components/study/hubModel.ts, studyModel.ts):
//   - the dates are the calendar's assignments (getAllAssignments), typed by
//     `classifyAssessment`; undated ones have nowhere to go;
//   - an exam's concepts are the course's topic checklist's links (a topic
//     lists the exams it is on and the graph node it describes:
//     `conceptIdsForExam`);
//   - ready means Proficient on the skill ladder (or the map's mastered tier
//     where the graph carries no skill), each concept's level as the rest of
//     the Tutor reads it.
import { useCallback, useEffect, useState } from "react";
import { getAllAssignments, type Assignment, type LoopGoal } from "@/lib/api";
import type { GraphNode } from "@/lib/data";
import { LOOP_GOAL_MAX_TARGETS } from "@/lib/inputLimits";
import { carriesSkill, LEVEL_TIER, type SkillLevel } from "@/lib/levels";
import { getTopicChecklist } from "@/lib/topicChecklistApi";
import { useUser } from "@/context/UserContext";
import { assessmentsForCourse } from "../../study/hubModel";
import { conceptIdsForExam } from "../../study/studyModel";
import { meterTier } from "./TutorPages";

export type MilestoneType = "Exam" | "Quiz" | "Homework";
export type Milestone = { id: string; courseId: string; title: string; iso: string; days: number; type: MilestoneType };

const DAY_MS = 86_400_000;

/** Whole days from today to a `YYYY-MM-DD` date, local. */
export function daysUntil(iso: string, today: Date = new Date()): number {
  const [y, m, d] = iso.slice(0, 10).split("-").map(Number);
  const day = new Date(y, (m || 1) - 1, d || 1).getTime();
  const now = new Date(today.getFullYear(), today.getMonth(), today.getDate()).getTime();
  return Math.round((day - now) / DAY_MS);
}

/** "Today", "Tomorrow", "13 days": the sidebar's countdown. */
export function countdown(days: number): string {
  return days <= 0 ? "Today" : days === 1 ? "Tomorrow" : `${days} days`;
}

/** "Midterm 2 is today" / "Midterm 2 is tomorrow" / "Midterm 2 in 13 days". */
export function milestoneHeadline(m: Pick<Milestone, "title" | "days">): string {
  return m.days <= 0 ? `${m.title} is today` : m.days === 1 ? `${m.title} is tomorrow` : `${m.title} in ${m.days} days`;
}

/** Every course's dated work still ahead (today counts), soonest first. */
export function milestonesOf(assignments: Assignment[], today: Date = new Date()): Milestone[] {
  const courseIds = [...new Set(assignments.map((a) => a.course_id).filter((c): c is string => !!c))];
  return courseIds
    .flatMap((courseId) => assessmentsForCourse(assignments, courseId).map((a) => ({
      id: a.id, courseId, title: a.title, iso: a.iso, days: daysUntil(a.iso, today), type: a.type as MilestoneType,
    })))
    .filter((m) => m.days >= 0)
    .sort((a, b) => a.iso.localeCompare(b.iso) || a.title.localeCompare(b.title));
}

// One read for the whole Tutor (the sidebar, the course page, New session and
// the milestone page all ask): shared per student, kept a minute.
const KEEP_MS = 60_000;
let cache: { userId: string; at: number; data: Promise<Assignment[]> } | null = null;
function readAssignments(userId: string, fresh = false): Promise<Assignment[]> {
  if (!fresh && cache && cache.userId === userId && Date.now() - cache.at < KEEP_MS) return cache.data;
  const data = getAllAssignments(userId).then((r) => r.assignments ?? []);
  cache = { userId, at: Date.now(), data };
  data.catch(() => { if (cache?.data === data) cache = null; });
  return data;
}
/** Test seam. */
export function __resetMilestonesForTests() { cache = null; }

const listeners = new Set<() => void>();
/** The dates changed (course setup saved them): drop the shared read and
 *  have every mounted reader read again. */
export function invalidateMilestones() {
  cache = null;
  listeners.forEach((l) => l());
}

/** The student's upcoming milestones, every course; null while loading. */
export function useMilestones(enabled: boolean) {
  const { userId } = useUser();
  const [state, setState] = useState<{ items: Milestone[] | null; failed: boolean }>({ items: null, failed: false });
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    const again = () => setAttempt((n) => n + 1);
    listeners.add(again);
    return () => { listeners.delete(again); };
  }, []);
  useEffect(() => {
    if (!enabled || !userId) return;
    let live = true;
    readAssignments(userId, attempt > 0)
      .then((a) => { if (live) setState({ items: milestonesOf(a), failed: false }); })
      .catch(() => { if (live) setState({ items: null, failed: true }); });
    return () => { live = false; };
  }, [enabled, userId, attempt]);
  const retry = useCallback(() => { setState({ items: null, failed: false }); setAttempt((n) => n + 1); }, []);
  return { ...state, retry };
}

/** Which concepts each of a course's milestones covers (the topic checklist's
 *  links), keyed by milestone id; null while loading, empty when the course
 *  has no outline. */
export function useMilestoneConcepts(courseId: string | null, milestones: readonly Milestone[] | null, enabled: boolean) {
  const { userId } = useUser();
  const [outline, setOutline] = useState<{ courseId: string; topics: Parameters<typeof conceptIdsForExam>[0] } | null>(null);
  useEffect(() => {
    if (!enabled || !userId || !courseId) return;
    let live = true;
    getTopicChecklist(userId, courseId)
      .then((r) => { if (live) setOutline({ courseId, topics: r.topics ?? [] }); })
      .catch(() => { if (live) setOutline({ courseId, topics: [] }); });
    return () => { live = false; };
  }, [enabled, userId, courseId]);
  if (!outline || outline.courseId !== courseId || !milestones) return null;
  return new Map(milestones.filter((m) => m.courseId === courseId).map((m) => [m.id, [...conceptIdsForExam(outline.topics, m.id)]]));
}

export type ConceptState = { id: string; name: string; score: number | null; level: SkillLevel; ready: boolean };

const TIER_ORDER: SkillLevel[] = ["not_started", "novice", "develop", "profic"];

/** Each covered concept's level, as the rest of the Tutor reads it. */
export function coveredConcepts(ids: readonly string[], nodes: readonly GraphNode[]): ConceptState[] {
  const ladder = nodes.some(carriesSkill);
  const byId = new Map(nodes.map((n) => [n.id, n]));
  return ids.flatMap((id) => {
    const n = byId.get(id);
    if (!n) return [];
    const score = n.mastery_tier === "unexplored" ? null : n.mastery_score;
    const tier = meterTier(score, ladder);
    const level = TIER_ORDER.find((l) => LEVEL_TIER[l] === tier) ?? "not_started";
    return [{ id, name: n.name, score, level, ready: level === "profic" }];
  });
}

/** "3 of 8 concepts are exam-ready" and the count per level. */
export function readinessOf(concepts: readonly ConceptState[]) {
  const counts: Record<SkillLevel, number> = { not_started: 0, novice: 0, develop: 0, profic: 0 };
  for (const c of concepts) counts[c.level] += 1;
  return { ready: counts.profic, total: concepts.length, counts };
}

/** The session a milestone's "Prepare" starts: a goal on its concepts that are
 *  not ready yet, weakest first, within the goal's cap. Null when none is. */
export function prepareGoal(m: Pick<Milestone, "title">, concepts: readonly ConceptState[]): { topic: string; goal: LoopGoal } | null {
  const open = concepts.filter((c) => !c.ready).sort((a, b) => (a.score ?? -1) - (b.score ?? -1));
  if (open.length === 0) return null;
  const topic = `Prepare for ${m.title}`;
  return { topic, goal: { text: topic, target_node_ids: open.slice(0, LOOP_GOAL_MAX_TARGETS).map((c) => c.id) } };
}

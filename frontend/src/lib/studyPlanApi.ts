import { fetchJSON } from "./api";

export interface PlanTopic {
  id: string;
  name: string;
  description: string;
  parent_id: string | null;
  prerequisite_ids: string[];
  source_ids: string[];
  importance: number;
  study_points?: string[];
}

export interface StudySession {
  id: string;
  topic_id: string;
  kind: "study" | "review";
  scheduled_date: string;
  minutes: number;
  completed: boolean;
}

export interface PlanInput {
  title: string;
  assessment_type: "quiz" | "exam";
  assessment_date: string;
  start_date: string;
  timezone: string;
  coverage: string;
  document_ids: string[];
  assignment_ids: string[];
  study_days: number[];
  minutes_per_day?: number;
}

export interface StudyPlan extends PlanInput {
  minutes_per_day: number;
  automatic_time?: boolean;
  guide_overview?: string;
  id: string;
  version: number;
  topics: (PlanTopic & {
    checked: boolean;
    status: "not_started" | "needs_review" | "in_progress" | "mastered";
    mastery_score: number | null;
    node_id: string | null;
  })[];
  sessions: StudySession[];
  sources: { id: string; label: string }[];
  warnings: string[];
  mastered_count: number;
}

export interface PlanSources {
  documents: { id: string; file_name: string }[];
  assignments: { id: string; title: string; due_date: string | null; assignment_type: string }[];
}

export interface PlanChanges {
  settings?: PlanInput;
  title?: string;
  topics?: PlanTopic[];
  session?: { id: string; scheduled_date?: string; completed?: boolean };
  regenerate?: boolean;
}

function path(userId: string, courseId: string, suffix: string, semester?: string) {
  return `/api/topic-checklist/${encodeURIComponent(userId)}/courses/${encodeURIComponent(courseId)}/plans${suffix}${semester ? `?${new URLSearchParams({ semester })}` : ""}`;
}

export const getStudyPlans = (userId: string, courseId: string, semester?: string, signal?: AbortSignal) =>
  fetchJSON<{ semester: string; plans: StudyPlan[] }>(path(userId, courseId, "", semester), { signal });

export const getStudyPlanSources = (userId: string, courseId: string, semester?: string, signal?: AbortSignal) =>
  fetchJSON<PlanSources>(path(userId, courseId, "/sources", semester), { signal });

export const createStudyPlan = (userId: string, courseId: string, input: PlanInput, semester?: string, signal?: AbortSignal) =>
  fetchJSON<StudyPlan>(path(userId, courseId, "", semester), { method: "POST", body: JSON.stringify(input), signal });

export const updateStudyPlan = (userId: string, courseId: string, plan: StudyPlan, changes: PlanChanges, semester?: string, signal?: AbortSignal) =>
  fetchJSON<StudyPlan>(path(userId, courseId, `/${encodeURIComponent(plan.id)}`, semester), {
    method: "PATCH", body: JSON.stringify({ version: plan.version, ...changes }), signal,
  });

export const deleteStudyPlan = (userId: string, courseId: string, id: string, semester?: string, signal?: AbortSignal) =>
  fetchJSON<{ deleted: boolean }>(path(userId, courseId, `/${encodeURIComponent(id)}`, semester), { method: "DELETE", signal });

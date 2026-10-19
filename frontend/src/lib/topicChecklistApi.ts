import { fetchJSON } from "./api";

export interface ChecklistAssessment {
  id: string;
  title: string;
  due_date: string;
  assignment_type: "quiz" | "exam";
}

export interface ChecklistTopic {
  id: string;
  name: string;
  description: string;
  importance: number;
  parent_id: string | null;
  prerequisite_ids: string[];
  prerequisite_gaps: string[];
  status: "not_started" | "needs_review" | "in_progress" | "mastered";
  checked: boolean;
  mastery_score: number | null;
  last_studied_at: string | null;
  review_reasons: string[];
  priority: "high" | "normal";
  assessments: ChecklistAssessment[];
  sources: { id: string; label: string }[];
  node_id: string | null;
}

export interface TopicChecklist {
  course_id: string;
  semester: string;
  generated_at: string | null;
  needs_refresh: boolean;
  topics: ChecklistTopic[];
  assessments: ChecklistAssessment[];
  warnings: string[];
  review_after_days: number;
}

function path(userId: string, courseId: string, suffix: string, semester?: string): string {
  const query = semester ? `?${new URLSearchParams({ semester })}` : "";
  return `/api/topic-checklist/${encodeURIComponent(userId)}/courses/${encodeURIComponent(courseId)}${suffix}${query}`;
}

export function getTopicChecklist(userId: string, courseId: string, semester?: string, signal?: AbortSignal) {
  return fetchJSON<TopicChecklist>(path(userId, courseId, "", semester), { signal });
}

export function refreshTopicChecklist(userId: string, courseId: string, semester?: string, signal?: AbortSignal) {
  return fetchJSON<TopicChecklist>(path(userId, courseId, "/refresh", semester), { method: "POST", signal });
}

/** A checkmark changes progress, never evidence: the server re-derives topic
 *  state without re-reading sources, so freshness (`needs_refresh`/`warnings`)
 *  is not part of this response — keep the values from the last read. */
export type TopicChecklistProgress = Omit<TopicChecklist, "needs_refresh" | "warnings">;

export function setTopicReviewed(userId: string, courseId: string, topicId: string, checked: boolean, semester?: string, signal?: AbortSignal) {
  return fetchJSON<TopicChecklistProgress>(path(userId, courseId, `/topics/${encodeURIComponent(topicId)}`, semester), {
    method: "PATCH", body: JSON.stringify({ checked }), signal,
  });
}

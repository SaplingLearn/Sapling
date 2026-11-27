/**
 * Study hub client (routes/study.py): estimated daily study minutes, the
 * student's daily goal, and (W8.3) learner-next buckets for Focus / Quick
 * Reviews. Kept out of lib/api.ts so the hub owns its wire types.
 */
import { fetchJSON } from "@/lib/api";
import type { PlannedConcept } from "@/lib/quiz/types";

export interface StudyDay {
  /** Local calendar day, YYYY-MM-DD. */
  date: string;
  /** Estimated minutes (quiz + flashcards + tutor). */
  minutes: number;
  quiz: number;
  flashcards: number;
  tutor: number;
  /** Raw counts behind the estimate. */
  quizzes: number;
  cards: number;
  sessions: number;
}

export interface StudyDaily {
  goal_minutes: number;
  /** The student's local today, YYYY-MM-DD (last entry of `days`). */
  today: string;
  /** Seven days, oldest first, ending today. */
  days: StudyDay[];
}

/** W8.3 / W8.6: uncapped learner-next buckets (`GET /api/study/{id}/next`).
 *  Same concept wire shape as `GET /api/quiz/plan`. */
export interface StudyNext {
  due: PlannedConcept[];
  misconceptions: PlannedConcept[];
  ready: PlannedConcept[];
}

export const getStudyDaily = (userId: string, tzOffsetMin = new Date().getTimezoneOffset()) =>
  fetchJSON<StudyDaily>(
    `/api/study/${encodeURIComponent(userId)}/daily?tz_offset_min=${tzOffsetMin}`,
  );

export const setStudyDailyGoal = (userId: string, minutes: number) =>
  fetchJSON<{ goal_minutes: number }>(`/api/study/${encodeURIComponent(userId)}/daily-goal`, {
    method: "PATCH",
    body: JSON.stringify({ minutes }),
  });

/** Learner-next for Hub Focus / Quick Reviews. 404 while learning_loop or
 *  quiz_concept_plan is off — callers only ask when both flags are on. */
export const getStudyNext = (userId: string, courseId?: string): Promise<StudyNext> => {
  const params = new URLSearchParams();
  if (courseId) params.set("course_id", courseId);
  const q = params.toString();
  return fetchJSON<StudyNext>(
    `/api/study/${encodeURIComponent(userId)}/next${q ? `?${q}` : ""}`,
  );
};

/**
 * Study hub client (routes/study.py): estimated daily study minutes and the
 * student's daily goal. Kept out of lib/api.ts so the hub owns its wire types.
 */
import { fetchJSON } from "@/lib/api";

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

export const getStudyDaily = (userId: string, tzOffsetMin = new Date().getTimezoneOffset()) =>
  fetchJSON<StudyDaily>(
    `/api/study/${encodeURIComponent(userId)}/daily?tz_offset_min=${tzOffsetMin}`,
  );

export const setStudyDailyGoal = (userId: string, minutes: number) =>
  fetchJSON<{ goal_minutes: number }>(`/api/study/${encodeURIComponent(userId)}/daily-goal`, {
    method: "PATCH",
    body: JSON.stringify({ minutes }),
  });

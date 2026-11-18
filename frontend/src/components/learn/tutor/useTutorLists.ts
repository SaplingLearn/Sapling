"use client";
import { useEffect, useState } from "react";
import { getDocuments, getReviewSummary, getSessions, type Session } from "@/lib/api";

export type TutorMaterial = { id: string; file_name: string; category?: string | null; course_id?: string | null };

/**
 * What the Tutor shell lists beside the session (wireframes T1–T3, T17): the
 * student's sessions in every course (the sidebar's recents, a course page,
 * all sessions), a course page's material, and how many reviews are due.
 *
 * A read that fails says so (`recentFailed`, `materialsFailed`, each with a
 * retry) instead of reading as "No sessions yet" or "No material yet". The due
 * count is the review queue's own (GET /review/summary, every course — the
 * queue Study's "Due today" serves), not the courses with a retention check
 * due, and it does not wait on the retention badge's flag; null while unread,
 * on a failure, or while `hide_study` hides Study (there is nowhere to send
 * the student, so nothing is read).
 */
export function useTutorLists({ userId, sessionId, sessionClosed, wantMaterials, studyVisible }: {
  userId: string | null | undefined;
  /** The session on screen: a start, a resume and a close each change the recents. */
  sessionId: string | null;
  sessionClosed: boolean;
  /** A course page is open: its material is read once, then kept. */
  wantMaterials: boolean;
  studyVisible: boolean;
}) {
  const [recent, setRecent] = useState<Session[] | null>(null);
  const [recentFailed, setRecentFailed] = useState(false);
  const [recentTry, setRecentTry] = useState(0);
  useEffect(() => {
    if (!userId) return;
    let cancelled = false;
    getSessions(userId, 50)
      .then((r) => {
        if (cancelled) return;
        setRecent(r.sessions ?? []);
        setRecentFailed(false);
      })
      .catch(() => { if (!cancelled) setRecentFailed(true); });
    return () => { cancelled = true; };
  }, [userId, sessionId, sessionClosed, recentTry]);

  const [materials, setMaterials] = useState<TutorMaterial[] | null>(null);
  const [materialsFailed, setMaterialsFailed] = useState(false);
  useEffect(() => {
    if (!wantMaterials || materials !== null || materialsFailed || !userId) return;
    let cancelled = false;
    getDocuments(userId)
      .then((r) => { if (!cancelled) setMaterials(r.documents ?? []); })
      .catch(() => { if (!cancelled) setMaterialsFailed(true); });
    return () => { cancelled = true; };
  }, [wantMaterials, materials, materialsFailed, userId]);

  const [dueReviews, setDueReviews] = useState<number | null>(null);
  useEffect(() => {
    if (!userId || !studyVisible) return;
    let cancelled = false;
    getReviewSummary(userId)
      .then((r) => { if (!cancelled) setDueReviews((r.due?.flashcard ?? 0) + (r.due?.check ?? 0)); })
      .catch(() => { if (!cancelled) setDueReviews(null); });
    return () => { cancelled = true; };
  }, [userId, studyVisible, sessionClosed]);

  return {
    recent,
    /** Present while the last sessions read failed: try it again. */
    retryRecent: recentFailed ? () => setRecentTry((t) => t + 1) : null,
    materials,
    /** Present while the material read failed: try it again. */
    retryMaterials: materialsFailed ? () => setMaterialsFailed(false) : null,
    dueReviews: studyVisible ? dueReviews : null,
  };
}

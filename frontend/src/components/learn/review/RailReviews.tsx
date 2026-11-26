"use client";
// Study's rail entries for the learning loop's Review queue and the retention
// check (`review_v2`): two compact rows under Quick Reviews, in its style, each
// opening its own component in the hub's modal (StudyModal), so the hub keeps
// its layout. Off, both sit under the hub's header as before (Study.tsx's
// LoopReviews). The Review row's count is the Tutor's (due cards and checks,
// new cards aside), so both places say the same number; the retention row says
// "Ready" when a check is due and still opens when none is (it says so).
import React, { useCallback, useEffect, useState } from "react";
import { getReviewSummary, type EnrolledCourse } from "@/lib/api";
import { useRetentionDue } from "@/context/RetentionDueContext";
import { useUser } from "@/context/UserContext";
import { LEARNING_COPY } from "@/lib/learningCopy";
import { Icon } from "../../Icon";
import { CardsIcon } from "../../study/hubUi";
import { StudyModal } from "../../study/StudyModal";
import q from "../../study/QuickReviews.module.css";
import { RetentionCheck } from "../RetentionCheck";
import { useLoopStatus } from "../useLoopStatus";
import { ReviewSlot } from "./ReviewSlot";
import styles from "./RailReviews.module.css";

export const RAIL_COPY = {
  retention: "Retention check",
  ready: "Ready",
  failed: "Couldn't load due reviews.",
  retry: "Retry due reviews",
} as const;

/** The Review row's count, as the Tutor's sidebar counts it; null unknown. */
function useDueCount(userId: string, enabled: boolean) {
  const [count, setCount] = useState<number | null>(null);
  const [tick, setTick] = useState(0);
  useEffect(() => {
    if (!enabled || !userId) return;
    let live = true;
    getReviewSummary(userId)
      .then((r) => { if (live) setCount(Math.max(0, (r.due?.flashcard ?? 0) + (r.due?.check ?? 0) - (r.new ?? 0))); })
      .catch(() => { if (live) setCount(null); });
    return () => { live = false; };
  }, [userId, enabled, tick]);
  return { count, refresh: useCallback(() => setTick((t) => t + 1), []) };
}

export function RailReviews({ courses, retentionCourse }: {
  courses: EnrolledCourse[];
  /** `?retention-course=` (the Study deep link): opens the check on that course. */
  retentionCourse: string;
}) {
  const { userId, userReady } = useUser();
  const { status, retry } = useLoopStatus(userId, userReady);
  const active = status === true;
  const { count, refresh } = useDueCount(userId, active);
  const { courseIds: dueCourses, refresh: refreshRetention } = useRetentionDue();
  // The deep link opens the retention check at once, as it opened the old card.
  const [open, setOpen] = useState<"review" | "retention" | null>(retentionCourse ? "retention" : null);
  const close = () => {
    setOpen(null);
    refresh(); // what was answered leaves the count
    refreshRetention();
  };

  if (status === "error") {
    return (
      <div role="status" className={styles.failed}>
        <span>{RAIL_COPY.failed}</span>
        <button type="button" className="btn btn--sm" onClick={retry} data-testid="review-status-retry">{RAIL_COPY.retry}</button>
      </div>
    );
  }
  if (!active) return null;
  const retentionReady = dueCourses.length > 0;
  return (
    <div className={styles.rows} data-testid="study-reviews">
      <button type="button" className={q.row} onClick={() => setOpen("review")} aria-haspopup="dialog" data-testid="study-rail-review">
        <span aria-hidden="true" className={q.glyph}><CardsIcon size={21} /></span>
        <span className={q.title}>{LEARNING_COPY.review}</span>
        {(count ?? 0) > 0 && (
          <span className={`chip ${q.estimate}`} data-testid="study-rail-review-count">
            {count} due<Icon name="chev" size={12} />
          </span>
        )}
      </button>
      <button type="button" className={`${q.row} ${styles.quiet}`} onClick={() => setOpen("retention")} aria-haspopup="dialog" data-testid="study-rail-retention">
        <span aria-hidden="true" className={`${q.glyph} ${styles.quietGlyph}`}><Icon name="cal" size={18} /></span>
        <span className={`${q.title} ${styles.quietTitle}`}>{RAIL_COPY.retention}</span>
        {retentionReady && (
          <span className={`chip ${q.estimate} ${styles.readyChip}`} data-testid="study-rail-retention-ready">
            {RAIL_COPY.ready}<Icon name="chev" size={12} />
          </span>
        )}
      </button>
      <StudyModal open={open === "review"} onClose={close} label={LEARNING_COPY.review} width={640} maxHeight={760} top={72} gap={0}>
        <div className={styles.sheet}><ReviewSlot userId={userId} courses={courses} /></div>
      </StudyModal>
      <StudyModal open={open === "retention"} onClose={close} label={RAIL_COPY.retention} width={640} maxHeight={760} top={72} gap={0}>
        <div className={styles.sheet}>
          <RetentionCheck key={userId} userId={userId} courses={courses} initialCourseId={retentionCourse || dueCourses[0] || ""} />
        </div>
      </StudyModal>
    </div>
  );
}

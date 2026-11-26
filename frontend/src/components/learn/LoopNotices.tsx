"use client";
// The session's notices region (moved out of LoopLearn.tsx unchanged): the
// budget pause, the course's item state (A26/A128), the materials outage
// (A128), the goal's exhausted practice, and the ?topic= offer (F3).
import React from "react";
import Link from "next/link";
import { AnimatePresence, motion } from "framer-motion";
import { useMotionPresets } from "@/lib/motion";
import type { LoopBudgetPause } from "@/lib/api";
import { handoffStudyHref, practiceUnavailableHandoffCtas } from "@/lib/learningHandoffs";
import { LEARNING_COPY } from "@/lib/learningCopy";
import { BudgetPausedBanner, tutorPauseMessage } from "./BudgetPausedBanner";
import { PREPARING_COPY } from "./checkNote";
import styles from "./LoopNotices.module.css";

const NO_CHECK_ITEMS_COPY =
  "No practice questions for this course yet. You can still learn with the tutor; nothing is graded until the course has some.";
// spec §13 A128: the session's course-material retrieval failed (an outage, not
// an empty result). Shown once per session, from the turn's response field —
// never a prompt change.
const MATERIALS_UNAVAILABLE_COPY =
  "Your course materials are temporarily unavailable, so answers may be less specific to your class.";
const NO_FRESH_PRACTICE_COPY = "Fresh practice questions are unavailable for these concepts in this session. You can review source material with the tutor; source review does not assess or complete your goal. Starting another session will not replenish these questions.";

export function LoopNotices({
  paused, studyVisible, quizVisible, courseId, noCheckItems, preparing, materialsNote, practiceUnavailable, names, exhaustedPracticeAttempt,
  libraryVisible, canRefreshPractice, refreshDisabled, onRefreshPractice, topicOffer, topicStartDisabled, onTopicStart,
}: {
  paused: LoopBudgetPause | null;
  studyVisible: boolean;
  /** False while `hide_quiz` hides Quiz. */
  quizVisible: boolean;
  courseId: string | null;
  noCheckItems: "none" | "preparing" | null;
  /** The A128 "preparing" note, unless a crisis-support card is on screen. */
  preparing: boolean;
  /** The A128 materials note, unless a crisis-support card is on screen. */
  materialsNote: boolean;
  practiceUnavailable: string[];
  names: Map<string, string>;
  exhaustedPracticeAttempt: boolean;
  libraryVisible: boolean;
  /** "Check for fresh practice" is offered (a plan, or teaching between checks). */
  canRefreshPractice: boolean;
  refreshDisabled: boolean;
  onRefreshPractice: () => void;
  topicOffer: string | null;
  topicStartDisabled: boolean;
  onTopicStart: () => void;
}) {
  const hasNotices = !!paused || noCheckItems === "none" || preparing || materialsNote || !!topicOffer || practiceUnavailable.length > 0;
  const practiceHandoffs = practiceUnavailableHandoffCtas({
    courseId,
    conceptIds: practiceUnavailable,
    visibility: { study: studyVisible, quiz: quizVisible },
  });
  // Each notice opens and closes in place (collapse); one already up on the
  // first render is simply there. The bare wrapper carries the height tween,
  // so a padded notice collapses to nothing rather than to its padding.
  const m = useMotionPresets();
  const handoff = `btn btn--sm ${styles.handoff} ${styles.press}`;
  // Always in the DOM (spec §13 A135): a notice is announced when it is added to
  // this polite region; one inserted together with its own region is not
  // reliably read out.
  return (
    <div
      aria-live="polite"
      data-testid="loop-notices"
      data-has-notices={hasNotices}
      className={styles.region}
    >
      <AnimatePresence initial={false}>
      {paused && (
        <motion.div key="paused" {...m.collapse}>
        <BudgetPausedBanner
          testId="loop-budget-paused"
          resetAt={paused.resetAt}
          sessionCapped={paused.sessionCapped}
          message={tutorPauseMessage(paused.resetAt, paused.sessionCapped, paused.pauseNovice, paused.aiLimit)}
        >
          {studyVisible && <>{" "}<Link data-testid="loop-budget-study-link" href={handoffStudyHref(courseId)} className={styles.studyLink}>
            {LEARNING_COPY.review}
          </Link></>}
        </BudgetPausedBanner>
        </motion.div>
      )}
      {noCheckItems === "none" && (
        <motion.div key="no-check-items" {...m.collapse}>
          <div data-testid="loop-no-check-items" role="status" className={styles.note}>
            {NO_CHECK_ITEMS_COPY}
          </div>
        </motion.div>
      )}
      {preparing && (
        <motion.div key="preparing" {...m.collapse}>
          <div data-testid="loop-preparing-items" role="status" className={styles.note}>
            {PREPARING_COPY}
          </div>
        </motion.div>
      )}
      {materialsNote && (
        <motion.div key="materials" {...m.collapse}>
          <div data-testid="loop-materials-unavailable" role="status" className={styles.note}>
            {MATERIALS_UNAVAILABLE_COPY}
          </div>
        </motion.div>
      )}
      {practiceUnavailable.length > 0 && (
        <motion.div key="practice" {...m.collapse}>
        <div data-testid="loop-practice-unavailable" role="status" className={`${styles.note} ${styles.practice}`}>
          <p className={styles.para}>{NO_FRESH_PRACTICE_COPY}</p>
          <p className={`${styles.paraLast} ${styles.anywhere}`}>Practice unavailable: {practiceUnavailable.map((id) => names.get(id) ?? "A selected concept").join(", ")}.</p>
          {exhaustedPracticeAttempt && <p className={styles.paraLast}>This session already moved past those concepts. Once new questions are available, start a new session to practice them.</p>}
          <div className={styles.actions}>
            {libraryVisible && <Link data-testid="loop-practice-sources" href="/library" className={`${handoff} btn--ghost ${styles.centered}`}>Review source material</Link>}
            {practiceHandoffs.map((link) => (
              <Link
                key={link.testId}
                data-testid={link.testId}
                href={link.href}
                className={`${handoff} ${styles.centered}`}
              >
                {link.label}
              </Link>
            ))}
            {!exhaustedPracticeAttempt && canRefreshPractice && (
              <button data-testid="loop-practice-refresh" type="button" className={handoff}
                disabled={refreshDisabled}
                onClick={onRefreshPractice}>Check for fresh practice</button>
            )}
          </div>
        </div>
        </motion.div>
      )}
      {topicOffer && (
        // ?topic= while a session is open: resume won (a reload never starts a
        // probe, §11.3); the link's concept is one click away, never automatic.
        <motion.div key="topic-offer" {...m.collapse}>
        <div data-testid="loop-topic-offer" role="status" className={styles.topicOffer}>
          <span className={styles.topicCopy}>You picked “{topicOffer}”. This session is still open.</span>
          <button
            data-testid="loop-topic-start"
            className={`btn btn--sm ${styles.press}`}
            disabled={topicStartDisabled}
            onClick={onTopicStart}
          >
            Start a session on {topicOffer}
          </button>
        </div>
        </motion.div>
      )}
      </AnimatePresence>
    </div>
  );
}

"use client";
// The session's notices region: the budget pause, the ?topic= offer (F3), the
// goal's exhausted practice, the course's item state (A26/A128) and the
// materials outage (A128), one at a time in that order (a StatusSlot).
import { CtaLink, HandoffLink } from "@/components/ui/HandoffLink";
import { StatusSlot, type StatusNotice } from "@/components/ui/StatusSlot";
import React from "react";
import Link from "next/link";
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
  const practiceHandoffs = practiceUnavailableHandoffCtas({
    courseId,
    conceptIds: practiceUnavailable,
    visibility: { study: studyVisible, quiz: quizVisible },
  });
  const handoff = `btn btn--sm ${styles.handoff} ${styles.press}`;
  // One notice at a time, most important first (components/ui/StatusSlot):
  // the pause stops the tutor; the ?topic= offer waits on the student's
  // choice; then what the session's practice lacks; then the outage note.
  const notices: StatusNotice[] = [
    {
      key: "paused",
      on: !!paused,
      render: () => paused && (
        <BudgetPausedBanner
          testId="loop-budget-paused"
          resetAt={paused.resetAt}
          sessionCapped={paused.sessionCapped}
          message={tutorPauseMessage(paused.resetAt, paused.sessionCapped, paused.pauseNovice, paused.aiLimit)}
        >
          {studyVisible && <>{" "}<HandoffLink variant="plain" testId="loop-budget-study-link" href={handoffStudyHref(courseId)} className={styles.studyLink}>
            {LEARNING_COPY.review}
          </HandoffLink></>}
        </BudgetPausedBanner>
      ),
    },
    {
      // ?topic= while a session is open: resume won (a reload never starts a
      // probe, §11.3); the link's concept is one click away, never automatic,
      // and the action says what it does to the open session.
      key: "topic-offer",
      on: !!topicOffer,
      render: () => (
        <div data-testid="loop-topic-offer" role="status" className={styles.topicOffer}>
          <span className={styles.topicCopy}>You picked “{topicOffer}”. Learning it wraps up this session first.</span>
          <button
            data-testid="loop-topic-start"
            className={`btn btn--sm ${styles.press}`}
            disabled={topicStartDisabled}
            onClick={onTopicStart}
          >
            {LEARNING_COPY.learnConcept(topicOffer ?? "")}
          </button>
        </div>
      ),
    },
    {
      key: "practice",
      on: practiceUnavailable.length > 0,
      render: () => (
        <div data-testid="loop-practice-unavailable" role="status" className={`${styles.note} ${styles.practice}`}>
          <p className={styles.para}>{NO_FRESH_PRACTICE_COPY}</p>
          <p className={`${styles.paraLast} ${styles.anywhere}`}>Practice unavailable: {practiceUnavailable.map((id) => names.get(id) ?? "A selected concept").join(", ")}.</p>
          {exhaustedPracticeAttempt && <p className={styles.paraLast}>This session already moved past those concepts. Once new questions are available, start a new session to practice them.</p>}
          <div className={styles.actions}>
            {libraryVisible && <Link data-testid="loop-practice-sources" href="/library" className={`${handoff} btn--ghost ${styles.centered}`}>Review source material</Link>}
            {practiceHandoffs.map((link) => (
              <CtaLink key={link.testId} cta={link} variant="plain" className={`${handoff} ${styles.centered}`} />
            ))}
            {!exhaustedPracticeAttempt && canRefreshPractice && (
              <button data-testid="loop-practice-refresh" type="button" className={handoff}
                disabled={refreshDisabled}
                onClick={onRefreshPractice}>Check for fresh practice</button>
            )}
          </div>
        </div>
      ),
    },
    {
      key: "no-check-items",
      on: noCheckItems === "none",
      render: () => <div data-testid="loop-no-check-items" role="status" className={styles.note}>{NO_CHECK_ITEMS_COPY}</div>,
    },
    {
      key: "preparing",
      on: preparing,
      render: () => <div data-testid="loop-preparing-items" role="status" className={styles.note}>{PREPARING_COPY}</div>,
    },
    {
      key: "materials",
      on: materialsNote,
      render: () => <div data-testid="loop-materials-unavailable" role="status" className={styles.note}>{MATERIALS_UNAVAILABLE_COPY}</div>,
    },
  ];
  return <StatusSlot notices={notices} testId="loop-notices" className={styles.region} />;
}

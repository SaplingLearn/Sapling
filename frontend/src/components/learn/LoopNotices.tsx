"use client";
// The session's notices region (moved out of LoopLearn.tsx unchanged): the
// budget pause, the course's item state (A26/A128), the materials outage
// (A128), the goal's exhausted practice, and the ?topic= offer (F3).
import React from "react";
import Link from "next/link";
import type { LoopBudgetPause } from "@/lib/api";
import { BudgetPausedBanner, tutorPauseMessage } from "./BudgetPausedBanner";
import { PREPARING_COPY } from "./checkNote";

const NO_CHECK_ITEMS_COPY =
  "No check items for this course yet. You can still learn with the tutor; nothing is graded until the course has items.";
// spec §13 A128: the session's course-material retrieval failed (an outage, not
// an empty result). Shown once per session, from the turn's response field —
// never a prompt change.
const MATERIALS_UNAVAILABLE_COPY =
  "Your course materials are temporarily unavailable, so answers may be less specific to your class.";
const NO_FRESH_PRACTICE_COPY = "Fresh practice questions are unavailable for these concepts in this session. You can review source material with the tutor; source review does not assess or complete your goal. Starting another session will not replenish these questions.";

const NOTE_STYLE: React.CSSProperties = { padding: "10px 14px", borderRadius: "var(--r-md)", background: "var(--info-soft)", fontSize: 13 };

export function LoopNotices({
  paused, studyVisible, noCheckItems, preparing, materialsNote, practiceUnavailable, names, exhaustedPracticeAttempt,
  libraryVisible, canRefreshPractice, refreshDisabled, onRefreshPractice, topicOffer, topicStartDisabled, onTopicStart,
}: {
  paused: LoopBudgetPause | null;
  studyVisible: boolean;
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
  // Always in the DOM (spec §13 A135): a notice is announced when it is added to
  // this polite region; one inserted together with its own region is not
  // reliably read out.
  return (
    <div
      aria-live="polite"
      data-testid="loop-notices"
      style={hasNotices ? { display: "flex", flexDirection: "column", gap: 8, padding: "12px 32px 0" } : undefined}
    >
      {paused && (
        <BudgetPausedBanner
          testId="loop-budget-paused"
          resetAt={paused.resetAt}
          sessionCapped={paused.sessionCapped}
          message={tutorPauseMessage(paused.resetAt, paused.sessionCapped, paused.aiLimit)}
        >
          {studyVisible && <>{" "}<Link data-testid="loop-budget-study-link" href="/study" style={{ color: "var(--accent)", fontWeight: 500 }}>
            Review flashcards
          </Link></>}
        </BudgetPausedBanner>
      )}
      {noCheckItems === "none" && (
        <div data-testid="loop-no-check-items" role="status" style={NOTE_STYLE}>
          {NO_CHECK_ITEMS_COPY}
        </div>
      )}
      {preparing && (
        <div data-testid="loop-preparing-items" role="status" style={NOTE_STYLE}>
          {PREPARING_COPY}
        </div>
      )}
      {materialsNote && (
        <div data-testid="loop-materials-unavailable" role="status" style={NOTE_STYLE}>
          {MATERIALS_UNAVAILABLE_COPY}
        </div>
      )}
      {practiceUnavailable.length > 0 && (
        <div data-testid="loop-practice-unavailable" role="status"
          style={{ ...NOTE_STYLE, fontSize: 14, lineHeight: 1.5 }}>
          <p style={{ margin: "0 0 6px" }}>{NO_FRESH_PRACTICE_COPY}</p>
          <p style={{ margin: "0 0 8px", overflowWrap: "anywhere" }}>Practice unavailable: {practiceUnavailable.map((id) => names.get(id) ?? "A selected concept").join(", ")}.</p>
          {exhaustedPracticeAttempt && <p style={{ margin: "0 0 8px" }}>This session already moved past those concepts. Once new questions are available, start a new session to practise them.</p>}
          <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
            {libraryVisible && <Link data-testid="loop-practice-sources" href="/library" className="btn btn--sm btn--ghost" style={{ minHeight: 44, flex: "1 1 130px", whiteSpace: "normal", justifyContent: "center", textAlign: "center" }}>Review source material</Link>}
            {!exhaustedPracticeAttempt && canRefreshPractice && (
              <button data-testid="loop-practice-refresh" type="button" className="btn btn--sm"
                style={{ minHeight: 44, flex: "1 1 130px", whiteSpace: "normal" }} disabled={refreshDisabled}
                onClick={onRefreshPractice}>Check for fresh practice</button>
            )}
          </div>
        </div>
      )}
      {topicOffer && (
        // ?topic= while a session is open: resume won (a reload never starts a
        // probe, §11.3); the link's concept is one click away, never automatic.
        <div
          data-testid="loop-topic-offer"
          role="status"
          style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap", fontSize: 13 }}
        >
          <span style={{ color: "var(--text-dim)" }}>You picked “{topicOffer}”. This session is still open.</span>
          <button
            data-testid="loop-topic-start"
            className="btn btn--sm"
            disabled={topicStartDisabled}
            onClick={onTopicStart}
          >
            Start a session on {topicOffer}
          </button>
        </div>
      )}
    </div>
  );
}

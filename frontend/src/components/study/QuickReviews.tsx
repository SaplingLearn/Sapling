"use client";
/**
 * Quick Reviews: the studied concepts that are slipping (stale, struggling or
 * under 70%), as one row that starts their flashcards. Hovering or focusing it
 * lists them first.
 *
 * One line: the glyph, the title in blue beside it, and a solid blue button
 * carrying the estimate and chevron. What the row is for is spelled out in the hover list.
 *
 * W8.3b / W3.3b: when the list is the FSRS-due set (`fsrsDue`), the pop-up also
 * offers a Practice secondary CTA (same due concept ids → Quiz) beside
 * Flashcards — cue stream, not Teach.
 */
import React from "react";
import { INHERIT_FONT } from "@/lib/inheritFont";
import { Icon } from "../Icon";
import { quickReviewEstimate } from "./hubModel";
import { CardsIcon, ELLIPSIS, POPOVER, StatusDot } from "./hubUi";
import s from "./StudyHub.module.css";
import type { Concept } from "./studyModel";

export type QuickReview = { t: Concept; ago: number };

const reviewsLabel = (n: number, fsrsDue: boolean) =>
  fsrsDue
    ? `${n} Due ${n === 1 ? "Review" : "Reviews"}`
    : `${n} Quick ${n === 1 ? "Review" : "Reviews"}`;
/** Why a concept is on the list: FSRS-due, not seen for a week, or simply weak. */
const reason = (x: QuickReview, fsrsDue: boolean) =>
  fsrsDue
    ? "Due for review"
    : (x.ago >= 7 ? `Last seen ${x.ago} days ago` : `Slipping · ${x.t.m}%`);

function ReviewList({ reviews, courseLabel, onStart, onQuiz, fsrsDue }: {
  reviews: QuickReview[];
  courseLabel: string;
  onStart: () => void;
  /** W8.3b / W3.3b: Practice (Quiz) secondary when Due Reviews + quiz is shown. */
  onQuiz: (() => void) | null;
  fsrsDue: boolean;
}) {
  return (
    <div style={{ position: "absolute", left: 0, right: 0, top: "100%", paddingTop: 8, zIndex: 31 }}>
      <div role="dialog" aria-label={fsrsDue ? "Due reviews" : "Quick reviews"} className={s.pop} style={{ width: "100%", boxSizing: "border-box", ...POPOVER, padding: "14px 16px", display: "flex", flexDirection: "column", gap: 10 }}>
        <span style={{ display: "flex", flexDirection: "column", gap: 2 }}>
          <span style={{ fontSize: "var(--fs-base)", fontWeight: 600, color: "var(--text)" }}>{reviewsLabel(reviews.length, fsrsDue)}</span>
          <span style={{ fontSize: "var(--fs-sm)", color: "var(--text-muted)" }}>{quickReviewEstimate(reviews.length)} · {courseLabel}</span>
        </span>
        <span className={s.catScroll} style={{ display: "flex", flexDirection: "column", maxHeight: 200, overflowY: "auto", paddingRight: 4 }}>
          {reviews.map(x => (
            <span key={x.t.id} style={{ display: "flex", alignItems: "center", gap: 10, padding: "7px 0", borderTop: "1px solid var(--border)" }}>
              <StatusDot st={x.t.st} size={8} fixed />
              <span style={{ flex: 1, minWidth: 0, fontSize: "var(--fs-md)", fontWeight: 600, ...ELLIPSIS }}>{x.t.name}</span>
              <span style={{ fontSize: "var(--fs-xs)", color: "var(--text-muted)", whiteSpace: "nowrap" }}>{reason(x, fsrsDue)}</span>
            </span>
          ))}
        </span>
        {onQuiz ? (
          <span style={{ display: "flex", gap: 8 }}>
            <button type="button" className="btn btn--primary" data-testid="due-reviews-flashcards" onClick={onStart} style={{ flex: 1, height: 36, justifyContent: "center" }}>
              Flashcards
            </button>
            <button type="button" className="btn" data-testid="due-reviews-quiz" onClick={onQuiz} style={{ flex: 1, height: 36, justifyContent: "center" }}>
              Practice what&apos;s due
            </button>
          </span>
        ) : (
          <button type="button" className="btn btn--primary" onClick={onStart} style={{ height: 36, justifyContent: "center" }}>Start Review</button>
        )}
      </div>
    </div>
  );
}

export function QuickReviews({ reviews, courseLabel, onStart, onQuiz = null, fsrsDue = false }: {
  /** Picked over the whole course, whichever exam tab is selected. */
  reviews: QuickReview[];
  /** So the list is named for what it is over: the course, not the exam. */
  courseLabel: string;
  /** Starts flashcards on these concepts. */
  onStart: () => void;
  /**
   * W8.3b / W3.3b: Practice secondary for Due Reviews (learner-next due[] →
   * Quiz). Null while flags off, quiz hidden, or the due bucket is empty —
   * flag-off UI unchanged.
   */
  onQuiz?: (() => void) | null;
  /** W8.3: list is the FSRS-due set from learner-next. */
  fsrsDue?: boolean;
}) {
  const [open, setOpen] = React.useState(false);
  if (reviews.length === 0) return null;
  return (
    <div onMouseEnter={() => setOpen(true)} onMouseLeave={() => setOpen(false)} style={{ position: "relative" }}>
      <button className={s.hoverQr} onClick={onStart} onFocus={() => setOpen(true)} onBlur={() => setOpen(false)} aria-expanded={open}
        style={{ width: "100%", display: "flex", alignItems: "center", gap: 8, padding: "12px 14px", border: 0, borderRadius: "var(--r-md)", background: "var(--info-soft)", color: "var(--text)", ...INHERIT_FONT, textAlign: "left", cursor: "pointer" }}>
        <span aria-hidden="true" style={{ width: 24, display: "grid", placeItems: "center", flexShrink: 0, color: "var(--info)" }}><CardsIcon size={21} /></span>
        <span style={{ flex: 1, minWidth: 0, fontSize: "var(--fs-md)", fontWeight: 600, color: "var(--info)", ...ELLIPSIS }}>{reviewsLabel(reviews.length, fsrsDue)}</span>
        {/* The original action: the estimate and the chevron in ONE solid blue
            button, not a pale chip sitting beside a loose chevron. */}
        <span className="chip" style={{ flexShrink: 0, height: 30, padding: "0 12px", borderRadius: "var(--r-sm)", background: "var(--info)", color: "var(--accent-fg)", borderColor: "transparent", fontSize: "var(--fs-sm)", fontWeight: 700 }}>
          {quickReviewEstimate(reviews.length)}
          <Icon name="chev" size={12} />
        </span>
      </button>
      {open && (
        <ReviewList
          reviews={reviews}
          courseLabel={courseLabel}
          fsrsDue={fsrsDue}
          onStart={() => { setOpen(false); onStart(); }}
          onQuiz={onQuiz ? () => { setOpen(false); onQuiz(); } : null}
        />
      )}
    </div>
  );
}

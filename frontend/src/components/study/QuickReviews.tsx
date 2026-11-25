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
import { HANDOFF_COPY } from "@/lib/learningHandoffs";
import { Icon } from "../Icon";
import { quickReviewEstimate } from "./hubModel";
import { CardsIcon, StatusDot } from "./hubUi";
import q from "./QuickReviews.module.css";
import s from "./StudyHub.module.css";
import type { Concept } from "./studyModel";

export type QuickReview = { t: Concept; ago: number };

const reviewsLabel = (n: number, fsrsDue: boolean) =>
  fsrsDue
    ? `${n} ${n === 1 ? "review" : "reviews"} due`
    : `${n} quick ${n === 1 ? "review" : "reviews"}`;
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
    <div className={q.listAnchor}>
      <div role="dialog" aria-label={fsrsDue ? "Due reviews" : "Quick reviews"} className={`${s.pop} ${s.popover} ${q.list}`}>
        <span className={q.head}>
          <span className={q.headTitle}>{reviewsLabel(reviews.length, fsrsDue)}</span>
          <span className={q.headMeta}>{quickReviewEstimate(reviews.length)} · {courseLabel}</span>
        </span>
        <span className={`${s.catScroll} ${q.scroll}`}>
          {reviews.map((x, i) => (
            <span key={x.t.id} className={q.item} style={{ "--i": i } as React.CSSProperties}>
              <StatusDot st={x.t.st} size={8} fixed />
              <span className={`${q.itemName} ${s.ellipsis}`}>{x.t.name}</span>
              <span className={q.itemReason}>{reason(x, fsrsDue)}</span>
            </span>
          ))}
        </span>
        {onQuiz ? (
          <span className={q.actions}>
            <button type="button" className={`btn btn--primary ${q.action} ${q.actionShare}`} data-testid="due-reviews-flashcards" onClick={onStart}>
              {HANDOFF_COPY.reviewFlashcards}
            </button>
            <button type="button" className={`btn ${q.action} ${q.actionShare}`} data-testid="due-reviews-quiz" onClick={onQuiz}>
              {HANDOFF_COPY.practiceWhatsDue}
            </button>
          </span>
        ) : (
          <button type="button" className={`btn btn--primary ${q.action}`} onClick={onStart}>Start review</button>
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
    <div onMouseEnter={() => setOpen(true)} onMouseLeave={() => setOpen(false)} className={q.anchor}>
      <button className={q.row} onClick={onStart} onFocus={() => setOpen(true)} onBlur={() => setOpen(false)} aria-expanded={open}>
        <span aria-hidden="true" className={q.glyph}><CardsIcon size={21} /></span>
        <span className={`${q.title} ${s.ellipsis}`}>{reviewsLabel(reviews.length, fsrsDue)}</span>
        {/* The original action: the estimate and the chevron in ONE solid blue
            button, not a pale chip sitting beside a loose chevron. */}
        <span className={`chip ${q.estimate}`}>
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

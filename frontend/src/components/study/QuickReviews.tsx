"use client";
/**
 * Quick Reviews: the studied concepts that are slipping (stale, struggling or
 * under 70%), as one row that opens their list, with Review (their
 * flashcards) under it.
 *
 * One line: the glyph, the title in blue beside it, and a solid blue button
 * carrying the estimate and chevron. What the row is for is spelled out in the list.
 *
 * W8.3b / W3.3b: when the list is the FSRS-due set (`fsrsDue`), the pop-up also
 * offers a Practice secondary CTA (same due concept ids → Quiz) beside
 * Flashcards — cue stream, not Teach.
 */
import React from "react";
import { HandoffLink } from "@/components/ui/HandoffLink";
import { LEARNING_COPY } from "@/lib/learningCopy";
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

function ReviewList({ id, reviews, courseLabel, reviewHref, quizHref, onNavigate, fsrsDue }: {
  id: string;
  reviews: QuickReview[];
  courseLabel: string;
  reviewHref: string;
  /** W8.3b / W3.3b: Practice (Quiz) secondary when Due Reviews + quiz is shown. */
  quizHref: string | null;
  onNavigate: (href: string) => void;
  fsrsDue: boolean;
}) {
  return (
    <div className={q.listAnchor}>
      <div id={id} role="region" aria-label={fsrsDue ? "Due reviews" : "Quick reviews"} className={`${s.pop} ${s.popover} ${q.list}`}>
        <span className={q.head}>
          <span className={q.headTitle}>{reviewsLabel(reviews.length, fsrsDue)}</span>
          <span className={q.headMeta}>{quickReviewEstimate(reviews.length)} · {courseLabel}</span>
        </span>
        <span className={`${s.catScroll} ${q.scroll}`}>
          {reviews.map((x, i) => (
            // The stagger stops growing after ten rows, so a long list is not
            // still arriving seconds later.
            <span key={x.t.id} className={q.item} style={{ "--i": Math.min(i, 10) } as React.CSSProperties}>
              <StatusDot st={x.t.st} size={8} fixed />
              <span className={`${q.itemName} ${s.ellipsis}`}>{x.t.name}</span>
              <span className={q.itemReason}>{reason(x, fsrsDue)}</span>
            </span>
          ))}
        </span>
        <span className={q.actions}>
          <HandoffLink variant="primary" href={reviewHref} onNavigate={onNavigate} testId="due-reviews-flashcards"
            className={`${q.action}${quizHref ? ` ${q.actionShare}` : ""}`}>
            {LEARNING_COPY.review}
          </HandoffLink>
          {quizHref && (
            <HandoffLink href={quizHref} onNavigate={onNavigate} testId="due-reviews-quiz" className={`${q.action} ${q.actionShare}`}>
              {LEARNING_COPY.practiceDue}
            </HandoffLink>
          )}
        </span>
      </div>
    </div>
  );
}

/**
 * The row is a disclosure (audit: the hover-only pop-up kept keyboard and
 * touch from its buttons): a click or Enter opens the list in place, and
 * Escape, a click outside or the row again closes it. Its actions are real
 * links (`HandoffLink`) that leave through the hub's fade.
 */
export function QuickReviews({ reviews, courseLabel, reviewHref, quizHref = null, onNavigate, fsrsDue = false }: {
  /** Picked over the whole course, whichever exam tab is selected. */
  reviews: QuickReview[];
  /** So the list is named for what it is over: the course, not the exam. */
  courseLabel: string;
  /** Flashcards on these concepts. */
  reviewHref: string;
  /**
   * W8.3b / W3.3b: Practice secondary for Due Reviews (learner-next due[] →
   * Quiz). Null while flags off, quiz hidden, or the due bucket is empty —
   * flag-off UI unchanged.
   */
  quizHref?: string | null;
  /** A plain click on an action: the hub's leave (fade, then navigate). */
  onNavigate: (href: string) => void;
  /** W8.3: list is the FSRS-due set from learner-next. */
  fsrsDue?: boolean;
}) {
  const [open, setOpen] = React.useState(false);
  const anchor = React.useRef<HTMLDivElement>(null);
  const rowRef = React.useRef<HTMLButtonElement>(null);
  const listId = React.useId();
  React.useEffect(() => {
    if (!open) return;
    const outside = (e: PointerEvent) => {
      if (anchor.current && !anchor.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("pointerdown", outside);
    return () => document.removeEventListener("pointerdown", outside);
  }, [open]);
  if (reviews.length === 0) return null;
  const leave = (href: string) => { setOpen(false); onNavigate(href); };
  return (
    <div
      ref={anchor}
      className={q.anchor}
      onKeyDown={(e) => {
        if (e.key === "Escape" && open) {
          setOpen(false);
          rowRef.current?.focus();
        }
      }}
    >
      <button
        ref={rowRef}
        type="button"
        className={q.row}
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        aria-controls={open ? listId : undefined}
      >
        <span aria-hidden="true" className={q.glyph}><CardsIcon size={21} /></span>
        <span className={`${q.title} ${s.ellipsis}`}>{reviewsLabel(reviews.length, fsrsDue)}</span>
        {/* The estimate and the chevron in ONE solid blue button. */}
        <span className={`chip ${q.estimate}`}>
          {quickReviewEstimate(reviews.length)}
          <Icon name="chev" size={12} />
        </span>
      </button>
      {open && (
        <ReviewList
          id={listId}
          reviews={reviews}
          courseLabel={courseLabel}
          fsrsDue={fsrsDue}
          reviewHref={reviewHref}
          quizHref={quizHref}
          onNavigate={leave}
        />
      )}
    </div>
  );
}

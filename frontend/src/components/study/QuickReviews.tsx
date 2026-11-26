"use client";
/**
 * Quick Reviews: the studied concepts that are slipping (stale, struggling or
 * under 70%), as one row that starts their flashcards. Hovering or focusing it
 * lists them first.
 *
 * One line: the glyph, the title in blue beside it, and a solid blue button
 * carrying the estimate and chevron. What the row is for is spelled out in the hover list.
 */
import React from "react";
import { Icon } from "../Icon";
import { quickReviewEstimate } from "./hubModel";
import { CardsIcon, StatusDot } from "./hubUi";
import s from "./StudyHub.module.css";
import type { Concept } from "./studyModel";
import { cn } from "@/lib/cn";

export type QuickReview = { t: Concept; ago: number };

const reviewsLabel = (n: number) => `${n} Quick ${n === 1 ? "Review" : "Reviews"}`;
/** Why a concept is on the list: not seen for a week, or simply weak. */
const reason = (x: QuickReview) => (x.ago >= 7 ? `Last seen ${x.ago} days ago` : `Slipping · ${x.t.m}%`);

function ReviewList({ reviews, courseLabel, onStart }: { reviews: QuickReview[]; courseLabel: string; onStart: () => void }) {
  return (
    <div className="absolute left-0 right-0 top-full pt-2 z-31">
      <div role="dialog" aria-label="Quick reviews" className={cn(s.pop, "w-full box-border [background:var(--bg-panel)] border border-border rounded-md shadow-lg py-3.5 px-4 flex flex-col gap-2.5")}>
        <span className="flex flex-col gap-0.5">
          <span className="text-base font-semibold text-text">{reviewsLabel(reviews.length)}</span>
          <span className="text-sm text-text-muted">{quickReviewEstimate(reviews.length)} · {courseLabel}</span>
        </span>
        <span className={cn(s.catScroll, "flex flex-col max-h-50 overflow-y-auto pr-1")}>
          {reviews.map(x => (
            <span key={x.t.id} className="flex items-center gap-2.5 py-[7px] px-0 border-t border-t-border">
              <StatusDot st={x.t.st} size={8} fixed />
              <span className="flex-1 min-w-0 text-md font-semibold whitespace-nowrap overflow-hidden text-ellipsis">{x.t.name}</span>
              <span className="text-xs text-text-muted whitespace-nowrap">{reason(x)}</span>
            </span>
          ))}
        </span>
        <button type="button" className="btn btn--primary h-9 justify-center" onClick={onStart}>Start Review</button>
      </div>
    </div>
  );
}

export function QuickReviews({ reviews, courseLabel, onStart }: {
  /** Picked over the whole course, whichever exam tab is selected. */
  reviews: QuickReview[];
  /** So the list is named for what it is over: the course, not the exam. */
  courseLabel: string;
  /** Starts flashcards on these concepts. */
  onStart: () => void;
}) {
  const [open, setOpen] = React.useState(false);
  if (reviews.length === 0) return null;
  return (
    <div onMouseEnter={() => setOpen(true)} onMouseLeave={() => setOpen(false)} className="relative">
      <button className={cn(s.hoverQr, "w-full flex items-center gap-2 py-3 px-3.5 border-0 rounded-md [background:var(--info-soft)] text-text [font-family:inherit] [font-size:inherit] [font-weight:inherit] [font-style:inherit] [line-height:inherit] text-left cursor-pointer")} onClick={onStart} onFocus={() => setOpen(true)} onBlur={() => setOpen(false)} aria-expanded={open}>
        <span aria-hidden="true" className="w-6 grid place-items-center shrink-0 text-info"><CardsIcon size={21} /></span>
        <span className="flex-1 min-w-0 text-md font-semibold text-info whitespace-nowrap overflow-hidden text-ellipsis">{reviewsLabel(reviews.length)}</span>
        {/* The original action: the estimate and the chevron in ONE solid blue
            button, not a pale chip sitting beside a loose chevron. */}
        <span className="chip shrink-0 h-7.5 py-0 px-3 rounded-sm bg-info text-accent-fg border-transparent text-sm font-bold">
          {quickReviewEstimate(reviews.length)}
          <Icon name="chev" size={12} />
        </span>
      </button>
      {open && <ReviewList reviews={reviews} courseLabel={courseLabel} onStart={() => { setOpen(false); onStart(); }} />}
    </div>
  );
}

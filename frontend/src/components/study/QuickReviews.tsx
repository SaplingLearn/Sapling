"use client";
/**
 * Quick Reviews: the studied concepts that are slipping (stale, struggling or
 * under 70%), as one row that starts their flashcards. Hovering or focusing it
 * lists them first.
 *
 * Built like a Today's-plan row on the Dashboard: glyph, a 13px title over an
 * 11px meta line, a chip, a chevron.
 */
import React from "react";
import { INHERIT_FONT } from "@/lib/inheritFont";
import { Icon } from "../Icon";
import { quickReviewEstimate } from "./hubModel";
import { CardsIcon, ELLIPSIS, POPOVER, StatusDot } from "./hubUi";
import s from "./StudyHub.module.css";
import type { Concept } from "./studyModel";

export type QuickReview = { t: Concept; ago: number };

const reviewsLabel = (n: number) => `${n} Quick ${n === 1 ? "Review" : "Reviews"}`;
/** Why a concept is on the list: not seen for a week, or simply weak. */
const reason = (x: QuickReview) => (x.ago >= 7 ? `Last seen ${x.ago} days ago` : `Slipping · ${x.t.m}%`);

function ReviewList({ reviews, courseLabel, onStart }: { reviews: QuickReview[]; courseLabel: string; onStart: () => void }) {
  return (
    <div style={{ position: "absolute", left: 0, right: 0, top: "100%", paddingTop: 8, zIndex: 31 }}>
      <div role="dialog" aria-label="Quick reviews" className={s.pop} style={{ width: "100%", boxSizing: "border-box", ...POPOVER, padding: "14px 16px", display: "flex", flexDirection: "column", gap: 10 }}>
        <span style={{ display: "flex", flexDirection: "column", gap: 2 }}>
          <span style={{ fontSize: "var(--fs-base)", fontWeight: 600, color: "var(--text)" }}>{reviewsLabel(reviews.length)}</span>
          <span style={{ fontSize: "var(--fs-sm)", color: "var(--text-muted)" }}>{quickReviewEstimate(reviews.length)} · {courseLabel}</span>
        </span>
        <span className={s.catScroll} style={{ display: "flex", flexDirection: "column", maxHeight: 200, overflowY: "auto", paddingRight: 4 }}>
          {reviews.map(x => (
            <span key={x.t.id} style={{ display: "flex", alignItems: "center", gap: 10, padding: "7px 0", borderTop: "1px solid var(--border)" }}>
              <StatusDot st={x.t.st} size={8} fixed />
              <span style={{ flex: 1, minWidth: 0, fontSize: "var(--fs-md)", fontWeight: 600, ...ELLIPSIS }}>{x.t.name}</span>
              <span style={{ fontSize: "var(--fs-xs)", color: "var(--text-muted)", whiteSpace: "nowrap" }}>{reason(x)}</span>
            </span>
          ))}
        </span>
        <button type="button" className="btn btn--primary" onClick={onStart} style={{ height: 36, justifyContent: "center" }}>Start Review</button>
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
    <div onMouseEnter={() => setOpen(true)} onMouseLeave={() => setOpen(false)} style={{ position: "relative" }}>
      <button className={s.hoverQr} onClick={onStart} onFocus={() => setOpen(true)} onBlur={() => setOpen(false)} aria-expanded={open}
        style={{ width: "100%", display: "flex", alignItems: "center", gap: 10, padding: "11px 11px", border: 0, borderRadius: "var(--r-md)", background: "var(--info-soft)", color: "var(--text)", ...INHERIT_FONT, textAlign: "left", cursor: "pointer" }}>
        <span aria-hidden="true" style={{ width: 18, display: "grid", placeItems: "center", flexShrink: 0, color: "var(--info)" }}><CardsIcon size={15} /></span>
        <span style={{ flex: 1, minWidth: 0 }}>
          <span style={{ display: "block", fontSize: "var(--fs-md)", fontWeight: 600, ...ELLIPSIS }}>{reviewsLabel(reviews.length)}</span>
          <span style={{ display: "block", fontSize: "var(--fs-xs)", color: "var(--text-muted)", ...ELLIPSIS }}>Flashcards on what&apos;s slipping</span>
        </span>
        <span className="chip chip--info" style={{ flexShrink: 0, background: "var(--bg-panel)" }}>{quickReviewEstimate(reviews.length)}</span>
        <span aria-hidden="true" style={{ display: "grid", flexShrink: 0, color: "var(--info)" }}><Icon name="chev" size={12} /></span>
      </button>
      {open && <ReviewList reviews={reviews} courseLabel={courseLabel} onStart={() => { setOpen(false); onStart(); }} />}
    </div>
  );
}

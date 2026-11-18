"use client";
import React from "react";
import type { LoopRating } from "@/lib/api";

const RATING_CHOICES: { value: LoopRating; label: string }[] = [
  { value: "too_easy", label: "Too easy" },
  { value: "appropriate", label: "About right" },
  { value: "too_hard", label: "Too hard" },
];

/** PKG-14 (spec §3.4): "How hard did these feel?" after every
 *  ZPD_RATING_EVERY_N_CHECKS graded checks; the server says when (done.ask_rating). */
export function RatingPrompt({ onRate }: { onRate: (rating: LoopRating) => void }) {
  return (
    <div
      data-testid="loop-rating"
      role="group"
      aria-label="How hard did these questions feel?"
      style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap", fontSize: 13 }}
    >
      <span style={{ color: "var(--text-muted)" }}>How hard did these questions feel?</span>
      {RATING_CHOICES.map((c) => (
        <button
          key={c.value}
          data-testid={`loop-rating-${c.value}`}
          className="btn btn--sm btn--ghost"
          onClick={() => onRate(c.value)}
        >
          {c.label}
        </button>
      ))}
    </div>
  );
}

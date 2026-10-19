"use client";

import React from "react";
import type { SessionSummaryData } from "@/lib/api";

interface SessionSummaryProps {
  summary: SessionSummaryData;
  onClose: () => void;
}

/** PKG-14b (spec §11.2): the summary carries only what the backend fills —
 *  `concepts_covered` and `time_spent_minutes`. The three lists that were
 *  always empty (mastery changes, new connections, recommended next) are gone. */
export function SessionSummary({ summary, onClose }: SessionSummaryProps) {
  const { concepts_covered = [], time_spent_minutes = 0 } = summary || {};
  const titleId = React.useId();
  const doneRef = React.useRef<HTMLButtonElement>(null);
  const closeRef = React.useRef(onClose);
  React.useEffect(() => {
    closeRef.current = onClose;
  }, [onClose]);
  // Focus lands on Done once, when the summary opens; Escape closes it.
  React.useEffect(() => {
    doneRef.current?.focus();
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") closeRef.current(); };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, []);

  return (
    <div
      style={{
        position: "fixed",
        inset: 0,
        background: "rgba(0,0,0,0.45)",
        zIndex: 200,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        padding: 16,
      }}
      onClick={onClose}
    >
      <div
        className="card"
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        onClick={e => e.stopPropagation()}
        style={{
          width: "min(560px, 100%)",
          maxHeight: "calc(100vh - 64px)",
          overflowY: "auto",
          padding: 28,
          boxShadow: "var(--shadow-lg)",
        }}
      >
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 6 }}>
          <div className="label-micro">Session summary</div>
          <button className="btn btn--ghost btn--sm" onClick={onClose} aria-label="Close">×</button>
        </div>
        {/* Honest wrap-up: what happened, never an automatic mastery celebration. */}
        <h2 id={titleId} className="h-serif" style={{ fontSize: 28, margin: "0 0 4px", fontWeight: 400 }}>Session wrapped up.</h2>
        <div style={{ fontSize: 13, color: "var(--text-dim)", marginBottom: 20 }}>
          {time_spent_minutes > 0 ? `${time_spent_minutes} minute${time_spent_minutes === 1 ? "" : "s"} spent.` : "Your conversation is saved in your sessions."}
        </div>

        {concepts_covered.length > 0 && (
          <section style={{ marginBottom: 18 }}>
            <div className="label-micro" style={{ marginBottom: 8 }}>Concepts covered</div>
            <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
              {concepts_covered.map(c => (
                <span key={c} className="chip" style={{ textTransform: "none", fontFamily: "var(--font-sans)" }}>
                  {c}
                </span>
              ))}
            </div>
          </section>
        )}

        <div style={{ display: "flex", justifyContent: "flex-end", marginTop: 20, gap: 8 }}>
          <button ref={doneRef} className="btn btn--primary" onClick={onClose}>Done</button>
        </div>
      </div>
    </div>
  );
}

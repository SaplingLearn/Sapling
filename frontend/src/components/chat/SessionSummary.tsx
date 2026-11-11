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
        <div className="h-serif" style={{ fontSize: 28, marginBottom: 4 }}>Nice session.</div>
        <div style={{ fontSize: 13, color: "var(--text-dim)", marginBottom: 20 }}>
          {time_spent_minutes > 0 ? `${time_spent_minutes} minute${time_spent_minutes === 1 ? "" : "s"} spent.` : "Session wrapped."}
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
          <button className="btn btn--primary" onClick={onClose}>Done</button>
        </div>
      </div>
    </div>
  );
}

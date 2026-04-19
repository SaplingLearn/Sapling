"use client";

import React from "react";
import type { SessionSummaryData } from "@/lib/api";

interface SessionSummaryProps {
  summary: SessionSummaryData;
  onClose: () => void;
  onStartNext?: (concept: string) => void;
}

export function SessionSummary({ summary, onClose, onStartNext }: SessionSummaryProps) {
  const { concepts_covered = [], mastery_changes = [], time_spent_minutes = 0, recommended_next = [] } = summary || {};

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

        {mastery_changes.length > 0 && (
          <section style={{ marginBottom: 18 }}>
            <div className="label-micro" style={{ marginBottom: 8 }}>Mastery changes</div>
            <div style={{ display: "grid", gap: 6 }}>
              {mastery_changes.map(m => {
                const delta = (m.after ?? 0) - (m.before ?? 0);
                const up = delta >= 0;
                return (
                  <div
                    key={m.concept}
                    style={{
                      display: "flex",
                      justifyContent: "space-between",
                      alignItems: "center",
                      padding: "8px 12px",
                      borderRadius: "var(--r-sm)",
                      background: up ? "var(--accent-soft)" : "var(--err-soft)",
                      color: up ? "var(--accent)" : "var(--err)",
                      fontSize: 13,
                    }}
                  >
                    <span style={{ fontWeight: 500 }}>{m.concept}</span>
                    <span className="mono" style={{ fontSize: 12 }}>
                      {Math.round((m.before ?? 0) * 100)}% → {Math.round((m.after ?? 0) * 100)}%
                      <span style={{ marginLeft: 8, fontWeight: 600 }}>{up ? "+" : ""}{Math.round(delta * 100)}</span>
                    </span>
                  </div>
                );
              })}
            </div>
          </section>
        )}

        {recommended_next.length > 0 && (
          <section style={{ marginBottom: 8 }}>
            <div className="label-micro" style={{ marginBottom: 8 }}>Recommended next</div>
            <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
              {recommended_next.map(c => (
                <button
                  key={c}
                  onClick={() => onStartNext?.(c)}
                  className="btn btn--sm"
                  style={{ fontSize: 12 }}
                >
                  {c}
                </button>
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

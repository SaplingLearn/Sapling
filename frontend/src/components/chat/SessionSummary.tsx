"use client";

import React from "react";
import type { SessionSummaryData } from "@/lib/api";
import Dialog from "@/components/Dialog";
import { cn } from "@/lib/cn";

interface SessionSummaryProps {
  summary: SessionSummaryData;
  onClose: () => void;
  onStartNext?: (concept: string) => void;
}

export function SessionSummary({ summary, onClose, onStartNext }: SessionSummaryProps) {
  const { concepts_covered = [], mastery_changes = [], time_spent_minutes = 0, recommended_next = [] } = summary || {};

  return (
    <Dialog open onClose={onClose} labelledBy="session-summary-title" width="560px" zIndex={200} showCloseButton={false}>
        <div className="flex justify-between items-center mb-1.5">
          <div id="session-summary-title" className="label-micro">Session summary</div>
          <button className="btn btn--ghost btn--sm" onClick={onClose} aria-label="Close">×</button>
        </div>
        <div className="h-serif text-[28px] mb-1">Nice session.</div>
        <div className="text-md text-text-dim mb-5">
          {time_spent_minutes > 0 ? `${time_spent_minutes} minute${time_spent_minutes === 1 ? "" : "s"} spent.` : "Session wrapped."}
        </div>

        {concepts_covered.length > 0 && (
          <section className="mb-4.5">
            <div className="label-micro mb-2">Concepts covered</div>
            <div className="flex flex-wrap gap-1.5">
              {concepts_covered.map(c => (
                <span key={c} className="chip normal-case font-sans">
                  {c}
                </span>
              ))}
            </div>
          </section>
        )}

        {mastery_changes.length > 0 && (
          <section className="mb-4.5">
            <div className="label-micro mb-2">Mastery changes</div>
            <div className="grid gap-1.5">
              {mastery_changes.map(m => {
                const delta = (m.after ?? 0) - (m.before ?? 0);
                const up = delta >= 0;
                return (
                  <div
                    key={m.concept}
                    className={cn("flex justify-between items-center py-2 px-3 rounded-sm text-md", up ? "bg-accent-soft" : "bg-err-soft", up ? "text-accent" : "text-err")}
                  >
                    <span className="font-medium">{m.concept}</span>
                    <span className="mono text-sm">
                      {Math.round((m.before ?? 0) * 100)}% → {Math.round((m.after ?? 0) * 100)}%
                      <span className="ml-2 font-semibold">{up ? "+" : ""}{Math.round(delta * 100)}</span>
                    </span>
                  </div>
                );
              })}
            </div>
          </section>
        )}

        {recommended_next.length > 0 && (
          <section className="mb-2">
            <div className="label-micro mb-2">Recommended next</div>
            <div className="flex flex-wrap gap-1.5">
              {recommended_next.map(c => (
                <button
                  key={c}
                  onClick={() => onStartNext?.(c)}
                  className="btn btn--sm text-sm"
                >
                  {c}
                </button>
              ))}
            </div>
          </section>
        )}

        <div className="flex justify-end mt-5 gap-2">
          <button className="btn btn--primary" onClick={onClose}>Done</button>
        </div>
    </Dialog>
  );
}

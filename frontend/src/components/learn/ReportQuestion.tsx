"use client";
// "Report this question" (learning-loop spec §13 A113; GitHub #695). The loop's
// check card (LoopLearn) and Study's review queue (DueQueue) render it while the
// `item_reports` flag is on. A check item's key comes from a classmate's upload
// and no instructor reviews it, so a student can say what is wrong with one —
// a reason from this short list, never free text (the server stores enums only).
// The parent sends the report and moves the student on; this control only asks
// why. Every testid is `${testIdPrefix}…`, written at the call site.
import React from "react";
import type { LoopReportReason } from "@/lib/api";

export const REPORT_REASONS: readonly { reason: LoopReportReason; label: string }[] = [
  { reason: "wrong_answer", label: "The answer is wrong" },
  { reason: "unclear", label: "It's unclear" },
  { reason: "not_from_my_course", label: "Not from my course" },
];

export function ReportQuestion({
  testIdPrefix,
  disabled = false,
  onReport,
}: {
  testIdPrefix: string;
  disabled?: boolean;
  /** Sends the report; resolves true once it is recorded (the parent then
   *  moves on), false to keep the reasons open for another try. */
  onReport: (reason: LoopReportReason) => Promise<boolean>;
}) {
  const [open, setOpen] = React.useState(false);
  const [busy, setBusy] = React.useState(false);
  const mounted = React.useRef(true);
  React.useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  const send = async (reason: LoopReportReason) => {
    if (busy) return;
    setBusy(true);
    const done = await onReport(reason).catch(() => false);
    if (!mounted.current) return;
    setBusy(false);
    if (done) setOpen(false);
  };

  if (!open) {
    return (
      <button
        type="button"
        data-testid={testIdPrefix}
        className="btn btn--sm btn--ghost"
        style={{ alignSelf: "flex-start", fontSize: 12, color: "var(--text-muted)" }}
        disabled={disabled}
        onClick={() => setOpen(true)}
      >
        Report this question
      </button>
    );
  }
  return (
    <div
      role="group"
      aria-label="What's wrong with this question?"
      data-testid={`${testIdPrefix}-reasons`}
      style={{ display: "flex", gap: 6, alignItems: "center", flexWrap: "wrap", fontSize: 13 }}
    >
      <span style={{ color: "var(--text-muted)" }}>What&apos;s wrong with it?</span>
      {REPORT_REASONS.map((r) => (
        <button
          key={r.reason}
          type="button"
          data-testid={`${testIdPrefix}-reason-${r.reason}`}
          className="btn btn--sm"
          disabled={busy || disabled}
          aria-busy={busy}
          onClick={() => void send(r.reason)}
        >
          {r.label}
        </button>
      ))}
      <button
        type="button"
        data-testid={`${testIdPrefix}-cancel`}
        className="btn btn--sm btn--ghost"
        disabled={busy}
        onClick={() => setOpen(false)}
      >
        Cancel
      </button>
    </div>
  );
}

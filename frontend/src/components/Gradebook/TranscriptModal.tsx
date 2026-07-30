"use client";
import React from "react";
import Dialog from "@/components/Dialog";
import { useToast } from "@/components/ToastProvider";
import { humanizeError } from "@/lib/errorMessage";
import { getGpa } from "@/lib/api";
import { buildTranscript } from "@/lib/transcript";
import { percentColor } from "@/components/Gradebook/CourseCard";
import type { GpaReport } from "@/lib/types";

interface Props {
  open: boolean;
  userId: string;
  onClose: () => void;
}

/**
 * Cumulative transcript over GET /api/gradebook/gpa (#139): overall
 * credit-weighted GPA plus per-semester sections, most recent term first.
 * Ungraded enrollments are listed as "in progress" — they never count as 0.
 */
export function TranscriptModal({ open, userId, onClose }: Props) {
  const toast = useToast();
  const [report, setReport] = React.useState<GpaReport | null>(null);
  const [loading, setLoading] = React.useState(false);
  const [failed, setFailed] = React.useState(false);

  const load = React.useCallback(async () => {
    setLoading(true);
    setFailed(false);
    try {
      setReport(await getGpa(userId));
    } catch (err) {
      // #463 pattern: surface the failure (toast + inline retry), never
      // render a failed load as an empty-but-fine transcript.
      setFailed(true);
      toast.error(humanizeError(err, "Couldn't load your transcript. Try again."));
    } finally {
      setLoading(false);
    }
  }, [userId, toast]);

  React.useEffect(() => {
    if (!open) return;
    setReport(null);
    load();
  }, [open, load]);

  return (
    <Dialog open={open} onClose={onClose} title="Transcript" size="md" padding="24px">
      {loading ? (
        <div aria-hidden="true">
          <div className="skeleton" style={{ height: 40, borderRadius: 8, marginBottom: 16 }} />
          {Array.from({ length: 3 }).map((_, i) => (
            <div key={i} className="skeleton" style={{ height: 22, borderRadius: 6, marginBottom: 10 }} />
          ))}
        </div>
      ) : failed ? (
        <div
          role="alert"
          style={{
            padding: "14px 16px",
            borderRadius: "var(--r-md)",
            background: "var(--err-soft)",
            border: "1px solid color-mix(in oklab, var(--err) 20%, transparent)",
            display: "flex",
            gap: 12,
            alignItems: "center",
            justifyContent: "space-between",
            flexWrap: "wrap",
          }}
        >
          <span style={{ fontSize: 13, color: "var(--text-dim)" }}>
            We couldn&apos;t load your transcript.
          </span>
          <button
            type="button"
            data-testid="gradebook-transcript-retry"
            className="btn btn--primary"
            onClick={load}
            style={{ padding: "6px 14px", fontSize: 13 }}
          >
            Try again
          </button>
        </div>
      ) : report ? (
        <TranscriptBody report={report} />
      ) : null}
    </Dialog>
  );
}

function TranscriptBody({ report }: { report: GpaReport }) {
  const semesters = buildTranscript(report.courses);

  if (semesters.length === 0) {
    return (
      <p style={{ margin: 0, fontSize: 14, color: "var(--text-dim)", lineHeight: 1.55 }}>
        Nothing on the transcript yet — grades appear here once your courses
        have graded work.
      </p>
    );
  }

  return (
    <div>
      <div
        style={{
          display: "flex",
          alignItems: "baseline",
          justifyContent: "space-between",
          gap: 12,
          padding: "4px 0 14px",
          borderBottom: "1px solid var(--border)",
          marginBottom: 16,
        }}
      >
        <span
          className="mono"
          style={{
            fontSize: 10,
            letterSpacing: "0.18em",
            textTransform: "uppercase",
            color: "var(--text-muted)",
            fontWeight: 600,
          }}
        >
          Cumulative GPA
        </span>
        <span
          data-testid="gradebook-transcript-gpa"
          style={{
            fontFamily: "var(--font-display), 'Playfair Display', Georgia, serif",
            fontWeight: 500,
            fontSize: 32,
            lineHeight: 1,
            letterSpacing: "-0.02em",
            color: "var(--text)",
          }}
        >
          {report.gpa === null ? "—" : report.gpa.toFixed(2)}
        </span>
      </div>

      {semesters.map((sem) => (
        <section key={sem.label || "no-term"} style={{ marginBottom: 18 }}>
          <div
            style={{
              display: "flex",
              alignItems: "baseline",
              justifyContent: "space-between",
              gap: 12,
              marginBottom: 8,
            }}
          >
            <span
              style={{
                fontFamily: "var(--font-display), 'Playfair Display', Georgia, serif",
                fontWeight: 500,
                fontSize: 16,
                color: "var(--text)",
              }}
            >
              {sem.label || "No term"}
            </span>
            <span className="mono" style={{ fontSize: 12, color: "var(--text-dim)" }}>
              GPA {sem.gpa === null ? "—" : sem.gpa.toFixed(2)}
            </span>
          </div>
          <ul style={{ listStyle: "none", margin: 0, padding: 0 }}>
            {sem.courses.map((c) => (
              <li
                key={c.course_id}
                style={{
                  display: "flex",
                  alignItems: "baseline",
                  justifyContent: "space-between",
                  gap: 12,
                  padding: "5px 0",
                  borderBottom: "1px solid var(--border)",
                }}
              >
                <span className="mono" style={{ fontSize: 12, color: "var(--text)" }}>
                  {c.course_code}
                </span>
                <span style={{ display: "flex", alignItems: "baseline", gap: 14 }}>
                  <span
                    className="mono"
                    style={{ fontSize: 11, color: "var(--text-muted)" }}
                  >
                    {c.credits ?? 1} cr
                  </span>
                  {c.letter === null ? (
                    <span
                      style={{
                        fontSize: 12,
                        fontStyle: "italic",
                        color: "var(--text-muted)",
                      }}
                    >
                      in progress
                    </span>
                  ) : (
                    <span
                      style={{
                        fontFamily:
                          "var(--font-display), 'Playfair Display', Georgia, serif",
                        fontWeight: 500,
                        fontSize: 15,
                        color: percentColor(c.percent),
                      }}
                    >
                      {c.letter}
                    </span>
                  )}
                </span>
              </li>
            ))}
          </ul>
        </section>
      ))}
    </div>
  );
}

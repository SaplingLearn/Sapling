"use client";
import React from "react";
import Dialog from "@/components/Dialog";
import { useToast } from "@/components/ToastProvider";
import { humanizeError } from "@/lib/errorMessage";
import { getGpa } from "@/lib/api";
import { buildTranscript, effectiveCredits } from "@/lib/transcript";
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
          <div className="skeleton h-10 rounded-[8px] mb-4" />
          {Array.from({ length: 3 }).map((_, i) => (
            <div key={i} className="skeleton h-5.5 rounded-sm mb-2.5" />
          ))}
        </div>
      ) : failed ? (
        <div
          role="alert"
          className="py-3.5 px-4 rounded-md bg-err-soft border border-[color-mix(in_oklab,_var(--err)_20%,_transparent)] flex gap-3 items-center justify-between flex-wrap"
        >
          <span className="text-md text-text-dim">
            We couldn&apos;t load your transcript.
          </span>
          <button
            type="button"
            data-testid="gradebook-transcript-retry"
            className="btn btn--primary py-1.5 px-3.5 text-md"
            onClick={load}
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
      <p className="m-0 text-base text-text-dim leading-[1.55]">
        Nothing on the transcript yet — grades appear here once your courses
        have graded work.
      </p>
    );
  }

  return (
    <div>
      <div
        className="flex items-baseline justify-between gap-3 pt-1 px-0 pb-3.5 border-b border-b-border mb-4"
      >
        <span
          className="mono text-sm text-text-muted font-semibold"
        >
          Cumulative GPA
        </span>
        <span
          data-testid="gradebook-transcript-gpa"
          className="font-display font-medium text-5xl leading-none tracking-[-0.02em] text-text"
        >
          {report.gpa === null ? "—" : report.gpa.toFixed(2)}
        </span>
      </div>

      {semesters.map((sem) => (
        <section key={sem.label || "no-term"} className="mb-4.5">
          <div
            className="flex items-baseline justify-between gap-3 mb-2"
          >
            <span
              className="font-display font-medium text-lg text-text"
            >
              {sem.label || "No term"}
            </span>
            <span className="mono text-base text-text-dim">
              GPA {sem.gpa === null ? "—" : sem.gpa.toFixed(2)}
            </span>
          </div>
          <ul className="list-none m-0 p-0">
            {sem.courses.map((c) => (
              <li
                key={c.course_id}
                className="flex items-baseline justify-between gap-3 py-[5px] px-0 border-b border-b-border"
              >
                <span className="mono text-sm text-text">
                  {c.course_code}
                </span>
                <span className="flex items-baseline gap-3.5">
                  <span
                    className="mono text-xs text-text-muted"
                  >
                    {/* Same rule as the GPA math — display what is weighed. */}
                    {effectiveCredits(c)} cr
                  </span>
                  {c.letter === null ? (
                    <span
                      className="text-sm italic text-text-muted"
                    >
                      in progress
                    </span>
                  ) : (
                    <span
                      className="font-display font-medium text-[15px]" style={{ color: percentColor(c.percent) }}
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

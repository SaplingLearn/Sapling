"use client";

/**
 * Admin review queue for learning-loop check items (spec §13 A113; GitHub
 * #695), over /api/admin/check-items. A check item is drafted by a model from
 * a classmate's upload and keyed from peer material — no instructor reviewed
 * it — so this lists every item the item-flaw linter flagged or a student
 * reported (counts by reason), worst first, with its text (decrypted by the
 * server for this page only) and two actions: Approve (reviewed, OK — it leaves
 * the queue until a newer report) and Retire (withdrawn for the whole course,
 * never drafted again; two clicks). An item whose retire did not finish is
 * marked and listed first.
 */

import React from "react";
import { TopBar } from "../TopBar";
import { useToast } from "../ToastProvider";
import { useUser } from "@/context/UserContext";
import { useConfirm } from "@/lib/useConfirm";
import { humanizeError } from "@/lib/errorMessage";
import {
  adminApproveCheckItem,
  adminCheckItemQueue,
  adminRetireCheckItem,
  type AdminCheckItemEntry,
  type AdminCheckItemQueue,
  type CheckItemLintFlag,
  type LoopReportReason,
} from "@/lib/api";

export const LINT_FLAG_LABELS: Record<CheckItemLintFlag, string> = {
  correct_longest: "Key is the longest option",
  correct_repeats_stem: "Key repeats the question's words",
  all_or_none_of_above: "All / none of the above",
  duplicate_options: "Duplicate options",
  negative_stem: "Negatively worded",
};

export const REPORT_REASON_LABELS: Record<LoopReportReason, string> = {
  wrong_answer: "Wrong answer",
  unclear: "Unclear",
  not_from_my_course: "Not from my course",
};

const REASONS = Object.keys(REPORT_REASON_LABELS) as LoopReportReason[];

export function AdminCheckItems() {
  // The gate lives outside the hook-owning body: a non-admin visit must not
  // fire a request that 403s (AdminAnalytics' pattern).
  const { isAdmin } = useUser();
  if (!isAdmin) {
    return (
      <div>
        <TopBar breadcrumb="Admin" title="Check-item review" subtitle="Staff only" />
        <div style={{ padding: 60, textAlign: "center", color: "var(--text-muted)" }}>
          You don&apos;t have admin access.
        </div>
      </div>
    );
  }
  return <QueueBody />;
}

function QueueBody() {
  const toast = useToast();
  const [queue, setQueue] = React.useState<AdminCheckItemQueue | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const [busyId, setBusyId] = React.useState<string | null>(null);

  // State is set only after the read settles (never synchronously in the effect).
  const load = React.useCallback(async () => {
    try {
      const q = await adminCheckItemQueue();
      setQueue(q);
      setError(null);
    } catch (err) {
      setError(humanizeError(err, "Couldn't load the review queue."));
    }
  }, []);

  React.useEffect(() => { void load(); }, [load]);

  const act = async (entry: AdminCheckItemEntry, action: "approve" | "retire") => {
    setBusyId(entry.id);
    try {
      if (action === "approve") await adminApproveCheckItem(entry.id);
      else await adminRetireCheckItem(entry.id);
      // the decision is per course question: every row of it leaves the queue
      setQueue((q) => {
        if (!q) return q;
        const left = q.items.filter(
          (i) => !(i.course_id === entry.course_id && i.question_hash === entry.question_hash),
        );
        return { ...q, items: left, count: Math.max(0, q.count - (q.items.length - left.length)) };
      });
      toast.success(action === "approve" ? "Approved — it leaves the queue." : "Retired for the whole course.");
    } catch (err) {
      toast.error(humanizeError(err, action === "approve" ? "Couldn't approve it." : "Couldn't retire it."));
    } finally {
      setBusyId(null);
    }
  };

  return (
    <div>
      <TopBar
        breadcrumb="Admin"
        title="Check-item review"
        subtitle="Learning-loop questions the linter flagged or students reported"
        actions={<span className="chip chip--err">Staff only</span>}
      />
      <div data-testid="admin-items" style={{ padding: "24px 32px", display: "grid", gap: 16, maxWidth: 960 }}>
        {error && !queue ? (
          <div role="alert" style={{ display: "flex", alignItems: "center", gap: 12, color: "var(--text-muted)", fontSize: 13 }}>
            <span>{error}</span>
            <button type="button" data-testid="admin-items-retry" className="btn btn--sm" onClick={() => void load()}>
              Try again
            </button>
          </div>
        ) : !queue ? (
          <div style={{ color: "var(--text-muted)", fontSize: 13 }}>Loading…</div>
        ) : queue.items.length === 0 ? (
          <div data-testid="admin-items-empty" style={{ color: "var(--text-muted)", fontSize: 14 }}>
            Nothing to review: no flagged or reported question is waiting.
          </div>
        ) : (
          <>
            <div data-testid="admin-items-count" style={{ color: "var(--text-muted)", fontSize: 13 }}>
              {queue.count} to review
              {queue.count > queue.items.length ? ` — showing the first ${queue.items.length}` : ""}. Reports
              from {queue.retire_min_reporters} different students retire a question on their own.
            </div>
            {queue.items.map((entry) => (
              <QueueRow
                key={entry.id}
                entry={entry}
                busy={busyId === entry.id}
                onApprove={() => void act(entry, "approve")}
                onRetire={() => void act(entry, "retire")}
              />
            ))}
          </>
        )}
      </div>
    </div>
  );
}

function QueueRow({
  entry, busy, onApprove, onRetire,
}: {
  entry: AdminCheckItemEntry;
  busy: boolean;
  onApprove: () => void;
  onRetire: () => void;
}) {
  const retire = useConfirm(onRetire);
  const reasons = REASONS.filter((r) => entry.reports[r] > 0);
  return (
    <section
      data-testid={`admin-items-row-${entry.id}`}
      className="card"
      style={{ padding: "var(--pad-lg)", display: "grid", gap: 10 }}
    >
      <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center", fontSize: 12 }}>
        <span className="label-micro">{entry.course_id} · {entry.concept_key}</span>
        <span className="chip">{entry.format} · difficulty {entry.difficulty}</span>
        {entry.retire_pending && <span className="chip chip--err">Retire not finished — retire again</span>}
        {reasons.map((r) => (
          <span key={r} className="chip chip--err" data-testid={`admin-items-reports-${entry.id}-${r}`}>
            {REPORT_REASON_LABELS[r]} ×{entry.reports[r]}
          </span>
        ))}
        {entry.lint_flags.map((f) => (
          <span key={f} className="chip" data-testid={`admin-items-flag-${entry.id}-${f}`}>
            {LINT_FLAG_LABELS[f] ?? f}
          </span>
        ))}
      </div>
      {entry.prompt === null ? (
        <div style={{ color: "var(--text-muted)", fontSize: 13 }}>This question could not be read.</div>
      ) : (
        <div style={{ fontSize: 15, lineHeight: 1.5, whiteSpace: "pre-wrap" }}>{entry.prompt}</div>
      )}
      {entry.options && (
        <ol style={{ margin: 0, paddingLeft: 0, listStyle: "none", display: "grid", gap: 4, fontSize: 14 }}>
          {entry.options.map((o) => (
            <li key={o.letter} style={{ fontWeight: o.correct ? 600 : 400 }}>
              {o.letter}. {o.text}
              {o.correct ? " — key" : ""}
            </li>
          ))}
        </ol>
      )}
      {entry.final_answer && (
        <div style={{ fontSize: 13 }}>
          <span className="label-micro">Final answer </span>
          {entry.final_answer}
        </div>
      )}
      {entry.reference_answer && (
        <details style={{ fontSize: 13 }}>
          <summary style={{ cursor: "pointer", color: "var(--text-muted)" }}>Reference answer</summary>
          <div style={{ whiteSpace: "pre-wrap", marginTop: 6 }}>{entry.reference_answer}</div>
        </details>
      )}
      <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
        {!entry.retire_pending && (
          <button
            type="button"
            data-testid={`admin-items-approve-${entry.id}`}
            className="btn btn--sm"
            disabled={busy}
            onClick={onApprove}
          >
            Approve
          </button>
        )}
        <button
          type="button"
          data-testid={`admin-items-retire-${entry.id}`}
          className="btn btn--sm btn--danger"
          disabled={busy}
          onClick={retire.trigger}
        >
          {retire.armed ? "Click again to retire for the course" : "Retire"}
        </button>
      </div>
    </section>
  );
}

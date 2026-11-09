"use client";

/**
 * Admin review queue for learning-loop check items (spec §13 A113; GitHub
 * #695), over /api/admin/check-items. A check item is drafted by a model from
 * a classmate's upload and keyed from peer material — no instructor reviewed
 * it — so this lists every item the item-flaw linter flagged, the alignment
 * check changed (A119: a criterion dropped, a concept re-tagged), a hold
 * withdraws — "Held" items are served to no one until approved: a key hold
 * (A124: an independent solve disputed its key, or an audit found it wrong or
 * ambiguous) or a quarantine (A123: enough students reported it; nothing is
 * deleted) — or a student reported (counts by reason), worst first, with its
 * text (decrypted by the server for this page only) and two actions: Approve
 * (reviewed, OK — it leaves the queue until a newer report, its key is
 * confirmed and any hold lifted, so a held question is restored to students)
 * and Retire (withdrawn for the whole course and never drafted again, and
 * every student's results on it are voided and their mastery recomputed —
 * A123; two clicks). Reports alone never delete a question. An item whose
 * retire did not finish is listed first, then the held ones.
 *
 * The "Key audit" tab (spec §13 A124) draws a stratified sample of one
 * course's stored keys (format × difficulty × concept) for staff to judge
 * correct / wrong / ambiguous, and shows the course's key-error rate with its
 * Wilson 95% interval. "Wrong" or "ambiguous" holds the item; "correct"
 * confirms its key.
 *
 * Item statistics (spec §13 A131): name a course and the queue shows, under
 * each of its questions, the classical item analysis of students' first
 * unassisted attempts — n, the share right (with its Wilson 95% interval) and
 * the item–rest discrimination — and a "Flagged by data" view lists the
 * course's questions the numbers flag (too easy, too hard, low or negative
 * discrimination), queued or not, with the same Approve / Retire. A flag asks
 * staff to look; nothing is written to the question.
 */

import React from "react";
import { TopBar } from "../TopBar";
import { useToast } from "../ToastProvider";
import { useUser } from "@/context/UserContext";
import { useConfirm } from "@/lib/useConfirm";
import { humanizeError } from "@/lib/errorMessage";
import {
  adminApproveCheckItem,
  adminAuditCheckItem,
  adminCheckItemAuditSample,
  adminCheckItemQueue,
  adminCheckItemStats,
  adminRetireCheckItem,
  type AdminAuditItem,
  type AdminAuditSample,
  type AdminCheckItemEntry,
  type AdminCheckItemQueue,
  type AdminCheckItemText,
  type AdminItemStatsReport,
  type AuditCounts,
  type CheckItemAuditVerdict,
  type CheckItemKeyStatus,
  type CheckItemLintFlag,
  type ItemStats,
  type ItemStatsFlag,
  type LoopReportReason,
} from "@/lib/api";

export const LINT_FLAG_LABELS: Record<CheckItemLintFlag, string> = {
  correct_longest: "Key is the longest option",
  correct_repeats_stem: "Key repeats the question's words",
  all_or_none_of_above: "All / none of the above",
  duplicate_options: "Duplicate options",
  negative_stem: "Negatively worded",
  // spec §13 A119: what the alignment check changed before the item was stored
  rubric_unasked_dropped: "Criteria the question never asks for were dropped",
  concept_retagged: "Moved to the concept it tests",
  // spec §13 A124: why a key is held (or was, before it was confirmed)
  key_disputed: "An independent solve gave a different answer",
  key_unsolved: "An independent solve found the passages don't settle it",
  key_audit_wrong: "An audit found the key wrong",
  key_audit_ambiguous: "An audit found the question ambiguous",
  // spec §13 A123: why staff hold it (the database sets these from the decision)
  reports_threshold: "Quarantined by student reports",
  staff_retired: "Retired — waiting to be removed",
  // spec §13 A128: provenance, not a flaw (and no hold) — its upload failed to index
  unsourced: "Drafted from the upload's raw text (indexing failed): no source passages",
};

export const REPORT_REASON_LABELS: Record<LoopReportReason, string> = {
  wrong_answer: "Wrong answer",
  unclear: "Unclear",
  not_from_my_course: "Not from my course",
};

export const KEY_STATUS_LABELS: Record<CheckItemKeyStatus, string> = {
  verified: "Key verified",
  held: "Key held",
  unverified: "Key unverified",
};

export const VERDICT_LABELS: Record<CheckItemAuditVerdict, string> = {
  correct: "Key correct",
  wrong: "Key wrong",
  ambiguous: "Ambiguous",
};

/** The ASCII unit separator a multi-concept item's concept_key joins its
 *  components with (backend learning/multi_concept.py SEP). */
const COMPONENT_SEP = "\u001f";

/** What an item is filed under, for staff: a concept, or — a multi-concept
 *  item (spec §13 A141) — "apex + prerequisite(s)", from its components when
 *  the row names them, else from its key. */
export function conceptLabel(conceptKey: string, components?: string[]): string {
  const parts = components?.length ? components : conceptKey.split(COMPONENT_SEP);
  return parts.length > 1 ? `Combines ${parts.join(" + ")}` : conceptKey;
}

// spec §13 A131: what the numbers flag (each only from `min_n` students)
export const ITEM_STATS_FLAG_LABELS: Record<ItemStatsFlag, string> = {
  too_easy: "Too easy: almost everyone gets it right first time",
  too_hard: "Too hard: few get it right first time — check the key",
  low_discrimination: "Low discrimination: doesn't separate stronger from weaker students",
  negative_discrimination: "Negative discrimination: stronger students get it wrong more often — check the key",
};

const REASONS = Object.keys(REPORT_REASON_LABELS) as LoopReportReason[];
const VERDICTS = Object.keys(VERDICT_LABELS) as CheckItemAuditVerdict[];

type View = "queue" | "audit";
const VIEWS: { value: View; label: string }[] = [
  { value: "queue", label: "Review queue" },
  { value: "audit", label: "Key audit" },
];

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
  return <ReviewBody />;
}

function ReviewBody() {
  const [view, setView] = React.useState<View>("queue");
  return (
    <div>
      <TopBar
        breadcrumb="Admin"
        title="Check-item review"
        subtitle="Learning-loop questions the linter flagged, a key check held or students reported"
        actions={<span className="chip chip--err">Staff only</span>}
      />
      <div role="tablist" style={{ display: "flex", gap: 4, padding: "0 32px", borderBottom: "1px solid var(--border)" }}>
        {VIEWS.map((v) => (
          <button
            key={v.value}
            type="button"
            data-testid={`admin-items-tab-${v.value}`}
            role="tab"
            aria-selected={view === v.value}
            onClick={() => setView(v.value)}
            style={{
              padding: "10px 16px", fontSize: 13, fontWeight: view === v.value ? 600 : 500,
              color: view === v.value ? "var(--text)" : "var(--text-dim)",
              borderBottom: `2px solid ${view === v.value ? "var(--accent)" : "transparent"}`,
              marginBottom: -1,
            }}
          >
            {v.label}
          </button>
        ))}
      </div>
      {view === "queue" ? <QueueBody /> : <AuditBody />}
    </div>
  );
}

type QueueFilter = "queue" | "data";

function QueueBody() {
  const toast = useToast();
  const [queue, setQueue] = React.useState<AdminCheckItemQueue | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const [busyId, setBusyId] = React.useState<string | null>(null);
  // spec §13 A131: one course's item statistics, read on demand (a journal scan)
  const [statsCourse, setStatsCourse] = React.useState("");
  const [stats, setStats] = React.useState<AdminItemStatsReport | null>(null);
  const [statsError, setStatsError] = React.useState<string | null>(null);
  const [statsLoading, setStatsLoading] = React.useState(false);
  const [filter, setFilter] = React.useState<QueueFilter>("queue");

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

  const loadStats = async (courseId: string) => {
    if (!courseId) return;
    setStatsLoading(true);
    try {
      setStats(await adminCheckItemStats(courseId));
      setStatsError(null);
    } catch (err) {
      setStatsError(humanizeError(err, "Couldn't load the item statistics."));
    } finally {
      setStatsLoading(false);
    }
  };

  // the course's numbers, by stored item id (a queued row of another course has none)
  const statsById = React.useMemo(() => {
    const out = new Map<string, ItemStats>();
    for (const row of stats?.items ?? []) out.set(row.id, row);
    return out;
  }, [stats]);
  const statsFor = (entry: AdminCheckItemEntry) =>
    stats && entry.course_id === stats.course_id ? statsById.get(entry.id) : undefined;

  const act = async (entry: AdminCheckItemEntry, action: "approve" | "retire") => {
    setBusyId(entry.id);
    try {
      let message: string;
      if (action === "approve") {
        const out = await adminApproveCheckItem(entry.id);
        message = out.restored
          ? "Approved — its key is confirmed, it is restored for students, and it leaves the queue."
          : "Approved — its key is confirmed and it leaves the queue.";
      } else {
        const out = await adminRetireCheckItem(entry.id);
        const students = out.students === 1 ? "1 student" : `${out.students} students`;
        message = out.voided
          ? `Retired for the whole course — results from ${students} voided.`
          : "Retired for the whole course.";
      }
      // the decision is per course question: every row of it leaves the queue
      const decided = (i: AdminCheckItemEntry) =>
        i.course_id === entry.course_id && i.question_hash === entry.question_hash;
      setQueue((q) => {
        if (!q) return q;
        const left = q.items.filter((i) => !decided(i));
        return { ...q, items: left, count: Math.max(0, q.count - (q.items.length - left.length)) };
      });
      // … and the "Flagged by data" view: decided on these numbers (A131)
      setStats((s) => {
        if (!s) return s;
        const left = s.flagged.filter((i) => !decided(i));
        return {
          ...s,
          flagged: left,
          flagged_count: Math.max(0, s.flagged_count - (s.flagged.length - left.length)),
        };
      });
      toast.success(message);
    } catch (err) {
      toast.error(humanizeError(err, action === "approve" ? "Couldn't approve it." : "Couldn't retire it."));
    } finally {
      setBusyId(null);
    }
  };

  const courseId = statsCourse.trim();
  const showData = filter === "data" && stats !== null;
  return (
    <div data-testid="admin-items" style={{ padding: "24px 32px", display: "grid", gap: 16, maxWidth: 960 }}>
      <form
        aria-label="Item statistics"
        style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}
        onSubmit={(e) => { e.preventDefault(); void loadStats(courseId); }}
      >
        <input
          data-testid="admin-items-stats-course"
          aria-label="Course id for item statistics"
          placeholder="Course id for item statistics"
          value={statsCourse}
          onChange={(e) => setStatsCourse(e.target.value)}
          style={{
            flex: 1, maxWidth: 320, padding: "7px 12px",
            border: "1px solid var(--border)", borderRadius: "var(--r-sm)",
            fontSize: 13, background: "var(--bg-input)",
          }}
        />
        <button
          type="submit"
          data-testid="admin-items-stats-load"
          className="btn btn--sm"
          disabled={!courseId || statsLoading}
        >
          {statsLoading ? "Loading…" : "Show item statistics"}
        </button>
      </form>
      {statsError && (
        <div role="alert" data-testid="admin-items-stats-error" style={{ color: "var(--text-muted)", fontSize: 13 }}>
          {statsError}
        </div>
      )}
      {stats && (
        <>
          <div data-testid="admin-items-stats-summary" style={{ color: "var(--text-muted)", fontSize: 13 }}>
            Item statistics for {stats.course_id}: each question&apos;s students&apos; first unassisted
            attempts, from {stats.rows_scanned} graded answer{stats.rows_scanned === 1 ? "" : "s"}. A
            question is flagged only from {stats.min_n} students; a flag asks you to look — nothing is
            changed until you approve or retire it.
            {stats.truncated ? " The read hit its limit, so the newest answers are not counted." : ""}
          </div>
          <div role="group" aria-label="Which questions to show" style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
            <button
              type="button"
              data-testid="admin-items-filter-queue"
              className={filter === "queue" ? "btn btn--sm btn--primary" : "btn btn--sm"}
              aria-pressed={filter === "queue"}
              onClick={() => setFilter("queue")}
            >
              Review queue
            </button>
            <button
              type="button"
              data-testid="admin-items-filter-data"
              className={filter === "data" ? "btn btn--sm btn--primary" : "btn btn--sm"}
              aria-pressed={filter === "data"}
              onClick={() => setFilter("data")}
            >
              Flagged by data ({stats.flagged_count})
            </button>
          </div>
        </>
      )}
      {showData ? (
        stats.flagged.length === 0 && stats.flagged_count > 0 ? (
          // every question of the page was decided; more are flagged beyond it
          <div data-testid="admin-items-data-more" style={{ display: "flex", alignItems: "center", gap: 12, color: "var(--text-muted)", fontSize: 13 }}>
            <span>{stats.flagged_count} more flagged — load the statistics again to see them.</span>
            <button
              type="button"
              data-testid="admin-items-data-reload"
              className="btn btn--sm"
              disabled={statsLoading}
              onClick={() => void loadStats(stats.course_id)}
            >
              Load again
            </button>
          </div>
        ) : stats.flagged.length === 0 ? (
          <div data-testid="admin-items-data-empty" style={{ color: "var(--text-muted)", fontSize: 14 }}>
            The numbers flag no question in {stats.course_id}.
          </div>
        ) : (
          <>
            {stats.flagged_count > stats.flagged.length && (
              <div style={{ color: "var(--text-muted)", fontSize: 13 }}>
                Showing the first {stats.flagged.length} of {stats.flagged_count}.
              </div>
            )}
            {stats.flagged.map((entry) => (
              <QueueRow
                key={entry.id}
                entry={entry}
                stats={entry.stats}
                minN={stats.min_n}
                busy={busyId === entry.id}
                onApprove={() => void act(entry, "approve")}
                onRetire={() => void act(entry, "retire")}
              />
            ))}
          </>
        )
      ) : error && !queue ? (
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
          Nothing to review: no flagged, held or reported question is waiting.
        </div>
      ) : (
        <>
          <div data-testid="admin-items-count" style={{ color: "var(--text-muted)", fontSize: 13 }}>
            {queue.count} to review
            {queue.count > queue.items.length ? ` — showing the first ${queue.items.length}` : ""}. Reports
            from {queue.quarantine_min_reporters} different students hide a question from everyone until
            you approve or retire it. Retiring voids every student&apos;s results on it.
          </div>
          {queue.items.map((entry) => (
            <QueueRow
              key={entry.id}
              entry={entry}
              stats={statsFor(entry)}
              minN={stats?.min_n}
              busy={busyId === entry.id}
              onApprove={() => void act(entry, "approve")}
              onRetire={() => void act(entry, "retire")}
            />
          ))}
        </>
      )}
    </div>
  );
}

const pctStat = (v: number | null) => (v === null ? "—" : `${Math.round(v * 100)}%`);

/** Spec §13 A131: one question's numbers — n, the share right with its Wilson
 *  95% interval, the item–rest discrimination — and what they flag. */
function ItemStatsLine({ id, stats, minN }: { id: string; stats: ItemStats; minN?: number }) {
  return (
    <div data-testid={`admin-items-stats-${id}`} style={{ display: "grid", gap: 6, fontSize: 13 }}>
      <div style={{ color: "var(--text-muted)" }}>
        {stats.n === 0 ? (
          "No unassisted first attempt yet."
        ) : (
          <>
            {stats.n} student{stats.n === 1 ? "" : "s"}&apos; first unassisted attempt
            {stats.n === 1 ? "" : "s"}: {pctStat(stats.p_value)} right (95% CI {pctStat(stats.p_ci_low)}–
            {pctStat(stats.p_ci_high)}) · discrimination{" "}
            {stats.discrimination === null ? "—" : stats.discrimination.toFixed(2)} ({stats.discrimination_n}{" "}
            with other answers on the concept)
            {minN !== undefined && stats.flags.length === 0 && stats.n < minN
              ? ` · too few to flag (${minN} needed)`
              : ""}
          </>
        )}
      </div>
      {stats.flags.length > 0 && (
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          {stats.flags.map((f) => (
            <span key={f} className="chip chip--err" data-testid={`admin-items-data-flag-${id}-${f}`}>
              {ITEM_STATS_FLAG_LABELS[f] ?? f}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

/** The question with its key marked, the final answer, a numeric key and the reference. */
function ItemText({ item }: { item: AdminCheckItemText }) {
  return (
    <>
      {item.prompt === null ? (
        <div style={{ color: "var(--text-muted)", fontSize: 13 }}>This question could not be read.</div>
      ) : (
        <div style={{ fontSize: 15, lineHeight: 1.5, whiteSpace: "pre-wrap" }}>{item.prompt}</div>
      )}
      {item.options && (
        <ol style={{ margin: 0, paddingLeft: 0, listStyle: "none", display: "grid", gap: 4, fontSize: 14 }}>
          {item.options.map((o) => (
            <li key={o.letter} style={{ fontWeight: o.correct ? 600 : 400 }}>
              {o.letter}. {o.text}
              {o.correct ? " — key" : ""}
            </li>
          ))}
        </ol>
      )}
      {item.final_answer && (
        <div style={{ fontSize: 13 }}>
          <span className="label-micro">Final answer </span>
          {item.final_answer}
        </div>
      )}
      {item.canonical_answer && (
        <div style={{ fontSize: 13 }}>
          <span className="label-micro">Numeric key </span>
          {item.canonical_answer}
          {item.tolerance ? ` ± ${item.tolerance}` : " (exact)"}
        </div>
      )}
      {item.reference_answer && (
        <details style={{ fontSize: 13 }}>
          <summary style={{ cursor: "pointer", color: "var(--text-muted)" }}>Reference answer</summary>
          <div style={{ whiteSpace: "pre-wrap", marginTop: 6 }}>{item.reference_answer}</div>
        </details>
      )}
    </>
  );
}

function QueueRow({
  entry, stats, minN, busy, onApprove, onRetire,
}: {
  entry: AdminCheckItemEntry;
  /** spec §13 A131: the question's numbers, once its course's statistics are loaded */
  stats?: ItemStats;
  minN?: number;
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
        <span className="label-micro">{entry.course_id} · {conceptLabel(entry.concept_key, entry.components)}</span>
        <span className="chip">{entry.format} · difficulty {entry.difficulty}</span>
        {entry.retire_pending && <span className="chip chip--err">Retire not finished — retire again</span>}
        {entry.held && (
          <span className="chip chip--err" data-testid={`admin-items-held-${entry.id}`}>
            Held — served to no one until approved
          </span>
        )}
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
      <ItemText item={entry} />
      {stats && <ItemStatsLine id={entry.id} stats={stats} minN={minN} />}
      <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
        {!entry.retire_pending && (
          <button
            type="button"
            data-testid={`admin-items-approve-${entry.id}`}
            className="btn btn--sm"
            disabled={busy}
            onClick={onApprove}
          >
            {entry.held ? "Approve and restore" : "Approve"}
          </button>
        )}
        <button
          type="button"
          data-testid={`admin-items-retire-${entry.id}`}
          className="btn btn--sm btn--danger"
          disabled={busy}
          onClick={retire.trigger}
        >
          {retire.armed ? "Click again to retire and void its results" : "Retire"}
        </button>
      </div>
    </section>
  );
}

// ── the key audit (spec §13 A124) ────────────────────────────────────────────

const pct = (v: number | null) => (v === null ? "—" : `${Math.round(v * 1000) / 10}%`);

function rateLine(c: AuditCounts): string {
  const r = c.key_error;
  return (
    `${c.audited} audited · key-error rate ${pct(r.rate)} (95% CI ${pct(r.ci_low)}–${pct(r.ci_high)})` +
    ` · wrong or ambiguous ${pct(c.key_error_or_ambiguous.rate)}`
  );
}

function AuditBody() {
  const toast = useToast();
  const [course, setCourse] = React.useState("");
  const [sample, setSample] = React.useState<AdminAuditSample | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const [loading, setLoading] = React.useState(false);
  const [busyId, setBusyId] = React.useState<string | null>(null);

  const draw = React.useCallback(async (courseId: string) => {
    if (!courseId) return;
    setLoading(true);
    try {
      setSample(await adminCheckItemAuditSample(courseId));
      setError(null);
    } catch (err) {
      setError(humanizeError(err, "Couldn't draw the audit sample."));
    } finally {
      setLoading(false);
    }
  }, []);

  const judge = async (item: AdminAuditItem, verdict: CheckItemAuditVerdict) => {
    setBusyId(item.id);
    try {
      await adminAuditCheckItem(item.id, verdict);
      // the same seed draws the same sample: re-read it for the new summary
      await draw(item.course_id);
      toast.success(verdict === "correct" ? "Recorded — its key is confirmed." : "Recorded — it is held for review.");
    } catch (err) {
      toast.error(humanizeError(err, "Couldn't record the verdict."));
    } finally {
      setBusyId(null);
    }
  };

  const courseId = course.trim();
  return (
    <div data-testid="admin-audit" style={{ padding: "24px 32px", display: "grid", gap: 16, maxWidth: 960 }}>
      <form
        style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}
        onSubmit={(e) => { e.preventDefault(); void draw(courseId); }}
      >
        <input
          data-testid="admin-audit-course"
          aria-label="Course id"
          placeholder="Course id"
          value={course}
          onChange={(e) => setCourse(e.target.value)}
          style={{
            flex: 1, maxWidth: 320, padding: "7px 12px",
            border: "1px solid var(--border)", borderRadius: "var(--r-sm)",
            fontSize: 13, background: "var(--bg-input)",
          }}
        />
        <button type="submit" data-testid="admin-audit-draw" className="btn btn--sm" disabled={!courseId || loading}>
          Draw sample
        </button>
      </form>
      {error ? (
        <div role="alert" style={{ display: "flex", alignItems: "center", gap: 12, color: "var(--text-muted)", fontSize: 13 }}>
          <span>{error}</span>
          <button type="button" data-testid="admin-audit-retry" className="btn btn--sm" onClick={() => void draw(courseId)}>
            Try again
          </button>
        </div>
      ) : !sample ? (
        <div style={{ color: "var(--text-muted)", fontSize: 13 }}>
          {loading
            ? "Loading…"
            : "Name a course to draw a sample of its stored keys, spread over formats, difficulties and concepts."}
        </div>
      ) : (
        <>
          <div data-testid="admin-audit-summary" style={{ display: "grid", gap: 4, fontSize: 13 }}>
            <div>{rateLine(sample.summary)}</div>
            <div style={{ color: "var(--text-muted)" }}>
              {sample.items.length} of {sample.population} stored question{sample.population === 1 ? "" : "s"} sampled.
              {" "}Verified by the solve: {pct(sample.summary.by_key_status.verified.key_error.rate)} wrong
              {" "}({sample.summary.by_key_status.verified.audited} audited).
            </div>
          </div>
          {sample.items.length === 0 ? (
            <div data-testid="admin-audit-empty" style={{ color: "var(--text-muted)", fontSize: 14 }}>
              This course has no stored questions to audit.
            </div>
          ) : (
            sample.items.map((item) => (
              <AuditRow
                key={item.id}
                item={item}
                busy={busyId === item.id}
                onJudge={(v) => void judge(item, v)}
              />
            ))
          )}
        </>
      )}
    </div>
  );
}

function AuditRow({
  item, busy, onJudge,
}: {
  item: AdminAuditItem;
  busy: boolean;
  onJudge: (verdict: CheckItemAuditVerdict) => void;
}) {
  return (
    <section
      data-testid={`admin-audit-row-${item.id}`}
      className="card"
      style={{ padding: "var(--pad-lg)", display: "grid", gap: 10 }}
    >
      <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center", fontSize: 12 }}>
        <span className="label-micro">{conceptLabel(item.concept_key)}</span>
        <span className="chip">{item.format} · difficulty {item.difficulty}</span>
        <span
          className={item.key_status === "held" ? "chip chip--err" : "chip"}
          data-testid={`admin-audit-status-${item.id}`}
        >
          {KEY_STATUS_LABELS[item.key_status]}
        </span>
      </div>
      <ItemText item={item} />
      <div role="group" aria-label="Verdict on the key" style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
        {VERDICTS.map((v) => (
          <button
            key={v}
            type="button"
            data-testid={`admin-audit-${v}-${item.id}`}
            className={item.verdict === v ? "btn btn--sm btn--primary" : "btn btn--sm"}
            aria-pressed={item.verdict === v}
            disabled={busy}
            onClick={() => onJudge(v)}
          >
            {VERDICT_LABELS[v]}
          </button>
        ))}
      </div>
    </section>
  );
}

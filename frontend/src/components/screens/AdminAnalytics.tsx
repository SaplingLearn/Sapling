"use client";

/**
 * Admin analytics dashboard (#121 data layer + #122 charts) over
 * /api/admin/analytics (usage summary, per-user rollup, LLM cost, errors).
 * One date range drives every panel; each panel owns its loading/error/empty
 * state so a single failed query never blanks the page. Charts render from
 * the ?bucket=day series via the lazy-loaded AnalyticsCharts primitives —
 * cost AND tokens over time, absolute errors plus the error RATE (errors ÷
 * events, joined across panels) — with the #121 raw tables kept as per-panel
 * "View data" fallbacks and every day-series chart mirrored by its own
 * "View data" table (the hover tooltip alone has no keyboard path).
 */

import React from "react";
import dynamic from "next/dynamic";
import Link from "next/link";
import { TopBar } from "../TopBar";
import { useToast } from "../ToastProvider";
import { useUser } from "@/context/UserContext";
import { errorRateSeries, formatCompactCount, zeroFillDays, type DayPointValue } from "@/lib/daySeries";

// Chart components load lazily (the #122 bundle-discipline checkbox). The
// pure helper imports statically from lib/daySeries — its own JSX-free
// module, so no synchronous edge pulls AnalyticsCharts into the main chunk
// (a static import from the SAME module would defeat dynamic(); PR #479
// review).
const DayLineChart = dynamic(() => import("../AnalyticsCharts").then((m) => m.DayLineChart), {
  ssr: false,
  loading: () => null,
});
const CategoryBars = dynamic(() => import("../AnalyticsCharts").then((m) => m.CategoryBars), {
  ssr: false,
  loading: () => null,
});
import {
  presetRange,
  useErrorsFeed,
  useLearningLoopKpis,
  useLlmCost,
  useUsageByUser,
  useUsageSummary,
  type AnalyticsQuery,
  type AnalyticsRangeValue,
} from "@/lib/useAdminAnalytics";
import type {
  CostDayPoint,
  LearningLoopKpisData,
  LlmCostGroupBy,
  LoopCalibrationReport,
  LoopGainSummary,
} from "@/lib/types";

const PRESETS = [
  { days: 7, label: "7d" },
  { days: 30, label: "30d" },
  { days: 90, label: "90d" },
] as const;

const GROUPS: LlmCostGroupBy[] = ["feature", "user", "model"];

const th: React.CSSProperties = {
  textAlign: "left", fontSize: 11, textTransform: "uppercase", letterSpacing: "0.08em",
  color: "var(--text-muted)", padding: "4px 8px",
};
const td: React.CSSProperties = {
  fontSize: 13, padding: "6px 8px", borderTop: "1px solid var(--border)",
};
const tdNum: React.CSSProperties = { ...td, textAlign: "right", fontVariantNumeric: "tabular-nums" };
// Panel tables keep a minWidth so columns stay readable; this wrapper lets
// narrow viewports scroll the table instead of overflowing the page.
const scrollX: React.CSSProperties = { overflowX: "auto" };
// Tiny nonzero rates floor at "<0.1%" so the tooltip/table never reads as
// "no errors" when errors exist.
const formatPct = (v: number) => (v > 0 && v < 0.1 ? "<0.1%" : `${Number(v.toFixed(1))}%`);

function TruncatedBadge() {
  // Copy stays meaning-neutral: on the aggregation panels `truncated` means
  // the visible aggregates are partial; on the errors panel it refers to the
  // (bucket=day) series scan only — the feed and total stay exact.
  return (
    <span className="chip chip--err" title="The range was too large for a full scan — some of this panel's data is partial.">
      Truncated — partial data
    </span>
  );
}

function Stat({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div>
      <div className="label-micro">{label}</div>
      <div style={{ fontSize: 24, fontWeight: 600 }}>{value}</div>
    </div>
  );
}

/** "View data" table twin for the day-series charts (#122 a11y): the chart
 * tooltip is pointer-hover only, so every plotted day/value pair also needs a
 * keyboard/screen-reader path. Rows follow the first non-empty series' dates
 * (callers zero-fill every series over the same range, so domains align);
 * a column with no value for a date renders an em dash. */
function DaySeriesTable({ label, columns }: {
  label: string;
  columns: { label: string; points: DayPointValue[]; format?: (v: number) => string }[];
}) {
  const dates = columns.find((c) => c.points.length)?.points.map((p) => p.date) ?? [];
  if (dates.length === 0) return null;
  const byDate = columns.map((c) => new Map(c.points.map((p) => [p.date, p.value])));
  return (
    <details style={{ marginTop: 12 }}>
      <summary style={{ fontSize: 12, color: "var(--text-muted)", cursor: "pointer" }}>View data: {label}</summary>
      <div style={scrollX}>
        <table style={{ borderCollapse: "collapse", minWidth: 280, marginTop: 8 }}>
          <thead>
            <tr>
              <th style={th}>Date</th>
              {columns.map((c) => (
                <th key={c.label} style={{ ...th, textAlign: "right" }}>{c.label}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {dates.map((date) => (
              <tr key={date}>
                <td style={td}>{date}</td>
                {columns.map((c, i) => {
                  const value = byDate[i].get(date);
                  return (
                    <td key={c.label} style={tdNum}>
                      {value == null ? "—" : (c.format ?? String)(value)}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </details>
  );
}

function Panel<T>({ title, query, testid, children }: {
  title: string;
  query: AnalyticsQuery<T>;
  testid: string;
  children: (data: T) => React.ReactNode;
}) {
  return (
    <section className="card" style={{ padding: "var(--pad-lg)" }}>
      <h2 className="h-serif" style={{ fontSize: 18, marginBottom: 12 }}>{title}</h2>
      {query.error && !query.data ? (
        <div role="alert" style={{ display: "flex", alignItems: "center", gap: 12, color: "var(--text-muted)", fontSize: 13 }}>
          <span>{query.error}</span>
          <button data-testid={`${testid}-retry`} className="btn btn--sm" onClick={query.reload}>
            Try again
          </button>
        </div>
      ) : !query.data ? (
        <div style={{ color: "var(--text-muted)", fontSize: 13 }}>Loading…</div>
      ) : (
        children(query.data)
      )}
    </section>
  );
}

const fmtRate = (v: number | null) => (v == null ? "—" : formatPct(v * 100));
const fmtNum = (v: number | null, digits = 3) => (v == null ? "—" : v.toFixed(digits));

/** A §10 gate: pass / fail, or "inconclusive" (null) — never a silent pass. */
function GateChip({ label, ok, testid }: { label: string; ok: boolean | null; testid: string }) {
  const state = ok == null ? "inconclusive" : ok ? "pass" : "fail";
  return (
    <span data-testid={testid} data-state={state} className={`chip ${ok === false ? "chip--err" : ""}`}
      title={ok == null ? "No step carries the signal yet in this range." : undefined}>
      {label}: {state}
    </span>
  );
}

/** BKT's predicted P(correct) against what students actually did unaided
 *  (spec §13 A110). A well-calibrated model's 0.8 predictions come true ~80%
 *  of the time; ECE is the bin-weighted gap. */
function CalibrationTable({ title, report, testid }: { title: string; report: LoopCalibrationReport; testid: string }) {
  return (
    <div data-testid={testid}>
      <div className="label-micro" style={{ marginBottom: 6 }}>{title}</div>
      {report.n === 0 ? (
        <div style={{ color: "var(--text-muted)", fontSize: 13 }}>No independent observations in this range.</div>
      ) : (
        <>
          <div style={{ display: "flex", gap: 24, flexWrap: "wrap", marginBottom: 8 }}>
            <Stat label="Observations" value={report.n} />
            <Stat label="Predicted" value={fmtRate(report.mean_predicted)} />
            <Stat label="Observed" value={fmtRate(report.observed_rate)} />
            <Stat label="Brier" value={fmtNum(report.brier)} />
            <Stat label="ECE" value={fmtNum(report.ece)} />
          </div>
          <div style={scrollX}>
            <table style={{ borderCollapse: "collapse", minWidth: 360 }}>
              <thead>
                <tr>
                  <th style={th}>Predicted P(correct)</th>
                  <th style={{ ...th, textAlign: "right" }}>n</th>
                  <th style={{ ...th, textAlign: "right" }}>Mean predicted</th>
                  <th style={{ ...th, textAlign: "right" }}>Observed</th>
                </tr>
              </thead>
              <tbody>
                {report.bins.map(b => (
                  <tr key={`${b.lo}-${b.hi}`}>
                    <td style={td}>{`${b.lo.toFixed(1)}–${b.hi.toFixed(1)}`}</td>
                    <td style={tdNum}>{b.n}</td>
                    <td style={tdNum}>{fmtRate(b.mean_predicted)}</td>
                    <td style={tdNum}>{fmtRate(b.observed)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  );
}

/** A paired change in percentage points (post − pre), signed; "—" when n = 0. */
const fmtPp = (v: number | null) => (v == null ? "—" : `${v > 0 ? "+" : ""}${(v * 100).toFixed(1)} pp`);

function GainRow({ testid, label, s, posttests, excludedRetired }: {
  testid: string;
  label: string;
  s: LoopGainSummary;
  posttests?: number;
  excludedRetired?: number;
}) {
  return (
    <tr data-testid={testid}>
      <td style={td}>{label}</td>
      <td style={tdNum}>{posttests ?? "—"}</td>
      <td style={tdNum} data-testid={excludedRetired == null ? undefined : `${testid}-excluded`}>
        {excludedRetired ?? "—"}
      </td>
      <td style={tdNum}>{s.n}</td>
      <td style={tdNum}>{fmtRate(s.pre_correct_rate)}</td>
      <td style={tdNum}>{fmtRate(s.post_correct_rate)}</td>
      <td style={tdNum}>{fmtPp(s.paired_difference)}</td>
      <td style={tdNum}>{`${s.improved} / ${s.same} / ${s.worse}`}</td>
    </tr>
  );
}

/** Pre/post learning gain per fixed post-test window (spec §13 A112): each
 *  concept's unaided probe pretest against its unaided delayed post-test, with
 *  the "no practice for a while before the post-test" stratum under each
 *  window. Observed answers only — never the mastery estimate. */
function LearningGainTable({ gain }: { gain: LearningLoopKpisData["learning_gain"] }) {
  // an outcome excluded for a retired item still shows the table: the drop stays visible
  if (!gain.windows.some(w => w.posttests > 0 || w.excluded_retired > 0)) {
    return (
      <div data-testid="admin-loop-gain" style={{ color: "var(--text-muted)", fontSize: 13 }}>
        No unaided post-test outcomes in this range.
      </div>
    );
  }
  return (
    <div data-testid="admin-loop-gain" style={scrollX}>
      <table style={{ borderCollapse: "collapse", minWidth: 560 }}>
        <thead>
          <tr>
            <th style={th}>Window</th>
            <th style={{ ...th, textAlign: "right" }}>Post-tests</th>
            <th style={{ ...th, textAlign: "right" }}>Excluded: item retired</th>
            <th style={{ ...th, textAlign: "right" }}>Pairs</th>
            <th style={{ ...th, textAlign: "right" }}>Pre-test correct</th>
            <th style={{ ...th, textAlign: "right" }}>Post-test correct</th>
            <th style={{ ...th, textAlign: "right" }}>Paired change</th>
            <th style={{ ...th, textAlign: "right" }}>Improved / same / worse</th>
          </tr>
        </thead>
        <tbody>
          {gain.windows.map(w => (
            <React.Fragment key={w.window_days}>
              <GainRow
                testid={`admin-loop-gain-${w.window_days}`}
                label={`${w.window_days} days`}
                s={w}
                posttests={w.posttests}
                excludedRetired={w.excluded_retired}
              />
              <GainRow
                testid={`admin-loop-gain-${w.window_days}-delayed`}
                label={`↳ no practice in the ${gain.delayed_min_days} days before`}
                s={w.delayed}
              />
            </React.Fragment>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function LearningLoopPanelBody({ d }: { d: LearningLoopKpisData }) {
  return (
    <>
      {d.truncated && <div style={{ marginBottom: 8 }}><TruncatedBadge /></div>}
      <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 16 }}>
        <GateChip label="Zero served reveals" ok={d.gates.zero_leaks} testid="admin-loop-gate-leaks" />
        <GateChip label="Ceiling compliance ≥ 95%" ok={d.gates.ceiling_compliance_ok} testid="admin-loop-gate-ceiling" />
        <GateChip label="Earnest-revise ≤ 5%" ok={d.gates.earnest_revise_ok} testid="admin-loop-gate-earnest" />
      </div>
      <div style={{ display: "flex", gap: 24, flexWrap: "wrap", marginBottom: 16 }}>
        <Stat label="Graded steps" value={d.steps_total} />
        <Stat label="In-band share" value={fmtRate(d.in_band_share)} />
        <Stat label="Unassisted next session" value={fmtRate(d.unassisted_next_session.rate)} />
        <Stat label="Ceiling compliance" value={fmtRate(d.ceiling_compliance.rate)} />
        <Stat label="Served reveals" value={d.served_reveals} />
      </div>
      <h3 className="h-serif" style={{ fontSize: 15, margin: "8px 0" }}>Are the mastery estimates right?</h3>
      <p style={{ color: "var(--text-muted)", fontSize: 13, margin: "0 0 12px" }}>
        BKT&apos;s predicted chance of a correct unaided answer, against what students actually did.
        The delayed post-test (fresh item, no tutor, at fixed follow-up windows) is the cleanest check.
      </p>
      <div style={{ display: "grid", gap: 16 }}>
        <CalibrationTable title="Delayed post-test" report={d.calibration.posttest} testid="admin-loop-calibration-posttest" />
        <CalibrationTable title="All independent evidence" report={d.calibration.all} testid="admin-loop-calibration-all" />
      </div>
      {/* spec §13 A123: answers to a question staff retired are void evidence */}
      {d.calibration.excluded_void > 0 && (
        <p data-testid="admin-loop-calibration-void" style={{ color: "var(--text-muted)", fontSize: 13, margin: "8px 0 0" }}>
          {d.calibration.excluded_void} answer{d.calibration.excluded_void === 1 ? "" : "s"} to retired
          questions left out (their results were voided).
        </p>
      )}
      <h3 className="h-serif" style={{ fontSize: 15, margin: "16px 0 8px" }}>Did students learn?</h3>
      <p style={{ color: "var(--text-muted)", fontSize: 13, margin: "0 0 12px" }}>
        Each concept&apos;s first unaided probe answer (the pretest) against its unaided delayed post-test,
        at fixed windows after the concept was first graded. Answers only, never the mastery estimate.
        An answer to a question later retired as broken is left out and counted under &ldquo;Excluded&rdquo;.
      </p>
      <LearningGainTable gain={d.learning_gain} />
      {/* spec §13 A113: the items themselves — flagged by the linter or reported by students */}
      <p style={{ color: "var(--text-muted)", fontSize: 13, margin: "16px 0 0" }}>
        Are the questions valid?{" "}
        <Link data-testid="admin-loop-items-link" href="/admin/check-items" style={{ color: "var(--accent)" }}>
          Review flagged and reported check items
        </Link>
      </p>
    </>
  );
}

export function AdminAnalytics() {
  // The gate lives OUTSIDE the hook-owning body: hooks fire their fetches on
  // mount, and a non-admin visit must not fire four requests that 403 (each
  // minting an auth.permission_denied audit event on the backend).
  const { isAdmin } = useUser();
  if (!isAdmin) {
    return (
      <div>
        <TopBar breadcrumb="Admin" title="Analytics" subtitle="Staff only" />
        <div style={{ padding: 60, textAlign: "center", color: "var(--text-muted)" }}>
          You don&apos;t have admin access.
        </div>
      </div>
    );
  }
  return <AnalyticsBody />;
}

function AnalyticsBody() {
  const [range, setRange] = React.useState<AnalyticsRangeValue>(() => presetRange(30));
  const [groupBy, setGroupBy] = React.useState<LlmCostGroupBy>("feature");
  const toast = useToast();
  // Failed BACKGROUND reloads keep the loaded view and toast (#463 convention).
  const onBackgroundError = React.useCallback(
    (message: string) => toast.error(message),
    [toast],
  );

  const summary = useUsageSummary(range, { bucket: "day", onBackgroundError });
  const byUser = useUsageByUser(range, { onBackgroundError });
  const cost = useLlmCost(range, { groupBy, bucket: "day", onBackgroundError });
  const errs = useErrorsFeed(range, { bucket: "day", onBackgroundError });
  const loop = useLearningLoopKpis(range, { onBackgroundError });

  // Users-table sort: null = keep the server order (cost desc, then events).
  const [userSort, setUserSort] = React.useState<{
    key: "events" | "cost" | "tokens" | null;
    desc: boolean;
  }>({ key: null, desc: true });
  const toggleUserSort = (key: "events" | "cost" | "tokens") =>
    setUserSort((s) => (s.key === key ? { key, desc: !s.desc } : { key, desc: true }));

  const setCustom = (edge: "from" | "to", day: string) => {
    if (!day) return;
    setRange((r) => {
      const next = {
        ...r,
        [edge]: edge === "from" ? `${day}T00:00:00.000Z` : `${day}T23:59:59.999Z`,
      };
      // Keep the window valid (the backend 422s from > to): moving one edge
      // past the other drags the other edge to the same day.
      if (next.from > next.to) {
        if (edge === "from") next.to = `${day}T23:59:59.999Z`;
        else next.from = `${day}T00:00:00.000Z`;
      }
      return next;
    });
  };

  return (
    <div>
      <TopBar
        breadcrumb="Admin"
        title="Analytics"
        subtitle="Usage, LLM cost, and errors"
        actions={<span className="chip chip--err">Staff only</span>}
      />
      <div style={{
        padding: "12px 32px", borderBottom: "1px solid var(--border)",
        display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap",
      }}>
        <span className="label-micro">Range</span>
        {PRESETS.map((p) => (
          <button
            key={p.days}
            data-testid={`admin-analytics-range-${p.label}`}
            className="btn btn--sm"
            onClick={() => setRange(presetRange(p.days))}
          >
            {p.label}
          </button>
        ))}
        <input
          data-testid="admin-analytics-range-from"
          type="date"
          aria-label="Range start"
          value={range.from.slice(0, 10)}
          max={range.to.slice(0, 10)}
          onChange={(e) => setCustom("from", e.target.value)}
          style={{ fontSize: 13 }}
        />
        <span style={{ color: "var(--text-muted)", fontSize: 13 }}>→</span>
        <input
          data-testid="admin-analytics-range-to"
          type="date"
          aria-label="Range end"
          value={range.to.slice(0, 10)}
          min={range.from.slice(0, 10)}
          onChange={(e) => setCustom("to", e.target.value)}
          style={{ fontSize: 13 }}
        />
      </div>

      <div style={{ padding: "24px 32px", display: "grid", gap: 16 }}>
        {/* Headline stats — type carries the hierarchy, no card chrome. */}
        <div style={{ display: "flex", gap: 40, flexWrap: "wrap", padding: "4px 2px" }}>
          <Stat label="Total events" value={summary.data ? summary.data.total_events : "—"} />
          <Stat label="Active users" value={summary.data ? summary.data.distinct_active_users : "—"} />
          <Stat label="LLM cost" value={cost.data ? `$${cost.data.totals.cost_usd.toFixed(2)}` : "—"} />
          <Stat label="LLM calls" value={cost.data ? cost.data.totals.calls : "—"} />
        </div>

        <Panel title="Usage" query={summary} testid="admin-analytics-usage">
          {(d) => {
            const eventPoints = d.series?.length
              ? zeroFillDays(d.series.map((p) => ({ date: p.date, value: p.count })), d.range.from, d.range.to)
              : [];
            return (
              <>
                {d.truncated && <TruncatedBadge />}
                <DayLineChart
                  points={eventPoints}
                  color="var(--brand-forest, #445D22)"
                  fillColor="var(--sap-100, #e1ecd7)"
                  ariaLabel="Events per day"
                />
                <DaySeriesTable label="events per day" columns={[{ label: "Events", points: eventPoints }]} />
                <h3 className="label-micro" style={{ margin: "16px 0 8px" }}>Top event types</h3>
                <CategoryBars
                  rows={d.by_event_type.slice(0, 8).map((r) => ({ label: r.event_type, value: r.count }))}
                  ariaLabel="Top event types"
                />
                <details style={{ marginTop: 12 }}>
                  <summary style={{ fontSize: 12, color: "var(--text-muted)", cursor: "pointer" }}>View data: event types</summary>
                  <div style={scrollX}>
                    <table style={{ borderCollapse: "collapse", minWidth: 360, marginTop: 8 }}>
                      <thead>
                        <tr><th style={th}>Event type</th><th style={{ ...th, textAlign: "right" }}>Count</th></tr>
                      </thead>
                      <tbody>
                        {d.by_event_type.map((row) => (
                          <tr key={row.event_type}>
                            <td style={td}>{row.event_type}</td>
                            <td style={tdNum}>{row.count}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </details>
              </>
            );
          }}
        </Panel>

        <Panel title="Top users" query={byUser} testid="admin-analytics-users">
          {(d) => {
            const selectors = {
              events: (u: (typeof d.users)[number]) => u.event_count,
              cost: (u: (typeof d.users)[number]) => u.llm_cost_usd,
              tokens: (u: (typeof d.users)[number]) => u.total_tokens,
            } as const;
            const users = userSort.key
              ? [...d.users].sort((a, b) => {
                  const sel = selectors[userSort.key!];
                  return userSort.desc ? sel(b) - sel(a) : sel(a) - sel(b);
                })
              : d.users;
            const sortBtn = (key: keyof typeof selectors, label: string) => (
              <button
                data-testid={`admin-analytics-users-sort-${key}`}
                onClick={() => toggleUserSort(key)}
                style={{
                  font: "inherit", color: "inherit", textTransform: "inherit", letterSpacing: "inherit",
                  fontWeight: userSort.key === key ? 700 : "inherit",
                }}
              >
                {label}{userSort.key === key ? (userSort.desc ? " ↓" : " ↑") : ""}
              </button>
            );
            return (
              <>
                {d.truncated && <TruncatedBadge />}
                {d.users.length === 0 ? (
                  <div style={{ color: "var(--text-muted)", fontSize: 13 }}>No user activity in this range.</div>
                ) : (
                  <div style={scrollX}>
                    <table style={{ borderCollapse: "collapse", minWidth: 520 }}>
                      <thead>
                        <tr>
                          <th style={th}>User</th>
                          <th style={{ ...th, textAlign: "right" }}>{sortBtn("events", "Events")}</th>
                          <th style={{ ...th, textAlign: "right" }}>{sortBtn("cost", "LLM cost")}</th>
                          <th style={{ ...th, textAlign: "right" }}>{sortBtn("tokens", "Tokens")}</th>
                        </tr>
                      </thead>
                      <tbody>
                        {users.map((u) => (
                          <tr key={u.user_id}>
                            <td style={{ ...td, fontFamily: "var(--font-mono, monospace)", fontSize: 12 }}>{u.user_id}</td>
                            <td style={tdNum}>{u.event_count}</td>
                            <td style={tdNum}>${u.llm_cost_usd.toFixed(4)}</td>
                            <td style={tdNum}>{u.total_tokens}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </>
            );
          }}
        </Panel>

        <Panel title="LLM cost" query={cost} testid="admin-analytics-cost">
          {(d) => {
            // One CostDayPoint series carries all three per-day metrics;
            // zero-fill each projection over the same range so the cost and
            // tokens charts (and the day table) share one date domain.
            const dayMetric = (pick: (p: CostDayPoint) => number) =>
              d.series?.length
                ? zeroFillDays(d.series.map((p) => ({ date: p.date, value: pick(p) })), d.range.from, d.range.to)
                : [];
            const costPoints = dayMetric((p) => p.cost_usd);
            const tokenPoints = dayMetric((p) => p.total_tokens);
            const callPoints = dayMetric((p) => p.calls);
            return (
            <>
              <div style={{ display: "flex", gap: 6, alignItems: "center", marginBottom: 12 }}>
                <span className="label-micro">Group by</span>
                {GROUPS.map((g) => (
                  <button
                    key={g}
                    data-testid={`admin-analytics-cost-group-${g}`}
                    className="btn btn--sm"
                    style={g === groupBy ? { fontWeight: 600, borderColor: "var(--accent)" } : undefined}
                    onClick={() => setGroupBy(g)}
                  >
                    {g}
                  </button>
                ))}
                {d.truncated && <TruncatedBadge />}
              </div>
              <DayLineChart
                points={costPoints}
                color="var(--brand-forest, #445D22)"
                fillColor="var(--sap-100, #e1ecd7)"
                ariaLabel="Cost per day"
                format={(v) => `$${v.toFixed(2)}`}
              />
              <h3 className="label-micro" style={{ margin: "16px 0 8px" }}>Tokens per day</h3>
              <DayLineChart
                points={tokenPoints}
                color="var(--brand-forest, #445D22)"
                fillColor="var(--sap-100, #e1ecd7)"
                ariaLabel="Tokens per day"
                format={formatCompactCount}
              />
              <DaySeriesTable
                label="cost per day"
                columns={[
                  { label: "Calls", points: callPoints },
                  { label: "Tokens", points: tokenPoints },
                  { label: "Cost", points: costPoints, format: (v) => `$${v.toFixed(2)}` },
                ]}
              />
              <h3 className="label-micro" style={{ margin: "16px 0 8px" }}>Cost by {d.group_by}</h3>
              <CategoryBars
                rows={d.rows.slice(0, 8).map((r) => ({ label: r.key || "(none)", value: r.cost_usd }))}
                ariaLabel={`Cost by ${d.group_by}`}
                format={(v) => `$${v.toFixed(4)}`}
              />
              <details style={{ marginTop: 12 }}>
                <summary style={{ fontSize: 12, color: "var(--text-muted)", cursor: "pointer" }}>View data: cost breakdown</summary>
                <div style={scrollX}>
                  <table style={{ borderCollapse: "collapse", minWidth: 560, marginTop: 8 }}>
                    <thead>
                      <tr>
                        <th style={th}>{d.group_by}</th>
                        <th style={{ ...th, textAlign: "right" }}>Calls</th>
                        <th style={{ ...th, textAlign: "right" }}>Prompt</th>
                        <th style={{ ...th, textAlign: "right" }}>Completion</th>
                        <th style={{ ...th, textAlign: "right" }}>Tokens</th>
                        <th style={{ ...th, textAlign: "right" }}>Cost</th>
                      </tr>
                    </thead>
                    <tbody>
                      {d.rows.map((row) => (
                        <tr key={row.key}>
                          <td style={td}>{row.key || "(none)"}</td>
                          <td style={tdNum}>{row.calls}</td>
                          <td style={tdNum}>{row.prompt_tokens}</td>
                          <td style={tdNum}>{row.completion_tokens}</td>
                          <td style={tdNum}>{row.total_tokens}</td>
                          <td style={tdNum}>${row.cost_usd.toFixed(4)}</td>
                        </tr>
                      ))}
                      <tr>
                        <td style={{ ...td, fontWeight: 600 }}>Total</td>
                        <td style={{ ...tdNum, fontWeight: 600 }}>{d.totals.calls}</td>
                        <td style={{ ...tdNum, fontWeight: 600 }}>{d.totals.prompt_tokens}</td>
                        <td style={{ ...tdNum, fontWeight: 600 }}>{d.totals.completion_tokens}</td>
                        <td style={{ ...tdNum, fontWeight: 600 }}>{d.totals.total_tokens}</td>
                        <td style={{ ...tdNum, fontWeight: 600 }}>${d.totals.cost_usd.toFixed(4)}</td>
                      </tr>
                    </tbody>
                  </table>
                </div>
              </details>
            </>
            );
          }}
        </Panel>

        <Panel title="Errors" query={errs} testid="admin-analytics-errors">
          {(d) => {
            // Zero-fill even when the series is empty: a no-error range is a
            // flat zero line and real 0s in the table, not "unknown" dashes.
            const errorPoints = zeroFillDays(
              (d.series ?? []).map((p) => ({ date: p.date, value: p.count })),
              d.range.from,
              d.range.to,
            );
            // The rate denominator joins ACROSS panels: the usage summary's
            // events/day series. Both series zero-fill over THIS panel's
            // range so errorRateSeries joins on an aligned date domain (days
            // with zero events report 0%, never NaN/Infinity). The summary
            // hook keeps its LAST payload while a range change reloads, so
            // guard on day-key range agreement — a stale series zero-filled
            // against the new range would fabricate an all-0% rate line.
            const summaryRange = summary.data?.range;
            const rangesAgree =
              !!summaryRange &&
              summaryRange.from.slice(0, 10) === d.range.from.slice(0, 10) &&
              summaryRange.to.slice(0, 10) === d.range.to.slice(0, 10);
            const eventPoints =
              rangesAgree && summary.data?.series?.length
                ? zeroFillDays(
                    summary.data.series.map((p) => ({ date: p.date, value: p.count })),
                    d.range.from,
                    d.range.to,
                  )
                : [];
            const ratePoints = errorRateSeries(errorPoints, eventPoints);
            return (
            <>
              {d.truncated && <TruncatedBadge />}
              <DayLineChart
                points={errorPoints}
                color="var(--err, #a83a3a)"
                ariaLabel="Errors per day"
              />
              <h3 className="label-micro" style={{ margin: "16px 0 8px" }}>Error rate</h3>
              {ratePoints.length ? (
                <>
                  {/* A truncated summary scan undercounts the denominator, so
                      the rate can overshoot — surface it on THIS chart. */}
                  {summary.data?.truncated && <TruncatedBadge />}
                  <DayLineChart
                    points={ratePoints}
                    color="var(--err, #a83a3a)"
                    ariaLabel="Error rate per day"
                    format={formatPct}
                  />
                </>
              ) : (
                <div style={{ color: "var(--text-muted)", fontSize: 13 }}>
                  {summary.error
                    ? "Couldn't load the events-per-day series, so the error rate can't be computed."
                    : summary.data && rangesAgree
                      ? "No events in this range."
                      : "Error rate appears once the usage events-per-day series loads."}
                </div>
              )}
              <DaySeriesTable
                label="errors per day"
                columns={[
                  { label: "Errors", points: errorPoints },
                  { label: "Error rate", points: ratePoints, format: formatPct },
                ]}
              />
              <div style={{ height: 12 }} />
              {d.errors.length === 0 ? (
                <div style={{ color: "var(--text-muted)", fontSize: 13 }}>No errors in this range. 🎉</div>
              ) : (
                <div style={scrollX}>
                  <table style={{ borderCollapse: "collapse", minWidth: 640 }}>
                    <thead>
                      <tr>
                        <th style={th}>Time</th>
                        <th style={th}>Type</th>
                        <th style={th}>Method</th>
                        <th style={th}>Path</th>
                        <th style={{ ...th, textAlign: "right" }}>Status</th>
                        <th style={{ ...th, textAlign: "right" }}>Duration</th>
                      </tr>
                    </thead>
                    <tbody>
                      {d.errors.map((e, i) => (
                        <tr key={e.request_id ?? `${e.created_at}-${i}`}>
                          <td style={{ ...td, whiteSpace: "nowrap" }}>{e.created_at ?? "—"}</td>
                          <td style={td}>{e.event_type}</td>
                          <td style={td}>{e.method ?? "—"}</td>
                          <td style={{ ...td, fontFamily: "var(--font-mono, monospace)", fontSize: 12 }}>{e.path ?? "—"}</td>
                          <td style={tdNum}>{e.status_code ?? "—"}</td>
                          <td style={tdNum}>{e.duration_ms != null ? `${e.duration_ms.toFixed(1)}ms` : "—"}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </>
            );
          }}
        </Panel>

        <Panel title="Learning loop" query={loop} testid="admin-analytics-learning-loop">
          {(d) => <LearningLoopPanelBody d={d} />}
        </Panel>
      </div>
    </div>
  );
}

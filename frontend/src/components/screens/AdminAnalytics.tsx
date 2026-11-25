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
import { useReducedMotion } from "framer-motion";
import Link from "next/link";
import { TopBar } from "../TopBar";
import { useToast } from "../ToastProvider";
import { HelpAbusePanel } from "./admin/HelpAbusePanel";
import { HintTrendPanel } from "./admin/HintTrendPanel";
import { LoopGates } from "./admin/LoopGates";
import { SelfExplanationPanel } from "./admin/SelfExplanationPanel";
import { MultiConceptPanel } from "./admin/MultiConceptPanel";
import { LoopCostPanel } from "./AdminLoopCost";
import { AdminReauthBanner } from "./admin/AdminReauthBanner";
import { FadeIn, StaggerBody, StaggerRow } from "./admin/adminMotion";
import { AnimatedNumber } from "./AnimatedNumber";
import t from "./admin/adminTable.module.css";
import s from "./AdminAnalytics.module.css";
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
  LoopConfidenceReport,
  LoopGainSummary,
} from "@/lib/types";

const PRESETS = [
  { days: 7, label: "7d" },
  { days: 30, label: "30d" },
  { days: 90, label: "90d" },
] as const;

const GROUPS: LlmCostGroupBy[] = ["feature", "user", "model"];

const th = t.th;
const thNum = `${t.th} ${t.num}`;
const td = t.td;
const tdNum = `${t.td} ${t.num}`;
const tdStrong = `${t.td} ${t.strong}`;
const tdNumStrong = `${t.td} ${t.num} ${t.strong}`;
const tdMono = `${t.td} ${t.mono}`;

// The chart series, as roles (AdminAnalytics.module.css defines them on the
// page from the brand and error tokens).
const SERIES = { line: "var(--series-line)", fill: "var(--series-fill)", error: "var(--series-error)" } as const;
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
      <div className={t.statValue}>{value}</div>
    </div>
  );
}

/** A figure that tweens when the range changes; "—" while there is none. */
function Num({ value, format }: { value: number | null | undefined; format?: (v: number) => string }) {
  return value == null ? <>—</> : <AnimatedNumber value={value} format={format ?? String} />;
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
    <details className={s.details}>
      <summary className={s.summary}>View data: {label}</summary>
      <div className={t.scrollX}>
        <table className={`${t.table} ${t.minDaySeries} ${s.detailsTable}`}>
          <thead>
            <tr>
              <th className={th}>Date</th>
              {columns.map((c) => (
                <th key={c.label} className={thNum}>{c.label}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {dates.map((date) => (
              <tr key={date}>
                <td className={td}>{date}</td>
                {columns.map((c, i) => {
                  const value = byDate[i].get(date);
                  return (
                    <td key={c.label} className={tdNum}>
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
    <section className={`card ${s.panel}`}>
      <h2 className={`h-serif ${s.panelTitle}`}>{title}</h2>
      {query.error && !query.data ? (
        <FadeIn key="error" role="alert" className={s.inlineAlert}>
          <span>{query.error}</span>
          <button data-testid={`${testid}-retry`} className="btn btn--sm" onClick={query.reload}>
            Try again
          </button>
        </FadeIn>
      ) : !query.data ? (
        <div className={t.muted}>Loading…</div>
      ) : (
        <FadeIn key="data">{children(query.data)}</FadeIn>
      )}
    </section>
  );
}

const fmtDollars = (v: number) => `$${v.toFixed(2)}`;
const fmtRate = (v: number | null) => (v == null ? "—" : formatPct(v * 100));
const fmtNum = (v: number | null, digits = 3) => (v == null ? "—" : v.toFixed(digits));

/** BKT's predicted P(correct) against what students actually did unaided
 *  (spec §13 A110). A well-calibrated model's 0.8 predictions come true ~80%
 *  of the time; ECE is the bin-weighted gap. */
function CalibrationTable({ title, report, testid }: { title: string; report: LoopCalibrationReport; testid: string }) {
  return (
    <div data-testid={testid}>
      <div className={`label-micro ${t.label}`}>{title}</div>
      {report.n === 0 ? (
        <div className={t.muted}>No independent observations in this range.</div>
      ) : (
        <>
          <div className={`${t.stats} ${t.statsTight}`}>
            <Stat label="Observations" value={<Num value={report.n} />} />
            <Stat label="Predicted" value={<Num value={report.mean_predicted} format={fmtRate} />} />
            <Stat label="Observed" value={<Num value={report.observed_rate} format={fmtRate} />} />
            <Stat label="Brier" value={<Num value={report.brier} format={fmtNum} />} />
            <Stat label="ECE" value={<Num value={report.ece} format={fmtNum} />} />
          </div>
          <div className={t.scrollX}>
            <table className={`${t.table} ${t.minCalibration}`}>
              <thead>
                <tr>
                  <th className={th}>Predicted P(correct)</th>
                  <th className={thNum}>n</th>
                  <th className={thNum}>Mean predicted</th>
                  <th className={thNum}>Observed</th>
                </tr>
              </thead>
              <StaggerBody>
                {report.bins.map(b => (
                  <StaggerRow key={`${b.lo}-${b.hi}`}>
                    <td className={td}>{`${b.lo.toFixed(1)}–${b.hi.toFixed(1)}`}</td>
                    <td className={tdNum}>{b.n}</td>
                    <td className={tdNum}>{fmtRate(b.mean_predicted)}</td>
                    <td className={tdNum}>{fmtRate(b.observed)}</td>
                  </StaggerRow>
                ))}
              </StaggerBody>
            </table>
          </div>
        </>
      )}
    </div>
  );
}

/** A paired change in percentage points (post − pre), signed; "—" when n = 0. */
const fmtPp = (v: number | null) => (v == null ? "—" : `${v > 0 ? "+" : ""}${(v * 100).toFixed(1)} pp`);

/** Spec §13 A127's channels and levels, in words (an unknown id is shown as is). */
const CHANNEL_LABEL: Record<string, string> = {
  free_response: "Free response",
  mc_reasoned: "Choice + reason",
  teachback_llm: "Teach-back",
  // The quiz writes every format under `mc` (spec §13 A10), and nothing else
  // writes it; its stated confidence arrives with A132.
  mc: "Quiz",
  chat_turn: "Chat turn",
};
const LEVEL_LABEL: Record<string, string> = {
  guessing: "Guessing",
  fairly_sure: "Fairly sure",
  sure: "Sure",
};

function ConfidenceRows({ id, label, report }: { id: string; label: string; report: LoopConfidenceReport }) {
  return (
    <>
      {report.levels.map((lv) => {
        const name = lv.level == null ? `Other (${fmtRate(lv.stated)})` : (LEVEL_LABEL[lv.level] ?? lv.level);
        return (
          <StaggerRow key={`${id}-${lv.level ?? lv.stated}`} data-testid={`admin-loop-confidence-${id}-${lv.level ?? "other"}`}>
            <td className={td}>{label}</td>
            <td className={td}>{name}</td>
            <td className={tdNum}>{lv.n}</td>
            <td className={tdNum}>{fmtRate(lv.stated)}</td>
            <td className={tdNum}>{fmtRate(lv.observed)}</td>
          </StaggerRow>
        );
      })}
      <StaggerRow data-testid={`admin-loop-confidence-${id}-all`}>
        <td className={td}>{label}</td>
        <td className={tdStrong}>All</td>
        <td className={tdNum}>{report.n}</td>
        <td className={tdNum}>{fmtRate(report.mean_stated)}</td>
        <td className={tdNum}>{fmtRate(report.observed_rate)}</td>
      </StaggerRow>
    </>
  );
}

/** Spec §13 A127: do students know what they know? The confidence a student
 *  stated on a check, probe, review or quiz answer ("Guessing" / "Fairly sure" /
 *  "Sure") against whether it was right, per channel — the students' own
 *  calibration, beside the model's. Overconfidence above 0: surer than right. */
function ConfidenceCalibrationTable({ data }: { data: LearningLoopKpisData["confidence_calibration"] }) {
  const all = data.all;
  return (
    <div data-testid="admin-loop-confidence">
      <div className={`label-micro ${t.label}`}>Students&apos; stated confidence</div>
      {all.n === 0 ? (
        <div className={t.muted}>No answers with a stated confidence in this range.</div>
      ) : (
        <>
          <div className={`${t.stats} ${t.statsTight}`}>
            <Stat label="Answers" value={<Num value={all.n} />} />
            <Stat label="Stated" value={<Num value={all.mean_stated} format={fmtRate} />} />
            <Stat label="Correct" value={<Num value={all.observed_rate} format={fmtRate} />} />
            <Stat label="Overconfidence" value={<Num value={all.overconfidence} format={fmtPp} />} />
            <Stat label="Brier" value={<Num value={all.brier} format={fmtNum} />} />
          </div>
          <div className={t.scrollX}>
            <table className={`${t.table} ${t.minConfidence}`}>
              <thead>
                <tr>
                  <th className={th}>Channel</th>
                  <th className={th}>Stated confidence</th>
                  <th className={thNum}>Answers</th>
                  <th className={thNum}>Stated</th>
                  <th className={thNum}>Correct</th>
                </tr>
              </thead>
              <StaggerBody>
                {data.channels.map((c) => (
                  <ConfidenceRows key={c.channel} id={c.channel} label={CHANNEL_LABEL[c.channel] ?? c.channel} report={c} />
                ))}
              </StaggerBody>
            </table>
          </div>
        </>
      )}
    </div>
  );
}

/** A126: a bootstrap interval under its estimate, in the estimate's own unit. */
function CiLine({ ci, fmt, testid }: { ci?: [number, number] | null; fmt: (v: number) => string; testid: string }) {
  if (!ci) return null;
  return (
    <div data-testid={testid} className={t.sub}>
      {`${fmt(ci[0])} to ${fmt(ci[1])}`}
    </div>
  );
}

function GainRow({ testid, label, s, posttests, excludedRetired, postCi, diffCi }: {
  testid: string;
  label: string;
  s: LoopGainSummary;
  posttests?: number;
  excludedRetired?: number;
  postCi?: [number, number] | null;
  diffCi?: [number, number] | null;
}) {
  return (
    <StaggerRow data-testid={testid}>
      <td className={td}>{label}</td>
      <td className={tdNum}>{posttests ?? "—"}</td>
      <td className={tdNum} data-testid={excludedRetired == null ? undefined : `${testid}-excluded`}>
        {excludedRetired ?? "—"}
      </td>
      <td className={tdNum}>{s.n}</td>
      <td className={tdNum}>{fmtRate(s.pre_correct_rate)}</td>
      <td className={tdNum}>
        <span>{fmtRate(s.post_correct_rate)}</span>
        <CiLine ci={postCi} fmt={(v) => fmtRate(v)} testid={`${testid}-post-ci`} />
      </td>
      <td className={tdNum}>
        <span>{fmtPp(s.paired_difference)}</span>
        <CiLine ci={diffCi} fmt={(v) => fmtPp(v)} testid={`${testid}-diff-ci`} />
      </td>
      <td className={tdNum}>{`${s.improved} / ${s.same} / ${s.worse}`}</td>
    </StaggerRow>
  );
}

const SKIP_REASON_LABEL: Record<string, string> = {
  no_items: "no items",
  exhausted: "all seen",
  reported: "only reported left",
};

/** A126: what happened to every post-test window that opened in the range —
 *  the missing outcomes, counted and never imputed. */
function FunnelTable({ funnel }: { funnel: LearningLoopKpisData["learning_gain"]["funnel"] }) {
  if (funnel == null) {
    return (
      <div data-testid="admin-loop-funnel" className={t.muted}>
        The windows that came due could not be read; the funnel is unknown for this range.
      </div>
    );
  }
  return (
    <div data-testid="admin-loop-funnel" className={t.scrollX}>
      <table className={`${t.table} ${t.minFunnel}`}>
        <thead>
          <tr>
            <th className={th}>Window</th>
            <th className={thNum}>Due</th>
            <th className={thNum}>Opened</th>
            <th className={thNum}>Answered (unaided)</th>
            <th className={thNum}>Expired</th>
            <th className={thNum}>Open now</th>
            <th className={thNum}>Skipped</th>
            <th className={thNum}>Never opened</th>
            <th className={thNum}>Window still open</th>
          </tr>
        </thead>
        <StaggerBody>
          {funnel.map(f => {
            const reasons = Object.entries(f.skip_reasons).filter(([, n]) => n > 0);
            return (
              <StaggerRow key={f.window_days} data-testid={`admin-loop-funnel-${f.window_days}`}>
                <td className={td}>{`${f.window_days} days`}</td>
                <td className={tdNum}>{f.due}</td>
                <td className={tdNum}>{f.opened}</td>
                <td className={tdNum}>
                  <span>{`${f.answered} (${f.unassisted})`}</span>
                  {/* spec §13 A123: answers to a question staff retired are void */}
                  {(f.excluded_retired ?? 0) > 0 && (
                    <div data-testid={`admin-loop-funnel-${f.window_days}-retired`} className={t.sub}>
                      {`+${f.excluded_retired} on retired questions, left out`}
                    </div>
                  )}
                </td>
                <td className={tdNum}>{f.expired}</td>
                <td className={tdNum}>{f.open}</td>
                <td className={tdNum} data-testid={`admin-loop-funnel-${f.window_days}-skipped`}>
                  <span>{f.skipped}</span>
                  {reasons.length > 0 && (
                    <div className={t.sub}>
                      {reasons.map(([r, n]) => `${SKIP_REASON_LABEL[r] ?? r}: ${n}`).join(", ")}
                    </div>
                  )}
                </td>
                <td className={tdNum}>{f.not_opened}</td>
                <td className={tdNum}>{f.still_open}</td>
              </StaggerRow>
            );
          })}
        </StaggerBody>
      </table>
    </div>
  );
}

/** A126: every window's pairs by the delay the outcome actually had. */
function DelayTable({ gain }: { gain: LearningLoopKpisData["learning_gain"] }) {
  return (
    <div data-testid="admin-loop-delay" className={t.scrollX}>
      <table className={`${t.table} ${t.minDelay}`}>
        <thead>
          <tr>
            <th className={th}>Days from first graded answer</th>
            <th className={thNum}>Post-tests</th>
            <th className={thNum}>Pairs</th>
            <th className={thNum}>Post-test correct</th>
            <th className={thNum}>Paired change</th>
          </tr>
        </thead>
        <StaggerBody>
          {gain.delay_bins.map(b => (
            <StaggerRow key={b.lo_days} data-testid={`admin-loop-delay-${b.lo_days}`}>
              <td className={td}>{b.hi_days == null ? `${b.lo_days}+` : `${b.lo_days}–${b.hi_days - 1}`}</td>
              <td className={tdNum}>{b.posttests}</td>
              <td className={tdNum}>{b.n}</td>
              <td className={tdNum}>{fmtRate(b.post_correct_rate)}</td>
              <td className={tdNum}>{fmtPp(b.paired_difference)}</td>
            </StaggerRow>
          ))}
        </StaggerBody>
      </table>
      {(gain.delay_unknown > 0 || gain.delay_out_of_range > 0) && (
        <div className={s.below}>
          {`Not binned: ${gain.delay_unknown} with no recorded anchor, ${gain.delay_out_of_range} answered before day ${gain.delay_bins[0]?.lo_days ?? 0}.`}
        </div>
      )}
    </div>
  );
}

/** Pre/post learning gain per fixed post-test window (spec §13 A112): each
 *  concept's unaided probe pretest against its unaided delayed post-test, with
 *  the "no practice for a while before the post-test" and "page hidden while
 *  answering" strata under each window, the bootstrap intervals, the actual
 *  delay and the funnel of windows that came due (A126). Observed answers
 *  only — never the mastery estimate. */
function LearningGainTable({ gain }: { gain: LearningLoopKpisData["learning_gain"] }) {
  const due = (gain.funnel ?? []).some(f => f.due > 0);
  // an outcome excluded for a retired item still shows the table: the drop stays visible
  if (!gain.windows.some(w => w.posttests > 0 || w.excluded_retired > 0)) {
    return (
      <div className={t.stack}>
        <div data-testid="admin-loop-gain" className={t.muted}>
          No unaided post-test outcomes in this range.
        </div>
        {/* A126: windows came due with no outcome — the missing data is the finding */}
        {(due || gain.funnel === null) && <FunnelTable funnel={gain.funnel} />}
      </div>
    );
  }
  return (
    <div className={t.stack}>
      <div data-testid="admin-loop-gain" className={t.scrollX}>
        <table className={`${t.table} ${t.minGain}`}>
          <thead>
            <tr>
              <th className={th}>Window</th>
              <th className={thNum}>Post-tests</th>
              <th className={thNum}>Excluded: item retired</th>
              <th className={thNum}>Pairs</th>
              <th className={thNum}>Pre-test correct</th>
              <th className={thNum}>Post-test correct</th>
              <th className={thNum}>Paired change</th>
              <th className={thNum}>Improved / same / worse</th>
            </tr>
          </thead>
          <StaggerBody>
            {gain.windows.map(w => (
              <React.Fragment key={w.window_days}>
                <GainRow
                  testid={`admin-loop-gain-${w.window_days}`}
                  label={`${w.window_days} days`}
                  s={w}
                  posttests={w.posttests}
                  excludedRetired={w.excluded_retired}
                  postCi={w.post_correct_ci}
                  diffCi={w.paired_difference_ci}
                />
                <GainRow
                  testid={`admin-loop-gain-${w.window_days}-delayed`}
                  label={`↳ no practice in the ${gain.delayed_min_days} days before`}
                  s={w.delayed}
                />
                <GainRow
                  testid={`admin-loop-gain-${w.window_days}-hidden`}
                  label="↳ page hidden while answering"
                  s={w.visibility_loss}
                />
              </React.Fragment>
            ))}
          </StaggerBody>
        </table>
      </div>
      <p className={t.small} data-testid="admin-loop-gain-ci-note">
        {`Under each rate: a ${Math.round(gain.ci.level * 100)}% interval from a ${gain.ci.resamples.toLocaleString()}-resample bootstrap over students (each student's answers resampled together; fixed seed). No interval below two students.`}
        {gain.windows.some(w => w.visibility_unreported > 0) &&
          ` ${gain.windows.reduce((n, w) => n + w.visibility_unreported, 0)} outcomes have no page-visibility record.`}
      </p>
      <FunnelTable funnel={gain.funnel} />
      <DelayTable gain={gain} />
    </div>
  );
}

const SLOT_WARNING_REASON: Record<string, string> = {
  pending_claude_eval: "its Claude eval has not passed yet",
  not_evaluated: "its quality gates were not recorded on this model",
};

/** spec §13 A128: evidence-producing model slots this API process runs outside
 *  their evaluated models, or on the model they must be independent of. A
 *  warning only — grading and tutoring run on. Nothing renders when none. */
function SlotWarnings({ warnings }: { warnings: NonNullable<LearningLoopKpisData["slot_warnings"]> }) {
  if (!warnings.length) return null;
  return (
    <FadeIn data-testid="admin-loop-slot-warnings" role="status" className={s.slotWarnings}>
      <strong>Model slot warnings</strong>
      <ul className={s.slotList}>
        {warnings.map(w => (
          <li key={`${w.kind}-${w.slot}`} data-testid={`admin-loop-slot-warning-${w.slot}`}>
            <code>{w.slot}</code> runs <code>{w.model}</code>
            {w.kind === "not_independent"
              ? <> — the same model as <code>{w.independent_of}</code>, so its verdicts are not independent ({w.rule})</>
              : <> — {SLOT_WARNING_REASON[w.reason ?? ""] ?? "outside its evaluated models"}</>}
          </li>
        ))}
      </ul>
    </FadeIn>
  );
}

export function LearningLoopPanelBody({ d }: { d: LearningLoopKpisData }) {
  return (
    <>
      <SlotWarnings warnings={d.slot_warnings ?? []} />
      {d.truncated && <div className={s.badgeRow}><TruncatedBadge /></div>}
      <LoopGates d={d} />
      <div className={`${t.stats} ${t.statsLoose}`}>
        <Stat label="Graded steps" value={<Num value={d.steps_total} />} />
        <Stat label="In-band share" value={<Num value={d.in_band_share} format={fmtRate} />} />
        <Stat label="Unassisted next session" value={<Num value={d.unassisted_next_session.rate} format={fmtRate} />} />
        <Stat label="Ceiling compliance" value={<Num value={d.ceiling_compliance.rate} format={fmtRate} />} />
        <Stat label="Served reveals" value={<Num value={d.served_reveals} />} />
      </div>
      <HintTrendPanel trend={d.htc_k_trend} />
      <h3 className={`h-serif ${t.headingTight}`}>Are the mastery estimates right?</h3>
      <p className={t.lede}>
        BKT&apos;s predicted chance of a correct unaided answer, against what students actually did.
        The delayed post-test (fresh item, no tutor, at fixed follow-up windows) is the cleanest check.
      </p>
      <div className={t.stackLoose}>
        <CalibrationTable title="Delayed post-test" report={d.calibration.posttest} testid="admin-loop-calibration-posttest" />
        <CalibrationTable title="All independent evidence" report={d.calibration.all} testid="admin-loop-calibration-all" />
      </div>
      {/* spec §13 A123: answers to a question staff retired are void evidence */}
      {d.calibration.excluded_void > 0 && (
        <p data-testid="admin-loop-calibration-void" className={t.tail}>
          {d.calibration.excluded_void} answer{d.calibration.excluded_void === 1 ? "" : "s"} to retired
          questions left out (their results were voided).
        </p>
      )}
      <h3 className={`h-serif ${t.heading}`}>Do students know what they know?</h3>
      <p className={t.lede}>
        How sure students said they were (Guessing / Fairly sure / Sure — optional, so only the answers that stated one)
        against how often those answers were right, per kind of question. A well-calibrated &ldquo;Sure&rdquo; is right
        most of the time; overconfidence is the stated confidence minus the share correct.
      </p>
      <ConfidenceCalibrationTable data={d.confidence_calibration} />
      <h3 className={`h-serif ${t.heading}`}>Did students learn?</h3>
      <p className={t.lede}>
        Each concept&apos;s first unaided probe answer (the pretest) against its unaided delayed post-test,
        at fixed windows after the concept was first graded (the last one closes too). Answers only, never
        the mastery estimate. An answer to a question later retired as broken is left out and counted under
        &ldquo;Excluded&rdquo;. The funnel below counts every window that opened in the range, answered or not.
      </p>
      <LearningGainTable gain={d.learning_gain} />
      {/* spec §13 A137: the loop's spend against that gain (absent from a pre-A137 backend) */}
      {d.cost_per_gain !== undefined && (
        <>
          <h3 className={`h-serif ${t.heading}`}>What did it cost?</h3>
          <LoopCostPanel cost={d.cost_per_gain} />
        </>
      )}
      {/* spec §13 A133: help abuse on the hint ladder (its own component) */}
      <HelpAbusePanel data={d.help_abuse} />
      {/* spec §13 A139: the self-explanation prompts — shown, replied, and the next item */}
      <SelfExplanationPanel data={d.self_explanation} />
      {/* spec §13 A141: questions that combine concepts — served and outcomes */}
      <MultiConceptPanel data={d.multi_concept} />
      {/* spec §13 A113: the items themselves — flagged by the linter or reported by students */}
      <p className={s.itemsLink}>
        Are the questions valid?{" "}
        <Link data-testid="admin-loop-items-link" href="/admin/check-items" className={s.link}>
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
        <div className={s.denied}>
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
  // A re-sort slides the users' rows to their new places, unless motion is reduced.
  const reduceMotion = Boolean(useReducedMotion());
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
    <div className={s.page}>
      <TopBar
        breadcrumb="Admin"
        title="Analytics"
        subtitle="Usage, LLM cost, and errors"
        actions={<span className="chip chip--err">Staff only</span>}
      />
      <AdminReauthBanner />
      <div className={s.rangeBar}>
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
          className={s.dateInput}
        />
        <span className={t.muted}>→</span>
        <input
          data-testid="admin-analytics-range-to"
          type="date"
          aria-label="Range end"
          value={range.to.slice(0, 10)}
          min={range.from.slice(0, 10)}
          onChange={(e) => setCustom("to", e.target.value)}
          className={s.dateInput}
        />
      </div>

      <div className={s.body}>
        {/* Headline stats — type carries the hierarchy, no card chrome. */}
        <div className={s.headline}>
          <Stat label="Total events" value={<Num value={summary.data?.total_events} />} />
          <Stat label="Active users" value={<Num value={summary.data?.distinct_active_users} />} />
          <Stat label="LLM cost" value={<Num value={cost.data?.totals.cost_usd} format={fmtDollars} />} />
          <Stat label="LLM calls" value={<Num value={cost.data?.totals.calls} />} />
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
                  color={SERIES.line}
                  fillColor={SERIES.fill}
                  ariaLabel="Events per day"
                />
                <DaySeriesTable label="events per day" columns={[{ label: "Events", points: eventPoints }]} />
                <h3 className={`label-micro ${s.chartTitle}`}>Top event types</h3>
                <CategoryBars
                  rows={d.by_event_type.slice(0, 8).map((r) => ({ label: r.event_type, value: r.count }))}
                  ariaLabel="Top event types"
                />
                <details className={s.details}>
                  <summary className={s.summary}>View data: event types</summary>
                  <div className={t.scrollX}>
                    <table className={`${t.table} ${t.minEventTypes} ${s.detailsTable}`}>
                      <thead>
                        <tr><th className={th}>Event type</th><th className={thNum}>Count</th></tr>
                      </thead>
                      <StaggerBody>
                        {d.by_event_type.map((row) => (
                          <StaggerRow key={row.event_type}>
                            <td className={td}>{row.event_type}</td>
                            <td className={tdNum}>{row.count}</td>
                          </StaggerRow>
                        ))}
                      </StaggerBody>
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
                className={userSort.key === key ? `${s.sort} ${s.sortActive}` : s.sort}
              >
                {label}{userSort.key === key ? (userSort.desc ? " ↓" : " ↑") : ""}
              </button>
            );
            return (
              <>
                {d.truncated && <TruncatedBadge />}
                {d.users.length === 0 ? (
                  <div className={t.muted}>No user activity in this range.</div>
                ) : (
                  <div className={t.scrollX}>
                    <table className={`${t.table} ${t.minUsers}`}>
                      <thead>
                        <tr>
                          <th className={th}>User</th>
                          <th className={thNum}>{sortBtn("events", "Events")}</th>
                          <th className={thNum}>{sortBtn("cost", "LLM cost")}</th>
                          <th className={thNum}>{sortBtn("tokens", "Tokens")}</th>
                        </tr>
                      </thead>
                      <StaggerBody>
                        {users.map((u) => (
                          <StaggerRow key={u.user_id} layout={reduceMotion ? false : "position"}>
                            <td className={tdMono}>{u.user_id}</td>
                            <td className={tdNum}>{u.event_count}</td>
                            <td className={tdNum}>${u.llm_cost_usd.toFixed(4)}</td>
                            <td className={tdNum}>{u.total_tokens}</td>
                          </StaggerRow>
                        ))}
                      </StaggerBody>
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
              <div className={s.groupBar}>
                <span className="label-micro">Group by</span>
                {GROUPS.map((g) => (
                  <button
                    key={g}
                    data-testid={`admin-analytics-cost-group-${g}`}
                    className={g === groupBy ? `btn btn--sm ${s.group} ${s.groupActive}` : `btn btn--sm ${s.group}`}
                    aria-pressed={g === groupBy}
                    onClick={() => setGroupBy(g)}
                  >
                    {g}
                  </button>
                ))}
                {d.truncated && <TruncatedBadge />}
              </div>
              <DayLineChart
                points={costPoints}
                color={SERIES.line}
                fillColor={SERIES.fill}
                ariaLabel="Cost per day"
                format={(v) => `$${v.toFixed(2)}`}
              />
              <h3 className={`label-micro ${s.chartTitle}`}>Tokens per day</h3>
              <DayLineChart
                points={tokenPoints}
                color={SERIES.line}
                fillColor={SERIES.fill}
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
              <h3 className={`label-micro ${s.chartTitle}`}>Cost by {d.group_by}</h3>
              <CategoryBars
                rows={d.rows.slice(0, 8).map((r) => ({ label: r.key || "(none)", value: r.cost_usd }))}
                ariaLabel={`Cost by ${d.group_by}`}
                format={(v) => `$${v.toFixed(4)}`}
              />
              <details className={s.details}>
                <summary className={s.summary}>View data: cost breakdown</summary>
                <div className={t.scrollX}>
                  <table className={`${t.table} ${t.minCostRows} ${s.detailsTable}`}>
                    <thead>
                      <tr>
                        <th className={th}>{d.group_by}</th>
                        <th className={thNum}>Calls</th>
                        <th className={thNum}>Prompt</th>
                        <th className={thNum}>Completion</th>
                        <th className={thNum}>Tokens</th>
                        <th className={thNum}>Cost</th>
                      </tr>
                    </thead>
                    <StaggerBody>
                      {d.rows.map((row) => (
                        <StaggerRow key={row.key}>
                          <td className={td}>{row.key || "(none)"}</td>
                          <td className={tdNum}>{row.calls}</td>
                          <td className={tdNum}>{row.prompt_tokens}</td>
                          <td className={tdNum}>{row.completion_tokens}</td>
                          <td className={tdNum}>{row.total_tokens}</td>
                          <td className={tdNum}>${row.cost_usd.toFixed(4)}</td>
                        </StaggerRow>
                      ))}
                      <StaggerRow>
                        <td className={tdStrong}>Total</td>
                        <td className={tdNumStrong}>{d.totals.calls}</td>
                        <td className={tdNumStrong}>{d.totals.prompt_tokens}</td>
                        <td className={tdNumStrong}>{d.totals.completion_tokens}</td>
                        <td className={tdNumStrong}>{d.totals.total_tokens}</td>
                        <td className={tdNumStrong}>${d.totals.cost_usd.toFixed(4)}</td>
                      </StaggerRow>
                    </StaggerBody>
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
                color={SERIES.error}
                ariaLabel="Errors per day"
              />
              <h3 className={`label-micro ${s.chartTitle}`}>Error rate</h3>
              {ratePoints.length ? (
                <>
                  {/* A truncated summary scan undercounts the denominator, so
                      the rate can overshoot — surface it on THIS chart. */}
                  {summary.data?.truncated && <TruncatedBadge />}
                  <DayLineChart
                    points={ratePoints}
                    color={SERIES.error}
                    ariaLabel="Error rate per day"
                    format={formatPct}
                  />
                </>
              ) : (
                <div className={t.muted}>
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
              <div className={s.spacer} />
              {d.errors.length === 0 ? (
                <div className={t.muted}>No errors in this range. 🎉</div>
              ) : (
                <div className={t.scrollX}>
                  <table className={`${t.table} ${t.minErrors}`}>
                    <thead>
                      <tr>
                        <th className={th}>Time</th>
                        <th className={th}>Type</th>
                        <th className={th}>Method</th>
                        <th className={th}>Path</th>
                        <th className={thNum}>Status</th>
                        <th className={thNum}>Duration</th>
                      </tr>
                    </thead>
                    <StaggerBody>
                      {d.errors.map((e, i) => (
                        <StaggerRow key={e.request_id ?? `${e.created_at}-${i}`}>
                          <td className={`${td} ${t.nowrap}`}>{e.created_at ?? "—"}</td>
                          <td className={td}>{e.event_type}</td>
                          <td className={td}>{e.method ?? "—"}</td>
                          <td className={tdMono}>{e.path ?? "—"}</td>
                          <td className={tdNum}>{e.status_code ?? "—"}</td>
                          <td className={tdNum}>{e.duration_ms != null ? `${e.duration_ms.toFixed(1)}ms` : "—"}</td>
                        </StaggerRow>
                      ))}
                    </StaggerBody>
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

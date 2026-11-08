/**
 * Admin > Analytics > Learning loop: what the loop cost against what it
 * measurably taught (spec §13 A137, backend learning/cost_per_gain.py).
 *
 * The loop's model spend in the range (tutor, grading, decisions, session
 * closes, check-item drafting) per active student-month against spec §3.5's
 * target, per session, and per matched pre/post pair and gain point at each
 * post-test window, overall and per course. Every figure shows its n; a
 * missing figure is "—", never a zero; intervals come from the same
 * student-cluster bootstrap as the learning gain, and an open upper bound
 * reads "unbounded".
 */

import React from "react";
import type { LoopCostBlock, LoopCostPerGain, LoopCostWindow } from "@/lib/types";

const th: React.CSSProperties = {
  textAlign: "left", fontSize: 11, textTransform: "uppercase", letterSpacing: "0.08em",
  color: "var(--text-muted)", padding: "4px 8px",
};
const thNum: React.CSSProperties = { ...th, textAlign: "right" };
const td: React.CSSProperties = { fontSize: 13, padding: "6px 8px", borderTop: "1px solid var(--border)" };
const tdNum: React.CSSProperties = { ...td, textAlign: "right", fontVariantNumeric: "tabular-nums" };
const muted: React.CSSProperties = { color: "var(--text-muted)", fontSize: 13, margin: 0 };

/** Dollars: cents from $1 up, three significant digits below (sub-cent costs
 *  stay readable), and a floor below $0.0001. */
export function fmtUsd(v: number | null | undefined): string {
  if (v == null) return "—";
  if (v === 0) return "$0";
  if (Math.abs(v) < 0.0001) return v > 0 ? "<$0.0001" : ">-$0.0001";
  return `$${Math.abs(v) >= 1 ? v.toFixed(2) : String(Number(v.toPrecision(3)))}`;
}

function fmtCi(ci: [number | null, number | null] | null): string | null {
  if (!ci) return null;
  return `${fmtUsd(ci[0])} to ${ci[1] == null ? "unbounded" : fmtUsd(ci[1])}`;
}

function Figure({ label, value, n, testid, note }: {
  label: string; value: string; n: string; testid: string; note?: string;
}) {
  return (
    <div data-testid={testid}>
      <div className="label-micro">{label}</div>
      <div style={{ fontSize: 22, fontWeight: 600 }}>{value}</div>
      <div style={{ fontSize: 12, color: "var(--text-muted)" }}>{n}</div>
      {note && <div style={{ fontSize: 12, color: "var(--text-muted)" }}>{note}</div>}
    </div>
  );
}

function plural(n: number, one: string, many = `${one}s`): string {
  return `${n.toLocaleString()} ${n === 1 ? one : many}`;
}

function WindowRow({ w, testid }: { w: LoopCostWindow; testid: string }) {
  const pairCi = fmtCi(w.per_pair_ci);
  const gainCi = fmtCi(w.per_gain_point_ci);
  return (
    <tr data-testid={testid}>
      <td style={td}>{`${w.window_days} days`}</td>
      <td style={tdNum}>{`${w.pairs} (${plural(w.students, "student")})`}</td>
      <td style={tdNum}>{w.gain_points > 0 ? `+${w.gain_points}` : w.gain_points}</td>
      <td style={tdNum}>
        <span>{fmtUsd(w.per_pair)}</span>
        {pairCi && <div data-testid={`${testid}-pair-ci`} style={{ fontSize: 11, color: "var(--text-muted)" }}>{pairCi}</div>}
      </td>
      <td style={tdNum}>
        <span data-testid={`${testid}-gain`}>{w.per_gain_point == null ? (w.pairs ? "no net gain" : "—") : fmtUsd(w.per_gain_point)}</span>
        {gainCi && <div data-testid={`${testid}-gain-ci`} style={{ fontSize: 11, color: "var(--text-muted)" }}>{gainCi}</div>}
      </td>
    </tr>
  );
}

function CourseRow({ c, firstWindow }: { c: LoopCostBlock; firstWindow: number | undefined }) {
  const w = c.windows.find(x => x.window_days === firstWindow);
  return (
    <tr data-testid={`admin-loop-cost-course-${c.course_id}`}>
      <td style={td}><code>{c.course_id}</code></td>
      <td style={tdNum}>{fmtUsd(c.cost_usd)}</td>
      <td style={tdNum}>{fmtUsd(c.drafting_usd)}</td>
      <td style={tdNum}>{c.active_students}</td>
      <td style={tdNum}>{fmtUsd(c.per_active_student_month)}</td>
      <td style={tdNum}>{`${fmtUsd(c.per_session)} (${c.sessions})`}</td>
      <td style={tdNum}>{w ? `${w.pairs} / ${w.gain_points > 0 ? `+${w.gain_points}` : w.gain_points}` : "—"}</td>
      <td style={tdNum}>{w ? fmtUsd(w.per_gain_point) : "—"}</td>
    </tr>
  );
}

export function LoopCostPanel({ cost }: { cost: LoopCostPerGain | null | undefined }) {
  if (cost === undefined) return null; // a pre-A137 backend
  if (cost === null) {
    return (
      <p data-testid="admin-loop-cost-unavailable" style={muted}>
        The loop&apos;s spend could not be read for this range.
      </p>
    );
  }
  const o = cost.overall;
  const target = fmtUsd(cost.target_usd_per_student_month);
  const firstWindow = o.windows[0]?.window_days;
  return (
    <div data-testid="admin-loop-cost" style={{ display: "grid", gap: 12 }}>
      <div style={{ display: "flex", gap: 24, flexWrap: "wrap" }}>
        <Figure
          testid="admin-loop-cost-student-month"
          label="Per active student-month"
          value={fmtUsd(o.per_active_student_month)}
          n={plural(o.active_students, "active student")}
          note={o.target_ratio == null ? `target ${target}` : `${o.target_ratio.toFixed(1)}× the ${target} target`}
        />
        <Figure
          testid="admin-loop-cost-tutor-month"
          label="Tutor only, per student-month"
          value={fmtUsd(o.tutor_per_active_student_month)}
          n={`what the ${target} target prices`}
        />
        <Figure
          testid="admin-loop-cost-session"
          label="Per session"
          value={fmtUsd(o.per_session)}
          n={plural(o.sessions, "session")}
        />
        <Figure
          testid="admin-loop-cost-total"
          label="Loop spend in range"
          value={fmtUsd(o.cost_usd)}
          n={`${plural(o.rows, "model call")}, drafting ${fmtUsd(o.drafting_usd)}`}
          note={o.unpriced_rows ? `${plural(o.unpriced_rows, "call")} on an unpriced model not counted` : undefined}
        />
      </div>
      <div style={{ overflowX: "auto" }}>
        <table data-testid="admin-loop-cost-windows" style={{ borderCollapse: "collapse", minWidth: 520 }}>
          <thead>
            <tr>
              <th style={th}>Window</th>
              <th style={thNum}>Pairs</th>
              <th style={thNum}>Gain points</th>
              <th style={thNum}>Per pair</th>
              <th style={thNum}>Per gain point</th>
            </tr>
          </thead>
          <tbody>
            {o.windows.map(w => <WindowRow key={w.window_days} w={w} testid={`admin-loop-cost-window-${w.window_days}`} />)}
          </tbody>
        </table>
      </div>
      {cost.courses.length > 0 && (
        <div style={{ overflowX: "auto" }}>
          <table data-testid="admin-loop-cost-courses" style={{ borderCollapse: "collapse", minWidth: 640 }}>
            <thead>
              <tr>
                <th style={th}>Course</th>
                <th style={thNum}>Spend</th>
                <th style={thNum}>Drafting</th>
                <th style={thNum}>Active students</th>
                <th style={thNum}>Per student-month</th>
                <th style={thNum}>Per session (n)</th>
                <th style={thNum}>{`Pairs / gain, ${firstWindow ?? "—"} days`}</th>
                <th style={thNum}>Per gain point</th>
              </tr>
            </thead>
            <tbody>
              {cost.courses.map(c => <CourseRow key={c.course_id} c={c} firstWindow={firstWindow} />)}
            </tbody>
          </table>
        </div>
      )}
      {cost.unattributed.rows > 0 && (
        <p data-testid="admin-loop-cost-unattributed" style={muted}>
          {`${fmtUsd(cost.unattributed.cost_usd)} over ${plural(cost.unattributed.rows, "call")} has no course on record (written before courses were recorded on model calls); it is in the totals, not in any course.`}
        </p>
      )}
      <p data-testid="admin-loop-cost-note" style={{ ...muted, fontSize: 12 }}>
        {`A gain point is one concept answered right at the post-test that was wrong at the pretest (the reverse counts −1). Under each figure: a ${Math.round(cost.ci.level * 100)}% interval from a ${cost.ci.resamples.toLocaleString()}-resample bootstrap over students; none below two students. Post-tests measure sessions 7 to 28 or more days earlier, so read this over a range much longer than the windows.`}
      </p>
    </div>
  );
}

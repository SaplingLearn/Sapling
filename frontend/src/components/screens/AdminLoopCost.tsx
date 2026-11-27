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

import type { LoopCostBlock, LoopCostPerGain, LoopCostWindow } from "@/lib/types";
import { AnimatedNumber } from "./AnimatedNumber";
import { StaggerBody, StaggerRow } from "./admin/adminMotion";
import t from "./admin/adminTable.module.css";
import s from "./AdminLoopCost.module.css";

const th = t.th;
const thNum = `${t.th} ${t.num}`;
const td = t.td;
const tdNum = `${t.td} ${t.num}`;

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

/** A headline dollar figure; it tweens when the range changes ("—" with none). */
function Figure({ label, value, n, testid, note }: {
  label: string; value: number | null | undefined; n: string; testid: string; note?: string;
}) {
  return (
    <div data-testid={testid}>
      <div className="label-micro">{label}</div>
      <div className={s.figure}>{value == null ? fmtUsd(value) : <AnimatedNumber value={value} format={fmtUsd} />}</div>
      <div className={t.statNote}>{n}</div>
      {note && <div className={t.statNote}>{note}</div>}
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
    <StaggerRow data-testid={testid}>
      <td className={td}>{`${w.window_days} days`}</td>
      <td className={tdNum}>{`${w.pairs} (${plural(w.students, "student")})`}</td>
      <td className={tdNum}>{w.gain_points > 0 ? `+${w.gain_points}` : w.gain_points}</td>
      <td className={tdNum}>
        <span>{fmtUsd(w.per_pair)}</span>
        {pairCi && <div data-testid={`${testid}-pair-ci`} className={s.ci}>{pairCi}</div>}
      </td>
      <td className={tdNum}>
        <span data-testid={`${testid}-gain`}>{w.per_gain_point == null ? (w.pairs ? "no net gain" : "—") : fmtUsd(w.per_gain_point)}</span>
        {gainCi && <div data-testid={`${testid}-gain-ci`} className={s.ci}>{gainCi}</div>}
      </td>
    </StaggerRow>
  );
}

function CourseRow({ c, firstWindow }: { c: LoopCostBlock; firstWindow: number | undefined }) {
  const w = c.windows.find(x => x.window_days === firstWindow);
  return (
    <StaggerRow data-testid={`admin-loop-cost-course-${c.course_id}`}>
      <td className={td}><code>{c.course_id}</code></td>
      <td className={tdNum}>{fmtUsd(c.cost_usd)}</td>
      <td className={tdNum}>{fmtUsd(c.drafting_usd)}</td>
      <td className={tdNum}>{c.active_students}</td>
      <td className={tdNum}>{fmtUsd(c.per_active_student_month)}</td>
      <td className={tdNum}>{`${fmtUsd(c.per_session)} (${c.sessions})`}</td>
      <td className={tdNum}>{w ? `${w.pairs} / ${w.gain_points > 0 ? `+${w.gain_points}` : w.gain_points}` : "—"}</td>
      <td className={tdNum}>{w ? fmtUsd(w.per_gain_point) : "—"}</td>
    </StaggerRow>
  );
}

export function LoopCostPanel({ cost }: { cost: LoopCostPerGain | null | undefined }) {
  if (cost === undefined) return null; // a pre-A137 backend
  if (cost === null) {
    return (
      <p data-testid="admin-loop-cost-unavailable" className={t.muted}>
        The loop&apos;s spend could not be read for this range.
      </p>
    );
  }
  const o = cost.overall;
  const target = fmtUsd(cost.target_usd_per_student_month);
  const firstWindow = o.windows[0]?.window_days;
  return (
    <div data-testid="admin-loop-cost" className={t.stack}>
      <div className={s.figures}>
        <Figure
          testid="admin-loop-cost-student-month"
          label="Per active student-month"
          value={o.per_active_student_month}
          n={plural(o.active_students, "active student")}
          note={o.target_ratio == null ? `target ${target}` : `${o.target_ratio.toFixed(1)}× the ${target} target`}
        />
        <Figure
          testid="admin-loop-cost-tutor-month"
          label="Tutor only, per student-month"
          value={o.tutor_per_active_student_month}
          n={`what the ${target} target prices`}
        />
        <Figure
          testid="admin-loop-cost-session"
          label="Per session"
          value={o.per_session}
          n={plural(o.sessions, "session")}
        />
        <Figure
          testid="admin-loop-cost-total"
          label="Loop spend in range"
          value={o.cost_usd}
          n={`${plural(o.rows, "model call")}, drafting ${fmtUsd(o.drafting_usd)}`}
          note={o.unpriced_rows ? `${plural(o.unpriced_rows, "call")} on an unpriced model not counted` : undefined}
        />
      </div>
      <div className={t.scrollX}>
        <table data-testid="admin-loop-cost-windows" className={`${t.table} ${t.minLoopWindows}`}>
          <thead>
            <tr>
              <th className={th}>Window</th>
              <th className={thNum}>Pairs</th>
              <th className={thNum}>Gain points</th>
              <th className={thNum}>Per pair</th>
              <th className={thNum}>Per gain point</th>
            </tr>
          </thead>
          <StaggerBody>
            {o.windows.map(w => <WindowRow key={w.window_days} w={w} testid={`admin-loop-cost-window-${w.window_days}`} />)}
          </StaggerBody>
        </table>
      </div>
      {cost.courses.length > 0 && (
        <div className={t.scrollX}>
          <table data-testid="admin-loop-cost-courses" className={`${t.table} ${t.minLoopCourses}`}>
            <thead>
              <tr>
                <th className={th}>Course</th>
                <th className={thNum}>Spend</th>
                <th className={thNum}>Drafting</th>
                <th className={thNum}>Active students</th>
                <th className={thNum}>Per student-month</th>
                <th className={thNum}>Per session (n)</th>
                <th className={thNum}>{`Pairs / gain, ${firstWindow ?? "—"} days`}</th>
                <th className={thNum}>Per gain point</th>
              </tr>
            </thead>
            <StaggerBody>
              {cost.courses.map(c => <CourseRow key={c.course_id} c={c} firstWindow={firstWindow} />)}
            </StaggerBody>
          </table>
        </div>
      )}
      {cost.unattributed.rows > 0 && (
        <p data-testid="admin-loop-cost-unattributed" className={t.muted}>
          {/* #866 K60: every loop call records its course now; an older call that
              named it only through its session loses it with the session */}
          {`${fmtUsd(cost.unattributed.cost_usd)} over ${plural(cost.unattributed.rows, "call")} has no course on record: the call did not record its course, and its session (if it named one) has since been deleted or never had a course. It is in the totals, not in any course.`}
        </p>
      )}
      <p data-testid="admin-loop-cost-note" className={t.small}>
        {`A gain point is one concept answered right at the post-test that was wrong at the pretest (the reverse counts −1). Under each figure: a ${Math.round(cost.ci.level * 100)}% interval from a ${cost.ci.resamples.toLocaleString()}-resample bootstrap over students; none below two students. Post-tests measure sessions 7 to 28 or more days earlier, so read this over a range much longer than the windows.`}
      </p>
    </div>
  );
}

"use client";

/**
 * Admin learning-loop: help abuse on the hint ladder (spec §13 A133). Admin
 * only — nothing here reaches a student. Reads the additive `help_abuse`
 * field of GET /api/admin/analytics/learning-loop (learning/help_abuse.py):
 * how often posed check items bottomed out (H5 completion problem or H6 full
 * solution), how fast, through which attempts, and whether the student then
 * answered the next item on the concept with no help. The "By gate" rows are
 * what the owner judges the strict genuine-attempt gate (A134,
 * `help_gate_strict`) by. Every count carries its n; a value with nothing
 * behind it reads "—", never a zero.
 */

import React from "react";
import type { LoopHelpAbuse, LoopHelpAbuseGroup, LoopHelpMedian, LoopHelpNext } from "@/lib/types";
import { AnimatedNumber } from "../AnimatedNumber";
import { StaggerBody, StaggerRow } from "./adminMotion";
import t from "./adminTable.module.css";
import s from "./HelpAbusePanel.module.css";

const th = t.th;
const thNum = `${t.th} ${t.num}`;
const td = t.td;
const tdNum = `${t.td} ${t.num}`;

/** How many student rows show before "Show all". */
export const STUDENT_ROWS = 10;

const GATE_LABEL: Record<string, string> = {
  standard: "Standard gate",
  strict: "Strict gate",
  none: "No hint attempt",
};
const BAND_LABEL: Record<string, string> = {
  novice: "Novice",
  develop: "Developing",
  profic: "Proficient",
  unknown: "Band unknown",
};
const LEVELS = [
  ["none", "No help"],
  ["partial", "Some help (H1–H4)"],
  ["bottom_out", "Bottomed out (H5–H6)"],
] as const;

const pct = (v: number | null) => (v == null ? "—" : `${Number((v * 100).toFixed(1))}%`);
const ofTotal = (n: number, total: number) => (total ? `${n} of ${total}` : "—");
const seconds = (m: LoopHelpMedian) => (m.median == null ? "—" : `${Math.round(m.median)} s`);
/** A median in seconds that tweens on a range change; "—" with none. */
function Seconds({ m }: { m: LoopHelpMedian }) {
  return m.median == null ? <>—</> : <AnimatedNumber value={m.median} format={(v) => `${Math.round(v)} s`} />;
}
/** answered right with no help, of the steps that had a next item */
const nextShare = (x: LoopHelpNext) => {
  const had = x.unassisted_correct + x.other;
  return had ? `${x.unassisted_correct} of ${had} (${pct(x.unassisted_correct / had)})` : "—";
};

function GroupRows({ rows, label, testid }: {
  rows: LoopHelpAbuseGroup[];
  label: (key: string) => string;
  testid: string;
}) {
  return (
    <>
      {rows.map(g => (
        <StaggerRow key={g.key} data-testid={`${testid}-${g.key}`}>
          <td className={td}>{label(g.key)}</td>
          <td className={tdNum}>{g.steps}</td>
          <td className={tdNum}>{g.bottom_outs}{g.full_solutions ? ` (${g.full_solutions} full)` : ""}</td>
          <td className={tdNum}>{pct(g.bottom_out_rate)}</td>
          <td className={tdNum} title={`n = ${g.time_to_bottom_out_s.n}`}>{seconds(g.time_to_bottom_out_s)}</td>
          <td className={tdNum} title={`n = ${g.help_gap_s.n}`}>{seconds(g.help_gap_s)}</td>
          <td className={tdNum}>
            {g.attempts.counted ? `${g.attempts.rapid} / ${g.attempts.repeat} of ${g.attempts.counted}` : "—"}
          </td>
          <td className={tdNum}>
            {ofTotal(g.bottom_out_attempts.held_by_strict, g.bottom_out_attempts.measured)}
            {g.bottom_out_attempts.unmeasured ? ` (+${g.bottom_out_attempts.unmeasured} unmeasured)` : ""}
          </td>
          <td className={tdNum}>{nextShare(g.next.bottom_out)}</td>
        </StaggerRow>
      ))}
    </>
  );
}

function GroupTable({ title, rows, label, testid }: {
  title: string;
  rows: LoopHelpAbuseGroup[];
  label: (key: string) => string;
  testid: string;
}) {
  return (
    <div data-testid={testid}>
      <div className={`label-micro ${t.label}`}>{title}</div>
      {rows.length === 0 ? (
        <div className={t.muted}>No posed check items in this range.</div>
      ) : (
        <div className={t.scrollX}>
          <table className={`${t.table} ${t.minHelpGroup}`}>
            <thead>
              <tr>
                <th className={th}>{title}</th>
                <th className={thNum}>Items</th>
                <th className={thNum}>Bottom-outs</th>
                <th className={thNum}>Rate</th>
                <th className={thNum}>Time to bottom-out</th>
                <th className={thNum}>Gap between hints</th>
                <th className={thNum}>Rapid / repeat attempts</th>
                <th className={thNum}>Bottom-outs the strict rule would hold</th>
                <th className={thNum}>Next item right unaided, after a bottom-out</th>
              </tr>
            </thead>
            <StaggerBody>
              <GroupRows rows={rows} label={label} testid={testid} />
            </StaggerBody>
          </table>
        </div>
      )}
    </div>
  );
}

function NextTable({ group }: { group: LoopHelpAbuseGroup }) {
  return (
    <div data-testid="admin-loop-help-abuse-next" className={t.scrollX}>
      <div className={`label-micro ${t.label}`}>What happened on the next item</div>
      <table className={`${t.table} ${t.minNextItem}`}>
        <thead>
          <tr>
            <th className={th}>Help on the item</th>
            <th className={thNum}>Graded</th>
            <th className={thNum}>Next right, unaided</th>
            <th className={thNum}>Next missed or helped</th>
            <th className={thNum}>No next item yet</th>
          </tr>
        </thead>
        <StaggerBody>
          {LEVELS.map(([key, label]) => {
            const x = group.next[key];
            return (
              <StaggerRow key={key} data-testid={`admin-loop-help-abuse-next-${key}`}>
                <td className={td}>{label}</td>
                <td className={tdNum}>{x.graded}</td>
                <td className={tdNum}>{nextShare(x)}</td>
                <td className={tdNum}>{x.other}</td>
                <td className={tdNum}>{x.none}</td>
              </StaggerRow>
            );
          })}
        </StaggerBody>
      </table>
    </div>
  );
}

/** The section for LearningLoopPanelBody. `data` undefined: the backend
 *  predates A133 (nothing renders); null: its reads failed for this range. */
export function HelpAbusePanel({ data }: { data: LoopHelpAbuse | null | undefined }) {
  const [allStudents, setAllStudents] = React.useState(false);
  if (data === undefined) return null;
  const heading = <h3 className={`h-serif ${t.heading}`}>Are students gaming the hints?</h3>;
  if (data === null) {
    return (
      <section data-testid="admin-loop-help-abuse">
        {heading}
        <p data-testid="admin-loop-help-abuse-unavailable" className={t.lede}>
          Hint-use data could not be read for this range.
        </p>
      </section>
    );
  }
  const o = data.overall;
  const students = allStudents ? data.by_student : data.by_student.slice(0, STUDENT_ROWS);
  return (
    <section data-testid="admin-loop-help-abuse">
      {heading}
      <p className={t.lede}>
        A check item <strong>bottoms out</strong> when its hints reach H{data.bottom_out_rung} (a completion
        problem) or H6 (the full solution). Rapid attempts came sooner after the latest hint than the
        band&apos;s independent-time gate (the time alone an attempt needs before it counts); repeats said
        nothing the student&apos;s earlier attempts on the item had not. &ldquo;Would hold&rdquo; counts bottom-outs reached through an
        attempt the strict gate would not count. A novice on the worked-example path reaches H5 by design,
        so read that band with its attempts. Compare the gate rows before switching the strict gate on.
      </p>
      <div data-testid="admin-loop-help-abuse-overall" className={t.stats}>
        <div><div className="label-micro">Items posed</div><div className={t.statValue}><AnimatedNumber value={o.steps} /></div></div>
        <div>
          <div className="label-micro">Bottom-outs</div>
          <div className={t.statValue}><AnimatedNumber value={o.bottom_outs} /> ({pct(o.bottom_out_rate)})</div>
        </div>
        <div><div className="label-micro">Full solutions</div><div className={t.statValue}><AnimatedNumber value={o.full_solutions} /></div></div>
        <div><div className="label-micro">Time to bottom-out</div><div className={t.statValue}><Seconds m={o.time_to_bottom_out_s} /></div></div>
        <div><div className="label-micro">Gap between hints</div><div className={t.statValue}><Seconds m={o.help_gap_s} /></div></div>
      </div>
      <div className={t.stackLoose}>
        <GroupTable title="By gate" rows={data.by_gate} label={k => GATE_LABEL[k] ?? k} testid="admin-loop-help-abuse-gate" />
        <GroupTable title="By band" rows={data.by_band} label={k => BAND_LABEL[k] ?? k} testid="admin-loop-help-abuse-band" />
        <GroupTable title="By course" rows={data.by_course} label={k => k} testid="admin-loop-help-abuse-course" />
        <GroupTable title="By student" rows={students} label={k => k} testid="admin-loop-help-abuse-student" />
        {data.by_student.length > STUDENT_ROWS && (
          <button
            type="button"
            data-testid="admin-loop-help-abuse-students-toggle"
            onClick={() => setAllStudents(v => !v)}
            className={`btn btn--sm ${s.toggle}`}
          >
            {allStudents ? `Show the top ${STUDENT_ROWS}` : `Show all ${data.by_student.length} students`}
          </button>
        )}
        <NextTable group={o} />
      </div>
      <p data-testid="admin-loop-help-abuse-limits" className={t.tail}>
        Not measured: whether an attempt had substance. Hint-unlocking attempts are never graded and their
        text is never stored, so these columns see rapid and repeated attempts, not a patient one-character
        one. Where help stands in for the work, the next-item column shows it.
      </p>
    </section>
  );
}

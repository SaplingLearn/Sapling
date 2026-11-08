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

const th: React.CSSProperties = {
  textAlign: "left", fontSize: 11, textTransform: "uppercase", letterSpacing: "0.08em",
  color: "var(--text-muted)", padding: "4px 8px",
};
const thNum: React.CSSProperties = { ...th, textAlign: "right" };
const td: React.CSSProperties = { fontSize: 13, padding: "6px 8px", borderTop: "1px solid var(--border)" };
const tdNum: React.CSSProperties = { ...td, textAlign: "right", fontVariantNumeric: "tabular-nums" };
const muted: React.CSSProperties = { color: "var(--text-muted)", fontSize: 13, margin: "0 0 12px" };
const scrollX: React.CSSProperties = { overflowX: "auto" };

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
        <tr key={g.key} data-testid={`${testid}-${g.key}`}>
          <td style={td}>{label(g.key)}</td>
          <td style={tdNum}>{g.steps}</td>
          <td style={tdNum}>{g.bottom_outs}{g.full_solutions ? ` (${g.full_solutions} full)` : ""}</td>
          <td style={tdNum}>{pct(g.bottom_out_rate)}</td>
          <td style={tdNum} title={`n = ${g.time_to_bottom_out_s.n}`}>{seconds(g.time_to_bottom_out_s)}</td>
          <td style={tdNum} title={`n = ${g.help_gap_s.n}`}>{seconds(g.help_gap_s)}</td>
          <td style={tdNum}>
            {g.attempts.counted ? `${g.attempts.rapid} / ${g.attempts.repeat} of ${g.attempts.counted}` : "—"}
          </td>
          <td style={tdNum}>
            {ofTotal(g.bottom_out_attempts.held_by_strict, g.bottom_out_attempts.measured)}
            {g.bottom_out_attempts.unmeasured ? ` (+${g.bottom_out_attempts.unmeasured} unmeasured)` : ""}
          </td>
          <td style={tdNum}>{nextShare(g.next.bottom_out)}</td>
        </tr>
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
      <div className="label-micro" style={{ marginBottom: 6 }}>{title}</div>
      {rows.length === 0 ? (
        <div style={{ color: "var(--text-muted)", fontSize: 13 }}>No posed check items in this range.</div>
      ) : (
        <div style={scrollX}>
          <table style={{ borderCollapse: "collapse", minWidth: 760 }}>
            <thead>
              <tr>
                <th style={th}>{title}</th>
                <th style={thNum}>Items</th>
                <th style={thNum}>Bottom-outs</th>
                <th style={thNum}>Rate</th>
                <th style={thNum}>Time to bottom-out</th>
                <th style={thNum}>Gap between hints</th>
                <th style={thNum}>Rapid / repeat attempts</th>
                <th style={thNum}>Bottom-outs the strict rule would hold</th>
                <th style={thNum}>Next item right unaided, after a bottom-out</th>
              </tr>
            </thead>
            <tbody>
              <GroupRows rows={rows} label={label} testid={testid} />
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function NextTable({ group }: { group: LoopHelpAbuseGroup }) {
  return (
    <div data-testid="admin-loop-help-abuse-next" style={scrollX}>
      <div className="label-micro" style={{ marginBottom: 6 }}>What happened on the next item</div>
      <table style={{ borderCollapse: "collapse", minWidth: 520 }}>
        <thead>
          <tr>
            <th style={th}>Help on the item</th>
            <th style={thNum}>Graded</th>
            <th style={thNum}>Next right, unaided</th>
            <th style={thNum}>Next missed or helped</th>
            <th style={thNum}>No next item yet</th>
          </tr>
        </thead>
        <tbody>
          {LEVELS.map(([key, label]) => {
            const x = group.next[key];
            return (
              <tr key={key} data-testid={`admin-loop-help-abuse-next-${key}`}>
                <td style={td}>{label}</td>
                <td style={tdNum}>{x.graded}</td>
                <td style={tdNum}>{nextShare(x)}</td>
                <td style={tdNum}>{x.other}</td>
                <td style={tdNum}>{x.none}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

/** The section for LearningLoopPanelBody. `data` undefined: the backend
 *  predates A133 (nothing renders); null: its reads failed for this range. */
export function HelpAbusePanel({ data }: { data: LoopHelpAbuse | null | undefined }) {
  const [allStudents, setAllStudents] = React.useState(false);
  if (data === undefined) return null;
  const heading = <h3 className="h-serif" style={{ fontSize: 15, margin: "16px 0 8px" }}>Are students gaming the hints?</h3>;
  if (data === null) {
    return (
      <section data-testid="admin-loop-help-abuse">
        {heading}
        <p data-testid="admin-loop-help-abuse-unavailable" style={muted}>
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
      <p style={muted}>
        A check item <strong>bottoms out</strong> when its hints reach H{data.bottom_out_rung} (a completion
        problem) or H6 (the full solution). Rapid attempts came less than the band&apos;s independent
        time (45 s; 90 s for a novice) after the latest hint; repeats said nothing the student&apos;s
        earlier attempts on the item had not. &ldquo;Would hold&rdquo; counts bottom-outs reached through an
        attempt the strict gate would not count. A novice on the worked-example path reaches H5 by design,
        so read that band with its attempts. Compare the gate rows before switching the strict gate on.
      </p>
      <div data-testid="admin-loop-help-abuse-overall" style={{ display: "flex", gap: 24, flexWrap: "wrap", marginBottom: 12 }}>
        <div><div className="label-micro">Items posed</div><div style={{ fontSize: 24, fontWeight: 600 }}>{o.steps}</div></div>
        <div><div className="label-micro">Bottom-outs</div><div style={{ fontSize: 24, fontWeight: 600 }}>{o.bottom_outs} ({pct(o.bottom_out_rate)})</div></div>
        <div><div className="label-micro">Full solutions</div><div style={{ fontSize: 24, fontWeight: 600 }}>{o.full_solutions}</div></div>
        <div><div className="label-micro">Time to bottom-out</div><div style={{ fontSize: 24, fontWeight: 600 }}>{seconds(o.time_to_bottom_out_s)}</div></div>
        <div><div className="label-micro">Gap between hints</div><div style={{ fontSize: 24, fontWeight: 600 }}>{seconds(o.help_gap_s)}</div></div>
      </div>
      <div style={{ display: "grid", gap: 16 }}>
        <GroupTable title="By gate" rows={data.by_gate} label={k => GATE_LABEL[k] ?? k} testid="admin-loop-help-abuse-gate" />
        <GroupTable title="By band" rows={data.by_band} label={k => BAND_LABEL[k] ?? k} testid="admin-loop-help-abuse-band" />
        <GroupTable title="By course" rows={data.by_course} label={k => k} testid="admin-loop-help-abuse-course" />
        <GroupTable title="By student" rows={students} label={k => k} testid="admin-loop-help-abuse-student" />
        {data.by_student.length > STUDENT_ROWS && (
          <button
            type="button"
            data-testid="admin-loop-help-abuse-students-toggle"
            className="btn btn--sm"
            onClick={() => setAllStudents(v => !v)}
            style={{ justifySelf: "start" }}
          >
            {allStudents ? `Show the top ${STUDENT_ROWS}` : `Show all ${data.by_student.length} students`}
          </button>
        )}
        <NextTable group={o} />
      </div>
      <p data-testid="admin-loop-help-abuse-limits" style={{ ...muted, margin: "8px 0 0" }}>
        Not measured: whether an attempt had substance. Hint-unlocking attempts are never graded and their
        text is never stored, so these columns see rapid and repeated attempts, not a patient one-character
        one. Where help stands in for the work, the next-item column shows it.
      </p>
    </section>
  );
}

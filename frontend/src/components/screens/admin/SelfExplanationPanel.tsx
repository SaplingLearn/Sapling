"use client";

/**
 * Admin learning-loop: the self-explanation prompts (spec §13 A139). Admin only
 * — nothing here reaches a student. Reads the additive `self_explanation`
 * field of GET /api/admin/analytics/learning-loop: how many "why does this
 * follow?" prompts the tutor asked (code picks the juncture: after a worked
 * example, after a shown solution, after a first unaided correct answer; at
 * most once per concept a session), how many students replied and at what
 * length, and how the next graded item on the concept went after a reply
 * against after none. Replies are diagnosis only — never graded, never
 * evidence — so this is the one place they are counted. Every rate carries its
 * n; a value with nothing behind it reads "—", never a zero.
 */

import React from "react";
import type { LoopSelfExplainNext, LoopSelfExplanation } from "@/lib/types";

const th: React.CSSProperties = {
  textAlign: "left", fontSize: 11, textTransform: "uppercase", letterSpacing: "0.08em",
  color: "var(--text-muted)", padding: "4px 8px",
};
const thNum: React.CSSProperties = { ...th, textAlign: "right" };
const td: React.CSSProperties = { fontSize: 13, padding: "6px 8px", borderTop: "1px solid var(--border)" };
const tdNum: React.CSSProperties = { ...td, textAlign: "right", fontVariantNumeric: "tabular-nums" };
const muted: React.CSSProperties = { color: "var(--text-muted)", fontSize: 13, margin: "0 0 12px" };
const statValue: React.CSSProperties = { fontSize: 24, fontWeight: 600 };
const statNote: React.CSSProperties = { fontSize: 12, color: "var(--text-muted)" };

export const JUNCTURE_LABEL: Record<string, string> = {
  worked_example: "After a worked example",
  released_solution: "After a shown solution",
  first_correct: "After a first unaided correct answer",
};

const pct = (v: number | null) => (v == null ? "—" : `${Number((v * 100).toFixed(1))}%`);
/** "3 of 4 (75%)": right with no help, of the prompts that had a next item. */
const nextShare = (x: LoopSelfExplainNext) => (x.n ? `${x.unassisted} of ${x.n} (${pct(x.rate)})` : "—");

function Stat({ label, value, note, testid }: { label: string; value: string; note: string; testid: string }) {
  return (
    <div data-testid={testid}>
      <div className="label-micro">{label}</div>
      <div style={statValue}>{value}</div>
      <div style={statNote}>{note}</div>
    </div>
  );
}

/** The section for LearningLoopPanelBody. `data` undefined: the backend
 *  predates A139 (nothing renders); null: its reads failed for this range. */
export function SelfExplanationPanel({ data }: { data: LoopSelfExplanation | null | undefined }) {
  if (data === undefined) return null;
  const heading = <h3 className="h-serif" style={{ fontSize: 15, margin: "16px 0 8px" }}>Do students explain their steps?</h3>;
  if (data === null) {
    return (
      <section data-testid="admin-loop-self-explain">
        {heading}
        <p data-testid="admin-loop-self-explain-unavailable" style={muted}>
          Self-explanation data could not be read for this range.
        </p>
      </section>
    );
  }
  const intro = (
    <p style={muted}>
      The tutor asks a &ldquo;why does this follow?&rdquo; question at a key moment — after a worked example, after
      a shown solution, or after a first unaided correct answer — at most once per concept a session. Replies are
      kept for diagnosis only: never graded and never counted as evidence. The next-item figures compare the
      student&apos;s next graded item on the concept after replying with after not replying (skipped or left
      unanswered); read them as a description, not a measured effect.
    </p>
  );
  if (data.shown === 0) {
    return (
      <section data-testid="admin-loop-self-explain">
        {heading}
        {intro}
        <p data-testid="admin-loop-self-explain-empty" style={muted}>No self-explanation prompts in this range.</p>
      </section>
    );
  }
  const { replied, not_replied } = data.next_item;
  return (
    <section data-testid="admin-loop-self-explain">
      {heading}
      {intro}
      <div style={{ display: "flex", gap: 24, flexWrap: "wrap", marginBottom: 12 }}>
        <Stat
          testid="admin-loop-self-explain-shown"
          label="Prompts shown"
          value={String(data.shown)}
          note={`${data.replied} replied · ${data.skipped} skipped · ${data.open} unanswered`}
        />
        <Stat testid="admin-loop-self-explain-reply-rate" label="Reply rate" value={pct(data.reply_rate)} note={`n = ${data.shown}`} />
        <Stat
          testid="admin-loop-self-explain-reply-chars"
          label="Reply length (median)"
          value={data.reply_chars.median == null ? "—" : `${Math.round(data.reply_chars.median)} chars`}
          note={`n = ${data.reply_chars.n}`}
        />
        <Stat
          testid="admin-loop-self-explain-next-replied"
          label="Next item right, unaided — after a reply"
          value={nextShare(replied)}
          note={`n = ${replied.n}${replied.none ? ` · ${replied.none} with no next item yet` : ""}`}
        />
        <Stat
          testid="admin-loop-self-explain-next-not-replied"
          label="Next item right, unaided — no reply"
          value={nextShare(not_replied)}
          note={`n = ${not_replied.n}${not_replied.none ? ` · ${not_replied.none} with no next item yet` : ""}`}
        />
      </div>
      {data.by_juncture.length > 0 && (
        <div data-testid="admin-loop-self-explain-by-juncture" style={{ overflowX: "auto" }}>
          <table style={{ borderCollapse: "collapse", minWidth: 640 }}>
            <thead>
              <tr>
                <th style={th}>Juncture</th>
                <th style={thNum}>Shown</th>
                <th style={thNum}>Reply rate</th>
                <th style={thNum}>Next right unaided, after a reply</th>
                <th style={thNum}>Next right unaided, no reply</th>
              </tr>
            </thead>
            <tbody>
              {data.by_juncture.map((j) => (
                <tr key={j.juncture} data-testid={`admin-loop-self-explain-juncture-${j.juncture}`}>
                  <td style={td}>{JUNCTURE_LABEL[j.juncture] ?? j.juncture}</td>
                  <td style={tdNum}>{j.shown}</td>
                  <td style={tdNum}>{j.shown ? `${pct(j.reply_rate)} (${j.replied} of ${j.shown})` : "—"}</td>
                  <td style={tdNum}>{nextShare(j.next_item.replied)}</td>
                  <td style={tdNum}>{nextShare(j.next_item.not_replied)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {data.truncated && (
        <p style={{ ...muted, margin: "8px 0 0" }}>Partial: a scan limit cut this range short.</p>
      )}
    </section>
  );
}

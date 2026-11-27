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

import type React from "react";
import type { LoopSelfExplainNext, LoopSelfExplanation } from "@/lib/types";
import { AnimatedNumber } from "../AnimatedNumber";
import { StaggerBody, StaggerRow } from "./adminMotion";
import t from "./adminTable.module.css";

const th = t.th;
const thNum = `${t.th} ${t.num}`;
const td = t.td;
const tdNum = `${t.td} ${t.num}`;

export const JUNCTURE_LABEL: Record<string, string> = {
  worked_example: "After a worked example",
  released_solution: "After a shown solution",
  first_correct: "After a first unaided correct answer",
};

const pct = (v: number | null) => (v == null ? "—" : `${Number((v * 100).toFixed(1))}%`);
/** "3 of 4 (75%)": right with no help, of the prompts that had a next item. */
const nextShare = (x: LoopSelfExplainNext) => (x.n ? `${x.unassisted} of ${x.n} (${pct(x.rate)})` : "—");

function Stat({ label, value, note, testid }: { label: string; value: React.ReactNode; note: string; testid: string }) {
  return (
    <div data-testid={testid}>
      <div className="label-micro">{label}</div>
      <div className={t.statValue}>{value}</div>
      <div className={t.statNote}>{note}</div>
    </div>
  );
}

/** A figure that tweens when the range changes; "—" when there is none. */
function Figure({ value, format }: { value: number | null; format: (v: number) => string }) {
  return value == null ? <>—</> : <AnimatedNumber value={value} format={format} />;
}

const pctOf = (v: number) => pct(v);
const chars = (v: number) => `${Math.round(v)} chars`;

/** The section for LearningLoopPanelBody. `data` undefined: the backend
 *  predates A139 (nothing renders); null: its reads failed for this range. */
export function SelfExplanationPanel({ data }: { data: LoopSelfExplanation | null | undefined }) {
  if (data === undefined) return null;
  const heading = <h3 className={`h-serif ${t.heading}`}>Do students explain their steps?</h3>;
  if (data === null) {
    return (
      <section data-testid="admin-loop-self-explain">
        {heading}
        <p data-testid="admin-loop-self-explain-unavailable" className={t.lede}>
          Self-explanation data could not be read for this range.
        </p>
      </section>
    );
  }
  const intro = (
    <p className={t.lede}>
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
        <p data-testid="admin-loop-self-explain-empty" className={t.lede}>No self-explanation prompts in this range.</p>
      </section>
    );
  }
  const { replied, not_replied } = data.next_item;
  return (
    <section data-testid="admin-loop-self-explain">
      {heading}
      {intro}
      <div className={t.stats}>
        <Stat
          testid="admin-loop-self-explain-shown"
          label="Prompts shown"
          value={<AnimatedNumber value={data.shown} />}
          note={`${data.replied} replied · ${data.skipped} skipped · ${data.open} unanswered`}
        />
        <Stat testid="admin-loop-self-explain-reply-rate" label="Reply rate" value={<Figure value={data.reply_rate} format={pctOf} />} note={`n = ${data.shown}`} />
        <Stat
          testid="admin-loop-self-explain-reply-chars"
          label="Reply length (median)"
          value={<Figure value={data.reply_chars.median} format={chars} />}
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
        <div data-testid="admin-loop-self-explain-by-juncture" className={t.scrollX}>
          <table className={`${t.table} ${t.minJuncture}`}>
            <thead>
              <tr>
                <th className={th}>Juncture</th>
                <th className={thNum}>Shown</th>
                <th className={thNum}>Reply rate</th>
                <th className={thNum}>Next right unaided, after a reply</th>
                <th className={thNum}>Next right unaided, no reply</th>
              </tr>
            </thead>
            <StaggerBody>
              {data.by_juncture.map((j) => (
                <StaggerRow key={j.juncture} data-testid={`admin-loop-self-explain-juncture-${j.juncture}`}>
                  <td className={td}>{JUNCTURE_LABEL[j.juncture] ?? j.juncture}</td>
                  <td className={tdNum}>{j.shown}</td>
                  <td className={tdNum}>{j.shown ? `${pct(j.reply_rate)} (${j.replied} of ${j.shown})` : "—"}</td>
                  <td className={tdNum}>{nextShare(j.next_item.replied)}</td>
                  <td className={tdNum}>{nextShare(j.next_item.not_replied)}</td>
                </StaggerRow>
              ))}
            </StaggerBody>
          </table>
        </div>
      )}
      {data.truncated && (
        <p className={t.tail}>Partial: a scan limit cut this range short.</p>
      )}
    </section>
  );
}

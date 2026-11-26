"use client";
// The session wrap-up, rebuilt (Tutor redesign phase 4, behind `wrapup_v2`;
// design: learn/__fixtures__/wrapup.design.html, the Claude Design board).
// One headline built from what moved, one list of the session's concepts in
// the skill ladder's words (the plan's concepts the session did not reach
// included), the tutor's summary, one "Next time", ONE primary next step
// chosen by state, the other hand-offs under "More practice", and the rating.
// Cut from the old wrap-up: the "n of m stronger" card and the retention CTA.
import React from "react";
import { motion } from "framer-motion";
import { CtaLink } from "@/components/ui/HandoffLink";
import type { LoopCloseConcept, LoopCloseResponse } from "@/lib/api";
import { LEARNING_COPY, plural } from "@/lib/learningCopy";
import { closeHandoffCtas, type HandoffVisibility } from "@/lib/learningHandoffs";
import { LEVEL_WORDS, levelFor, type SkillLevel } from "@/lib/levels";
import { useMotionPresets } from "@/lib/motion";
import { WrapUpRating } from "../WrapUpRating";
import { usePracticeDueIds } from "./practiceDue";
import styles from "./WrapUpV2.module.css";

export const WRAPUP_COPY = {
  notReached: "Not reached today",
  firstTime: "Measured for the first time",
  nextTime: "Next time",
  morePractice: "More practice",
  nothingMeasured: "Nothing measured yet",
} as const;

const RANK: Record<SkillLevel, number> = { not_started: 0, novice: 1, develop: 2, profic: 3 };

export type WrapRow = { id: string; name: string; change: string; gain: number; delta: number; first: boolean; reached: boolean };

/** One concept's change in the ladder's words. A concept first measured this
 *  session (`baseline` check_in / teaching) that did not move is "Measured for
 *  the first time: Developing" — never a drop from the model's prior (A117). */
export function conceptRow(c: LoopCloseConcept, name: string): WrapRow {
  const from = levelFor(c.p_before);
  const to = levelFor(c.p_after);
  const delta = c.p_after - c.p_before;
  const moved = Math.abs(delta) >= 0.005;
  const firstSeen = (c.baseline ?? "pre_session") !== "pre_session";
  let change: string;
  if (from !== to) change = `${LEVEL_WORDS[from]} to ${LEVEL_WORDS[to]}`;
  else if (firstSeen && !moved) change = `${WRAPUP_COPY.firstTime}: ${LEVEL_WORDS[to]}`;
  else if (moved) change = `${LEVEL_WORDS[to]}, a little ${delta > 0 ? "higher" : "lower"}`;
  else change = `${LEVEL_WORDS[to]}, no change`;
  return { id: c.node_id, name, change, gain: RANK[to] - RANK[from], delta, first: firstSeen && !moved, reached: true };
}

/** Every concept the session measured, then the plan's concepts it did not reach. */
export function wrapRows(concepts: readonly LoopCloseConcept[], planned: readonly string[], names: Map<string, string>): WrapRow[] {
  const rows = concepts.map((c) => conceptRow(c, names.get(c.node_id) ?? "A concept"));
  const seen = new Set(rows.map((r) => r.id));
  for (const id of planned) {
    if (seen.has(id)) continue;
    seen.add(id);
    rows.push({ id, name: names.get(id) ?? "A concept", change: WRAPUP_COPY.notReached, gain: 0, delta: 0, first: false, reached: false });
  }
  return rows;
}

/** The headline, from the data: the biggest level-up, else how many concepts
 *  were measured for the first time, else the biggest rise, else the plain title. */
export function wrapHeadline(concepts: readonly LoopCloseConcept[], names: Map<string, string>): { text: string; leadId: string | null } {
  if (concepts.length === 0) return { text: WRAPUP_COPY.nothingMeasured, leadId: null };
  const rows = concepts.map((c) => ({ c, row: conceptRow(c, names.get(c.node_id) ?? "A concept") }));
  const up = rows.filter((r) => r.row.gain > 0).sort((a, b) => b.row.gain - a.row.gain || b.row.delta - a.row.delta)[0];
  if (up) return { text: `${up.row.name} moved up to ${LEVEL_WORDS[levelFor(up.c.p_after)]}`, leadId: up.row.id };
  const firsts = rows.filter((r) => r.row.first).length;
  if (firsts > 0) return { text: `${plural(firsts, "concept")} measured for the first time`, leadId: null };
  const rise = rows.filter((r) => r.row.delta >= 0.005).sort((a, b) => b.row.delta - a.row.delta)[0];
  if (rise) return { text: `${rise.row.name} is a little stronger`, leadId: rise.row.id };
  return { text: "Session wrap-up", leadId: null };
}

export function WrapUpV2({ close, names, courseId, onNew, visibility, rating, planned, dueCount, headingRef }: {
  close: LoopCloseResponse;
  names: Map<string, string>;
  courseId: string | null;
  onNew?: () => void;
  visibility: HandoffVisibility;
  rating: { sessionId: string; topic?: string } | null;
  /** The approved plan's concept ids (for "Not reached today"). */
  planned: readonly string[];
  /** Reviews due on the course (the session panel's count), null unknown. */
  dueCount: number | null;
  /** The headline takes focus when the wrap-up replaces the lesson (A135). */
  headingRef: (el: HTMLElement | null) => void;
}) {
  const rec = close.close;
  const m = useMotionPresets();
  const item = m.list.item;
  const rows = wrapRows(rec.concepts, planned, names);
  const headline = wrapHeadline(rec.concepts, names);
  const dueIds = usePracticeDueIds(courseId, visibility.study && visibility.quiz);
  const quizConcept = rec.concepts.find((c) => c.p_after < c.p_before)?.node_id ?? rec.concepts[0]?.node_id ?? null;
  const ctas = closeHandoffCtas({ courseId, quizConceptId: quizConcept, dueConceptIds: dueIds, visibility });
  // ONE primary step, by state: reviews are due → Review; else a new session.
  const review = (dueCount ?? 0) > 0 ? ctas.find((c) => c.key === "study") ?? null : null;
  const more = ctas.filter((c) => c.key !== "study");
  return (
    <div className={styles.root} data-testid="loop-wrapup-v2">
      <motion.div className={styles.col} variants={m.list.container} initial="hidden" animate="shown">
        <motion.h2 variants={item} ref={headingRef} tabIndex={-1} className={`h-serif ${styles.headline}`} data-testid="loop-close-headline">
          {headline.text}
        </motion.h2>
        {rows.length > 0 && (
          <motion.ul variants={item} className={styles.rows} aria-label="What changed">
            {rows.map((r) => (
              <li key={r.id} data-testid={`loop-close-concept-${r.id}`} data-reached={r.reached ? "true" : "false"} className={styles.row}>
                <span className={r.id === headline.leadId ? styles.lead : undefined}>{r.name}</span>
                <span className={styles.change}>{r.change}</span>
              </li>
            ))}
          </motion.ul>
        )}
        <motion.p variants={item} data-testid="loop-close-summary" className={styles.summary}>{rec.summary}</motion.p>
        {rec.if_then && (
          <motion.section variants={item} data-testid="loop-close-if-then" aria-labelledby="loop-close-next-time" className={styles.nextTime}>
            <h3 id="loop-close-next-time" className={`h-serif ${styles.h3}`}>{WRAPUP_COPY.nextTime}</h3>
            <p className={styles.plain}>{rec.if_then}</p>
          </motion.section>
        )}
        <motion.div variants={item} data-testid="loop-close-done" className={styles.next}>
          {review ? (
            <>
              <CtaLink cta={{ ...review, label: LEARNING_COPY.reviewLink(dueCount) }} variant="primary" />
              {onNew && (
                <button type="button" data-testid="loop-close-new-session" className="btn" onClick={onNew}>{LEARNING_COPY.newSession}</button>
              )}
            </>
          ) : onNew && (
            <button type="button" data-testid="loop-close-new-session" className="btn btn--primary" onClick={onNew}>{LEARNING_COPY.newSession}</button>
          )}
        </motion.div>
        {more.length > 0 && (
          <motion.section variants={item} aria-labelledby="loop-close-more" className={styles.more}>
            <h3 id="loop-close-more" className={styles.moreTitle}>{WRAPUP_COPY.morePractice}</h3>
            <div className={styles.moreLinks}>
              {more.map((c) => <CtaLink key={c.testId} cta={c} variant="text" />)}
            </div>
          </motion.section>
        )}
        {rating && <WrapUpRating key={rating.sessionId} sessionId={rating.sessionId} topic={rating.topic} />}
      </motion.div>
    </div>
  );
}

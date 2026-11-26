"use client";
// The graded check's verdict, rebuilt (Tutor redesign phase 4, behind the
// `verdict_v2` flag; design: learn/__fixtures__/question-states.design.html,
// states 4–6). It leads, then explains: a title, at most one credit line, the
// concept's skill change shown once, and — after a confident miss — why the
// next step waits. The next step itself is the action row's primary button
// (TeachActions), which names where it goes and counts the hold down.
//
// The skill change is the learner model's (one measure, lib/levels.ts): the
// concept's belief just before the answer (`useVerdictSkill.snapshot`, taken
// at submit) against the one the graded turn left.
import React, { useCallback, useState } from "react";
import { motion } from "framer-motion";
import type { LoopCredit, LoopCreditReason, LoopLearnerState } from "@/lib/api";
import { LEVEL_WORDS, levelFor } from "@/lib/levels";
import { useMotionPresets } from "@/lib/motion";
import tutorStyles from "../tutor/tutor.module.css";
import { VerdictBanner } from "../VerdictBanner";
import styles from "./VerdictCard.module.css";

export const VERDICT_V2_COPY = {
  correct: "Correct",
  halfCredit: "Correct, half credit",
  partCredit: "Correct, part credit",
  notQuite: "Not quite",
  sure: "You were sure about this one, so take a moment with it.",
  noCredit: "No skill change this time: the worked steps came before your answer.",
  tryOnOwn: "Try the next one on your own.",
} as const;

const REASON_WHY: Record<LoopCreditReason, string> = {
  hint: "you used a hint",
  recheck: "this idea was already checked earlier this session",
  low_confidence: "the tutor couldn't be fully sure how to read it",
  multi_concept: "it tests more than one concept at once",
};

/** The title: what happened, in two or three words. */
export function verdictTitle(verdict: string, credit?: LoopCredit | null, reasons: readonly LoopCreditReason[] = []): string {
  if (verdict !== "correct") return VERDICT_V2_COPY.notQuite;
  if (credit !== "partial") return VERDICT_V2_COPY.correct;
  return reasons.length === 1 && reasons[0] === "hint" ? VERDICT_V2_COPY.halfCredit : VERDICT_V2_COPY.partCredit;
}

/** The one credit line, or null when the title says it all (full credit, a miss). */
export function creditLine(credit: LoopCredit | null | undefined, reasons: readonly LoopCreditReason[], concept: string): string | null {
  if (credit === "none") return `${VERDICT_V2_COPY.noCredit} ${VERDICT_V2_COPY.tryOnOwn}`;
  if (credit !== "partial") return null;
  if (reasons.length === 1 && reasons[0] === "hint") {
    return `You used a hint, so this counts half toward ${concept}. ${VERDICT_V2_COPY.tryOnOwn}`;
  }
  const why = reasons.filter((r) => REASON_WHY[r]).map((r) => REASON_WHY[r]);
  const joined = why.length < 2 ? why.join("") : `${why.slice(0, -1).join(", ")} and ${why[why.length - 1]}`;
  return joined ? `This counts partly toward ${concept}, because ${joined}.` : `This counts partly toward ${concept}.`;
}

/** A belief that is a measurement (not the model's prior). */
function measured(s: LoopLearnerState | null | undefined): s is LoopLearnerState {
  return !!s && s.measured !== false;
}

/** "Loops: Getting started → Developing", "Loops: Developing, a little higher",
 *  or the first measurement, "Loops: Developing". Null when nothing moved. */
export function skillChangeLine(
  concept: string,
  before: LoopLearnerState | null | undefined,
  after: LoopLearnerState | null | undefined,
): string | null {
  if (!measured(after)) return null;
  const to = levelFor(after.p_known);
  if (!measured(before)) return `${concept}: ${LEVEL_WORDS[to]}`;
  const from = levelFor(before.p_known);
  if (from !== to) return `${concept}: ${LEVEL_WORDS[from]} → ${LEVEL_WORDS[to]}`;
  const delta = after.p_known - before.p_known;
  if (Math.abs(delta) < 0.005) return null;
  return `${concept}: ${LEVEL_WORDS[to]}, a little ${delta > 0 ? "higher" : "lower"}`;
}

/** The learner state as it stood when the answer was submitted. */
export function useVerdictSkill() {
  const [before, setBefore] = useState<Record<string, LoopLearnerState>>({});
  const snapshot = useCallback((states: Record<string, LoopLearnerState>) => setBefore({ ...states }), []);
  return { before, snapshot };
}

/** Continue's label after a verdict: where the plan goes next ("Next: Stacks"),
 *  else plain "Continue" (`nextAfterVerdict`: undefined while the next check
 *  stays on this concept, null when nothing is left). */
export function nextStepLabel(next: string | null | undefined): string {
  return typeof next === "string" && next ? `Next: ${next}` : "Continue";
}

/** The hold's end, for the action row's countdown: a graded response's
 *  `feedback_dwell_ms` from now (null: no hold). */
export function holdUntil(ms: number | null | undefined): number | null {
  return ms != null && ms > 0 ? Date.now() + ms : null;
}

export function VerdictCard({ verdict, credit, reasons = [], concept, before, after, held }: {
  verdict: string;
  credit?: LoopCredit | null;
  reasons?: LoopCreditReason[];
  /** The checked concept's name. */
  concept: string;
  before?: LoopLearnerState | null;
  after?: LoopLearnerState | null;
  /** A confident miss: the next step waits while the student reads (W2.5). */
  held: boolean;
}) {
  const yes = verdict === "correct";
  const title = verdictTitle(verdict, credit, reasons);
  const credited = yes ? creditLine(credit, reasons, concept) : null;
  const skill = skillChangeLine(concept, before, after);
  // As the banner it replaces: it rises into place, and its title confirms the
  // grade — a pulse for a right answer, a shake for a wrong one ("I don't know"
  // is not wrong, so it is not shaken). Keyed by the verdict so a new grade replays it.
  const m = useMotionPresets();
  const pulse = yes ? m.pulse("correct") : verdict === "not_yet" ? m.pulse("wrong") : null;
  return (
    <motion.div
      {...m.fadeUp}
      data-testid="loop-verdict"
      data-verdict={verdict}
      data-credit={yes ? credit ?? undefined : undefined}
      className={`${yes ? tutorStyles.verdictYes : tutorStyles.verdictNo} ${styles.card}`}
    >
      <motion.p key={verdict} {...pulse} className={yes ? `${styles.title} ${styles.yes}` : styles.title}>{title}</motion.p>
      {credited && <p className={styles.line} data-testid="loop-verdict-credit">{credited}</p>}
      {skill && <p className={styles.skill} data-testid="loop-verdict-skill">{skill}</p>}
      {!yes && held && <p className={styles.line} data-testid="loop-verdict-sure">{VERDICT_V2_COPY.sure}</p>}
    </motion.div>
  );
}

type VerdictState = { verdict: string; nodeId: string | null; credit?: LoopCredit | null; reasons?: LoopCreditReason[] };

/** The verdict LoopLearn shows over the feedback: the rebuilt card while
 *  `verdict_v2` is on, else the banner as before. */
export function VerdictSlot({ v2, verdict, next, concept, before, after, held }: {
  v2: boolean;
  verdict: VerdictState;
  /** `nextAfterVerdict`: the banner's "Next up" (the card's is on Continue). */
  next: string | null | undefined;
  concept: string | null;
  /** The learner state at submit, and now. */
  before: Record<string, LoopLearnerState>;
  after: Record<string, LoopLearnerState>;
  held: boolean;
}) {
  if (!v2) return <VerdictBanner verdict={verdict.verdict} credit={verdict.credit} reasons={verdict.reasons} next={next} />;
  const node = verdict.nodeId;
  return (
    <VerdictCard verdict={verdict.verdict} credit={verdict.credit} reasons={verdict.reasons} concept={concept || "this concept"}
      before={node ? before[node] : null} after={node ? after[node] : null} held={held} />
  );
}

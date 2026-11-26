"use client";
// The question card's hint ladder (Tutor redesign phase 4, behind the
// `hint_ladder` flag; design: __fixtures__/question-states.design.html, states
// 1–3). The help ladder is drawn as steps instead of one "Hint" button and the
// latest hint: the hints already taken stay stacked, the next step names its
// cost before it is taken, and a locked hint says why, with a countdown when
// the only thing missing is time alone with the question.
//
// What the costs are, from the backend (learning/evidence.py::evidence_weight):
// a correct answer after hints H1–H3 counts half (WEIGHT_ASSISTED); after the
// worked steps (H4 and up, RUNG_NO_CREDIT_MIN) it counts nothing.
import React, { useCallback, useEffect, useState } from "react";
import { useFlag } from "@/context/FlagsContext";
import styles from "./HintLadder.module.css";

/** The first rung that shows worked steps (backend Rung.H4). */
export const WORKED_RUNG = 4;

export const HINT_LADDER_COPY = {
  locked: "Write what you think first. Hints open after a real try.",
  waiting: "Stay with the question a little longer. Your try counts when the timer ends.",
  hintCost: "Hints: half credit",
  stepsCost: "Worked steps: no credit",
  stepsWarning: "Showing steps means this question won't raise your skill level.",
} as const;

export type HintStep = { rung: number; reply: string };

/** "0:32", "1:05". */
export function clock(seconds: number): string {
  const s = Math.max(0, Math.ceil(seconds));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

/** The next step's button: "Hint", "Hint 2", … and "Show worked steps" once
 *  the next rung is the worked steps. The server decides the rung; the label
 *  reads the one after the last it granted. */
export function nextHintLabel(steps: readonly HintStep[]): string {
  if (nextIsWorkedSteps(steps)) return "Show worked steps";
  const hints = steps.filter((s) => s.rung < WORKED_RUNG).length;
  return hints === 0 ? "Hint" : `Hint ${hints + 1}`;
}

export function nextIsWorkedSteps(steps: readonly HintStep[]): boolean {
  return (steps.at(-1)?.rung ?? 0) + 1 >= WORKED_RUNG;
}

/** Seconds left until `until` (a Date.now() time; null: no countdown). */
export function useCountdown(until: number | null): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (until === null) return;
    const id = window.setInterval(() => {
      const t = Date.now();
      setNow(t);
      if (t >= until) window.clearInterval(id);
    }, 250);
    return () => window.clearInterval(id);
  }, [until]);
  return until === null ? 0 : Math.max(0, (until - now) / 1000);
}

export type HintLadderView = { steps: HintStep[]; waitUntil: number | null };
type Kept = { questionHash: string | null; steps: HintStep[]; waitUntil: number | null };

/** The hints taken on the question on screen and the wait a locked hint
 *  owes, kept per question (another question starts empty). `view` is what
 *  the check card draws: null while the `hint_ladder` flag is off. */
export function useHintSteps(item: { question_hash: string } | null) {
  const questionHash = item?.question_hash ?? null;
  const on = useFlag("hint_ladder") === "on";
  const [kept, setKept] = useState<Kept>({ questionHash, steps: [], waitUntil: null });
  const mine = kept.questionHash === questionHash ? kept : { questionHash, steps: [], waitUntil: null };
  const add = useCallback((rung: number | undefined, reply: string) => {
    setKept((prev) => {
      const steps = prev.questionHash === questionHash ? prev.steps : [];
      return { questionHash, steps: [...steps, { rung: rung ?? (steps.at(-1)?.rung ?? 0) + 1, reply }], waitUntil: null };
    });
  }, [questionHash]);
  const setWaitS = useCallback((seconds: number | null) => {
    setKept((prev) => ({
      questionHash,
      steps: prev.questionHash === questionHash ? prev.steps : [],
      waitUntil: seconds && seconds > 0 ? Date.now() + seconds * 1000 : null,
    }));
  }, [questionHash]);
  const view: HintLadderView | null = on ? { steps: mine.steps, waitUntil: mine.waitUntil } : null;
  return { view, add, setWaitS };
}

/** "Hint 1.", "Hint 2.", "Worked steps." — each step's label, in order. */
export function stepLabels(steps: readonly HintStep[]): string[] {
  const out: string[] = [];
  let hints = 0;
  for (const s of steps) {
    if (s.rung >= WORKED_RUNG) out.push("Worked steps.");
    else out.push(`Hint ${(hints += 1)}.`);
  }
  return out;
}

/** The steps taken, stacked; the latest one is the card's `loop-hint-reply`. */
export function HintSteps({ steps }: { steps: readonly HintStep[] }) {
  if (steps.length === 0) return null;
  const labels = stepLabels(steps);
  return (
    <ol className={styles.steps} data-testid="loop-hint-ladder">
      {steps.map((s, i) => {
        const worked = s.rung >= WORKED_RUNG;
        const last = i === steps.length - 1;
        return (
          <li key={`${i}:${s.rung}`} data-rung={s.rung} data-testid={last ? "loop-hint-reply" : `loop-hint-step-${i}`}
            className={worked ? `${styles.step} ${styles.worked}` : styles.step}>
            <strong className={styles.label}>{labels[i]}</strong> {s.reply}
          </li>
        );
      })}
    </ol>
  );
}

/** What the next step costs, said before it is taken. */
export function HintCost({ steps }: { steps: readonly HintStep[] }) {
  const steps_next = nextIsWorkedSteps(steps);
  if (steps.length === 0 && !steps_next) return null;
  return (
    <div className={styles.cost} data-testid="loop-hint-cost">
      <span>{HINT_LADDER_COPY.hintCost}</span>
      <span>{HINT_LADDER_COPY.stepsCost}</span>
      {steps_next && <p className={styles.warning}>{HINT_LADDER_COPY.stepsWarning}</p>}
    </div>
  );
}

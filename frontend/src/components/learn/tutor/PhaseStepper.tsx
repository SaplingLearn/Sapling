"use client";
import React from "react";
import type { LoopPhase } from "@/lib/api";
import { Icon } from "../../Icon";
import styles from "./tutor.module.css";

/** The session's four steps (wireframe D, "AI Tutor · structured layout v2"),
 *  each with the loop phases it covers. */
const STEPS: readonly { label: string; phases: readonly LoopPhase[] }[] = [
  { label: "Check-in", phases: ["probe"] },
  { label: "Plan", phases: ["plan"] },
  { label: "Learn", phases: ["teach", "check", "feedback"] },
  { label: "Wrap-up", phases: ["close"] },
];

/** The step a loop phase belongs to (0 Check-in … 3 Wrap-up). */
export function stepOf(phase: LoopPhase): number {
  const at = STEPS.findIndex((s) => s.phases.includes(phase));
  return at < 0 ? 0 : at;
}

/**
 * Where the session is, at the top of the conversation: Check-in · Plan ·
 * Learn · Wrap-up, from the loop's own phase (GET /status, and every turn's
 * `phase`). Steps before it carry a tick, the current one its number in bold,
 * later ones are dimmed. An ordered list, the current step marked
 * `aria-current="step"`; a passed step says "done" to a screen reader.
 * A step the loop skipped (an empty plan teaches at once) reads as passed.
 */
export function PhaseStepper({ phase }: { phase: LoopPhase }) {
  const at = stepOf(phase);
  return (
    <ol className={styles.stepper} aria-label="Session progress" data-testid="tutor-phase-stepper">
      {STEPS.map((step, i) => {
        const state = i < at ? "done" : i === at ? "current" : "todo";
        return (
          <li
            key={step.label}
            className={styles.step}
            data-state={state}
            aria-current={state === "current" ? "step" : undefined}
          >
            <span className={styles.stepMark} aria-hidden>
              {state === "done" ? <Icon name="check" size={12} /> : i + 1}
            </span>
            <span className={styles.stepLabel}>{step.label}</span>
            {state === "done" && <span className={styles.sr}> (done)</span>}
          </li>
        );
      })}
    </ol>
  );
}

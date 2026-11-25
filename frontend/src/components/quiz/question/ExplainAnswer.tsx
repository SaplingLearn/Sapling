"use client";

/**
 * W7.2 Explain (design kit 7.16) under the focus SessionTop shell.
 *
 * Tall prose box on the short_answer wire. Optional rubric lines appear after
 * a verdict as informational criteria (overall tone only — no per-row scoring
 * yet). Mic is refused (W6).
 */

import React, { useState } from "react";
import { motion } from "framer-motion";
import type { ExplainInteraction } from "@/lib/quiz/types";
import { isExplainComplete } from "@/lib/quiz/explainInteraction";
import { toneOfVerdict, useKitMotion } from "./kitMotion";

export interface ExplainAnswerProps {
  interaction: ExplainInteraction;
  value: string;
  disabled: boolean;
  expected?: string | null;
  verdict?: "correct" | "incorrect" | null;
  onChange: (value: string) => void;
}

export function ExplainAnswer({
  interaction,
  value,
  disabled,
  verdict,
  onChange,
}: ExplainAnswerProps) {
  const complete = isExplainComplete(value);
  const done = Boolean(verdict);
  const placeholder =
    interaction.placeholder?.trim() || "Type your explanation";
  const rubric = interaction.rubric ?? [];
  const kit = useKitMotion();
  // Marked before the kit appeared (a revisited question): the rubric is
  // already there, so it doesn't stagger in.
  const [doneAtMount] = useState(done);

  return (
    <div
      className="quiz-explain"
      data-testid="quiz-explain"
      data-complete={complete ? "true" : "false"}
      data-verdict={verdict || undefined}
    >
      <motion.textarea
        {...kit.mark(toneOfVerdict(verdict))}
        className="quiz-explain__input field"
        data-testid="quiz-explain-input"
        value={value}
        disabled={disabled || done}
        placeholder={placeholder}
        rows={6}
        aria-label={placeholder}
        onChange={e => onChange(e.target.value)}
      />
      {done && rubric.length > 0 ? (
        <motion.ul
          variants={kit.list.container}
          initial={doneAtMount ? false : "hidden"}
          animate="shown"
          className="quiz-explain__rubric"
          data-testid="quiz-explain-rubric"
          aria-label="Explanation criteria"
        >
          {rubric.map((row, i) => (
            <motion.li
              variants={kit.list.item}
              key={`${i}-${row}`}
              className={`quiz-explain__rubric-row quiz-explain__rubric-row--${verdict === "correct" ? "right" : "wrong"}`}
              data-testid={`quiz-explain-rubric-${i}`}
            >
              {row}
            </motion.li>
          ))}
        </motion.ul>
      ) : null}
    </div>
  );
}

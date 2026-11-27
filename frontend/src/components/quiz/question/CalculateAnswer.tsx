"use client";

/**
 * W7.2 Calculate (design kit 7.13) — value + unit + optional working steps.
 */

import React, { useMemo } from "react";
import { motion } from "framer-motion";
import type { CalculateInteraction } from "@/lib/quiz/types";
import {
  decodeCalculateAnswer,
  encodeCalculateAnswer,
  isCalculateComplete,
} from "@/lib/quiz/calculateInteraction";
import { toneOfVerdict, useKitMotion } from "./kitMotion";

export interface CalculateAnswerProps {
  interaction: CalculateInteraction;
  value: string;
  disabled: boolean;
  expected?: string | null;
  verdict?: "correct" | "incorrect" | null;
  onChange: (value: string) => void;
}

export function CalculateAnswer({
  interaction,
  value,
  disabled,
  verdict,
  onChange,
}: CalculateAnswerProps) {
  const parts = useMemo(() => decodeCalculateAnswer(value), [value]);
  const complete = isCalculateComplete(value);
  const done = Boolean(verdict);
  const locked = disabled || done;
  const kit = useKitMotion();
  const valuePh = interaction.placeholder?.trim() || "Your answer";
  const unitPh = interaction.unitLabel?.trim() || "Units";
  const stepsPh = interaction.stepsPlaceholder?.trim() || "Show your working (optional)";

  const commit = (next: { value?: string; unit?: string; steps?: string }) => {
    if (locked) return;
    onChange(encodeCalculateAnswer(
      next.value ?? parts.value,
      next.unit ?? parts.unit,
      next.steps ?? parts.steps,
    ));
  };

  return (
    <div
      className="quiz-calculate"
      data-testid="quiz-calculate"
      data-complete={complete ? "true" : "false"}
      data-verdict={verdict || undefined}
    >
      <motion.div {...kit.mark(toneOfVerdict(verdict))} className="quiz-calculate__fields">
        <input
          className="quiz-calculate__value field"
          data-testid="quiz-calculate-value"
          type="text"
          inputMode="decimal"
          value={parts.value}
          disabled={locked}
          placeholder={valuePh}
          aria-label={valuePh}
          onChange={e => commit({ value: e.target.value })}
        />
        <input
          className="quiz-calculate__unit field"
          data-testid="quiz-calculate-unit"
          type="text"
          value={parts.unit}
          disabled={locked}
          placeholder={unitPh}
          aria-label={unitPh}
          onChange={e => commit({ unit: e.target.value })}
        />
      </motion.div>
      <label className="quiz-calculate__steps-label label-micro" htmlFor="quiz-calculate-steps">
        Working
      </label>
      <textarea
        id="quiz-calculate-steps"
        className="quiz-calculate__steps field"
        data-testid="quiz-calculate-steps"
        rows={3}
        value={parts.steps}
        disabled={locked}
        placeholder={stepsPh}
        aria-label={stepsPh}
        onChange={e => commit({ steps: e.target.value })}
      />
    </div>
  );
}

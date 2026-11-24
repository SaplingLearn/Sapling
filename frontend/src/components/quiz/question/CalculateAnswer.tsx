"use client";

/**
 * W7.2 Calculate (design kit 7.13) under the focus SessionTop shell.
 *
 * Value + unit fields encode into short_answer `answerText` as `value|unit`.
 * Working-steps UI is deferred. Generation does not emit `interaction` yet.
 */

import React, { useMemo } from "react";
import type { CalculateInteraction } from "@/lib/quiz/types";
import {
  decodeCalculateAnswer,
  encodeCalculateAnswer,
  isCalculateComplete,
} from "@/lib/quiz/calculateInteraction";

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
  const valuePh = interaction.placeholder?.trim() || "Your answer";
  const unitPh = interaction.unitLabel?.trim() || "Units";

  const setValue = (next: string) => {
    if (locked) return;
    onChange(encodeCalculateAnswer(next, parts.unit));
  };
  const setUnit = (next: string) => {
    if (locked) return;
    onChange(encodeCalculateAnswer(parts.value, next));
  };

  return (
    <div
      className="quiz-calculate"
      data-testid="quiz-calculate"
      data-complete={complete ? "true" : "false"}
      data-verdict={verdict || undefined}
    >
      <div className="quiz-calculate__fields">
        <input
          className="quiz-calculate__value field"
          data-testid="quiz-calculate-value"
          type="text"
          inputMode="decimal"
          value={parts.value}
          disabled={locked}
          placeholder={valuePh}
          aria-label={valuePh}
          onChange={e => setValue(e.target.value)}
        />
        <input
          className="quiz-calculate__unit field"
          data-testid="quiz-calculate-unit"
          type="text"
          value={parts.unit}
          disabled={locked}
          placeholder={unitPh}
          aria-label={unitPh}
          onChange={e => setUnit(e.target.value)}
        />
      </div>
    </div>
  );
}

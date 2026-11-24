"use client";

/**
 * W7.2 Compare under the focus SessionTop shell.
 *
 * Two fixed panels + relation chips. Click an option to select; click again to
 * clear. Matches shell tones (plain / lift / right / wrong) without inventing
 * a second answer store: the choice encodes into short_answer `answerText`
 * via `lib/quiz/compareInteraction`.
 *
 * Generation does not emit `interaction` yet — this is the UI stub + fixture
 * path. Verdict card tones compare against `expected` when the server key is
 * the same encode shape.
 */

import React, { useMemo } from "react";
import type { CompareInteraction } from "@/lib/quiz/types";
import {
  decodeCompareAnswer,
  encodeCompareAnswer,
  isCompareComplete,
} from "@/lib/quiz/compareInteraction";

export interface CompareAnswerProps {
  interaction: CompareInteraction;
  value: string;
  disabled: boolean;
  /** Once the verdict may show: mark the chosen chip vs the expected encode. */
  expected?: string | null;
  verdict?: "correct" | "incorrect" | null;
  onChange: (value: string) => void;
}

function optionTone(
  optionId: string,
  chosen: string | null,
  expected: string | null,
  verdict: "correct" | "incorrect" | null | undefined,
): "plain" | "lift" | "right" | "wrong" {
  if (verdict && expected) {
    if (optionId === expected && optionId === chosen) return "right";
    if (optionId === chosen && optionId !== expected) return "wrong";
    if (optionId === expected) return "right";
    return "plain";
  }
  return chosen === optionId ? "lift" : "plain";
}

export function CompareAnswer({
  interaction,
  value,
  disabled,
  expected,
  verdict,
  onChange,
}: CompareAnswerProps) {
  const chosen = useMemo(
    () => decodeCompareAnswer(interaction, value),
    [interaction, value],
  );
  const expectedId = useMemo(
    () => (expected ? decodeCompareAnswer(interaction, expected) : null),
    [interaction, expected],
  );
  const complete = isCompareComplete(interaction, value);
  const done = Boolean(verdict);

  const select = (optionId: string) => {
    if (disabled || done) return;
    onChange(encodeCompareAnswer(chosen === optionId ? null : optionId));
  };

  return (
    <div
      className="quiz-compare"
      data-testid="quiz-compare"
      data-complete={complete ? "true" : "false"}
      data-verdict={verdict || undefined}
    >
      <div className="quiz-compare__sides" data-testid="quiz-compare-sides" aria-label="Items to compare">
        <div
          className="quiz-compare__side"
          data-testid={`quiz-compare-side-${interaction.left.id}`}
          data-side={interaction.left.id}
        >
          <p className="quiz-compare__side-label label-micro">Left</p>
          <p className="quiz-compare__side-body">{interaction.left.label}</p>
        </div>
        <div
          className="quiz-compare__side"
          data-testid={`quiz-compare-side-${interaction.right.id}`}
          data-side={interaction.right.id}
        >
          <p className="quiz-compare__side-label label-micro">Right</p>
          <p className="quiz-compare__side-body">{interaction.right.label}</p>
        </div>
      </div>

      <div
        className="quiz-compare__options"
        data-testid="quiz-compare-options"
        role="group"
        aria-label="How do they compare?"
      >
        {interaction.options.map(opt => (
          <button
            key={opt.id}
            type="button"
            className={`quiz-compare__option quiz-compare__option--${optionTone(opt.id, chosen, expectedId, verdict)}`}
            data-testid={`quiz-compare-option-${opt.id}`}
            aria-pressed={chosen === opt.id}
            disabled={disabled || done}
            onClick={() => select(opt.id)}
          >
            {opt.label}
          </button>
        ))}
      </div>
    </div>
  );
}

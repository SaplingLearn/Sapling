"use client";

/**
 * W7.2 Highlight (design kit 7.10) under the focus SessionTop shell.
 *
 * Click passages to toggle a highlight. Selection encodes into short_answer
 * `answerText` via `lib/quiz/highlightInteraction`. Generation does not emit
 * `interaction` yet — UI stub + fixture path only.
 */

import React, { useMemo } from "react";
import type { HighlightInteraction } from "@/lib/quiz/types";
import {
  decodeHighlightAnswer,
  encodeHighlightAnswer,
  isHighlightComplete,
  toggleHighlightPassage,
} from "@/lib/quiz/highlightInteraction";

export interface HighlightAnswerProps {
  interaction: HighlightInteraction;
  value: string;
  disabled: boolean;
  expected?: string | null;
  verdict?: "correct" | "incorrect" | null;
  onChange: (value: string) => void;
}

function rowTone(
  id: string,
  selected: string[],
  expected: string[],
  verdict: "correct" | "incorrect" | null | undefined,
): "plain" | "lift" | "right" | "wrong" {
  const on = selected.includes(id);
  if (verdict && expected.length) {
    const want = expected.includes(id);
    if (on && want) return "right";
    if (on && !want) return "wrong";
    if (!on && want) return "right";
    return "plain";
  }
  return on ? "lift" : "plain";
}

export function HighlightAnswer({
  interaction,
  value,
  disabled,
  expected,
  verdict,
  onChange,
}: HighlightAnswerProps) {
  const selected = useMemo(
    () => decodeHighlightAnswer(interaction, value),
    [interaction, value],
  );
  const expectedIds = useMemo(
    () => (expected ? decodeHighlightAnswer(interaction, expected) : []),
    [interaction, expected],
  );
  const complete = isHighlightComplete(interaction, value);
  const done = Boolean(verdict);

  const toggle = (id: string) => {
    if (disabled || done) return;
    onChange(encodeHighlightAnswer(toggleHighlightPassage(selected, id)));
  };

  return (
    <div
      className="quiz-highlight"
      data-testid="quiz-highlight"
      data-complete={complete ? "true" : "false"}
      data-verdict={verdict || undefined}
    >
      {interaction.note ? (
        <p className="quiz-highlight__note label-micro" data-testid="quiz-highlight-note">
          {interaction.note}
        </p>
      ) : null}
      <div
        className="quiz-highlight__passages"
        data-testid="quiz-highlight-passages"
        role="group"
        aria-label="Passages to highlight"
      >
        {interaction.passages.map(p => {
          const on = selected.includes(p.id);
          return (
            <button
              key={p.id}
              type="button"
              className={`quiz-highlight__row quiz-highlight__row--${rowTone(p.id, selected, expectedIds, verdict)}`}
              data-testid={`quiz-highlight-row-${p.id}`}
              data-selected={on ? "true" : "false"}
              aria-pressed={on}
              disabled={disabled || done}
              onClick={() => toggle(p.id)}
            >
              {p.label}
            </button>
          );
        })}
      </div>
    </div>
  );
}

"use client";

import React from "react";
import type { QuestionType } from "@/lib/quiz/types";
import {
  expressionParts,
  formatNumber,
  numericValue,
  isWrittenAnswerFormatValid,
} from "@/lib/quiz/answerFormats";

export type WrittenType = Exclude<QuestionType, "multiple_choice">;

const PLACEHOLDER: Record<WrittenType, string> = {
  short_answer: "Type your answer",
  numeric: "e.g. 42, 3/4, 0.75 or 75%",
  symbolic: "e.g. 2(x + 1) or x^2 - 1",
};

export interface WrittenAnswerProps {
  type: WrittenType;
  value: string;
  disabled: boolean;
  onChange: (value: string) => void;
  /** Enter in the input — the screen's primary action, when it is enabled. */
  onSubmit: () => void;
  /** The visible format rules, for `aria-describedby`. */
  describedBy: string;
  /** "Your answer" plus the stem, so focusing the input reads the question. */
  labelledBy?: string;
  numericUnit?: string;
}

export function WrittenAnswer({
  type,
  value,
  disabled,
  onChange,
  onSubmit,
  describedBy,
  labelledBy,
  numericUnit,
}: WrittenAnswerProps) {
  const valid = isWrittenAnswerFormatValid(type, value, numericUnit);

  const readBack = (() => {
    if (!valid) return null;
    if (type === "numeric" && !numericUnit) {
      const n = numericValue(value);
      return n === null
        ? null
        : <>Reads as <span className="quiz-written__value">{formatNumber(n)}</span></>;
    }
    if (type === "symbolic") {
      return (
        <>
          Reads as{" "}
          <span className="quiz-written__value quiz-written__expr">
            {expressionParts(value).map((part, i) =>
              part.sup ? <sup key={i}>{part.text}</sup> : <React.Fragment key={i}>{part.text}</React.Fragment>,
            )}
          </span>
        </>
      );
    }
    return null;
  })();

  return (
    <div className="quiz-written" data-format={type}>
      <input
        id="quiz-written-answer"
        data-testid="quiz-written-answer"
        type="text"
        className={`quiz-question__written-input quiz-written__input--${type}`}
        aria-labelledby={labelledBy}
        aria-describedby={readBack ? `${describedBy} quiz-written-readback` : describedBy}
        aria-invalid={Boolean(value.trim()) && !valid ? true : undefined}
        placeholder={numericUnit ? `e.g. 2.5 ${numericUnit}` : PLACEHOLDER[type]}
        maxLength={2000}
        value={value}
        disabled={disabled}
        onChange={event => onChange(event.target.value)}
        onKeyDown={event => {
          if (event.key !== "Enter" || event.nativeEvent.isComposing) return;
          event.preventDefault();
          if (!disabled && valid) onSubmit();
        }}
        autoComplete="off"
        autoCorrect="off"
        autoCapitalize="off"
        spellCheck={type === "short_answer"}
      />

      {readBack && (
        <p
          id="quiz-written-readback"
          className="quiz-written__readback"
          data-testid="quiz-written-readback"
          aria-live="polite"
        >
          {readBack}
        </p>
      )}
    </div>
  );
}

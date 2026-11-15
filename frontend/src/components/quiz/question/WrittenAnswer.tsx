"use client";

import type { QuestionType } from "@/lib/quiz/types";
import { isWrittenAnswerFormatValid } from "@/lib/quiz/answerFormats";

export type WrittenType = Exclude<QuestionType, "multiple_choice">;

export interface WrittenAnswerProps {
  type: WrittenType;
  value: string;
  disabled: boolean;
  onChange: (value: string) => void;
  /** Enter in the input — the screen's primary action, when it is enabled. */
  onSubmit: () => void;
  /** The visible format rules, for `aria-describedby`. */
  describedBy?: string;
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

  return (
    <div className="quiz-written" data-format={type}>
      <input
        id="quiz-written-answer"
        data-testid="quiz-written-answer"
        type="text"
        className={`quiz-question__written-input quiz-written__input--${type}`}
        aria-labelledby={labelledBy}
        aria-describedby={describedBy}
        aria-invalid={Boolean(value.trim()) && !valid ? true : undefined}
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
    </div>
  );
}

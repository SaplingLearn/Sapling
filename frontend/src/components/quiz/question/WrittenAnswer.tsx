"use client";

/**
 * The answer input for the three written formats, each shaped to what it
 * asks for rather than one free-text box for all three:
 *
 * - short_answer: one line of text. The key is a term or brief fact (at most
 *   eight words, `routes/quiz.py`), so a paragraph box invited the very
 *   sentences the grader can never match.
 * - numeric: one line, the decimal keypad on a phone, keys for what that pad
 *   lacks (− / % and ×10ⁿ), and a live "Reads as 0.75" so a student sees
 *   their fraction or percentage parsed before they submit it.
 * - symbolic: one monospace line, keys for powers, brackets and operators,
 *   and a live preview with real superscripts (2x^2 reads as 2x²), plus a
 *   plain warning for what the grammar refuses (functions, equations, an
 *   unclosed bracket).
 *
 * Enter submits from all three. The screen's own Enter handler skips typing
 * targets (it would steal a textarea's newline), so the input forwards Enter
 * itself — a single-line answer has no newline to lose.
 */

import React from "react";
import type { QuestionType } from "@/lib/quiz/types";
import {
  expressionParts,
  formatNumber,
  numericValue,
  symbolicProblem,
} from "@/lib/quiz/answerFormats";

export type WrittenType = Exclude<QuestionType, "multiple_choice">;

/** A key on the format's symbol row. `caret` is where the cursor lands,
 *  counted from the start of the inserted text (default: after it). */
interface Key {
  id: string;
  label: string;
  insert: string;
  caret?: number;
  ariaLabel: string;
}

const NUMERIC_KEYS: Key[] = [
  { id: "minus", label: "−", insert: "-", ariaLabel: "Insert minus sign" },
  { id: "fraction", label: "/", insert: "/", ariaLabel: "Insert fraction bar" },
  { id: "percent", label: "%", insert: "%", ariaLabel: "Insert percent sign" },
  { id: "exponent", label: "×10ⁿ", insert: "e", ariaLabel: "Insert times ten to the power (e notation)" },
];

const SYMBOLIC_KEYS: Key[] = [
  { id: "squared", label: "x²", insert: "^2", ariaLabel: "Insert squared" },
  { id: "power", label: "xⁿ", insert: "^", ariaLabel: "Insert power" },
  { id: "brackets", label: "( )", insert: "()", caret: 1, ariaLabel: "Insert brackets" },
  { id: "times", label: "×", insert: "*", ariaLabel: "Insert multiplication sign" },
  { id: "divide", label: "÷", insert: "/", ariaLabel: "Insert division sign" },
  { id: "minus", label: "−", insert: "-", ariaLabel: "Insert minus sign" },
];

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
}

export function WrittenAnswer({
  type,
  value,
  disabled,
  onChange,
  onSubmit,
  describedBy,
  labelledBy,
}: WrittenAnswerProps) {
  const inputRef = React.useRef<HTMLInputElement>(null);
  const keys = type === "numeric" ? NUMERIC_KEYS : type === "symbolic" ? SYMBOLIC_KEYS : [];

  /** Put `key` in at the cursor (replacing any selection) and keep typing. */
  const insert = (key: Key) => {
    const input = inputRef.current;
    const start = input?.selectionStart ?? value.length;
    const end = input?.selectionEnd ?? value.length;
    onChange(value.slice(0, start) + key.insert + value.slice(end));
    const caret = start + (key.caret ?? key.insert.length);
    // After React has written the new value back into the input.
    requestAnimationFrame(() => {
      inputRef.current?.focus();
      inputRef.current?.setSelectionRange(caret, caret);
    });
  };

  const readBack = (() => {
    if (!value.trim()) return null;
    if (type === "numeric") {
      const n = numericValue(value);
      return n === null
        ? { ok: false, node: "Not a number the grader can read yet." }
        : { ok: true, node: <>Reads as <span className="quiz-written__value">{formatNumber(n)}</span></> };
    }
    if (type === "symbolic") {
      const problem = symbolicProblem(value);
      if (problem) return { ok: false, node: problem };
      return {
        ok: true,
        node: (
          <>
            Reads as{" "}
            <span className="quiz-written__value quiz-written__expr">
              {expressionParts(value).map((part, i) =>
                part.sup ? <sup key={i}>{part.text}</sup> : <React.Fragment key={i}>{part.text}</React.Fragment>,
              )}
            </span>
          </>
        ),
      };
    }
    return null;
  })();

  return (
    <div className="quiz-written" data-format={type}>
      <input
        ref={inputRef}
        id="quiz-written-answer"
        data-testid="quiz-written-answer"
        type="text"
        className={`quiz-question__written-input quiz-written__input--${type}`}
        aria-labelledby={labelledBy}
        aria-describedby={readBack ? `${describedBy} quiz-written-readback` : describedBy}
        aria-invalid={readBack && !readBack.ok ? true : undefined}
        inputMode={type === "numeric" ? "decimal" : "text"}
        placeholder={PLACEHOLDER[type]}
        maxLength={2000}
        value={value}
        disabled={disabled}
        onChange={event => onChange(event.target.value)}
        onKeyDown={event => {
          if (event.key !== "Enter" || event.nativeEvent.isComposing) return;
          event.preventDefault();
          onSubmit();
        }}
        autoComplete="off"
        autoCorrect="off"
        autoCapitalize="off"
        spellCheck={type === "short_answer"}
      />

      {keys.length > 0 && (
        <div className="quiz-written__keys" role="group" aria-label="Insert a symbol">
          {keys.map(key => (
            <button
              key={key.id}
              type="button"
              className="quiz-written__key"
              data-testid={`quiz-key-${key.id}`}
              aria-label={key.ariaLabel}
              disabled={disabled}
              // Keep focus (and the cursor) in the input.
              onMouseDown={event => event.preventDefault()}
              onClick={() => insert(key)}
            >
              {key.label}
            </button>
          ))}
        </div>
      )}

      {readBack && (
        <p
          id="quiz-written-readback"
          className="quiz-written__readback"
          data-testid="quiz-written-readback"
          data-ok={readBack.ok ? "true" : "false"}
          aria-live="polite"
        >
          {readBack.node}
        </p>
      )}
    </div>
  );
}

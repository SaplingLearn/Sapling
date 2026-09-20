"use client";
import React from "react";

/**
 * AnswerOption — one row of a multiple-choice question (#537).
 *
 * The radio row the quiz question screen builds its answer list from. Three
 * things it guarantees:
 *   1. Selection is a 2px LEFT bar, not a full border — and the resting state
 *      reserves the same 2px transparent, so picking an answer never nudges
 *      the text.
 *   2. The ✓/✕ slot is always reserved (20px, right-aligned), so revealing the
 *      verdict doesn't reflow the row either.
 *   3. Nothing is signalled by colour alone: `correct` also gets a mark and a
 *      spoken suffix, `chosen-wrong` its own mark and suffix.
 *
 * It is a `<button role="radio">`, so Enter/Space select for free. `disabled`
 * maps to `aria-disabled` rather than the DOM attribute: a revealed answer row
 * must stay focusable and readable, it just stops responding.
 *
 * The roving tab stop belongs to the GROUP, so the screen passes `tabIndex`.
 * The default (checked → 0, else -1) is right once something is selected; a
 * group with nothing selected must give its first row `tabIndex={0}`.
 */
export type AnswerState = "default" | "selected" | "correct" | "chosen-wrong" | "muted";

const SUFFIX: Partial<Record<AnswerState, string>> = {
  correct: " — correct answer",
  "chosen-wrong": " — your answer, incorrect",
};

const MARK: Partial<Record<AnswerState, string>> = {
  correct: "✓",
  "chosen-wrong": "✕",
};

export interface AnswerOptionProps {
  letter: string;
  text: string;
  state: AnswerState;
  disabled?: boolean;
  onSelect?: () => void;
  /** Roving tab stop, owned by the enclosing radiogroup. */
  tabIndex?: number;
  testid?: string;
}

export function AnswerOption({
  letter,
  text,
  state,
  disabled = false,
  onSelect,
  tabIndex,
  testid,
}: AnswerOptionProps) {
  const checked = state === "selected" || state === "chosen-wrong";
  const mark = MARK[state];

  return (
    <button
      type="button"
      role="radio"
      aria-checked={checked}
      aria-disabled={disabled || undefined}
      aria-label={`${letter}. ${text}${SUFFIX[state] ?? ""}`}
      tabIndex={tabIndex ?? (checked ? 0 : -1)}
      className={`answer-option answer-option--${state}`}
      data-testid={testid}
      onClick={() => {
        if (disabled) return;
        onSelect?.();
      }}
    >
      <span className="answer-option__letter label-micro" aria-hidden="true">
        {letter}
      </span>
      <span className="answer-option__text">{text}</span>
      <span className="answer-option__mark" aria-hidden="true">
        {mark}
      </span>
    </button>
  );
}

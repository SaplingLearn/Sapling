"use client";
import React, { useMemo } from "react";

import { useRadioGroup } from "./useRadioGroup";

/** The served options of an `mc_reason` item, in stored order; the UI never
 *  marks one correct (A22). A radio group (spec §13 A135) named by the question
 *  (`labelledBy`): one tab stop, the arrow keys move and choose, Home / End
 *  choose the ends (`useRadioGroup`, shared with ConfidenceControl). Its tab
 *  stop carries `data-answer-start`, so a new question focuses it. Shared by
 *  the check-in and check cards (LoopLearn) and the segment prequestion
 *  (PrequestionCard, spec §13 A138). */
export function OptionList({
  options,
  selected,
  onSelect,
  testIdPrefix,
  labelledBy,
  disabled,
}: {
  options: { letter: string; text: string }[];
  selected: string;
  onSelect: (letter: string) => void;
  testIdPrefix: string;
  labelledBy: string;
  disabled?: boolean;
}) {
  const letters = useMemo(() => options.map((o) => o.letter), [options]);
  const group = useRadioGroup(letters, selected || null, onSelect);
  return (
    <div
      role="radiogroup"
      aria-labelledby={labelledBy}
      data-testid={`${testIdPrefix}s`}
      style={{ display: "flex", flexDirection: "column", gap: 6 }}
    >
      {options.map((o, i) => {
        const on = selected === o.letter;
        const radio = group.optionProps(i);
        return (
          <button
            key={o.letter}
            {...radio}
            type="button"
            // "B. It writes …": the letter and the text read as one name
            aria-label={`${o.letter}. ${o.text}`}
            data-answer-start={radio.tabIndex === 0 ? "" : undefined}
            data-testid={`${testIdPrefix}-${o.letter}`}
            disabled={disabled}
            onClick={() => onSelect(o.letter)}
            style={{
              display: "flex",
              gap: 10,
              alignItems: "flex-start",
              textAlign: "left",
              padding: "9px 12px",
              borderRadius: "var(--r-md)",
              border: `1px solid ${on ? "var(--accent-border)" : "var(--border)"}`,
              background: on ? "var(--accent-soft)" : "var(--bg-panel)",
              fontSize: 14,
              cursor: disabled ? "default" : "pointer",
              color: "var(--text)",
            }}
          >
            <strong style={{ minWidth: 16 }}>{o.letter}</strong>
            <span>{o.text}</span>
          </button>
        );
      })}
    </div>
  );
}

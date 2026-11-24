"use client";

/**
 * W7.2 Sequence (kit 7.2) under the focus SessionTop shell.
 *
 * Click-to-assign (no drag): select a tray card, then a numbered slot — or
 * click a placed card to return it to the tray. Matches shell tones
 * (plain / lift / right / wrong) without inventing a second answer store:
 * order encodes into the short_answer `answerText` via
 * `lib/quiz/sequenceInteraction`.
 *
 * Generation does not emit `interaction` yet — this is the UI stub + fixture
 * path. Verdict card tones compare against `expected` when the server key is
 * the same encode shape.
 */

import React, { useMemo, useState } from "react";
import type { SequenceInteraction } from "@/lib/quiz/types";
import {
  decodeSequenceAnswer,
  encodeSequenceAnswer,
  isSequenceComplete,
  placeSequenceItem,
  type SequenceAssignment,
} from "@/lib/quiz/sequenceInteraction";

export interface SequenceAnswerProps {
  interaction: SequenceInteraction;
  value: string;
  disabled: boolean;
  /** Once the verdict may show: mark cards vs the expected encode. */
  expected?: string | null;
  verdict?: "correct" | "incorrect" | null;
  onChange: (value: string) => void;
}

function cardTone(
  stepId: string,
  assign: SequenceAssignment,
  expected: SequenceAssignment | null,
  verdict: "correct" | "incorrect" | null | undefined,
  selected: boolean,
): "plain" | "lift" | "right" | "wrong" {
  if (verdict && expected) {
    const got = assign[stepId];
    const want = expected[stepId];
    if (typeof got === "number" && got === want) return "right";
    if (typeof got === "number") return "wrong";
  }
  return selected ? "lift" : "plain";
}

export function SequenceAnswer({
  interaction,
  value,
  disabled,
  expected,
  verdict,
  onChange,
}: SequenceAnswerProps) {
  const assign = useMemo(
    () => decodeSequenceAnswer(interaction, value),
    [interaction, value],
  );
  const expectedAssign = useMemo(
    () => (expected ? decodeSequenceAnswer(interaction, expected) : null),
    [interaction, expected],
  );
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const complete = isSequenceComplete(interaction, assign);
  const tray = interaction.steps.filter(it => assign[it.id] == null);
  const done = Boolean(verdict);
  const n = interaction.steps.length;

  const commit = (next: SequenceAssignment) => {
    onChange(encodeSequenceAnswer(interaction, next));
  };

  const selectOrReturn = (stepId: string) => {
    if (disabled || done) return;
    if (assign[stepId] != null) {
      setSelectedId(null);
      commit(placeSequenceItem(assign, stepId, null));
      return;
    }
    setSelectedId(prev => (prev === stepId ? null : stepId));
  };

  const placeOnSlot = (slot: number) => {
    if (disabled || done || selectedId == null) return;
    commit(placeSequenceItem(assign, selectedId, slot));
    setSelectedId(null);
  };

  return (
    <div
      className="quiz-sequence"
      data-testid="quiz-sequence"
      data-complete={complete ? "true" : "false"}
      data-verdict={verdict || undefined}
    >
      <ol
        className="quiz-sequence__slots"
        data-testid="quiz-sequence-slots"
        aria-label="Order the steps"
      >
        {Array.from({ length: n }, (_, slot) => {
          const placed = interaction.steps.find(it => assign[it.id] === slot);
          const canDrop = selectedId != null && !disabled && !done;
          return (
            <li
              key={slot}
              className={`quiz-sequence__slot${canDrop ? " quiz-sequence__slot--target" : ""}`}
              data-testid={`quiz-sequence-slot-${slot}`}
              data-slot={slot}
            >
              <button
                type="button"
                className="quiz-sequence__slot-hit"
                aria-label={`Place in position ${slot + 1}`}
                disabled={!canDrop}
                onClick={() => placeOnSlot(slot)}
              >
                <span className="quiz-sequence__slot-num" aria-hidden="true">
                  {slot + 1}
                </span>
                {!placed && !done && (
                  <span className="quiz-sequence__slot-hint">
                    {canDrop ? "Tap to place" : "Drop a step here"}
                  </span>
                )}
              </button>
              {placed && (
                <button
                  type="button"
                  className={`quiz-sequence__card quiz-sequence__card--${cardTone(
                    placed.id,
                    assign,
                    expectedAssign,
                    verdict,
                    false,
                  )}`}
                  data-testid={`quiz-sequence-item-${placed.id}`}
                  disabled={disabled || done}
                  onClick={() => selectOrReturn(placed.id)}
                >
                  {placed.label}
                </button>
              )}
            </li>
          );
        })}
      </ol>

      {!done && (
        <div className="quiz-sequence__tray" data-testid="quiz-sequence-tray" aria-label="Steps to place">
          <p className="quiz-sequence__tray-label label-micro">Steps</p>
          {tray.length === 0 ? (
            <p className="quiz-sequence__tray-empty" data-testid="quiz-sequence-tray-empty">
              Every step is placed.
            </p>
          ) : (
            <ul className="quiz-sequence__cards">
              {tray.map(it => (
                <li key={it.id}>
                  <button
                    type="button"
                    className={`quiz-sequence__card quiz-sequence__card--${cardTone(
                      it.id,
                      assign,
                      expectedAssign,
                      verdict,
                      selectedId === it.id,
                    )}`}
                    data-testid={`quiz-sequence-item-${it.id}`}
                    aria-pressed={selectedId === it.id}
                    disabled={disabled}
                    onClick={() => selectOrReturn(it.id)}
                  >
                    {it.label}
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}

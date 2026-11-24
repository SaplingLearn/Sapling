"use client";

/**
 * W7.2 Build (design kit ~7.x construct) under the focus SessionTop shell.
 *
 * Click-to-assign (no drag): select a tray card, then a slot — or click a
 * placed card to return it to the tray. Matches shell tones (plain / lift /
 * right / wrong) without inventing a second answer store: placements encode
 * into the short_answer `answerText` via `lib/quiz/buildInteraction`.
 *
 * Generation does not emit `interaction` yet — this is the UI stub + fixture
 * path. Verdict card tones compare against `expected` when the server key is
 * the same encode shape.
 */

import React, { useMemo, useState } from "react";
import type { BuildInteraction } from "@/lib/quiz/types";
import {
  decodeBuildAnswer,
  encodeBuildAnswer,
  isBuildComplete,
  placeBuildItem,
  type BuildAssignment,
} from "@/lib/quiz/buildInteraction";

export interface BuildAnswerProps {
  interaction: BuildInteraction;
  value: string;
  disabled: boolean;
  /** Once the verdict may show: mark cards vs the expected encode. */
  expected?: string | null;
  verdict?: "correct" | "incorrect" | null;
  onChange: (value: string) => void;
}

function cardTone(
  partId: string,
  assign: BuildAssignment,
  expected: BuildAssignment | null,
  verdict: "correct" | "incorrect" | null | undefined,
  selected: boolean,
): "plain" | "lift" | "right" | "wrong" {
  if (verdict && expected) {
    const got = assign[partId];
    const want = expected[partId];
    if (typeof got === "number" && got === want) return "right";
    if (typeof got === "number") return "wrong";
  }
  return selected ? "lift" : "plain";
}

export function BuildAnswer({
  interaction,
  value,
  disabled,
  expected,
  verdict,
  onChange,
}: BuildAnswerProps) {
  const assign = useMemo(
    () => decodeBuildAnswer(interaction, value),
    [interaction, value],
  );
  const expectedAssign = useMemo(
    () => (expected ? decodeBuildAnswer(interaction, expected) : null),
    [interaction, expected],
  );
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const complete = isBuildComplete(interaction, assign);
  const tray = interaction.parts.filter(it => assign[it.id] == null);
  const done = Boolean(verdict);

  const commit = (next: BuildAssignment) => {
    onChange(encodeBuildAnswer(interaction, next));
  };

  const selectOrReturn = (partId: string) => {
    if (disabled || done) return;
    if (assign[partId] != null) {
      setSelectedId(null);
      commit(placeBuildItem(assign, partId, null));
      return;
    }
    setSelectedId(prev => (prev === partId ? null : partId));
  };

  const placeOnSlot = (slot: number) => {
    if (disabled || done || selectedId == null) return;
    commit(placeBuildItem(assign, selectedId, slot));
    setSelectedId(null);
  };

  return (
    <div
      className="quiz-build"
      data-testid="quiz-build"
      data-complete={complete ? "true" : "false"}
      data-verdict={verdict || undefined}
    >
      <div
        className="quiz-build__slots"
        style={{ gridTemplateColumns: `repeat(${Math.min(interaction.slots.length, 4)}, minmax(0, 1fr))` }}
        data-testid="quiz-build-slots"
        aria-label="Slots to fill"
      >
        {interaction.slots.map((slot, slotIndex) => {
          const placed = interaction.parts.find(it => assign[it.id] === slotIndex);
          const canDrop = selectedId != null && !disabled && !done;
          return (
            <div
              key={slot.id}
              className={`quiz-build__slot${canDrop ? " quiz-build__slot--target" : ""}`}
              data-testid={`quiz-build-slot-${slot.id}`}
              data-slot={slot.id}
            >
              <button
                type="button"
                className="quiz-build__slot-hit"
                aria-label={`Place on ${slot.label}`}
                disabled={!canDrop}
                onClick={() => placeOnSlot(slotIndex)}
              >
                <span className="quiz-build__slot-num" aria-hidden="true">
                  {slot.label}
                </span>
                {!placed && !done && (
                  <span className="quiz-build__slot-hint">
                    {canDrop ? "Tap to place" : "Drop a part here"}
                  </span>
                )}
              </button>
              {placed && (
                <button
                  type="button"
                  className={`quiz-build__card quiz-build__card--${cardTone(placed.id, assign, expectedAssign, verdict, false)}`}
                  data-testid={`quiz-build-item-${placed.id}`}
                  disabled={disabled || done}
                  onClick={() => selectOrReturn(placed.id)}
                >
                  {placed.label}
                </button>
              )}
            </div>
          );
        })}
      </div>

      {!done && (
        <div className="quiz-build__tray" data-testid="quiz-build-tray" aria-label="Parts to place">
          <p className="quiz-build__tray-label label-micro">Parts</p>
          {tray.length === 0 ? (
            <p className="quiz-build__tray-empty" data-testid="quiz-build-tray-empty">
              Every part is placed.
            </p>
          ) : (
            <ul className="quiz-build__cards">
              {tray.map(it => (
                <li key={it.id}>
                  <button
                    type="button"
                    className={`quiz-build__card quiz-build__card--${cardTone(it.id, assign, expectedAssign, verdict, selectedId === it.id)}`}
                    data-testid={`quiz-build-item-${it.id}`}
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

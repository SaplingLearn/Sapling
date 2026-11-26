"use client";

/**
 * W7.2 Label (kit 7.4) under the focus SessionTop shell.
 *
 * Click-to-assign (no drag): select a tray card, then a numbered spot — or
 * click a placed card to return it to the tray. Diagram SVG paths from the
 * design kit are deferred; spots render as a simple region grid. Matches
 * shell tones (plain / lift / right / wrong) without inventing a second
 * answer store: placements encode into the short_answer `answerText` via
 * `lib/quiz/labelInteraction`.
 *
 * Generation does not emit `interaction` yet — this is the UI stub + fixture
 * path. Verdict card tones compare against `expected` when the server key is
 * the same encode shape.
 */

import React, { useMemo, useState } from "react";
import type { LabelInteraction } from "@/lib/quiz/types";
import {
  decodeLabelAnswer,
  encodeLabelAnswer,
  isLabelComplete,
  placeLabelItem,
  type LabelAssignment,
} from "@/lib/quiz/labelInteraction";
import { KitPiece, useKitMotion, type KitTone } from "./kitMotion";

/** More spots than this wrap onto a second row. */
const MAX_SPOT_COLUMNS = 4;

export interface LabelAnswerProps {
  interaction: LabelInteraction;
  value: string;
  disabled: boolean;
  /** Once the verdict may show: mark cards vs the expected encode. */
  expected?: string | null;
  verdict?: "correct" | "incorrect" | null;
  onChange: (value: string) => void;
}

function cardTone(
  labelId: string,
  assign: LabelAssignment,
  expected: LabelAssignment | null,
  verdict: "correct" | "incorrect" | null | undefined,
  selected: boolean,
): KitTone {
  if (verdict && expected) {
    const got = assign[labelId];
    const want = expected[labelId];
    if (typeof got === "number" && got === want) return "right";
    if (typeof got === "number") return "wrong";
  }
  return selected ? "lift" : "plain";
}

export function LabelAnswer({
  interaction,
  value,
  disabled,
  expected,
  verdict,
  onChange,
}: LabelAnswerProps) {
  const assign = useMemo(
    () => decodeLabelAnswer(interaction, value),
    [interaction, value],
  );
  const expectedAssign = useMemo(
    () => (expected ? decodeLabelAnswer(interaction, expected) : null),
    [interaction, expected],
  );
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const kit = useKitMotion();
  const complete = isLabelComplete(interaction, assign);
  const tray = interaction.labels.filter(it => assign[it.id] == null);
  const done = Boolean(verdict);

  const commit = (next: LabelAssignment) => {
    onChange(encodeLabelAnswer(interaction, next));
  };

  const selectOrReturn = (labelId: string) => {
    if (disabled || done) return;
    if (assign[labelId] != null) {
      setSelectedId(null);
      commit(placeLabelItem(assign, labelId, null));
      return;
    }
    setSelectedId(prev => (prev === labelId ? null : labelId));
  };

  const placeOnSpot = (spot: number) => {
    if (disabled || done || selectedId == null) return;
    commit(placeLabelItem(assign, selectedId, spot));
    setSelectedId(null);
  };

  return (
    <div
      className="quiz-label"
      data-testid="quiz-label"
      data-complete={complete ? "true" : "false"}
      data-verdict={verdict || undefined}
    >
      <div
        className="quiz-label__spots"
        style={{ "--quiz-kit-cols": Math.min(interaction.spots.length, MAX_SPOT_COLUMNS) } as React.CSSProperties}
        data-testid="quiz-label-spots"
        aria-label="Regions to label"
      >
        {interaction.spots.map((spot, spotIndex) => {
          const placed = interaction.labels.find(it => assign[it.id] === spotIndex);
          const canDrop = selectedId != null && !disabled && !done;
          return (
            <div
              key={spot.id}
              className={`quiz-label__spot${canDrop ? " quiz-label__spot--target" : ""}`}
              data-testid={`quiz-label-spot-${spot.id}`}
              data-spot={spot.id}
            >
              <button
                type="button"
                className="quiz-label__spot-hit"
                aria-label={`Place on ${spot.label}`}
                disabled={!canDrop}
                onClick={() => placeOnSpot(spotIndex)}
              >
                <span className="quiz-label__spot-num" aria-hidden="true">
                  {spot.label}
                </span>
                {!placed && !done && (
                  <span className="quiz-label__spot-hint">
                    {canDrop ? "Tap to place" : "Drop a label here"}
                  </span>
                )}
              </button>
              {placed && (
                <KitPiece
                  kit={kit}
                  pieceId={placed.id}
                  block="quiz-label__card"
                  tone={cardTone(placed.id, assign, expectedAssign, verdict, false)}
                  movable={!done}
                  data-testid={`quiz-label-item-${placed.id}`}
                  disabled={disabled || done}
                  onClick={() => selectOrReturn(placed.id)}
                >
                  {placed.label}
                </KitPiece>
              )}
            </div>
          );
        })}
      </div>

      {!done && (
        <div className="quiz-label__tray" data-testid="quiz-label-tray" aria-label="Labels to place">
          <p className="quiz-label__tray-label label-micro">Labels</p>
          {tray.length === 0 ? (
            <p className="quiz-label__tray-empty" data-testid="quiz-label-tray-empty">
              Every label is placed.
            </p>
          ) : (
            <ul className="quiz-label__cards">
              {tray.map(it => (
                <li key={it.id}>
                  <KitPiece
                    kit={kit}
                    pieceId={it.id}
                    block="quiz-label__card"
                    tone={cardTone(it.id, assign, expectedAssign, verdict, selectedId === it.id)}
                    movable={!done}
                    data-testid={`quiz-label-item-${it.id}`}
                    aria-pressed={selectedId === it.id}
                    disabled={disabled}
                    onClick={() => selectOrReturn(it.id)}
                  >
                    {it.label}
                  </KitPiece>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}

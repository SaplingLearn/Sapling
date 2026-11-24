"use client";

/**
 * W7.2 Position (design kit 7.12) — click-to-assign markers onto scale stops.
 */

import React, { useMemo, useState } from "react";
import type { PositionInteraction } from "@/lib/quiz/types";
import {
  decodePositionAnswer,
  encodePositionAnswer,
  isPositionComplete,
  placePositionMarker,
  type PositionAssignment,
} from "@/lib/quiz/positionInteraction";

export interface PositionAnswerProps {
  interaction: PositionInteraction;
  value: string;
  disabled: boolean;
  expected?: string | null;
  verdict?: "correct" | "incorrect" | null;
  onChange: (value: string) => void;
}

function cardTone(
  markerId: string,
  assign: PositionAssignment,
  expected: PositionAssignment | null,
  verdict: "correct" | "incorrect" | null | undefined,
  selected: boolean,
): "plain" | "lift" | "right" | "wrong" {
  if (verdict && expected) {
    const got = assign[markerId];
    const want = expected[markerId];
    if (got && got === want) return "right";
    if (got) return "wrong";
  }
  return selected ? "lift" : "plain";
}

export function PositionAnswer({
  interaction,
  value,
  disabled,
  expected,
  verdict,
  onChange,
}: PositionAnswerProps) {
  const assign = useMemo(
    () => decodePositionAnswer(interaction, value),
    [interaction, value],
  );
  const expectedAssign = useMemo(
    () => (expected ? decodePositionAnswer(interaction, expected) : null),
    [interaction, expected],
  );
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const complete = isPositionComplete(interaction, assign);
  const tray = interaction.markers.filter(m => assign[m.id] == null);
  const done = Boolean(verdict);

  const commit = (next: PositionAssignment) => {
    onChange(encodePositionAnswer(interaction, next));
  };

  const selectOrReturn = (markerId: string) => {
    if (disabled || done) return;
    if (assign[markerId] != null) {
      setSelectedId(null);
      commit(placePositionMarker(assign, markerId, null));
      return;
    }
    setSelectedId(prev => (prev === markerId ? null : markerId));
  };

  const placeOnStop = (stopId: string) => {
    if (disabled || done || selectedId == null) return;
    commit(placePositionMarker(assign, selectedId, stopId));
    setSelectedId(null);
  };

  return (
    <div
      className="quiz-position"
      data-testid="quiz-position"
      data-complete={complete ? "true" : "false"}
      data-verdict={verdict || undefined}
    >
      {interaction.axisLabel ? (
        <p className="quiz-position__axis label-micro" data-testid="quiz-position-axis">
          {interaction.axisLabel}
        </p>
      ) : null}
      <div
        className="quiz-position__stops"
        data-testid="quiz-position-stops"
        aria-label="Scale stops"
      >
        {interaction.stops.map(stop => {
          const placed = interaction.markers.find(m => assign[m.id] === stop.id);
          const canDrop = selectedId != null && !disabled && !done;
          return (
            <div
              key={stop.id}
              className={`quiz-position__stop${canDrop ? " quiz-position__stop--target" : ""}`}
              data-testid={`quiz-position-stop-${stop.id}`}
              data-stop={stop.id}
            >
              <button
                type="button"
                className="quiz-position__stop-hit"
                aria-label={`Place on ${stop.label}`}
                disabled={!canDrop}
                onClick={() => placeOnStop(stop.id)}
              >
                <span className="quiz-position__stop-label">{stop.label}</span>
                {!placed && !done && (
                  <span className="quiz-position__stop-hint">
                    {canDrop ? "Tap to place" : "Drop a marker"}
                  </span>
                )}
              </button>
              {placed && (
                <button
                  type="button"
                  className={`quiz-position__card quiz-position__card--${cardTone(placed.id, assign, expectedAssign, verdict, false)}`}
                  data-testid={`quiz-position-item-${placed.id}`}
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
        <div className="quiz-position__tray" data-testid="quiz-position-tray" aria-label="Markers">
          <p className="quiz-position__tray-label label-micro">Markers</p>
          {tray.length === 0 ? (
            <p className="quiz-position__tray-empty" data-testid="quiz-position-tray-empty">
              Every marker is placed.
            </p>
          ) : (
            <ul className="quiz-position__cards">
              {tray.map(m => (
                <li key={m.id}>
                  <button
                    type="button"
                    className={`quiz-position__card quiz-position__card--${cardTone(m.id, assign, expectedAssign, verdict, selectedId === m.id)}`}
                    data-testid={`quiz-position-item-${m.id}`}
                    aria-pressed={selectedId === m.id}
                    disabled={disabled}
                    onClick={() => selectOrReturn(m.id)}
                  >
                    {m.label}
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

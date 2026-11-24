"use client";

/**
 * W7.2 Sort (kit 7.1) under the focus SessionTop shell.
 *
 * Click-to-assign (no drag): select a card, then a bucket — or click a placed
 * card to return it to the tray. Matches shell tones (plain / lift / right /
 * wrong) without inventing a second answer store: placements encode into the
 * short_answer `answerText` via `lib/quiz/sortInteraction`.
 *
 * Generation does not emit `interaction` yet — this is the UI stub + fixture
 * path. Verdict card tones compare against `expected` when the server key is
 * the same encode shape.
 */

import React, { useMemo, useState } from "react";
import type { SortInteraction } from "@/lib/quiz/types";
import {
  decodeSortAnswer,
  encodeSortAnswer,
  isSortComplete,
  placeSortItem,
  type SortAssignment,
} from "@/lib/quiz/sortInteraction";

export interface SortAnswerProps {
  interaction: SortInteraction;
  value: string;
  disabled: boolean;
  /** Once the verdict may show: mark cards vs the expected encode. */
  expected?: string | null;
  verdict?: "correct" | "incorrect" | null;
  onChange: (value: string) => void;
}

function cardTone(
  itemId: string,
  assign: SortAssignment,
  expected: SortAssignment | null,
  verdict: "correct" | "incorrect" | null | undefined,
  selected: boolean,
): "plain" | "lift" | "right" | "wrong" {
  if (verdict && expected) {
    const got = assign[itemId];
    const want = expected[itemId];
    if (typeof got === "number" && got === want) return "right";
    if (typeof got === "number") return "wrong";
  }
  return selected ? "lift" : "plain";
}

export function SortAnswer({
  interaction,
  value,
  disabled,
  expected,
  verdict,
  onChange,
}: SortAnswerProps) {
  const assign = useMemo(
    () => decodeSortAnswer(interaction, value),
    [interaction, value],
  );
  const expectedAssign = useMemo(
    () => (expected ? decodeSortAnswer(interaction, expected) : null),
    [interaction, expected],
  );
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const complete = isSortComplete(interaction, assign);
  const tray = interaction.items.filter(it => assign[it.id] == null);
  const done = Boolean(verdict);

  const commit = (next: SortAssignment) => {
    onChange(encodeSortAnswer(interaction, next));
  };

  const selectOrReturn = (itemId: string) => {
    if (disabled || done) return;
    if (assign[itemId] != null) {
      // Placed card → tray.
      setSelectedId(null);
      commit(placeSortItem(assign, itemId, null));
      return;
    }
    setSelectedId(prev => (prev === itemId ? null : itemId));
  };

  const placeInBucket = (bucket: number) => {
    if (disabled || done || selectedId == null) return;
    commit(placeSortItem(assign, selectedId, bucket));
    setSelectedId(null);
  };

  return (
    <div
      className="quiz-sort"
      data-testid="quiz-sort"
      data-complete={complete ? "true" : "false"}
      data-verdict={verdict || undefined}
    >
      {!done && (
        <div className="quiz-sort__tray" data-testid="quiz-sort-tray" aria-label="Items to sort">
          <p className="quiz-sort__tray-label label-micro">Items</p>
          {tray.length === 0 ? (
            <p className="quiz-sort__tray-empty" data-testid="quiz-sort-tray-empty">
              Every item is sorted.
            </p>
          ) : (
            <ul className="quiz-sort__cards">
              {tray.map(it => (
                <li key={it.id}>
                  <button
                    type="button"
                    className={`quiz-sort__card quiz-sort__card--${cardTone(it.id, assign, expectedAssign, verdict, selectedId === it.id)}`}
                    data-testid={`quiz-sort-item-${it.id}`}
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

      <div
        className="quiz-sort__buckets"
        style={{ gridTemplateColumns: `repeat(${interaction.buckets.length}, minmax(0, 1fr))` }}
        data-testid="quiz-sort-buckets"
      >
        {interaction.buckets.map((name, bucket) => {
          const inBucket = interaction.items.filter(it => assign[it.id] === bucket);
          const canDrop = selectedId != null && !disabled && !done;
          return (
            <div
              key={name}
              className={`quiz-sort__bucket${canDrop ? " quiz-sort__bucket--target" : ""}`}
              data-testid={`quiz-sort-bucket-${bucket}`}
              data-bucket={name}
            >
              <button
                type="button"
                className="quiz-sort__bucket-hit"
                aria-label={`Place in ${name}`}
                disabled={!canDrop}
                onClick={() => placeInBucket(bucket)}
              >
                <span className="quiz-sort__bucket-name label-micro">{name}</span>
                {inBucket.length === 0 && !done && (
                  <span className="quiz-sort__bucket-hint">
                    {canDrop ? "Tap to place" : "Drop items here"}
                  </span>
                )}
              </button>
              <ul className="quiz-sort__cards">
                {inBucket.map(it => (
                  <li key={it.id}>
                    <button
                      type="button"
                      className={`quiz-sort__card quiz-sort__card--${cardTone(it.id, assign, expectedAssign, verdict, false)}`}
                      data-testid={`quiz-sort-item-${it.id}`}
                      disabled={disabled || done}
                      onClick={() => selectOrReturn(it.id)}
                    >
                      {it.label}
                    </button>
                  </li>
                ))}
              </ul>
            </div>
          );
        })}
      </div>
    </div>
  );
}

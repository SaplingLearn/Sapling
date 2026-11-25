"use client";

/**
 * W7.2 Rank & Judge (design kit 7.15) — ordered slots + why prose.
 */

import React, { useMemo, useState } from "react";
import type { RankInteraction } from "@/lib/quiz/types";
import {
  decodeRankAnswer,
  encodeRankAnswer,
  isRankComplete,
  placeRankItem,
  type RankAssignment,
} from "@/lib/quiz/rankInteraction";
import { KitPiece, useKitMotion, type KitTone } from "./kitMotion";

export interface RankAnswerProps {
  interaction: RankInteraction;
  value: string;
  disabled: boolean;
  expected?: string | null;
  verdict?: "correct" | "incorrect" | null;
  onChange: (value: string) => void;
}

function cardTone(
  itemId: string,
  assign: RankAssignment,
  expected: RankAssignment | null,
  verdict: "correct" | "incorrect" | null | undefined,
  selected: boolean,
): KitTone {
  if (verdict && expected) {
    const got = assign[itemId];
    const want = expected[itemId];
    if (typeof got === "number" && got === want) return "right";
    if (typeof got === "number") return "wrong";
  }
  return selected ? "lift" : "plain";
}

export function RankAnswer({
  interaction,
  value,
  disabled,
  expected,
  verdict,
  onChange,
}: RankAnswerProps) {
  const { assign, why } = useMemo(
    () => decodeRankAnswer(interaction, value),
    [interaction, value],
  );
  const expectedAssign = useMemo(
    () => (expected ? decodeRankAnswer(interaction, expected).assign : null),
    [interaction, expected],
  );
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const kit = useKitMotion();
  const complete = isRankComplete(interaction, value);
  const tray = interaction.items.filter(it => assign[it.id] == null);
  const done = Boolean(verdict);
  const whyPh =
    interaction.whyPlaceholder?.trim() || "Why is your top choice first?";

  const commit = (nextAssign: RankAssignment, nextWhy: string) => {
    onChange(encodeRankAnswer(interaction, nextAssign, nextWhy));
  };

  const selectOrReturn = (itemId: string) => {
    if (disabled || done) return;
    if (assign[itemId] != null) {
      setSelectedId(null);
      commit(placeRankItem(assign, itemId, null), why);
      return;
    }
    setSelectedId(prev => (prev === itemId ? null : itemId));
  };

  const placeOnSlot = (slot: number) => {
    if (disabled || done || selectedId == null) return;
    commit(placeRankItem(assign, selectedId, slot), why);
    setSelectedId(null);
  };

  return (
    <div
      className="quiz-rank"
      data-testid="quiz-rank"
      data-complete={complete ? "true" : "false"}
      data-verdict={verdict || undefined}
    >
      {interaction.hint ? (
        <p className="quiz-rank__hint label-micro" data-testid="quiz-rank-hint">
          {interaction.hint}
        </p>
      ) : null}

      <div className="quiz-rank__slots" data-testid="quiz-rank-slots" aria-label="Rank order">
        {interaction.items.map((_, slot) => {
          const placed = interaction.items.find(it => assign[it.id] === slot);
          const canDrop = selectedId != null && !disabled && !done;
          return (
            <div
              key={slot}
              className={`quiz-rank__slot${canDrop ? " quiz-rank__slot--target" : ""}`}
              data-testid={`quiz-rank-slot-${slot}`}
              data-slot={slot}
            >
              <button
                type="button"
                className="quiz-rank__slot-hit"
                aria-label={`Place in position ${slot + 1}`}
                disabled={!canDrop}
                onClick={() => placeOnSlot(slot)}
              >
                <span className="quiz-rank__slot-num" aria-hidden="true">
                  {slot + 1}
                </span>
                {!placed && !done && (
                  <span className="quiz-rank__slot-hint">
                    {canDrop ? "Tap to place" : "Drop here"}
                  </span>
                )}
              </button>
              {placed && (
                <KitPiece
                  kit={kit}
                  pieceId={placed.id}
                  block="quiz-rank__card"
                  tone={cardTone(placed.id, assign, expectedAssign, verdict, false)}
                  movable={!done}
                  data-testid={`quiz-rank-item-${placed.id}`}
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
        <div className="quiz-rank__tray" data-testid="quiz-rank-tray" aria-label="Items to rank">
          <p className="quiz-rank__tray-label label-micro">Items</p>
          {tray.length === 0 ? (
            <p className="quiz-rank__tray-empty" data-testid="quiz-rank-tray-empty">
              Every item is ranked.
            </p>
          ) : (
            <ul className="quiz-rank__cards">
              {tray.map(it => (
                <li key={it.id}>
                  <KitPiece
                    kit={kit}
                    pieceId={it.id}
                    block="quiz-rank__card"
                    tone={cardTone(it.id, assign, expectedAssign, verdict, selectedId === it.id)}
                    movable={!done}
                    data-testid={`quiz-rank-item-${it.id}`}
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

      <textarea
        className="quiz-rank__why field"
        data-testid="quiz-rank-why"
        value={why}
        disabled={disabled || done}
        placeholder={whyPh}
        rows={3}
        aria-label={whyPh}
        onChange={e => commit(assign, e.target.value)}
      />
    </div>
  );
}

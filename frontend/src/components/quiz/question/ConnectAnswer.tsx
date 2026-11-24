"use client";

/**
 * W7.2 Connect (design kit 7.3 match) — click left then right to pair.
 */

import React, { useMemo, useState } from "react";
import type { ConnectInteraction } from "@/lib/quiz/types";
import {
  decodeConnectAnswer,
  encodeConnectAnswer,
  isConnectComplete,
  pairConnect,
  type ConnectAssignment,
} from "@/lib/quiz/connectInteraction";

export interface ConnectAnswerProps {
  interaction: ConnectInteraction;
  value: string;
  disabled: boolean;
  expected?: string | null;
  verdict?: "correct" | "incorrect" | null;
  onChange: (value: string) => void;
}

function leftTone(
  leftId: string,
  assign: ConnectAssignment,
  expected: ConnectAssignment | null,
  verdict: "correct" | "incorrect" | null | undefined,
  selected: boolean,
): "plain" | "lift" | "right" | "wrong" {
  if (verdict && expected) {
    const got = assign[leftId];
    const want = expected[leftId];
    if (got && got === want) return "right";
    if (got) return "wrong";
  }
  return selected ? "lift" : assign[leftId] ? "lift" : "plain";
}

export function ConnectAnswer({
  interaction,
  value,
  disabled,
  expected,
  verdict,
  onChange,
}: ConnectAnswerProps) {
  const assign = useMemo(
    () => decodeConnectAnswer(interaction, value),
    [interaction, value],
  );
  const expectedAssign = useMemo(
    () => (expected ? decodeConnectAnswer(interaction, expected) : null),
    [interaction, expected],
  );
  const [selectedLeft, setSelectedLeft] = useState<string | null>(null);
  const complete = isConnectComplete(interaction, assign);
  const done = Boolean(verdict);
  const usedRight = new Set(
    Object.values(assign).filter((id): id is string => typeof id === "string"),
  );

  const commit = (next: ConnectAssignment) => {
    onChange(encodeConnectAnswer(interaction, next));
  };

  const selectLeft = (leftId: string) => {
    if (disabled || done) return;
    if (assign[leftId] != null) {
      setSelectedLeft(null);
      commit(pairConnect(assign, leftId, null));
      return;
    }
    setSelectedLeft(prev => (prev === leftId ? null : leftId));
  };

  const selectRight = (rightId: string) => {
    if (disabled || done || selectedLeft == null) return;
    commit(pairConnect(assign, selectedLeft, rightId));
    setSelectedLeft(null);
  };

  const partnerLabel = (rightId: string | null) => {
    if (!rightId) return null;
    return interaction.right.find(n => n.id === rightId)?.label ?? rightId;
  };

  return (
    <div
      className="quiz-connect"
      data-testid="quiz-connect"
      data-complete={complete ? "true" : "false"}
      data-verdict={verdict || undefined}
    >
      {interaction.note ? (
        <p className="quiz-connect__note label-micro" data-testid="quiz-connect-note">
          {interaction.note}
        </p>
      ) : null}

      <div className="quiz-connect__columns" data-testid="quiz-connect-columns">
        <div className="quiz-connect__col" data-testid="quiz-connect-left" aria-label="Left items">
          {interaction.left.map(n => (
            <button
              key={n.id}
              type="button"
              className={`quiz-connect__node quiz-connect__node--${leftTone(n.id, assign, expectedAssign, verdict, selectedLeft === n.id)}`}
              data-testid={`quiz-connect-left-${n.id}`}
              data-paired={assign[n.id] ? "true" : "false"}
              aria-pressed={selectedLeft === n.id}
              disabled={disabled || done}
              onClick={() => selectLeft(n.id)}
            >
              <span className="quiz-connect__node-label">{n.label}</span>
              {assign[n.id] ? (
                <span className="quiz-connect__pair label-micro">
                  → {partnerLabel(assign[n.id])}
                </span>
              ) : null}
            </button>
          ))}
        </div>

        <div className="quiz-connect__col" data-testid="quiz-connect-right" aria-label="Right items">
          {interaction.right.map(n => {
            const taken = usedRight.has(n.id);
            const canPair = selectedLeft != null && !disabled && !done;
            return (
              <button
                key={n.id}
                type="button"
                className={`quiz-connect__node quiz-connect__node--${taken ? "lift" : "plain"}${canPair ? " quiz-connect__node--target" : ""}`}
                data-testid={`quiz-connect-right-${n.id}`}
                data-taken={taken ? "true" : "false"}
                disabled={!canPair && (disabled || done || taken)}
                onClick={() => selectRight(n.id)}
              >
                {n.label}
              </button>
            );
          })}
        </div>
      </div>
    </div>
  );
}

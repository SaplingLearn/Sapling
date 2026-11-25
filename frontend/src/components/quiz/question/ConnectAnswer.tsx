"use client";

/**
 * W7.2 Connect — match (7.3) or concept-map mode.
 */

import React, { useMemo, useState } from "react";
import { motion } from "framer-motion";
import type { ConnectInteraction } from "@/lib/quiz/types";
import {
  decodeConnectAnswer,
  decodeConnectMapAnswer,
  encodeConnectAnswer,
  encodeConnectMapAnswer,
  isConnectComplete,
  isConnectMap,
  isConnectMapComplete,
  pairConnect,
  toggleConnectMapEdge,
  type ConnectAssignment,
  type ConnectMapEdge,
} from "@/lib/quiz/connectInteraction";
import { useKitMotion, type KitTone } from "./kitMotion";

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
): KitTone {
  if (verdict && expected) {
    const got = assign[leftId];
    const want = expected[leftId];
    if (got && got === want) return "right";
    if (got) return "wrong";
  }
  return selected ? "lift" : assign[leftId] ? "lift" : "plain";
}

function MatchConnect({
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
  const kit = useKitMotion();
  // Pairings already made when the kit appeared: those don't animate in.
  const [pairedAtMount] = useState(
    () => new Set(Object.keys(assign).filter(id => assign[id] != null)),
  );
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
      data-mode="match"
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
            <motion.button
              {...kit.mark(leftTone(n.id, assign, expectedAssign, verdict, selectedLeft === n.id))}
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
                <motion.span
                  {...kit.arrive(!pairedAtMount.has(n.id))}
                  key={assign[n.id]}
                  className="quiz-connect__pair label-micro"
                >
                  → {partnerLabel(assign[n.id])}
                </motion.span>
              ) : null}
            </motion.button>
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

function MapConnect({
  interaction,
  value,
  disabled,
  expected,
  verdict,
  onChange,
}: ConnectAnswerProps) {
  const nodes = interaction.nodes ?? [];
  const edges = useMemo(
    () => decodeConnectMapAnswer(interaction, value),
    [interaction, value],
  );
  const expectedEdges = useMemo(
    () => (expected ? decodeConnectMapAnswer(interaction, expected) : null),
    [interaction, expected],
  );
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const kit = useKitMotion();
  // Links already drawn when the kit appeared: those don't animate in.
  const [edgesAtMount] = useState(() => new Set(edges.map(e => `${e.a}-${e.b}`)));
  const complete = isConnectMapComplete(interaction, edges);
  const done = Boolean(verdict);

  const commit = (next: ConnectMapEdge[]) => {
    onChange(encodeConnectMapAnswer(next));
  };

  const labelOf = (id: string) => nodes.find(n => n.id === id)?.label ?? id;

  const onNode = (id: string) => {
    if (disabled || done) return;
    if (selectedId == null) {
      setSelectedId(id);
      return;
    }
    if (selectedId === id) {
      setSelectedId(null);
      return;
    }
    commit(toggleConnectMapEdge(edges, selectedId, id));
    setSelectedId(null);
  };

  const removeEdge = (a: string, b: string) => {
    if (disabled || done) return;
    commit(toggleConnectMapEdge(edges, a, b));
  };

  const edgeTone = (e: ConnectMapEdge): KitTone => {
    if (!verdict || !expectedEdges) return "plain";
    const k = `${e.a}=${e.b}`;
    const ok = expectedEdges.some(x => `${x.a}=${x.b}` === k);
    return ok ? "right" : "wrong";
  };

  return (
    <div
      className="quiz-connect quiz-connect--map"
      data-testid="quiz-connect"
      data-mode="map"
      data-complete={complete ? "true" : "false"}
      data-verdict={verdict || undefined}
    >
      {interaction.note ? (
        <p className="quiz-connect__note label-micro" data-testid="quiz-connect-note">
          {interaction.note}
        </p>
      ) : (
        <p className="quiz-connect__note label-micro">
          Tap two concepts to link them. Link every concept at least once.
        </p>
      )}

      <div className="quiz-connect__map-nodes" data-testid="quiz-connect-map-nodes">
        {nodes.map(n => (
          <button
            key={n.id}
            type="button"
            className={`quiz-connect__node quiz-connect__node--${selectedId === n.id ? "lift" : "plain"}`}
            data-testid={`quiz-connect-node-${n.id}`}
            aria-pressed={selectedId === n.id}
            disabled={disabled || done}
            onClick={() => onNode(n.id)}
          >
            {n.label}
          </button>
        ))}
      </div>

      <ul className="quiz-connect__map-edges" data-testid="quiz-connect-map-edges">
        {edges.length === 0 ? (
          <li className="quiz-connect__map-empty label-micro">No links yet.</li>
        ) : (
          edges.map(e => (
            <motion.li
              {...(verdict ? kit.mark(edgeTone(e)) : kit.arrive(!edgesAtMount.has(`${e.a}-${e.b}`)))}
              key={`${e.a}-${e.b}`}
              className={`quiz-connect__map-edge quiz-connect__map-edge--${edgeTone(e)}`}
              data-testid={`quiz-connect-edge-${e.a}-${e.b}`}
            >
              <span>
                {labelOf(e.a)} — {labelOf(e.b)}
              </span>
              {!done && !disabled ? (
                <button
                  type="button"
                  className="quiz-connect__map-remove"
                  data-testid={`quiz-connect-remove-${e.a}-${e.b}`}
                  aria-label={`Remove link between ${labelOf(e.a)} and ${labelOf(e.b)}`}
                  onClick={() => removeEdge(e.a, e.b)}
                >
                  Remove
                </button>
              ) : null}
            </motion.li>
          ))
        )}
      </ul>
    </div>
  );
}

export function ConnectAnswer(props: ConnectAnswerProps) {
  if (isConnectMap(props.interaction)) {
    return <MapConnect {...props} />;
  }
  return <MatchConnect {...props} />;
}

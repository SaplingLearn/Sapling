"use client";

/**
 * W3.5a — learner-constructed mini-map stub.
 *
 * Generative "connect these ideas" sketch: concept chips → local undirected
 * edges in React state only. Never posts, never calls apply_graph_update /
 * graph APIs, never writes mastery. Unmount discards the sketch.
 *
 * See docs/learning-loop/w3-5-learner-minimap-spike.md.
 */

import React, { useState } from "react";
import tutorStyles from "./tutor/tutor.module.css";

export type MiniMapConcept = { id: string; label: string };

export type MiniMapEdge = { a: string; b: string };

function edgeKey(a: string, b: string): string {
  return a < b ? `${a}|${b}` : `${b}|${a}`;
}

function hasEdge(edges: readonly MiniMapEdge[], a: string, b: string): boolean {
  const k = edgeKey(a, b);
  return edges.some((e) => edgeKey(e.a, e.b) === k);
}

/** Cap chips at 3 — Q6 “connect these 3 ideas”; keep the stub small. */
export function takeMiniMapConcepts(
  concepts: readonly MiniMapConcept[],
  max = 3,
): MiniMapConcept[] {
  return concepts.slice(0, Math.max(0, max));
}

export function LearnerMiniMapStub({
  concepts,
}: {
  concepts: readonly MiniMapConcept[];
}) {
  const chips = takeMiniMapConcepts(concepts);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [edges, setEdges] = useState<MiniMapEdge[]>([]);

  if (chips.length < 2) return null;

  const labelOf = (id: string) => chips.find((c) => c.id === id)?.label ?? id;

  const onChip = (id: string) => {
    if (selectedId == null) {
      setSelectedId(id);
      return;
    }
    if (selectedId === id) {
      setSelectedId(null);
      return;
    }
    if (!hasEdge(edges, selectedId, id)) {
      setEdges((prev) => [...prev, { a: selectedId, b: id }]);
    }
    setSelectedId(null);
  };

  const removeEdge = (a: string, b: string) => {
    const k = edgeKey(a, b);
    setEdges((prev) => prev.filter((e) => edgeKey(e.a, e.b) !== k));
  };

  const clearAll = () => {
    setEdges([]);
    setSelectedId(null);
  };

  return (
    <section
      data-testid="loop-close-minimap"
      className={`card ${tutorStyles.cardPad}`}
      style={{ gap: 10 }}
      aria-labelledby="loop-close-minimap-h"
    >
      <div>
        <span className="label-micro">Connect these ideas</span>
        <h3 id="loop-close-minimap-h" className="h-serif" style={{ margin: "4px 0 0", fontSize: 18 }}>
          How do they link?
        </h3>
      </div>
      <p style={{ margin: 0, fontSize: 13, color: "var(--text-muted)" }}>
        Tap one concept, then another to draw a link. Just for you — nothing is saved.
      </p>
      <div
        data-testid="loop-close-minimap-chips"
        style={{ display: "flex", flexWrap: "wrap", gap: 8 }}
        role="group"
        aria-label="Concepts to connect"
      >
        {chips.map((c) => {
          const pressed = selectedId === c.id;
          return (
            <button
              key={c.id}
              type="button"
              data-testid={`loop-close-minimap-chip-${c.id}`}
              aria-pressed={pressed}
              className="btn"
              style={{
                fontSize: 13,
                background: pressed ? "var(--accent-soft)" : undefined,
                borderColor: pressed ? "var(--accent-border)" : undefined,
              }}
              onClick={() => onChip(c.id)}
            >
              {c.label}
            </button>
          );
        })}
      </div>
      <ul
        data-testid="loop-close-minimap-edges"
        style={{ margin: 0, padding: 0, listStyle: "none", display: "flex", flexDirection: "column", gap: 6 }}
      >
        {edges.length === 0 ? (
          <li style={{ fontSize: 13, color: "var(--text-muted)" }}>No links yet.</li>
        ) : (
          edges.map((e) => {
            const k = edgeKey(e.a, e.b);
            return (
              <li
                key={k}
                data-testid={`loop-close-minimap-edge-${k}`}
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 8,
                  fontSize: 14,
                  fontFamily: "var(--font-serif)",
                }}
              >
                <span style={{ flex: 1, minWidth: 0 }}>
                  {labelOf(e.a)} <span aria-hidden>↔</span> {labelOf(e.b)}
                </span>
                <button
                  type="button"
                  className="btn"
                  style={{ fontSize: 12 }}
                  data-testid={`loop-close-minimap-remove-${k}`}
                  onClick={() => removeEdge(e.a, e.b)}
                >
                  Remove
                </button>
              </li>
            );
          })
        )}
      </ul>
      {edges.length > 0 && (
        <button
          type="button"
          className="btn"
          style={{ alignSelf: "flex-start", fontSize: 12 }}
          data-testid="loop-close-minimap-clear"
          onClick={clearAll}
        >
          Clear links
        </button>
      )}
    </section>
  );
}

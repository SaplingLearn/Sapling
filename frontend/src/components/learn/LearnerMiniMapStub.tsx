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
import { motion } from "framer-motion";
import { useMotionPresets } from "@/lib/motion";
import tutorStyles from "./tutor/tutor.module.css";
import styles from "./LearnerMiniMapStub.module.css";

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
  const m = useMotionPresets();

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
      className={`card ${tutorStyles.cardPad} ${styles.root}`}
      aria-labelledby="loop-close-minimap-h"
    >
      <div>
        <h3 id="loop-close-minimap-h" className={`h-serif ${styles.title}`}>
          How do they link?
        </h3>
      </div>
      <p className={styles.lede}>
        Tap two concepts to link them. Just for you. Nothing is saved.
      </p>
      <div
        data-testid="loop-close-minimap-chips"
        className={styles.chips}
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
              className={`btn ${styles.chip}`}
              onClick={() => onChip(c.id)}
            >
              {c.label}
            </button>
          );
        })}
      </div>
      {/* Each link drawn rises into the list (the list stagger's item). */}
      <motion.ul
        data-testid="loop-close-minimap-edges"
        className={styles.edges}
        variants={m.list.container}
        initial="hidden"
        animate="shown"
      >
        {edges.length === 0 ? (
          <motion.li key="none" variants={m.list.item} className={styles.empty}>No links yet.</motion.li>
        ) : (
          edges.map((e) => {
            const k = edgeKey(e.a, e.b);
            return (
              <motion.li
                key={k}
                variants={m.list.item}
                data-testid={`loop-close-minimap-edge-${k}`}
                className={styles.edge}
              >
                <span className={styles.edgeLabel}>
                  {labelOf(e.a)} <span aria-hidden>↔</span> {labelOf(e.b)}
                </span>
                <button
                  type="button"
                  className={`btn ${styles.small} ${styles.press}`}
                  data-testid={`loop-close-minimap-remove-${k}`}
                  onClick={() => removeEdge(e.a, e.b)}
                >
                  Remove
                </button>
              </motion.li>
            );
          })
        )}
      </motion.ul>
      {edges.length > 0 && (
        <button
          type="button"
          className={`btn ${styles.small} ${styles.clear} ${styles.press}`}
          data-testid="loop-close-minimap-clear"
          onClick={clearAll}
        >
          Clear links
        </button>
      )}
    </section>
  );
}

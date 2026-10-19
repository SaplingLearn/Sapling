"use client";
import React from "react";

import type { GraphNode } from "@/lib/data";
import type { GraphNode as ApiNode } from "@/lib/types";
import { TIER_LABEL } from "@/lib/graph/nodeStyle";
import { relativeTime } from "./format";
import { StateGlyph, tierOf } from "./StateGlyph";
import styles from "./Dashboard.module.css";

/**
 * The map as a list: the keyboard / screen-reader equivalent of the canvas
 * ("View topics"). Every topic in the current scope with its FULL name, its
 * course, its state in words and its recency. Keyed and selected by node
 * id, so two courses' same-named concepts are two distinct, labelled rows.
 */
export function TopicList({
  nodes,
  raw,
  selectedId,
  courseLabel,
  onPick,
}: {
  nodes: GraphNode[];
  raw: Map<string, ApiNode>;
  selectedId: string | null;
  courseLabel: (id: string | null | undefined) => string | null;
  onPick: (n: GraphNode) => void;
}) {
  const groups = React.useMemo(() => {
    const hubs = nodes.filter((n) => n.is_subject_root);
    const byCourse = new Map<string, { hub: GraphNode | null; label: string; items: GraphNode[] }>();
    for (const h of hubs) byCourse.set(h.course_id, { hub: h, label: courseLabel(h.course_id) ?? h.name, items: [] });
    for (const n of nodes) {
      if (n.is_subject_root) continue;
      const key = n.course_id || `subject:${n.subject}`;
      if (!byCourse.has(key)) byCourse.set(key, { hub: null, label: courseLabel(n.course_id) ?? n.subject ?? "Other", items: [] });
      byCourse.get(key)!.items.push(n);
    }
    for (const g of byCourse.values()) g.items.sort((a, b) => a.name.localeCompare(b.name) || a.id.localeCompare(b.id));
    return [...byCourse.entries()].sort((a, b) => a[1].label.localeCompare(b[1].label));
  }, [nodes, courseLabel]);

  if (groups.length === 0) {
    return <p className={styles.muted} data-testid="dashboard-topics-empty">No topics on your map in this view yet.</p>;
  }

  return (
    <div data-testid="dashboard-topic-list">
      {groups.map(([key, g]) => (
        <section key={key} className={styles.topicGroup} aria-label={g.label}>
          <h3 className={styles.topicGroupTitle}>{g.label}</h3>
          <ul className={styles.rows} style={{ marginTop: 0 }}>
            {g.hub && (
              <li>
                <button
                  type="button"
                  className={styles.topicButton}
                  aria-pressed={selectedId === g.hub.id}
                  onClick={() => onPick(g.hub!)}
                  data-testid={`dashboard-topic-${g.hub.id}`}
                >
                  <span className={styles.topicName}>Course overview</span>
                  <span className={styles.topicState}>{g.items.length} {g.items.length === 1 ? "concept" : "concepts"}</span>
                </button>
              </li>
            )}
            {g.items.map((n) => {
              const tier = tierOf(n.mastery_tier);
              const last = relativeTime(raw.get(n.id)?.last_studied_at ?? n.last_studied_at);
              return (
                <li key={n.id}>
                  <button
                    type="button"
                    className={styles.topicButton}
                    aria-pressed={selectedId === n.id}
                    onClick={() => onPick(n)}
                    data-testid={`dashboard-topic-${n.id}`}
                    data-node-id={n.id}
                  >
                    <StateGlyph tier={tier} />
                    <span className={styles.topicName}>
                      {n.name}
                      <span className="sapling-visually-hidden"> ({g.label})</span>
                    </span>
                    <span className={styles.topicState}>
                      {TIER_LABEL[tier]}
                      {last ? ` · ${last}` : ""}
                    </span>
                  </button>
                </li>
              );
            })}
          </ul>
        </section>
      ))}
    </div>
  );
}

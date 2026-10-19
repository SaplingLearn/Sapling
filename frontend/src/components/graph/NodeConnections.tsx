"use client";

import type { GraphEdge, GraphNode } from "@/lib/data";

const RELATIONSHIP_LABELS: Record<string, string> = {
  related: "Related",
  prerequisite: "Prerequisite",
  builds_on: "Builds on",
  part_of: "Part of",
};

interface Props {
  node: GraphNode;
  nodes: GraphNode[];
  edges: GraphEdge[];
  onSelect: (node: GraphNode) => void;
}

/** Display the recorded direction without inferring a study order from it.
 * Generic relevance edges are not evidence of prerequisite relationships. */
export function NodeConnections({ node, nodes, edges, onSelect }: Props) {
  const byId = new Map(nodes.map((n) => [n.id, n]));
  const seen = new Set<string>();
  const connections = edges.flatMap((edge) => {
    if (edge.source !== node.id && edge.target !== node.id) return [];
    const otherId = edge.source === node.id ? edge.target : edge.source;
    const other = byId.get(otherId);
    if (!other || otherId === node.id) return [];
    const type = edge.relationship_type || "related";
    const key = JSON.stringify(type === "related"
      ? [type, ...[edge.source, edge.target].sort()]
      : [type, edge.source, edge.target]);
    if (seen.has(key)) return [];
    seen.add(key);
    return [{ key, edge, other, type }];
  }).sort((a, b) => a.other.name.localeCompare(b.other.name) || a.key.localeCompare(b.key));

  return (
    <section aria-label="Concept connections" style={{ marginBottom: 20 }}>
      <h3 className="label-micro" style={{ margin: "0 0 8px" }}>Connections</h3>
      {connections.length === 0 ? (
        <p style={{ fontSize: 13, margin: 0 }}>No connections recorded yet.</p>
      ) : (
        <ul style={{ listStyle: "none", padding: 0, margin: 0, display: "grid", gap: 8 }}>
          {connections.map(({ key, edge, other, type }) => (
            <li key={key}>
              <button
                type="button"
                className="btn btn--ghost"
                onClick={() => onSelect(other)}
                style={{ width: "100%", textAlign: "left", display: "block", whiteSpace: "normal", overflowWrap: "anywhere" }}
              >
                <span style={{ display: "block", fontWeight: 500 }}>{other.name}</span>
                <span style={{ display: "block", fontSize: 12, marginTop: 4 }}>
                  {Object.hasOwn(RELATIONSHIP_LABELS, type) ? RELATIONSHIP_LABELS[type] : "Connection"}
                  {type !== "related" && (
                    <> · {byId.get(edge.source)?.name} → {byId.get(edge.target)?.name}</>
                  )}
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

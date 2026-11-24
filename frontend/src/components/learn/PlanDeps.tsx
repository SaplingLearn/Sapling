"use client";
import type { LoopPlanPrereqEdge } from "@/lib/api";
import tutorStyles from "./tutor/tutor.module.css";

/** Resolve a node id to a display name: plan row, then names map, then fallback. */
export function conceptLabel(
  nodeId: string,
  plan: { node_id: string; concept_name: string }[] | null | undefined,
  names: Map<string, string>,
): string {
  const fromPlan = plan?.find((c) => c.node_id === nodeId)?.concept_name;
  return fromPlan || names.get(nodeId) || "Concept";
}

/**
 * W3.1 compact “How these connect” list — PlanPanel (approve) and SessionPanel
 * (teach rail) share the same markup; `testIdPrefix` keeps their testids apart
 * (`loop-plan` vs `session-plan`).
 */
export function PlanDeps({
  edges,
  plan,
  names,
  testIdPrefix,
}: {
  edges: LoopPlanPrereqEdge[];
  plan: { node_id: string; concept_name: string }[] | null | undefined;
  names: Map<string, string>;
  /** e.g. `loop-plan` → `loop-plan-deps`; `session-plan` → `session-plan-deps`. */
  testIdPrefix: string;
}) {
  if (edges.length === 0) return null;
  const headingId = `${testIdPrefix}-deps-heading`;
  return (
    <div
      data-testid={`${testIdPrefix}-deps`}
      className={tutorStyles.panelSec}
      aria-labelledby={headingId}
    >
      <h3 id={headingId} className={tutorStyles.ps} style={{ margin: 0, fontWeight: 600 }}>
        How these connect
      </h3>
      <ul
        aria-label="Prerequisite dependencies"
        style={{ listStyle: "none", margin: 0, padding: 0, display: "flex", flexDirection: "column", gap: 4 }}
      >
        {edges.map((edge) => {
          const from = conceptLabel(edge.prerequisite, plan, names);
          const to = conceptLabel(edge.dependent, plan, names);
          return (
            <li
              key={`${edge.prerequisite}-${edge.dependent}`}
              data-testid={`${testIdPrefix}-dep-${edge.prerequisite}-${edge.dependent}`}
              className={tutorStyles.ps}
              style={{ overflowWrap: "anywhere" }}
              aria-label={`${from} is a prerequisite for ${to}`}
            >
              {from} → {to}
            </li>
          );
        })}
      </ul>
    </div>
  );
}

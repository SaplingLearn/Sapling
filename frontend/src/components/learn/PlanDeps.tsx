"use client";
import type { LoopPlanPrereqEdge } from "@/lib/api";
import tutorStyles from "./tutor/tutor.module.css";

type PlanRow = { node_id: string; concept_name: string };

/** Resolve a node id to a display name: plan row, then names map, then fallback. */
export function conceptLabel(
  nodeId: string,
  plan: PlanRow[] | null | undefined,
  names: Map<string, string>,
): string {
  const fromPlan = plan?.find((c) => c.node_id === nodeId)?.concept_name;
  return fromPlan || names.get(nodeId) || "Concept";
}

/**
 * The edges worth showing under a plan, in the plan's own order: one line per
 * pair (the server never repeats one, but a repeat would collide as a key), only
 * pairs that touch a planned concept (GET /plan also scopes to goal targets, and
 * a target → target pair with neither planned today says nothing about today's
 * plan), sorted by where the prerequisite, then the dependent, sits in the plan
 * (an endpoint off the plan, i.e. a goal target, sorts last). Structure only: no
 * edge is invented here and nothing about mastery is read or implied.
 */
export function orderedPlanEdges(
  edges: LoopPlanPrereqEdge[],
  plan: PlanRow[] | null | undefined,
): LoopPlanPrereqEdge[] {
  const position = new Map((plan ?? []).map((c, i) => [c.node_id, i]));
  const at = (id: string) => position.get(id) ?? Number.POSITIVE_INFINITY;
  const seen = new Set<string>();
  const kept = edges.filter((e) => {
    const key = `${e.prerequisite}\u0000${e.dependent}`;
    if (seen.has(key) || e.prerequisite === e.dependent) return false;
    seen.add(key);
    return position.has(e.prerequisite) || position.has(e.dependent);
  });
  return kept.sort((a, b) => at(a.prerequisite) - at(b.prerequisite) || at(a.dependent) - at(b.dependent));
}

/**
 * W3.1 compact “How these connect” list — PlanPanel (approve) and SessionPanel
 * (teach rail) share the same markup; `testIdPrefix` keeps their testids apart
 * (`loop-plan` vs `session-plan`). Absent when no edge touches the plan: the
 * numbered list alone is the plan (sparse graphs are the common case).
 */
export function PlanDeps({
  edges,
  plan,
  names,
  testIdPrefix,
}: {
  edges: LoopPlanPrereqEdge[];
  plan: PlanRow[] | null | undefined;
  names: Map<string, string>;
  /** e.g. `loop-plan` → `loop-plan-deps`; `session-plan` → `session-plan-deps`. */
  testIdPrefix: string;
}) {
  const shown = orderedPlanEdges(edges, plan);
  if (shown.length === 0) return null;
  const headingId = `${testIdPrefix}-deps-heading`;
  return (
    <section
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
        {shown.map((edge) => {
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
    </section>
  );
}

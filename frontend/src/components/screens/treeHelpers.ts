import type React from "react";
import type { GraphNode } from "@/lib/data";

/** The Tree's course filter keeps `"all"` as its no-course value; the graph
 *  and the course key both want `null` for it. */
export function selectedCourseIdOf(courseFilter: string): string | null {
  return courseFilter === "all" ? null : courseFilter;
}

/** The graph paints the `?suggest=` node first, else the selected node. */
export function highlightIdFor(
  suggestId: string | undefined,
  selected: GraphNode | null,
): string | undefined {
  return suggestId || selected?.id;
}

/** "Delete concept" borrows the error palette once armed (the second click
 *  confirms); unarmed it is a plain full-width button. */
export function deleteButtonStyle(armed: boolean): React.CSSProperties {
  return {
    width: "100%", marginTop: 12,
    background: armed ? "var(--err-soft)" : undefined,
    color: armed ? "var(--err)" : undefined,
    borderColor: armed ? "var(--err)" : undefined,
  };
}

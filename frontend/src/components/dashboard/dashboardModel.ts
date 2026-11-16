import type { GraphStats } from "@/lib/types";
import type { GraphNode } from "@/lib/data";

/** The dashboard's graph counters (the wire's `total_nodes` is `total`). */
export type DashboardStats = {
  streak: number;
  mastered: number;
  total: number;
  learning: number;
  struggling: number;
  unexplored: number;
};

/** The /api/graph `stats` block as the dashboard reads it; every missing
 *  counter (or a missing block) is 0. */
export function statsFromGraph(stats: Partial<GraphStats> | null | undefined): DashboardStats {
  return {
    streak: stats?.streak ?? 0,
    mastered: stats?.mastered ?? 0,
    total: stats?.total_nodes ?? 0,
    learning: stats?.learning ?? 0,
    struggling: stats?.struggling ?? 0,
    unexplored: stats?.unexplored ?? 0,
  };
}

/** UTC YYYY-MM-DD days on which some node was last studied (unparseable
 *  timestamps are skipped). */
export function activeDaysFrom(nodes: GraphNode[]): Set<string> {
  const days = new Set<string>();
  for (const n of nodes) {
    if (!n.last_studied_at) continue;
    const d = new Date(n.last_studied_at);
    if (!isNaN(d.getTime())) days.add(d.toISOString().slice(0, 10));
  }
  return days;
}

/** The legacy Upcoming panel's urgency chip for an item due at `dueIso`. */
export function assignmentUrgency(dueIso: string, nowMs: number): { chipClass: string; label: string } {
  const diffMs = new Date(dueIso).getTime() - nowMs;
  const hours = diffMs / (1000 * 60 * 60);
  const days = Math.ceil(diffMs / 86400000);
  if (hours <= 0) return { chipClass: "chip--err", label: "OVERDUE" };
  if (hours <= 24) {
    return { chipClass: "chip--err", label: hours < 1 ? "NOW" : `${Math.max(1, Math.round(hours))}H` };
  }
  return { chipClass: days <= 2 ? "chip--warn" : "chip--info", label: `${days}D` };
}

export type StreakMarkState = "done" | "today" | "missed" | "future";

/** One day of the legacy week strip: studied, today, a past miss, or ahead. */
export function streakMarkState(d: Date, today: Date, activeDays: Set<string>): StreakMarkState {
  if (activeDays.has(d.toISOString().slice(0, 10))) return "done";
  if (d.getTime() === today.getTime()) return "today";
  return d.getTime() < today.getTime() ? "missed" : "future";
}

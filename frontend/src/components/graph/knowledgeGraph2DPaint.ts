/**
 * Per-link / per-node paint decisions for `KnowledgeGraph2D`, as pure
 * functions of the render's inputs. The component's renderers call these
 * once per item per render; they take plain positional arguments so a
 * render allocates nothing extra for them.
 */
import type { GraphEdge, GraphNode } from "@/lib/data";
import { NODE_STROKE_OPACITY, opacityFor } from "@/lib/graph/nodeStyle";
import { isDirected } from "@/lib/graph/radialLayout";

/** A link end: the node itself once the link force swapped it in, else its id. */
export function linkEnd<N extends { id: string }>(end: string | N, byId: ReadonlyMap<string, N>): N | undefined {
  return typeof end === "object" ? end : byId.get(String(end));
}

/** A hovered "My courses" row (the host's key): that course stays bright. */
export function inCourseFocus(n: Pick<GraphNode, "course_id">, focusCourseId: string | null): boolean {
  return !focusCourseId || n.course_id === focusCourseId;
}

/** Legible focus: the hovered concept, or nobody outside legible mode. */
export function hoverFocusId(legible: boolean, hovered: { id: string } | null): string | null {
  return legible ? hovered?.id ?? null : null;
}

/** The mastery the tooltip shows: a course's average, a concept's own score. */
export function hoverMastery(
  hovered: Pick<GraphNode, "is_subject_root" | "subject" | "mastery_score"> | null,
  subjectAverage: Record<string, number>,
): number {
  if (!hovered) return 0;
  return hovered.is_subject_root ? subjectAverage[hovered.subject] ?? 0 : hovered.mastery_score || 0;
}

// ── Links ──────────────────────────────────────────────────────────────────

/** Whether a link touches the focused concept. */
export function linkIncident(focusId: string | null, sourceId: string, targetId: string): boolean {
  return !!focusId && (sourceId === focusId || targetId === focusId);
}

/** A link's stroke opacity outside legible mode. */
export function plainLinkOpacity(mastery: boolean, variant: string): number {
  return mastery ? 0.85 : variant === "constellation" ? 0.35 : 0.2;
}

/** A link's stroke opacity in legible mode: focus first, then the course key. */
export function legibleLinkOpacity(
  anchor: boolean | undefined,
  incident: boolean,
  s: Pick<GraphNode, "course_id">,
  t: Pick<GraphNode, "course_id">,
  mastery: boolean,
  focusId: string | null,
  focusCourseId: string | null,
): number {
  if (focusId) return incident ? 0.9 : 0.04;
  if (!inCourseFocus(s, focusCourseId) || !inCourseFocus(t, focusCourseId)) return 0.03;
  return anchor ? 0.1 : mastery ? 0.45 : 0.16;
}

/**
 * Whether a link draws its arrowhead: directed concept links in legible mode,
 * when focused on, or zoomed in. Arrowheads don't fade with their line, so a
 * dimmed link drops its arrow.
 */
export function linkArrow(
  l: Pick<GraphEdge, "relationship_type"> & { anchor?: boolean },
  legible: boolean,
  focusId: string | null,
  incident: boolean,
  scale: number,
): boolean {
  const directed = legible && !l.anchor && isDirected(l);
  return directed && (focusId ? incident : scale >= 0.9);
}

/** A link's stroke: its gradient in mastery mode, else a muted line (dim when focused). */
export function linkStroke(mastery: boolean, gradId: string, incident: boolean): string {
  return mastery ? `url(#${gradId})` : incident ? "var(--text-dim)" : "var(--text-muted)";
}

/** A link's arrowhead marker reference, or none. */
export function linkMarker(arrow: boolean, gradPrefix: string, incident: boolean): string | undefined {
  return arrow ? `url(#${gradPrefix}-arrow${incident ? "-on" : ""})` : undefined;
}

// ── Nodes ──────────────────────────────────────────────────────────────────

/**
 * A node's fill opacity: `mastery` mode carries the tier in the hue, so every
 * mark is fully opaque; `course` mode carries it in the opacity.
 */
export function nodeOpacity(n: Pick<GraphNode, "is_subject_root" | "mastery_tier">, mastery: boolean): number {
  return n.is_subject_root || mastery ? 1 : opacityFor(n.mastery_tier);
}

/**
 * Course roots are always pinned by the radial layout, so a pin only means
 * "being dragged" for concepts.
 */
export function isDragPinned(n: Pick<GraphNode, "is_subject_root"> & { fx?: number | null; fy?: number | null }): boolean {
  return !n.is_subject_root && n.fx != null && n.fy != null;
}

/** A node's stroke opacity: full while dragged, raised while hovered. */
export function nodeStrokeOpacity(pinned: boolean, hovered: boolean): number {
  return pinned ? 1 : hovered ? 0.9 : NODE_STROKE_OPACITY;
}

/** Legible: a node outside the hover focus (or the course key's focus) fades. */
export function legibleNodeOpacity(
  n: Pick<GraphNode, "id" | "course_id">,
  focusId: string | null,
  focusSet: ReadonlySet<string>,
  focusCourseId: string | null,
): number {
  return (focusId && !focusSet.has(n.id)) || (!focusId && !inCourseFocus(n, focusCourseId)) ? 0.15 : 1;
}

/** A concept label's font size: focused labels stay readable however far out. */
export function conceptLabelSize(legible: boolean, focused: boolean, scale: number): number {
  return legible && focused ? Math.min(24, 10.5 / Math.min(1, scale)) : 10.5;
}

/** A concept label's weight: the focused concept's own label is bold. */
export function conceptLabelWeight(legible: boolean, isFocus: boolean): number | undefined {
  return legible && isFocus ? 600 : undefined;
}

/** A concept label's opacity: legible labels follow focus, else fade in with zoom. */
export function conceptLabelOpacity(
  legible: boolean,
  focusId: string | null,
  focused: boolean,
  zoomLabels: number,
): number {
  return legible ? (focusId ? (focused ? 1 : 0) : zoomLabels) * 0.85 : 0.85;
}

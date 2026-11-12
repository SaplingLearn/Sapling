/**
 * Per-link / per-node paint decisions for `KnowledgeGraph2D`, as pure
 * functions of the render's inputs. The component's renderers call these
 * once per item per render; they take plain positional arguments so a
 * render allocates nothing extra for them.
 */
import type { GraphEdge, GraphNode } from "@/lib/data";
import { blobProfile, rimRadius, wobbleFor } from "@/lib/graph/blobShape";
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

/**
 * A link's stroke opacity outside legible mode. A hand-drawn (`organism`) link
 * in course colours is a bar of its course's colour, lighter than the nodes it
 * joins, so it sits well above the thin grey line the other variants draw.
 * Its `anchor` links (the course's own, one to each starting concept) say
 * only "belongs to this course" and there can be dozens of them, so they
 * stay faint in either colour mode.
 */
export function plainLinkOpacity(mastery: boolean, variant: string, anchor = false): number {
  if (anchor && variant === "organism") return 0.16;
  if (mastery) return 0.85;
  if (variant === "constellation") return 0.35;
  return variant === "organism" ? 0.45 : 0.2;
}

/** The width of a hand-drawn `anchor` link: thinner than any concept link. */
export const ANCHOR_WIDTH = 1.8;

/**
 * A link's stroke opacity in legible mode: focus first, then the course key.
 * At rest a hand-drawn link in course colours is a pale bar of its course's
 * colour (0.26), where the thin grey line it replaced sat at 0.16.
 */
export function legibleLinkOpacity(
  anchor: boolean | undefined,
  incident: boolean,
  s: Pick<GraphNode, "course_id">,
  t: Pick<GraphNode, "course_id">,
  mastery: boolean,
  focusId: string | null,
  focusCourseId: string | null,
  organic = false,
): number {
  if (focusId) return incident ? 0.9 : 0.04;
  if (!inCourseFocus(s, focusCourseId) || !inCourseFocus(t, focusCourseId)) return 0.03;
  if (anchor) return 0.1;
  if (mastery) return 0.45;
  return organic ? 0.26 : 0.16;
}

/** The zoom from which directed links show their arrowheads at rest. */
export const ARROW_ZOOM = 0.7;

/**
 * Whether a link draws its arrowhead: directed concept links in legible mode,
 * when focused on, or from `ARROW_ZOOM` in (further out a head is a speck).
 * Arrowheads don't fade with their line, so a dimmed link drops its arrow.
 */
export function linkArrow(
  l: Pick<GraphEdge, "relationship_type"> & { anchor?: boolean },
  legible: boolean,
  focusId: string | null,
  incident: boolean,
  scale: number,
): boolean {
  const directed = legible && !l.anchor && isDirected(l);
  return directed && (focusId ? incident : scale >= ARROW_ZOOM);
}

/**
 * A link's stroke: its gradient in mastery mode; else, for a hand-drawn link,
 * its course's one flat colour (`courseColor`); else a muted line (dim when
 * focused).
 */
export function linkStroke(mastery: boolean, gradId: string, incident: boolean, courseColor?: string): string {
  if (mastery) return `url(#${gradId})`;
  return courseColor ?? (incident ? "var(--text-dim)" : "var(--text-muted)");
}

/**
 * A "related" link's dash pattern. A hand-drawn link is a row of round dots
 * (a zero-length dash under a round cap, spaced by its width); a thin line
 * keeps the plain dash.
 */
export function relatedDash(organic: boolean, width: number): string {
  return organic ? `0.01 ${(width * 2.2).toFixed(2)}` : "4 4";
}

// How far a hand-drawn link runs under the rim of the node it joins: just
// enough to close the sliver between its square end and the curved rim, and
// no more, because a node's fill can be translucent and must stay one colour.
const LINK_OVERLAP = 0.5;
/** The arrowhead marker's side, in the graph's units (`markerUnits="userSpaceOnUse"`). */
export const ARROW_SIZE = 8;
/** Where along its length the arrowhead sits on the line's end (0 = base, 10 = tip). */
export const ARROW_REF_X = 2;
// A hand-drawn link with an arrowhead stops short of its target: the head
// reaches past the line's end by the rest of its length, then leaves a hair
// of air before the rim so the point stays readable.
const ARROW_REACH = (ARROW_SIZE * (10 - ARROW_REF_X)) / 10 + 1;

/**
 * The visible part of a hand-drawn link: from the source's drawn rim to the
 * target's (or short of it, when the link carries an arrowhead). The rim is
 * the node's own outline in the link's direction, not its nominal radius, so
 * a link neither floats off a dent nor stabs through a bulge. `sShape` /
 * `tShape` are the radii the outlines' irregularity was chosen for (the
 * resting radius); `sr` / `tr` are the radii drawn. Nodes that touch or
 * overlap leave nothing to draw.
 */
export function organicLinkSegment(
  sId: string, sx: number, sy: number, sr: number, sShape: number,
  tId: string, tx: number, ty: number, tr: number, tShape: number,
  arrow: boolean,
): [number, number, number, number] {
  const dx = tx - sx;
  const dy = ty - sy;
  const len = Math.hypot(dx, dy);
  const theta = Math.atan2(dy, dx);
  const r1 = len > 0 ? rimRadius(blobProfile(sId, wobbleFor(sShape)), sr, theta) - LINK_OVERLAP : 0;
  const r2 =
    len > 0
      ? rimRadius(blobProfile(tId, wobbleFor(tShape)), tr, theta + Math.PI) + (arrow ? ARROW_REACH : -LINK_OVERLAP)
      : 0;
  if (len <= r1 + r2) {
    const mx = (sx + tx) / 2;
    const my = (sy + ty) / 2;
    return [mx, my, mx, my];
  }
  const ux = dx / len;
  const uy = dy / len;
  return [sx + ux * r1, sy + uy * r1, tx - ux * r2, ty - uy * r2];
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

/**
 * A node's stroke opacity: full while dragged, raised while hovered. At rest
 * a hand-drawn node has no rim at all: over a translucent fill a rim of the
 * same colour reads as a second, darker tone, and the node is one flat colour.
 */
export function nodeStrokeOpacity(pinned: boolean, hovered: boolean, organic = false): number {
  if (pinned) return 1;
  if (hovered) return 0.9;
  return organic ? 0 : NODE_STROKE_OPACITY;
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

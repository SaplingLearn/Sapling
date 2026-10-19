/**
 * Deterministic live-data adaptation of the authored Pen graph.
 *
 * The reference fixture uses its exact source coordinates/branches. Real data
 * uses the same source marks and branch contours, mapped by stable IDs and
 * topology; no sample course or concept is inserted into a student's graph.
 * Mastery, course colours, input order and viewport size never move a node.
 */
import type { GraphEdge, GraphNode } from "@/lib/data";
import { sourceFillFor } from "@/lib/graph/nodeStyle";
import { PEN_NATIVE_GRAPH_REFERENCE } from "@/lib/graph/penNativeGraphSource";
import {
  PEN_GRAPH_SOURCE_EDGES,
  PEN_GRAPH_SOURCE_NODES,
  PEN_GRAPH_VIEWBOX,
} from "@/lib/graph/penGraphSource";

export { PEN_GRAPH_REFERENCE, PEN_GRAPH_SOURCE_EDGES, PEN_GRAPH_SOURCE_NODES, PEN_GRAPH_VIEWBOX } from "@/lib/graph/penGraphSource";

type SourceNode = (typeof PEN_GRAPH_SOURCE_NODES)[number];
type SourceEdge = (typeof PEN_GRAPH_SOURCE_EDGES)[number];
export type PenPoint = { x: number; y: number };
export type PenGraphNodeLayout = GraphNode & PenPoint & {
  r: number;
  kind: "hub" | "topic" | "leaf";
  fillPath: string;
  fillTransform: string;
  outlinePath: string;
  outlineTransform: string;
  shapeTransform: string;
  strokeWidth: number;
  sourceId: string;
};
export type PenBranch = {
  d: string;
  transform: string;
  projectionScale: number;
  gradient: { x1: number; y1: number; x2: number; y2: number; transform: string; from: string; to: string };
  strokeWidth: number;
  sourceId: string;
};
export type PenGraphEdgeLayout = PenBranch & { id: string; source: string; target: string };
export type PenGraphLayout = { nodes: PenGraphNodeLayout[]; edges: PenGraphEdgeLayout[]; width: number; height: number };
export type PenGraphData = { nodes: GraphNode[]; edges: GraphEdge[] };

const byId = (a: { id: string }, b: { id: string }) => a.id < b.id ? -1 : a.id > b.id ? 1 : 0;
const sourceById = new Map<string, SourceNode>(PEN_GRAPH_SOURCE_NODES.map((n) => [n.sourceId, n]));
const SOURCE_LEFT = ["B3NyPy", "d2aDSd", "n3mZgK", "l7Hg2", "oeBY7", "NmDeL", "llXAf", "HzS35", "yl9rk", "SSkbd", "z7LH6", "TAVXo", "D5DTe"];
const SOURCE_RIGHT = ["S6yVOt", "iZyR9", "RTscJ", "h5p0b", "BXL6j", "N8gm7", "BUHUf", "hwlQn", "I7RqMD"];
const PRESET_HUB = PEN_GRAPH_SOURCE_NODES[0];
const PRESET_TOPIC = PEN_GRAPH_SOURCE_NODES[2];
const PRESET_LEAF = PEN_GRAPH_SOURCE_NODES[5];
const FIXTURE_PREFIX = "pen-fixture:";

function finite(n: number): string {
  return Number.isFinite(n) ? String(Math.round(n * 1e6) / 1e6) : "0";
}

function translate(x: number, y: number): string {
  return `translate(${finite(x)} ${finite(y)})`;
}

function makeNode(n: GraphNode, position: PenPoint, preset: SourceNode): PenGraphNodeLayout {
  const shape = n.is_subject_root ? (preset.kind === "hub" ? preset : PRESET_HUB) : preset.kind === "hub" ? PRESET_TOPIC : preset;
  const nativeIndex = PEN_NATIVE_GRAPH_REFERENCE.paths.findIndex((p) => p.sourceId === shape.sourceId);
  const nativeFill = PEN_NATIVE_GRAPH_REFERENCE.paths[nativeIndex];
  const nativeOutline = PEN_NATIVE_GRAPH_REFERENCE.paths[nativeIndex + 1];
  return {
    ...n,
    ...position,
    r: shape.r,
    kind: shape.kind,
    fillPath: nativeFill.d,
    fillTransform: nativeFill.transform,
    outlinePath: nativeOutline.d,
    outlineTransform: nativeOutline.transform,
    shapeTransform: translate(position.x - shape.x, position.y - shape.y),
    strokeWidth: shape.strokeWidth,
    sourceId: shape.sourceId,
  };
}

/** Similarity transform of an original organic contour onto two endpoints.
 * Preserves the contour's relative curvature instead of replacing it by a
 * straight line. Scaling uses uniform x/y so the authored contour is not
 * stretched differently on the two axes. The source gradient shares the
 * path's coordinate space; apply the same transform to both.
 */
function branchTransform(template: SourceEdge, a: PenPoint, b: PenPoint): string {
  const sx = template.end[0] - template.start[0];
  const sy = template.end[1] - template.start[1];
  const dx = b.x - a.x;
  const dy = b.y - a.y;
  const norm = sx * sx + sy * sy;
  const m00 = (dx * sx + dy * sy) / norm;
  const m10 = (dy * sx - dx * sy) / norm;
  const tx = a.x - m00 * template.start[0] + m10 * template.start[1];
  const ty = a.y - m10 * template.start[0] - m00 * template.start[1];
  return `matrix(${finite(m00)} ${finite(m10)} ${finite(-m10)} ${finite(m00)} ${finite(tx)} ${finite(ty)})`;
}


/** Native Pen gradients are evaluated in normalized object space before the
 * object's anisotropic bounds. Flattening just the endpoints to canvas space
 * changes the paint field. This composition retains that normalized space.
 */
function nativeBranchPaint(template: SourceEdge, sourceColor: string, targetColor: string): PenBranch["gradient"] {
  const path = PEN_NATIVE_GRAPH_REFERENCE.paths.find((p) => p.sourceId === template.sourceId)!;
  const gradient = PEN_NATIVE_GRAPH_REFERENCE.gradients.find((g) => g.id === `g-${template.sourceId}-stroke`)!;
  const matrix = path.transform.slice(7, -1).split(" ").map(Number);
  const width = gradient.nativePaint.width;
  const height = gradient.nativePaint.height;
  const first = { x: matrix[0] * width * gradient.x1 + matrix[4], y: matrix[3] * height * gradient.y1 + matrix[5] };
  const source = sourceById.get(template.source)!;
  const target = sourceById.get(template.target)!;
  const startsAtSource = Math.hypot(first.x - source.x, first.y - source.y) < Math.hypot(first.x - target.x, first.y - target.y);
  return {
    x1: gradient.x1, y1: gradient.y1, x2: gradient.x2, y2: gradient.y2,
    transform: `matrix(${matrix[0] * width} 0 0 ${matrix[3] * height} ${matrix[4]} ${matrix[5]})`,
    from: startsAtSource ? sourceColor : targetColor,
    to: startsAtSource ? targetColor : sourceColor,
  };
}

export function penBranchFor(
  source: PenPoint & { r: number; is_subject_root?: boolean; mastery_tier?: string },
  target: PenPoint & { r: number; is_subject_root?: boolean; mastery_tier?: string },
  templateIndex = 0,
): PenBranch {
  const template = PEN_GRAPH_SOURCE_EDGES[((Math.trunc(templateIndex) % PEN_GRAPH_SOURCE_EDGES.length) + PEN_GRAPH_SOURCE_EDGES.length) % PEN_GRAPH_SOURCE_EDGES.length];
  const dx = target.x - source.x;
  const dy = target.y - source.y;
  const distance = Math.hypot(dx, dy);
  // A coincident/self edge remains finite and visible. It does not create a
  // synthetic graph relationship: it only gives an existing edge a contour.
  const ux = distance > 0 ? dx / distance : 1;
  const uy = distance > 0 ? dy / distance : 0;
  const trim = distance > 0 ? Math.min(1, distance / Math.max(1, source.r + target.r + 4)) : 0;
  const start = { x: source.x + ux * source.r * trim, y: source.y + uy * source.r * trim };
  const end = distance > 0
    ? { x: target.x - ux * target.r * trim, y: target.y - uy * target.r * trim }
    : { x: target.x + 1, y: target.y + 1 };
  return {
    d: template.d,
    transform: branchTransform(template, start, end),
    projectionScale: Math.hypot(end.x - start.x, end.y - start.y) / Math.hypot(template.end[0] - template.start[0], template.end[1] - template.start[1]),
    gradient: nativeBranchPaint(template, sourceFillFor(source), sourceFillFor(target)),
    strokeWidth: 7,
    sourceId: template.sourceId,
  };
}


type PaintBounds = { left: number; top: number; right: number; bottom: number };

/** A Bezier lies inside the convex hull of its control points. Source branch
 * commands are absolute M/L/C, so transforming every coordinate pair gives a
 * conservative painted bound without flattening or rasterizing the artwork.
 */
function branchPaintBounds(branch: PenBranch): PaintBounds {
  const matrix = branch.transform.slice(7, -1).split(" ").map(Number);
  const numbers = (branch.d.match(/-?\d*\.?\d+(?:[eE][-+]?\d+)?/g) ?? []).map(Number);
  const points: PenPoint[] = [];
  for (let i = 0; i + 1 < numbers.length; i += 2) {
    points.push({
      x: matrix[0] * numbers[i] + matrix[2] * numbers[i + 1] + matrix[4],
      y: matrix[1] * numbers[i] + matrix[3] * numbers[i + 1] + matrix[5],
    });
  }
  return {
    left: Math.min(...points.map((p) => p.x)) - 10,
    top: Math.min(...points.map((p) => p.y)) - 10,
    right: Math.max(...points.map((p) => p.x)) + 10,
    bottom: Math.max(...points.map((p) => p.y)) + 10,
  };
}

function paintBounds(nodes: PenGraphNodeLayout[], edges: GraphEdge[]): PaintBounds {
  const byId = new Map(nodes.map((n) => [n.id, n]));
  const marks: PaintBounds[] = nodes.map((n) => ({
    left: n.x - n.r - n.strokeWidth / 2 - 8,
    top: n.y - n.r - n.strokeWidth / 2 - 8,
    right: n.x + n.r + n.strokeWidth / 2 + 8,
    bottom: n.y + n.r + n.strokeWidth / 2 + 8,
  }));
  edges.forEach((e, index) => {
    const source = byId.get(e.source);
    const target = byId.get(e.target);
    if (source && target) marks.push(branchPaintBounds(penBranchFor(source, target, index)));
  });
  return {
    left: Math.min(0, ...marks.map((b) => b.left)),
    top: Math.min(0, ...marks.map((b) => b.top)),
    right: Math.max(0, ...marks.map((b) => b.right)),
    bottom: Math.max(0, ...marks.map((b) => b.bottom)),
  };
}

/** Pack actual course silhouettes, not their mostly empty source canvases.
 * The fixed design aspect is independent of viewport/mastery. Search a small
 * deterministic set of rectangle widths/orderings, retaining all authored
 * positions inside each family and a 40-unit gap between painted bounds.
 */
function compactCourses(groups: PenGraphNodeLayout[][], edges: GraphEdge[]): PenGraphNodeLayout[] {
  if (groups.length <= 2) return groups.flat();
  const gap = 40;
  const blocks = groups.map((nodes, index) => {
    // Course-local bounds exclude empty space back to the canvas origin.
    const ids = new Set(nodes.map((n) => n.id));
    const parts = nodes.map((n) => ({ left: n.x - n.r - n.strokeWidth / 2 - 8, top: n.y - n.r - n.strokeWidth / 2 - 8, right: n.x + n.r + n.strokeWidth / 2 + 8, bottom: n.y + n.r + n.strokeWidth / 2 + 8 }));
    const nodeById = new Map(nodes.map((n) => [n.id, n]));
    edges.forEach((e, edgeIndex) => {
      if (ids.has(e.source) && ids.has(e.target)) parts.push(branchPaintBounds(penBranchFor(nodeById.get(e.source)!, nodeById.get(e.target)!, edgeIndex)));
    });
    const bounds = {
      left: Math.min(...parts.map((p) => p.left)),
      top: Math.min(...parts.map((p) => p.top)),
      right: Math.max(...parts.map((p) => p.right)),
      bottom: Math.max(...parts.map((p) => p.bottom)),
    };
    return { index, nodes, bounds, width: bounds.right - bounds.left, height: bounds.bottom - bounds.top };
  });
  const orders = [
    blocks,
    [...blocks].reverse(),
    [...blocks].sort((a, b) => b.height - a.height || a.index - b.index),
    [...blocks].sort((a, b) => b.width - a.width || a.index - b.index),
    [...blocks].sort((a, b) => b.width * b.height - a.width * a.height || a.index - b.index),
  ];
  const minWidth = Math.max(...blocks.map((b) => b.width));
  const totalArea = blocks.reduce((sum, b) => sum + (b.width + gap) * (b.height + gap), 0);
  const idealWidth = Math.sqrt(totalArea * PEN_GRAPH_VIEWBOX.width / PEN_GRAPH_VIEWBOX.height);
  const widths = new Set<number>([minWidth, ...[0.7, 0.85, 1, 1.15, 1.3, 1.5, 1.8].map((factor) => Math.max(minWidth, idealWidth * factor))]);
  // Small course counts benefit from every potential row width, including
  // irregular three-course rows that a fixed two-column grid wastes space on.
  if (blocks.length <= 8) {
    for (let mask = 1; mask < 2 ** blocks.length; mask++) {
      const row = blocks.filter((_, i) => mask & 2 ** i);
      widths.add(Math.max(minWidth, row.reduce((sum, b) => sum + b.width, 0) + gap * (row.length - 1)));
    }
  }
  type Placement = { index: number; x: number; y: number; width: number; height: number };
  let best: { placements: Placement[]; score: number; area: number } | undefined;
  for (const limit of [...widths].sort((a, b) => a - b)) for (const order of orders) {
    const placed: Placement[] = [];
    for (const block of order) {
      const xs = [0, ...placed.map((p) => p.x + p.width + gap)];
      const ys = [0, ...placed.map((p) => p.y + p.height + gap)];
      let choice: Placement | undefined;
      for (const y of ys) for (const x of xs) {
        if (x + block.width > limit + 0.00001) continue;
        if (placed.some((p) => x < p.x + p.width + gap - 0.00001 && x + block.width + gap > p.x + 0.00001 && y < p.y + p.height + gap - 0.00001 && y + block.height + gap > p.y + 0.00001)) continue;
        const next = { index: block.index, x, y, width: block.width, height: block.height };
        if (!choice || y + block.height < choice.y + choice.height || (y === choice.y && x < choice.x)) choice = next;
      }
      // At least the position below all placed rectangles is always valid.
      placed.push(choice ?? { index: block.index, x: 0, y: Math.max(0, ...placed.map((p) => p.y + p.height + gap)), width: block.width, height: block.height });
    }
    const width = Math.max(...placed.map((p) => p.x + p.width));
    const height = Math.max(...placed.map((p) => p.y + p.height));
    const score = Math.max(width / PEN_GRAPH_VIEWBOX.width, height / PEN_GRAPH_VIEWBOX.height);
    const area = width * height;
    if (!best || score < best.score - 0.00001 || (Math.abs(score - best.score) < 0.00001 && area < best.area)) best = { placements: placed, score, area };
  }
  return blocks.flatMap((block) => {
    const location = best!.placements.find((p) => p.index === block.index)!;
    return block.nodes.map((n) => makeNode(n, { x: n.x - block.bounds.left + location.x, y: n.y - block.bounds.top + location.y }, sourceById.get(n.sourceId)!));
  });
}

function edgeKey(e: GraphEdge): string {
  return JSON.stringify([e.source, e.target, e.relationship_type ?? "", e.strength]);
}

function fixtureLayout(data: PenGraphData): PenGraphLayout {
  const nodes = data.nodes.map((n) => {
    const preset = sourceById.get(n.id.slice(FIXTURE_PREFIX.length));
    if (!n.id.startsWith(FIXTURE_PREFIX) || !preset) throw new Error("The exact Pen layout accepts explicit design-fixture IDs only.");
    return makeNode(n, preset, preset);
  });
  const edges = data.edges.map((e) => {
    const template = PEN_GRAPH_SOURCE_EDGES.find((s) => `${FIXTURE_PREFIX}${s.source}` === e.source && `${FIXTURE_PREFIX}${s.target}` === e.target);
    if (!template) throw new Error("The exact Pen layout accepts the authored fixture topology only.");
    return {
      id: template.sourceId,
      source: e.source, target: e.target,
      d: template.d, transform: "matrix(1 0 0 1 0 0)", projectionScale: 1,
      gradient: nativeBranchPaint(template, sourceById.get(template.source)!.fill, sourceById.get(template.target)!.fill),
      strokeWidth: template.strokeWidth,
      sourceId: template.sourceId,
    };
  });
  return { nodes, edges, ...PEN_GRAPH_VIEWBOX };
}

/**
 * A stable ID/topology layout. Each course uses one authored branch family;
 * course pairs retain the master silhouette. Dense courses receive separate
 * cells and additional collision-spaced slots, while disconnected concepts
 * are retained in the same course family. Cross-course edges remain intact.
 *
 * `referenceFixture` is intentionally explicit and rejects real API IDs.
 */
export function buildPenGraphLayout(data: PenGraphData, options: { referenceFixture?: boolean } = {}): PenGraphLayout {
  if (options.referenceFixture) return fixtureLayout(data);
  const nodes = [...new Map(data.nodes.map((n) => [n.id, n])).values()].sort(byId);
  const ids = new Set(nodes.map((n) => n.id));
  const edges = data.edges.filter((e) => ids.has(e.source) && ids.has(e.target)).sort((a, b) => {
    const left = edgeKey(a);
    const right = edgeKey(b);
    return left < right ? -1 : left > right ? 1 : 0;
  });
  const adjacency = new Map(nodes.map((n) => [n.id, new Set<string>()]));
  for (const e of edges) {
    adjacency.get(e.source)!.add(e.target);
    adjacency.get(e.target)!.add(e.source);
  }
  const courses = new Map<string, GraphNode[]>();
  for (const n of nodes) {
    const key = n.course_id || "";
    const group = courses.get(key) ?? [];
    group.push(n);
    courses.set(key, group);
  }
  const maxCourseSize = Math.max(0, ...[...courses.values()].map((group) => group.length));
  const dense = maxCourseSize > 13;
  const denseCellSize = Math.max(1000, 2 * (325 + Math.ceil(maxCourseSize / 16) * 90) + 180);
  const courseOutput: PenGraphNodeLayout[][] = [];
  const keys = [...courses.keys()].sort();
  keys.forEach((courseId, courseIndex) => {
    const group = courses.get(courseId)!;
    const groupIds = new Set(group.map((n) => n.id));
    const nodeById = new Map(group.map((n) => [n.id, n]));
    const pattern = courseIndex % 2 === 0 ? SOURCE_LEFT : SOURCE_RIGHT;
    const hubPreset = sourceById.get(pattern[0])!;
    const dx = dense ? denseCellSize / 2 - hubPreset.x + (courseIndex % 2) * denseCellSize : 0;
    const dy = dense ? denseCellSize / 2 - hubPreset.y + Math.floor(courseIndex / 2) * denseCellSize : Math.floor(courseIndex / 2) * 700;
    const placed = new Map<string, SourceNode>();
    const used = new Set<string>();
    const roots = group.filter((n) => n.is_subject_root);
    const first = roots[0] ?? group[0];
    const queue = [first.id];
    const seen = new Set<string>();
    const ordered: string[] = [];
    while (queue.length) {
      const id = queue.shift()!;
      if (seen.has(id)) continue;
      seen.add(id);
      ordered.push(id);
      queue.push(...[...(adjacency.get(id) ?? [])].filter((x) => groupIds.has(x) && !seen.has(x)).sort());
    }
    ordered.push(...group.filter((n) => !seen.has(n.id)).map((n) => n.id));
    const local: PenGraphNodeLayout[] = [];
    for (const [index, id] of ordered.entries()) {
      const n = nodeById.get(id)!;
      let candidate: SourceNode | undefined;
      if (index === 0) candidate = hubPreset;
      else {
        const parent = [...(adjacency.get(id) ?? [])].sort().find((p) => placed.has(p));
        const sourceParent = parent ? placed.get(parent)?.sourceId : undefined;
        const sourceChildren = PEN_GRAPH_SOURCE_EDGES.filter((e) => e.source === sourceParent).map((e) => e.target);
        const available = [...sourceChildren, ...pattern.slice(1)].find((slot) => pattern.includes(slot) && !used.has(slot));
        candidate = available ? sourceById.get(available) : undefined;
      }
      if (candidate) {
        used.add(candidate.sourceId);
        placed.set(id, candidate);
        local.push(makeNode(n, { x: candidate.x + dx, y: candidate.y + dy }, candidate));
      } else {
        const preset = n.is_subject_root ? PRESET_HUB : (adjacency.get(id)?.size ?? 0) > 1 ? PRESET_TOPIC : PRESET_LEAF;
        let attempt = 0;
        let position: PenPoint;
        do {
          const ring = Math.floor(attempt / 16);
          const radius = 325 + ring * 90;
          const angle = (attempt % 16) * Math.PI / 8 + (courseIndex % 2 ? 0 : Math.PI);
          position = { x: hubPreset.x + dx + Math.cos(angle) * radius, y: hubPreset.y + dy + Math.sin(angle) * radius };
          attempt++;
        } while (local.some((p) => Math.hypot(p.x - position.x, p.y - position.y) < p.r + preset.r + 22));
        local.push(makeNode(n, position, preset));
      }
    }
    courseOutput.push(local);
  });
  const output = compactCourses(courseOutput, edges);
  // Include the complete branch control hull as well as node paint. This
  // keeps projected organic curves inside the fitted overview.
  const bounds = paintBounds(output, edges);
  const left = bounds.left;
  const top = bounds.top;
  const adjusted = output.map((n) => makeNode(n, { x: n.x - left, y: n.y - top }, sourceById.get(n.sourceId)!)).sort(byId);
  const layoutById = new Map(adjusted.map((n) => [n.id, n]));
  const duplicateOrdinal = new Map<string, number>();
  const laidEdges = edges.map((e, index) => {
    const key = edgeKey(e);
    const ordinal = duplicateOrdinal.get(key) ?? 0;
    duplicateOrdinal.set(key, ordinal + 1);
    return {
      ...penBranchFor(layoutById.get(e.source)!, layoutById.get(e.target)!, index),
      id: `${key}:${ordinal}`, source: e.source, target: e.target,
    };
  });
  return {
    nodes: adjusted, edges: laidEdges,
    width: Math.max(PEN_GRAPH_VIEWBOX.width, bounds.right - left),
    height: Math.max(PEN_GRAPH_VIEWBOX.height, bounds.bottom - top),
  };
}

/** Explicit design-only data. Sample CAS names never enter live adaptation. */
export function createPenGraphFixture(): PenGraphData {
  const leftIds = new Set(SOURCE_LEFT);
  const tierByFill: Record<string, GraphNode["mastery_tier"]> = {
    "#A3B06D": "mastered", "#FCC98A": "learning", "#EF908F": "struggling", "#DECDC1": "unexplored",
  };
  return {
    nodes: PEN_GRAPH_SOURCE_NODES.map((n, index) => ({
      id: `${FIXTURE_PREFIX}${n.sourceId}`,
      name: n.kind === "hub" ? (n.sourceId === "B3NyPy" ? "CAS LX 250" : "CAS HS 526") : `Design concept ${index - 1}`,
      subject: leftIds.has(n.sourceId) ? "CAS LX 250" : "CAS HS 526",
      color: n.fill,
      is_subject_root: n.kind === "hub",
      mastery_tier: tierByFill[n.fill] ?? "unexplored",
      mastery_score: 0,
      course_id: `${FIXTURE_PREFIX}${leftIds.has(n.sourceId) ? "B3NyPy" : "S6yVOt"}`,
    })),
    edges: PEN_GRAPH_SOURCE_EDGES.map((e) => ({ source: `${FIXTURE_PREFIX}${e.source}`, target: `${FIXTURE_PREFIX}${e.target}`, strength: 1 })),
  };
}

"use client";
/**
 * The Home screen's knowledge graph (Sapling Home v2). Home-only on purpose:
 * the shared `graph/KnowledgeGraph` (Learn, Tree) is a zoomable d3 canvas,
 * while the design here is a calm, fixed composition: one course hub with its
 * concepts around it, a "Family Tree" that re-stacks the goal's prerequisite
 * chain into generations, and a hover card with a single call to action.
 *
 * Layouts are computed per state (all courses / one course / family tree)
 * and the view tweens between them over 750ms, like the prototype.
 */
import React from "react";
import { forceSimulation, forceLink, forceManyBody, forceCollide, forceX, forceY, type SimulationNodeDatum } from "d3-force";
import type { GraphEdge, GraphNode } from "@/lib/data";
import { IS_TEST_MODE } from "@/lib/testMode";
import { usePrefersReducedMotion } from "@/lib/usePrefersReducedMotion";
import styles from "./Home.module.css";
import {
  STATUS,
  TIER_LOOK,
  chainOf,
  darkerRgb,
  isReady,
  isSolid,
  needsRefresh,
  prereqsOf,
  type CourseFocus,
  type Prereqs,
} from "./homeModel";

export type HomeCourse = { id: string; code: string; name: string; rgb: string };
export type GraphMode = "graph" | "tree";

export const GEN_LABELS = ["Your Goal", "Needs", "Before That", "Earlier", "Foundations"];
export const HATCH = "repeating-linear-gradient(135deg, rgba(255,255,255,0.55) 0 2px, transparent 2px 6px)";
const BG = "#FAF8F3";
const DUR = 750;

type P = { x: number; y: number; op: number };
type HubP = P & { s: number };
type Layout = {
  pts: Record<string, P>;
  hubs: Record<string, HubP>;
  /** 0 = graph shapes, 1 = family-tree shapes. */
  tree: number;
  /** 1 when a single course is focused (notes under names show). */
  notes: number;
};

const ease = (q: number) => (q < 0.5 ? 4 * q * q * q : 1 - Math.pow(-2 * q + 2, 3) / 2);
const lerp = (a: number, b: number, k: number) => a + (b - a) * k;

function lerpLayout(a: Layout, b: Layout, k: number): Layout {
  const pts: Record<string, P> = {};
  for (const id of new Set([...Object.keys(a.pts), ...Object.keys(b.pts)])) {
    const p = a.pts[id] ?? { ...b.pts[id], op: 0 };
    const q = b.pts[id] ?? { ...a.pts[id], op: 0 };
    pts[id] = { x: lerp(p.x, q.x, k), y: lerp(p.y, q.y, k), op: lerp(p.op, q.op, k) };
  }
  const hubs: Record<string, HubP> = {};
  for (const id of new Set([...Object.keys(a.hubs), ...Object.keys(b.hubs)])) {
    const p = a.hubs[id] ?? { ...b.hubs[id], op: 0 };
    const q = b.hubs[id] ?? { ...a.hubs[id], op: 0 };
    hubs[id] = { x: lerp(p.x, q.x, k), y: lerp(p.y, q.y, k), op: lerp(p.op, q.op, k), s: lerp(p.s, q.s, k) };
  }
  return { pts, hubs, tree: lerp(a.tree, b.tree, k), notes: lerp(a.notes, b.notes, k) };
}

/** Radius of a concept dot. The goal is drawn larger, as in the design. */
export function nodeRadius(n: GraphNode, isGoal: boolean): number {
  return isGoal ? 22 : Math.round(8 + TIER_LOOK[n.mastery_tier][0] * 12);
}

// ── Layouts ──────────────────────────────────────────────────────────────────

type Sim = SimulationNodeDatum & { id: string };

/** Unit-free force layout of one course around its hub at (0, 0). Deterministic:
 *  d3-force seeds its initial placement and jiggle with a fixed LCG. */
function forceLayout(ids: string[], edges: GraphEdge[]): Map<string, { x: number; y: number }> {
  const set = new Set(ids);
  const sim: Sim[] = [{ id: "__hub", fx: 0, fy: 0 }, ...ids.map((id) => ({ id }))];
  const links = [
    ...ids.map((id) => ({ source: "__hub", target: id, d: 230, s: 0.12 })),
    ...edges.filter((e) => set.has(e.source) && set.has(e.target) && e.source !== e.target)
      .map((e) => ({ source: e.source, target: e.target, d: 150, s: 0.35 })),
  ];
  const s = forceSimulation(sim)
    .force("link", forceLink<Sim, (typeof links)[number] & { source: string | Sim; target: string | Sim }>(links)
      .id((d) => d.id).distance((l) => l.d).strength((l) => l.s))
    .force("charge", forceManyBody().strength(-700))
    .force("collide", forceCollide(64))
    .force("x", forceX(0).strength(0.02))
    .force("y", forceY(0).strength(0.05))
    .stop();
  s.tick(300);
  return new Map(sim.slice(1).map((n) => [n.id, { x: n.x ?? 0, y: n.y ?? 0 }]));
}

const PAD_L = 60, PAD_R = 260, PAD_T = 40, PAD_B = 50;

function clampPt(x: number, y: number, W: number, H: number) {
  return { x: Math.max(PAD_L * 0.5, Math.min(W - 40, x)), y: Math.max(20, Math.min(H - 20, y)) };
}

/** Every course visible: hubs on an ellipse, concepts ringed around each. */
function allLayout(courses: HomeCourse[], byCourse: Map<string, GraphNode[]>, W: number, H: number) {
  const pts: Record<string, P> = {};
  const hubs: Record<string, HubP> = {};
  const cx = W / 2 - 40, cy = H / 2;
  const n = courses.length;
  courses.forEach((c, i) => {
    const a0 = n === 2 ? Math.PI : -Math.PI / 2;
    const a = a0 + (i * 2 * Math.PI) / Math.max(1, n);
    const hx = n === 1 ? cx : cx + Math.cos(a) * W * 0.3;
    const hy = n === 1 ? cy : cy + Math.sin(a) * H * 0.3;
    hubs[c.id] = { x: hx, y: hy, op: 1, s: 0 };
    const kids = byCourse.get(c.id) ?? [];
    const rr = Math.min(n === 1 ? H * 0.38 : H * 0.17, 60 + 7 * kids.length);
    kids.forEach((k, j) => {
      const ang = -Math.PI / 2 + 0.5 + (j * 2 * Math.PI) / kids.length;
      pts[k.id] = { ...clampPt(hx + Math.cos(ang) * rr * 1.3, hy + Math.sin(ang) * rr, W, H), op: 1 };
    });
  });
  return { pts, hubs };
}

/** Longest path from each chain concept up to the goal, clipped to the 5 rows. */
function generations(goalId: string, chain: Set<string>, prereqs: Prereqs): Map<string, number> {
  const dependents = new Map<string, string[]>();
  for (const id of chain) for (const p of prereqsOf(id, prereqs)) {
    if (!chain.has(p)) continue;
    dependents.set(p, [...(dependents.get(p) ?? []), id]);
  }
  const memo = new Map<string, number>();
  const visiting = new Set<string>();
  const gen = (id: string): number => {
    if (id === goalId) return 0;
    if (memo.has(id)) return memo.get(id) as number;
    if (visiting.has(id)) return 0;
    visiting.add(id);
    const g = 1 + Math.max(0, ...(dependents.get(id) ?? []).map(gen));
    visiting.delete(id);
    memo.set(id, g);
    return g;
  };
  return new Map([...chain].map((id) => [id, Math.min(GEN_LABELS.length - 1, gen(id))]));
}

export function treeRows(H: number) {
  const gap = (H - 120) / (GEN_LABELS.length - 1);
  return GEN_LABELS.map((label, i) => ({ label, y: 60 + i * gap }));
}

function treeLayout(goalId: string, prereqs: Prereqs, W: number, H: number) {
  const chain = chainOf(goalId, prereqs);
  const gens = generations(goalId, chain, prereqs);
  const rows = treeRows(H);
  const fx = new Map<string, number>([[goalId, 0.47]]);
  const pts: Record<string, P> = {};
  const rowSize = new Map<string, number>();
  for (let g = 0; g < GEN_LABELS.length; g++) {
    const row = [...chain].filter((id) => gens.get(id) === g);
    if (g > 0) {
      // Order each row under the concepts that need it, so lines cross less.
      const key = (id: string) => {
        const deps = [...chain].filter((d) => prereqsOf(d, prereqs).includes(id) && fx.has(d));
        return deps.length ? deps.reduce((s, d) => s + (fx.get(d) as number), 0) / deps.length : 0.5;
      };
      row.sort((a, b) => key(a) - key(b) || a.localeCompare(b));
      row.forEach((id, i) => fx.set(id, row.length === 1 ? key(id) : 0.08 + (0.84 * (i + 0.5)) / row.length));
    }
    for (const id of row) {
      pts[id] = { x: 150 + (fx.get(id) as number) * (W - 330), y: rows[g].y, op: 1 };
      rowSize.set(id, row.length);
    }
  }
  return { pts, rowSize };
}

// ── Tween ────────────────────────────────────────────────────────────────────

function useTweened(target: Layout, animKey: string, animate: boolean): Layout {
  const [shown, setShown] = React.useState(target);
  const shownRef = React.useRef(target);
  const keyRef = React.useRef(animKey);
  React.useEffect(() => {
    const changed = keyRef.current !== animKey;
    keyRef.current = animKey;
    if (!changed || !animate) {
      shownRef.current = target;
      setShown(target);
      return;
    }
    const from = shownRef.current;
    const t0 = performance.now();
    let raf = 0;
    const step = (now: number) => {
      const q = Math.min(1, (now - t0) / DUR);
      const l = q >= 1 ? target : lerpLayout(from, target, ease(q));
      shownRef.current = l;
      setShown(l);
      if (q < 1) raf = requestAnimationFrame(step);
    };
    raf = requestAnimationFrame(step);
    return () => cancelAnimationFrame(raf);
  }, [target, animKey, animate]);
  return shown;
}

// ── Component ────────────────────────────────────────────────────────────────

export type HomeGraphProps = {
  nodes: GraphNode[];
  edges: GraphEdge[];
  prereqs: Prereqs;
  courses: HomeCourse[];
  /** "all" or a course id. */
  course: string;
  mode: GraphMode;
  focus: Map<string, CourseFocus>;
  /** Note under the goal, e.g. "Your Goal · On Friday's Exam". */
  goalNote: (courseId: string) => string;
  nowMs: number;
  width: number;
  height: number;
  highlightId?: string | null;
  onSelectCourse: (courseId: string) => void;
  onOpen: (n: GraphNode) => void;
};

/** Course-focused graphs show every name up to this many concepts. */
const NAME_CAP_FOCUSED = 40;
/** In the all-courses view a course's names show only when it is this small. */
const NAME_CAP_ALL = 10;
/** A family-tree row this crowded shows names on hover only. */
const NAME_CAP_ROW = 6;

export function HomeGraph(props: HomeGraphProps) {
  const { nodes, edges, prereqs, courses, course, mode, focus, goalNote, nowMs, width: W, height: H, highlightId, onSelectCourse, onOpen } = props;
  const reduced = usePrefersReducedMotion();
  const [sel, setSel] = React.useState<string | null>(null);
  // A new course or view drops the hovered concept (not on mount: a hover
  // that lands before the first effects flush must survive).
  const selKey = `${course}|${mode}`;
  const selKeyRef = React.useRef(selKey);
  React.useEffect(() => {
    if (selKeyRef.current === selKey) return;
    selKeyRef.current = selKey;
    setSel(null);
  }, [selKey]);

  const byId = React.useMemo(() => new Map(nodes.map((n) => [n.id, n])), [nodes]);
  const courseById = React.useMemo(() => new Map(courses.map((c) => [c.id, c])), [courses]);
  const byCourse = React.useMemo(() => {
    const m = new Map<string, GraphNode[]>();
    for (const n of nodes) m.set(n.course_id, [...(m.get(n.course_id) ?? []), n]);
    for (const list of m.values()) list.sort((a, b) => a.name.localeCompare(b.name));
    return m;
  }, [nodes]);

  const focused = course !== "all" ? course : null;
  const focusedIds = React.useMemo(() => (focused ? (byCourse.get(focused) ?? []).map((n) => n.id) : []), [focused, byCourse]);
  const unitLayout = React.useMemo(() => forceLayout(focusedIds, edges), [focusedIds, edges]);
  const goalId = focused ? focus.get(focused)?.goalId ?? null : null;
  const treeOn = mode === "tree" && !!goalId;

  const hubXY = { x: W / 2 - 40, y: H / 2 };
  const target = React.useMemo<{ layout: Layout; rowSize: Map<string, number> }>(() => {
    const all = allLayout(courses, byCourse, W, H);
    if (!focused) return { layout: { ...all, tree: 0, notes: 0 }, rowSize: new Map() };
    const pts: Record<string, P> = Object.fromEntries(Object.entries(all.pts).map(([k, v]) => [k, { ...v, op: 0 }]));
    const hubs: Record<string, HubP> = Object.fromEntries(Object.entries(all.hubs).map(([k, v]) => [k, { ...v, op: 0 }]));
    // Scale the unit layout into the box around the hub, separately per side
    // (labels run right, so the right side keeps room for them).
    const rel = [...unitLayout.entries()];
    const maxOf = (f: (p: { x: number; y: number }) => number) => Math.max(1, ...rel.map(([, p]) => f(p)));
    const sxL = Math.min(1.8, (hubXY.x - PAD_L) / maxOf((p) => -p.x));
    const sxR = Math.min(1.8, (W - PAD_R - hubXY.x) / maxOf((p) => p.x));
    const syT = Math.min(1.8, (hubXY.y - PAD_T) / maxOf((p) => -p.y));
    const syB = Math.min(1.8, (H - PAD_B - hubXY.y) / maxOf((p) => p.y));
    for (const [id, p] of rel) {
      pts[id] = { ...clampPt(hubXY.x + p.x * (p.x < 0 ? sxL : sxR), hubXY.y + p.y * (p.y < 0 ? syT : syB), W, H), op: 1 };
    }
    hubs[focused] = { x: hubXY.x, y: hubXY.y, op: 1, s: 1 };
    if (!treeOn || !goalId) return { layout: { pts, hubs, tree: 0, notes: 1 }, rowSize: new Map() };
    const tree = treeLayout(goalId, prereqs, W, H);
    for (const id of focusedIds) pts[id] = tree.pts[id] ?? { ...pts[id], op: 0 };
    hubs[focused] = { x: hubXY.x, y: hubXY.y - 40, op: 0, s: 1 };
    return { layout: { pts, hubs, tree: 1, notes: 1 }, rowSize: tree.rowSize };
    // hubXY derives from W/H.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [courses, byCourse, focused, focusedIds, unitLayout, treeOn, goalId, prereqs, W, H]);

  const shown = useTweened(target.layout, `${course}|${treeOn ? "tree" : "graph"}`, !IS_TEST_MODE && !reduced);

  const activeSel = sel ?? (highlightId && byId.has(highlightId) && (shown.pts[highlightId]?.op ?? 0) > 0.5 ? highlightId : null);
  const chain = activeSel ? chainOf(activeSel, prereqs) : null;

  const ctxOf = (n: GraphNode) => focus.get(n.course_id) ?? { goalId: null, hereId: null, steps: [] };
  const rgbOf = (courseId: string) => courseById.get(courseId)?.rgb ?? "192,96,32";
  const R = (n: GraphNode) => nodeRadius(n, ctxOf(n).goalId === n.id);

  const visible = (id: string) => (shown.pts[id]?.op ?? 0) > 0.01;

  // ── Edges ──
  const lines: React.ReactNode[] = [];
  for (const [i, e] of edges.entries()) {
    const a = byId.get(e.source), b = byId.get(e.target);
    if (!a || !b || a.id === b.id || !visible(a.id) || !visible(b.id)) continue;
    const p = shown.pts[a.id], q = shown.pts[b.id];
    const baseOp = Math.min(p.op, q.op);
    if (a.course_id !== b.course_id) {
      lines.push(
        <line key={`x${i}`} x1={p.x} y1={p.y} x2={q.x} y2={q.y} stroke="#6F6857" strokeWidth={1.2}
          strokeDasharray="4 4" strokeOpacity={baseOp * (1 - shown.tree) * 0.45} />,
      );
      continue;
    }
    const ordered = e.relationship_type === "prerequisite" || e.relationship_type === "builds_on";
    const t = shown.tree;
    const Ra = R(a), Rb = R(b);
    const L = Math.hypot(q.x - p.x, q.y - p.y) || 1, ux = (q.x - p.x) / L, uy = (q.y - p.y) / L;
    const lp = (u: number, v: number) => u + (v - u) * t;
    const sx = lp(p.x + ux * Ra, p.x), sy = lp(p.y + uy * Ra, p.y - Ra);
    const ex = lp(q.x - ux * Rb, q.x), ey = lp(q.y - uy * Rb, q.y + Rb);
    const my = (sy + ey) / 2;
    const c1x = lp(sx + (ex - sx) / 3, sx), c1y = lp(sy + (ey - sy) / 3, my);
    const c2x = lp(sx + (2 * (ex - sx)) / 3, ex), c2y = lp(sy + (2 * (ey - sy)) / 3, my);
    const on = !!chain && chain.has(a.id) && chain.has(b.id) && ordered;
    const op = (chain ? (on ? 0.85 : 0.12) : 0.3) * baseOp * (ordered ? 1 : 1 - t);
    lines.push(
      <path key={`e${i}`} d={`M${sx},${sy} C${c1x},${c1y} ${c2x},${c2y} ${ex},${ey}`} fill="none"
        stroke={on ? `rgb(${rgbOf(a.course_id)})` : "#6F6857"} strokeWidth={on ? 2 : 1.34} strokeOpacity={op}
        strokeLinejoin="round" strokeLinecap="round" />,
    );
  }
  const spokes: React.ReactNode[] = [];
  for (const c of courses) {
    const h = shown.hubs[c.id];
    if (!h || h.op <= 0.01) continue;
    const hr = (22 + 8 * h.s) * (1 - 0.25 * (1 - h.s));
    for (const n of byCourse.get(c.id) ?? []) {
      const p = shown.pts[n.id];
      if (!p || p.op <= 0.01) continue;
      const L = Math.hypot(p.x - h.x, p.y - h.y) || 1, r = R(n);
      spokes.push(
        <line key={`s${n.id}`} x1={h.x + ((p.x - h.x) / L) * hr} y1={h.y + ((p.y - h.y) / L) * hr}
          x2={p.x - ((p.x - h.x) / L) * r} y2={p.y - ((p.y - h.y) / L) * r} stroke={`rgb(${c.rgb})`}
          strokeWidth={1.2} strokeLinecap="round"
          strokeOpacity={Math.min(h.op, p.op) * (1 - shown.tree) * (chain ? 0.08 : 0.28)} />,
      );
    }
  }

  // ── Hover card ──
  let card: React.ReactNode = null;
  const selNode = activeSel ? byId.get(activeSel) : undefined;
  if (selNode && shown.pts[selNode.id]) {
    const p = shown.pts[selNode.id], r = R(selNode);
    const ctx = ctxOf(selNode);
    const refresh = needsRefresh(selNode, nowMs);
    const word = STATUS[selNode.mastery_tier].word + (refresh ? ", needs a refresh" : "");
    const open = prereqsOf(selNode.id, prereqs).map((id) => byId.get(id)).filter((x): x is GraphNode => !!x && !isSolid(x));
    const cta = selNode.id === ctx.hereId
      ? { label: "Continue", to: selNode }
      : isSolid(selNode)
        ? { label: "Review", to: selNode }
        : open.length
          ? { label: `Learn ${open[0].name} First`, to: open[0] }
          : { label: "Learn This", to: selNode };
    const pct = Math.round(Math.max(0, Math.min(1, selNode.mastery_score)) * 100);
    const x = p.x + r + 236 > W ? p.x - r - 234 : p.x + r + 14;
    const y = Math.max(0, Math.min(p.y - 50, H - 130));
    card = (
      <div
        data-testid="home-graph-card"
        style={{
          position: "absolute", left: x, top: y, width: 220, boxSizing: "border-box", background: "#FDFCF9",
          border: "1px solid rgba(42,39,31,0.16)", borderRadius: 14, boxShadow: "0 14px 36px rgba(25,37,11,0.14)",
          padding: "12px 14px", zIndex: 10, display: "flex", flexDirection: "column", gap: 8,
        }}
      >
        <div style={{ display: "flex", alignItems: "baseline", gap: 8 }}>
          <span style={{ fontFamily: "var(--font-serif)", fontSize: 17, fontWeight: 600, minWidth: 0, overflow: "hidden", textOverflow: "ellipsis" }}>{selNode.name}</span>
          <span style={{ marginLeft: "auto", fontSize: 13, fontWeight: 600, color: "#3F3B31", flexShrink: 0 }}>{STATUS[selNode.mastery_tier].word}</span>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <span style={{ flex: 1, height: 6, borderRadius: 3, background: "#E6E2D9", overflow: "hidden" }}>
            <span style={{ display: "block", width: `${pct}%`, height: "100%", borderRadius: 3, background: STATUS[selNode.mastery_tier].bar }} />
          </span>
          <span style={{ fontSize: 14, fontWeight: 700, fontVariantNumeric: "tabular-nums" }}>{pct}%</span>
        </div>
        <button
          type="button"
          aria-label={`${cta.label}: ${cta.to.name}`}
          title={word}
          onClick={() => onOpen(cta.to)}
          className={styles.primary}
          style={{
            marginTop: 4, height: 34, border: 0, background: "#445D22", color: "#FFFFFF", borderRadius: 9,
            fontFamily: "inherit", fontSize: 14, fontWeight: 600, cursor: "pointer",
            whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis", padding: "0 10px",
          }}
        >
          {cta.label}
        </button>
      </div>
    );
  }

  const rows = treeRows(H);

  return (
    <div
      data-testid="home-graph"
      onMouseLeave={() => setSel(null)}
      style={{ position: "relative", width: "100%", height: "100%" }}
    >
      {rows.map((g) => (
        <React.Fragment key={g.label}>
          <span aria-hidden style={{ position: "absolute", left: 0, right: 0, top: g.y, height: 1, background: "rgba(42,39,31,0.06)", opacity: shown.tree }} />
          <span
            aria-hidden={shown.tree < 0.5}
            style={{
              position: "absolute", left: 0, top: g.y, transform: "translateY(-50%)", fontFamily: "var(--font-mono)",
              fontSize: 11, letterSpacing: "0.14em", textTransform: "uppercase", color: "#8A8372", background: BG,
              padding: "2px 8px 2px 0", opacity: shown.tree, pointerEvents: "none",
            }}
          >
            {g.label}
          </span>
        </React.Fragment>
      ))}
      <svg width={W} height={H} style={{ position: "absolute", left: 0, top: 0, overflow: "visible" }} aria-hidden="true">
        {spokes}
        {lines}
      </svg>

      {courses.map((c) => {
        const h = shown.hubs[c.id];
        if (!h || h.op <= 0.01) return null;
        const size = 44 + 16 * h.s;
        const dark = darkerRgb(c.rgb);
        return (
          <div
            key={`hub-${c.id}`}
            role="button"
            tabIndex={h.op > 0.5 ? 0 : -1}
            data-testid="home-graph-hub"
            aria-label={`${c.code}${c.name && c.name !== c.code ? ` ${c.name}` : ""}, course. Select to focus`}
            onClick={() => onSelectCourse(c.id)}
            onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onSelectCourse(c.id); } }}
            style={{
              cursor: "pointer", position: "absolute", left: h.x, top: h.y, transform: "translate(-50%, -50%)",
              width: size, height: size, borderRadius: "50%", background: `rgb(${c.rgb})`, boxSizing: "border-box",
              border: h.s > 0.5 ? `2.5px solid rgb(${c.rgb})` : undefined,
              boxShadow: h.s > 0.5
                ? `0 0 0 10px rgba(${c.rgb},0.10), 0 0 28px 10px rgba(${c.rgb},0.18)`
                : `0 0 0 8px rgba(${c.rgb},0.12), 0 0 24px 8px rgba(${c.rgb},0.12)`,
              opacity: h.op, pointerEvents: h.op > 0.5 ? "auto" : "none", zIndex: 1,
            }}
          >
            <span style={{ position: "absolute", top: "100%", marginTop: 8, left: "50%", transform: "translateX(-50%)", fontFamily: "var(--font-serif)", fontSize: 15, fontWeight: 600, color: dark, background: BG, padding: "0 4px", borderRadius: 4, whiteSpace: "nowrap", opacity: h.s }}>
              {c.code}{c.name && c.name !== c.code ? ` ${c.name}` : ""}
            </span>
            <span style={{ position: "absolute", bottom: "100%", marginBottom: 14, left: "50%", transform: "translateX(-50%)", fontFamily: "var(--font-serif)", fontSize: 17, fontWeight: 600, color: dark, whiteSpace: "nowrap", opacity: 1 - h.s }}>
              {c.code}
            </span>
          </div>
        );
      })}

      {nodes.map((n) => {
        const p = shown.pts[n.id];
        if (!p || p.op <= 0.01) return null;
        const ctx = ctxOf(n);
        const isGoal = ctx.goalId === n.id, here = ctx.hereId === n.id;
        const rgb = rgbOf(n.course_id);
        const [, fill] = TIER_LOOK[n.mastery_tier];
        const r = R(n);
        const refresh = needsRefresh(n, nowMs);
        const ready = isReady(n, byId, prereqs);
        const glow = `0 0 10px 4px rgba(${rgb},0.15)`;
        const ring = here
          ? `0 0 0 5px ${BG}, 0 0 0 7px rgba(${rgb},0.7), ${glow}`
          : ready
            ? `0 0 0 4px ${BG}, 0 0 0 5.5px rgba(${rgb},0.45), ${glow}`
            : glow;
        const firstOpen = prereqsOf(n.id, prereqs).map((id) => byId.get(id)).find((x) => x && !isSolid(x));
        const stepNo = here ? ctx.steps.indexOf(n.id) + 1 : 0;
        const note = here
          ? `You Are Here${stepNo > 0 ? ` · Step ${stepNo} of ${ctx.steps.length}` : ""}`
          : isGoal
            ? goalNote(n.course_id)
            : ready
              ? "Ready to Learn"
              : n.mastery_tier === "struggling"
                ? "Struggling"
                : refresh
                  ? "Needs a Refresh"
                  : isSolid(n)
                    ? "Mastered"
                    : n.mastery_tier === "learning"
                      ? "Learning"
                      : firstOpen
                        ? `Learn ${firstOpen.name} First`
                        : "Not Started";
        const word = STATUS[n.mastery_tier].word + (refresh ? ", needs a refresh" : "");
        const count = byCourse.get(n.course_id)?.length ?? 0;
        const showName = shown.tree > 0.5
          ? (target.rowSize.get(n.id) ?? 0) <= NAME_CAP_ROW || isGoal || here
          : shown.notes > 0.5
            ? count <= NAME_CAP_FOCUSED || isGoal || here
            : count <= NAME_CAP_ALL;
        const dim = chain ? (chain.has(n.id) ? 1 : 0.28) : 1;
        const noteVisible = shown.notes;
        return (
          <div
            key={n.id}
            role="button"
            tabIndex={p.op > 0.5 ? 0 : -1}
            data-testid="home-graph-node"
            data-node-id={n.id}
            aria-label={`${n.name}, ${word}, ${note}`}
            title={showName ? undefined : n.name}
            onMouseEnter={() => setSel(n.id)}
            onFocus={() => setSel(n.id)}
            onClick={() => onOpen(n)}
            onKeyDown={(e) => { if (e.key === "Enter") onOpen(n); }}
            style={{
              pointerEvents: p.op > 0.5 ? "auto" : "none", position: "absolute", left: p.x, top: p.y,
              transform: `translate(-${r}px, -50%)`, display: "flex", alignItems: "center", gap: 10,
              opacity: p.op * dim, cursor: "pointer", zIndex: 2, transition: "opacity 160ms ease", outline: "none",
            }}
          >
            <span
              style={{
                position: "relative", width: r * 2, height: r * 2, borderRadius: "50%", background: `rgba(${rgb},${fill})`,
                border: `${isGoal ? 2.5 : 1.5}px solid rgba(${rgb},0.4)`, boxShadow: ring, boxSizing: "border-box",
                overflow: "hidden", display: "grid", placeItems: "center", flexShrink: 0,
              }}
            >
              <span style={{ position: "absolute", inset: 0, background: refresh ? HATCH : "none" }} />
            </span>
            {showName && (
              <span style={{ lineHeight: 1.2, background: BG, padding: "2px 6px 2px 2px", borderRadius: 4, whiteSpace: "nowrap" }}>
                <span
                  style={{
                    display: "block", fontSize: isGoal ? 17 : 14, fontWeight: isGoal ? 600 : here ? 700 : 500, color: "#1A1814",
                    fontFamily: isGoal ? "var(--font-serif)" : "inherit",
                  }}
                >
                  {n.name}
                </span>
                {noteVisible > 0.01 && (
                  <span style={{ display: "block", fontSize: 13, color: here ? "#445D22" : isGoal ? darkerRgb(rgb) : ready ? "#597536" : "#6F6857", opacity: noteVisible }}>
                    {note}
                  </span>
                )}
              </span>
            )}
          </div>
        );
      })}
      {card}
    </div>
  );
}

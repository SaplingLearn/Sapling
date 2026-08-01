'use client';

import { useEffect, useMemo, useRef, useState } from 'react';

import { IS_TEST_MODE, now } from '@/lib/testMode';

import { COURSE_GRAPHS, TIER_COLOR, type CourseGraph } from './courseGraphs';
import { helixEntry, radialLayout, type Point } from './layout';

const VIEW_W = 900;
const VIEW_H = 560;

/** How long the helical assembly takes to land on the laid-out frame. */
const ASSEMBLE_MS = 1100;

function nodeRadius(g: CourseGraph, id: string): number {
  return id === g.rootId ? 26 : 14;
}

/**
 * Renders one course's edges + nodes, animating them in along the helical
 * entry path (#344). The parent keys this by `graph.id`, so picking another
 * course remounts it — a fresh `progress` state per course instead of
 * resetting one inside an effect (the "adjusting state on a prop change"
 * anti-pattern React's own react-hooks/set-state-in-effect rule flags).
 * Remounting also means unmount cleanup alone is enough to cancel the RAF
 * both on course change and on real unmount — no separate reset path needed.
 */
function AssemblingGraph({
  graph,
  points,
  parked,
}: {
  graph: CourseGraph;
  points: Map<string, Point>;
  parked: boolean;
}) {
  // "Parked" means the assembly is skipped and the graph renders complete —
  // fully laid out, full opacity — on the very first frame. Reduced-motion
  // visitors and the E2E/unit-test lanes (IS_TEST_MODE) both get this.
  const [progress, setProgress] = useState(parked ? 1 : 0);
  const rafRef = useRef(0);

  useEffect(() => {
    if (parked) return;
    const start = now();
    const tick = () => {
      const p = Math.min(1, (now() - start) / ASSEMBLE_MS);
      setProgress(p);
      if (p < 1) rafRef.current = requestAnimationFrame(tick);
    };
    rafRef.current = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(rafRef.current);
  }, [parked]);

  return (
    <>
      {graph.edges.map((e) => {
        const a = points.get(e.source);
        const b = points.get(e.target);
        if (!a || !b) return null;
        return (
          <line
            key={`${e.source}-${e.target}`}
            x1={a.x}
            y1={a.y}
            x2={b.x}
            y2={b.y}
            stroke="var(--text-dim)"
            strokeOpacity={0.28 * progress}
            strokeWidth={1.4}
          />
        );
      })}

      {graph.nodes.map((n, i) => {
        const p = points.get(n.id);
        if (!p) return null;
        // Stagger: later nodes start later, all finish by progress = 1.
        const span = 1 / (graph.nodes.length + 2);
        const local = Math.min(1, Math.max(0, (progress - i * span) / (1 - i * span)));
        const h = helixEntry(p, { x: VIEW_W / 2, y: VIEW_H / 2 }, local);
        const r = nodeRadius(graph, n.id);
        return (
          <g key={n.id} data-testid={`landing-graph-node-${n.id}`} opacity={h.opacity}>
            <circle cx={h.x} cy={h.y} r={r * h.scale} fill={TIER_COLOR[n.tier]} />
            <text
              x={h.x}
              y={h.y + r + 16}
              textAnchor="middle"
              className="font-jetbrains"
              fontSize={12}
              fill="var(--text-dim)"
              opacity={h.opacity}
            >
              {n.label}
            </text>
          </g>
        );
      })}
    </>
  );
}

export default function KnowledgeGraphDemo() {
  const [courseId, setCourseId] = useState(COURSE_GRAPHS[0].id);

  const graph = useMemo(
    () => COURSE_GRAPHS.find((g) => g.id === courseId) ?? COURSE_GRAPHS[0],
    [courseId],
  );
  const points = useMemo(() => radialLayout(graph, VIEW_W, VIEW_H), [graph]);

  const prefersReduced =
    typeof window !== 'undefined' &&
    typeof window.matchMedia === 'function' &&
    window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  const parked = IS_TEST_MODE || prefersReduced;

  return (
    <section
      id="knowledge-graph"
      data-testid="landing-graph"
      aria-label={`Interactive knowledge graph for ${graph.name}`}
      className="landing-section landing-graph relative z-10 py-24 md:py-32"
    >
      <div className="max-w-7xl mx-auto px-6 lg:px-12">
        <div data-testid="landing-graph-copy" className="landing-graph-copy">
          <span className="font-jetbrains text-[0.7rem] tracking-[0.32em] text-[var(--brand-forest)] uppercase font-medium">
            Your knowledge, mapped
          </span>
          <h2 className="font-playfair text-4xl md:text-6xl font-semibold text-[var(--text)] mt-4 leading-[1.05] tracking-tight">
            Pick a course. Watch it grow.
          </h2>
        </div>

        <div className="mt-8 flex flex-wrap gap-3">
          {COURSE_GRAPHS.map((g) => {
            const active = g.id === graph.id;
            return (
              <button
                key={g.id}
                type="button"
                data-testid={`landing-graph-chip-${g.id}`}
                aria-pressed={active}
                onClick={() => setCourseId(g.id)}
                className={`landing-graph-chip${active ? ' is-active' : ''}`}
              >
                {g.code}
              </button>
            );
          })}
        </div>

        <svg
          viewBox={`0 0 ${VIEW_W} ${VIEW_H}`}
          className="mt-8 w-full h-auto"
          role="img"
          aria-label={`${graph.name} concept graph`}
        >
          <AssemblingGraph key={graph.id} graph={graph} points={points} parked={parked} />
        </svg>
      </div>
    </section>
  );
}

'use client';

import { useEffect, useMemo, useRef, useState } from 'react';

import { IS_TEST_MODE, now } from '@/lib/testMode';
import { usePrefersReducedMotion } from '@/lib/usePrefersReducedMotion';

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
 * course remounts it — a fresh `animatedProgress` state per course instead
 * of resetting one inside an effect (the "adjusting state on a prop change"
 * anti-pattern React's own react-hooks/set-state-in-effect rule flags).
 * Remounting also means unmount cleanup alone is enough to cancel the RAF
 * both on course change and on real unmount — no separate reset path needed.
 *
 * `progress` is derived from `animatedProgress`, not the state directly:
 * `parked` can flip after mount without a remount (`usePrefersReducedMotion`
 * corrects from its SSR-safe default to the real client value shortly after
 * hydration — see that hook's doc comment), and deriving `progress` this way
 * means that transition is correct in *both* directions without an effect
 * having to reconcile it: parked always reads back as the complete frame
 * regardless of whatever `animatedProgress` last held, and un-parking just
 * exposes whatever `animatedProgress` already is (still its unmounted-since
 * initial `0` if the assembly effect below hasn't started yet).
 */
function AssemblingGraph({
  graph,
  points,
  parked,
  onNodeEnter,
  onNodeLeave,
}: {
  graph: CourseGraph;
  points: Map<string, Point>;
  parked: boolean;
  onNodeEnter: (id: string) => void;
  onNodeLeave: () => void;
}) {
  const [animatedProgress, setAnimatedProgress] = useState(0);
  // "Parked" means the assembly is skipped and the graph renders complete —
  // fully laid out, full opacity — on the very first frame. Reduced-motion
  // visitors and the E2E/unit-test lanes (IS_TEST_MODE) both get this.
  const progress = parked ? 1 : animatedProgress;
  const rafRef = useRef(0);

  useEffect(() => {
    if (parked) return;
    const start = now();
    const tick = () => {
      const p = Math.min(1, (now() - start) / ASSEMBLE_MS);
      setAnimatedProgress(p);
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
          <g
            key={n.id}
            data-testid={`landing-graph-node-${n.id}`}
            opacity={h.opacity}
            onMouseEnter={() => onNodeEnter(n.id)}
            onMouseLeave={onNodeLeave}
          >
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

  // Interaction state (#344 task 5). Both live here, in the parent, rather
  // than inside `AssemblingGraph`: that child is keyed by `graph.id` and
  // remounts on every course switch, which would silently wipe any state
  // stored inside it. `engaged` in particular must survive a course switch
  // (once a visitor has interacted, the instructional copy stays faded for
  // the rest of the session) — that's only guaranteed by keeping it outside
  // the subtree that remounts. `hovered` doesn't strictly need the same
  // guarantee (a stale id from the previous course just fails the
  // `graph.nodes.find` lookup below and renders no blurb), but the blurb
  // paragraph itself is rendered here in the parent, as a sibling of the
  // `<svg>`, so the parent needs read access to "which node is hovered"
  // regardless. One state owner for both pieces of interaction state keeps
  // `AssemblingGraph` a plain layout/animation renderer that only takes
  // callback props, instead of splitting hover across two lifetimes for no
  // behavioral gain.
  const [hovered, setHovered] = useState<string | null>(null);
  const [engaged, setEngaged] = useState(false);

  function onNodeEnter(id: string) {
    setHovered(id);
    setEngaged(true);
  }

  function onNodeLeave() {
    setHovered(null);
  }

  const graph = useMemo(
    () => COURSE_GRAPHS.find((g) => g.id === courseId) ?? COURSE_GRAPHS[0],
    [courseId],
  );
  const points = useMemo(() => radialLayout(graph, VIEW_W, VIEW_H), [graph]);
  const hoveredBlurb = hovered ? graph.nodes.find((n) => n.id === hovered)?.blurb : undefined;

  // `usePrefersReducedMotion` (not a direct `window.matchMedia` read in the
  // render body — #344 fix round 1) is hydration-safe: it renders the same
  // value on the server and the first client paint, then corrects to the
  // real value after hydration commits. See its doc comment for why it
  // defaults to "reduced motion" rather than "no preference".
  const prefersReduced = usePrefersReducedMotion();
  const parked = IS_TEST_MODE || prefersReduced;

  return (
    <section
      id="knowledge-graph"
      data-testid="landing-graph"
      aria-label={`Interactive knowledge graph for ${graph.name}`}
      className="landing-section landing-graph relative z-10 py-24 md:py-32"
    >
      <div className="max-w-7xl mx-auto px-6 lg:px-12">
        <div
          data-testid="landing-graph-copy"
          data-engaged={engaged ? 'true' : 'false'}
          className="landing-graph-copy"
          style={{ opacity: engaged ? 0.35 : 1 }}
        >
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
          <AssemblingGraph
            key={graph.id}
            graph={graph}
            points={points}
            parked={parked}
            onNodeEnter={onNodeEnter}
            onNodeLeave={onNodeLeave}
          />
        </svg>

        {/*
          Reserved min-height (#344 task 5): the blurb text appears and
          disappears on every hover/unhover. Without a floor, the paragraph
          collapsing to empty on mouseleave shifts anything rendered below
          this section on every single hover — load-bearing, not cosmetic.
        */}
        <p
          data-testid="landing-graph-blurb"
          className="landing-graph-blurb font-inter text-[var(--text-dim)] mt-4 min-h-[1.5rem]"
        >
          {hoveredBlurb ?? ''}
        </p>
      </div>
    </section>
  );
}

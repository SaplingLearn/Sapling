'use client';

import { useMemo, useState } from 'react';

import { COURSE_GRAPHS, TIER_COLOR, type CourseGraph } from './courseGraphs';
import { radialLayout } from './layout';

const VIEW_W = 900;
const VIEW_H = 560;

function nodeRadius(g: CourseGraph, id: string): number {
  return id === g.rootId ? 26 : 14;
}

export default function KnowledgeGraphDemo() {
  const [courseId, setCourseId] = useState(COURSE_GRAPHS[0].id);

  const graph = useMemo(
    () => COURSE_GRAPHS.find((g) => g.id === courseId) ?? COURSE_GRAPHS[0],
    [courseId],
  );
  const points = useMemo(() => radialLayout(graph, VIEW_W, VIEW_H), [graph]);

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
                strokeOpacity={0.28}
                strokeWidth={1.4}
              />
            );
          })}

          {graph.nodes.map((n) => {
            const p = points.get(n.id);
            if (!p) return null;
            return (
              <g key={n.id} data-testid={`landing-graph-node-${n.id}`}>
                <circle cx={p.x} cy={p.y} r={nodeRadius(graph, n.id)} fill={TIER_COLOR[n.tier]} />
                <text
                  x={p.x}
                  y={p.y + nodeRadius(graph, n.id) + 16}
                  textAnchor="middle"
                  className="font-jetbrains"
                  fontSize={12}
                  fill="var(--text-dim)"
                >
                  {n.label}
                </text>
              </g>
            );
          })}
        </svg>
      </div>
    </section>
  );
}

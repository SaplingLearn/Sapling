'use client';

/**
 * The draggable course-cluster field.
 *
 * Ported from `Sapling Landing v5.dc.html`. Small course graphs float over the
 * lower half of the page and can be grabbed and thrown; `engine/sim.ts` owns
 * the physics and finds its targets through `[data-dragnode]`,
 * `[data-dragpuck]` and `[data-sim]`.
 *
 * Two constraints the markup has to honour, both easy to break by tidying:
 *
 * - The wrapper is `height:0`. The field is decorative and must never add
 *   page height, so it hangs out of a zero-height sticky box.
 * - `touch-action:none` on each cluster. Without it, dragging a node on a
 *   touch device scrolls the page instead of moving the node.
 *
 * Hidden below 1023px by the `.drag-field` rule in globals.css.
 */

import { DRAG_CLUSTERS, type DragCluster } from '@/lib/landing/dragClusters';

function Cluster({ c }: { c: DragCluster }) {
  return (
    <span
      data-dragnode={c.id}
      style={{
        position: 'absolute', ...c.pos,
        pointerEvents: 'none', cursor: 'grab',
        // must stay: otherwise a touch-drag scrolls the page
        touchAction: 'none',
        animation: c.anim, willChange: 'transform',
      }}
    >
      <span data-dragpuck="1" style={{ display: 'block', willChange: 'transform' }}>
        <svg
          width={c.svg.w}
          height={c.svg.h}
          viewBox={c.svg.vb}
          style={{
            display: 'block', overflow: 'visible', pointerEvents: 'none',
            // recentres the oversized box so the cluster sits where `pos` says
            margin: '-1600px -900px',
          }}
        >
          {c.lines.map((l, i) => (
            <line
              key={i} x1={l.x1} y1={l.y1} x2={l.x2} y2={l.y2}
              stroke="#6f6857" strokeOpacity="0.2" strokeWidth={l.w} strokeLinecap="round"
            />
          ))}
          {/*
            Flat, and strictly glow -> ring -> label per node. `engine/sim.ts`
            finds a ring's halo via `previousElementSibling` and its caption via
            `nextElementSibling`, so ANY wrapper element here (a <g>, a
            fragment that renders one) breaks the binding and the sim throws on
            a null label. Node 0 is the course puck, and its label is the
            course code.
          */}
          {c.nodes.flatMap((n, i) => {
            const label = i === 0
              ? { text: c.code, x: c.codeAt[0], y: c.codeAt[1] }
              : c.labels[i - 1];
            return [
              <circle
                key={`glow-${i}`}
                cx={n.cx} cy={n.cy} r={n.r + 8}
                fill={c.color} opacity="0.15" style={{ filter: 'blur(3px)' }}
              />,
              <circle
                key={`ring-${i}`}
                data-ring="1" data-sim="1"
                style={{ pointerEvents: 'auto', cursor: 'grab' }}
                cx={n.cx} cy={n.cy} r={n.r}
                fill={c.color} fillOpacity={n.fo}
                stroke={c.color} strokeWidth={n.sw} strokeOpacity="0.75"
              />,
              label ? (
                <text
                  key={`label-${i}`}
                  x={label.x} y={label.y} textAnchor="middle"
                  fontFamily={i === 0 ? "'Playfair Display',Georgia,serif" : "'DM Sans',sans-serif"}
                  fontSize={i === 0 ? '12.5' : '9'}
                  fontWeight={i === 0 ? '600' : undefined}
                  fill={i === 0 ? c.color : '#3f3b31'}
                  opacity={i === 0 ? undefined : 0.85}
                  style={{ pointerEvents: 'none', userSelect: 'none' }}
                >
                  {label.text}
                </text>
              ) : null,
            ];
          })}
        </svg>
      </span>
    </span>
  );
}

/** The field for one section. Renders nothing if that section has no clusters. */
export function DragField({ section }: { section: DragCluster['section'] }) {
  const mine = DRAG_CLUSTERS.filter((c) => c.section === section);
  return (
    <div
      className="drag-field"
      aria-hidden="true"
      style={{ position: 'sticky', top: 0, height: 0, zIndex: 2, pointerEvents: 'none', overflow: 'visible' }}
    >
      <div style={{ position: 'absolute', top: 0, left: 0, right: 0, height: '100vh', pointerEvents: 'none', overflow: 'visible' }}>
        {mine.map((c) => <Cluster key={c.id} c={c} />)}
      </div>
    </div>
  );
}

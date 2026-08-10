'use client';

/**
 * The draggable course-cluster field.
 *
 * Ported from `Sapling Landing v5.dc.html`. Small course graphs float over the
 * lower half of the page and can be grabbed and thrown; `engine/sim.ts` owns
 * the physics and finds its targets through `[data-dragnode]`,
 * `[data-dragpuck]` and `[data-sim]`.
 *
 * The field is decorative and must never add page height — see the two
 * wrapper shapes on `DragField` below, which is the whole reason it takes a
 * section rather than just rendering one box.
 *
 * `touch-action:none` on each cluster is also load-bearing: without it,
 * dragging a node on a touch device scrolls the page instead.
 *
 * Hidden below 1023px by the `.drag-field` rule in globals.css.
 */

import { DRAG_CLUSTERS, type DragCluster } from '@/lib/landing/dragClusters';

/**
 * Every section that carries a field.
 *
 * Wider than `DragCluster['section']`: `act-ingest` has a field but no
 * clusters in it, so it never appears in the data. It still needs the
 * element, because `engine/sim.ts` discovers fields by class and the pinned
 * shape is what keeps the act's motes off the page's height.
 */
export type FieldSection = DragCluster['section'] | 'act-ingest';

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

/**
 * The field for one section.
 *
 * Two shapes, and using the wrong one adds page height:
 *
 * - **Pinned acts** (`act-ingest`, `act-tutor`) put the field inside an
 *   `absolute; inset:0` box — out of flow, so it occupies no space in the
 *   act — and make the field itself `sticky; top:0; height:100vh`.
 * - **Static sections** (`faq`, `newsletter`, `cta`) use `absolute; inset:0`
 *   and hold the clusters directly. They must NOT get the 100vh layer: an
 *   absolutely positioned child still extends the document's scrollHeight,
 *   so on the last section it left a viewport's worth of dead scroll below
 *   the footer.
 *
 * **The `100vh` on the pinned shape is load-bearing, and it is not about
 * size.** Every act is a `position:relative` section holding one
 * `sticky; top:0; height:100vh` stage, and that height is what decides when
 * the stage stops sticking: it releases once the section's bottom reaches a
 * viewport-height above the fold. An earlier version of this component hung
 * a `100vh` layer out of a `sticky; height:0` box instead. A zero-height
 * sticky releases a whole viewport LATER, so for the last 100vh of every
 * act the copy scrolled away while the clusters stayed welded to the top of
 * the screen — measured at 882px of divergence through `act-tutor`. Matching
 * the stage's geometry is what keeps the two moving as one, through the
 * pin and through the release. If an act's stage ever stops being
 * `sticky; top:0; height:100vh`, this has to follow it.
 */
const PINNED = new Set<FieldSection>(['act-ingest', 'act-tutor']);

/**
 * Static sections whose copy pins on its own, and the element it pins in.
 *
 * A static field gets the section's rect, which is the right box for placing
 * clusters but says nothing about a child that sticks inside it. `faq` is
 * exactly that case: the question column is `sticky; top:110`, so it holds
 * still for `grid 733px - column 358px` = 375px while the section — and with
 * it the field, and with it CS 112 and PH 150 — keeps scrolling. The clusters
 * slid 374px out from under the words they belong to.
 *
 * Naming the copy here lets `engine/sim.ts` add back its travel, so the two
 * move as one through the pin and the release. This is the static-section
 * counterpart to `PINNED` above: that one matches a field to a stage it lives
 * beside, this one matches clusters to copy that pins beneath them.
 */
const TRACKS: Partial<Record<FieldSection, string>> = {
  faq: '[data-drag-anchor="faq"]',
};

export function DragField({ section }: { section: FieldSection }) {
  const mine = DRAG_CLUSTERS.filter((c) => c.section === section);
  const clusters = mine.map((c) => <Cluster key={c.id} c={c} />);

  if (!PINNED.has(section)) {
    return (
      <div
        className="drag-field"
        aria-hidden="true"
        data-drag-track={TRACKS[section]}
        style={{ position: 'absolute', inset: 0, zIndex: 2, pointerEvents: 'none', overflow: 'visible' }}
      >
        {clusters}
      </div>
    );
  }

  return (
    <div
      aria-hidden="true"
      style={{ position: 'absolute', inset: 0, zIndex: 2, pointerEvents: 'none', overflow: 'visible' }}
    >
      <div
        className="drag-field"
        style={{ position: 'sticky', top: 0, height: '100vh', pointerEvents: 'none', overflow: 'visible' }}
      >
        {clusters}
      </div>
    </div>
  );
}

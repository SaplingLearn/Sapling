'use client';

import { useEffect, useMemo, useRef, useState, type CSSProperties } from 'react';

import { IS_TEST_MODE, now } from '@/lib/testMode';
import { useIsMobile } from '@/lib/useIsMobile';
import { usePrefersReducedMotion } from '@/lib/usePrefersReducedMotion';

import { StateDot, SurfaceFrame, SurfaceRule } from '../surfaces/Surface';
import {
  COURSE_GRAPHS,
  TIER_COLOR,
  TIER_LABEL,
  TIER_ORDER,
  conceptNodes,
  neighbours,
  tierCounts,
  type CourseGraph,
  type DemoNode,
} from './courseGraphs';
import {
  DESKTOP_VIEW,
  MOBILE_VIEW,
  helixEntry,
  labelBaselineY,
  radialLayout,
  viewBoxAttr,
  type GraphView,
  type Point,
} from './layout';

/** How long the helical assembly takes to land on the laid-out frame. */
const ASSEMBLE_MS = 1100;

/**
 * When the section counts as "near enough to arm the assembly".
 *
 * Deliberately a NEGATIVE bottom inset, not the positive lead-in margin that
 * looks natural here. This section is mounted immediately after a
 * `min-h-screen` hero, so its top edge sits at exactly 100vh: *any* positive
 * bottom rootMargin makes it intersect at scroll position 0 and re-creates the
 * exact bug the gate exists to fix (#344 review #1) — the helix burning its
 * 1100ms during hydration, under the intro overlay, where nobody can see it.
 *
 * −10% instead means the section's top has to clear a tenth of the viewport
 * before the loop arms. There is still ample lead-in: the section opens with
 * `py-24` of padding plus the copy block and the chips, so ~300px of further
 * scrolling separates arming from the SVG itself appearing — the assembly is
 * already underway by the time the graph is on screen.
 */
const ARM_ROOT_MARGIN = '0px 0px -10% 0px';

/**
 * Opacity the headline fades to once the visitor engages with the graph.
 *
 * Not the 0.35 this shipped with (#344 review #2). Composited over the flat
 * `--bg` paper (#faf8f3) this section renders on, `--text` (#1a1814) at 0.35 is
 * #ACAAA5 = 2.20:1 — under the 3:1 WCAG AA bar for large text, permanently,
 * because `engaged` never resets. At 0.55 it composites to #7F7D78 = 3.88:1,
 * which clears it with room to spare while still reading as a clear recede.
 *
 * The eyebrow above the headline is deliberately NOT faded: it's 0.7rem
 * (small text ⇒ 4.5:1), and `--brand-forest` (#1B6C42) needs α ≥ 0.86 to hold
 * that ratio — a "fade" nobody can perceive. Since CSS opacity on the wrapper
 * would group both elements and a child can never be *more* opaque than its
 * group, the fade lives on the headline alone.
 */
export const ENGAGED_HEADLINE_OPACITY = 0.55;

/**
 * Ambient drift, in SVG user units (#344 step 3).
 *
 * The brand guide describes the page's atmosphere as "a barely-there field of
 * colourful orbs drifting slowly in 3D — like the glow under water", and the
 * hero's canvas does exactly that. This section was frozen the moment its
 * assembly landed, which read as a diagram rather than as a living map.
 *
 * THREE UNITS, and the ceiling is not taste — it is the frame. `fitViewBox`
 * fits the desktop `viewBox` to the entry sweep with `fitPad: 10` of margin, so
 * anything up to 10 units of post-settle displacement stays inside the box; 3
 * spends less than a third of that. The phone view's pad is 2 and its worst
 * label-to-neighbour clearance is 5.40 units, which two nodes drifting toward
 * each other would eat — so the phone does not drift at all (see `drifting`
 * below). At the 720px desktop cap 3 units is ~3.7 CSS px: perceptible as
 * breathing, invisible as movement.
 *
 * The motion is a CSS animation, not a rAF loop, on purpose. It composites off
 * the main thread, it costs zero React re-renders for a section that already
 * re-renders on hover, the global `prefers-reduced-motion` reset in globals.css
 * neutralises it for free, and — decisively — it stays out of the assembly's
 * rAF budget, which `KnowledgeGraphDemo.test.tsx` counts frame by frame to
 * prove the helix neither fires early nor replays.
 */
const DRIFT_AMPLITUDE = 3;
const DRIFT_MIN_S = 13;
const DRIFT_SPAN_S = 9;

/** Two decimals is plenty for user units, and keeps the SSR payload small. */
function r2(v: number): number {
  return Math.round(v * 100) / 100;
}

/**
 * FNV-1a over the node id — a per-node drift phase that is a pure function of
 * the fixture.
 *
 * NOT `Math.random()`, and not `testMode.random()` either: this value is baked
 * into a `style` attribute that React renders on the server and then diffs on
 * the client, so anything stateful here is a hydration mismatch. A hash of the
 * id gives every node its own direction, amplitude, period and starting phase
 * while staying byte-identical across both renders and across reloads.
 */
function nodeSeed(id: string): number {
  let h = 0x811c9dc5;
  for (let i = 0; i < id.length; i += 1) {
    h ^= id.charCodeAt(i);
    h = Math.imul(h, 0x01000193);
  }
  return h >>> 0;
}

/**
 * The four custom properties `landing-graph-drift` reads. A NEGATIVE delay
 * starts each node part-way through its own cycle, so the field never syncs up
 * into a single collective pulse — the failure mode that makes ambient motion
 * read as a loading state.
 */
function driftStyle(id: string): CSSProperties {
  const seed = nodeSeed(id);
  const angle = ((seed % 3600) / 3600) * Math.PI * 2;
  const amplitude = DRIFT_AMPLITUDE * (0.55 + (((seed >>> 12) % 100) / 100) * 0.45);
  const duration = DRIFT_MIN_S + (((seed >>> 19) % 100) / 100) * DRIFT_SPAN_S;
  const delay = -(((seed >>> 25) % 100) / 100) * duration;
  return {
    '--drift-x': `${r2(Math.cos(angle) * amplitude)}px`,
    '--drift-y': `${r2(Math.sin(angle) * amplitude)}px`,
    '--drift-dur': `${r2(duration)}s`,
    '--drift-delay': `${r2(delay)}s`,
  } as CSSProperties;
}

function nodeRadius(view: GraphView, g: CourseGraph, id: string): number {
  return id === g.rootId ? view.rootR : view.nodeR;
}

/**
 * The root is an ANCHOR, not a status (#344 visual 2).
 *
 * Its fixture tier is `learning`, so it used to render in the progress amber —
 * which made the stem the whole graph hangs from, and the largest object in the
 * section, look like a warning. `--brand-forest` is the brand primary and the
 * hero's logo colour, so the course node reads as "this is the course" while
 * colour keeps carrying mastery meaning where it actually means something: the
 * concept nodes. The fixture `tier` field is untouched — this is a render
 * decision, not a data change.
 */
function nodeFill(g: CourseGraph, node: DemoNode): string {
  return node.id === g.rootId ? 'var(--brand-forest)' : TIER_COLOR[node.tier];
}

/** Human label for the detail panel's status chip. The root isn't a status. */
function nodeTierLabel(g: CourseGraph, node: DemoNode): string {
  return node.id === g.rootId ? 'Course' : TIER_LABEL[node.tier];
}

/**
 * The mastery arc: an open path from 12 o'clock, sweeping clockwise through
 * `fraction` of the ring (#344 step 3).
 *
 * A `<path>` rather than a `stroke-dasharray` circle, for two reasons. The
 * dash trick needs the circumference computed anyway, it renders the *gap* as a
 * second visible dash on any browser that rounds differently, and — the one
 * that settles it — `KnowledgeGraphDemo.test.tsx` and the E2E legibility gate
 * both reach for `querySelector('circle')` inside a node group and read its
 * `fill` and `r`. The node's first circle has to stay the tier-painted disc
 * whose diameter is the node's drawn size. Arcs are paths; nothing shifts.
 *
 * Capped just under a full turn: at exactly 1 the two endpoints coincide and
 * the arc collapses to nothing.
 */
function masteryArc(cx: number, cy: number, radius: number, fraction: number): string {
  const f = Math.min(0.999, Math.max(0, fraction));
  if (f <= 0 || radius <= 0) return '';
  const sweep = f * Math.PI * 2;
  const large = f > 0.5 ? 1 : 0;
  return [
    `M ${r2(cx)} ${r2(cy - radius)}`,
    `A ${r2(radius)} ${r2(radius)} 0 ${large} 1`,
    `${r2(cx + radius * Math.sin(sweep))} ${r2(cy - radius * Math.cos(sweep))}`,
  ].join(' ');
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
 * `progress` is derived, never read straight off state, and its resting value
 * is 1 — the COMPLETE frame. That is the whole of #344 review #6: this
 * component server-renders a complete graph, and the majority visitor (no
 * motion preference) then has `usePrefersReducedMotion` correct from its
 * SSR-safe `true` default to `false` shortly after hydration. If un-parking
 * exposed a raw `animatedProgress` initialised to 0, that correction would
 * commit at least one painted frame with the entire graph at opacity 0 — and
 * once the RAF is viewport-gated (`armed`), it would stay blank until the
 * visitor scrolled down to a section that its own `id="knowledge-graph"`
 * invites them to deep-link straight into. So `animatedProgress` starts as
 * `null` meaning "the assembly has never run", and `null` reads back as 1.
 * The graph is never blank in a committed frame; the only frames below 1 are
 * the ones the live RAF loop is actively driving, on screen, on purpose.
 *
 * Deriving rather than reconciling also makes the `parked` flip correct in
 * both directions without an effect: parked always reads back as the complete
 * frame regardless of whatever `animatedProgress` last held.
 */
function AssemblingGraph({
  graph,
  points,
  view,
  parked,
  armed,
  drifting,
  hovered,
  onNodeEnter,
  onNodeLeave,
}: {
  graph: CourseGraph;
  points: Map<string, Point>;
  view: GraphView;
  parked: boolean;
  armed: boolean;
  drifting: boolean;
  hovered: string | null;
  onNodeEnter: (id: string) => void;
  onNodeLeave: () => void;
}) {
  const [animatedProgress, setAnimatedProgress] = useState<number | null>(null);
  // Latches once the assembly has finished (or been abandoned). Keeps a
  // re-entry into the viewport from replaying the whole helix every time the
  // visitor scrolls past, and keeps a mid-flight cancel from freezing a
  // half-faded frame.
  const settledRef = useRef(false);

  // "Parked" means the assembly is skipped and the graph renders complete —
  // fully laid out, full opacity — on the very first frame. Reduced-motion
  // visitors and the E2E/unit-test lanes (IS_TEST_MODE) both get this. So does
  // everyone else until the loop is actually armed and running; see above.
  const progress = parked || animatedProgress === null ? 1 : animatedProgress;

  useEffect(() => {
    if (parked || !armed || settledRef.current) return;
    const start = now();
    let raf = 0;
    const tick = () => {
      const p = Math.min(1, (now() - start) / ASSEMBLE_MS);
      if (p >= 1) settledRef.current = true;
      setAnimatedProgress(p);
      if (p < 1) raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => {
      cancelAnimationFrame(raf);
      if (!settledRef.current) {
        // Scrolled away (or unmounted) mid-assembly: settle on the complete
        // frame rather than leaving the section parked on a half-faded one.
        settledRef.current = true;
        setAnimatedProgress(1);
      }
    };
  }, [parked, armed]);

  const centre = { x: view.w / 2, y: view.h / 2 };

  return (
    <>
      {graph.edges.map((e) => {
        const a = points.get(e.source);
        const b = points.get(e.target);
        if (!a || !b) return null;

        /*
          Edges stop at the rim of the discs they connect instead of running to
          their centres (#344 step 3). Under flat filled dots the difference was
          invisible — the disc painted over the stub. The node is a RING now,
          and the annulus between its core and its ring is transparent paper, so
          an untrimmed edge would draw a grey line straight across the middle of
          every mastery dial on the page. Trimming is capped at 45% of the run
          so a short edge shortens rather than inverting.
        */
        const dx = b.x - a.x;
        const dy = b.y - a.y;
        const len = Math.hypot(dx, dy) || 1;
        const ux = dx / len;
        const uy = dy / len;
        const cap = len * 0.45;
        const trimA = Math.min(nodeRadius(view, graph, e.source), cap);
        const trimB = Math.min(nodeRadius(view, graph, e.target), cap);
        // The hovered node's own edges lift out of the mesh, so "3 connections"
        // in the detail panel is a claim the picture can be checked against.
        const lit = hovered === e.source || hovered === e.target;

        return (
          <line
            key={`${e.source}-${e.target}`}
            x1={r2(a.x + ux * trimA)}
            y1={r2(a.y + uy * trimA)}
            x2={r2(b.x - ux * trimB)}
            y2={r2(b.y - uy * trimB)}
            stroke={lit ? 'var(--brand-forest)' : 'var(--text-dim)'}
            strokeOpacity={(lit ? 0.55 : 0.28) * progress}
            strokeWidth={(lit ? 1.5 : 1) * view.edgeW}
            strokeLinecap="round"
            className="landing-graph-edge"
          />
        );
      })}

      {graph.nodes.map((n, i) => {
        const p = points.get(n.id);
        if (!p) return null;
        // Stagger: later nodes start later, all finish by progress = 1.
        const span = 1 / (graph.nodes.length + 2);
        const local = Math.min(1, Math.max(0, (progress - i * span) / (1 - i * span)));
        const h = helixEntry(p, centre, local);
        const r = nodeRadius(view, graph, n.id);
        const fill = nodeFill(graph, n);
        const lit = hovered === n.id;

        /*
          The dial (#344 step 3). Every dimension is measured INWARD from `r`,
          the node's existing radius, so the drawn footprint is byte-identical
          to the flat disc this replaced: `fitViewBox` still frames it, the
          label gap `labelBaselineY` reserves is still the right gap, and the
          phone's 5.40-unit worst-case label clearance is untouched. A ring
          hung OUTSIDE `r` would have moved all three, and every one of them is
          load-bearing arithmetic that `layout.test.ts` pins.

            · disc   — r, tier colour at 14% — the node's extent and its hit
                       target (fill-opacity > 0 keeps `visiblePainted` hits).
            · track  — the unfilled remainder, in a NEUTRAL. A track tinted
                       with the node's own colour made an arc at 6% and an arc
                       at 90% look alike at this size, which is the one thing
                       a dial may not do.
            · arc    — mastery, swept clockwise from 12 o'clock.
            · core   — 0.52 r of solid tier colour, so the node still reads as
                       a coloured dot from across the page.
        */
        const scaled = r * h.scale;
        const ringW = Math.min(r * 0.22, 4.4) * h.scale;
        const ringR = scaled - ringW / 2;
        const coreR = scaled * 0.52;
        const arc = masteryArc(h.x, h.y, ringR, n.mastery);

        return (
          <g
            key={n.id}
            data-testid={`landing-graph-node-${n.id}`}
            className={`landing-graph-node${drifting ? ' is-drifting' : ''}`}
            style={drifting ? driftStyle(n.id) : undefined}
            opacity={h.opacity}
            onMouseEnter={() => onNodeEnter(n.id)}
            onMouseLeave={onNodeLeave}
          >
            <circle cx={h.x} cy={h.y} r={scaled} fill={fill} fillOpacity={lit ? 0.24 : 0.14} />
            <circle
              cx={h.x}
              cy={h.y}
              r={ringR}
              fill="none"
              stroke="var(--ink-200)"
              strokeWidth={ringW}
            />
            {arc === '' ? null : (
              <path
                d={arc}
                fill="none"
                stroke={fill}
                strokeWidth={ringW}
                strokeLinecap="round"
              />
            )}
            <circle cx={h.x} cy={h.y} r={coreR} fill={fill} />
            {/*
              Labels sit ON the edge mesh — under the upward fan every arm's
              label straddles the edge running out to its child, and the middle
              shoot's label sits across the stem it hangs from (#344 visual 4).
              `paint-order: stroke` lays a halo in the section's own backdrop
              colour under the glyphs and paints the fill over it, so a line
              passing behind a word breaks around the letterforms instead of
              running through them. One element, existing token, no backdrop
              filter — the brand's hard "no frosted panels" line holds.

              The halo is `--bg-mesh` and the canvas the graph now sits on is
              painted `--bg-mesh` for exactly that reason: on the panel paper
              the halo would show as a pale rectangle behind every word.
            */}
            <text
              x={h.x}
              y={labelBaselineY(view, n.id === graph.rootId, h.y, r)}
              textAnchor="middle"
              className="font-jetbrains"
              fontSize={view.font}
              fill={lit ? 'var(--text)' : 'var(--text-dim)'}
              stroke="var(--bg-mesh)"
              strokeWidth={view.labelHalo}
              strokeLinejoin="round"
              style={{ paintOrder: 'stroke' }}
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

/**
 * The inspector rail — what the app's own node detail looks like (#344 step 3).
 *
 * Replaces the single line of body text this section used to swap under the
 * graph. That line was the only thing hover produced, on a page where the four
 * bento tiles below each recreate a whole product screen, and it made the
 * differentiator the thinnest surface here.
 *
 * IT IS NEVER EMPTY. With nothing hovered it shows the COURSE — the root node,
 * whose blurb is a real sentence and whose mastery is the real aggregate — so
 * the panel reads as a populated screen at rest rather than as a placeholder
 * waiting to be earned. That also removes the "hover to see more" instruction
 * a touch visitor can never act on.
 *
 * Every row is fixed-height or floor-reserved, and at the two-column breakpoint
 * the grid stretches this rail to the canvas's height, so the swap on hover
 * cannot move a single pixel of the page.
 */
function GraphInspector({ graph, node }: { graph: CourseGraph; node: DemoNode }) {
  const links = neighbours(graph, node.id);
  const isRoot = node.id === graph.rootId;
  const paint = nodeFill(graph, node);
  const pct = Math.round(node.mastery * 100);

  return (
    <SurfaceFrame
      testId="landing-graph-detail"
      title={isRoot ? 'Course' : 'Concept'}
      meta={`${links.length} connection${links.length === 1 ? '' : 's'}`}
    >
      <span className="landing-graph-detailhead">
        <span className="landing-graph-detailname" data-testid="landing-graph-detail-name">
          {node.label}
        </span>
        {/*
          The tier is spelled out, and the colour rides the chip's dot and
          border rather than its lettering — the same recipe, down to the
          `color-mix` wash, that `GradebookSurface`'s per-row grade pill uses.
          `--state-progress` (#c89b5e) as text on this paper is 2.2:1; as a
          border and a mark next to a `--text` word it carries the state
          without ever having to be legible as type.
        */}
        <span
          className="landing-graph-tierchip"
          data-testid="landing-graph-detail-tier"
          style={{ '--tier': paint } as CSSProperties}
        >
          {nodeTierLabel(graph, node)}
        </span>
      </span>

      {/*
        Reserved min-height (#344 task 5, kept): the blurb swaps on every
        hover and unhover. Without a floor, a one-line blurb replacing a
        two-line one shifts everything under it on every pass of the mouse —
        load-bearing, not cosmetic. The floor is two lines, which is the
        tallest any fixture blurb reaches at the narrowest column this panel
        is ever rendered in.
      */}
      <p className="landing-graph-blurb" data-testid="landing-graph-blurb">
        {node.blurb}
      </p>

      <SurfaceRule />

      <span className="landing-surface-headrow">
        <span className="landing-surface-label">Mastery</span>
        <span className="landing-surface-mono" data-testid="landing-graph-detail-mastery">
          {pct}%
        </span>
      </span>
      {/* The Study surface's own progress track, reused verbatim so the two
          meters on this page are the same object. Only the fill's colour and
          width are per-node. */}
      <span aria-hidden className="landing-surface-track">
        <span className="landing-surface-fill" style={{ width: `${pct}%`, background: paint }} />
      </span>

      <SurfaceRule />

      {/*
        The neighbours as a LIST with their own scores, not a chip row: it is
        what the app's related-concepts rail shows, it is the second half of
        the "3 connections" claim in the chrome bar, and — with the edges those
        links name lit up in the canvas alongside — it is the thing that makes
        the picture and the panel readable as one screen.

        Three rows are reserved. No fixture node has more than three
        neighbours, so the floor is also the ceiling and the panel's height is
        constant across every node of every course.
      */}
      <span className="landing-surface-label">Connected to</span>
      <span className="landing-graph-links">
        {links.map((l) => (
          <span key={l.id} className="landing-graph-link">
            <span
              aria-hidden
              className="landing-surface-dot"
              style={{ background: nodeFill(graph, l) }}
            />
            <span className="landing-graph-linkname">{l.label}</span>
            <span className="landing-surface-mono">{Math.round(l.mastery * 100)}%</span>
          </span>
        ))}
      </span>
    </SurfaceFrame>
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
  // guarantee, but the detail panel is rendered here in the parent, as a
  // sibling of the `<svg>`, so the parent needs read access to "which node is
  // hovered" regardless. One state owner for both pieces of interaction state
  // keeps `AssemblingGraph` a plain layout/animation renderer that only takes
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

  // #344 review #3: one viewBox rendered at every width put 4.6 CSS px labels
  // on a 390px phone. Each view now carries its own DERIVED frame (`view.fit`,
  // #344 visual 3) alongside its own type scale. `useIsMobile` is the same
  // `useSyncExternalStore` shape as `usePrefersReducedMotion` — SSR-safe, no
  // render-body matchMedia read — so the server (and the hydrating render)
  // picks the desktop view and the phone corrects on the first commit after
  // hydration. A viewBox is not something a CSS `@media` rule can swap, so that
  // one-frame correction is the floor here; both views render the complete
  // graph, so it is a resize, never a blank.
  const isMobile = useIsMobile();
  const view = isMobile ? MOBILE_VIEW : DESKTOP_VIEW;
  const points = useMemo(
    () => radialLayout(graph, view.w, view.h, view.maxRadius),
    [graph, view],
  );

  // The panel's subject: the hovered node, or the course itself at rest. A
  // stale id can't survive here anyway (the chip handler clears `hovered`),
  // but falling back to the root also covers a fixture edit that drops a node.
  const detailNode =
    graph.nodes.find((n) => n.id === hovered) ??
    graph.nodes.find((n) => n.id === graph.rootId) ??
    graph.nodes[0];

  const concepts = conceptNodes(graph);
  const counts = tierCounts(graph);
  const coursePct = Math.round(
    (graph.nodes.find((n) => n.id === graph.rootId)?.mastery ?? 0) * 100,
  );

  // `usePrefersReducedMotion` (not a direct `window.matchMedia` read in the
  // render body — #344 fix round 1) is hydration-safe: it renders the same
  // value on the server and the first client paint, then corrects to the
  // real value after hydration commits. See its doc comment for why it
  // defaults to "reduced motion" rather than "no preference".
  const prefersReduced = usePrefersReducedMotion();
  const parked = IS_TEST_MODE || prefersReduced;

  // Ambient drift rides the SAME park switch as the assembly, so a
  // reduced-motion visitor and the E2E lane both get a graph whose nodes sit
  // exactly on their laid-out points — a complete, still, readable frame. It
  // is additionally off below the mobile breakpoint: the phone view's frame
  // pad is 2 units and its worst label-to-neighbour clearance 5.40, both of
  // which a 3-unit drift would spend (see DRIFT_AMPLITUDE).
  const drifting = !parked && !isMobile;

  // #344 review #1: without this gate the assembly effect fired on mount and
  // burned its full 1100ms during the hydration window — underneath the
  // landing page's full-screen intro overlay, concurrently with the hero
  // canvas RAF and the hero text scramble, ~66 re-renders of this SVG subtree
  // that nobody could see. By the time a visitor scrolled here, progress was
  // already 1 and the "interactive knowledge graph" was a static picture, for
  // every visitor, every time.
  const sectionRef = useRef<HTMLElement | null>(null);
  const [armed, setArmed] = useState(false);

  // No `IntersectionObserver` (jsdom, pre-2019 browsers) means no gate, and the
  // graceful degradation is to leave the section on its complete frame rather
  // than to un-gate the animation: a static, fully laid-out graph is exactly
  // what reduced-motion visitors already get, and it can never be blank. That
  // also keeps this effect free of a synchronous `setArmed` fallback, which
  // react-hooks/set-state-in-effect rightly rejects as a cascading render.
  useEffect(() => {
    const el = sectionRef.current;
    if (!el || typeof IntersectionObserver === 'undefined') return;
    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) setArmed(entry.isIntersecting);
      },
      { rootMargin: ARM_ROOT_MARGIN },
    );
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  return (
    <section
      ref={sectionRef}
      id="knowledge-graph"
      data-testid="landing-graph"
      aria-label={`Interactive knowledge graph for ${graph.name}`}
      className="landing-section landing-graph relative z-10 py-24 md:py-32 overflow-hidden"
    >
      {/* Atmospheric continuity. The hero above and the CTA below both carry
          mesh blobs; the sections this one replaced (#features, HowItWorks)
          carried --3 and --2 plus a green tint. Without them the middle of the
          page is a flat hole between two atmospheric sections, and the cut in
          and out of it reads as a seam. Lower opacity than the hero's so the
          graph itself stays the focus. */}
      <div aria-hidden className="absolute inset-0 pointer-events-none z-0">
        <div
          className="sapling-mesh-blob sapling-mesh-blob--3"
          style={{ top: '2%', left: '-14%', bottom: 'auto', opacity: 0.26, width: '34vw', height: '34vw' }}
        />
        <div
          className="sapling-mesh-blob sapling-mesh-blob--2"
          style={{ bottom: '-8%', right: '-10%', top: 'auto', opacity: 0.18, width: '30vw', height: '30vw' }}
        />
      </div>

      <div className="relative z-[1] max-w-7xl mx-auto px-6 lg:px-12">
        <div
          data-testid="landing-graph-copy"
          data-engaged={engaged ? 'true' : 'false'}
          className="landing-graph-copy"
        >
          <span
            data-testid="landing-graph-eyebrow"
            className="font-jetbrains text-[0.7rem] tracking-[0.32em] text-[var(--brand-forest)] uppercase font-medium"
          >
            Your knowledge, mapped
          </span>
          <h2
            data-testid="landing-graph-headline"
            className="landing-graph-headline font-playfair text-4xl md:text-6xl font-semibold text-[var(--text)] mt-4 leading-[1.05] tracking-tight"
            style={{ opacity: engaged ? ENGAGED_HEADLINE_OPACITY : 1 }}
          >
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
                onClick={() => {
                  setCourseId(g.id);
                  setHovered(null);
                }}
                className={`landing-graph-chip${active ? ' is-active' : ''}`}
              >
                {g.code}
              </button>
            );
          })}
        </div>

        {/*
          #344 step 3 — the graph gets the same product chrome as every other
          surface on this page.

          It used to float naked on the page background: six dots and six words
          left-aligned in a 1184px container, with the right 40% of the field
          empty, one viewport above four bento tiles that each recreate a whole
          screen. The differentiator was the flimsiest thing here.

          One surface, full container width, split the way the app's own Tree
          screen is split: canvas left, inspector right, legend along the foot.
          The canvas keeps the `md:max-w-[720px]` cap it was fitted against
          (#344 visual 3/5 — a wider render makes the section TALLER, and the
          section's height is what those waves bought down) and centres inside
          the space the rail leaves, so nothing about the drawing's scale moved.
        */}
        <div className="landing-surface mt-8" data-testid="landing-graph-surface">
          <div className="landing-surface-chrome landing-graph-chrome">
            <span className="landing-surface-title">Knowledge Graph</span>
            <span className="landing-surface-meta" data-testid="landing-graph-meta">
              {graph.code} · {graph.conceptCount} concepts · {coursePct}% mastery
            </span>
          </div>

          <div className="landing-graph-split">
            {/*
              The canvas is painted `--bg-mesh`, not the panel's paper, and
              that is a requirement rather than a preference: every label is
              stroked with a `--bg-mesh` halo so the edge mesh breaks around
              its letterforms. On any other backdrop those haloes show up as
              pale rectangles behind the words.

              It is also full-bleed horizontally — no side padding at ALL —
              because the phone's legibility gate is measured in CSS px off
              the rendered `<svg>` width. At 390px the section's content box
              is ~332px and the frame renders at 0.769 of a unit per px;
              spending 30px on padding takes the drawing under the E2E bar.
              Vertical padding is free (the height follows the width) and is
              where the breathing room goes.
            */}
            <div className="landing-graph-canvas">
              <svg
                data-testid="landing-graph-svg"
                viewBox={viewBoxAttr(view.fit)}
                className="w-full md:max-w-[720px] xl:max-w-[820px] h-auto"
                role="img"
                aria-label={`${graph.name} concept graph`}
              >
                <AssemblingGraph
                  key={graph.id}
                  graph={graph}
                  points={points}
                  view={view}
                  parked={parked}
                  armed={armed}
                  drifting={drifting}
                  hovered={hovered}
                  onNodeEnter={onNodeEnter}
                  onNodeLeave={onNodeLeave}
                />
              </svg>
            </div>

            <div className="landing-graph-rail">
              <GraphInspector graph={graph} node={detailNode} />

              {/*
                The legend, and the reason it exists: four `--state-*` hues
                were already carrying the whole meaning of this picture, and
                nothing on the page said what any of them meant. A visitor who
                has never signed in read six coloured dots as decoration.

                It carries COUNTS, so it is a readout rather than a colour key,
                and the note under it closes the second gap the dial opened.
                Pinned to the FOOT of the rail (`margin-top: auto`), which is
                both where a legend belongs and what squares the rail's height
                against the canvas beside it.
              */}
              <div className="landing-graph-legend" data-testid="landing-graph-legend">
                <span className="landing-graph-legenditems">
                  {TIER_ORDER.map((t) => (
                    <span
                      key={t}
                      className="landing-graph-legenditem"
                      data-testid={`landing-graph-legend-${t}`}
                    >
                      <StateDot tier={t} />
                      <span className="landing-graph-legendname">{TIER_LABEL[t]}</span>
                      <span className="landing-surface-mono">{counts[t]}</span>
                    </span>
                  ))}
                </span>
                <span className="landing-surface-mono landing-graph-legendnote">
                  Ring = progress to mastery · {concepts.length} of {graph.conceptCount} shown
                </span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}

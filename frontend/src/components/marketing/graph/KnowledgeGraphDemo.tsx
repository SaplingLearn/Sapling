'use client';

import { useEffect, useMemo, useRef, useState } from 'react';

import { IS_TEST_MODE, now } from '@/lib/testMode';
import { useIsMobile } from '@/lib/useIsMobile';
import { usePrefersReducedMotion } from '@/lib/usePrefersReducedMotion';

import { COURSE_GRAPHS, TIER_COLOR, type CourseGraph, type DemoNode } from './courseGraphs';
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
  onNodeEnter,
  onNodeLeave,
}: {
  graph: CourseGraph;
  points: Map<string, Point>;
  view: GraphView;
  parked: boolean;
  armed: boolean;
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
        return (
          <line
            key={`${e.source}-${e.target}`}
            x1={a.x}
            y1={a.y}
            x2={b.x}
            y2={b.y}
            stroke="var(--text-dim)"
            strokeOpacity={0.28 * progress}
            strokeWidth={view.edgeW}
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
        return (
          <g
            key={n.id}
            data-testid={`landing-graph-node-${n.id}`}
            opacity={h.opacity}
            onMouseEnter={() => onNodeEnter(n.id)}
            onMouseLeave={onNodeLeave}
          >
            <circle cx={h.x} cy={h.y} r={r * h.scale} fill={nodeFill(graph, n)} />
            {/*
              Labels sit ON the edge mesh — under the upward fan every arm's
              label straddles the edge running out to its child, and the middle
              shoot's label sits across the stem it hangs from (#344 visual 4).
              `paint-order: stroke` lays a halo in the section's own backdrop
              colour under the glyphs and paints the fill over it, so a line
              passing behind a word breaks around the letterforms instead of
              running through them. One element, existing token, no backdrop
              filter — the brand's hard "no frosted panels" line holds.
            */}
            <text
              x={h.x}
              y={labelBaselineY(view, n.id === graph.rootId, h.y, r)}
              textAnchor="middle"
              className="font-jetbrains"
              fontSize={view.font}
              fill="var(--text-dim)"
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

  // #344 review #3: one viewBox rendered at every width put 4.6 CSS px labels
  // on a 390px phone. Each view now carries its own DERIVED frame (`view.fit`,
  // #344 visual 3) alongside its own type scale. `useIsMobile` is the same
  // `useSyncExternalStore` shape as `usePrefersReducedMotion` — SSR-safe, no
  // render-body matchMedia read — so the server (and the hydrating render)
  // picks the desktop view and the phone corrects on the first commit after
  // hydration. A viewBox is not something a CSS `@media` rule can swap, so that
  // one-frame correction is the floor here; both views render the complete
  // graph, so it is a resize, never a blank.
  const view = useIsMobile() ? MOBILE_VIEW : DESKTOP_VIEW;
  const points = useMemo(
    () => radialLayout(graph, view.w, view.h, view.maxRadius),
    [graph, view],
  );
  const hoveredBlurb = hovered ? graph.nodes.find((n) => n.id === hovered)?.blurb : undefined;

  // `usePrefersReducedMotion` (not a direct `window.matchMedia` read in the
  // render body — #344 fix round 1) is hydration-safe: it renders the same
  // value on the server and the first client paint, then corrects to the
  // real value after hydration commits. See its doc comment for why it
  // defaults to "reduced motion" rather than "no preference".
  const prefersReduced = usePrefersReducedMotion();
  const parked = IS_TEST_MODE || prefersReduced;

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
                onClick={() => setCourseId(g.id)}
                className={`landing-graph-chip${active ? ' is-active' : ''}`}
              >
                {g.code}
              </button>
            );
          })}
        </div>

        {/*
          #344 visual 3 + 5, which have to be solved together.

          The frame is now measured off the content (`view.fit`) instead of the
          hardcoded `0 0 900 560`, which drops 36% of dead margin off the box.
          But a tight box stretched to the full 1184px container would render
          the graph at 2× and make the section TALLER, not shorter — the fit only
          pays off with a width cap. Capping also settles the composition: the
          section's eyebrow, headline and chips are left-aligned on the container
          grid while the graph was centred inside a full-bleed box one viewport
          below a hero that is centred and symmetric, so it read as an accident.
          Left-aligning the graph to the same grid line commits to the editorial
          direction the rest of the section already uses, and it is the reversible
          half of the choice: no copy moves, no structure changes.

          At the 720px cap the desktop graph draws at ~1.24 units per CSS px in
          a 720×413 box, where the fixed viewBox reserved 1184×737 and drew the
          graph across the middle 277px of it. The box is 224px SHORTER than the
          720×638 the same upward fan fitted while `helixEntry` turned 1.5 times
          on the way in: the frame is fitted to that entry SWEEP (it has to be,
          or the assembly gets clipped mid-flight), a 540° sweep is very nearly a
          disc, and a near-square frame around a canopy twice as wide as it is
          tall is dead paper on the top and bottom edges. At a quarter turn the
          sweep hugs the drawing, so the drawing now fills 87% of the frame's
          width and 85% of its height — and it renders BIGGER than it did in the
          taller box (694×352 CSS px against 669×339).
        */}
        <svg
          data-testid="landing-graph-svg"
          viewBox={viewBoxAttr(view.fit)}
          className="mt-8 w-full max-w-[420px] md:max-w-[720px] h-auto"
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

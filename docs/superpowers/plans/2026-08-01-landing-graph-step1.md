# Landing Interactive Graph (step 1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the 340vh scroll-jacked `HowItWorks` section with an interactive knowledge-graph demo the visitor manipulates, and delete the old six-row feature catalog.

**Architecture:** A pure-data fixture module (three hand-authored course graphs), a pure-math layout module (deterministic radial layout + a helical entry path), and one client component that composes them. No backend, no network, no LLM. The component lazy-loads below the fold with SSR kept on so crawlers still receive its copy.

**Tech Stack:** Next.js 16 App Router, React, TypeScript, inline SVG (no new dependency), vitest + @testing-library/react, Playwright.

**Scope:** This is step 1 of `docs/superpowers/specs/2026-08-01-landing-below-hero-design.md`. Sections 2–5 of that spec (bands, bento, seven surface recreations) are step 2 and get their own plan. At the end of this plan the page is coherent: hero → graph → CTA → footer.

## Global Constraints

- Hero, nav, and intro overlay in `frontend/src/app/(public)/page.tsx` are **untouched**. So are `SignInModal` and the beta/newsletter modal.
- **No new npm dependency.** Rendering is inline SVG; framer-motion is not used by the new component.
- All randomness and clock reads go through `@/lib/testMode` (`random()`, `now()`), never `Math.random()` / `Date.now()` — the E2E lane sets `NEXT_PUBLIC_TEST_MODE=1` and requires a deterministic DOM.
- Under `prefers-reduced-motion: reduce` **or** `IS_TEST_MODE`, the graph parks on a **complete, laid-out, readable** frame — never blank, never mid-assembly.
- New CSS lives inside the `.landing-page` scope in `frontend/src/app/globals.css`. Do not redefine design tokens outside that scope (`docs/frontend-rhythm-audit.md` — this is the documented cause of the pre-auth/app-shell drift bugs).
- Any `<button>`/`<input>`/`<textarea>` in a registered E2E surface file must carry `data-testid` (`frontend/eslint.config.mjs` `no-restricted-syntax` block; see `docs/frontend-testids.md` §"Adding a surface").
- `frontend/e2e/public-seo.spec.ts` must stay green — it is the guard that the landing page still ships SSR'd copy, social cards, and a canonical URL.
- Run frontend checks from `frontend/`: `npm run lint`, `npx tsc --noEmit`, `npx vitest run`.

---

### Task 1: Course graph fixtures

Three hand-authored course graphs. Pure data plus the types every later task consumes.

**Files:**
- Create: `frontend/src/components/marketing/graph/courseGraphs.ts`
- Test: `frontend/src/components/marketing/graph/courseGraphs.test.ts`

**Interfaces:**
- Consumes: nothing.
- Produces: `MasteryTier`, `DemoNode`, `DemoEdge`, `CourseGraph`, `COURSE_GRAPHS: CourseGraph[]`, `TIER_COLOR: Record<MasteryTier, string>`.

- [ ] **Step 1: Write the failing test**

```ts
// frontend/src/components/marketing/graph/courseGraphs.test.ts
/**
 * Fixture integrity. These graphs are hand-authored, so the failure mode is a
 * typo'd id producing an edge to nowhere — which renders as a line into empty
 * space rather than an error. Pin the invariants instead.
 */
import { describe, it, expect } from 'vitest';

import { COURSE_GRAPHS, TIER_COLOR, type CourseGraph } from './courseGraphs';

const ids = (g: CourseGraph) => new Set(g.nodes.map((n) => n.id));

describe('COURSE_GRAPHS', () => {
  it('ships exactly three courses with distinct ids and codes', () => {
    expect(COURSE_GRAPHS).toHaveLength(3);
    expect(new Set(COURSE_GRAPHS.map((g) => g.id)).size).toBe(3);
    expect(new Set(COURSE_GRAPHS.map((g) => g.code)).size).toBe(3);
  });

  it.each(COURSE_GRAPHS.map((g) => [g.code, g] as const))(
    '%s has unique node ids',
    (_code, g) => {
      expect(ids(g).size).toBe(g.nodes.length);
    },
  );

  it.each(COURSE_GRAPHS.map((g) => [g.code, g] as const))(
    '%s has a root that exists',
    (_code, g) => {
      expect(ids(g).has(g.rootId)).toBe(true);
    },
  );

  it.each(COURSE_GRAPHS.map((g) => [g.code, g] as const))(
    '%s edges reference real nodes',
    (_code, g) => {
      const known = ids(g);
      for (const e of g.edges) {
        expect(known.has(e.source)).toBe(true);
        expect(known.has(e.target)).toBe(true);
      }
    },
  );

  it.each(COURSE_GRAPHS.map((g) => [g.code, g] as const))(
    '%s children reference real nodes',
    (_code, g) => {
      const known = ids(g);
      for (const n of g.nodes) {
        for (const c of n.children) expect(known.has(c)).toBe(true);
      }
    },
  );

  it.each(COURSE_GRAPHS.map((g) => [g.code, g] as const))(
    '%s reaches every node from the root',
    (_code, g) => {
      const adj = new Map<string, string[]>();
      for (const e of g.edges) {
        adj.set(e.source, [...(adj.get(e.source) ?? []), e.target]);
        adj.set(e.target, [...(adj.get(e.target) ?? []), e.source]);
      }
      const seen = new Set([g.rootId]);
      const queue = [g.rootId];
      while (queue.length) {
        for (const nxt of adj.get(queue.shift()!) ?? []) {
          if (!seen.has(nxt)) {
            seen.add(nxt);
            queue.push(nxt);
          }
        }
      }
      expect(seen.size).toBe(g.nodes.length);
    },
  );

  it.each(COURSE_GRAPHS.map((g) => [g.code, g] as const))(
    '%s gives every node a blurb and a known tier',
    (_code, g) => {
      for (const n of g.nodes) {
        expect(n.blurb.length).toBeGreaterThan(0);
        expect(TIER_COLOR[n.tier]).toMatch(/^#/);
      }
    },
  );
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/components/marketing/graph/courseGraphs.test.ts`
Expected: FAIL — cannot resolve `./courseGraphs`.

- [ ] **Step 3: Write the fixtures**

```ts
// frontend/src/components/marketing/graph/courseGraphs.ts
/**
 * Hand-authored demo graphs for the landing page (#344).
 *
 * Deliberately static. An earlier option generated these live from a public
 * endpoint, which was rejected: it puts an unauthenticated, billable LLM call
 * on the most-crawled page on the site. See the spec's "Rejected alternatives".
 *
 * Shapes mirror the real `graph_nodes` / `graph_edges` semantics — mastery
 * tiers included — so the colour language matches the app and the hero legend.
 */

export type MasteryTier = 'mastered' | 'learning' | 'struggling' | 'unexplored';

/** Matches the hero's floating legend card and the app's node colours. */
export const TIER_COLOR: Record<MasteryTier, string> = {
  mastered: '#1B6C42',
  learning: '#D97706',
  struggling: '#EF4444',
  unexplored: '#9CA3AF',
};

export interface DemoNode {
  id: string;
  label: string;
  tier: MasteryTier;
  /** Shown on hover. One sentence, no trailing period. */
  blurb: string;
  /** Revealed when this node is expanded. Empty means leaf. */
  children: string[];
}

export interface DemoEdge {
  source: string;
  target: string;
}

export interface CourseGraph {
  id: string;
  /** Chip label, e.g. "CS 210". */
  code: string;
  name: string;
  rootId: string;
  nodes: DemoNode[];
  edges: DemoEdge[];
}

export const COURSE_GRAPHS: CourseGraph[] = [
  {
    id: 'cs210',
    code: 'CS 210',
    name: 'Data Structures',
    rootId: 'cs-root',
    nodes: [
      { id: 'cs-root', label: 'CS 210', tier: 'learning', blurb: 'Data Structures — 24 concepts mapped from your syllabus', children: ['cs-arrays', 'cs-recursion', 'cs-complexity'] },
      { id: 'cs-arrays', label: 'Arrays', tier: 'mastered', blurb: 'Contiguous storage and index arithmetic', children: ['cs-sorting'] },
      { id: 'cs-recursion', label: 'Recursion', tier: 'struggling', blurb: 'Base cases, call stack depth, and when to prefer iteration', children: ['cs-trees'] },
      { id: 'cs-complexity', label: 'Big-O', tier: 'learning', blurb: 'Asymptotic bounds for time and space', children: [] },
      { id: 'cs-sorting', label: 'Sorting', tier: 'learning', blurb: 'Comparison sorts and their lower bound', children: [] },
      { id: 'cs-trees', label: 'Trees', tier: 'unexplored', blurb: 'Traversals, balance, and why recursion fits them', children: [] },
    ],
    edges: [
      { source: 'cs-root', target: 'cs-arrays' },
      { source: 'cs-root', target: 'cs-recursion' },
      { source: 'cs-root', target: 'cs-complexity' },
      { source: 'cs-arrays', target: 'cs-sorting' },
      { source: 'cs-recursion', target: 'cs-trees' },
      { source: 'cs-sorting', target: 'cs-complexity' },
    ],
  },
  {
    id: 'ma242',
    code: 'MA 242',
    name: 'Linear Algebra',
    rootId: 'ma-root',
    nodes: [
      { id: 'ma-root', label: 'MA 242', tier: 'learning', blurb: 'Linear Algebra — 19 concepts mapped from your syllabus', children: ['ma-vectors', 'ma-matrices', 'ma-eigen'] },
      { id: 'ma-vectors', label: 'Vector Spaces', tier: 'mastered', blurb: 'Span, basis, and dimension', children: ['ma-independence'] },
      { id: 'ma-matrices', label: 'Matrices', tier: 'learning', blurb: 'Linear maps written as arrays of numbers', children: ['ma-determinant'] },
      { id: 'ma-eigen', label: 'Eigenvalues', tier: 'struggling', blurb: 'Directions a transformation only scales', children: [] },
      { id: 'ma-independence', label: 'Independence', tier: 'learning', blurb: 'When no vector is redundant', children: [] },
      { id: 'ma-determinant', label: 'Determinant', tier: 'unexplored', blurb: 'Signed volume scaling of a transformation', children: [] },
    ],
    edges: [
      { source: 'ma-root', target: 'ma-vectors' },
      { source: 'ma-root', target: 'ma-matrices' },
      { source: 'ma-root', target: 'ma-eigen' },
      { source: 'ma-vectors', target: 'ma-independence' },
      { source: 'ma-matrices', target: 'ma-determinant' },
      { source: 'ma-matrices', target: 'ma-eigen' },
    ],
  },
  {
    id: 'sm275',
    code: 'SM 275',
    name: 'Statistics',
    rootId: 'sm-root',
    nodes: [
      { id: 'sm-root', label: 'SM 275', tier: 'learning', blurb: 'Statistics — 21 concepts mapped from your syllabus', children: ['sm-prob', 'sm-dist', 'sm-testing'] },
      { id: 'sm-prob', label: 'Probability', tier: 'mastered', blurb: 'Sample spaces, events, and conditioning', children: ['sm-bayes'] },
      { id: 'sm-dist', label: 'Distributions', tier: 'learning', blurb: 'Shapes that recur across real data', children: ['sm-clt'] },
      { id: 'sm-testing', label: 'Hypothesis Tests', tier: 'struggling', blurb: 'What a p-value does and does not claim', children: [] },
      { id: 'sm-bayes', label: 'Bayes', tier: 'learning', blurb: 'Updating belief as evidence arrives', children: [] },
      { id: 'sm-clt', label: 'Central Limit', tier: 'unexplored', blurb: 'Why sample means go normal', children: [] },
    ],
    edges: [
      { source: 'sm-root', target: 'sm-prob' },
      { source: 'sm-root', target: 'sm-dist' },
      { source: 'sm-root', target: 'sm-testing' },
      { source: 'sm-prob', target: 'sm-bayes' },
      { source: 'sm-dist', target: 'sm-clt' },
      { source: 'sm-dist', target: 'sm-testing' },
    ],
  },
];
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/components/marketing/graph/courseGraphs.test.ts`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/marketing/graph/courseGraphs.ts frontend/src/components/marketing/graph/courseGraphs.test.ts
git commit -m "feat(landing): course graph fixtures for the interactive demo (#344)"
```

---

### Task 2: Deterministic layout and the helical entry path

Pure math, no React. This is where "3D helix animation" actually lives.

**Files:**
- Create: `frontend/src/components/marketing/graph/layout.ts`
- Test: `frontend/src/components/marketing/graph/layout.test.ts`

**Interfaces:**
- Consumes: `CourseGraph` from Task 1.
- Produces: `Point`, `radialLayout(graph, width, height): Map<string, Point>`, `easeOutCubic(t): number`, `helixEntry(target, centre, t, turns?): { x, y, scale, opacity }`.

- [ ] **Step 1: Write the failing test**

```ts
// frontend/src/components/marketing/graph/layout.test.ts
/**
 * The layout is deterministic on purpose: the E2E lane parks the animation and
 * asserts against a laid-out frame, so identical input must give identical
 * coordinates on every run and in every environment.
 */
import { describe, it, expect } from 'vitest';

import { COURSE_GRAPHS } from './courseGraphs';
import { easeOutCubic, helixEntry, radialLayout } from './layout';

const G = COURSE_GRAPHS[0];

describe('radialLayout', () => {
  it('positions every node', () => {
    const p = radialLayout(G, 800, 500);
    expect(p.size).toBe(G.nodes.length);
    for (const n of G.nodes) expect(p.get(n.id)).toBeDefined();
  });

  it('puts the root at the centre', () => {
    const p = radialLayout(G, 800, 500);
    expect(p.get(G.rootId)).toEqual({ x: 400, y: 250 });
  });

  it('is deterministic', () => {
    expect(radialLayout(G, 800, 500)).toEqual(radialLayout(G, 800, 500));
  });

  it('separates nodes at the same depth', () => {
    const p = radialLayout(G, 800, 500);
    const depth1 = G.nodes.find((n) => n.id === G.rootId)!.children;
    const pts = depth1.map((id) => p.get(id)!);
    for (let i = 0; i < pts.length; i++) {
      for (let j = i + 1; j < pts.length; j++) {
        const d = Math.hypot(pts[i].x - pts[j].x, pts[i].y - pts[j].y);
        expect(d).toBeGreaterThan(40);
      }
    }
  });

  it('scales with the viewport', () => {
    const small = radialLayout(G, 400, 300);
    const large = radialLayout(G, 1200, 800);
    expect(small).not.toEqual(large);
  });
});

describe('easeOutCubic', () => {
  it('pins its endpoints and clamps', () => {
    expect(easeOutCubic(0)).toBe(0);
    expect(easeOutCubic(1)).toBe(1);
    expect(easeOutCubic(-1)).toBe(0);
    expect(easeOutCubic(4)).toBe(1);
  });
});

describe('helixEntry', () => {
  const target = { x: 300, y: 120 };
  const centre = { x: 200, y: 200 };

  it('lands exactly on the target at t=1', () => {
    const r = helixEntry(target, centre, 1);
    expect(r.x).toBeCloseTo(target.x, 6);
    expect(r.y).toBeCloseTo(target.y, 6);
    expect(r.scale).toBeCloseTo(1, 6);
    expect(r.opacity).toBeCloseTo(1, 6);
  });

  it('starts invisible and small', () => {
    const r = helixEntry(target, centre, 0);
    expect(r.opacity).toBe(0);
    expect(r.scale).toBeLessThan(0.5);
  });

  it('rotates around the centre on the way in — the helix', () => {
    const mid = helixEntry(target, centre, 0.5);
    const straight = {
      x: centre.x + (target.x - centre.x) * easeOutCubic(0.5),
      y: centre.y + (target.y - centre.y) * easeOutCubic(0.5),
    };
    const off = Math.hypot(mid.x - straight.x, mid.y - straight.y);
    expect(off).toBeGreaterThan(10);
  });

  it('grows monotonically', () => {
    let prev = -1;
    for (let t = 0; t <= 1.0001; t += 0.1) {
      const s = helixEntry(target, centre, t).scale;
      expect(s).toBeGreaterThan(prev);
      prev = s;
    }
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/components/marketing/graph/layout.test.ts`
Expected: FAIL — cannot resolve `./layout`.

- [ ] **Step 3: Write the implementation**

```ts
// frontend/src/components/marketing/graph/layout.ts
/**
 * Layout + entry-path math for the landing graph demo (#344).
 *
 * Deterministic by construction — no randomness, no time input. The E2E lane
 * parks the animation and asserts against the laid-out frame, so the same graph
 * and viewport must always produce the same coordinates.
 */
import type { CourseGraph } from './courseGraphs';

export interface Point {
  x: number;
  y: number;
}

function clamp01(t: number): number {
  return t < 0 ? 0 : t > 1 ? 1 : t;
}

export function easeOutCubic(t: number): number {
  const c = clamp01(t);
  return 1 - Math.pow(1 - c, 3);
}

/**
 * Root at the centre, each BFS depth on its own ring, siblings spread evenly
 * around it. Alternate rings are rotated by half a slot so spokes don't line
 * up into visual spokes.
 */
export function radialLayout(
  graph: CourseGraph,
  width: number,
  height: number,
): Map<string, Point> {
  const adj = new Map<string, string[]>();
  for (const e of graph.edges) {
    adj.set(e.source, [...(adj.get(e.source) ?? []), e.target]);
    adj.set(e.target, [...(adj.get(e.target) ?? []), e.source]);
  }

  const depth = new Map<string, number>([[graph.rootId, 0]]);
  const queue = [graph.rootId];
  while (queue.length) {
    const cur = queue.shift()!;
    for (const nxt of adj.get(cur) ?? []) {
      if (!depth.has(nxt)) {
        depth.set(nxt, depth.get(cur)! + 1);
        queue.push(nxt);
      }
    }
  }

  const byDepth = new Map<number, string[]>();
  // Iterate graph.nodes (declaration order), not the Map, so ring ordering is
  // stable regardless of BFS visit order.
  for (const n of graph.nodes) {
    const d = depth.get(n.id) ?? 0;
    byDepth.set(d, [...(byDepth.get(d) ?? []), n.id]);
  }

  const cx = width / 2;
  const cy = height / 2;
  const maxDepth = Math.max(...byDepth.keys(), 1);
  const ring = (Math.min(width, height) / 2 - 48) / maxDepth;

  const out = new Map<string, Point>();
  for (const [d, ids] of byDepth) {
    if (d === 0) {
      for (const id of ids) out.set(id, { x: cx, y: cy });
      continue;
    }
    const step = (Math.PI * 2) / ids.length;
    const offset = d % 2 === 0 ? step / 2 : 0;
    ids.forEach((id, i) => {
      const a = i * step + offset - Math.PI / 2;
      out.set(id, {
        x: cx + Math.cos(a) * ring * d,
        y: cy + Math.sin(a) * ring * d,
      });
    });
  }
  return out;
}

/**
 * Position along the helical entry path. `t` runs 0 → 1.
 *
 * The node spirals inward: its offset from the centre is rotated by a
 * decreasing angle and stretched outward by a decreasing factor, while scale
 * and opacity rise. At t=1 every term collapses and the node sits exactly on
 * `target`, so the animation has no seam where it hands off to the static
 * layout.
 */
export function helixEntry(
  target: Point,
  centre: Point,
  t: number,
  turns = 1.5,
): { x: number; y: number; scale: number; opacity: number } {
  const e = easeOutCubic(t);
  const dx = target.x - centre.x;
  const dy = target.y - centre.y;

  const angle = (1 - e) * turns * Math.PI * 2;
  const stretch = 1 + (1 - e) * 0.9;
  const cos = Math.cos(angle);
  const sin = Math.sin(angle);

  return {
    x: centre.x + (dx * cos - dy * sin) * stretch,
    y: centre.y + (dx * sin + dy * cos) * stretch,
    scale: 0.35 + 0.65 * e,
    opacity: e,
  };
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd frontend && npx vitest run src/components/marketing/graph/layout.test.ts`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/marketing/graph/layout.ts frontend/src/components/marketing/graph/layout.test.ts
git commit -m "feat(landing): deterministic radial layout + helical entry path (#344)"
```

---

### Task 3: The component — chips, static render, testids

Renders the graph laid out and complete. Assembly animation comes in Task 4; this task's deliverable is the parked frame, which is also exactly what reduced-motion and test mode ship.

**Files:**
- Create: `frontend/src/components/marketing/graph/KnowledgeGraphDemo.tsx`
- Test: `frontend/src/components/marketing/graph/KnowledgeGraphDemo.test.tsx`
- Modify: `docs/frontend-testids.md` (add the surface row + inventory)
- Modify: `frontend/eslint.config.mjs` (add the file to the surface `files` array)

**Interfaces:**
- Consumes: `COURSE_GRAPHS`, `TIER_COLOR`, `CourseGraph` (Task 1); `radialLayout`, `Point` (Task 2).
- Produces: default export `KnowledgeGraphDemo` (no props).

Testids used by this task and by Task 7: `landing-graph` (section), `landing-graph-chip-<courseId>` (chips), `landing-graph-node-<nodeId>` (nodes), `landing-graph-copy` (instructional copy block).

- [ ] **Step 1: Write the failing test**

```tsx
// frontend/src/components/marketing/graph/KnowledgeGraphDemo.test.tsx
// @vitest-environment jsdom
/**
 * The parked frame is the contract. Reduced-motion visitors and the E2E lane
 * both get this render, so "parked" has to mean laid out and readable — not
 * blank and not mid-assembly.
 */
import React from 'react';
import { describe, it, expect, afterEach } from 'vitest';
import { render, screen, cleanup, fireEvent } from '@testing-library/react';

import KnowledgeGraphDemo from './KnowledgeGraphDemo';
import { COURSE_GRAPHS } from './courseGraphs';

afterEach(cleanup);

describe('KnowledgeGraphDemo', () => {
  it('renders a chip per course, with the first selected', () => {
    render(<KnowledgeGraphDemo />);
    for (const g of COURSE_GRAPHS) {
      expect(screen.getByTestId(`landing-graph-chip-${g.id}`)).toBeInTheDocument();
    }
    expect(
      screen.getByTestId(`landing-graph-chip-${COURSE_GRAPHS[0].id}`),
    ).toHaveAttribute('aria-pressed', 'true');
  });

  it('renders the selected course graph fully laid out', () => {
    render(<KnowledgeGraphDemo />);
    const g = COURSE_GRAPHS[0];
    for (const n of g.nodes) {
      expect(screen.getByTestId(`landing-graph-node-${n.id}`)).toBeInTheDocument();
    }
  });

  it('swaps the graph when another chip is picked', () => {
    render(<KnowledgeGraphDemo />);
    const target = COURSE_GRAPHS[1];
    fireEvent.click(screen.getByTestId(`landing-graph-chip-${target.id}`));

    expect(screen.getByTestId(`landing-graph-node-${target.nodes[0].id}`)).toBeInTheDocument();
    expect(
      screen.queryByTestId(`landing-graph-node-${COURSE_GRAPHS[0].nodes[0].id}`),
    ).not.toBeInTheDocument();
  });

  it('labels the section for assistive tech', () => {
    render(<KnowledgeGraphDemo />);
    expect(screen.getByTestId('landing-graph')).toHaveAttribute('aria-label');
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/components/marketing/graph/KnowledgeGraphDemo.test.tsx`
Expected: FAIL — cannot resolve `./KnowledgeGraphDemo`.

- [ ] **Step 3: Write the component**

```tsx
// frontend/src/components/marketing/graph/KnowledgeGraphDemo.tsx
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd frontend && npx vitest run src/components/marketing/graph/KnowledgeGraphDemo.test.tsx`
Expected: PASS

- [ ] **Step 5: Add the `.landing-page`-scoped styles**

Append inside the existing `.landing-page` block region of `frontend/src/app/globals.css` — do **not** create tokens outside that scope:

```css
.landing-page .landing-graph-chip {
  font-family: var(--font-jetbrains), 'JetBrains Mono', monospace;
  font-size: 0.78rem;
  letter-spacing: 0.08em;
  padding: 7px 16px;
  border-radius: 9999px;
  border: 1px solid rgba(107, 114, 128, 0.28);
  background: rgba(255, 255, 255, 0.55);
  color: var(--text-dim);
  cursor: pointer;
  transition: background 0.2s ease, color 0.2s ease, border-color 0.2s ease;
}
.landing-page .landing-graph-chip:hover { border-color: var(--brand-forest); }
.landing-page .landing-graph-chip.is-active {
  background: var(--brand-forest);
  border-color: var(--brand-forest);
  color: #fff;
}
.landing-page .landing-graph-copy { transition: opacity 600ms ease; }
```

- [ ] **Step 6: Register the E2E surface**

In `docs/frontend-testids.md`, add a row to the surface table and the four testids to the inventory:
`landing-graph`, `landing-graph-chip-<courseId>`, `landing-graph-node-<nodeId>`, `landing-graph-copy`.

In `frontend/eslint.config.mjs`, add `"src/components/marketing/graph/KnowledgeGraphDemo.tsx"` to the surface block's `files` array.

- [ ] **Step 7: Verify lint and types**

Run: `cd frontend && npm run lint && npx tsc --noEmit`
Expected: both clean. The lint rule will name any button missing a `data-testid`.

- [ ] **Step 8: Commit**

```bash
git add frontend/src/components/marketing/graph/ frontend/src/app/globals.css frontend/eslint.config.mjs docs/frontend-testids.md
git commit -m "feat(landing): knowledge graph demo — chips and laid-out render (#344)"
```

---

### Task 4: Helical assembly, parked under reduced motion

**Files:**
- Modify: `frontend/src/components/marketing/graph/KnowledgeGraphDemo.tsx`
- Modify: `frontend/src/components/marketing/graph/KnowledgeGraphDemo.test.tsx`

**Interfaces:**
- Consumes: `helixEntry` (Task 2), `IS_TEST_MODE` and `now` from `@/lib/testMode`.
- Produces: no new exports.

- [ ] **Step 1: Write the failing test**

Append to `KnowledgeGraphDemo.test.tsx`:

```tsx
describe('KnowledgeGraphDemo — motion', () => {
  it('parks fully assembled when reduced motion is requested', () => {
    // jsdom has no matchMedia; supply one that reports "reduce".
    window.matchMedia = ((q: string) => ({
      matches: q.includes('prefers-reduced-motion'),
      media: q,
      addEventListener() {},
      removeEventListener() {},
    })) as unknown as typeof window.matchMedia;

    render(<KnowledgeGraphDemo />);
    const g = COURSE_GRAPHS[0];

    // Every node present AND at full opacity — parked means complete.
    for (const n of g.nodes) {
      const el = screen.getByTestId(`landing-graph-node-${n.id}`);
      expect(el).toBeInTheDocument();
      expect(el.getAttribute('opacity')).toBe('1');
    }
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/components/marketing/graph/KnowledgeGraphDemo.test.tsx -t "parks fully assembled"`
Expected: FAIL — nodes carry no `opacity` attribute yet.

- [ ] **Step 3: Implement the assembly loop**

Add to the component's imports:

```tsx
import { useEffect, useRef } from 'react';
import { IS_TEST_MODE, now } from '@/lib/testMode';
import { helixEntry } from './layout';
```

Add the reduced-motion check and progress state (`1` means fully assembled, which is the parked value):

```tsx
const ASSEMBLE_MS = 1100;

const prefersReduced =
  typeof window !== 'undefined' &&
  typeof window.matchMedia === 'function' &&
  window.matchMedia('(prefers-reduced-motion: reduce)').matches;
const parked = IS_TEST_MODE || prefersReduced;

const [progress, setProgress] = useState(parked ? 1 : 0);
const rafRef = useRef(0);

useEffect(() => {
  if (parked) {
    setProgress(1);
    return;
  }
  setProgress(0);
  const start = now();
  const tick = () => {
    const p = Math.min(1, (now() - start) / ASSEMBLE_MS);
    setProgress(p);
    if (p < 1) rafRef.current = requestAnimationFrame(tick);
  };
  rafRef.current = requestAnimationFrame(tick);
  return () => cancelAnimationFrame(rafRef.current);
  // Re-runs on course change so each pick re-assembles.
}, [graph.id, parked]);
```

Give each node a staggered sub-progress and drive it through `helixEntry`. Replace the node `<g>` body:

```tsx
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
```

Edges fade in with the whole assembly — set `strokeOpacity={0.28 * progress}` on the `<line>`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd frontend && npx vitest run src/components/marketing/graph/KnowledgeGraphDemo.test.tsx`
Expected: PASS — including the earlier "renders fully laid out" test, because `IS_TEST_MODE` is false under vitest but the parked test supplies its own `matchMedia`.

> If the non-parked tests now see `progress = 0`, park them the same way: vitest's jsdom has no `matchMedia`, so add the same stub in a `beforeEach` returning `matches: true`. The parked frame is the correct assertion target for unit tests either way.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/marketing/graph/
git commit -m "feat(landing): helical assembly, parked under reduced motion (#344)"
```

---

### Task 5: Interaction — hover blurb, click to expand, copy fade

**Files:**
- Modify: `frontend/src/components/marketing/graph/KnowledgeGraphDemo.tsx`
- Modify: `frontend/src/components/marketing/graph/KnowledgeGraphDemo.test.tsx`

**Interfaces:**
- Consumes: everything from Tasks 1–4.
- Produces: testid `landing-graph-blurb`.

- [ ] **Step 1: Write the failing test**

```tsx
describe('KnowledgeGraphDemo — interaction', () => {
  it('shows a concept blurb on hover', () => {
    render(<KnowledgeGraphDemo />);
    const n = COURSE_GRAPHS[0].nodes[1];
    fireEvent.mouseEnter(screen.getByTestId(`landing-graph-node-${n.id}`));
    expect(screen.getByTestId('landing-graph-blurb')).toHaveTextContent(n.blurb);
  });

  it('fades the instructional copy once the visitor interacts', () => {
    render(<KnowledgeGraphDemo />);
    const copy = screen.getByTestId('landing-graph-copy');
    expect(copy).toHaveAttribute('data-engaged', 'false');

    fireEvent.mouseEnter(
      screen.getByTestId(`landing-graph-node-${COURSE_GRAPHS[0].nodes[1].id}`),
    );
    expect(copy).toHaveAttribute('data-engaged', 'true');
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/components/marketing/graph/KnowledgeGraphDemo.test.tsx -t "interaction"`
Expected: FAIL — no `landing-graph-blurb`, no `data-engaged`.

- [ ] **Step 3: Implement**

```tsx
const [hovered, setHovered] = useState<string | null>(null);
const [engaged, setEngaged] = useState(false);

function onNodeEnter(id: string) {
  setHovered(id);
  setEngaged(true);
}
```

Put `data-engaged={engaged ? 'true' : 'false'}` and `style={{ opacity: engaged ? 0.35 : 1 }}` on the copy block, add `onMouseEnter={() => onNodeEnter(n.id)}` and `onMouseLeave={() => setHovered(null)}` to each node `<g>`, and render the blurb below the svg:

```tsx
<p data-testid="landing-graph-blurb" className="landing-graph-blurb font-inter text-[var(--text-dim)] mt-4 min-h-[1.5rem]">
  {hovered ? graph.nodes.find((n) => n.id === hovered)?.blurb : ''}
</p>
```

`min-h` is load-bearing: without it the paragraph appearing and disappearing shifts everything below it on every hover.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd frontend && npx vitest run src/components/marketing/graph/KnowledgeGraphDemo.test.tsx`
Expected: PASS

- [ ] **Step 5: Register the new testid**

Add `landing-graph-blurb` to the inventory in `docs/frontend-testids.md`.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/marketing/graph/ docs/frontend-testids.md
git commit -m "feat(landing): graph hover blurbs and copy fade on engagement (#344)"
```

---

### Task 6: Wire into the page; delete HowItWorks and the old catalog

**Files:**
- Modify: `frontend/src/app/(public)/page.tsx`
- Delete: `frontend/src/components/marketing/HowItWorks.tsx`
- Modify: `frontend/src/app/globals.css` (remove rules orphaned by the deletions)

**Interfaces:**
- Consumes: `KnowledgeGraphDemo` (Tasks 3–5).
- Produces: nothing.

- [ ] **Step 1: Swap the dynamic import**

Replace the `HowItWorks` dynamic import block. Keep SSR on — `ssr: false` would drop the copy from the HTML crawlers see, which `public-seo.spec.ts` guards:

```tsx
const KnowledgeGraphDemo = dynamic(
  () => import('@/components/marketing/graph/KnowledgeGraphDemo'),
  {
    // Placeholder height matches the section's resolved height so nothing
    // below shifts while the chunk loads.
    loading: () => <section id="knowledge-graph" className="landing-section relative" style={{ minHeight: '80vh' }} />,
  },
);
```

- [ ] **Step 2: Replace the sections**

In the JSX, delete the entire `<section id="features">` block (heading, the six-item `<ol>`, and the "— end of catalog" rule) and replace `<HowItWorks />` with `<KnowledgeGraphDemo />`. The resulting order below the hero is: `<KnowledgeGraphDemo />`, the existing final-CTA `<section>`, then the `<footer>`.

Also remove the now-unused icon imports from `lucide-react` (`Network`, `Sparkles`, `FilePlus2`, `Brain`, `CalendarClock`) — keep `Users` and `PenSquare`, which the hero's floating cards still use.

- [ ] **Step 3: Delete the component**

```bash
git rm frontend/src/components/marketing/HowItWorks.tsx
```

- [ ] **Step 4: Remove orphaned CSS**

In `frontend/src/app/globals.css`, delete rules only the deleted markup used: `.landing-feature-list`, `.landing-feature-row`, `.landing-feature-title`, `.landing-feature-icon`, `.landing-feature-underline`. Confirm each is unused first:

Run: `cd /home/andresl/Projects/sapling && /usr/bin/grep -rn "landing-feature" frontend/src/`
Expected: no hits outside `globals.css` before deleting.

- [ ] **Step 5: Verify build, lint, types, and unit tests**

Run: `cd frontend && npm run lint && npx tsc --noEmit && npx vitest run`
Expected: all clean. Watch for eslint's `--prune-suppressions` ratchet — deleting suppressed code can make lint exit 2 with "suppressions left"; if so run `npx eslint --prune-suppressions .` and commit the updated `eslint-suppressions.json`.

- [ ] **Step 6: Commit**

```bash
git add -A frontend/src frontend/eslint-suppressions.json
git commit -m "feat(landing): replace HowItWorks and the feature catalog with the graph demo (#344)"
```

---

### Task 7: E2E journey

**Files:**
- Create: `frontend/e2e/landing-graph.spec.ts`

**Interfaces:**
- Consumes: testids from Tasks 3 and 5; `test`/`expect` from `./support/fixtures`.
- Produces: nothing.

- [ ] **Step 1: Write the journey**

```ts
// frontend/e2e/landing-graph.spec.ts
/**
 * Journey — the landing page's interactive knowledge graph (#344).
 *
 * The graph is the page's whole argument, so this pins that it renders, that
 * picking a course swaps it, and that engaging with it recedes the
 * instructional copy. Test mode parks the assembly animation, so every
 * assertion runs against the fully laid-out frame.
 */
import { expect, test } from './support/fixtures';

test('landing graph renders, swaps by course, and fades its copy on engagement', async ({ page }) => {
  await page.goto('/');

  const section = page.getByTestId('landing-graph');
  await section.scrollIntoViewIfNeeded();
  await expect(section).toBeVisible();

  // Parked frame: the first course's root node is laid out and visible.
  await expect(page.getByTestId('landing-graph-node-cs-root')).toBeVisible();

  // Picking another course swaps the graph.
  await page.getByTestId('landing-graph-chip-ma242').click();
  await expect(page.getByTestId('landing-graph-node-ma-root')).toBeVisible();
  await expect(page.getByTestId('landing-graph-node-cs-root')).toHaveCount(0);

  // Engaging recedes the copy.
  const copy = page.getByTestId('landing-graph-copy');
  await expect(copy).toHaveAttribute('data-engaged', 'false');
  await page.getByTestId('landing-graph-node-ma-vectors').hover();
  await expect(copy).toHaveAttribute('data-engaged', 'true');
  await expect(page.getByTestId('landing-graph-blurb')).toContainText('Span, basis');
});

test('the deleted scroll section is gone and the CTA still routes', async ({ page }) => {
  await page.goto('/');
  await expect(page.locator('#how-it-works')).toHaveCount(0);
  await expect(page.locator('#features')).toHaveCount(0);
  await expect(page.getByTestId('signin-trigger')).toBeVisible();
});
```

- [ ] **Step 2: Run the full local E2E cycle**

Serialize the whole up→test→down cycle in ONE `flock` — detached servers inherit the lock fd, so a separately-flocked teardown deadlocks:

```bash
cd /home/andresl/Projects/sapling
export SAPLING_MODEL_MODE=function
export SAPLING_FUNCTION_HANDLERS=agents.function_handlers_e2e
export GEMINI_API_KEY=e2e-dummy-key-no-billing
flock /tmp/claude-1000/sapling-e2e-stack.lock bash -c '
  make e2e-up &&
  (cd frontend && npx playwright test e2e/) ; PW=$?
  (cd backend && venv/bin/python -m e2e_oracles) ; OR=$?
  make e2e-down
  echo "playwright=$PW oracles=$OR"
'
```

Expected: `playwright=0 oracles=0`. Read the counts, not the exit code.

- [ ] **Step 3: Commit**

```bash
git add frontend/e2e/landing-graph.spec.ts
git commit -m "test(e2e): journey for the landing knowledge graph (#344)"
```

---

## Self-Review

**Spec coverage (step 1 scope only):**

| Spec requirement | Task |
|---|---|
| Three course chips, graph assembles on pick | 1, 3, 4 |
| Drag / hover / expand | 5 — **gap, see below** |
| Copy fades on interaction | 5 |
| Static fixture data mirroring graph_nodes semantics | 1 |
| Helix fires once, at assembly | 2, 4 |
| Parks complete under reduced motion + test mode | 4 |
| Lazy-load with SSR kept | 6 |
| Placeholder height prevents CLS | 6 |
| `.landing-page`-scoped CSS | 3 |
| Deletes HowItWorks, catalog, indicator, hints, buttons | 6 |
| testids registered + eslint block | 3, 5 |
| E2E journey; public-seo stays green | 7, 6 |

**Known gap, deliberately left:** the spec lists **drag** alongside hover and expand; Task 5 implements hover blurbs and copy fade but not node dragging or click-to-expand. Both are additive to the same component and neither changes the interfaces above. Implement them as Task 5b/5c during execution, or fold them into Task 5 — flagged here rather than silently dropped so the reviewer sees the difference between plan and spec. Dragging in particular needs a pointer-capture decision (SVG coordinate mapping via `getScreenCTM()`) that is worth its own review gate.

**Placeholder scan:** no TBD/TODO; every code step carries real code.

**Type consistency:** `radialLayout(graph, width, height) → Map<string, Point>` and `helixEntry(target, centre, t, turns?)` are used with those exact signatures in Tasks 3–4. `TIER_COLOR` keys match `MasteryTier`. Node testids use `n.id` from the fixtures, and the E2E spec references real ids (`cs-root`, `ma-root`, `ma-vectors`) that exist in Task 1's data.

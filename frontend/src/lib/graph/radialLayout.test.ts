import { describe, expect, it } from "vitest";
import type { GraphEdge, GraphNode } from "@/lib/data";
import {
  ARC_PER_NODE,
  COURSE_MARGIN,
  LABEL_ZOOM,
  RING0,
  RING_REACH,
  RING_STEP,
  computeDepths,
  courseLinks,
  forceOrbit,
  importanceRadii,
  isDirected,
  labelOpacityAt,
  packCourses,
  planBounds,
  planRadial,
  pushCoursesApart,
  reachByCourse,
  ringsFor,
  splitEdges,
  type RadialPlan,
} from "./radialLayout";

const TAU = Math.PI * 2;

const root = (course: string): GraphNode => ({
  id: `root-${course}`,
  name: `${course.toUpperCase()} 101 - A course`,
  subject: course,
  color: "#3e6f8a",
  mastery_tier: "learning",
  mastery_score: 0,
  course_id: course,
  is_subject_root: true,
});
const concept = (id: string, course = "c1"): GraphNode => ({
  id,
  name: id,
  subject: course,
  color: "#3e6f8a",
  mastery_tier: "learning",
  mastery_score: 0.5,
  course_id: course,
});
const concepts = (count: number, course = "c1", prefix = "n") =>
  Array.from({ length: count }, (_, i) => concept(`${course}-${prefix}${i}`, course));
const edge = (source: string, target: string, relationship_type?: GraphEdge["relationship_type"]): GraphEdge => ({
  source,
  target,
  strength: 0.5,
  relationship_type,
});
/** A prerequisite chain through the given ids, in order. */
const chain = (ids: string[]) => ids.slice(1).map((id, i) => edge(ids[i], id, "prerequisite"));

/** The smallest angle between two directions. */
const angleBetween = (a: number, b: number) => {
  const d = Math.abs(a - b) % TAU;
  return Math.min(d, TAU - d);
};

describe("isDirected / splitEdges", () => {
  it("treats prerequisite, builds_on and part_of as directed", () => {
    expect(isDirected({ relationship_type: "prerequisite" })).toBe(true);
    expect(isDirected({ relationship_type: "builds_on" })).toBe(true);
    expect(isDirected({ relationship_type: "part_of" })).toBe(true);
    expect(isDirected({ relationship_type: "related" })).toBe(false);
    expect(isDirected({})).toBe(false);
  });

  it("separates the course spokes from the concept-to-concept edges", () => {
    const nodes = [root("c1"), concept("a"), concept("b")];
    const edges = [edge("root-c1", "a"), edge("a", "b", "prerequisite"), edge("b", "root-c1")];
    const { concept: kept, anchors } = splitEdges(nodes, edges);
    expect(kept).toEqual([edges[1]]);
    expect(anchors).toEqual([edges[0], edges[2]]);
  });
});

describe("computeDepths", () => {
  it("is the longest directed path into each concept", () => {
    const depth = computeDepths(
      ["a", "b", "c", "d"],
      [edge("a", "b", "prerequisite"), edge("b", "c", "builds_on"), edge("a", "c", "part_of"), edge("a", "d", "related")],
    );
    expect(Object.fromEntries(depth)).toEqual({ a: 0, b: 1, c: 2, d: 0 });
  });

  it("ignores edges to concepts outside the set", () => {
    const depth = computeDepths(["a", "b"], [edge("zz", "a", "prerequisite"), edge("a", "b", "prerequisite")]);
    expect(Object.fromEntries(depth)).toEqual({ a: 0, b: 1 });
  });

  it("stops on a cycle instead of looping", () => {
    const depth = computeDepths(["a", "b", "c"], chain(["a", "b", "c", "a"]));
    for (const d of depth.values()) {
      expect(d).toBeGreaterThanOrEqual(0);
      expect(d).toBeLessThan(3);
    }
  });
});

describe("ringsFor", () => {
  const seats = (rings: ReturnType<typeof ringsFor>) => rings.reduce((sum, ring) => sum + ring.count, 0);
  const outer = (rings: ReturnType<typeof ringsFor>) => rings[rings.length - 1].radius;
  /** Arc each concept gets on a ring. */
  const pitch = (ring: { radius: number; count: number }) => (TAU * ring.radius) / ring.count;

  it("seats nothing on no rings", () => {
    expect(ringsFor(0, RING0)).toEqual([]);
    expect(ringsFor(-3, RING0)).toEqual([]);
  });

  it("keeps a handful of concepts on one ring at the smallest radius", () => {
    for (const n of [1, 2, 3, 6]) {
      expect(ringsFor(n, RING0)).toEqual([{ radius: RING0, count: n }]);
    }
  });

  it("grows the one ring until a second ring is the smaller answer", () => {
    const seven = ringsFor(7, RING0);
    expect(seven).toHaveLength(1);
    expect(seven[0].radius).toBeCloseTo((7 * ARC_PER_NODE) / TAU, 10);
    expect(ringsFor(11, RING0)).toHaveLength(1);
    // Twelve on one ring would be wider than two rings from the centre.
    const twelve = ringsFor(12, RING0);
    expect(twelve.map((ring) => ring.radius)).toEqual([RING0, RING0 + RING_STEP]);
    expect(seats(twelve)).toBe(12);
  });

  it("seats every concept, on rings one step apart, for any number of them", () => {
    for (let n = 1; n <= 240; n++) {
      const rings = ringsFor(n, RING0);
      expect(seats(rings)).toBe(n);
      rings.forEach((ring, i) => {
        expect(ring.count).toBeGreaterThan(0);
        expect(ring.radius).toBeGreaterThanOrEqual(RING0);
        if (i > 0) expect(ring.radius - rings[i - 1].radius).toBeCloseTo(RING_STEP, 10);
      });
    }
  });

  it("gives every concept close to its arc, on every ring", () => {
    for (let n = 1; n <= 240; n++) {
      for (const ring of ringsFor(n, RING0)) {
        // Rounding a ring's share up or down costs at most one seat's worth.
        expect(pitch(ring)).toBeGreaterThan(ARC_PER_NODE * 0.84);
      }
    }
  });

  it("fills every ring about equally, inner rings holding fewer", () => {
    for (const n of [30, 60, 90, 200]) {
      const rings = ringsFor(n, RING0);
      expect(rings.length).toBeGreaterThan(2);
      const pitches = rings.map(pitch);
      expect(Math.max(...pitches) / Math.min(...pitches)).toBeLessThan(1.2);
      for (let i = 1; i < rings.length; i++) expect(rings[i].count).toBeGreaterThan(rings[i - 1].count);
    }
  });

  it("is far more compact than one ring", () => {
    for (const n of [20, 30, 60, 120]) {
      const single = (n * ARC_PER_NODE) / TAU;
      expect(outer(ringsFor(n, RING0))).toBeLessThan(single * 0.65);
    }
    // Thirty concepts: three rings, the outer one at 232, not one ring at 439.
    expect(ringsFor(30, RING0)).toEqual([
      { radius: 96, count: 6 },
      { radius: 164, count: 10 },
      { radius: 232, count: 14 },
    ]);
  });

  it("never grows narrower when a concept is added", () => {
    let last = 0;
    for (let n = 1; n <= 240; n++) {
      const r = outer(ringsFor(n, RING0));
      // Filling in from the centre may cost a few percent; it is never a step back by more.
      expect(r).toBeGreaterThanOrEqual(last * 0.94);
      last = Math.max(last, r);
    }
  });

  it("starts from the centre when that costs next to nothing", () => {
    // Two rings pushed out to 164 and 232 are no narrower than three from 96.
    const rings = ringsFor(27, RING0);
    expect(rings.map((ring) => ring.radius)).toEqual([96, 164, 232]);
    // …but twenty concepts stay on two rings: a third would be much wider.
    const twenty = ringsFor(20, RING0);
    expect(twenty).toHaveLength(2);
    expect(outer(twenty)).toBeLessThan(RING0 + 2 * RING_STEP);
  });

  it("respects a larger smallest radius", () => {
    const rings = ringsFor(4, 300);
    expect(rings).toEqual([{ radius: 300, count: 4 }]);
    for (const ring of ringsFor(80, 300)) expect(ring.radius).toBeGreaterThanOrEqual(300);
  });
});

describe("packCourses", () => {
  const F = 260;
  const REACH = { x: 250, y: 230 };
  /** Every pair of courses keeps its two footprints apart. */
  const expectApart = (spots: Array<{ x: number; y: number }>, footprint = F) => {
    for (let i = 0; i < spots.length; i++) {
      for (let j = i + 1; j < spots.length; j++) {
        const d = Math.hypot(spots[i].x - spots[j].x, spots[i].y - spots[j].y);
        expect(d, `courses ${i} and ${j}`).toBeGreaterThanOrEqual(2 * footprint - 1e-6);
      }
    }
  };
  /** The scale at which the arrangement, with its reach, fits the window. */
  const fitScale = (spots: Array<{ x: number; y: number }>, w: number, h: number) => {
    const xs = spots.map((s) => s.x);
    const ys = spots.map((s) => s.y);
    return Math.min(
      w / (Math.max(...xs) - Math.min(...xs) + 2 * REACH.x),
      h / (Math.max(...ys) - Math.min(...ys) + 2 * REACH.y),
      1,
    );
  };
  const rowsOf = (spots: Array<{ x: number; y: number }>) => {
    const rows = new Map<number, number>();
    for (const s of spots) rows.set(Math.round(s.y), (rows.get(Math.round(s.y)) ?? 0) + 1);
    return [...rows.entries()].sort((a, b) => a[0] - b[0]).map(([, n]) => n);
  };

  it("puts nothing nowhere and one course in the middle", () => {
    expect(packCourses(0, F, REACH, 1200, 700)).toEqual([]);
    expect(packCourses(1, F, REACH, 1200, 700)).toEqual([{ x: 0, y: 0 }]);
  });

  it("sits two courses side by side in a wide window and stacked in a tall one", () => {
    expect(packCourses(2, F, REACH, 1240, 744)).toEqual([{ x: -F, y: 0 }, { x: F, y: 0 }]);
    expect(packCourses(2, F, REACH, 300, 900)).toEqual([{ x: 0, y: -F }, { x: 0, y: F }]);
  });

  it("centres the arrangement on the middle of the canvas", () => {
    for (const k of [2, 3, 4, 5, 6, 7, 9, 12]) {
      for (const [w, h] of [[1240, 744], [798, 667], [400, 900]]) {
        const spots = packCourses(k, F, REACH, w, h);
        const xs = spots.map((s) => s.x);
        const ys = spots.map((s) => s.y);
        expect(Math.min(...xs) + Math.max(...xs)).toBeCloseTo(0, 6);
        expect(Math.min(...ys) + Math.max(...ys)).toBeCloseTo(0, 6);
      }
    }
  });

  it("gives every course its place and keeps their footprints apart", () => {
    for (let k = 1; k <= 14; k++) {
      for (const [w, h] of [[1240, 744], [798, 667], [400, 900], [2000, 500], [1, 1]]) {
        const spots = packCourses(k, F, REACH, w, h);
        expect(spots).toHaveLength(k);
        expectApart(spots);
      }
    }
  });

  it("uses as many rows as show the courses largest", () => {
    // Three in a very wide window: one row. In a squarer one: two rows.
    expect(rowsOf(packCourses(3, F, REACH, 1900, 600))).toEqual([3]);
    expect(rowsOf(packCourses(3, F, REACH, 798, 667))).toEqual([1, 2]);
    expect(rowsOf(packCourses(4, F, REACH, 1240, 744))).toEqual([2, 2]);
    expect(rowsOf(packCourses(5, F, REACH, 1240, 744))).toEqual([2, 3]);
    expect(rowsOf(packCourses(6, F, REACH, 1240, 744))).toEqual([3, 3]);
    expect(rowsOf(packCourses(7, F, REACH, 1240, 744))).toEqual([3, 4]);
    expect(rowsOf(packCourses(4, F, REACH, 400, 2400))).toEqual([1, 1, 1, 1]);
  });

  it("puts the shorter row on top, clear of the window's corners", () => {
    for (const [k, w, h] of [[3, 798, 667], [5, 1240, 744], [7, 1240, 744]]) {
      const rows = rowsOf(packCourses(k, F, REACH, w, h));
      expect(rows).toHaveLength(2);
      expect(rows[0]).toBeLessThan(rows[1]);
    }
  });

  it("nests rows of unequal length like a honeycomb", () => {
    const spots = packCourses(5, F, REACH, 1240, 744);
    const top = spots.filter((s) => s.y < 0);
    const bottom = spots.filter((s) => s.y > 0);
    // The rows are closer together than a square grid would put them…
    expect(bottom[0].y - top[0].y).toBeCloseTo(Math.sqrt(3) * F, 6);
    // …because each course in the short row sits between two of the long one.
    expect(top.map((s) => s.x)).toEqual([-F, F]);
    expect(bottom.map((s) => s.x)).toEqual([-2 * F, 0, 2 * F]);
  });

  // The arrangement this replaced: every course on one circle from the top,
  // wide enough to keep neighbours apart.
  const ringOf = (k: number) => {
    const spread = F / Math.sin(Math.PI / k);
    return Array.from({ length: k }, (_, i) => {
      const a = -Math.PI / 2 + (i / k) * TAU;
      return { x: Math.cos(a) * spread, y: Math.sin(a) * spread };
    });
  };

  it("never shows the courses smaller than a ring of courses would", () => {
    for (let k = 3; k <= 14; k++) {
      for (const [w, h] of [[1240, 744], [798, 667], [400, 900], [2000, 500], [700, 700]]) {
        const packed = fitScale(packCourses(k, F, REACH, w, h), w, h);
        expect(packed, `${k} courses in ${w}×${h}`).toBeGreaterThanOrEqual(fitScale(ringOf(k), w, h) - 1e-9);
      }
    }
  });

  it("shows many courses much larger than a ring of courses would", () => {
    for (const k of [4, 6, 8, 12]) {
      for (const [w, h] of [[1240, 744], [798, 667]]) {
        const packed = fitScale(packCourses(k, F, REACH, w, h), w, h);
        expect(packed, `${k} courses in ${w}×${h}`).toBeGreaterThan(fitScale(ringOf(k), w, h) * 1.15);
      }
    }
  });

  it("keeps a ring of courses where that is the better shape", () => {
    // Five in a squarish panel: two rows would run three wide, so a pentagon shows them larger.
    const spots = packCourses(5, F, REACH, 798, 667);
    expectApart(spots);
    const cx = spots.reduce((sum, p) => sum + p.x, 0) / 5;
    const cy = spots.reduce((sum, p) => sum + p.y, 0) / 5;
    const spread = F / Math.sin(Math.PI / 5);
    for (const p of spots) expect(Math.hypot(p.x - cx, p.y - cy)).toBeCloseTo(spread, 6);
    expect(fitScale(spots, 798, 667)).toBeGreaterThan(fitScale(packCourses(5, F, REACH, 1240, 744), 798, 667));
  });

  it("fills rows in order: left to right, top to bottom", () => {
    const spots = packCourses(6, F, REACH, 1240, 744);
    for (let i = 1; i < spots.length; i++) {
      const before = spots[i - 1];
      const here = spots[i];
      expect(here.y > before.y || (here.y === before.y && here.x > before.x)).toBe(true);
    }
  });

  it("is steady: the same question has the same answer", () => {
    expect(packCourses(7, F, REACH, 1240, 744)).toEqual(packCourses(7, F, REACH, 1240, 744));
  });
});

describe("planRadial", () => {
  const W = 1240;
  const H = 744;
  const plan30 = () => planRadial([root("c1"), ...concepts(30)], [], W, H);

  it("puts a single course in the middle of the canvas", () => {
    const plan = plan30();
    expect(plan.centers.get("root-c1")).toEqual({ x: W / 2, y: H / 2 });
  });

  it("seats unlinked concepts on a few rings from the centre, not one wide wheel", () => {
    const plan = plan30();
    const radii = [...plan.orbit.values()].map((o) => o.radius);
    expect([...new Set(radii)].sort((a, b) => a - b)).toEqual([96, 164, 232]);
    expect(radii.filter((r) => r === 96)).toHaveLength(6);
    expect(radii.filter((r) => r === 164)).toHaveLength(10);
    expect(radii.filter((r) => r === 232)).toHaveLength(14);
    for (const o of plan.orbit.values()) {
      expect(o.rootId).toBe("root-c1");
      expect(o.depth).toBe(0);
    }
  });

  it("spreads each ring's concepts evenly all the way round", () => {
    const plan = plan30();
    for (const radius of [96, 164, 232]) {
      const angles = [...plan.orbit.values()]
        .filter((o) => o.radius === radius)
        .map((o) => ((o.angle % TAU) + TAU) % TAU)
        .sort((a, b) => a - b);
      const step = TAU / angles.length;
      for (let i = 1; i < angles.length; i++) expect(angles[i] - angles[i - 1]).toBeCloseTo(step, 9);
    }
  });

  it("keeps every pair of concepts a caption apart", () => {
    for (const n of [5, 12, 30, 60, 120]) {
      const plan = planRadial([root("c1"), ...concepts(n)], [], W, H);
      const pts = [...plan.orbit.values()].map((o) => [Math.cos(o.angle) * o.radius, Math.sin(o.angle) * o.radius]);
      let nearest = Infinity;
      for (let i = 0; i < pts.length; i++) {
        for (let j = i + 1; j < pts.length; j++) {
          nearest = Math.min(nearest, Math.hypot(pts[i][0] - pts[j][0], pts[i][1] - pts[j][1]));
        }
      }
      // Neighbours on a ring sit about an arc apart; rings sit a step apart.
      expect(nearest, `${n} concepts`).toBeGreaterThan(Math.min(RING_STEP, ARC_PER_NODE) * 0.8);
    }
  });

  it("turns each ring so concepts on neighbouring rings do not line up", () => {
    const plan = plan30();
    const at = (radius: number) =>
      [...plan.orbit.values()].filter((o) => o.radius === radius).map((o) => o.angle);
    const first = (radius: number) => {
      const angles = at(radius);
      const step = TAU / angles.length;
      return ((Math.min(...angles.map((a) => ((a % step) + step) % step))) / step);
    };
    // Each ring starts at its own point in its own step.
    expect(new Set([first(96), first(164), first(232)].map((f) => f.toFixed(3))).size).toBe(3);
  });

  it("never seats a concept inside something that leads into it", () => {
    const nodes = [root("c1"), ...concepts(40)];
    const ids = nodes.slice(1).map((n) => n.id);
    // A long chain, a fan and some cross links.
    const edges = [
      ...chain(ids.slice(0, 12)),
      ...ids.slice(13, 22).map((id) => edge(ids[12], id, "builds_on")),
      ...ids.slice(23, 30).map((id, i) => edge(ids[13 + i], id, "part_of")),
      edge(ids[30], ids[5], "prerequisite"),
      edge(ids[31], ids[32], "related"),
    ];
    const plan = planRadial(nodes, edges, W, H);
    for (const e of edges) {
      if (!isDirected(e)) continue;
      const s = plan.orbit.get(e.source)!;
      const t = plan.orbit.get(e.target)!;
      expect(t.depth).toBeGreaterThan(s.depth);
      expect(t.radius, `${e.source} → ${e.target}`).toBeGreaterThanOrEqual(s.radius);
    }
    // The concepts nothing leads into are the innermost ones.
    const starts = [...plan.orbit.values()].filter((o) => o.depth === 0).map((o) => o.radius);
    const rest = [...plan.orbit.values()].filter((o) => o.depth > 0).map((o) => o.radius);
    expect(Math.max(...starts)).toBeLessThanOrEqual(Math.min(...rest));
  });

  it("is as compact for a long chain as for unlinked concepts", () => {
    const nodes = [root("c1"), ...concepts(30)];
    const ids = nodes.slice(1).map((n) => n.id);
    const linked = planRadial(nodes, chain(ids), W, H);
    const outer = Math.max(...[...linked.orbit.values()].map((o) => o.radius));
    // One ring per level would put the thirtieth concept 29 rings out.
    expect(outer).toBe(232);
    expect(Math.max(...[...linked.orbit.values()].map((o) => o.depth))).toBe(29);
  });

  it("seats a concept out from what leads into it", () => {
    // Twelve concepts take two rings, of four and eight. Four starting
    // concepts fill the inner one; each has two concepts built on it.
    const starts = concepts(4, "c1", "s");
    const next = concepts(8, "c1", "t");
    const edges = next.map((t, i) => edge(starts[i % 4].id, t.id, "prerequisite"));
    const plan = planRadial([root("c1"), ...starts, ...next], edges, W, H);
    for (const s of starts) expect(plan.orbit.get(s.id)!.radius).toBe(96);
    for (const e of edges) {
      const s = plan.orbit.get(e.source)!;
      const t = plan.orbit.get(e.target)!;
      expect(t.radius).toBe(164);
      // Within a seat of straight out from its source: a quarter turn is one inner seat.
      expect(angleBetween(s.angle, t.angle), `${e.source} → ${e.target}`).toBeLessThan(TAU / 8 + 1e-9);
    }
  });

  it("gives the same plan for the same graph, whatever order the nodes come in", () => {
    const nodes = [root("c1"), ...concepts(18)];
    const ids = nodes.slice(1).map((n) => n.id);
    const edges = [...chain(ids.slice(0, 5)), edge(ids[6], ids[7], "builds_on")];
    const a = planRadial(nodes, edges, W, H);
    const b = planRadial([nodes[0], ...nodes.slice(1).reverse()], [...edges].reverse(), W, H);
    for (const id of ids) {
      expect(b.orbit.get(id)!.radius).toBe(a.orbit.get(id)!.radius);
      expect(b.orbit.get(id)!.angle).toBeCloseTo(a.orbit.get(id)!.angle, 9);
    }
  });

  it("plans each course on its own, around its own centre", () => {
    const nodes = [root("c1"), root("c2"), ...concepts(8, "c1"), ...concepts(20, "c2")];
    const plan = planRadial(nodes, [], W, H);
    for (const [id, o] of plan.orbit) expect(o.rootId).toBe(id.startsWith("c1-") ? "root-c1" : "root-c2");
    const a = plan.centers.get("root-c1")!;
    const b = plan.centers.get("root-c2")!;
    // Side by side, the first course on the left, centred on the canvas.
    expect(a.y).toBe(H / 2);
    expect(b.y).toBe(H / 2);
    expect(a.x).toBeLessThan(b.x);
    expect((a.x + b.x) / 2).toBeCloseTo(W / 2, 9);
    // Apart by the wider course's ring plus the margin, twice over.
    const widest = Math.max(...[...plan.orbit.values()].map((o) => o.radius));
    expect(b.x - a.x).toBeCloseTo(2 * (widest + COURSE_MARGIN), 9);
  });

  it("keeps neighbouring courses' outer rings a margin apart", () => {
    for (const k of [2, 3, 4, 5, 7]) {
      const courses = Array.from({ length: k }, (_, i) => `k${i}`);
      const nodes = [...courses.map(root), ...courses.flatMap((c) => concepts(14, c))];
      const plan = planRadial(nodes, [], 798, 667);
      const centres = [...plan.centers.values()];
      const outer = Math.max(...[...plan.orbit.values()].map((o) => o.radius));
      for (let i = 0; i < centres.length; i++) {
        for (let j = i + 1; j < centres.length; j++) {
          const d = Math.hypot(centres[i].x - centres[j].x, centres[i].y - centres[j].y);
          expect(d - 2 * outer).toBeGreaterThanOrEqual(2 * COURSE_MARGIN - 1e-6);
        }
      }
    }
  });

  it("gives a course with no concepts a centre and room", () => {
    const plan = planRadial([root("c1"), root("c2"), ...concepts(3, "c1")], [], W, H);
    expect(plan.centers.size).toBe(2);
    const a = plan.centers.get("root-c1")!;
    const b = plan.centers.get("root-c2")!;
    expect(b.x - a.x).toBeCloseTo(2 * (RING0 + COURSE_MARGIN), 9);
  });

  it("lets concepts with no course root orbit the middle of the canvas", () => {
    // A quiz neighbourhood: concepts only.
    const plan = planRadial(concepts(9), [], 500, 340);
    expect(plan.centers.size).toBe(0);
    for (const o of plan.orbit.values()) expect(o.rootId).toBeNull();
    expect(plan.orbit.size).toBe(9);
    expect(courseLinks(plan)).toEqual([]);
  });

  it("plans nothing for no nodes", () => {
    const plan = planRadial([], [], W, H);
    expect(plan.centers.size).toBe(0);
    expect(plan.orbit.size).toBe(0);
    expect(planBounds(plan, W, H)).toBeNull();
  });

  it("survives a cycle in the data", () => {
    const nodes = [root("c1"), ...concepts(5)];
    const ids = nodes.slice(1).map((n) => n.id);
    const plan = planRadial(nodes, chain([...ids, ids[0]]), W, H);
    expect(plan.orbit.size).toBe(5);
    for (const o of plan.orbit.values()) {
      expect(Number.isFinite(o.radius)).toBe(true);
      expect(Number.isFinite(o.angle)).toBe(true);
    }
  });
});

describe("courseLinks", () => {
  it("links the course to each concept nothing leads into, and only those", () => {
    const nodes = [root("c1"), concept("a"), concept("b"), concept("c")];
    const plan = planRadial(nodes, [edge("a", "b", "prerequisite"), edge("a", "c", "related")], 800, 600);
    expect(courseLinks(plan).map((l) => `${l.source}>${l.target}`).sort()).toEqual(["root-c1>a", "root-c1>c"]);
    for (const l of courseLinks(plan)) expect(l.relationship_type).toBe("part_of");
  });
});

describe("planBounds", () => {
  it("reaches past the outer ring by the room a mark and its caption need", () => {
    const plan = planRadial([root("c1"), ...concepts(30)], [], 1240, 744);
    const b = planBounds(plan, 1240, 744)!;
    expect(b.minX).toBeCloseTo(620 - 232 - RING_REACH.x, 9);
    expect(b.maxX).toBeCloseTo(620 + 232 + RING_REACH.x, 9);
    expect(b.minY).toBeCloseTo(372 - 232 - RING_REACH.y, 9);
    expect(b.maxY).toBeCloseTo(372 + 232 + RING_REACH.y, 9);
    // Captions are wider than they are tall.
    expect(RING_REACH.x).toBeGreaterThan(RING_REACH.y);
  });

  it("covers a course with no concepts", () => {
    const plan = planRadial([root("c1")], [], 800, 600);
    expect(planBounds(plan, 800, 600)).toEqual({ minX: 360, maxX: 440, minY: 260, maxY: 340 });
  });

  it("measures rootless concepts from the middle of the canvas", () => {
    const plan = planRadial(concepts(4), [], 500, 340);
    const b = planBounds(plan, 500, 340)!;
    expect((b.minX + b.maxX) / 2).toBeCloseTo(250, 9);
    expect((b.minY + b.maxY) / 2).toBeCloseTo(170, 9);
  });

  it("fits thirty unlinked concepts in a dashboard panel at full size", () => {
    // The point of the rings: this was a 966-wide wheel.
    const plan = planRadial([root("c1"), ...concepts(30)], [], 798, 667);
    const b = planBounds(plan, 798, 667)!;
    expect(b.maxX - b.minX).toBeLessThanOrEqual(798);
    expect(b.maxY - b.minY).toBeLessThanOrEqual(667);
  });
});

describe("forceOrbit", () => {
  type P = { id: string; x: number; y: number; vx: number; vy: number };
  const planOf = (radius: number, angle: number) => ({
    centers: new Map<string, { x: number; y: number }>(),
    orbit: new Map([["a", { rootId: "r", radius, angle, depth: 0 }]]),
  });
  /** One tick at full strength, with the course centred on (100, 100) unless said otherwise. */
  const run = (n: P, radius: number, angle: number, centre = { x: 100, y: 100 }) => {
    const force = forceOrbit<P>(() => planOf(radius, angle), () => centre, 0.3);
    force.initialize([n]);
    force(1);
  };

  it("draws a concept straight toward its seat, harder the further away it is", () => {
    // Seat at (200, 100).
    const near: P = { id: "a", x: 190, y: 100, vx: 0, vy: 0 };
    run(near, 100, 0);
    expect(near.vx).toBeCloseTo(3, 9);
    expect(near.vy).toBeCloseTo(0, 9);
    const far: P = { id: "a", x: 130, y: 100, vx: 0, vy: 0 };
    run(far, 100, 0);
    expect(far.vx).toBeCloseTo(21, 9);
    expect(far.vy).toBeCloseTo(0, 9);
  });

  it("leaves a concept sitting on its seat alone", () => {
    const n: P = { id: "a", x: 200, y: 100, vx: 0, vy: 0 };
    run(n, 100, 0);
    expect(n.vx).toBeCloseTo(0, 9);
    expect(n.vy).toBeCloseTo(0, 9);
  });

  it("walks a concept round the course to a seat on its far side, not through the middle", () => {
    // On its ring, diametrically opposite its seat (at (200, 100)).
    const n: P = { id: "a", x: 0, y: 100, vx: 0, vy: 0 };
    run(n, 100, 0);
    // It heads for a point an eighth of a turn round, half a ring outside its ring…
    const target = { x: n.x + n.vx / 0.3, y: n.y + n.vy / 0.3 };
    expect(Math.hypot(target.x - 100, target.y - 100)).toBeCloseTo(100 + RING_STEP / 2, 6);
    expect(Math.abs(Math.atan2(target.y - 100, target.x - 100))).toBeCloseTo(Math.PI - Math.PI / 4, 6);
    // …so it moves round, not in toward the course's centre.
    expect(Math.abs(n.vy)).toBeGreaterThan(5 * Math.abs(n.vx));
  });

  it("takes the shorter way round", () => {
    // Seat a quarter turn clockwise (screen y is down: angle π/2 is below).
    const n: P = { id: "a", x: 100, y: 0, vx: 0, vy: 0 };
    run(n, 100, -Math.PI / 2 + Math.PI / 2 + 1.2);
    // From the top (angle -π/2) to angle 1.2, the short way is clockwise
    // through the right-hand side: it heads right.
    expect(n.vx).toBeGreaterThan(0);
  });

  it("heads straight for a seat close round the course", () => {
    // A little round from its seat: straight at it, no detour.
    const n: P = { id: "a", x: 100 + Math.cos(0.5) * 100, y: 100 + Math.sin(0.5) * 100, vx: 0, vy: 0 };
    run(n, 100, 0);
    expect(n.vx).toBeCloseTo((200 - n.x) * 0.3, 9);
    expect(n.vy).toBeCloseTo((100 - n.y) * 0.3, 9);
  });

  it("weakens with the simulation's heat", () => {
    const n: P = { id: "a", x: 190, y: 100, vx: 0, vy: 0 };
    const force = forceOrbit<P>(() => planOf(100, 0), () => ({ x: 100, y: 100 }), 0.3);
    force.initialize([n]);
    force(0.5);
    expect(n.vx).toBeCloseTo(1.5, 9);
  });

  it("ignores a node with no seat or no position", () => {
    const stray = { id: "zz", x: 5, y: 5, vx: 0, vy: 0 };
    const force = forceOrbit<P>(() => planOf(100, 0), () => ({ x: 0, y: 0 }));
    force.initialize([stray]);
    force(1);
    expect(stray).toEqual({ id: "zz", x: 5, y: 5, vx: 0, vy: 0 });
  });

  it("follows the course's centre as it is now, not as planned", () => {
    // The course has moved 30 to the right: its concepts follow it there.
    const n: P = { id: "a", x: 200, y: 100, vx: 0, vy: 0 };
    run(n, 100, 0, { x: 130, y: 100 });
    expect(n.vx).toBeCloseTo(9, 9);
  });
});

describe("importanceRadii", () => {
  it("sizes a concept by how much is built on it", () => {
    const nodes = [root("c1"), concept("a"), concept("b"), concept("c"), concept("d")];
    const radii = importanceRadii(nodes, [edge("a", "b", "prerequisite"), edge("b", "c", "builds_on")]);
    expect(radii.has("root-c1")).toBe(false);
    expect(radii.get("a")).toBe(9 + 14); // everything downstream of it
    expect(radii.get("b")).toBeCloseTo(9 + 14 * Math.sqrt(1 / 2), 9);
    expect(radii.get("c")).toBe(9);
    expect(radii.get("d")).toBe(9);
  });

  it("falls back to link count with no directed edges, and to one size with none at all", () => {
    const nodes = [concept("a"), concept("b"), concept("c")];
    const linked = importanceRadii(nodes, [edge("a", "b", "related"), edge("a", "c")]);
    expect(linked.get("a")).toBe(23);
    expect(linked.get("b")).toBeCloseTo(9 + 14 * Math.sqrt(1 / 2), 9);
    expect([...importanceRadii(nodes, []).values()]).toEqual([11, 11, 11]);
  });
});

describe("labelOpacityAt", () => {
  it("hides labels zoomed out and shows them fully from the full mark up", () => {
    expect(labelOpacityAt(LABEL_ZOOM.hidden)).toBe(0);
    expect(labelOpacityAt(0.2)).toBe(0);
    expect(labelOpacityAt(LABEL_ZOOM.full)).toBe(1);
    expect(labelOpacityAt(1)).toBe(1);
    expect(labelOpacityAt(3)).toBe(1);
  });

  it("fades evenly in between", () => {
    const mid = (LABEL_ZOOM.hidden + LABEL_ZOOM.full) / 2;
    expect(labelOpacityAt(mid)).toBeCloseTo(0.5, 9);
    expect(labelOpacityAt(mid + 0.05)).toBeGreaterThan(labelOpacityAt(mid));
  });

  it("opens a graph that is a little under full size with its labels on", () => {
    expect(labelOpacityAt(0.9)).toBe(1);
    expect(labelOpacityAt(0.8)).toBeGreaterThan(0.7);
  });
});

/** Where each concept of a plan sits, relative to its course's centre. */
const seatOf = (plan: RadialPlan, id: string) => {
  const o = plan.orbit.get(id)!;
  return { x: Math.cos(o.angle) * o.radius, y: Math.sin(o.angle) * o.radius };
};
/** How many pairs of links (as straight lines between seats) cross. */
function crossings(plan: RadialPlan, edges: GraphEdge[]): number {
  const segs = edges.map((e) => [seatOf(plan, e.source), seatOf(plan, e.target)] as const);
  const side = (a: { x: number; y: number }, b: { x: number; y: number }, c: { x: number; y: number }) =>
    Math.sign((b.x - a.x) * (c.y - a.y) - (b.y - a.y) * (c.x - a.x));
  let n = 0;
  for (let i = 0; i < segs.length; i++) {
    for (let j = i + 1; j < segs.length; j++) {
      const [p, q] = segs[i];
      const [r, t] = segs[j];
      // Links that share a concept meet there; that is not a crossing.
      if ([p, q].some((u) => [r, t].some((v) => Math.hypot(u.x - v.x, u.y - v.y) < 1e-6))) continue;
      if (side(p, q, r) * side(p, q, t) < 0 && side(r, t, p) * side(r, t, q) < 0) n++;
    }
  }
  return n;
}

describe("planRadial — untangling", () => {
  const W = 1240;
  const H = 744;
  const related = (a: string, b: string) => edge(a, b, "related");

  it("seats linked concepts next to each other", () => {
    // Six linked pairs among twelve concepts, named so that seating by id
    // alone would scatter every pair across the course.
    const nodes = [root("c1"), ...concepts(12)];
    const ids = nodes.slice(1).map((n) => n.id);
    const pairs = [0, 1, 2, 3, 4, 5].map((i) => [ids[i], ids[i + 6]] as const);
    const plan = planRadial(nodes, pairs.map(([a, b]) => related(a, b)), W, H);
    for (const [a, b] of pairs) {
      const d = Math.hypot(seatOf(plan, a).x - seatOf(plan, b).x, seatOf(plan, a).y - seatOf(plan, b).y);
      // Neighbouring seats: on one ring, or one ring apart.
      expect(d, `${a} – ${b}`).toBeLessThan(ARC_PER_NODE * 1.5);
    }
  });

  it("draws a prerequisite chain without a single crossing", () => {
    const nodes = [root("c1"), ...concepts(30)];
    const ids = nodes.slice(1).map((n) => n.id);
    // Linked in an order unrelated to the ids.
    const order = ids.map((id, i) => ids[(i * 7) % 30]);
    const edges = chain(order);
    const plan = planRadial(nodes, edges, W, H);
    expect(crossings(plan, edges)).toBe(0);
  });

  it("untangles a busy course a long way", () => {
    // A course like the preview's: chains, fans and cross links.
    const nodes = [root("c1"), ...concepts(30)];
    const ids = nodes.slice(1).map((n) => n.id);
    const pick = (i: number) => ids[(i * 11) % 30];
    const edges: GraphEdge[] = [
      ...chain([0, 1, 2, 3, 4, 5].map(pick)),
      ...chain([6, 7, 8, 9].map(pick)),
      ...[10, 11, 12, 13].map((i) => edge(pick(2), pick(i), "builds_on")),
      ...[14, 15, 16].map((i) => edge(pick(7), pick(i), "part_of")),
      ...[17, 18, 19, 20, 21].map((i) => related(pick(i), pick(i + 5))),
      edge(pick(4), pick(12), "prerequisite"),
      edge(pick(9), pick(15), "prerequisite"),
    ];
    const plan = planRadial(nodes, edges, W, H);
    // Seated by dependency alone, links like these crossed some 40 times.
    expect(crossings(plan, edges)).toBeLessThanOrEqual(12);
    // …and the dependency rule still holds.
    for (const e of edges) {
      if (!isDirected(e)) continue;
      expect(plan.orbit.get(e.target)!.radius).toBeGreaterThanOrEqual(plan.orbit.get(e.source)!.radius);
    }
  });

  it("only moves concepts between seats the plan made", () => {
    const nodes = [root("c1"), ...concepts(30)];
    const ids = nodes.slice(1).map((n) => n.id);
    const plain = planRadial(nodes, [], W, H);
    const linked = planRadial(nodes, chain(ids.slice(0, 15)), W, H);
    const seats = (plan: RadialPlan) =>
      [...plan.orbit.values()].map((o) => `${o.radius}`).sort();
    // The same rings, holding the same number of concepts each.
    expect(seats(linked)).toEqual(seats(plain));
  });

  it("keeps the starting concepts innermost", () => {
    const nodes = [root("c1"), ...concepts(24)];
    const ids = nodes.slice(1).map((n) => n.id);
    const edges = [...chain(ids.slice(0, 10)), ...ids.slice(11, 18).map((id) => related(ids[9], id))];
    const plan = planRadial(nodes, edges, W, H);
    const starts = [...plan.orbit.values()].filter((o) => o.depth === 0).map((o) => o.radius);
    const rest = [...plan.orbit.values()].filter((o) => o.depth > 0).map((o) => o.radius);
    expect(Math.max(...starts)).toBeLessThanOrEqual(Math.min(...rest));
  });
});

describe("reachByCourse", () => {
  it("is each course's furthest seat", () => {
    const plan = planRadial([root("c1"), root("c2"), ...concepts(30, "c1"), ...concepts(4, "c2")], [], 1240, 744);
    const reach = reachByCourse(plan.orbit);
    expect(reach.get("root-c1")).toBe(232);
    expect(reach.get("root-c2")).toBe(RING0);
    expect(reach.has("root-c3")).toBe(false);
  });

  it("groups concepts with no course under null", () => {
    const plan = planRadial(concepts(7), [], 500, 340);
    expect([...reachByCourse(plan.orbit).keys()]).toEqual([null]);
  });
});

describe("pushCoursesApart", () => {
  const course = (id: string, x: number, y: number, reach = 100, held = false) => ({ id, x, y, reach, held });

  it("leaves courses that are clear of each other alone", () => {
    expect(pushCoursesApart([course("a", 0, 0), course("b", 240, 0)], 40, 0.5).size).toBe(0);
    expect(pushCoursesApart([course("a", 0, 0)], 40, 0.5).size).toBe(0);
  });

  it("pushes two overlapping courses straight apart, half each", () => {
    // 200 apart, 240 wanted: 40 of overlap, half of it closed this step.
    const moves = pushCoursesApart([course("a", 0, 0), course("b", 200, 0)], 40, 0.5);
    expect(moves.get("a")).toEqual({ dx: -10, dy: 0 });
    expect(moves.get("b")).toEqual({ dx: 10, dy: 0 });
  });

  it("moves only the other course when one is held", () => {
    const moves = pushCoursesApart([course("a", 0, 0, 100, true), course("b", 0, 150)], 40, 0.5);
    expect(moves.has("a")).toBe(false);
    expect(moves.get("b")!.dx).toBeCloseTo(0, 9);
    expect(moves.get("b")!.dy).toBeCloseTo(45, 9);
    const other = pushCoursesApart([course("a", 0, 0), course("b", 0, 150, 100, true)], 40, 0.5);
    expect(other.has("b")).toBe(false);
    expect(other.get("a")!.dy).toBeCloseTo(-45, 9);
  });

  it("separates two courses on exactly the same spot", () => {
    const moves = pushCoursesApart([course("a", 50, 50), course("b", 50, 50)], 40, 1);
    expect(moves.get("a")!.dx).toBeLessThan(0);
    expect(moves.get("b")!.dx).toBeGreaterThan(0);
  });

  it("adds up the pushes from every course a course overlaps", () => {
    const moves = pushCoursesApart([course("a", -150, 0), course("b", 0, 0), course("c", 150, 0)], 40, 1);
    // b is pushed both ways equally: it stays.
    expect(moves.get("b")!.dx).toBeCloseTo(0, 9);
    expect(moves.get("a")!.dx).toBeLessThan(0);
    expect(moves.get("c")!.dx).toBeGreaterThan(0);
  });

  it("clears every overlap when run step after step", () => {
    let courses = [course("a", 0, 0), course("b", 30, 10), course("c", -20, 40), course("d", 10, -30)];
    for (let i = 0; i < 200; i++) {
      const moves = pushCoursesApart(courses, 40, 0.15);
      courses = courses.map((c) => ({ ...c, x: c.x + (moves.get(c.id)?.dx ?? 0), y: c.y + (moves.get(c.id)?.dy ?? 0) }));
    }
    for (let i = 0; i < courses.length; i++) {
      for (let j = i + 1; j < courses.length; j++) {
        expect(Math.hypot(courses[i].x - courses[j].x, courses[i].y - courses[j].y)).toBeGreaterThan(240 - 1);
      }
    }
  });
});

describe("planRadial — four courses of fifty", () => {
  const W = 1240;
  const H = 744;
  const courses = ["c1", "c2", "c3", "c4"];
  const nodes = [...courses.map(root), ...courses.flatMap((c) => concepts(50, c))];
  const plan = () => planRadial(nodes, [], W, H);

  it("seats each course on four rings, every concept with its own room", () => {
    const p = plan();
    for (const c of courses) {
      const radii = [...p.orbit.values()].filter((o) => o.rootId === `root-${c}`).map((o) => o.radius);
      expect(radii).toHaveLength(50);
      expect([...new Set(radii)].sort((a, b) => a - b)).toEqual([96, 164, 232, 300]);
    }
    const pts = [...p.orbit.values()].map((o) => {
      const centre = p.centers.get(o.rootId!)!;
      return { x: centre.x + Math.cos(o.angle) * o.radius, y: centre.y + Math.sin(o.angle) * o.radius };
    });
    let nearest = Infinity;
    for (let i = 0; i < pts.length; i++) {
      for (let j = i + 1; j < pts.length; j++) nearest = Math.min(nearest, Math.hypot(pts[i].x - pts[j].x, pts[i].y - pts[j].y));
    }
    expect(nearest).toBeGreaterThanOrEqual(64);
  });

  it("lays the four courses out in two rows of two, clear of each other", () => {
    const centres = [...plan().centers.values()];
    const rows = new Set(centres.map((c) => Math.round(c.y)));
    expect(rows.size).toBe(2);
    for (let i = 0; i < centres.length; i++) {
      for (let j = i + 1; j < centres.length; j++) {
        const d = Math.hypot(centres[i].x - centres[j].x, centres[i].y - centres[j].y);
        expect(d).toBeGreaterThanOrEqual(2 * (300 + COURSE_MARGIN) - 1e-6);
      }
    }
  });

  it("opens at about half size in a 1240 × 744 window", () => {
    const b = planBounds(plan(), W, H)!;
    const scale = Math.min(W / (b.maxX - b.minX), H / (b.maxY - b.minY));
    expect(scale).toBeGreaterThan(0.45);
    expect(scale).toBeLessThan(0.6);
  });
});


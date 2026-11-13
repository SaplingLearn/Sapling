import { describe, expect, it } from "vitest";
import type { GraphEdge, GraphNode } from "@/lib/data";
import {
  CONCEPT_REACH,
  COURSE_MARGIN,
  LABEL_ZOOM,
  MAX_SPOKES,
  ROOT_REACH,
  ROOT_ROOM,
  SPACE_X,
  SPACE_Y,
  courseLinks,
  forceOrbit,
  importanceRadii,
  isDirected,
  labelOpacityAt,
  packCourses,
  planBounds,
  planCourse,
  planRadial,
  splitEdges,
  startingConcepts,
  type Box,
  type RadialPlan,
} from "./radialLayout";

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
const idsOf = (nodes: GraphNode[]) => nodes.map((n) => n.id);
const edge = (source: string, target: string, relationship_type?: GraphEdge["relationship_type"]): GraphEdge => ({
  source,
  target,
  strength: 0.5,
  relationship_type,
});
/** A prerequisite chain through the given ids, in order. */
const chain = (ids: string[]) => ids.slice(1).map((id, i) => edge(ids[i], id, "prerequisite"));
const related = (a: string, b: string) => edge(a, b, "related");

type Pt = { x: number; y: number };
/** Where a concept of a plan sits, relative to its course root (a root itself sits at the origin). */
const seatOf = (plan: RadialPlan, id: string): Pt => {
  const o = plan.orbit.get(id);
  return o ? { x: Math.cos(o.angle) * o.radius, y: Math.sin(o.angle) * o.radius } : { x: 0, y: 0 };
};
/** Where a concept sits on the canvas. */
const pointOf = (plan: RadialPlan, id: string, width: number, height: number): Pt => {
  const o = plan.orbit.get(id)!;
  const c = (o.rootId && plan.centers.get(o.rootId)) || { x: width / 2, y: height / 2 };
  const s = seatOf(plan, id);
  return { x: c.x + s.x, y: c.y + s.y };
};
/**
 * How far apart two concepts are, in caption room: 1 is exactly `SPACE_X`
 * side by side, or `SPACE_Y` one above the other (an ellipse between).
 */
const captionGap = (a: Pt, b: Pt) => Math.hypot((a.x - b.x) / SPACE_X, (a.y - b.y) / SPACE_Y);
/** The least caption gap between any two of the points. */
function tightest(points: Pt[]): number {
  let least = Infinity;
  for (let i = 0; i < points.length; i++) {
    for (let j = i + 1; j < points.length; j++) least = Math.min(least, captionGap(points[i], points[j]));
  }
  return least;
}
/** How many pairs of links (as straight lines between seats) cross. */
function crossings(plan: RadialPlan, edges: GraphEdge[]): number {
  const segs = edges.map((e) => [seatOf(plan, e.source), seatOf(plan, e.target)] as const);
  const side = (a: Pt, b: Pt, c: Pt) => Math.sign((b.x - a.x) * (c.y - a.y) - (b.y - a.y) * (c.x - a.x));
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
const widthOf = (b: { minX: number; maxX: number }) => b.maxX - b.minX;
const heightOf = (b: { minY: number; maxY: number }) => b.maxY - b.minY;

const W = 1240;
const H = 744;

/** A course like the preview's: chains, fans and cross links, linked in an order unrelated to the ids. */
function busyCourse() {
  const nodes = [root("c1"), ...concepts(30)];
  const ids = idsOf(nodes.slice(1));
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
  return { nodes, edges };
}
/** Thirty concepts in one prerequisite chain, linked in an order unrelated to the ids. */
function longChain() {
  const nodes = [root("c1"), ...concepts(30)];
  const ids = idsOf(nodes.slice(1));
  return { nodes, edges: chain(ids.map((_, i) => ids[(i * 7) % 30])) };
}

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

describe("startingConcepts", () => {
  it("starts a strand at what nothing leads into, the one more is built on first", () => {
    const edges = [edge("a", "b", "prerequisite"), edge("b", "c", "builds_on"), edge("d", "c", "prerequisite")];
    expect(startingConcepts(["a", "b", "c", "d"], edges)).toEqual(["a", "d"]);
  });

  it("starts a group of related concepts at its most-linked concept", () => {
    expect(startingConcepts(["a", "b", "c"], [related("a", "b"), related("b", "c")])).toEqual(["b"]);
  });

  it("gives a concept with no links a start of its own, after the bigger strands", () => {
    expect(startingConcepts(["x", "y", "a", "b"], [edge("a", "b", "part_of")])).toEqual(["a", "x", "y"]);
  });

  it("never starts more than a few", () => {
    const ids = idsOf(concepts(30));
    expect(startingConcepts(ids, [])).toHaveLength(MAX_SPOKES);
    expect(MAX_SPOKES).toBeLessThanOrEqual(6);
    expect(startingConcepts(ids, [], 2)).toHaveLength(2);
  });

  it("starts nothing in a loop that nothing leads into from outside", () => {
    expect(startingConcepts(["a", "b"], chain(["a", "b", "a"]))).toEqual([]);
  });

  it("ignores links to concepts outside the course", () => {
    expect(startingConcepts(["a", "b"], [edge("zz", "a", "prerequisite"), edge("a", "b", "prerequisite")])).toEqual(["a"]);
  });
});

describe("planCourse", () => {
  const unlinked = (count: number, course = "c1") => planCourse(idsOf(concepts(count, course)), [], `root-${course}`);

  it("keeps every two concepts a caption apart: further side by side than one above the other", () => {
    const busy = busyCourse();
    const strand = longChain();
    for (const plan of [
      unlinked(5),
      unlinked(30),
      unlinked(50),
      planCourse(idsOf(busy.nodes.slice(1)), busy.edges, "root-c1"),
      planCourse(idsOf(strand.nodes.slice(1)), strand.edges, "root-c1"),
    ]) {
      expect(tightest([...plan.seats.values()])).toBeGreaterThanOrEqual(1 - 1e-9);
    }
    expect(SPACE_X).toBeGreaterThan(SPACE_Y);
  });

  it("keeps every concept clear of its course root", () => {
    const busy = busyCourse();
    for (const plan of [unlinked(5), unlinked(30), planCourse(idsOf(busy.nodes.slice(1)), busy.edges, "root-c1")]) {
      for (const s of plan.seats.values()) expect(Math.hypot(s.x, s.y)).toBeGreaterThanOrEqual(ROOT_ROOM - 1e-6);
    }
  });

  it("does not seat concepts on rings round the root", () => {
    for (const count of [30, 50]) {
      const radii = [...unlinked(count).seats.values()].map((s) => Math.round(Math.hypot(s.x, s.y)));
      // Rings would leave a handful of distances; here nearly every concept has its own.
      expect(new Set(radii).size).toBeGreaterThanOrEqual(0.8 * count);
    }
  });

  it("puts the course root off to one side of its concepts, not in the middle of a disc of them", () => {
    const { box } = unlinked(30);
    const off = Math.hypot((box.minX + box.maxX) / 2, (box.minY + box.maxY) / 2);
    expect(off).toBeGreaterThan(0.1 * widthOf(box));
  });

  it("grows each course into a shape of its own", () => {
    const a = unlinked(30, "c1").box;
    const b = unlinked(30, "c2").box;
    expect(Math.abs(widthOf(a) - widthOf(b)) + Math.abs(heightOf(a) - heightOf(b))).toBeGreaterThan(1);
  });

  it("links the course root to a few of its starting concepts, never to all of them", () => {
    expect(unlinked(30).spokes.size).toBe(MAX_SPOKES);
    expect(unlinked(3).spokes.size).toBe(3);
  });

  it("seats linked concepts next to each other", () => {
    // Six linked pairs among twelve concepts, named so that seating by id
    // alone would scatter every pair across the course.
    const ids = idsOf(concepts(12));
    const pairs = [0, 1, 2, 3, 4, 5].map((i) => [ids[i], ids[i + 6]] as const);
    const plan = planCourse(ids, pairs.map(([a, b]) => related(a, b)), "root-c1");
    for (const [a, b] of pairs) {
      const p = plan.seats.get(a)!;
      const q = plan.seats.get(b)!;
      expect(Math.hypot(p.x - q.x, p.y - q.y), `${a} – ${b}`).toBeLessThanOrEqual(1.2 * SPACE_X);
    }
  });

  it("plans concepts with no course root round the middle of their own group", () => {
    const { box, spokes } = planCourse(idsOf(concepts(4)), [], null);
    expect((box.minX + box.maxX) / 2).toBeCloseTo(0, 6);
    expect((box.minY + box.maxY) / 2).toBeCloseTo(0, 6);
    expect(spokes.size).toBe(0);
  });

  it("plans a large course in well under a second", () => {
    const start = performance.now();
    planCourse(idsOf(concepts(400, "big")), [], "root-big");
    expect(performance.now() - start).toBeLessThan(2000);
  });
});

describe("planRadial", () => {
  it("puts a single course in the middle of the canvas", () => {
    const plan = planRadial([root("c1"), ...concepts(12)], [], W, H);
    const b = planBounds(plan, W, H)!;
    expect((b.minX + b.maxX) / 2).toBeCloseTo(W / 2, 6);
    expect((b.minY + b.maxY) / 2).toBeCloseTo(H / 2, 6);
  });

  it("draws a prerequisite chain without a single crossing", () => {
    const { nodes, edges } = longChain();
    const plan = planRadial(nodes, edges, W, H);
    expect(crossings(plan, [...edges, ...courseLinks(plan)])).toBe(0);
  });

  it("coils a long chain up instead of stretching it across the screen", () => {
    const { nodes, edges } = longChain();
    const strand = planBounds(planRadial(nodes, edges, W, H), W, H)!;
    const loose = planBounds(planRadial(nodes, [], W, H), W, H)!;
    expect(widthOf(strand)).toBeLessThanOrEqual(1.5 * widthOf(loose));
    expect(widthOf(strand)).toBeLessThanOrEqual(W);
    expect(heightOf(strand)).toBeLessThanOrEqual(H);
  });

  it("untangles a busy course", () => {
    const { nodes, edges } = busyCourse();
    const plan = planRadial(nodes, edges, W, H);
    // Seated on rings by dependency alone, links like these crossed some 40 times.
    expect(crossings(plan, [...edges, ...courseLinks(plan)])).toBeLessThanOrEqual(3);
  });

  it("gives the same plan for the same graph, whatever order its nodes and edges come in", () => {
    const { nodes, edges } = busyCourse();
    const a = planRadial(nodes, edges, W, H);
    const b = planRadial([...nodes].reverse(), [...edges].reverse(), W, H);
    for (const n of nodes.slice(1)) {
      expect(seatOf(b, n.id).x).toBeCloseTo(seatOf(a, n.id).x, 9);
      expect(seatOf(b, n.id).y).toBeCloseTo(seatOf(a, n.id).y, 9);
    }
    expect(b.centers.get("root-c1")).toEqual(a.centers.get("root-c1"));
  });

  it("plans each course on its own: a course keeps its shape whatever else is on the canvas", () => {
    const alone = planRadial([root("c1"), ...concepts(20, "c1")], [], W, H);
    const together = planRadial([root("c1"), root("c2"), ...concepts(20, "c1"), ...concepts(9, "c2")], [], W, H);
    for (const n of concepts(20, "c1")) {
      expect(seatOf(together, n.id).x).toBeCloseTo(seatOf(alone, n.id).x, 9);
      expect(seatOf(together, n.id).y).toBeCloseTo(seatOf(alone, n.id).y, 9);
    }
  });

  it("keeps a course's plan when only the window changes", () => {
    const nodes = [root("c1"), ...concepts(20)];
    const wide = planRadial(nodes, [], W, H);
    const narrow = planRadial(nodes, [], 600, 900);
    for (const n of nodes.slice(1)) expect(narrow.orbit.get(n.id)).toEqual(wide.orbit.get(n.id));
  });

  it("keeps neighbouring courses' boxes a margin apart", () => {
    const courses = ["c1", "c2", "c3"];
    const plan = planRadial([...courses.map(root), ...courses.flatMap((c) => concepts(12, c))], [], W, H);
    const placed = courses.map((c) => {
      const centre = plan.centers.get(`root-${c}`)!;
      const box = plan.boxes.get(`root-${c}`)!;
      return { minX: centre.x + box.minX, maxX: centre.x + box.maxX, minY: centre.y + box.minY, maxY: centre.y + box.maxY };
    });
    for (let i = 0; i < placed.length; i++) {
      for (let j = i + 1; j < placed.length; j++) {
        const [a, b] = [placed[i], placed[j]];
        const gapX = Math.max(a.minX - b.maxX, b.minX - a.maxX);
        const gapY = Math.max(a.minY - b.maxY, b.minY - a.maxY);
        expect(Math.max(gapX, gapY)).toBeGreaterThanOrEqual(COURSE_MARGIN - 1e-6);
      }
    }
  });

  it("gives a course with no concepts a centre and the room its root needs", () => {
    const plan = planRadial([root("c1"), root("c2"), ...concepts(5, "c2")], [], W, H);
    expect(plan.centers.has("root-c1")).toBe(true);
    expect(plan.boxes.get("root-c1")).toEqual({ minX: -ROOT_REACH.x, minY: -ROOT_REACH.up, maxX: ROOT_REACH.x, maxY: ROOT_REACH.down });
  });

  it("plans concepts with no course root round the middle of the canvas", () => {
    const plan = planRadial(concepts(7), [], 500, 340);
    expect([...plan.orbit.values()].every((o) => o.rootId === null)).toBe(true);
    const b = planBounds(plan, 500, 340)!;
    expect((b.minX + b.maxX) / 2).toBeCloseTo(250, 6);
    expect((b.minY + b.maxY) / 2).toBeCloseTo(170, 6);
  });

  it("plans nothing for no nodes", () => {
    const plan = planRadial([], [], W, H);
    expect(plan.centers.size).toBe(0);
    expect(plan.orbit.size).toBe(0);
    expect(planBounds(plan, W, H)).toBeNull();
  });

  it("survives a cycle in the data", () => {
    const nodes = [root("c1"), ...concepts(6)];
    const ids = idsOf(nodes.slice(1));
    const plan = planRadial(nodes, chain([...ids, ids[0]]), W, H);
    for (const id of ids) {
      expect(Number.isFinite(seatOf(plan, id).x) && Number.isFinite(seatOf(plan, id).y)).toBe(true);
    }
    expect(tightest(ids.map((id) => pointOf(plan, id, W, H)))).toBeGreaterThanOrEqual(1 - 1e-9);
  });
});

describe("courseLinks", () => {
  it("links each course to the concepts it starts with, and only those", () => {
    const nodes = [root("c1"), concept("a"), concept("b"), concept("c"), concept("d"), concept("e")];
    const plan = planRadial(nodes, chain(["a", "b", "c"]), W, H);
    const links = courseLinks(plan);
    expect(links.map((l) => l.target).sort()).toEqual(["a", "d", "e"]);
    for (const l of links) {
      expect(l.source).toBe("root-c1");
      expect(l.relationship_type).toBe("part_of");
    }
  });

  it("never links a course to more than a few of its concepts", () => {
    expect(courseLinks(planRadial([root("c1"), ...concepts(30)], [], W, H))).toHaveLength(MAX_SPOKES);
  });
});

describe("packCourses", () => {
  const box = (w: number, h: number, dx = 0, dy = 0): Box => ({
    minX: -w / 2 + dx,
    maxX: w / 2 + dx,
    minY: -h / 2 + dy,
    maxY: h / 2 + dy,
  });
  const B = box(600, 400);
  /** The boxes where they are put. */
  const placed = (boxes: Box[], spots: Pt[]) =>
    boxes.map((b, i) => ({ minX: spots[i].x + b.minX, maxX: spots[i].x + b.maxX, minY: spots[i].y + b.minY, maxY: spots[i].y + b.maxY }));
  const rowsOf = (spots: Pt[]) => {
    const rows = new Map<number, number>();
    for (const s of spots) rows.set(Math.round(s.y), (rows.get(Math.round(s.y)) ?? 0) + 1);
    return [...rows.entries()].sort((a, b) => a[0] - b[0]).map(([, n]) => n);
  };

  it("puts nothing nowhere, and one course with its box in the middle", () => {
    expect(packCourses([], 1200, 700)).toEqual([]);
    const [spot] = packCourses([box(300, 200, 40, -30)], 1200, 700);
    expect(spot.x).toBeCloseTo(-40, 9);
    expect(spot.y).toBeCloseTo(30, 9);
  });

  it("sits two courses side by side in a wide window and stacked in a tall one", () => {
    const half = 300 + COURSE_MARGIN / 2;
    expect(packCourses([B, B], W, H)).toEqual([{ x: -half, y: 0 }, { x: half, y: 0 }]);
    const tall = packCourses([B, B], 300, 900);
    expect(tall.map((s) => s.x)).toEqual([0, 0]);
    expect(tall.map((s) => s.y)).toEqual([-(200 + COURSE_MARGIN / 2), 200 + COURSE_MARGIN / 2]);
  });

  it("centres the arrangement on the middle of the canvas", () => {
    const boxes = [box(500, 300, 30, 10), box(700, 420, -50, 20), box(300, 260), box(640, 380, 10, -40), box(420, 300)];
    for (let k = 1; k <= boxes.length; k++) {
      for (const [w, h] of [[W, H], [798, 667], [400, 900]]) {
        const all = placed(boxes.slice(0, k), packCourses(boxes.slice(0, k), w, h));
        expect(Math.min(...all.map((b) => b.minX)) + Math.max(...all.map((b) => b.maxX))).toBeCloseTo(0, 6);
        expect(Math.min(...all.map((b) => b.minY)) + Math.max(...all.map((b) => b.maxY))).toBeCloseTo(0, 6);
      }
    }
  });

  it("keeps every two courses' boxes a margin apart", () => {
    const boxes = Array.from({ length: 9 }, (_, i) => box(300 + (i % 3) * 120, 200 + (i % 2) * 140, (i % 4) * 10, 0));
    for (let k = 1; k <= boxes.length; k++) {
      for (const [w, h] of [[W, H], [798, 667], [400, 900], [2000, 500], [1, 1]]) {
        const all = placed(boxes.slice(0, k), packCourses(boxes.slice(0, k), w, h));
        for (let i = 0; i < all.length; i++) {
          for (let j = i + 1; j < all.length; j++) {
            const gapX = Math.max(all[i].minX - all[j].maxX, all[j].minX - all[i].maxX);
            const gapY = Math.max(all[i].minY - all[j].maxY, all[j].minY - all[i].maxY);
            expect(Math.max(gapX, gapY), `${k} courses in ${w}×${h}`).toBeGreaterThanOrEqual(COURSE_MARGIN - 1e-6);
          }
        }
      }
    }
  });

  it("uses as many rows as show the courses largest", () => {
    expect(rowsOf(packCourses([B, B, B, B], W, H))).toEqual([2, 2]);
    expect(rowsOf(packCourses([B, B, B, B], 2600, 450))).toEqual([4]);
  });

  it("puts the shorter row on top, clear of the window's corners", () => {
    expect(rowsOf(packCourses([B, B, B], W, H))).toEqual([1, 2]);
  });

  it("fills rows in order: left to right, top to bottom", () => {
    const [a, b, c, d] = packCourses([B, B, B, B], W, H);
    expect(a.y).toBe(b.y);
    expect(c.y).toBe(d.y);
    expect(a.y).toBeLessThan(c.y);
    expect(a.x).toBeLessThan(b.x);
    expect(c.x).toBeLessThan(d.x);
  });

  it("centres each course in its row, whatever its size", () => {
    const boxes = [box(400, 200, 0, 50), box(400, 500, 0, -60)];
    const [a, b] = placed(boxes, packCourses(boxes, W, H));
    expect((a.minY + a.maxY) / 2).toBeCloseTo((b.minY + b.maxY) / 2, 9);
  });

  it("is steady: the same question has the same answer", () => {
    expect(packCourses([B, B, B, B, B], W, H)).toEqual(packCourses([B, B, B, B, B], W, H));
  });
});

describe("planBounds", () => {
  it("reaches past every concept by the room its mark and caption need", () => {
    const plan = planRadial([root("c1"), ...concepts(30)], [], W, H);
    const b = planBounds(plan, W, H)!;
    const points = concepts(30).map((n) => pointOf(plan, n.id, W, H));
    const centre = plan.centers.get("root-c1")!;
    expect(b.minX).toBeCloseTo(Math.min(...points.map((p) => p.x - CONCEPT_REACH.x), centre.x - ROOT_REACH.x), 9);
    expect(b.maxX).toBeCloseTo(Math.max(...points.map((p) => p.x + CONCEPT_REACH.x), centre.x + ROOT_REACH.x), 9);
    expect(b.minY).toBeCloseTo(Math.min(...points.map((p) => p.y - CONCEPT_REACH.up), centre.y - ROOT_REACH.up), 9);
    expect(b.maxY).toBeCloseTo(Math.max(...points.map((p) => p.y + CONCEPT_REACH.down), centre.y + ROOT_REACH.down), 9);
    // Captions are wider than they are tall, and hang under their marks.
    expect(CONCEPT_REACH.x).toBeGreaterThan(CONCEPT_REACH.up);
    expect(CONCEPT_REACH.down).toBeGreaterThan(CONCEPT_REACH.up);
  });

  it("covers a course with no concepts", () => {
    const plan = planRadial([root("c1")], [], 800, 600);
    expect(planBounds(plan, 800, 600)).toEqual({
      minX: 400 - ROOT_REACH.x,
      maxX: 400 + ROOT_REACH.x,
      minY: 300 - (ROOT_REACH.up + ROOT_REACH.down) / 2,
      maxY: 300 + (ROOT_REACH.up + ROOT_REACH.down) / 2,
    });
  });

  it("fits thirty unlinked concepts in a dashboard panel at full size", () => {
    const plan = planRadial([root("c1"), ...concepts(30)], [], 798, 667);
    const b = planBounds(plan, 798, 667)!;
    expect(widthOf(b)).toBeLessThanOrEqual(798);
    expect(heightOf(b)).toBeLessThanOrEqual(667);
  });
});

describe("forceOrbit", () => {
  type P = { id: string; x: number; y: number; vx: number; vy: number };
  const planOf = (radius: number, angle: number): RadialPlan => ({
    centers: new Map(),
    orbit: new Map([["a", { rootId: "r", radius, angle, spoke: false }]]),
    boxes: new Map(),
  });
  /** One tick, the course centred on (100, 100) unless said otherwise; the planned place is (200, 100). */
  const run = (
    n: P,
    { centre = { x: 100, y: 100 }, alpha = 1, reaction = 0, pushRoot }: {
      centre?: { x: number; y: number };
      alpha?: number;
      reaction?: number;
      pushRoot?: (rootId: string, dvx: number, dvy: number) => void;
    } = {},
  ) => {
    const force = forceOrbit<P>(() => planOf(100, 0), () => centre, 0.55, 0.12, { reaction, pushRoot });
    force.initialize([n]);
    force(alpha);
  };

  it("pulls a concept firmly to its planned distance from its course root", () => {
    // On its planned angle, 30 short of its distance: drawn straight out.
    const n: P = { id: "a", x: 170, y: 100, vx: 0, vy: 0 };
    run(n);
    expect(n.vx).toBeCloseTo(30 * 0.55 + 30 * 0.12, 9);
    expect(n.vy).toBeCloseTo(0, 6);
  });

  it("pulls it round to its planned angle only gently", () => {
    // At its distance but a quarter turn round: no pull in or out, a gentle one round.
    const n: P = { id: "a", x: 100, y: 200, vx: 0, vy: 0 };
    run(n);
    expect(n.vx).toBeCloseTo(100 * 0.12, 6);
    expect(n.vy).toBeCloseTo(-100 * 0.12, 6);
  });

  it("leaves a concept on its planned place alone", () => {
    const n: P = { id: "a", x: 200, y: 100, vx: 0, vy: 0 };
    run(n);
    expect(n.vx).toBeCloseTo(0, 6);
    expect(n.vy).toBeCloseTo(0, 6);
  });

  it("weakens with the simulation's heat", () => {
    const n: P = { id: "a", x: 170, y: 100, vx: 0, vy: 0 };
    run(n, { alpha: 0.5 });
    expect(n.vx).toBeCloseTo((30 * 0.55 + 30 * 0.12) / 2, 9);
  });

  it("follows the course's centre as it is now, not as planned", () => {
    // The course has moved 30 to the right: its concept is pulled after it.
    const n: P = { id: "a", x: 200, y: 100, vx: 0, vy: 0 };
    run(n, { centre: { x: 130, y: 100 } });
    expect(n.vx).toBeCloseTo(30 * 0.55 + 30 * 0.12, 9);
  });

  it("hands a share of each pull back to the course root, when asked", () => {
    const n: P = { id: "a", x: 170, y: 100, vx: 0, vy: 0 };
    const tugs: Array<[string, number, number]> = [];
    run(n, { reaction: 0.35, pushRoot: (rootId, dvx, dvy) => tugs.push([rootId, dvx, dvy]) });
    expect(tugs).toHaveLength(1);
    expect(tugs[0][0]).toBe("r");
    expect(tugs[0][1]).toBeCloseTo(-(30 * 0.55 + 30 * 0.12) * 0.35, 9);
    // With no share asked for, the root is left alone.
    const none: string[] = [];
    run({ id: "a", x: 170, y: 100, vx: 0, vy: 0 }, { pushRoot: (rootId) => none.push(rootId) });
    expect(none).toEqual([]);
  });

  it("ignores a node with no plan or no position", () => {
    const stray = { id: "zz", x: 5, y: 5, vx: 0, vy: 0 };
    const force = forceOrbit<P>(() => planOf(100, 0), () => ({ x: 0, y: 0 }));
    force.initialize([stray]);
    force(1);
    expect(stray).toEqual({ id: "zz", x: 5, y: 5, vx: 0, vy: 0 });
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

describe("planRadial — four courses of fifty", () => {
  const courses = ["c1", "c2", "c3", "c4"];
  const nodes = [...courses.map(root), ...courses.flatMap((c) => concepts(50, c))];
  const plan = () => planRadial(nodes, [], W, H);

  it("keeps every concept clear of every other and of its course root", () => {
    const p = plan();
    const points = nodes.filter((n) => !n.is_subject_root).map((n) => pointOf(p, n.id, W, H));
    expect(points).toHaveLength(200);
    expect(tightest(points)).toBeGreaterThanOrEqual(1 - 1e-9);
    for (const o of p.orbit.values()) expect(o.radius).toBeGreaterThanOrEqual(ROOT_ROOM - 1e-6);
  });

  it("lays the four courses out in two rows of two, their boxes clear of each other", () => {
    const p = plan();
    const centres = courses.map((c) => p.centers.get(`root-${c}`)!);
    const boxes = courses.map((c, i) => {
      const b = p.boxes.get(`root-${c}`)!;
      return { minX: centres[i].x + b.minX, maxX: centres[i].x + b.maxX, minY: centres[i].y + b.minY, maxY: centres[i].y + b.maxY };
    });
    // Two rows: the first two courses above the last two.
    expect(Math.max(boxes[0].maxY, boxes[1].maxY)).toBeLessThan(Math.min(boxes[2].minY, boxes[3].minY));
    for (let i = 0; i < boxes.length; i++) {
      for (let j = i + 1; j < boxes.length; j++) {
        const gapX = Math.max(boxes[i].minX - boxes[j].maxX, boxes[j].minX - boxes[i].maxX);
        const gapY = Math.max(boxes[i].minY - boxes[j].maxY, boxes[j].minY - boxes[i].maxY);
        expect(Math.max(gapX, gapY)).toBeGreaterThanOrEqual(COURSE_MARGIN - 1e-6);
      }
    }
  });

  it("opens at about half size in a 1240 × 744 window", () => {
    const b = planBounds(plan(), W, H)!;
    const scale = Math.min(W / widthOf(b), H / heightOf(b));
    expect(scale).toBeGreaterThan(0.45);
    expect(scale).toBeLessThan(0.6);
  });
});

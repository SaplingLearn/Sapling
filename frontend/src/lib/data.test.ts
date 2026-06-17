import { describe, expect, it } from "vitest";
import { apiToGraphNode, hashSeed, paletteFor } from "./data";
import type { GraphNode as ApiNode } from "./types";
import type { EnrolledCourse } from "./api";

function makeApiNode(over: Partial<ApiNode> = {}): ApiNode {
  return {
    id: "n1",
    concept_name: "Eigenvalues",
    mastery_score: 0.5,
    mastery_tier: "learning",
    times_studied: 3,
    last_studied_at: null,
    subject: "Linear Algebra",
    course_id: "c1",
    course_color: null,
    color: null,
    is_subject_root: false,
    ...over,
  };
}

function makeCourse(over: Partial<EnrolledCourse> = {}): EnrolledCourse {
  return {
    enrollment_id: "e1",
    course_id: "c1",
    course_code: "MATH 242",
    course_name: "Linear Algebra",
    school: "BU",
    department: "MATH",
    color: null,
    nickname: null,
    node_count: 8,
    enrolled_at: "2026-01-01",
    ...over,
  };
}

// First entry of COURSE_PALETTE in data.ts. Asserted directly so the
// palette stays internal to data.ts. (Darkened sage — chosen to clear
// WCAG AA 3:1 contrast against the cream `--bg`.)
const PALETTE_FIRST = "#7a874f";

describe("paletteFor", () => {
  it("returns the first palette entry for empty / nullish seeds", () => {
    expect(paletteFor(null)).toBe(PALETTE_FIRST);
    expect(paletteFor(undefined)).toBe(PALETTE_FIRST);
    expect(paletteFor("")).toBe(PALETTE_FIRST);
  });

  it("is deterministic for a given seed", () => {
    expect(paletteFor("course-42")).toBe(paletteFor("course-42"));
  });

  it("produces multiple distinct outputs across varied seeds", () => {
    const colors = new Set(["alpha", "beta", "gamma", "delta"].map(paletteFor));
    expect(colors.size).toBeGreaterThanOrEqual(2);
  });

  it("always returns a defined #RRGGBB color, even for negative-raw-hash seeds", () => {
    // "overflow10"'s raw DJB2 hash is a NEGATIVE 32-bit int (-2114666079).
    // Under the buggy `Math.abs(h)` path this could index out of range
    // (and at exactly -2^31, `Math.abs` stays negative). The `>>> 0`
    // unsigned coercion guarantees an in-range, defined palette color.
    const color = paletteFor("overflow10");
    expect(color).toBeDefined();
    expect(color).toMatch(/^#[0-9a-f]{6}$/);
  });
});

describe("apiToGraphNode color resolution", () => {
  it("prefers n.course_color over everything else", () => {
    const n = makeApiNode({ course_color: "#abcdef" });
    const course = makeCourse({ color: "#fedcba" });
    expect(apiToGraphNode(n, [course]).color).toBe("#abcdef");
  });

  it("falls back to course?.color when course_color is missing", () => {
    const n = makeApiNode({ course_color: null });
    const course = makeCourse({ color: "#123456" });
    expect(apiToGraphNode(n, [course]).color).toBe("#123456");
  });

  it("falls back to paletteFor when both course_color and course.color are missing", () => {
    const n = makeApiNode({ course_color: null, course_id: "c1" });
    const course = makeCourse({ color: null, course_id: "c1" });
    expect(apiToGraphNode(n, [course]).color).toBe(paletteFor("c1"));
  });

  it("seeds palette from course.course_id, not n.course_id (round-2 fix)", () => {
    // Round 2 fixed a bug where two nodes in the same family could
    // hash to different palette colors if some carried n.course_id
    // and others fell through to subject. The hoisted adapter must
    // prefer the course-record id so all family members agree.
    const n = makeApiNode({
      course_color: null,
      course_id: "different-from-course",
    });
    const course = makeCourse({ color: null, course_id: "stable-family-id" });
    expect(apiToGraphNode(n, [course]).color).toBe(paletteFor("stable-family-id"));
  });

  it("remaps subject_root tier to mastered", () => {
    const n = makeApiNode({ mastery_tier: "subject_root", is_subject_root: true });
    expect(apiToGraphNode(n, []).mastery_tier).toBe("mastered");
  });
});

describe("hashSeed", () => {
  it("is deterministic", () => {
    expect(hashSeed("hello")).toBe(hashSeed("hello"));
  });

  it("returns a non-negative integer for typical inputs", () => {
    for (const s of ["", "x", "concept-1", "a longer string with spaces"]) {
      const h = hashSeed(s);
      expect(Number.isInteger(h)).toBe(true);
      expect(h).toBeGreaterThanOrEqual(0);
    }
  });

  it("returns a non-negative integer even when the raw 32-bit hash is negative", () => {
    // OVERFLOW REGRESSION GUARD. The naive implementation did
    // `return Math.abs(h)` where `h` is a `| 0` 32-bit int. That is
    // broken at exactly INT_MIN (-2^31), whose magnitude has no positive
    // 32-bit counterpart — `Math.abs(-2147483648) === -2147483648` stays
    // NEGATIVE, yielding a negative array index and an `undefined` color.
    //
    // "overflow10" hashes to -2114666079 (negative raw 32-bit). We assert
    // the unsigned-coerced result is a non-negative integer and that the
    // downstream palette lookup is in-range and defined — a test the
    // buggy `Math.abs` path would fail for the INT_MIN class of seeds.
    const h = hashSeed("overflow10");
    expect(Number.isInteger(h)).toBe(true);
    expect(h).toBeGreaterThanOrEqual(0);
    // `>>> 0` guarantees the full unsigned 32-bit range.
    expect(h).toBe(2180301217);
    expect(paletteFor("overflow10")).toBeDefined();
    expect(paletteFor("overflow10")).toMatch(/^#[0-9a-f]{6}$/);
  });
});

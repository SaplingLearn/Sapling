import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";
import type { GraphNode } from "@/lib/data";
import { PEN_NATIVE_GRAPH_REFERENCE } from "./penNativeGraphSource";
import {
  buildPenGraphLayout, createPenGraphFixture, penBranchFor,
  PEN_GRAPH_REFERENCE, PEN_GRAPH_SOURCE_NODES, PEN_GRAPH_SOURCE_EDGES,
} from "./penGraphGeometry";

const node = (id: string, overrides: Partial<GraphNode> = {}): GraphNode => ({
  id, name: "Same name", subject: "Real course", color: "#ff00ff",
  course_id: "course-1", mastery_score: 0.3, mastery_tier: "learning", ...overrides,
});
const graph = {
  nodes: [node("root", { is_subject_root: true }), node("a"), node("b"), node("c"), node("isolated")],
  edges: [{ source: "root", target: "a", strength: 0.7 }, { source: "a", target: "b", strength: 0.5 }, { source: "a", target: "c", strength: 1 }],
};

const positions = (nodes: ReturnType<typeof buildPenGraphLayout>["nodes"]) => nodes.map(({ id, x, y, r, sourceId }) => ({ id, x, y, r, sourceId }));

describe("canonical Pen geometry", () => {
  it("retains the canonical source SVG hash, 74 paths, and all 21 gradients", () => {
    const svg = readFileSync(path.join(process.cwd(), "public/design/sapling/graph-reference.svg"), "utf8");
    expect(createHash("sha256").update(svg).digest("hex")).toBe(PEN_GRAPH_REFERENCE.sha256);
    const paths = [...svg.matchAll(/<path\s+([^>]+)>/g)].map((match) => match[1]);
    expect(paths).toHaveLength(74);
    expect(PEN_GRAPH_REFERENCE.paths).toHaveLength(74);
    expect(new Set(PEN_GRAPH_REFERENCE.paths.map((p) => p.sourceId)).size).toBe(74);
    paths.forEach((attributes, index) => {
      const source = PEN_GRAPH_REFERENCE.paths[index];
      expect(attributes.match(/\bd="([^"]+)"/)?.[1]).toBe(source.d);
      expect(attributes.match(/\bfill="([^"]+)"/)?.[1]).toBe("fill" in source ? source.fill : undefined);
      expect(attributes.match(/\bstroke="([^"]+)"/)?.[1]).toBe("stroke" in source ? source.stroke : undefined);
      expect(attributes.match(/\bstroke-width="([^"]+)"/)?.[1]).toBe("strokeWidth" in source ? String(source.strokeWidth) : undefined);
    });
    expect([...svg.matchAll(/<linearGradient\b/g)]).toHaveLength(21);
    expect(PEN_GRAPH_REFERENCE.gradients).toHaveLength(21);
    expect(svg).not.toMatch(/<image|data:image/i);
  });

  it("keeps every authored source coordinate and original branch in the explicit fixture", () => {
    const fixture = createPenGraphFixture();
    const layout = buildPenGraphLayout(fixture, { referenceFixture: true });
    expect(layout).toMatchObject({ width: 893, height: 601 });
    expect(layout.nodes).toHaveLength(22);
    expect(layout.edges).toHaveLength(21);
    PEN_GRAPH_SOURCE_NODES.forEach((source, i) => {
      const nativeIndex = PEN_NATIVE_GRAPH_REFERENCE.paths.findIndex((p) => p.sourceId === source.sourceId);
      expect(layout.nodes[i]).toMatchObject({
        x: source.x, y: source.y, r: source.r, sourceId: source.sourceId,
        fillPath: PEN_NATIVE_GRAPH_REFERENCE.paths[nativeIndex].d,
        fillTransform: PEN_NATIVE_GRAPH_REFERENCE.paths[nativeIndex].transform,
        outlinePath: PEN_NATIVE_GRAPH_REFERENCE.paths[nativeIndex + 1].d,
        outlineTransform: PEN_NATIVE_GRAPH_REFERENCE.paths[nativeIndex + 1].transform,
        shapeTransform: "translate(0 0)",
      });
    });
    PEN_GRAPH_SOURCE_EDGES.forEach((source, i) => {
      expect(layout.edges[i]).toMatchObject({ sourceId: source.sourceId, d: source.d, transform: "matrix(1 0 0 1 0 0)", strokeWidth: 7 });
      expect(layout.edges[i].gradient.from).toBe(source.gradient.stops[0].color);
      expect(layout.edges[i].gradient.to).toBe(source.gradient.stops[1].color);
    });
  });

  it("requires explicit fixture IDs and topology before applying source positions", () => {
    expect(() => buildPenGraphLayout(graph, { referenceFixture: true })).toThrow(/fixture IDs/);
    const fixture = createPenGraphFixture();
    fixture.edges[0] = { source: fixture.nodes[0].id, target: fixture.nodes[1].id, strength: 1 };
    expect(() => buildPenGraphLayout(fixture, { referenceFixture: true })).toThrow(/topology/);
  });
});

describe("live Pen graph adaptation", () => {
  it("retains real IDs, duplicate names, isolated nodes and every valid edge without manufacturing sample data", () => {
    const data = {
      nodes: [...graph.nodes, node("other-a", { course_id: "course-2" })],
      edges: [...graph.edges, { source: "b", target: "other-a", strength: 0.2 }, { source: "missing", target: "a", strength: 1 }],
    };
    const layout = buildPenGraphLayout(data);
    expect(layout.nodes.map((n) => n.id).sort()).toEqual(data.nodes.map((n) => n.id).sort());
    expect(layout.nodes.every((n) => n.name === "Same name")).toBe(true);
    expect(layout.edges.map(({ source, target }) => [source, target]).sort()).toEqual(data.edges.slice(0, -1).map(({ source, target }) => [source, target]).sort());
    expect(layout.nodes.some((n) => n.id.startsWith("pen-fixture:"))).toBe(false);
    expect(new Set(layout.edges.map((e) => e.id)).size).toBe(data.edges.length - 1);
    expect(layout.nodes.find((n) => n.id === "root")?.r).toBe(53.5);
  });

  it("keeps geometry stable across input reordering and mastery updates", () => {
    const baseline = buildPenGraphLayout(graph);
    const reordered = buildPenGraphLayout({ nodes: [...graph.nodes].reverse(), edges: [...graph.edges].reverse() });
    expect(reordered).toEqual(baseline);
    const updated = buildPenGraphLayout({
      nodes: graph.nodes.map((n) => ({ ...n, mastery_score: 0.99, mastery_tier: "mastered" as const, color: "#000000" })),
      edges: graph.edges,
    });
    expect(positions(updated.nodes)).toEqual(positions(baseline.nodes));
    expect(updated.edges.map((e) => [e.d, e.transform])).toEqual(baseline.edges.map((e) => [e.d, e.transform]));
    expect(updated.edges.find((e) => e.source === "a")?.gradient.from).toBe("#A3B06D");
  });

  it("preserves repeated valid relationships with unique renderer keys", () => {
    const layout = buildPenGraphLayout({ nodes: graph.nodes, edges: [graph.edges[0], graph.edges[0]] });
    expect(layout.edges).toHaveLength(2);
    expect(new Set(layout.edges.map((e) => e.id)).size).toBe(2);
  });

  it("fits dense multi-course data, including courses without hubs, with finite and nonoverlapping marks", () => {
    const nodes = Array.from({ length: 90 }, (_, i) => node(`node-${String(i).padStart(3, "0")}`, {
      course_id: `course-${Math.floor(i / 30)}`,
      is_subject_root: i % 30 === 0 && i < 60,
    }));
    const edges = nodes.slice(1).map((n, i) => ({ source: nodes[i].id, target: n.id, strength: 0.5 }));
    const layout = buildPenGraphLayout({ nodes, edges });
    expect(layout.nodes).toHaveLength(90);
    expect(layout.edges).toHaveLength(89);
    for (const n of layout.nodes) {
      expect(Number.isFinite(n.x) && Number.isFinite(n.y)).toBe(true);
      expect(n.x - n.r).toBeGreaterThanOrEqual(0);
      expect(n.y - n.r).toBeGreaterThanOrEqual(0);
      expect(n.x + n.r).toBeLessThan(layout.width);
      expect(n.y + n.r).toBeLessThan(layout.height);
      for (const other of layout.nodes.filter((p) => p.id > n.id)) {
        expect(Math.hypot(n.x - other.x, n.y - other.y)).toBeGreaterThan(n.r + other.r);
      }
    }
  });

  it("packs five actual course families compactly without moving their authored internal positions", () => {
    const counts = [3, 5, 0, 4, 2];
    const nodes = counts.flatMap((count, courseIndex) => [
      node(`root-${courseIndex}`, { course_id: `course-${courseIndex}`, is_subject_root: true }),
      ...Array.from({ length: count }, (_, i) => node(`course-${courseIndex}-concept-${i}`, { course_id: `course-${courseIndex}` })),
    ]);
    const edges = nodes.filter((n) => !n.is_subject_root).map((n) => ({ source: `root-${n.course_id.slice(-1)}`, target: n.id, strength: 0.7 }));
    const layout = buildPenGraphLayout({ nodes, edges });
    expect(layout.nodes).toHaveLength(19);
    expect(layout.edges).toHaveLength(14);
    // The live 703 × 473 overview previously scaled these marks to 0.282.
    // Compact course bounds preserve at least 0.6, without viewport inputs.
    const fitScale = Math.min(703 / layout.width, 473 / layout.height);
    expect(fitScale).toBeGreaterThanOrEqual(0.6);
    for (const [courseIndex] of counts.entries()) {
      const isolated = buildPenGraphLayout({ nodes: nodes.filter((n) => n.course_id === `course-${courseIndex}`), edges: edges.filter((e) => e.source === `root-${courseIndex}`) });
      const packedRoot = layout.nodes.find((n) => n.id === `root-${courseIndex}`)!;
      const sameCourseRoot = isolated.nodes.find((n) => n.is_subject_root)!;
      // Compare source-space relative offsets. The right-hand authored family
      // has different original positions, so compare each mark to its preset.
      for (const packed of layout.nodes.filter((n) => n.course_id === `course-${courseIndex}`)) {
        const preset = PEN_GRAPH_SOURCE_NODES.find((p) => p.sourceId === packed.sourceId)!;
        const rootPreset = PEN_GRAPH_SOURCE_NODES.find((p) => p.sourceId === packedRoot.sourceId)!;
        expect(packed.x - packedRoot.x).toBeCloseTo(preset.x - rootPreset.x, 5);
        expect(packed.y - packedRoot.y).toBeCloseTo(preset.y - rootPreset.y, 5);
      }
      expect(sameCourseRoot.r).toBe(packedRoot.r);
    }
    expect(positions(buildPenGraphLayout({ nodes: [...nodes].reverse(), edges: [...edges].reverse() }).nodes)).toEqual(positions(layout.nodes));
  });

  it("has a truthful empty graph and finite self-edge geometry", () => {
    expect(buildPenGraphLayout({ nodes: [], edges: [] })).toEqual({ nodes: [], edges: [], width: 893, height: 601 });
    const branch = penBranchFor({ x: 50, y: 80, r: 25 }, { x: 50, y: 80, r: 25 });
    expect(branch.transform).not.toMatch(/NaN|Infinity/);
    expect(branch.d).toBe(PEN_GRAPH_SOURCE_EDGES[0].d);
  });

  it("projects the source contour exactly to endpoint boundaries while preserving a uniform transform", () => {
    const branch = penBranchFor({ x: 100, y: 100, r: 25, mastery_tier: "learning" }, { x: 300, y: 100, r: 15, mastery_tier: "struggling" });
    const matrix = branch.transform.match(/matrix\(([^)]+)\)/)![1].split(" ").map(Number);
    const apply = (x: number, y: number) => [matrix[0] * x + matrix[2] * y + matrix[4], matrix[1] * x + matrix[3] * y + matrix[5]];
    const template = PEN_GRAPH_SOURCE_EDGES[0];
    const start = apply(template.start[0], template.start[1]);
    const end = apply(template.end[0], template.end[1]);
    expect(start[0]).toBeCloseTo(125, 3);
    expect(start[1]).toBeCloseTo(100, 3);
    expect(end[0]).toBeCloseTo(285, 3);
    expect(end[1]).toBeCloseTo(100, 3);
    expect(matrix[0]).toBe(matrix[3]);
    expect(matrix[1]).toBe(-matrix[2]);
    expect(branch.gradient).toMatchObject({ from: "#EF908F", to: "#FCC98A" });
    expect(branch.projectionScale).toBeCloseTo(Math.hypot(matrix[0], matrix[1]), 5);
    expect(branch.gradient.transform).toMatch(/^matrix\(/);
  });
});


describe("current native Pen paint authority", () => {
  it("retains all native local paths, viewport transforms and native asset hash", () => {
    const svg = readFileSync(path.join(process.cwd(), "public/design/sapling/graph-pen-reference.svg"), "utf8");
    expect(createHash("sha256").update(svg).digest("hex")).toBe(PEN_NATIVE_GRAPH_REFERENCE.sha256);
    const paths = [...svg.matchAll(/<path\s+([^>]+)>/g)].map((match) => match[1]);
    expect(paths).toHaveLength(74);
    PEN_NATIVE_GRAPH_REFERENCE.paths.forEach((source, i) => {
      expect(paths[i].match(/\bd="([^"]+)"/)?.[1]).toBe(source.d);
      expect(svg).toContain(`transform="${source.transform}"`);
      expect(source.sourceId).toBe(PEN_GRAPH_REFERENCE.paths[i].sourceId);
    });
    expect(svg).not.toMatch(/<image|data:image/i);
  });

  it("keeps all 21 native gradients in normalized object space before scaling bounds", () => {
    expect(PEN_NATIVE_GRAPH_REFERENCE.gradients).toHaveLength(21);
    for (const gradient of PEN_NATIVE_GRAPH_REFERENCE.gradients) {
      const paint = gradient.nativePaint;
      const theta = paint.rotation * Math.PI / 180;
      const half = paint.size.height / 2;
      expect(gradient.x1).toBeCloseTo(paint.center.x + Math.sin(theta) * half, 12);
      expect(gradient.y1).toBeCloseTo(paint.center.y + Math.cos(theta) * half, 12);
      expect(gradient.x2).toBeCloseTo(paint.center.x - Math.sin(theta) * half, 12);
      expect(gradient.y2).toBeCloseTo(paint.center.y - Math.cos(theta) * half, 12);
      expect(gradient.transform).toBe(`matrix(${paint.width} 0 0 ${paint.height} 0 0)`);
    }
  });
});

// @vitest-environment jsdom
import { describe, it, expect, afterEach } from "vitest";
import { render, cleanup } from "@testing-library/react";
import React from "react";
import { __resetReducedMotionStoreForTests } from "@/lib/usePrefersReducedMotion";
import { edgeWidthFor, shadeFor } from "@/lib/graph/nodeStyle";
import type { NeighbourNode } from "@/lib/graph/neighbourhood";
import { ConceptNeighbourhood } from "./ConceptNeighbourhood";

afterEach(() => {
  cleanup();
  __resetReducedMotionStoreForTests();
});

const CENTRE = { id: "recursion", name: "Recursion", mastery: 0.29, tier: "struggling" };
const SIBLINGS: NeighbourNode[] = [
  { id: "base-cases", name: "Base cases", mastery: 0.52, tier: "learning", strength: 0.9 },
  { id: "stack-frames", name: "Stack frames", mastery: 0.3, tier: "struggling", strength: 0.7 },
  { id: "tail-recursion", name: "Tail recursion", mastery: 0.12, tier: "struggling", strength: 0.4 },
];

const HOME = { width: 320, height: 204, scale: 2 } as const;

function renderHome(over: Partial<React.ComponentProps<typeof ConceptNeighbourhood>> = {}) {
  return render(
    <ConceptNeighbourhood
      centre={CENTRE}
      siblings={SIBLINGS}
      courseColor="#7b4b99"
      ariaLabel="Recursion and its neighbours on your knowledge tree"
      {...HOME}
      {...over}
    />,
  );
}

const num = (el: Element, attr: string) => Number(el.getAttribute(attr));

describe("ConceptNeighbourhood", () => {
  it("is one image to a screen reader, sized to the preset", () => {
    const { container } = renderHome({ testid: "quiz-neighbourhood" });
    const svg = container.querySelector("svg")!;
    expect(svg).toHaveAttribute("role", "img");
    expect(svg).toHaveAttribute(
      "aria-label",
      "Recursion and its neighbours on your knowledge tree",
    );
    expect(svg).toHaveAttribute("width", "320");
    expect(svg).toHaveAttribute("height", "204");
    expect(svg).toHaveAttribute("data-testid", "quiz-neighbourhood");
  });

  it("draws one edge per sibling, from the centre, at the tree's width and opacity", () => {
    const { container } = renderHome();
    const edges = Array.from(container.querySelectorAll(".concept-neighbourhood__edge"));
    expect(edges).toHaveLength(3);
    for (const edge of edges) {
      expect(num(edge, "x1")).toBe(320 / 2 + 8);
      expect(num(edge, "y1")).toBe(204 / 2);
      expect(num(edge, "stroke-opacity")).toBe(0.2);
    }
    expect(num(edges[0], "stroke-width")).toBeCloseTo(edgeWidthFor(0.9), 6);
    expect(num(edges[2], "stroke-width")).toBeCloseTo(edgeWidthFor(0.4), 6);
  });

  it("scales every mark by the preset's scale and shades each by its own id", () => {
    const { container } = renderHome();
    const bodies = Array.from(container.querySelectorAll(".concept-node__body"));
    // three siblings then the centre
    expect(bodies).toHaveLength(4);
    // radiusFor(0.52) * 2
    expect(num(bodies[0], "r")).toBeCloseTo((8 + 0.52 * 12) * 2, 6);
    expect(bodies[0]).toHaveAttribute("fill", shadeFor("#7b4b99", "base-cases"));
    // the centre, radiusFor(0.29) * 2
    expect(num(bodies[3], "r")).toBeCloseTo((8 + 0.29 * 12) * 2, 6);
    expect(bodies[3]).toHaveAttribute("fill", shadeFor("#7b4b99", "recursion"));
  });

  it("glows only under the centre — the siblings stay flat", () => {
    const { container } = renderHome();
    expect(container.querySelectorAll(".concept-node__glow")).toHaveLength(1);
  });

  it("places the three siblings in the design's slots and the centre right of true centre", () => {
    const { container } = renderHome();
    const bodies = Array.from(container.querySelectorAll(".concept-node__body"));
    const at = (el: Element) => [num(el, "cx"), num(el, "cy")];
    expect(at(bodies[0])[0]).toBeLessThan(160); // top-left
    expect(at(bodies[0])[1]).toBeLessThan(102);
    expect(at(bodies[1])[0]).toBeGreaterThan(160); // top-right
    expect(at(bodies[1])[1]).toBeLessThan(102);
    expect(at(bodies[2])[0]).toBeLessThan(160); // bottom-left
    expect(at(bodies[2])[1]).toBeGreaterThan(102);
    expect(at(bodies[3])).toEqual([168, 102]);
  });

  it("captions the centre and the two left-hand siblings, never the one on the edge", () => {
    const { container } = renderHome();
    const labels = Array.from(container.querySelectorAll(".concept-neighbourhood__label")).map(
      (t) => t.textContent,
    );
    expect(labels).toEqual(["Base cases", "Tail recursion", "Recursion"]);
    expect(labels).not.toContain("Stack frames");
  });

  it("truncates a caption at 18 characters", () => {
    const { container } = renderHome({
      centre: { ...CENTRE, name: "Fundamental theorem of calculus" },
    });
    const labels = Array.from(container.querySelectorAll(".concept-neighbourhood__label")).map(
      (t) => t.textContent,
    );
    expect(labels).toContain("Fundamental theor…");
  });

  it("flips a caption above the mark when below would fall off the canvas", () => {
    const { container } = renderHome();
    const bodies = Array.from(container.querySelectorAll(".concept-node__body"));
    const labels = Array.from(container.querySelectorAll(".concept-neighbourhood__label"));
    // slot 2 (bottom-left) sits at 0.96 * height, so its caption goes above.
    const bottomLeft = labels.find((l) => l.textContent === "Tail recursion")!;
    expect(num(bottomLeft, "y")).toBeLessThan(num(bodies[2], "cy"));
    // slot 0 (top-left) has room below.
    const topLeft = labels.find((l) => l.textContent === "Base cases")!;
    expect(num(topLeft, "y")).toBeGreaterThan(num(bodies[0], "cy"));
  });

  it("drops every caption when showLabels is false", () => {
    const { container } = renderHome({ showLabels: false });
    expect(container.querySelectorAll(".concept-neighbourhood__label")).toHaveLength(0);
  });

  it("renders with fewer than three siblings, and with none at all", () => {
    const one = renderHome({ siblings: SIBLINGS.slice(0, 1) });
    expect(one.container.querySelectorAll(".concept-node__body")).toHaveLength(2);
    expect(one.container.querySelectorAll(".concept-neighbourhood__edge")).toHaveLength(1);
    cleanup();
    const none = renderHome({ siblings: [] });
    expect(none.container.querySelectorAll(".concept-node__body")).toHaveLength(1);
    expect(none.container.querySelectorAll(".concept-neighbourhood__edge")).toHaveLength(0);
  });

  it("ignores a fourth sibling rather than stacking it on a used slot", () => {
    const { container } = renderHome({
      siblings: [
        ...SIBLINGS,
        { id: "closures", name: "Closures", mastery: 0.7, tier: "learning", strength: 0.3 },
      ],
    });
    expect(container.querySelectorAll(".concept-neighbourhood__edge")).toHaveLength(3);
  });

  it("draws the wide results canvas exactly where the design draws it", () => {
    const { container } = render(
      <ConceptNeighbourhood
        centre={CENTRE}
        siblings={SIBLINGS}
        courseColor="#7b4b99"
        width={640}
        height={212}
        scale={2.5}
        ariaLabel="Recursion and its neighbours"
      />,
    );
    const bodies = Array.from(container.querySelectorAll(".concept-node__body"));
    const at = (el: Element) => [num(el, "cx"), num(el, "cy")];
    // The design's own numbers: centre (320,106) with NO rightward nudge, and
    // siblings at (96,34) / (628,48) / (86,208). Within a pixel on each.
    expect(at(bodies[3])).toEqual([320, 106]);
    const expected = [
      [96, 34],
      [628, 48],
      [86, 208],
    ];
    expected.forEach(([x, y], i) => {
      expect(at(bodies[i])[0]).toBeCloseTo(x, 0);
      expect(at(bodies[i])[1]).toBeCloseTo(y, 0);
    });
  });

  it("picks the composition from the width, and lets a caller override it", () => {
    // 640 wide → wide → centred.
    const wide = renderHome({ width: 640, height: 212, scale: 2.5 });
    expect(num(wide.container.querySelectorAll(".concept-node__body")[3], "cx")).toBe(320);
    cleanup();
    // The same canvas, forced compact → the 8px nudge comes back.
    const forced = renderHome({
      width: 640,
      height: 212,
      scale: 2.5,
      composition: "compact",
    });
    expect(num(forced.container.querySelectorAll(".concept-node__body")[3], "cx")).toBe(328);
  });

  it("renders the results preset's growth centre at the after-radius with reduced motion", () => {
    const { container } = render(
      <ConceptNeighbourhood
        centre={CENTRE}
        siblings={SIBLINGS}
        courseColor="#7b4b99"
        width={640}
        height={212}
        scale={2.5}
        centreVariant={{ kind: "growth", before: 0.29, after: 0.46 }}
        ariaLabel="Recursion node grew from 29% to 46% mastery"
      />,
    );
    const centre = container.querySelector<SVGCircleElement>(".concept-node__body--growth")!;
    expect(num(centre, "r")).toBeCloseTo((8 + 0.46 * 12) * 2.5, 6);
    expect(centre.style.getPropertyValue("--concept-grow")).toBe("1.0000");
    const before = container.querySelector(".concept-node__before")!;
    expect(num(before, "r")).toBeCloseTo((8 + 0.29 * 12) * 2.5, 6);
  });
});

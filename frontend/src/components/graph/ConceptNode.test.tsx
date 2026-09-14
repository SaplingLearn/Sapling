// @vitest-environment jsdom
import { describe, it, expect, afterEach } from "vitest";
import { render, cleanup } from "@testing-library/react";
import React from "react";
import { __resetReducedMotionStoreForTests } from "@/lib/usePrefersReducedMotion";
import { opacityFor, shadeFor } from "@/lib/graph/nodeStyle";
import { ConceptNode, NODE_REF_BOX } from "./ConceptNode";

/**
 * The shared setup stubs `matchMedia` to REDUCED MOTION = true (see
 * vitest.setup.ts), which is the right default here: it is the static frame,
 * and it is the case the design contract cares about most.
 */
afterEach(() => {
  cleanup();
  __resetReducedMotionStoreForTests();
});

const BASE = {
  courseColor: "#7b4b99",
  nodeId: "recursion",
  mastery: 0.29,
  tier: "struggling",
};

const body = (c: HTMLElement) => c.querySelector<SVGCircleElement>(".concept-node__body")!;
const num = (el: Element, attr: string) => Number(el.getAttribute(attr));

describe("ConceptNode", () => {
  it("draws the mark in reference units so size only scales it", () => {
    const { container } = render(<ConceptNode size={26} variant={{ kind: "node" }} {...BASE} />);
    const svg = container.querySelector("svg")!;
    expect(svg).toHaveAttribute("width", "26");
    expect(svg).toHaveAttribute("viewBox", `0 0 ${NODE_REF_BOX} ${NODE_REF_BOX}`);
    // radiusFor(0.29) = 8 + 0.29*12
    expect(num(body(container), "r")).toBeCloseTo(11.48, 6);
  });

  it("is the same mark at 15px and 26px — only the CSS width differs", () => {
    const small = render(<ConceptNode size={15} variant={{ kind: "dot" }} {...BASE} />);
    const rSmall = num(body(small.container), "r");
    const viewSmall = small.container.querySelector("svg")!.getAttribute("viewBox");
    cleanup();
    const big = render(<ConceptNode size={26} variant={{ kind: "dot" }} {...BASE} />);
    expect(num(body(big.container), "r")).toBe(rSmall);
    expect(big.container.querySelector("svg")!.getAttribute("viewBox")).toBe(viewSmall);
  });

  it("takes its colour from shadeFor and its opacity from the tier", () => {
    const { container } = render(<ConceptNode size={26} {...BASE} />);
    const circle = body(container);
    const expected = shadeFor("#7b4b99", "recursion");
    expect(circle).toHaveAttribute("fill", expected);
    expect(circle).toHaveAttribute("stroke", expected);
    expect(num(circle, "opacity")).toBe(opacityFor("struggling"));
    expect(num(circle, "stroke-opacity")).toBe(0.4);
  });

  it("clamps a fully-mastered concept so it can't overflow the reference box", () => {
    const { container } = render(
      <ConceptNode size={26} {...BASE} mastery={1} tier="mastered" />,
    );
    expect(num(body(container), "r")).toBeLessThanOrEqual(NODE_REF_BOX / 2);
  });

  it("leaves a subject root unshaded, fully opaque, and at the flat root radius", () => {
    const { container } = render(
      <ConceptNode size={26} {...BASE} isRoot mastery={0} tier="mastered" />,
    );
    const circle = body(container);
    expect(circle).toHaveAttribute("fill", "#7b4b99");
    expect(num(circle, "opacity")).toBe(1);
    // radiusFor(_, true) is 22, clamped into the reference box.
    expect(num(circle, "r")).toBe(NODE_REF_BOX / 2 - 0.75);
  });

  it("adds the glow to `node` and `growth` but not to `dot`", () => {
    const dot = render(<ConceptNode size={15} variant={{ kind: "dot" }} {...BASE} />);
    expect(dot.container.querySelector(".concept-node__glow")).toBeNull();
    cleanup();
    const node = render(<ConceptNode size={26} variant={{ kind: "node" }} {...BASE} />);
    expect(node.container.querySelector(".concept-node__glow")).not.toBeNull();
    expect(node.container.querySelector("filter")).not.toBeNull();
  });

  it("truncates the caption at 18 characters, like the tree", () => {
    const { container } = render(
      <ConceptNode size={26} {...BASE} label="Fundamental theorem of calculus" />,
    );
    expect(container.querySelector(".concept-node__label")!.textContent).toBe(
      "Fundamental theor…",
    );
    // The caption needs vertical room, so the box grows below the mark only.
    const svg = container.querySelector("svg")!;
    expect(svg.getAttribute("viewBox")).toBe(`0 0 ${NODE_REF_BOX} ${NODE_REF_BOX + 18}`);
    expect(Number(svg.getAttribute("height"))).toBeGreaterThan(26);
  });

  it("leaves a caption of 18 characters or fewer alone", () => {
    const { container } = render(<ConceptNode size={26} {...BASE} label="Recursion" />);
    expect(container.querySelector(".concept-node__label")!.textContent).toBe("Recursion");
  });

  it("is decorative without a title and an image with one", () => {
    const bare = render(<ConceptNode size={15} variant={{ kind: "dot" }} {...BASE} />);
    expect(bare.container.querySelector("svg")).toHaveAttribute("aria-hidden", "true");
    cleanup();
    const named = render(
      <ConceptNode size={15} variant={{ kind: "dot" }} {...BASE} title="Recursion, 29% mastery" />,
    );
    const svg = named.container.querySelector("svg")!;
    expect(svg).toHaveAttribute("role", "img");
    expect(svg).toHaveAttribute("aria-label", "Recursion, 29% mastery");
    expect(svg).not.toHaveAttribute("aria-hidden");
  });

  it("passes a testid through", () => {
    const { container } = render(
      <ConceptNode size={26} {...BASE} testid="quiz-proposal-node" />,
    );
    expect(container.querySelector('[data-testid="quiz-proposal-node"]')).not.toBeNull();
  });
});

describe("ConceptNode — the growth variant", () => {
  const GROWTH = { kind: "growth", before: 0.29, after: 0.46 } as const;

  it("renders the after-radius immediately under prefers-reduced-motion", () => {
    const { container } = render(<ConceptNode size={64} {...BASE} variant={GROWTH} />);
    const circle = body(container);
    // radiusFor(0.46) = 8 + 0.46*12 — the END state, on the very first paint.
    expect(num(circle, "r")).toBeCloseTo(13.52, 6);
    // …and no pre-grow scale for a transition to run from.
    expect(circle.style.getPropertyValue("--concept-grow")).toBe("1.0000");
  });

  it("renders the after-radius immediately with animate={false}", () => {
    const { container } = render(
      <ConceptNode size={64} {...BASE} variant={GROWTH} animate={false} />,
    );
    const circle = body(container);
    expect(num(circle, "r")).toBeCloseTo(13.52, 6);
    expect(circle.style.getPropertyValue("--concept-grow")).toBe("1.0000");
  });

  it("draws the dashed before-ring at the before-radius in every case", () => {
    const { container } = render(<ConceptNode size={64} {...BASE} variant={GROWTH} />);
    const ring = container.querySelector<SVGCircleElement>(".concept-node__before")!;
    expect(num(ring, "r")).toBeCloseTo(11.48, 6);
    expect(ring).toHaveAttribute("stroke-dasharray", "4 4");
    expect(ring).toHaveAttribute("fill", "none");
    expect(num(ring, "opacity")).toBe(0.5);
  });

  it("takes its opacity from tierFor(after), the one place a tier is derived (R-12)", () => {
    const { container } = render(
      // after 0.8 → mastered, though the passed-in tier says struggling.
      <ConceptNode size={64} {...BASE} variant={{ kind: "growth", before: 0.1, after: 0.8 }} />,
    );
    expect(num(body(container), "opacity")).toBe(opacityFor("mastered"));
  });

  it("starts scaled down when motion is allowed, so the transition has somewhere to grow from", () => {
    window.matchMedia = ((query: string) => ({
      matches: false,
      media: query,
      onchange: null,
      addEventListener() {},
      removeEventListener() {},
      addListener() {},
      removeListener() {},
      dispatchEvent: () => false,
    })) as unknown as typeof window.matchMedia;
    __resetReducedMotionStoreForTests();

    const { container } = render(<ConceptNode size={64} {...BASE} variant={GROWTH} />);
    const circle = body(container);
    // The drawn circle is always the END radius; only the scale animates.
    expect(num(circle, "r")).toBeCloseTo(13.52, 6);
    expect(Number(circle.style.getPropertyValue("--concept-grow"))).toBeCloseTo(11.48 / 13.52, 3);
  });
});

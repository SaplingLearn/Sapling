// @vitest-environment jsdom
import { describe, it, expect, afterEach } from "vitest";
import { render, cleanup } from "@testing-library/react";
import React from "react";
import { __resetReducedMotionStoreForTests } from "@/lib/usePrefersReducedMotion";
import { blobPath, blobProfile, nodeBlobPathAt, wobbleFor } from "@/lib/graph/blobShape";
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

// The mark is a hand-drawn outline (a path), so its radius and centre ride on
// `data-r` / `data-cx` / `data-cy`: what a circle's `r` / `cx` / `cy` would say.
const body = (c: HTMLElement) => c.querySelector<SVGPathElement>(".concept-node__body")!;
const num = (el: Element, attr: string) => Number(el.getAttribute(attr));
const CENTRE = NODE_REF_BOX / 2;

describe("ConceptNode", () => {
  it("draws the mark in reference units so size only scales it", () => {
    const { container } = render(<ConceptNode size={26} variant={{ kind: "node" }} {...BASE} />);
    const svg = container.querySelector("svg")!;
    expect(svg).toHaveAttribute("width", "26");
    expect(svg).toHaveAttribute("viewBox", `0 0 ${NODE_REF_BOX} ${NODE_REF_BOX}`);
    // radiusFor(0.29) = 8 + 0.29*12
    expect(num(body(container), "data-r")).toBeCloseTo(11.48, 6);
    expect(num(body(container), "data-cx")).toBe(CENTRE);
    expect(num(body(container), "data-cy")).toBe(CENTRE);
  });

  it("draws the body as the node's own hand-drawn outline, centred in the box", () => {
    const { container } = render(<ConceptNode size={26} variant={{ kind: "node" }} {...BASE} />);
    const mark = body(container);
    expect(mark.tagName.toLowerCase()).toBe("path");
    const r = num(mark, "data-r");
    expect(mark).toHaveAttribute("d", nodeBlobPathAt("recursion", r, wobbleFor(r), CENTRE, CENTRE));
    // The centre is in the path itself: a CSS transform on the growth mark
    // would replace a `transform` attribute.
    expect(mark).not.toHaveAttribute("transform");
    expect(container.querySelector("circle")).toBeNull();
  });

  it("gives two concepts two different outlines, and one concept the same outline every time", () => {
    const first = render(<ConceptNode size={26} {...BASE} />);
    const d = body(first.container).getAttribute("d");
    cleanup();
    const again = render(<ConceptNode size={26} {...BASE} />);
    expect(body(again.container).getAttribute("d")).toBe(d);
    cleanup();
    const other = render(<ConceptNode size={26} {...BASE} nodeId="base-cases" />);
    expect(body(other.container).getAttribute("d")).not.toBe(d);
  });

  it("is the same mark at 15px and 26px — only the CSS width differs", () => {
    const small = render(<ConceptNode size={15} variant={{ kind: "dot" }} {...BASE} />);
    const rSmall = num(body(small.container), "data-r");
    const dSmall = body(small.container).getAttribute("d");
    const viewSmall = small.container.querySelector("svg")!.getAttribute("viewBox");
    cleanup();
    const big = render(<ConceptNode size={26} variant={{ kind: "dot" }} {...BASE} />);
    expect(num(body(big.container), "data-r")).toBe(rSmall);
    expect(body(big.container).getAttribute("d")).toBe(dSmall);
    expect(big.container.querySelector("svg")!.getAttribute("viewBox")).toBe(viewSmall);
  });

  it("takes its colour from shadeFor and its opacity from the tier", () => {
    const { container } = render(<ConceptNode size={26} {...BASE} />);
    const mark = body(container);
    expect(mark).toHaveAttribute("fill", shadeFor("#7b4b99", "recursion"));
    expect(num(mark, "opacity")).toBe(opacityFor("struggling"));
  });

  it("is one flat colour: no rim, no glow, no filter, no gradient, in every variant", () => {
    const variants = [
      { kind: "dot" },
      { kind: "node" },
      { kind: "growth", before: 0.29, after: 0.46 },
    ] as const;
    for (const variant of variants) {
      const { container } = render(<ConceptNode size={26} variant={variant} {...BASE} />);
      const mark = body(container);
      // A rim of the same colour over a translucent fill reads as a second,
      // darker tone; the fill is the whole mark.
      expect(mark).not.toHaveAttribute("stroke");
      expect(mark).not.toHaveAttribute("filter");
      expect(mark.getAttribute("fill")).not.toMatch(/^url\(/);
      expect(container.querySelector(".concept-node__glow")).toBeNull();
      expect(container.querySelector("filter, linearGradient, radialGradient, pattern, image")).toBeNull();
      // Exactly one filled shape.
      expect(container.querySelectorAll('path:not([fill="none"]), circle, ellipse, rect')).toHaveLength(1);
      cleanup();
    }
  });

  it("clamps a fully-mastered concept so it can't overflow the reference box", () => {
    const { container } = render(
      <ConceptNode size={26} {...BASE} mastery={1} tier="mastered" />,
    );
    expect(num(body(container), "data-r")).toBeLessThanOrEqual(NODE_REF_BOX / 2);
  });

  it("leaves a subject root unshaded, fully opaque, and at the flat root radius", () => {
    const { container } = render(
      <ConceptNode size={26} {...BASE} isRoot mastery={0} tier="mastered" />,
    );
    const mark = body(container);
    expect(mark).toHaveAttribute("fill", "#7b4b99");
    expect(num(mark, "opacity")).toBe(1);
    // radiusFor(_, true) is 22, clamped into the reference box.
    expect(num(mark, "data-r")).toBe(NODE_REF_BOX / 2 - 0.75);
  });

  it("draws `dot` and `node` as the same mark", () => {
    const dot = render(<ConceptNode size={26} variant={{ kind: "dot" }} {...BASE} />);
    const dotMarkup = dot.container.querySelector("svg")!.innerHTML;
    cleanup();
    const node = render(<ConceptNode size={26} variant={{ kind: "node" }} {...BASE} />);
    expect(node.container.querySelector("svg")!.innerHTML).toBe(dotMarkup);
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
    const mark = body(container);
    // radiusFor(0.46) = 8 + 0.46*12 — the END state, on the very first paint.
    expect(num(mark, "data-r")).toBeCloseTo(13.52, 6);
    // …and no pre-grow scale for a transition to run from.
    expect(mark.style.getPropertyValue("--concept-grow")).toBe("1.0000");
  });

  it("renders the after-radius immediately with animate={false}", () => {
    const { container } = render(
      <ConceptNode size={64} {...BASE} variant={GROWTH} animate={false} />,
    );
    const mark = body(container);
    expect(num(mark, "data-r")).toBeCloseTo(13.52, 6);
    expect(mark.style.getPropertyValue("--concept-grow")).toBe("1.0000");
  });

  it("draws the dashed before-ring at the before-radius in every case", () => {
    const { container } = render(<ConceptNode size={64} {...BASE} variant={GROWTH} />);
    const ring = container.querySelector<SVGPathElement>(".concept-node__before")!;
    expect(num(ring, "data-r")).toBeCloseTo(11.48, 6);
    expect(ring).toHaveAttribute("stroke-dasharray", "4 4");
    expect(ring).toHaveAttribute("fill", "none");
    expect(num(ring, "opacity")).toBe(0.5);
  });

  it("draws the before-ring as the body's own outline at the earlier size", () => {
    const { container } = render(<ConceptNode size={64} {...BASE} variant={GROWTH} />);
    const ring = container.querySelector<SVGPathElement>(".concept-node__before")!;
    const mark = body(container);
    // One shape, chosen for the size the node ends at, drawn twice.
    const profile = blobProfile("recursion", wobbleFor(num(mark, "data-r")));
    expect(mark).toHaveAttribute("d", blobPath(profile, num(mark, "data-r"), CENTRE, CENTRE));
    expect(ring).toHaveAttribute("d", blobPath(profile, num(ring, "data-r"), CENTRE, CENTRE));
    expect(ring).toHaveAttribute("stroke", mark.getAttribute("fill")!);
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
    const mark = body(container);
    // The drawn shape is always the END radius; only the scale animates.
    expect(num(mark, "data-r")).toBeCloseTo(13.52, 6);
    expect(Number(mark.style.getPropertyValue("--concept-grow"))).toBeCloseTo(11.48 / 13.52, 3);
  });
});

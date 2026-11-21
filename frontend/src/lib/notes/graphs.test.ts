import { describe, expect, it } from "vitest";

import {
  compile, compose, DEFAULT_VIEW, fmt, nice, parseView, pretty, renderChart,
  renderPlot, snap, viewAttr, zoomView, W,
} from "./graphs";

const NO_PARAMS: Record<string, number> = {};

describe("compile", () => {
  it("reads y = f(x), with or without the y =", () => {
    const a = compile("x^2 - 2x - 3");
    expect(a.kind).toBe("fn");
    expect(a.fn!(3, NO_PARAMS)).toBe(0);
    expect(compile("y = 2x").fn!(4, NO_PARAMS)).toBe(8);
    expect(compile("f(x) = x + 1").fn!(1, NO_PARAMS)).toBe(2);
  });

  it("reads a point and a vertical line", () => {
    expect(compile("(1, -4)").point!(NO_PARAMS)).toEqual([1, -4]);
    expect(compile("x = 3").vx!(NO_PARAMS)).toBe(3);
  });

  it("knows the named functions and constants", () => {
    expect(compile("sin(x)").fn!(0, NO_PARAMS)).toBe(0);
    expect(compile("pi").fn!(0, NO_PARAMS)).toBeCloseTo(Math.PI);
    expect(compile("sqrt(x)").fn!(9, NO_PARAMS)).toBe(3);
  });

  it("multiplies implicitly: 2x, 2(x), xy", () => {
    expect(compile("2x").fn!(5, NO_PARAMS)).toBe(10);
    expect(compile("2(x+1)").fn!(2, NO_PARAMS)).toBe(6);
  });

  it("finds the single letters that are parameters", () => {
    const c = compile("a*x + b");
    expect(c.params).toEqual(["a", "b"]);
    expect(c.fn!(2, { a: 3, b: 1 })).toBe(7);
  });

  it("is empty for nothing, and an error for nonsense — it never throws", () => {
    expect(compile("").kind).toBe("empty");
    expect(compile("   ").kind).toBe("empty");
    expect(compile("x +* ").kind).toBe("err");
  });
});

describe("compose", () => {
  it("shifts a curve and writes the result back readably", () => {
    expect(compose("x^2", 2, 0)).toBe("(x - 2)^2");
    expect(compose("x^2", 0, 3)).toBe("x^2 + 3");
    expect(compose("x^2", -1, -2)).toBe("(x + 1)^2 - 2");
  });

  it("leaves an unshifted curve exactly as it was", () => {
    expect(compose("y = sin(x)", 0, 0)).toBe("sin(x)");
  });

  it("shifts the x inside a call without doubling its parentheses", () => {
    // `exp` is a known name and is left alone; the x it wraps is shifted, and
    // the redundant bracket the substitution would leave is collapsed.
    expect(compose("exp(x)", 1, 0)).toBe("exp(x - 1)");
  });
});

describe("view", () => {
  it("round-trips through its attribute", () => {
    const v = { cx: 1.5, cy: -2, s: 0.05 };
    expect(parseView(viewAttr(v))).toEqual(v);
  });

  it("falls back on a missing or broken value", () => {
    expect(parseView(null).s).toBeGreaterThan(0);
    expect(parseView("junk")).toEqual({ cx: 0, cy: 0, s: DEFAULT_VIEW.s });
  });

  it("zooms about a point, keeping that point still", () => {
    const v = { cx: 0, cy: 0, s: 0.05 };
    const z = zoomView(v, 0.5, W / 2, 0);
    // Zooming about the centre column leaves cx where it was.
    expect(z.cx).toBeCloseTo(0);
    expect(z.s).toBeCloseTo(0.025);
  });

  it("clamps the zoom so it cannot invert or run away", () => {
    expect(zoomView({ cx: 0, cy: 0, s: 40 }, 10, 0, 0).s).toBe(50);
    expect(zoomView({ cx: 0, cy: 0, s: 1e-4 }, 0.001, 0, 0).s).toBe(1e-4);
  });
});

describe("renderPlot", () => {
  it("draws a curve with a hit path for dragging", () => {
    const { svg, model } = renderPlot(
      [{ src: "x^2", color: "#445D22" }], DEFAULT_VIEW, NO_PARAMS,
    );
    expect(svg).toContain("pl-vis");
    expect(svg).toContain('class="pl-hit" data-r="0"');
    expect(model.step).toBeGreaterThan(0);
  });

  it("breaks a curve at an asymptote rather than drawing through it", () => {
    const { svg } = renderPlot([{ src: "1/x", color: "#445D22" }], DEFAULT_VIEW, NO_PARAMS);
    // More than one move command means the path was broken.
    expect((svg.match(/M/g) || []).length).toBeGreaterThan(1);
  });

  it("marks a parameter-free point as draggable, and a driven one as not", () => {
    const free = renderPlot([{ src: "(1,2)", color: "#445D22" }], DEFAULT_VIEW, NO_PARAMS);
    expect(free.svg).toContain("pl-drag");
    const driven = renderPlot([{ src: "(a,2)", color: "#445D22" }], DEFAULT_VIEW, { a: 1 });
    expect(driven.svg).toContain("pl-pt");
    expect(driven.svg).not.toContain("pl-drag");
  });

  it("survives a broken row without losing the good ones", () => {
    const { svg } = renderPlot([
      { src: "x +*", color: "#445D22" },
      { src: "x", color: "#2E5F96" },
    ], DEFAULT_VIEW, NO_PARAMS);
    expect(svg).toContain("#2E5F96");
  });
});

describe("renderChart", () => {
  const rows = [["Mon", 3], ["Tue", 5]] as [string, number][];

  it("draws a bar chart with a draggable bar per row", () => {
    const { svg, model } = renderChart("bar", "Hours", rows);
    expect(svg).toContain("Hours");
    expect((svg.match(/ch-drag/g) || []).length).toBe(2);
    expect(model?.kind).toBe("bar");
  });

  it("offers a + slot on an editable bar chart, and not on a frozen one", () => {
    expect(renderChart("bar", "t", rows).svg).toContain("ch-add");
    expect(renderChart("bar", "t", rows, { lo: 0, hi: 6, step: 2 }).svg).not.toContain("ch-add");
  });

  it("fits a trend line to a scatter", () => {
    const { svg } = renderChart("scatter", "x vs y", [["1", 2], ["2", 4], ["3", 6]]);
    expect(svg).toContain("stroke-dasharray");
    expect(svg).toContain("y = 2x");
  });

  it("gives a pie a handle between each pair of slices", () => {
    const { svg, model } = renderChart("pie", "Split", [["a", 1], ["b", 1], ["c", 2]]);
    expect((svg.match(/pie-h/g) || []).length).toBe(2);
    expect(model?.total).toBe(4);
  });

  it("draws just the title when there is no usable data", () => {
    const { svg, model } = renderChart("bar", "Empty", [["", Number.NaN]]);
    expect(svg).toContain("Empty");
    expect(model).toBeNull();
  });

  it("escapes a label rather than letting it become markup", () => {
    const { svg } = renderChart("bar", "<script>", [["<b>", 1]]);
    // `<` is what opens a tag, so escaping it is what makes the label inert;
    // a bare `>` in text is not markup and is left as typed.
    expect(svg).not.toContain("<script>");
    expect(svg).not.toContain("<b>");
    expect(svg).toContain("&lt;b");
  });
});

describe("number helpers", () => {
  it("formats with a real minus sign and sensible precision", () => {
    expect(fmt(-1.5)).toBe("−1.5");
    expect(fmt(1234)).toBe("1.23e+3");
    expect(fmt(Number.POSITIVE_INFINITY)).toBe("–");
  });

  it("picks a round axis step", () => {
    expect(nice(1)).toBe(1);
    expect(nice(3)).toBe(2);
    expect(nice(23)).toBe(20);
  });

  it("snaps a drag to a tenth of the step", () => {
    expect(snap(1.04, 1)).toBe(1);
    expect(snap(1.06, 1)).toBeCloseTo(1.1);
  });

  it("prettifies an expression for the legend", () => {
    expect(pretty("x^2 - 2*x")).toBe("x² − 2·x");
  });
});

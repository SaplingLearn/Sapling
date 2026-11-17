// @vitest-environment jsdom
/**
 * FunctionPlot hands function-plot only what plotSpec.ts validated and
 * rebuilt; a fence that fails is drawn as code and function-plot is never
 * called (it compiles expressions with `new Function`).
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";

const fp = vi.hoisted(() => vi.fn());
vi.mock("function-plot", () => ({ default: fp }));

import { FunctionPlot } from "./FunctionPlot";

afterEach(() => {
  cleanup();
  fp.mockReset();
});

// Let the component's dynamic import settle.
const settle = () => new Promise((r) => setTimeout(r, 20));

describe("FunctionPlot", () => {
  it.each([
    'plot: x + ["(globalThis.hit=1, 0)"]',
    "plot: x + ['(globalThis.hit=1, 0)']",
    "plot: x + [`(globalThis.hit=1, 0)`]",
    "plot: constructor",
    "plot: __proto__",
    "plot: this",
    "plot: globalThis",
    "plot: sin(x); color=url(https://attacker.example/#a)",
    "plot: sin(x); graphType=constructor",
    "plot: sin(x)\ntitle: <b>x</b>",
  ])("draws %j as code and never calls function-plot", async (spec) => {
    render(<FunctionPlot spec={spec} />);
    const pre = screen.getByTestId("plot-fence-as-code");
    expect(pre.textContent).toBe(spec);
    await settle();
    expect(fp).not.toHaveBeenCalled();
  });

  it.each([
    ["sin(x)", "sin ( x )"],
    ["x^2 + 3*x - 1", "x ^ 2 + 3 * x - 1"],
    ["sqrt(abs(x))", "sqrt ( abs ( x ) )"],
    ["2*pi*x", "2 * PI * x"],
  ])("plots %j as the rebuilt %j", async (expr, rebuilt) => {
    render(<FunctionPlot spec={`plot: ${expr}; color=steelblue\nxdomain: [-3, 3]`} />);
    await waitFor(() => expect(fp).toHaveBeenCalledTimes(1));
    const opts = fp.mock.calls[0][0];
    expect(opts.data).toEqual([{ fn: rebuilt, color: "steelblue" }]);
    expect(opts.xAxis).toEqual({ domain: [-3, 3] });
    expect(screen.queryByTestId("plot-fence-as-code")).toBeNull();
  });
});

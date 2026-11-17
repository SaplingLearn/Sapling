// @vitest-environment jsdom
/**
 * A ```plot fence is model text a student's documents can steer, and
 * function-plot compiles its expressions with `new Function` (math-codegen).
 * plotSpec.ts is the only thing between the two: these pin that an
 * expression which is not plain maths never reaches function-plot, and that
 * plain maths still plots.
 */
import { afterEach, describe, expect, it } from "vitest";
import { EvalBuiltIn, EvalInterval } from "function-plot";

import {
  MAX_EXPRESSION_LENGTH,
  MAX_SERIES,
  isSafeColor,
  parsePlotSpec,
  safeExpression,
} from "./plotSpec";

type Flagged = typeof globalThis & { __plotHit?: unknown };
const g = globalThis as Flagged;

afterEach(() => {
  delete g.__plotHit;
});

// The verified C1 payload: a string inside an array literal is emitted by
// math-codegen as raw JavaScript.
const PAYLOAD = 'x + ["(globalThis.__plotHit=1, 0)"]';

describe("the payload is live (control)", () => {
  it("runs when function-plot compiles it unvalidated", () => {
    // Proves the rejections below guard a real gadget, not a hypothetical.
    // If a function-plot upgrade defuses it this fails: re-check C1 then.
    // The default (interval) sampler, as a plain `plot: <expr>` series uses.
    // It may throw afterwards; the side effect has already run by then.
    try {
      EvalInterval({ fn: PAYLOAD }, "fn", { x: { lo: 1, hi: 1 } });
    } catch {
      /* evaluation error after the injected code ran */
    }
    expect(g.__plotHit).toBe(1);
  });
});

describe("safeExpression rejects anything that is not plain maths", () => {
  it.each([
    PAYLOAD,
    "x + ['(globalThis.__plotHit=1, 0)']",
    "x + [`(globalThis.__plotHit=1, 0)`]",
    'x + [["(globalThis.__plotHit=1, 0)"]]',
    "x + [[[x]]]",
    "[x]",
    'x + "a"',
    "x + 'a'",
    "`x`",
    "x + {a: 1}",
    "constructor",
    'constructor("globalThis.__plotHit=1")()',
    "x.constructor",
    "__proto__",
    "x + __proto__",
    "this",
    "globalThis",
    "window",
    "document",
    "Function",
    "eval(x)",
    "\\u0078",
    "x + \\u005b1\\u005d",
    "\\x78",
    "ｘ", // fullwidth x
    "х", // Cyrillic ha
    "x; globalThis.__plotHit = 1",
    "x = 1",
    "x == 1",
    // A leading `y =` / `f(x) =` / `r =` is the one `=` allowed, once.
    "y = x = 2",
    "y == x",
    "y = = x",
    "y = y = x",
    "f(x) = y = x",
    "x^2 = y",
    "g(x) = x",
    "f(t) = t",
    "z = x",
    "y := x",
    'y = x + ["(globalThis.__plotHit=1, 0)"]',
    "x ? 1 : 2",
    "x < 1",
    "x % 2",
    "x & 1",
    "x!",
    "x.y",
    ".",
    "1e3",
    "x2",
    "sin",
    "sin + x",
    "x(1)",
    "pi(2)",
    "(x",
    "x)",
    "1 2",
    "",
    "   ",
    "x".padEnd(MAX_EXPRESSION_LENGTH + 1, "+x"),
  ])("rejects %j", (expr) => {
    expect(() => safeExpression(expr)).toThrow();
    const res = parsePlotSpec(`plot: ${expr}`);
    expect(res.ok).toBe(false);
    expect(g.__plotHit).toBeUndefined();
  });
});

describe("safeExpression keeps plain maths", () => {
  it.each([
    ["sin(x)", "sin ( x )"],
    ["x^2 + 3*x - 1", "x ^ 2 + 3 * x - 1"],
    ["sqrt(abs(x))", "sqrt ( abs ( x ) )"],
    ["2*pi*x", "2 * PI * x"],
    ["e^x", "E ^ x"],
    ["2x", "2 x"],
    ["ln(x)", "log ( x )"],
    ["max(x, 0.5) / .25", "max ( x , 0.5 ) / .25"],
    ["-cos(theta) + t*r - y", "- cos ( theta ) + t * r - y"],
    // One leading definition is dropped.
    ["y = x^2", "x ^ 2"],
    ["y=x^2", "x ^ 2"],
    ["  y   =   sin(x)", "sin ( x )"],
    ["f(x) = sin(x)", "sin ( x )"],
    ["f ( x )=2*pi*x", "2 * PI * x"],
    ["r = 1 + cos(theta)", "1 + cos ( theta )"],
  ])("%j → %j", (expr, rebuilt) => {
    expect(safeExpression(expr).fn).toBe(rebuilt);
  });

  it("rebuilds expressions both samplers evaluate", () => {
    const at = (expr: string) => {
      const fn = safeExpression(expr).fn;
      const point = EvalBuiltIn({ fn }, "fn", { x: 2 }) as number;
      const box = EvalInterval({ fn }, "fn", { x: { lo: 2, hi: 2 } }) as { lo: number; hi: number };
      expect(box.lo).toBeCloseTo(point, 9);
      return point;
    };
    expect(at("sin(x)")).toBeCloseTo(Math.sin(2), 12);
    expect(at("x^2 + 3*x - 1")).toBeCloseTo(9, 12);
    expect(at("sqrt(abs(x))")).toBeCloseTo(Math.SQRT2, 12);
    expect(at("2*pi*x")).toBeCloseTo(4 * Math.PI, 12);
    expect(at("ln(e^x)")).toBeCloseTo(2, 12);
  });

  it("plots a fence written as a definition", () => {
    const res = parsePlotSpec("plot: y = x^2; color=red\nfn: f(x) = sqrt(abs(x))");
    expect(res.ok && res.spec.data.map((d) => d.fn)).toEqual(["x ^ 2", "sqrt ( abs ( x ) )"]);
  });

  it("samples point by point when the interval sampler lacks a function", () => {
    const res = parsePlotSpec("plot: floor(x) + cbrt(x)");
    expect(res.ok && res.spec.data[0]).toMatchObject({ sampler: "builtIn", graphType: "polyline" });
    const fn = res.ok ? res.spec.data[0].fn : "";
    expect(EvalBuiltIn({ fn }, "fn", { x: 8 })).toBe(10);
  });
});

describe("parsePlotSpec", () => {
  it("parses a full spec into validated fields only", () => {
    const res = parsePlotSpec(
      [
        "# a comment",
        "title: Sine and square",
        "plot: sin(x); color=#1f77b4; graphType=polyline",
        "fn: x^2; color=SteelBlue; closed=true",
        "xdomain: [-5, 5]",
        "ydomain: -2 to 2",
        "grid: false",
        "unknown: ignored",
      ].join("\n"),
    );
    expect(res).toEqual({
      ok: true,
      spec: {
        title: "Sine and square",
        grid: false,
        xAxis: { domain: [-5, 5] },
        yAxis: { domain: [-2, 2] },
        data: [
          { fn: "sin ( x )", color: "#1f77b4", graphType: "polyline" },
          { fn: "x ^ 2", color: "SteelBlue", closed: true },
        ],
      },
    });
  });

  it.each([
    ["no plot line", "title: nothing"],
    ["colour as a url", "plot: x; color=url(https://attacker.example/#a)"],
    ["colour as css", "plot: x; color=red;fill:blue"],
    ["colour as script", "plot: x; color=javascript:alert(1)"],
    ["colour not on the list", "plot: x; color=hotpink"],
    ["bad hex", "plot: x; color=#12"],
    ["graph type off the enum", "plot: x; graphType=constructor"],
    ["graph type text", "plot: x; graphType=text"],
    ["closed not boolean", "plot: x; closed=yes"],
    ["fnType smuggled", "plot: x; fnType=implicit"],
    ["sampler smuggled", "plot: x; sampler=builtIn"],
    ["option not key=value", "plot: x; [1]"],
    ["domain not numbers", "plot: x\nxdomain: [a, b]"],
    ["domain reversed", "plot: x\nxdomain: [5, -5]"],
    ["domain with code", "plot: x\nydomain: [0, 1] + alert(1)"],
    ["title with markup", "plot: x\ntitle: <img src=x onerror=alert(1)>"],
    ["title too long", `plot: x\ntitle: ${"a".repeat(121)}`],
    ["grid not boolean", "plot: x\ngrid: maybe"],
    ["too many series", Array.from({ length: MAX_SERIES + 1 }, () => "plot: x").join("\n")],
    ["one bad series among good", "plot: sin(x)\nplot: x + ['a']"],
  ])("rejects %s", (_label, spec) => {
    expect(parsePlotSpec(spec).ok).toBe(false);
  });

  it("allows hex and named colours only", () => {
    expect(isSafeColor("#abc")).toBe(true);
    expect(isSafeColor("#aabbccdd")).toBe(true);
    expect(isSafeColor("Crimson")).toBe(true);
    expect(isSafeColor("constructor")).toBe(false);
    expect(isSafeColor("rgb(1,2,3)")).toBe(false);
  });
});

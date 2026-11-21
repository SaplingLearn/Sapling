/**
 * The Graph block: a function plotter and four chart kinds, as SVG.
 *
 * Ported from `designs/notes-graph.js`. The expression parser, the view
 * model, the tick choice and every drawing rule are the handoff's; what
 * changed is that this file renders and nothing else — the DOM wiring
 * (dragging a curve, dragging a bar, zoom) lives in `useNoteGraphs`, so the
 * maths can be tested on its own.
 */

/** The plot's intrinsic size. Everything is drawn in this space and scaled. */
export const W = 720;
export const H = 420;

/** The series colours, in the order a new expression takes them. */
export const PALETTE = ["#445D22", "#2E5F96", "#B4562C", "#7B4B99", "#A8456B", "#207878"];

/** The functions and constants an expression may use. */
const F: Record<string, number | ((...a: number[]) => number)> = {
  sin: Math.sin, cos: Math.cos, tan: Math.tan,
  asin: Math.asin, acos: Math.acos, atan: Math.atan,
  sqrt: Math.sqrt, abs: Math.abs, log: Math.log10, ln: Math.log, exp: Math.exp,
  floor: Math.floor, ceil: Math.ceil, round: Math.round, min: Math.min, max: Math.max,
  pi: Math.PI, e: Math.E,
};
const NAMES = Object.keys(F);

export function esc(s: unknown): string {
  return String(s ?? "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/"/g, "&quot;");
}

/** A number as an axis label: short, with a real minus sign. */
export function fmt(n: number): string {
  if (!Number.isFinite(n)) return "–";
  const a = Math.abs(n);
  const v = a >= 1000 || (a < 0.01 && a > 0) ? n.toPrecision(3) : String(+n.toFixed(3));
  return v.replace("-", "−");
}

const num = (v: number) => String(+(+v).toFixed(3));

const SUP: Record<string, string> = {
  0: "⁰", 1: "¹", 2: "²", 3: "³", 4: "⁴", 5: "⁵", 6: "⁶", 7: "⁷", 8: "⁸", 9: "⁹", "-": "⁻",
};

/** `x^2 - 2*x` as `x² − 2·x`, for the legend. */
export function pretty(t: string): string {
  return String(t)
    .replace(/\^(-?\d+)/g, (_, d: string) => d.split("").map(c => SUP[c]).join(""))
    .replace(/\s*\*\s*/g, "·")
    .replace(/-/g, "−");
}

/** The nearest 1, 2, 5 or 10 × a power of ten — what an axis steps by. */
export function nice(raw: number): number {
  const p = Math.pow(10, Math.floor(Math.log10(raw)));
  const m = raw / p;
  return (m < 1.5 ? 1 : m < 3.5 ? 2 : m < 7.5 ? 5 : 10) * p;
}

/**
 * Rewrite what a student types into something JavaScript evaluates: `2x`
 * becomes `2*x`, `^` becomes `**`, `π` becomes `pi`, and a run of letters that
 * is not a known function is split into a product (`xy` → `x*y`).
 */
function prep(src: string): string {
  let s = String(src).trim()
    .replace(/−/g, "-").replace(/·|×/g, "*").replace(/π/g, "pi").replace(/\^/g, "**");
  s = s.replace(/[a-zA-Z]+/g, w => (NAMES.includes(w) ? w : w.split("").join("*")));
  s = s.replace(/(\d|\.)\s*([a-zA-Z(])/g, "$1*$2")
    .replace(/\)\s*([a-zA-Z0-9(])/g, ")*$1")
    .replace(/(^|[^a-zA-Z_])([a-zA-Z])\s*\(/g,
      (m, p: string, l: string) => (NAMES.includes(l) ? m : `${p}${l}*(`));
  return s;
}

/** The single letters in an expression that are parameters, not `x` or `e`. */
function paramsOf(s: string): string[] {
  return [...new Set((s.match(/[a-zA-Z]+/g) || []).filter(w => w.length === 1 && !"xye".includes(w)))]
    .sort();
}

export type CompiledKind = "fn" | "pt" | "vx" | "empty" | "err";

export interface Compiled {
  kind: CompiledKind;
  params: string[];
  /** `fn`: y of x. `pt`: the point. `vx`: the x of a vertical line. */
  fn?: (x: number, p: Record<string, number>) => number;
  point?: (p: Record<string, number>) => [number, number];
  vx?: (p: Record<string, number>) => number;
}

/**
 * Compile one expression row. Three shapes are understood: `(a, b)` is a
 * point, `x = …` is a vertical line, and anything else is `y = f(x)`.
 * A failure is `kind: "err"` — the row turns red, nothing throws.
 */
export function compile(src: string): Compiled {
  let s = String(src || "").trim();
  if (!s) return { kind: "empty", params: [] };
  try {
    const pt = s.match(/^\(\s*([^,]+),\s*([^)]+)\)$/);
    if (pt) {
      const a = prep(pt[1]);
      const b = prep(pt[2]);
      const ps = paramsOf(`${a} ${b}`);
      const fa = new Function("F", ...ps, `with(F){return (${a});}`) as (...x: unknown[]) => number;
      const fb = new Function("F", ...ps, `with(F){return (${b});}`) as (...x: unknown[]) => number;
      return {
        kind: "pt", params: ps,
        point: p => [fa(F, ...ps.map(k => p[k])), fb(F, ...ps.map(k => p[k]))],
      };
    }

    const vx = s.match(/^x\s*=\s*(.+)$/);
    if (vx) {
      const a = prep(vx[1]);
      const ps = paramsOf(a);
      const fa = new Function("F", ...ps, `with(F){return (${a});}`) as (...x: unknown[]) => number;
      return { kind: "vx", params: ps, vx: p => fa(F, ...ps.map(k => p[k])) };
    }

    s = s.replace(/^(y|f\s*\(\s*x\s*\))\s*=\s*/, "");
    const e = prep(s);
    const ps = paramsOf(e);
    const f = new Function("F", ...ps, "x", `with(F){return (${e});}`) as (...x: unknown[]) => number;
    // Probe once so a syntactically valid but unevaluable expression fails here.
    const probe: Record<string, number> = {};
    ps.forEach(p => { probe[p] = 1; });
    f(F, ...ps.map(k => probe[k]), 0.5);
    return { kind: "fn", params: ps, fn: (x, p) => f(F, ...ps.map(k => p[k]), x) };
  } catch {
    return { kind: "err", params: [] };
  }
}

/**
 * Shift `y = f(x)` by (h, k) and write it back as readable text — how dragging
 * a curve edits the expression that produced it.
 */
export function compose(base: string, h: number, k: number): string {
  let s = String(base).trim().replace(/^(y|f\s*\(\s*x\s*\))\s*=\s*/, "");
  if (!h && !k) return s;
  if (h) {
    s = s.replace(/[a-zA-Z]+/g, w => (NAMES.includes(w)
      ? w
      : w.split("").map(c => (c === "x"
        ? `(x ${h > 0 ? "-" : "+"} ${num(Math.abs(h))})`
        : c)).join("")))
      .replace(/\(\((x [+-] [\d.]+)\)\)/g, "($1)");
  }
  if (k) s = `${s} ${k > 0 ? "+" : "-"} ${num(Math.abs(k))}`;
  return s;
}

/** The plot's window: the world point at its centre, and world-units per pixel. */
export interface View { cx: number; cy: number; s: number }

export const DEFAULT_VIEW: View = { cx: 0, cy: 0, s: 20 / W };

export function parseView(raw: string | null | undefined): View {
  const [cx, cy, s] = String(raw || "0,0,0.0278").split(",").map(Number);
  return {
    cx: Number.isFinite(cx) ? cx : 0,
    cy: Number.isFinite(cy) ? cy : 0,
    s: Number.isFinite(s) && s > 0 ? s : DEFAULT_VIEW.s,
  };
}

export const viewAttr = (v: View) => `${v.cx},${v.cy},${v.s}`;

/** Zoom by `factor` about the pixel (px, py), keeping that point still. */
export function zoomView(v: View, factor: number, px: number, py: number): View {
  const x = v.cx + (px - W / 2) * v.s;
  const y = v.cy - (py - H / 2) * v.s;
  const s = Math.min(50, Math.max(1e-4, v.s * factor));
  return { cx: x - (px - W / 2) * s, cy: y + (py - H / 2) * s, s };
}

export interface PlotRow {
  /** What the student typed. */
  src: string;
  color: string;
  /** Pan offsets applied by dragging, so the base expression is not lost. */
  h?: number;
  k?: number;
}

export interface PlotModel {
  /** Pixel → world, and back. */
  X: (px: number) => number;
  Y: (py: number) => number;
  /** The axis step the grid is drawn at — what a drag snaps to. */
  step: number;
}

/** A trace readout: the pointer's pixel position, for the nearest-curve dot. */
export interface Trace { px: number; py: number }

/**
 * Draw the function plot. Returns the SVG body (no `<svg>` wrapper) and the
 * model the pointer handlers need to turn pixels back into world units.
 */
export function renderPlot(
  rows: PlotRow[], view: View, params: Record<string, number>, trace?: Trace,
): { svg: string; model: PlotModel } {
  const X = (px: number) => view.cx + (px - W / 2) * view.s;
  const Y = (py: number) => view.cy - (py - H / 2) * view.s;
  const PX = (x: number) => W / 2 + (x - view.cx) / view.s;
  const PY = (y: number) => H / 2 - (y - view.cy) / view.s;

  const step = nice(80 * view.s);
  const minorDiv = Math.round(step / Math.pow(10, Math.floor(Math.log10(step)))) === 2 ? 4 : 5;
  const minor = step / minorDiv;

  let g = "";
  for (let x = Math.ceil(X(0) / minor) * minor; x <= X(W); x += minor) {
    g += `<line x1="${PX(x).toFixed(1)}" y1="0" x2="${PX(x).toFixed(1)}" y2="${H}" stroke="#F3F0EA"/>`;
  }
  for (let y = Math.ceil(Y(H) / minor) * minor; y <= Y(0); y += minor) {
    g += `<line x1="0" y1="${PY(y).toFixed(1)}" x2="${W}" y2="${PY(y).toFixed(1)}" stroke="#F3F0EA"/>`;
  }

  // The axes stay on screen when the origin is panned off it, so the numbers
  // always have something to hang from.
  const ax = Math.min(H - 6, Math.max(14, PY(0)));
  const ay = Math.min(W - 6, Math.max(6, PX(0)));

  for (let x = Math.ceil(X(0) / step) * step; x <= X(W); x += step) {
    const px = PX(x);
    g += `<line x1="${px.toFixed(1)}" y1="0" x2="${px.toFixed(1)}" y2="${H}" stroke="#E4DFD3"/>`;
    if (Math.abs(x) > step / 2) {
      const ty = ax + 15 > H - 4 ? ax - 6 : ax + 15;
      g += `<text x="${px.toFixed(1)}" y="${ty.toFixed(1)}" text-anchor="middle" `
        + `class="pl-num">${fmt(+x.toPrecision(10))}</text>`;
    }
  }
  for (let y = Math.ceil(Y(H) / step) * step; y <= Y(0); y += step) {
    const py = PY(y);
    g += `<line x1="0" y1="${py.toFixed(1)}" x2="${W}" y2="${py.toFixed(1)}" stroke="#E4DFD3"/>`;
    if (Math.abs(y) > step / 2) {
      const left = ay - 6 < 20;
      g += `<text x="${(left ? ay + 6 : ay - 6).toFixed(1)}" y="${(py + 4).toFixed(1)}" `
        + `text-anchor="${left ? "start" : "end"}" class="pl-num">${fmt(+y.toPrecision(10))}</text>`;
    }
  }
  g += `<line x1="0" y1="${PY(0).toFixed(1)}" x2="${W}" y2="${PY(0).toFixed(1)}" `
    + 'stroke="#6F6857" stroke-width="1.2"/>'
    + `<line x1="${PX(0).toFixed(1)}" y1="0" x2="${PX(0).toFixed(1)}" y2="${H}" `
    + 'stroke="#6F6857" stroke-width="1.2"/>';

  const compiled = rows.map(r => ({ ...r, ...compile(r.src) }));
  let points = "";
  compiled.forEach((r, i) => {
    try {
      if (r.kind === "fn" && r.fn) {
        let d = "";
        let prev: number | null = null;
        for (let px = -2; px <= W + 2; px += 1.5) {
          const y = r.fn(X(px), params);
          const py = PY(y);
          // A jump bigger than the canvas is an asymptote, not a line: break.
          if (!Number.isFinite(py) || Math.abs(py) > H * 8) { prev = null; continue; }
          d += (prev === null || Math.abs(py - prev) > H * 1.5 ? "M" : "L")
            + `${px.toFixed(1)},${py.toFixed(1)}`;
          prev = py;
        }
        g += `<g class="pl-fg"><path class="pl-vis" d="${d}" stroke="${r.color}"/>`
          + `<path class="pl-hit" data-r="${i}" d="${d}"/></g>`;
      } else if (r.kind === "vx" && r.vx) {
        const px = PX(r.vx(params));
        if (Number.isFinite(px)) {
          const d = `M${px.toFixed(1)},0V${H}`;
          g += `<g class="pl-fg"><path class="pl-vis" d="${d}" stroke="${r.color}"/>`
            + `<path class="pl-hit pl-hit-x" data-r="${i}" d="${d}"/></g>`;
        }
      } else if (r.kind === "pt" && r.point) {
        const [x, y] = r.point(params);
        if (Number.isFinite(x) && Number.isFinite(y)) {
          // A point with no parameters can be dragged; one driven by a slider cannot.
          points += `<circle class="pl-pt${r.params.length ? "" : " pl-drag"}" data-r="${i}" `
            + `cx="${PX(x).toFixed(1)}" cy="${PY(y).toFixed(1)}" r="6" fill="${r.color}"/>`
            + `<text x="${(PX(x) + 11).toFixed(1)}" y="${(PY(y) - 11).toFixed(1)}" `
            + `class="pl-lab">(${fmt(x)}, ${fmt(y)})</text>`;
        }
      }
    } catch { /* one bad row never stops the others */ }
  });
  g += points;

  if (trace) {
    let best: { d: number; x: number; y: number; px: number; py: number; c: string } | null = null;
    const x = X(trace.px);
    compiled.forEach(r => {
      if (r.kind !== "fn" || !r.fn) return;
      let y: number;
      try { y = r.fn(x, params); } catch { return; }
      const py = PY(y);
      if (!Number.isFinite(py)) return;
      const d = Math.abs(py - trace.py);
      if (d < 36 && (!best || d < best.d)) best = { d, x, y, px: trace.px, py, c: r.color };
    });
    if (best) {
      const b = best as { x: number; y: number; px: number; py: number; c: string };
      const t = `(${fmt(b.x)}, ${fmt(b.y)})`;
      const tw = t.length * 7.6 + 16;
      const tx = Math.min(W - tw - 4, b.px + 12);
      const ty = Math.max(4, b.py - 34);
      g += `<circle cx="${b.px.toFixed(1)}" cy="${b.py.toFixed(1)}" r="5" fill="#FFFFFF" `
        + `stroke="${b.c}" stroke-width="2.5" pointer-events="none"/>`
        + `<g pointer-events="none"><rect x="${tx.toFixed(1)}" y="${ty.toFixed(1)}" `
        + `width="${tw.toFixed(1)}" height="24" rx="6" fill="#1A1814" opacity="0.88"/>`
        + `<text x="${(tx + 8).toFixed(1)}" y="${(ty + 16).toFixed(1)}" class="pl-tip">${t}</text></g>`;
    }
  }

  return { svg: g, model: { X, Y, step } };
}

/** The legend shown under a finalized function plot. */
export function renderLegend(rows: PlotRow[], params: Record<string, number>): string {
  const live = rows.map(r => ({ ...r, ...compile(r.src) }))
    .filter(r => r.kind !== "empty" && r.kind !== "err");
  const names = Object.keys(params);
  return live.map(r => {
    const label = r.kind === "fn" && !/^\s*(y|f\s*\(\s*x\s*\))\s*=/.test(r.src)
      ? `y = ${r.src}`
      : r.src;
    return `<span class="pl-li"><span class="pl-dot" style="background:${r.color}"></span>`
      + `${esc(pretty(label))}</span>`;
  }).join("")
    + (names.length
      ? `<span class="pl-li pl-pv">${names.map(p => `${p} = ${fmt(params[p])}`).join(", ")}</span>`
      : "");
}

export type ChartKind = "bar" | "line" | "scatter" | "pie";

/** A chart's rows: a label (or an x value, for a scatter) and a number. */
export type ChartRow = [string, number];

export interface ChartModel {
  kind: ChartKind;
  /** Pixel → value, for dragging a bar or a point. */
  toValue?: (py: number) => number;
  toX?: (px: number) => number;
  lo?: number;
  hi?: number;
  step?: number;
  xLo?: number;
  xHi?: number;
  xStep?: number;
  /** Pie only: each slice's start and end angle, and the total. */
  starts?: number[];
  ends?: number[];
  total?: number;
  cx?: number;
  cy?: number;
}

/** The chart axes are frozen while a drag is running, so they do not jump. */
export interface ChartFreeze {
  lo: number; hi: number; step: number;
  xLo?: number; xHi?: number; xStep?: number;
}

const CHART_PAD = { l: 56, r: 24, t: 54, b: 44 };

/** Draw a chart. Returns the SVG body and the model the drags need. */
export function renderChart(
  kind: ChartKind, title: string, rows: ChartRow[], freeze?: ChartFreeze | null,
): { svg: string; model: ChartModel | null } {
  let g = `<text x="${W / 2}" y="30" text-anchor="middle" class="ch-ttl">${esc(title)}</text>`;
  const data = rows.filter(([l, v]) => l !== "" && Number.isFinite(v));
  if (!data.length) return { svg: g, model: null };

  const iw = W - CHART_PAD.l - CHART_PAD.r;
  const ih = H - CHART_PAD.t - CHART_PAD.b;

  if (kind === "pie") {
    const total = data.reduce((a, [, v]) => a + Math.max(0, v), 0) || 1;
    const cx = 230;
    const cy = H / 2 + 14;
    const r = 140;
    let a0 = -Math.PI / 2;
    const starts: number[] = [];
    const ends: number[] = [];
    data.forEach(([l, v], i) => {
      const fr = Math.max(0, v) / total;
      const a1 = a0 + fr * Math.PI * 2;
      const big = a1 - a0 > Math.PI ? 1 : 0;
      const c = PALETTE[i % PALETTE.length];
      // A single slice covering everything cannot be drawn as an arc to itself.
      const p = fr >= 0.9999
        ? `M${cx},${cy - r}A${r},${r} 0 1 1 ${cx - 0.01},${cy - r}Z`
        : `M${cx},${cy}L${(cx + r * Math.cos(a0)).toFixed(1)},${(cy + r * Math.sin(a0)).toFixed(1)}`
          + `A${r},${r} 0 ${big} 1 ${(cx + r * Math.cos(a1)).toFixed(1)},`
          + `${(cy + r * Math.sin(a1)).toFixed(1)}Z`;
      starts.push(a0 + Math.PI / 2);
      ends.push(a1 + Math.PI / 2);
      g += `<path class="ch-hit" d="${p}" fill="${c}" stroke="#FFFFFF" stroke-width="2" `
        + `data-tip="${esc(l)}: ${fmt(v)} (${Math.round(fr * 100)}%)"/>`;
      const ly = cy - data.length * 16 + i * 32;
      g += `<rect x="440" y="${ly.toFixed(1)}" width="14" height="14" rx="4" fill="${c}"/>`
        + `<text x="464" y="${(ly + 12).toFixed(1)}" class="ch-leg">`
        + `${esc(l)} · ${Math.round(fr * 100)}%</text>`;
      a0 = a1;
    });
    // A handle on each internal boundary drags the split between two slices.
    for (let i = 0; i < data.length - 1; i += 1) {
      const a = ends[i] - Math.PI / 2;
      g += `<circle class="ch-drag pie-h" data-i="${i}" `
        + `cx="${(cx + r * Math.cos(a)).toFixed(1)}" cy="${(cy + r * Math.sin(a)).toFixed(1)}" r="8"/>`;
    }
    return { svg: g, model: { kind, starts, ends, total, cx, cy } };
  }

  const values = data.map(([, v]) => v);
  let lo = Math.min(0, ...values);
  let hi = Math.max(0, ...values);
  if (hi === lo) hi = lo + 1;
  let step = nice((hi - lo) / 5);
  lo = Math.floor(lo / step) * step;
  hi = Math.ceil(hi / step) * step;
  if (freeze) { lo = freeze.lo; hi = freeze.hi; step = freeze.step; }

  const sy = (y: number) => CHART_PAD.t + ih - (y - lo) / (hi - lo) * ih;
  const toValue = (py: number) => lo + (CHART_PAD.t + ih - py) / ih * (hi - lo);

  for (let y = lo; y <= hi + step / 2; y += step) {
    g += `<line x1="${CHART_PAD.l}" y1="${sy(y).toFixed(1)}" x2="${W - CHART_PAD.r}" `
      + `y2="${sy(y).toFixed(1)}" stroke="${Math.abs(y) < step / 2 ? "#8A8372" : "#EFEBE2"}"/>`
      + `<text x="${CHART_PAD.l - 10}" y="${(sy(y) + 4).toFixed(1)}" text-anchor="end" `
      + `class="pl-num">${fmt(+y.toPrecision(10))}</text>`;
  }

  if (kind === "scatter") {
    const xs = data.map(([l]) => parseFloat(l)).filter(Number.isFinite);
    if (!xs.length) return { svg: g, model: null };
    let xLo = Math.min(...xs);
    let xHi = Math.max(...xs);
    if (xHi === xLo) xHi = xLo + 1;
    let xStep = nice((xHi - xLo) / 6);
    xLo = Math.floor(xLo / xStep) * xStep;
    xHi = Math.ceil(xHi / xStep) * xStep;
    if (freeze?.xLo !== undefined) { xLo = freeze.xLo; xHi = freeze.xHi!; xStep = freeze.xStep!; }
    const sx = (x: number) => CHART_PAD.l + (x - xLo) / (xHi - xLo) * iw;

    for (let x = xLo; x <= xHi + xStep / 2; x += xStep) {
      g += `<text x="${sx(x).toFixed(1)}" y="${H - CHART_PAD.b + 22}" text-anchor="middle" `
        + `class="pl-num">${fmt(+x.toPrecision(10))}</text>`;
    }
    // A least-squares line, when there is more than one point to fit.
    if (xs.length > 1 && xs.length === values.length) {
      const n = xs.length;
      const mx = xs.reduce((a, b) => a + b) / n;
      const my = values.reduce((a, b) => a + b) / n;
      const sxx = xs.reduce((a, x) => a + (x - mx) ** 2, 0);
      if (sxx > 0) {
        const m = xs.reduce((a, x, i) => a + (x - mx) * (values[i] - my), 0) / sxx;
        const c0 = my - m * mx;
        g += `<line x1="${sx(xLo).toFixed(1)}" y1="${sy(m * xLo + c0).toFixed(1)}" `
          + `x2="${sx(xHi).toFixed(1)}" y2="${sy(m * xHi + c0).toFixed(1)}" `
          + 'stroke="#B8873F" stroke-width="2" stroke-dasharray="6 5"/>'
          + `<text x="${W - CHART_PAD.r}" y="${CHART_PAD.t - 8}" text-anchor="end" `
          + `class="pl-lab">y = ${fmt(m)}x ${c0 < 0 ? "−" : "+"} ${fmt(Math.abs(c0))}</text>`;
      }
    }
    xs.forEach((x, i) => {
      g += `<circle class="ch-hit ch-drag" data-i="${i}" cx="${sx(x).toFixed(1)}" `
        + `cy="${sy(values[i]).toFixed(1)}" r="7" fill="#445D22" fill-opacity="0.88" `
        + `data-tip="(${fmt(x)}, ${fmt(values[i])})"/>`;
    });
    return {
      svg: g,
      model: {
        kind, lo, hi, step, xLo, xHi, xStep, toValue,
        toX: (px: number) => xLo + (px - CHART_PAD.l) / iw * (xHi - xLo),
      },
    };
  }

  // A bar chart that is still editable keeps one slot free for "+".
  const addSlot = !freeze && kind === "bar";
  const bw = iw / (data.length + (addSlot ? 1 : 0));
  const cxs = data.map((_, i) => CHART_PAD.l + bw * (i + 0.5));

  data.forEach(([l], i) => {
    g += `<text x="${cxs[i].toFixed(1)}" y="${H - CHART_PAD.b + 22}" text-anchor="middle" `
      + `class="pl-num">${esc(l)}</text>`;
  });

  if (kind === "bar") {
    data.forEach(([l, v], i) => {
      const y0 = sy(0);
      const y1 = sy(v);
      const w = Math.min(64, bw * 0.62);
      g += `<rect class="ch-hit ch-drag" data-i="${i}" x="${(cxs[i] - w / 2).toFixed(1)}" `
        + `y="${Math.min(y0, y1).toFixed(1)}" width="${w.toFixed(1)}" `
        + `height="${Math.max(1, Math.abs(y1 - y0)).toFixed(1)}" rx="5" fill="#445D22" `
        + `data-tip="${esc(l)}: ${fmt(v)}"/>`
        + `<rect class="ch-grip" x="${(cxs[i] - 11).toFixed(1)}" y="${(y1 - 3).toFixed(1)}" `
        + 'width="22" height="6" rx="3"/>';
    });
  } else {
    g += `<path d="${data.map(([, v], i) => (i ? "L" : "M") + cxs[i].toFixed(1) + "," + sy(v).toFixed(1)).join("")}" `
      + 'fill="none" stroke="#445D22" stroke-width="2.8" stroke-linejoin="round"/>';
    data.forEach(([l, v], i) => {
      g += `<circle class="ch-hit ch-drag" data-i="${i}" cx="${cxs[i].toFixed(1)}" `
        + `cy="${sy(v).toFixed(1)}" r="6" fill="#FFFFFF" stroke="#445D22" stroke-width="2.5" `
        + `data-tip="${esc(l)}: ${fmt(v)}"/>`;
    });
  }

  if (addSlot) {
    const ax = CHART_PAD.l + bw * (data.length + 0.5);
    const w = Math.min(64, bw * 0.62);
    g += '<g class="ch-add" data-act="g-rowadd2">'
      + `<rect x="${(ax - w / 2).toFixed(1)}" y="${(CHART_PAD.t + ih * 0.35).toFixed(1)}" `
      + `width="${w.toFixed(1)}" height="${(ih * 0.65).toFixed(1)}" rx="6"/>`
      + `<text x="${ax.toFixed(1)}" y="${(CHART_PAD.t + ih * 0.675 + 8).toFixed(1)}" `
      + 'text-anchor="middle">+</text></g>';
  }

  return { svg: g, model: { kind, lo, hi, step, toValue } };
}

/** Snap a dragged value to a tenth of the axis step, as the prototype does. */
export function snap(v: number, step: number): number {
  const q = step / 10;
  return +(Math.round(v / q) * q).toPrecision(12);
}

/** The default data each chart kind starts with. */
export const CHART_DATA: Record<ChartKind, { title: string; rows: ChartRow[] }> = {
  bar: {
    title: "Study Hours",
    rows: [["Mon", 3], ["Tue", 5], ["Wed", 2], ["Thu", 6], ["Fri", 4]],
  },
  line: {
    title: "Quiz Scores",
    rows: [["Wk 1", 62], ["Wk 2", 70], ["Wk 3", 68], ["Wk 4", 81], ["Wk 5", 88]],
  },
  scatter: {
    title: "Hours vs. Score",
    rows: [["1", 58], ["2", 64], ["3", 70], ["4", 73], ["5", 82], ["6", 88]],
  },
  pie: {
    title: "Grade Weighting",
    rows: [["Lectures", 35], ["Readings", 25], ["Labs", 20], ["Exams", 20]],
  },
};

/** The two expressions a new function plot opens with. */
export const DEFAULT_EXPRS = ["x^2 - 2x - 3", "(1, -4)"];

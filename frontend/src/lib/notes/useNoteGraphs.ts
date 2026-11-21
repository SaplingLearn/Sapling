"use client";
/**
 * The Graph block's behaviour: build one, render it, and let the student edit
 * it by dragging the picture — a curve, a point, a bar, a scatter dot, a pie
 * boundary — with the expression or the value written back as they go.
 *
 * Ported from the plot/chart half of `designs/notes-graph.js`. The drawing and
 * the maths live in `graphs.ts` and are tested there; this is the DOM.
 */
import React from "react";

import {
  CHART_DATA, DEFAULT_EXPRS, PALETTE, W, H, compile, compose, esc, fmt,
  parseView, renderChart, renderLegend, renderPlot, snap, viewAttr, zoomView,
  type ChartFreeze, type ChartKind, type ChartModel, type ChartRow,
  type PlotModel, type PlotRow, type Trace, type View,
} from "./graphs";
import { GRAPH_KINDS, X } from "./blocks";
import { useLatest } from "./useLatest";

/** A plot row's expression input. */
const exprRow = (value: string, color: string) =>
  `<div class="pl-row" data-c="${color}"><span class="pl-dot" style="background:${color}"></span>`
  + `<input class="pl-expr" type="text" spellcheck="false" value="${esc(value)}" `
  + 'aria-label="Expression">'
  + '<button class="pl-del" data-act="g-del" aria-label="Remove">×</button></div>';

/** A chart row's label + value inputs. */
const chartRow = (label: string | number, value: string | number) =>
  '<div class="ch-row">'
  + `<input class="ch-l" type="text" value="${esc(label)}" placeholder="Label" aria-label="Label">`
  + `<input class="ch-v" type="text" value="${esc(value)}" placeholder="0" aria-label="Value">`
  + '<button class="pl-del" data-act="g-rowdel" aria-label="Remove">×</button></div>';

export interface GraphOptions {
  kind?: ChartKind | "fn";
  exprs?: string[];
  title?: string;
  rows?: ChartRow[];
  view?: string;
  final?: boolean;
}

/** The markup for a new graph block. */
export function graphHTML(o: GraphOptions = {}): string {
  const kind = o.kind || "fn";
  const data = o.rows
    ? { title: o.title || "", rows: o.rows }
    : CHART_DATA[kind === "fn" ? "bar" : kind];
  const exprs = o.exprs?.length ? o.exprs : DEFAULT_EXPRS;

  return `<div class="blk gx" contenteditable="false" data-blk="graph" data-kind="${kind}" `
    + `data-view="${o.view || `0,0,${(20 / W).toFixed(6)}`}" data-final="${o.final ? 1 : 0}">${X}`
    + '<div class="g-head"><div class="g-kinds">'
    + GRAPH_KINDS.map(k => `<button data-act="g-kind" data-k="${k.key}" `
      + `class="${k.key === kind ? "on" : ""}">`
      + '<svg viewBox="0 0 18 18" fill="none" stroke="currentColor" stroke-width="1.7" '
      + `stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="${k.icon}"/></svg>`
      + `${k.label}</button>`).join("")
    + '</div><span class="g-sp"></span>'
    + '<button class="g-btn g-done" data-act="g-final">Done</button>'
    + '<button class="g-btn g-edit" data-act="g-edit">Edit</button></div>'
    + '<div class="g-body"><div class="g-side">'
    + '<div class="fn-side"><div class="pl-list">'
    + exprs.map((e, i) => exprRow(e, PALETTE[i % PALETTE.length])).join("")
    + '</div><button class="g-link" data-act="g-add">Add expression</button>'
    + '<div class="pl-sliders"></div></div>'
    + `<div class="ch-side"><input class="ch-title" type="text" value="${esc(data.title)}" `
    + 'placeholder="Title" aria-label="Chart title">'
    + `<div class="ch-rows">${data.rows.map(([l, v]) => chartRow(l, v)).join("")}</div>`
    + '<button class="g-link" data-act="g-rowadd">Add row</button></div>'
    + '</div><div class="pl-canvas ch-canvas">'
    + `<svg class="pl-svg" viewBox="0 0 ${W} ${H}"></svg>`
    + `<svg class="ch-svg" viewBox="0 0 ${W} ${H}"></svg>`
    + '<div class="pl-zoom"><button data-act="g-zin" aria-label="Zoom in">+</button>'
    + '<button data-act="g-zout" aria-label="Zoom out">−</button>'
    + '<button data-act="g-home" aria-label="Reset view">⌂</button></div>'
    + '<div class="ch-tip"></div><div class="pl-legend"></div></div></div></div><p><br></p>';
}

/** Per-block state the renderer and the drags share. */
interface BlockState {
  plot?: PlotModel;
  chart?: ChartModel | null;
  freeze?: ChartFreeze | null;
}

const STATE = new WeakMap<HTMLElement, BlockState>();

const plotRows = (b: HTMLElement): PlotRow[] =>
  [...b.querySelectorAll<HTMLElement>(".pl-row")].map(r => ({
    src: r.querySelector<HTMLInputElement>(".pl-expr")?.value ?? "",
    color: r.dataset.c || PALETTE[0],
    h: Number(r.dataset.h) || 0,
    k: Number(r.dataset.k) || 0,
  }));

const paramValues = (b: HTMLElement): Record<string, number> => {
  const p: Record<string, number> = {};
  b.querySelectorAll<HTMLElement>(".pl-sl").forEach(s => {
    p[s.dataset.p!] = parseFloat(s.querySelector<HTMLInputElement>("input")!.value);
  });
  return p;
};

const chartRows = (b: HTMLElement): ChartRow[] =>
  [...b.querySelectorAll<HTMLElement>(".ch-row")].map(r => [
    r.querySelector<HTMLInputElement>(".ch-l")!.value.trim(),
    parseFloat(r.querySelector<HTMLInputElement>(".ch-v")!.value),
  ]);

/** Give every free parameter a slider, and take away the ones nothing uses. */
function syncSliders(b: HTMLElement): void {
  const rows = plotRows(b);
  const needed = [...new Set(rows.flatMap(r => compile(r.src).params))];
  const box = b.querySelector(".pl-sliders");
  if (!box) return;

  const have: Record<string, boolean> = {};
  box.querySelectorAll<HTMLElement>(".pl-sl").forEach(s => {
    if (!needed.includes(s.dataset.p!)) s.remove();
    else have[s.dataset.p!] = true;
  });
  needed.filter(p => !have[p]).forEach(p => {
    box.insertAdjacentHTML("beforeend",
      `<label class="pl-sl" data-p="${p}"><span>${p}</span>`
      + `<input type="range" min="-10" max="10" step="0.1" value="1" aria-label="${p}">`
      + "<output>1</output></label>");
  });
  [...box.querySelectorAll<HTMLElement>(".pl-sl")]
    .sort((x, y) => x.dataset.p!.localeCompare(y.dataset.p!))
    .forEach(s => box.appendChild(s));

  // A row that will not compile is marked, rather than silently drawing nothing.
  [...b.querySelectorAll<HTMLElement>(".pl-row")].forEach((r, i) => {
    r.classList.toggle("bad", compile(rows[i]?.src ?? "").kind === "err");
  });
}

function drawPlot(b: HTMLElement, trace?: Trace): void {
  const svg = b.querySelector(".pl-svg");
  if (!svg) return;
  const { svg: body, model } = renderPlot(
    plotRows(b), parseView(b.dataset.view), paramValues(b), trace,
  );
  svg.innerHTML = body;
  STATE.set(b, { ...STATE.get(b), plot: model });
  const legend = b.querySelector(".pl-legend");
  if (legend) legend.innerHTML = renderLegend(plotRows(b), paramValues(b));
}

function drawChart(b: HTMLElement): void {
  const svg = b.querySelector(".ch-svg");
  if (!svg) return;
  const title = b.querySelector<HTMLInputElement>(".ch-title")?.value ?? "";
  const state = STATE.get(b);
  const { svg: body, model } = renderChart(
    (b.dataset.kind || "bar") as ChartKind, title, chartRows(b), state?.freeze,
  );
  svg.innerHTML = body;
  STATE.set(b, { ...state, chart: model });
}

/** Draw a graph block, whichever kind it is. */
export function drawGraph(b: HTMLElement): void {
  if (!b.dataset.kind || b.dataset.kind === "fn") {
    syncSliders(b);
    drawPlot(b);
  } else {
    drawChart(b);
  }
}

/** Draw every graph block in `root`. */
export function drawAllGraphs(root: HTMLElement): void {
  root.querySelectorAll<HTMLElement>('.blk[data-blk="graph"]').forEach(drawGraph);
}

/** Keep an input's VALUE ATTRIBUTE in step, so the markup survives a save. */
function setInput(el: HTMLInputElement, v: string | number): void {
  el.value = String(v);
  el.setAttribute("value", String(v));
}

interface Drag {
  block: HTMLElement;
  svg: SVGSVGElement;
  /** Panning the plot's background. */
  pan?: { x: number; y: number; view: View };
  /** Dragging a curve, a point, a bar, a dot or a pie boundary. */
  item?: {
    index: number;
    curve: boolean;
    point: boolean;
    verticalLine: boolean;
    row?: HTMLElement;
    input?: HTMLInputElement;
    x0: number;
    y0: number;
    h0: number;
    k0: number;
  };
}

export interface NoteGraphs {
  refresh: () => void;
  /** The markup for a new graph of the given kind. */
  html: (kind: ChartKind | "fn") => string;
}

export interface NoteGraphsInput {
  rootRef: React.RefObject<HTMLElement | null>;
  onChange: () => void;
}

export function useNoteGraphs({ rootRef, onChange }: NoteGraphsInput): NoteGraphs {
  const changeRef = useLatest(onChange);
  const dragRef = React.useRef<Drag | null>(null);

  const refresh = React.useCallback(() => {
    const root = rootRef.current;
    if (root) drawAllGraphs(root);
  }, [rootRef]);

  React.useEffect(() => {
    const root = rootRef.current;
    if (!root) return;

    const svgPoint = (svg: SVGSVGElement, e: PointerEvent) => {
      const r = svg.getBoundingClientRect();
      return {
        px: (e.clientX - r.left) / r.width * W,
        py: (e.clientY - r.top) / r.height * H,
      };
    };

    /** Start dragging a curve, a point, a bar, a dot or a pie boundary. */
    const onItemDown = (e: PointerEvent) => {
      const handle = (e.target as HTMLElement).closest?.(".ch-drag, .pl-drag, .pl-hit");
      if (!handle) return;
      const block = handle.closest(".blk") as HTMLElement | null;
      if (!block || block.dataset.final === "1") return;
      e.preventDefault();
      e.stopPropagation();

      const svg = (handle as SVGElement).ownerSVGElement!;
      try { svg.setPointerCapture(e.pointerId); } catch { /* not every browser */ }

      // A chart's axes are frozen for the drag, so the bar does not chase a
      // rescaled axis as it is pulled.
      const state = STATE.get(block);
      if (state?.chart && block.dataset.kind !== "fn") {
        const c = state.chart;
        STATE.set(block, {
          ...state,
          freeze: {
            lo: c.lo!, hi: c.hi!, step: c.step!,
            xLo: c.xLo, xHi: c.xHi, xStep: c.xStep,
          },
        });
      }

      const index = Number(
        (handle as HTMLElement).dataset.i ?? (handle as HTMLElement).dataset.r,
      );
      const curve = handle.classList.contains("pl-hit");
      const item: NonNullable<Drag["item"]> = {
        index,
        curve,
        point: handle.classList.contains("pl-drag"),
        verticalLine: handle.classList.contains("pl-hit-x"),
        x0: 0, y0: 0, h0: 0, k0: 0,
      };

      if (curve) {
        const model = STATE.get(block)?.plot;
        const p = svgPoint(svg, e);
        const row = block.querySelectorAll<HTMLElement>(".pl-row")[index];
        const input = row?.querySelector<HTMLInputElement>(".pl-expr") ?? undefined;
        // The UNSHIFTED expression is remembered once, so repeated drags
        // compose against the original rather than re-shifting a shifted one.
        if (row && row.dataset.base == null) row.dataset.base = input?.value ?? "";
        Object.assign(item, {
          row,
          input,
          x0: model ? model.X(p.px) : 0,
          y0: model ? model.Y(p.py) : 0,
          h0: Number(row?.dataset.h) || 0,
          k0: Number(row?.dataset.k) || 0,
        });
      }

      dragRef.current = { block, svg, item };
      block.classList.add("dragging");
      const tip = block.querySelector<HTMLElement>(".ch-tip");
      if (tip) tip.style.opacity = "0";
    };

    /** Start panning the plot background. */
    const onCanvasDown = (e: PointerEvent) => {
      const svg = (e.target as HTMLElement).closest?.(".pl-svg") as SVGSVGElement | null;
      if (!svg) return;
      const block = svg.closest(".blk") as HTMLElement | null;
      if (!block || block.dataset.final === "1") return;
      e.preventDefault();
      try { svg.setPointerCapture(e.pointerId); } catch { /* not every browser */ }
      dragRef.current = {
        block, svg,
        pan: { x: e.clientX, y: e.clientY, view: parseView(block.dataset.view) },
      };
      block.classList.add("dragging");
    };

    /** Panning the plot background. */
    const panTo = (drag: Drag, e: PointerEvent): void => {
      if (!drag.pan) return;
      const r = drag.svg.getBoundingClientRect();
      const k = W / r.width;
      const { view } = drag.pan;
      drag.block.dataset.view = viewAttr({
        cx: view.cx - (e.clientX - drag.pan.x) * k * view.s,
        cy: view.cy + (e.clientY - drag.pan.y) * k * view.s,
        s: view.s,
      });
      drawPlot(drag.block);
    };

    /** Dragging a curve: shift it, and write the shift back as the expression. */
    const dragCurve = (drag: Drag, p: { px: number; py: number }): void => {
      const item = drag.item!;
      const model = STATE.get(drag.block)?.plot;
      if (!model || !item.input) return;
      const x = model.X(p.px);
      const y = model.Y(p.py);
      if (item.verticalLine) {
        setInput(item.input, `x = ${snap(x, model.step)}`);
      } else {
        const h = +(item.h0 + snap(x - item.x0, model.step)).toFixed(4);
        const k = +(item.k0 + snap(y - item.y0, model.step)).toFixed(4);
        if (item.row) { item.row.dataset.h = String(h); item.row.dataset.k = String(k); }
        setInput(item.input, compose(item.row?.dataset.base ?? "", h, k));
      }
      drawPlot(drag.block);
    };

    /** Dragging a plotted point: its coordinates follow the pointer. */
    const dragPoint = (drag: Drag, p: { px: number; py: number }): void => {
      const model = STATE.get(drag.block)?.plot;
      const input = drag.block.querySelectorAll<HTMLInputElement>(".pl-expr")[drag.item!.index];
      if (!model || !input) return;
      setInput(input, `(${snap(model.X(p.px), model.step)}, ${snap(model.Y(p.py), model.step)})`);
      drawPlot(drag.block);
    };

    /**
     * Dragging a pie boundary moves value between the two slices it divides,
     * keeping their total — the rest of the pie does not move.
     */
    const dragPie = (
      drag: Drag, model: ChartModel, rows: NodeListOf<HTMLElement>,
      p: { px: number; py: number },
    ): void => {
      const i = drag.item!.index;
      let a = Math.atan2(p.py - model.cy!, p.px - model.cx!) + Math.PI / 2;
      if (a < 0) a += Math.PI * 2;
      const lo = model.starts![i] + 0.04;
      const hi = model.ends![i + 1] - 0.04;
      if (hi <= lo) return;
      a = Math.min(hi, Math.max(lo, a));
      const span = model.ends![i + 1] - model.starts![i];
      const first = rows[i].querySelector<HTMLInputElement>(".ch-v")!;
      const second = rows[i + 1].querySelector<HTMLInputElement>(".ch-v")!;
      const pair = parseFloat(first.value) + parseFloat(second.value);
      const q = pair >= 20 ? 1 : 0.1;
      const v = Math.round((a - model.starts![i]) / span * pair / q) * q;
      setInput(first, +v.toFixed(2));
      setInput(second, +(pair - v).toFixed(2));
      drawChart(drag.block);
    };

    /** Dragging a bar, a line point or a scatter dot. */
    const dragChart = (drag: Drag, p: { px: number; py: number }): void => {
      const model = STATE.get(drag.block)?.chart;
      if (!model) return;
      const rows = drag.block.querySelectorAll<HTMLElement>(".ch-row");
      if (model.kind === "pie") { dragPie(drag, model, rows, p); return; }

      const row = rows[drag.item!.index];
      if (!row || !model.toValue) return;
      const y = Math.min(model.hi!, Math.max(model.lo!, model.toValue(p.py)));
      setInput(row.querySelector<HTMLInputElement>(".ch-v")!, snap(y, model.step!));
      if (model.kind === "scatter" && model.toX) {
        const x = Math.min(model.xHi!, Math.max(model.xLo!, model.toX(p.px)));
        setInput(row.querySelector<HTMLInputElement>(".ch-l")!, snap(x, model.xStep!));
      }
      drawChart(drag.block);
    };

    /** Not dragging: trace the nearest curve, or show a chart tooltip. */
    const hover = (e: PointerEvent): void => {
      const svg = (e.target as HTMLElement).closest?.(".pl-svg") as SVGSVGElement | null;
      if (svg) {
        const block = svg.closest(".blk") as HTMLElement | null;
        if (block) drawPlot(block, svgPoint(svg, e));
        return;
      }
      const canvas = (e.target as HTMLElement).closest?.(".ch-canvas") as HTMLElement | null;
      const tip = canvas?.querySelector<HTMLElement>(".ch-tip");
      if (!canvas || !tip) return;
      const hit = (e.target as HTMLElement).closest?.(".ch-hit") as HTMLElement | null;
      if (!hit) { tip.style.opacity = "0"; return; }
      const r = canvas.getBoundingClientRect();
      const k = canvas.offsetWidth / r.width;
      tip.textContent = hit.getAttribute("data-tip");
      tip.style.left = `${(e.clientX - r.left) * k}px`;
      tip.style.top = `${(e.clientY - r.top) * k}px`;
      tip.style.opacity = "1";
    };

    const onMove = (e: PointerEvent) => {
      const drag = dragRef.current;
      if (!drag) { hover(e); return; }
      if (drag.pan) { panTo(drag, e); return; }
      if (!drag.item) return;

      const p = svgPoint(drag.svg, e);
      if (drag.item.curve) dragCurve(drag, p);
      else if (drag.item.point) dragPoint(drag, p);
      else dragChart(drag, p);
    };

    const onUp = () => {
      const drag = dragRef.current;
      if (!drag) return;
      dragRef.current = null;
      drag.block.classList.remove("dragging");
      STATE.set(drag.block, { ...STATE.get(drag.block), freeze: null });
      drawGraph(drag.block);
      changeRef.current();
    };

    const onOut = (e: PointerEvent) => {
      const svg = (e.target as HTMLElement).closest?.(".pl-svg") as SVGSVGElement | null;
      if (svg && !dragRef.current && !svg.contains(e.relatedTarget as Node)) {
        const block = svg.closest(".blk") as HTMLElement | null;
        if (block) drawPlot(block);
      }
      const canvas = (e.target as HTMLElement).closest?.(".ch-canvas") as HTMLElement | null;
      if (canvas && !canvas.contains(e.relatedTarget as Node)) {
        const tip = canvas.querySelector<HTMLElement>(".ch-tip");
        if (tip) tip.style.opacity = "0";
      }
    };

    let wheelTimer: ReturnType<typeof setTimeout> | null = null;
    const onWheel = (e: WheelEvent) => {
      const svg = (e.target as HTMLElement).closest?.(".pl-svg") as SVGSVGElement | null;
      if (!svg) return;
      const block = svg.closest(".blk") as HTMLElement | null;
      if (!block || block.dataset.final === "1") return;
      e.preventDefault();
      const r = svg.getBoundingClientRect();
      const px = (e.clientX - r.left) / r.width * W;
      const py = (e.clientY - r.top) / r.height * H;
      block.dataset.view = viewAttr(
        zoomView(parseView(block.dataset.view), Math.exp(e.deltaY * 0.0015), px, py),
      );
      drawPlot(block);
      if (wheelTimer) clearTimeout(wheelTimer);
      wheelTimer = setTimeout(() => changeRef.current(), 300);
    };

    let inputTimer: ReturnType<typeof setTimeout> | null = null;
    const onInput = (e: Event) => {
      const target = e.target as HTMLInputElement;
      const block = target.closest?.(".blk.gx") as HTMLElement | null;
      if (!block) return;
      e.stopPropagation();
      target.setAttribute("value", target.value);
      if (target.classList.contains("pl-expr")) {
        // Typing a new expression drops the drag offsets: it is a new curve.
        const row = target.closest(".pl-row") as HTMLElement | null;
        if (row) { delete row.dataset.base; delete row.dataset.h; delete row.dataset.k; }
      }
      if (target.type === "range") {
        const out = target.nextElementSibling;
        if (out) out.textContent = fmt(parseFloat(target.value));
        drawPlot(block);
      } else {
        drawGraph(block);
      }
      if (inputTimer) clearTimeout(inputTimer);
      inputTimer = setTimeout(() => changeRef.current(), 250);
    };

    const addExpression = (block: HTMLElement) => {
      const used = [...block.querySelectorAll<HTMLElement>(".pl-row")].map(r => r.dataset.c);
      const color = PALETTE.find(p => !used.includes(p)) ?? PALETTE[used.length % PALETTE.length];
      block.querySelector(".pl-list")?.insertAdjacentHTML("beforeend", exprRow("", color));
      const inputs = block.querySelectorAll<HTMLInputElement>(".pl-expr");
      inputs[inputs.length - 1]?.focus();
    };

    const onKeyDown = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement;
      if (t.classList?.contains("pl-expr") && e.key === "Enter") {
        e.preventDefault();
        const block = t.closest(".blk") as HTMLElement | null;
        if (block) addExpression(block);
      }
    };

    /** One `data-act="g-…"` action on a graph block. */
    type GraphAction = (block: HTMLElement, btn: HTMLElement) => void;

    const GRAPH_ACTIONS: Record<string, GraphAction> = {
      "g-final": block => block.setAttribute("data-final", "1"),
      "g-edit": block => block.setAttribute("data-final", "0"),
      "g-add": block => addExpression(block),
      "g-del": (_block, btn) => btn.closest(".pl-row")?.remove(),
      "g-zin": block => {
        block.dataset.view = viewAttr(zoomView(parseView(block.dataset.view), 0.7, W / 2, H / 2));
      },
      "g-zout": block => {
        block.dataset.view = viewAttr(
          zoomView(parseView(block.dataset.view), 1 / 0.7, W / 2, H / 2),
        );
      },
      "g-home": block => { block.dataset.view = viewAttr({ cx: 0, cy: 0, s: 20 / W }); },
      "g-kind": (block, btn) => {
        const kind = btn.dataset.k!;
        block.setAttribute("data-kind", kind);
        block.querySelectorAll(".g-kinds button")
          .forEach(x => x.classList.toggle("on", x === btn));
        // A scatter needs numeric x values; word labels become indices rather
        // than silently drawing nothing.
        if (kind !== "scatter") return;
        const labels = [...block.querySelectorAll<HTMLInputElement>(".ch-l")];
        if (labels.some(l => !Number.isFinite(parseFloat(l.value)))) {
          labels.forEach((l, i) => setInput(l, i + 1));
        }
      },
      "g-rowadd": block => {
        const count = block.querySelectorAll(".ch-row").length;
        block.querySelector(".ch-rows")?.insertAdjacentHTML(
          "beforeend", chartRow(block.dataset.kind === "scatter" ? count + 1 : "", ""),
        );
        const labels = block.querySelectorAll<HTMLInputElement>(".ch-l");
        labels[labels.length - 1]?.focus();
      },
      "g-rowdel": (_block, btn) => btn.closest(".ch-row")?.remove(),
      // The "+" slot on a bar chart: a new bar the height of the last.
      "g-rowadd2": block => {
        const rows = block.querySelectorAll<HTMLElement>(".ch-row");
        const last = rows[rows.length - 1];
        const height = last
          ? parseFloat(last.querySelector<HTMLInputElement>(".ch-v")!.value)
          : 1;
        block.querySelector(".ch-rows")?.insertAdjacentHTML(
          "beforeend",
          chartRow(`Item ${rows.length + 1}`, Number.isFinite(height) ? height : 1),
        );
      },
    };

    const onClick = (e: MouseEvent) => {
      const btn = (e.target as HTMLElement).closest?.("[data-act^='g-']") as HTMLElement | null;
      const block = btn?.closest(".blk") as HTMLElement | null;
      const run = btn && GRAPH_ACTIONS[btn.dataset.act!];
      if (!btn || !block || !run) return;
      e.preventDefault();
      e.stopPropagation();
      run(block, btn);
      drawGraph(block);
      changeRef.current();
    };

    // Flashcards: a click flips, a double-click edits the face instead.
    const onCardClick = (e: MouseEvent) => {
      const face = (e.target as HTMLElement).closest?.(".fc-face");
      if (!face) return;
      const card = face.closest('.blk[data-blk="card"]') as HTMLElement | null;
      if (!card || card.dataset.editing === "1") return;
      // A click that ends a text selection is not a flip.
      const sel = window.getSelection();
      if (sel && !sel.isCollapsed) return;
      card.setAttribute("data-open", card.getAttribute("data-open") === "1" ? "0" : "1");
      changeRef.current();
    };
    const onCardDouble = (e: MouseEvent) => {
      const face = (e.target as HTMLElement).closest?.(".fc-face");
      const card = face?.closest('.blk[data-blk="card"]') as HTMLElement | null;
      if (card) card.dataset.editing = "1";
    };
    const onCardBlur = () => setTimeout(() => {
      const sel = window.getSelection();
      const node = sel?.anchorNode;
      const el = node && (node.nodeType === 1 ? node as HTMLElement : node.parentElement);
      root.querySelectorAll<HTMLElement>('.blk[data-blk="card"][data-editing="1"]')
        .forEach(c => { if (!el || !c.contains(el)) delete c.dataset.editing; });
    }, 0);

    root.addEventListener("pointerdown", onItemDown, true);
    root.addEventListener("pointerdown", onCanvasDown);
    root.addEventListener("pointermove", onMove);
    root.addEventListener("pointerup", onUp);
    root.addEventListener("pointerout", onOut);
    root.addEventListener("wheel", onWheel, { passive: false });
    root.addEventListener("input", onInput, true);
    root.addEventListener("keydown", onKeyDown, true);
    root.addEventListener("click", onClick, true);
    root.addEventListener("click", onCardClick);
    root.addEventListener("dblclick", onCardDouble);
    root.addEventListener("focusout", onCardBlur);

    return () => {
      root.removeEventListener("pointerdown", onItemDown, true);
      root.removeEventListener("pointerdown", onCanvasDown);
      root.removeEventListener("pointermove", onMove);
      root.removeEventListener("pointerup", onUp);
      root.removeEventListener("pointerout", onOut);
      root.removeEventListener("wheel", onWheel);
      root.removeEventListener("input", onInput, true);
      root.removeEventListener("keydown", onKeyDown, true);
      root.removeEventListener("click", onClick, true);
      root.removeEventListener("click", onCardClick);
      root.removeEventListener("dblclick", onCardDouble);
      root.removeEventListener("focusout", onCardBlur);
      if (wheelTimer) clearTimeout(wheelTimer);
      if (inputTimer) clearTimeout(inputTimer);
    };
  }, [rootRef, changeRef]);

  return { refresh, html: kind => graphHTML({ kind }) };
}

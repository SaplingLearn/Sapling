/**
 * Layout measurement for the landing engine.
 *
 * Ported from `Sapling Landing v4.dc.html`. This is the *only* place that
 * reads layout, and it runs a few times a second (600ms throttle in the tick
 * loop), never per frame. Everything the tick needs — element lists, page
 * offsets, section tops — is resolved here and cached.
 */

import { invalidateCanvas } from './dom';

export interface Off {
  top: number;
  left: number;
  w: number;
  h: number;
}

export interface IngestChip {
  el: HTMLElement;
  i: number;
  /** Which tile this chip flies to. */
  dest: number;
  /** Which source line it came from. */
  line: number;
  docLine: HTMLElement | null;
}

export interface IngestScene {
  so: Off;
  tiles: HTMLElement[];
  tileO: Off[];
  doc: Off | null;
  /** Unscaled local coords, immune to the fit transform. */
  docL: { x: number; y: number; h: number; w: number };
  tileL: { x: number; y: number; h: number; w: number }[];
  counts: (HTMLElement | null)[];
  chips: IngestChip[];
}

export interface NavEntry {
  btn: HTMLElement;
  top: number;
  dot: HTMLElement | null;
  label: string;
}

export interface Measured {
  cards: HTMLElement[];
  depths: { el: HTMLElement; o: Off; d: number; pinned: boolean }[];
  tilts: { el: HTMLElement; o: Off }[];
  caps: { el: HTMLElement; i: number }[];
  ticks: { el: HTMLElement; i: number }[];
  tcaps: { el: HTMLElement; i: number }[];
  panels: { el: HTMLElement; i: number }[];
  pills: HTMLElement | null;
  stem: HTMLElement | null;
  jumpPill: HTMLElement | null;
  jumpLabel: HTMLElement | null;
  jumpTicks: HTMLElement[];
  nav: NavEntry[];
  act1: { el: HTMLElement; o: Off } | null;
  act2: { el: HTMLElement; o: Off } | null;
  act3: { el: HTMLElement; o: Off } | null;
  scene: IngestScene | null;
  plant: Off | null;
  gal: Off | null;
}

export interface MeasureTargets {
  root: HTMLElement;
  ingestScene: HTMLElement | null;
  plantCanvas: HTMLCanvasElement | null;
  actCanvas: HTMLCanvasElement | null;
  ambientCanvas: HTMLCanvasElement | null;
}

/** Cached viewport, so canvases only re-read their size when it changes. */
export interface ViewportCache {
  vw: number;
  vh: number;
}

export function measure(
  t: MeasureTargets,
  vp: ViewportCache,
): { M: Measured; docH: number } {
  const { root } = t;
  const sy = window.scrollY;
  const off = (el: Element): Off => {
    const r = el.getBoundingClientRect();
    return { top: r.top + sy, left: r.left, w: r.width, h: r.height };
  };
  const q = <E extends Element = HTMLElement>(sel: string) =>
    Array.from(root.querySelectorAll<E>(sel));

  if (vp.vw !== window.innerWidth || vp.vh !== window.innerHeight) {
    vp.vw = window.innerWidth;
    vp.vh = window.innerHeight;
    invalidateCanvas(t.actCanvas);
    invalidateCanvas(t.ambientCanvas);
    invalidateCanvas(t.plantCanvas);
  }

  const M = {} as Measured;
  M.cards = q('.floating-card');
  M.depths = q('[data-depth]').map((el) => ({
    el,
    o: off(el),
    d: parseFloat(el.dataset.depth || '0.2'),
    // inside a pinned act the frame doesn't move, so neither should the dots
    pinned: !!el.closest?.('[data-act]'),
  }));
  M.tilts = q('[data-tilt]').map((el) => ({ el, o: off(el) }));
  M.caps = q('[data-cap]').map((el) => ({ el, i: parseInt(el.dataset.cap as string) }));
  M.ticks = q('[data-tick]').map((el) => ({ el, i: parseInt(el.dataset.tick as string) }));
  M.tcaps = q('[data-tcap]').map((el) => ({ el, i: parseInt(el.dataset.tcap as string) }));
  M.panels = q('[data-panel]').map((el) => ({ el, i: parseInt(el.dataset.panel as string) }));
  M.pills = root.querySelector('[data-tutor-pills]');
  M.stem = root.querySelector('[data-stem]');


  M.jumpPill = root.querySelector('[data-jumppill]');
  M.jumpLabel = root.querySelector('[data-jumplabel]');
  M.jumpTicks = q('[data-jumptick]');
  M.nav = q('[data-secnav]').map((btn) => {
    const sec = document.getElementById(btn.dataset.secnav as string);
    return {
      btn,
      top: sec ? off(sec).top : 0,
      dot: btn.querySelector<HTMLElement>('[data-jumpdot]'),
      label: (btn.textContent || '').trim(),
    };
  });

  ([1, 2, 3] as const).forEach((k) => {
    const el = root.querySelector<HTMLElement>('[data-act="' + k + '"]');
    (M as unknown as Record<string, unknown>)['act' + k] = el ? { el, o: off(el) } : null;
  });

  const scene = t.ingestScene;
  if (scene) {
    const so = off(scene);
    const doc = scene.querySelector<HTMLElement>('[data-ingest-doc]');
    const tiles = Array.from(scene.querySelectorAll<HTMLElement>('[data-ingest-tile]'));
    const wrap = scene.querySelector<HTMLElement>('[data-ingest-fit]');
    // offset chain up to the scaled wrapper: unscaled local coords, immune
    // to the fit scale that `fitIngest` applies
    const local = (el: HTMLElement) => {
      let x = 0;
      let y = 0;
      let n: HTMLElement | null = el;
      while (n && n !== wrap) {
        x += n.offsetLeft;
        y += n.offsetTop;
        n = n.offsetParent as HTMLElement | null;
      }
      return { x, y, h: el.offsetHeight, w: el.offsetWidth };
    };
    M.scene = {
      so,
      tiles,
      tileO: tiles.map(off),
      doc: doc ? off(doc) : null,
      docL: doc ? local(doc) : { x: 0, y: 0, h: 0, w: 0 },
      tileL: tiles.map((x) => local(x)),
      counts: tiles.map((_, i) => scene.querySelector<HTMLElement>('[data-tilecount="' + i + '"]')),
      chips: Array.from(scene.querySelectorAll<HTMLElement>('[data-chip]')).map((c) => ({
        el: c,
        i: parseInt(c.dataset.chip as string),
        dest: parseInt(c.dataset.dest as string),
        line: parseInt(c.dataset.line as string),
        docLine: scene.querySelector<HTMLElement>('[data-docline="' + c.dataset.line + '"]'),
      })),
    };
  } else {
    M.scene = null;
  }

  M.plant = t.plantCanvas ? off(t.plantCanvas) : null;
  const gal = document.getElementById('gallery');
  M.gal = gal ? off(gal) : null;

  return { M, docH: Math.max(1, document.documentElement.scrollHeight - window.innerHeight) };
}

/**
 * Scales the Act II ingest scene down to fit its sticky stage.
 *
 * The inner wrapper is given the scene's natural height and a uniform scale,
 * so the chip flight paths (computed in unscaled local coords) stay correct
 * at any viewport height.
 */
export function fitIngest(stage: HTMLElement | null): number {
  if (!stage) return 1;
  const inner = stage.querySelector<HTMLElement>('[data-ingest-fit]');
  const grid = stage.querySelector<HTMLElement>('[data-ingest-tile]');
  const doc = stage.querySelector<HTMLElement>('[data-ingest-doc]');
  if (!inner || !grid || !doc || !grid.parentElement) return 1;
  const natural = Math.max(doc.offsetHeight, grid.parentElement.offsetHeight, 1);
  const hPx = natural + 'px';
  if (inner.style.height !== hPx) inner.style.height = hPx;
  const f = Math.min(1, stage.clientHeight / natural);
  const tf = f < 0.999 ? 'scale(' + f.toFixed(4) + ')' : 'none';
  if (inner.style.transform !== tf) inner.style.transform = tf;
  return f;
}

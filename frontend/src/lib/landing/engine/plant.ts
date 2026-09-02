/**
 * "Plant a concept" canvas in the final CTA.
 *
 * Ported from `Sapling Landing v4.dc.html`. Seeded with seven anonymous
 * nodes; anything the visitor types drops in from above, springs into place,
 * links to its two nearest neighbours and glows for three seconds. Planted
 * labels persist to localStorage so the grove is still there next visit.
 */

import { cv } from './dom';

const STORAGE_KEY = 'sapling-planted-v3';
/** Only the most recent 30 survive a reload. */
const KEEP = 30;
const MAX_LABEL = 32;

export interface PlantNode {
  /** Rest position. `x`/`y` spring toward this. */
  tx: number;
  ty: number;
  x: number;
  y: number;
  vy: number;
  /** Empty for the seeded background nodes. */
  label: string;
  color: string;
  r: number;
  born: number;
  links: number[];
  seed: number;
}

export interface PlantField {
  nodes: PlantNode[];
  labels: string[];
  /** @param animate Drop in from above rather than appearing in place. */
  add(canvas: HTMLCanvasElement | null, label: string, animate: boolean): void;
  /** Returns the new planted count, or -1 when the input was empty. */
  plant(canvas: HTMLCanvasElement | null, raw: string): number;
  restore(canvas: HTMLCanvasElement | null): number;
  draw(canvas: HTMLCanvasElement): void;
}

export function createPlantField(): PlantField {
  const nodes: PlantNode[] = [];
  const labels: string[] = [];

  function add(canvas: HTMLCanvasElement | null, label: string, animate: boolean): void {
    const w = canvas ? canvas.clientWidth : 400;
    const h = canvas ? canvas.clientHeight : 240;
    const x = 30 + Math.random() * (w - 60);
    const y = 34 + Math.random() * (h - 64);
    // link to the two nearest existing nodes, so the grove stays connected
    const dists = nodes
      .map((n, i) => ({ i, d: Math.hypot(n.tx - x, n.ty - y) }))
      .sort((a, b) => a.d - b.d)
      .slice(0, 2);
    nodes.push({
      tx: x, ty: y, x, y: animate ? -20 : y, vy: 0,
      label, color: '#8FD9A8', r: 5, born: Date.now(),
      links: dists.map((d) => d.i), seed: Math.random() * 100,
    });
    if (label) labels.push(label);
  }

  function plant(canvas: HTMLCanvasElement | null, raw: string): number {
    const label = (raw || '').trim().slice(0, MAX_LABEL);
    if (!label) return -1;
    add(canvas, label, true);
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(labels.slice(-KEEP)));
    } catch {
      /* private mode / quota — the grove just won't persist */
    }
    return labels.length;
  }

  function restore(canvas: HTMLCanvasElement | null): number {
    // seven anonymous nodes so the field is never empty
    for (let i = 0; i < 7; i++) add(canvas, '', false);
    labels.length = 0;
    // Everything below distrusts localStorage: it is user-writable and
    // survives across deploys, so the stored shape can be anything. Parse and
    // validate FULLY before touching the field — a partial restore that then
    // threw would leave the grove holding half of a corrupt payload, and
    // `add(canvas, 42)` would render `undefined`-width text forever. The seven
    // seed nodes above are already placed and stay placed either way.
    let clean: string[];
    try {
      const parsed: unknown = JSON.parse(localStorage.getItem(STORAGE_KEY) || '[]');
      if (!Array.isArray(parsed)) return 0;
      clean = parsed
        .filter((lb): lb is string => typeof lb === 'string')
        // Same cap `plant()` applies on the way in; an older or hand-edited
        // entry can exceed it and would overflow the node's label.
        .map((lb) => lb.slice(0, MAX_LABEL))
        .filter((lb) => lb.length > 0)
        .slice(-KEEP);
    } catch {
      return 0;
    }
    clean.forEach((lb) => add(canvas, lb, false));
    // `add()` already pushed each label; reset and re-push so the array is
    // exactly `clean` rather than depending on that side effect.
    labels.length = 0;
    labels.push(...clean);
    return clean.length;
  }

  function draw(canvas: HTMLCanvasElement): void {
    const c = cv(canvas);
    const { ctx, w, h } = c;
    ctx.clearRect(0, 0, w, h);
    const t = Date.now() * 0.001;

    // critically-ish damped spring toward rest
    nodes.forEach((n) => {
      n.vy += (n.ty - n.y) * 0.06;
      n.vy *= 0.82;
      n.y += n.vy;
      n.x += (n.tx - n.x) * 0.1;
    });

    ctx.lineWidth = 0.8;
    nodes.forEach((n) => {
      (n.links || []).forEach((li) => {
        const o = nodes[li];
        if (!o) return;
        ctx.strokeStyle = 'rgba(143,217,168,0.22)';
        ctx.beginPath();
        ctx.moveTo(n.x, n.y + Math.sin(t + n.seed) * 3);
        ctx.lineTo(o.x, o.y + Math.sin(t + o.seed) * 3);
        ctx.stroke();
      });
    });

    nodes.forEach((n) => {
      const wob = Math.sin(t + n.seed) * 3;
      const age = (Date.now() - n.born) / 1000;
      const glow = n.label && age < 3 ? (3 - age) / 3 : 0;
      ctx.beginPath();
      ctx.arc(n.x, n.y + wob, n.label ? 5 : 3, 0, Math.PI * 2);
      ctx.fillStyle = n.label ? '#8FD9A8' : '#4FA574';
      ctx.fill();
      if (glow > 0) {
        ctx.globalAlpha = glow * 0.5;
        ctx.beginPath();
        ctx.arc(n.x, n.y + wob, 5 + glow * 12, 0, Math.PI * 2);
        ctx.strokeStyle = '#8FD9A8';
        ctx.stroke();
        ctx.globalAlpha = 1;
      }
      if (n.label) {
        ctx.font = '10px "JetBrains Mono", monospace';
        ctx.fillStyle = 'rgba(230,242,232,0.85)';
        ctx.fillText(n.label, n.x + 9, n.y + wob + 3);
      }
    });
  }

  return { nodes, labels, add, plant, restore, draw };
}

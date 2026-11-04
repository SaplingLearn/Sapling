#!/usr/bin/env node
//
// Builds public/email/header.jpg, the header every Sapling email opens with
// (backend/services/email_templates.py): the landing page hero, frozen.
//
//   - the pale #F2F4F0 ground and the point cloud from
//     src/components/landing-v5/Hero.tsx (same palette, cluster centres,
//     spread and link rule, at rest: no rotation, no mouse), thinned out;
//   - the hero's legibility glow behind the wordmark;
//   - the landing navbar's logo: the approved hand-drawn wordmark SVG,
//     drawn the way src/components/SaplingWordmark.tsx draws it (an <img>),
//     just larger;
//   - a fade into the email's white card at the bottom.
//
// Email clients can't run canvas or render SVG/web fonts reliably, so a real
// browser (Playwright's Chromium, already installed for the E2E lane) renders
// it once into a JPEG. Re-run after changing the hero or the wordmark:
//
//   cd frontend && node scripts/build-email-header.mjs
//
// The cloud uses a fixed seed, so an unchanged run draws the same picture.

import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { chromium } from "playwright";

const FRONTEND = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const OUT = join(FRONTEND, "public", "email", "header.jpg");

// Shown 600x220 in the email; rendered at 2x.
const W = 600;
const H = 220;
const GROUND = "#F2F4F0";
const CARD = "#ffffff";

// Hero.tsx's background-node palette and cluster centres.
const PALETTE = [
  ["#445D22", 0.24], ["#7B9E51", 0.24], ["#D97706", 0.2],
  ["#B1D28B", 0.15], ["#A39E8F", 0.1], ["#D6D1C4", 0.07],
];
const CLUSTERS = [
  [-600, -250, 80], [-350, -100, -120], [-100, -300, 200], [150, -150, -80],
  [400, -250, 150], [600, -100, -50], [-500, 100, -150], [-200, 200, 100],
  [50, 150, -200], [300, 250, 120], [550, 150, -100], [-400, 350, 60],
  [0, 0, 0], [200, -50, -150],
];
const SPREAD = 280;
const FOCAL = 1000;
const POINTS = 110;

// mulberry32: a tiny seeded PRNG, so the cloud is reproducible.
function rng(seed) {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

function cloudSvg() {
  const random = rng(20261023);
  const colour = () => {
    const r = random();
    let s = 0;
    for (const [c, w] of PALETTE) {
      s += w;
      if (r <= s) return c;
    }
    return PALETTE[0][0];
  };
  // The hero fills a ~1440x900 viewport; the header is its middle band,
  // zoomed out a little and squashed vertically so the strip holds more cloud.
  const scale = 0.48;
  const pts = [];
  for (let i = 0; i < POINTS; i++) {
    const [ox, oy, oz] = CLUSTERS[Math.floor(random() * CLUSTERS.length)];
    const x = ox + (random() - 0.5) * SPREAD;
    const y = oy + (random() - 0.5) * SPREAD;
    const z = oz + (random() - 0.5) * SPREAD;
    const sc = FOCAL / (FOCAL + z);
    const px = x * sc * scale + W / 2;
    const py = y * sc * scale * 0.62 + H / 2;
    const r = (1 + random() * 4) * sc * 0.85;
    const c = colour();
    if (px > -10 && px < W + 10 && py > -10 && py < H + 10) pts.push({ px, py, sc, r, c });
  }
  const links = [];
  for (let i = 0; i < pts.length; i++) {
    const a = pts[i];
    const maxD = 70 * a.sc * 0.7;
    for (let j = i + 1; j < pts.length; j++) {
      const b = pts[j];
      const d = Math.hypot(a.px - b.px, a.py - b.py);
      if (d < maxD) {
        const op = (1 - d / maxD) * 0.2 * Math.min(1, a.sc);
        links.push(
          `<line x1="${a.px.toFixed(1)}" y1="${a.py.toFixed(1)}" x2="${b.px.toFixed(1)}" y2="${b.py.toFixed(1)}" stroke="#A39E8F" stroke-opacity="${op.toFixed(3)}" stroke-width="0.6"/>`,
        );
      }
    }
  }
  const dots = pts
    .sort((p, q) => p.sc - q.sc)
    .map((p) => `<circle cx="${p.px.toFixed(1)}" cy="${p.py.toFixed(1)}" r="${p.r.toFixed(2)}" fill="${p.c}"/>`);
  return `<svg xmlns="http://www.w3.org/2000/svg" width="${W}" height="${H}" viewBox="0 0 ${W} ${H}">${links.join("")}${dots.join("")}</svg>`;
}

// The navbar shows it 132px wide; the email header shows it at this width.
const MARK_W = 250;

function page() {
  const mark = pathToFileURL(join(FRONTEND, "public", "design", "sapling", "sapling-wordmark-approved.svg")).href;
  return `<!doctype html><html><head><meta charset="utf-8"><style>
html, body { margin: 0; padding: 0; }
#h { position: relative; width: ${W}px; height: ${H}px; overflow: hidden; background: ${GROUND}; }
#cloud { position: absolute; inset: 0; }
#glow { position: absolute; inset: 0;
  background: radial-gradient(ellipse 34% 46% at 50% 47%, rgba(242,244,240,0.96) 0%, rgba(242,244,240,0.8) 45%, rgba(242,244,240,0.35) 75%, rgba(242,244,240,0) 100%); }
#foot { position: absolute; inset: 0; background: linear-gradient(180deg, rgba(255,255,255,0) 58%, ${CARD} 100%); }
#mark { position: absolute; left: 50%; top: 47%; transform: translate(-50%, -50%);
  display: block; width: ${MARK_W}px; height: auto; }
</style></head><body>
<div id="h">
  <div id="cloud">${cloudSvg()}</div>
  <div id="glow"></div>
  <div id="foot"></div>
  <img id="mark" src="${mark}" alt="Sapling">
</div>
</body></html>`;
}

const dir = mkdtempSync(join(tmpdir(), "email-header-"));
try {
  const html = join(dir, "header.html");
  writeFileSync(html, page());
  const browser = await chromium.launch();
  try {
    const tab = await browser.newPage({ viewport: { width: W, height: H }, deviceScaleFactor: 2 });
    await tab.goto(pathToFileURL(html).href);
    await tab.evaluate(() => document.fonts.ready);
    await tab.waitForFunction(() => [...document.images].every((img) => img.complete && img.naturalWidth > 0));
    await tab.locator("#h").screenshot({ path: OUT, type: "jpeg", quality: 88 });
  } finally {
    await browser.close();
  }
  console.log(`wrote ${OUT}`);
} finally {
  rmSync(dir, { recursive: true, force: true });
}

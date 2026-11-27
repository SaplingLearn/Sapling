// Build Sapling's design system (a Claude "Design System" artifact) from the
// code: tokens from src/styles, the app's fonts and compiled CSS, and a static
// preview of every Storybook story.
//
//   npm run design-system     (builds Storybook, then runs this; PW_CHROMIUM=<chromium> if Playwright's own isn't installed)
//
// Writes design-system/project/, which is committed: the design system is
// versioned with the code and reviewed in PRs. Publishing that folder to the
// artifact happens from main (design-system/README.md). The system is marked
// `"editing": "code"`, so its page is read-only and every change comes from
// here.
import fs from "node:fs";
import path from "node:path";
import { execFileSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright";
import { parseTokens } from "./tokens.mjs";
import { propsTable } from "./props.mjs";

const here = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(here, "../..");
const dsDir = path.join(root, "design-system");
const out = path.join(dsDir, "project");
const sbDir = path.join(root, "storybook-static");
const TITLE = "Sapling";

function git(...args) {
  try {
    return execFileSync("git", args, { cwd: root, encoding: "utf8" }).trim();
  } catch {
    return "";
  }
}

function write(rel, data) {
  const file = path.join(out, rel);
  fs.mkdirSync(path.dirname(file), { recursive: true });
  fs.writeFileSync(file, data);
}

const escapeHtml = (s) => String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");

// ---------------------------------------------------------------- inputs
if (!fs.existsSync(path.join(sbDir, "index.json"))) {
  console.error("storybook-static/ is missing: run `npm run design-system`, which builds it first.");
  process.exit(1);
}
const sha = git("rev-parse", "--short", "HEAD");
// The last commit's time, not now, so a rebuild of the same commit is byte-identical.
const at = git("log", "-1", "--format=%cI") || new Date().toISOString();

fs.rmSync(out, { recursive: true, force: true });
fs.mkdirSync(out, { recursive: true });

// ---------------------------------------------------------------- tokens
const { tokens, tokensCss, skipped } = parseTokens({
  tokensCss: fs.readFileSync(path.join(root, "src/styles/tokens.css"), "utf8"),
  themeCss: fs.readFileSync(path.join(root, "src/styles/theme.css"), "utf8"),
  title: TITLE,
});
tokens.meta = {
  source: "github",
  repo: "SaplingLearn/Sapling",
  ref: `main@${sha}`,
  package: "frontend",
  paths: { tokens: ["frontend/src/styles/tokens.css", "frontend/src/styles/theme.css"], fonts: ["frontend/src/app/fonts"], docs: ["frontend/design-system/brand.md"] },
  synced: at.slice(0, 10),
};
write("tokens.json", JSON.stringify(tokens, null, 2) + "\n");
write("tokens.css", tokensCss);

// ---------------------------------------------------------------- fonts
// Only the faces tokens.json names, each with its licence (OFL requires the
// licence to travel with the font).
for (const f of tokens.type.fonts) {
  const name = path.basename(f.file);
  write(`fonts/${name}`, fs.readFileSync(path.join(root, "src/app/fonts", name)));
  const licence = `${f.family}-OFL.txt`;
  if (!fs.existsSync(path.join(out, "licenses", licence))) write(`licenses/${licence}`, fs.readFileSync(path.join(root, "src/app/fonts", licence)));
}

// ---------------------------------------------------------------- bundle.css
// The app's compiled stylesheet, as Storybook built it: tokens, base, the
// component classes and every utility class in src/. next/font's @font-face
// rules point at hashed build files, so they go; tokens.css declares the
// faces from fonts/ instead, and these variables point the font roles at them.
const cssFiles = fs.readdirSync(path.join(sbDir, "assets")).filter((f) => f.endsWith(".css"));
const appCss = cssFiles.map((f) => fs.readFileSync(path.join(sbDir, "assets", f), "utf8")).find((c) => c.includes("--bg-panel"));
if (!appCss) throw new Error("No compiled app stylesheet in storybook-static/assets");
let bundleCss = appCss.replace(/@font-face\s*\{[^}]*\}/g, "");
bundleCss += `\n:root{--font-aleo:"Aleo";--font-suse:"SUSE"}\n`;
bundleCss += `.ds-stories{display:flex;flex-direction:column;gap:20px;padding:20px;background:var(--bg);color:var(--text);font-family:var(--font-sans)}.ds-story-label{margin:0 0 8px;font:600 11px/1.2 var(--font-sans);color:var(--text-muted)}.ds-story-canvas{display:flex;flex-wrap:wrap;align-items:flex-start;gap:12px}.ds-story-canvas--overlay{position:relative;display:block;width:920px;height:440px;overflow:hidden;transform:translateZ(0);border:1px solid var(--border);border-radius:var(--r-md);background:var(--bg)}\n`;
if (/<\/style/i.test(bundleCss)) throw new Error("bundle.css contains </style");
write("components/bundle.css", bundleCss);

// ---------------------------------------------------------------- stories
const index = JSON.parse(fs.readFileSync(path.join(sbDir, "index.json"), "utf8"));
const stories = Object.values(index.entries).filter((e) => e.type === "story");
const byComponent = new Map();
for (const s of stories) {
  const [group, name] = s.title.split("/");
  if (!byComponent.has(name)) byComponent.set(name, { name, group, importPath: s.importPath, stories: [] });
  byComponent.get(name).stories.push(s);
}

// Serve storybook-static and capture each story's rendered markup, portals
// (dialogs, menus, tooltips) included.
const http = await import("node:http");
const types = { ".html": "text/html", ".js": "text/javascript", ".css": "text/css", ".json": "application/json", ".woff2": "font/woff2", ".svg": "image/svg+xml", ".png": "image/png" };
const server = http.createServer((req, res) => {
  const p = decodeURIComponent(new URL(req.url, "http://x").pathname);
  const file = path.join(sbDir, p === "/" ? "index.html" : p);
  if (!file.startsWith(sbDir) || !fs.existsSync(file) || fs.statSync(file).isDirectory()) {
    res.writeHead(404).end();
    return;
  }
  res.writeHead(200, { "content-type": types[path.extname(file)] ?? "application/octet-stream" });
  fs.createReadStream(file).pipe(res);
});
await new Promise((r) => server.listen(0, "127.0.0.1", r));
const base = `http://127.0.0.1:${server.address().port}`;

const browser = await chromium.launch(process.env.PW_CHROMIUM ? { executablePath: process.env.PW_CHROMIUM } : {});
const page = await browser.newPage({ viewport: { width: 960, height: 640 } });
const OVERLAY = /^(Overlays|UI\/Menu|UI\/Tooltip)/;
const CANVAS = { width: 920, height: 440 };

const components = [];
for (const comp of byComponent.values()) {
  let summary = "";
  const sections = [];
  for (const s of comp.stories) {
    // An overlay story renders at exactly the size of its preview canvas, so
    // fixed-position portals (menus, tooltips) land in the same place there.
    const overlay = OVERLAY.test(s.title);
    await page.setViewportSize(overlay ? { width: CANVAS.width, height: CANVAS.height } : { width: 960, height: 640 });
    await page.goto(`${base}/iframe.html?id=${s.id}&viewMode=story`, { waitUntil: "networkidle" });
    await page.waitForFunction(() => document.querySelector("#storybook-root")?.childElementCount > 0, null, { timeout: 15000 });
    await page.waitForTimeout(600); // play functions, transitions
    const shot = await page.evaluate(async ({ id, overlay }) => {
      const preview = window.__STORYBOOK_PREVIEW__;
      let description = "";
      try {
        const story = await preview.storyStoreValue.loadStory({ storyId: id });
        description = story.parameters?.docs?.description?.component ?? "";
      } catch {}
      const rootEl = document.querySelector("#storybook-root");
      const r = rootEl.getBoundingClientRect();
      const parts = [overlay ? `<div style="position:absolute;box-sizing:border-box;left:${Math.round(r.left) - 1}px;top:${Math.round(r.top) - 1}px;width:${Math.round(r.width)}px;padding:${getComputedStyle(rootEl).padding}">${rootEl.innerHTML}</div>` : rootEl.innerHTML];
      for (const el of document.body.children) {
        if (el === rootEl || el.tagName === "SCRIPT" || el.id?.startsWith("storybook") || el.className?.toString().includes("sb-")) continue;
        parts.push(el.outerHTML);
      }
      const box = rootEl.getBoundingClientRect();
      return { description, html: parts.join("\n"), height: Math.ceil(box.height) };
    }, { id: s.id, overlay });
    if (!summary) summary = shot.description;
    const html = shot.html
      .replace(/<script[\s\S]*?<\/script>/gi, "")
      .replace(/\s(id|aria-labelledby|aria-describedby|aria-controls|for)="(:r[0-9a-z]+:|radix-[^"]*|«[^"]*»)"/g, "")
      .replace(/ data-testid="[^"]*"/g, "");
    sections.push(
      `<section class="ds-story">\n<p class="ds-story-label">${escapeHtml(s.name)}</p>\n<div class="ds-story-canvas${overlay ? " ds-story-canvas--overlay" : ""}">\n${html}\n</div>\n</section>`,
    );
  }

  const subtitle = summary.split(/(?<=\.)\s/)[0] ?? "";
  const preview =
    `<!-- @dsCard group="${comp.group}" height=120 subtitle="${escapeHtml(subtitle).slice(0, 160)}" -->\n` +
    `<!-- Static render of the ${comp.name} stories (${comp.importPath.replace("./", "frontend/")}). Generated by scripts/design-system/build.mjs. -->\n` +
    `<div class="ds-stories">\n${sections.join("\n")}\n</div>\n`;
  write(`components/${comp.name}/preview.html`, preview);

  const source = comp.importPath.replace(".stories.tsx", ".tsx").replace("./", "");
  const props = fs.existsSync(path.join(root, source)) ? propsTable(path.join(root, source)) : "";
  const importLine =
    comp.group === "Overlays" && comp.name === "Dialog"
      ? `import Dialog from "@/components/Dialog";`
      : comp.name === "Field"
        ? `import { fieldClass } from "@/components/ui";`
        : `import { ${comp.name} } from "@/components/ui";`;
  const readme =
    `# ${comp.name}\n\n${summary || `The ${comp.name} component.`}\n\n` +
    "```tsx\n" + importLine + "\n```\n\n" +
    (props ? `## Props\n\n${props}\n` : "") +
    `## States\n\n${comp.stories.map((s) => `- ${s.name}`).join("\n")}\n\n` +
    `Source: \`frontend/${source}\`. The preview is a static render of its Storybook stories, styled by \`components/bundle.css\`; build with the classes it shows.\n`;
  write(`components/${comp.name}/README.md`, readme);
  components.push({ name: comp.name, group: comp.group, stories: comp.stories.length });
}
// Card heights: render each preview as the page frames it and measure.
for (const comp of components) {
  const file = path.join(out, "components", comp.name, "preview.html");
  const body = fs.readFileSync(file, "utf8");
  const doc =
    `<!doctype html><html data-theme="light"><head><base href="${new URL(`file://${out}/`).href}">` +
    `<link rel="stylesheet" href="tokens.css"><link rel="stylesheet" href="components/bundle.css"></head><body style="margin:0">${body}</body></html>`;
  const tmp = path.join(out, `.measure-${comp.name}.html`);
  fs.writeFileSync(tmp, doc);
  await page.setViewportSize({ width: 960, height: 200 });
  await page.goto(`file://${tmp}`);
  await page.evaluate(() => document.fonts.ready);
  const h = await page.evaluate(() => Math.ceil(document.querySelector(".ds-stories").getBoundingClientRect().height));
  fs.rmSync(tmp);
  fs.writeFileSync(file, body.replace(/height=\d+/, `height=${Math.min(Math.max(h, 40), 4000)}`));
}
await browser.close();
server.close();

// ---------------------------------------------------------------- docs
const brand = fs.readFileSync(path.join(dsDir, "brand.md"), "utf8");
write("README.md", brand + `\n## Not synced\n\n- Gummi, the production heading face: licensed for saplinglearn.com only, so Aleo stands in.\n- Motion tokens (\`--ease\`, \`--dur-fast\` 140ms, \`--dur\` 220ms, \`--dur-slow\` 420ms): no motion family in this format.\n${skipped.map((s) => `- \`--${s.name}\`: ${s.why}`).join("\n")}\n- Components are static renders of their stories, not a live bundle.\n`);
const cover = path.join(dsDir, "cover.html");
if (fs.existsSync(cover)) write("components/Cover/preview.html", fs.readFileSync(cover));

// Logo uploads live in the artifact's asset store; design-system/assets.json
// records their ids once uploaded (see design-system/README.md).
const assetsFile = path.join(dsDir, "assets.json");
const assetGroups = fs.existsSync(assetsFile) ? JSON.parse(fs.readFileSync(assetsFile, "utf8")) : {};
const groupRecords = Object.fromEntries(
  Object.entries(assetGroups).map(([name, g]) => [
    name,
    {
      name,
      tile: g.tile ?? "l",
      order: (g.files ?? []).filter((f) => f.blob).map((f) => f.name),
      files: Object.fromEntries((g.files ?? []).filter((f) => f.blob).map((f) => [f.name, { name: f.name, blob: f.blob, size: f.size, type: f.type }])),
    },
  ]),
);
if (fs.existsSync(assetsFile)) {
  for (const [name, g] of Object.entries(assetGroups)) {
    if (g.readme) write(`assets/${name}/README.md`, g.readme + "\n");
  }
}

// ---------------------------------------------------------------- index
const designSystem = {
  v: 3,
  layout: "files",
  createdOnFiles: { v: 1, at: "2026-11-26T20:00:00Z" },
  title: TITLE,
  namespace: "Sapling",
  libraries: [],
  sections: {},
  groups: Object.keys(groupRecords),
  assetGroups: groupRecords,
  blobs: {},
  docs: { readme: "project/README.md", sections: [] },
  editing: "code",
  lastChange: {
    by: git("log", "-1", "--format=%an") || "Claude",
    at,
    via: `GitHub · SaplingLearn/Sapling@${sha}`,
    note: `Synced from frontend/ at ${sha}: ${components.length} components, ${stories.length} stories.`,
  },
};
write("design-system.json", JSON.stringify(designSystem, null, 2) + "\n");

console.log(`design-system/project: ${components.length} components, ${stories.length} stories, ${tokens.color.tokens.length} colours`);
if (skipped.length) console.log(`skipped: ${skipped.map((s) => s.name).join(", ")}`);

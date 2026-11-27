// Render every design-system/project/components/*/preview.html the way the
// Design System page frames it (tokens.css, then bundle.css, then the
// preview) and screenshot it, to look at before publishing.
//
//   node scripts/design-system/render-previews.mjs <out-dir>
//
// Fails if a preview renders blank.
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright";

const proj = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../design-system/project");
const out = path.resolve(process.argv[2] ?? "design-system-previews");
fs.mkdirSync(out, { recursive: true });

const browser = await chromium.launch(process.env.PW_CHROMIUM ? { executablePath: process.env.PW_CHROMIUM } : {});
const page = await browser.newPage({ viewport: { width: 960, height: 800 } });
let blank = 0;
for (const comp of fs.readdirSync(path.join(proj, "components")).sort()) {
  const file = path.join(proj, "components", comp, "preview.html");
  if (!fs.existsSync(file)) continue;
  const body = fs.readFileSync(file, "utf8");
  const doc =
    `<!doctype html><html data-theme="light"><head><base href="${new URL(`file://${proj}/`).href}">` +
    `<link rel="stylesheet" href="tokens.css"><link rel="stylesheet" href="components/bundle.css"></head>` +
    `<body style="margin:0">${body}</body></html>`;
  const html = path.join(out, `${comp}.html`);
  fs.writeFileSync(html, doc);
  await page.goto(`file://${html}`);
  await page.evaluate(() => document.fonts.ready);
  await page.waitForTimeout(500); // entrance animations (fade-in) finish
  const { height, text } = await page.evaluate(() => ({ height: document.documentElement.scrollHeight, text: document.body.innerText.trim().length }));
  await page.screenshot({ path: path.join(out, `${comp}.png`), fullPage: true });
  const marker = Number(/height=(\d+)/.exec(body)?.[1] ?? 0);
  console.log(`${comp.padEnd(18)} height ${String(height).padStart(5)} (card ${marker})${text ? "" : "  BLANK"}`);
  if (!text && comp !== "Cover") blank++;
}
await browser.close();
if (blank) {
  console.error(`${blank} preview(s) rendered blank`);
  process.exit(1);
}

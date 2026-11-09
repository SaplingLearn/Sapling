/**
 * Push Sapling screens/states into Figma as EDITABLE layers.
 *
 * Inventory: docs/figma/inventory/ (state ids = recipe keys, e2e/figma/recipes/).
 * Driver:    scripts/figma-capture.sh (one flock'd up→capture→down cycle on
 *            the showcase stack, like gallery-shots).
 *
 * Modes (env):
 *   FIGMA_CAPTURES_FILE=<json>  [{state, captureId, endpoint}] minted by the
 *                               Figma MCP generate_figma_design tool → capture.
 *   FIGMA_DRYRUN_DIR=<dir>      run EVERY recipe (or FIGMA_ONLY=a,b) and write
 *                               <dir>/<state>.png + results.json — validates
 *                               recipes without spending capture ids.
 * Neither set → every test skips.
 *
 * `test` comes from @playwright/test directly (not support/fixtures.ts) so the
 * autouse dbReset fixture does not wipe the showcase overlay.
 */
import fs from "node:fs";
import path from "node:path";

import { expect, test, type Browser, type Page } from "@playwright/test";

import { RECIPES } from "./figma/recipes";
import type { Persona } from "./figma/types";
import { mintStorageState } from "./support/session";
import { FRONTEND_URL } from "./support/stack";

const CAPTURES_FILE = process.env.FIGMA_CAPTURES_FILE?.trim();
/** Pool mode: FIGMA_POOL_FILE = JSON array of pre-minted capture ids,
 *  FIGMA_PROMPT_ID = the promptId they were minted under, FIGMA_STATES_FILE =
 *  JSON array of state ids. Each submit's response carries a nextCaptureId
 *  (the toolbar re-capture mechanism); we chain on it and only fall back to
 *  the pool when a chain breaks. */
const POOL_FILE = process.env.FIGMA_POOL_FILE?.trim();
const PROMPT_ID = process.env.FIGMA_PROMPT_ID?.trim();
const STATES_FILE = process.env.FIGMA_STATES_FILE?.trim();
const POOL: string[] = POOL_FILE ? JSON.parse(fs.readFileSync(POOL_FILE, "utf8")) : [];
let chainNext: string | undefined;
const used: Record<string, string> = {};
/** Parallel workers: each worker draws only from its own stride of the pool
 *  (superseded by the shared locked pool below). */
/** Spare ids are a SHARED pool claimed under a mkdir lock, so any worker
 *  whose chain breaks can take one (a per-worker stride let one unlucky
 *  worker run dry while spares sat idle in another's slice). */
function withLock<T>(dir: string, fn: () => T): T {
  const lock = path.join(dir, ".pool.lock");
  for (let i = 0; ; i++) {
    try {
      fs.mkdirSync(lock);
      break;
    } catch {
      if (i > 2000) throw new Error("pool lock timeout");
      Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, 10);
    }
  }
  try {
    return fn();
  } finally {
    fs.rmdirSync(lock);
  }
}
function readLines(f: string): Set<string> {
  return new Set(fs.existsSync(f) ? fs.readFileSync(f, "utf8").split("\n").filter(Boolean) : []);
}
function takeId(): { captureId: string; endpoint: string } {
  const dir = path.dirname(POOL_FILE!);
  const spentFile = path.join(dir, "spent.txt");
  const claimedFile = path.join(dir, "claimed.txt");
  // Per-worker chain file: survives a worker restart after a failed test.
  const chainFile = path.join(dir, `chain.w${test.info().parallelIndex}.txt`);
  if (!chainNext && fs.existsSync(chainFile)) chainNext = fs.readFileSync(chainFile, "utf8").trim() || undefined;
  if (chainNext && readLines(spentFile).has(chainNext)) chainNext = undefined;
  let captureId = chainNext;
  chainNext = undefined;
  if (!captureId) {
    captureId = withLock(dir, () => {
      const taken = new Set([...readLines(spentFile), ...readLines(claimedFile)]);
      const id = POOL.find((x) => !taken.has(x));
      if (id) fs.appendFileSync(claimedFile, id + "\n");
      return id;
    });
  }
  if (!captureId) throw new Error("capture id pool exhausted");
  fs.writeFileSync(chainFile, captureId);
  return {
    captureId,
    endpoint: `https://mcp.figma.com/mcp/capture/${captureId}/submit?bindVariables=true&promptId=${PROMPT_ID}`,
  };
}
const DRYRUN_DIR = process.env.FIGMA_DRYRUN_DIR?.trim();
const ONLY_LIST = process.env.FIGMA_ONLY?.split(",").map((s) => s.trim()).filter(Boolean);
const ONLY = ONLY_LIST?.length ? ONLY_LIST : undefined;
const CAPTURE_JS = "https://mcp.figma.com/mcp/html-to-design/capture.js";

type Capture = { state: string; captureId?: string; endpoint?: string };

const CAPTURE_MODE = !!CAPTURES_FILE || !!POOL_FILE;
const CAPTURES: Capture[] = CAPTURES_FILE
  ? JSON.parse(fs.readFileSync(CAPTURES_FILE, "utf8"))
  : POOL_FILE
    ? (JSON.parse(fs.readFileSync(STATES_FILE!, "utf8")) as string[]).map((state) => ({ state }))
    : DRYRUN_DIR
    ? (ONLY ?? Object.keys(RECIPES)).map((state) => ({ state }))
    : [];

const VIEWPORT = { width: 1440, height: 900 };

const PERSONAS: Record<Exclude<Persona, "active" | "public">, [string, string]> = {
  second: ["rich-user-second", "Jordan Lee"],
  admin: ["rich-user-admin", "Ada Admin"],
  new: ["rich-user-new", "New Student"],
};

async function pageFor(browser: Browser, persona: Persona, defaultPage: Page): Promise<Page> {
  if (persona === "active") return defaultPage;
  const storageState =
    persona === "public"
      ? { cookies: [], origins: [] }
      : await mintStorageState(...PERSONAS[persona]);
  const ctx = await browser.newContext({
    storageState,
    viewport: VIEWPORT,
    baseURL: FRONTEND_URL,
    timezoneId: "America/New_York",
    locale: "en-US",
  });
  return ctx.newPage();
}

async function settle(page: Page, state: string): Promise<void> {
  await page.waitForLoadState("networkidle", { timeout: 5_000 }).catch(() => {});
  await page.mouse.move(0, 0);
  await page.evaluate(() => document.fonts.ready);
  await page.addStyleTag({ content: ".skip-link{display:none!important}" });
  await page.evaluate((t) => {
    (document.activeElement as HTMLElement | null)?.blur?.();
    document.title = t; // Figma names the captured frame after the title
  }, state);
  await page.waitForTimeout(400);
}

async function pushToFigma(page: Page, c: Capture): Promise<number> {
  if (!c.captureId) Object.assign(c, takeId());
  const script = await (await page.context().request.get(CAPTURE_JS)).text();
  await page.evaluate((s) => {
    const el = document.createElement("script");
    el.textContent = s;
    document.head.appendChild(el);
  }, script);
  await page.waitForTimeout(500);
  const submitted = page.waitForResponse(
    (r) => r.url().includes(c.captureId!) && r.url().includes("/submit"),
    { timeout: 240_000 },
  );
  // captureForDesign's promise never settles (it parks a toolbar) — fire and
  // wait for the submit POST instead.
  void page.evaluate(
    ({ captureId, endpoint }) => {
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      (window as any).figma.captureForDesign({ captureId, endpoint, selector: "body" });
    },
    { captureId: c.captureId!, endpoint: c.endpoint! },
  );
  const res = await submitted.catch((e) => {
    fs.appendFileSync(path.join(path.dirname(POOL_FILE!), "spent.txt"), c.captureId! + "\n");
    throw e;
  });
  used[c.state] = c.captureId!;
  fs.appendFileSync(path.join(path.dirname(POOL_FILE!), "spent.txt"), c.captureId! + "\n");
  try {
    const body = await res.json();
    if (body?.nextCaptureId) {
      chainNext = body.nextCaptureId;
      fs.writeFileSync(
        path.join(path.dirname(POOL_FILE!), `chain.w${test.info().parallelIndex}.txt`),
        body.nextCaptureId,
      );
    }
  } catch {
    /* no body → next state falls back to the pool */
  }
  return res.status();
}

test.use({ viewport: VIEWPORT });

test("every capture names a known recipe", () => {
  const unknown = CAPTURES.map((c) => c.state).filter((s) => !RECIPES[s]);
  expect(unknown).toEqual([]);
});

const results: Record<string, string> = {};

for (const c of CAPTURES) {
  test(`figma — ${c.state}`, async ({ page, browser }) => {
    test.setTimeout(330_000);
    expect(
      FRONTEND_URL.includes("localhost") || FRONTEND_URL.includes("127.0.0.1"),
      `REFUSING: FRONTEND_URL ${FRONTEND_URL} is not local`,
    ).toBe(true);
    const recipe = RECIPES[c.state];
    test.skip(!recipe, "unknown recipe");

    const p = await pageFor(browser, recipe.persona ?? "active", page);
    try {
      await p.addInitScript(() => window.localStorage.setItem("sapling_disclaimer_ack", "true"));
      // Strip CSP so the inlined capture.js + its submit POST are allowed.
      // Registered FIRST so recipe mocks (registered later) take precedence.
      if (CAPTURE_MODE) {
        await p.route("**/*", async (route) => {
          // Only documents carry the CSP header; let every API/SSE call
          // through untouched (route.fetch would buffer streams).
          if (route.request().resourceType() !== "document") return route.fallback();
          const response = await route.fetch();
          const headers = { ...response.headers() };
          delete headers["content-security-policy"];
          delete headers["content-security-policy-report-only"];
          await route.fulfill({ response, headers });
        });
      }
      await recipe.run(p);
      await settle(p, c.state);
      if (DRYRUN_DIR) {
        const file = path.join(DRYRUN_DIR, `${c.state.replace(/\//g, "__")}.png`);
        fs.mkdirSync(DRYRUN_DIR, { recursive: true });
        await p.screenshot({ path: file });
        results[c.state] = "ok";
      } else {
        const status = await pushToFigma(p, c);
        results[c.state] = `submitted ${status}`;
        expect(status).toBeLessThan(300);
        await p.waitForTimeout(1_500);
      }
    } catch (e) {
      results[c.state] = `FAIL ${(e as Error).message.split("\n")[0]}`;
      throw e;
    } finally {
      if (p !== page) await p.context().close();
    }
  });
}

test.afterAll(() => {
  const dir = DRYRUN_DIR ?? (CAPTURES_FILE ? path.dirname(CAPTURES_FILE) : POOL_FILE ? path.dirname(POOL_FILE) : null);
  if (POOL_FILE && dir) {
    const w = test.info().parallelIndex;
    fs.writeFileSync(path.join(dir, `used.w${w}.json`), JSON.stringify(used, null, 1));
    fs.writeFileSync(
      path.join(dir, `pool.left.w${w}.json`),
      JSON.stringify(chainNext ? [chainNext] : []),
    );
  }
  if (!dir || !Object.keys(results).length) return;
  const file = path.join(dir, POOL_FILE ? `results.w${test.info().parallelIndex}.json` : "results.json");
  const prev = fs.existsSync(file) ? JSON.parse(fs.readFileSync(file, "utf8")) : {};
  fs.writeFileSync(file, JSON.stringify({ ...prev, ...results }, null, 1));
});

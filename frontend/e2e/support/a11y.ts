/**
 * The automated accessibility check for the E2E lane (learning-loop spec §13
 * A135): axe-core, injected into the page under test, run against the WCAG 2.0
 * and 2.1 level A and AA rules.
 *
 * axe-core is an exact devDependency (frontend/package.json) and is injected
 * from node_modules with `page.addScriptTag({ path })` — never from a CDN, so
 * the lane stays offline and the rule set only changes with a reviewed version
 * bump.
 *
 * Rules: every rule tagged wcag2a, wcag2aa, wcag21a or wcag21aa runs, on the
 * whole document, with nothing excluded. A violation is reported with its rule
 * id, impact and the CSS selector of every failing node, so a red run says what
 * to fix without opening the trace. Each scan's raw result is also written to
 * `e2e/results/a11y/<label>.json` (git-ignored) for counting by rule.
 *
 * Determinism: the scan waits for web fonts and for every finite animation to
 * finish, so a fade-in caught half way is never measured for colour contrast.
 * The specs also run with `reducedMotion: "reduce"`, which the app's global
 * reset (globals.css) turns into instant transitions.
 */
import fs from "node:fs";
import path from "node:path";

import type { Page } from "@playwright/test";

import { expect } from "./fixtures";

/** The rule tags the lane runs: WCAG 2.0 and 2.1, levels A and AA. */
export const WCAG_TAGS = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"] as const;

const AXE_SOURCE = require.resolve("axe-core/axe.min.js");
const RESULTS_DIR = path.resolve(__dirname, "..", "results", "a11y");

/** One failing rule, as the lane reports it. */
export type A11yViolation = {
  id: string;
  impact: string | null;
  help: string;
  helpUrl: string;
  /** One entry per failing node: its selector and axe's summary of why it fails. */
  nodes: { target: string; summary: string }[];
};

type AxeRun = {
  violations: {
    id: string;
    impact?: string | null;
    help: string;
    helpUrl: string;
    nodes: { target: unknown[]; failureSummary?: string }[];
  }[];
};

/** Wait until the page has stopped moving: fonts loaded, every finite
 *  animation finished, then two frames for layout to settle. */
async function settle(page: Page): Promise<void> {
  await page.evaluate(async () => {
    await document.fonts.ready;
    // Running, finite animations only: a paused one never finishes. Bounded, so
    // a scan can never hang on an animation that keeps restarting.
    const finite = document.getAnimations().filter((animation) => {
      const end = animation.effect?.getComputedTiming().endTime;
      return animation.playState === "running" && typeof end === "number" && Number.isFinite(end);
    });
    await Promise.race([
      Promise.all(finite.map((animation) => animation.finished.catch(() => undefined))),
      new Promise((resolve) => setTimeout(resolve, 5_000)),
    ]);
    await new Promise<void>((resolve) => requestAnimationFrame(() => requestAnimationFrame(() => resolve())));
  });
}

/** Run axe against the current page and return its violations. */
export async function scanA11y(page: Page, label: string): Promise<A11yViolation[]> {
  await settle(page);
  if (!(await page.evaluate(() => "axe" in window))) {
    await page.addScriptTag({ path: AXE_SOURCE });
  }
  const run = (await page.evaluate(async (tags) => {
    const axe = (window as unknown as { axe: { run: (context: Document, options: object) => Promise<unknown> } }).axe;
    return axe.run(document, { runOnly: { type: "tag", values: tags }, resultTypes: ["violations"] });
  }, [...WCAG_TAGS])) as AxeRun;
  const violations: A11yViolation[] = run.violations.map((v) => ({
    id: v.id,
    impact: v.impact ?? null,
    help: v.help,
    helpUrl: v.helpUrl,
    nodes: v.nodes.map((n) => ({
      target: n.target.map((part) => (Array.isArray(part) ? part.join(" >>> ") : String(part))).join(" ⟶ "),
      summary: (n.failureSummary ?? "").replace(/\s+/g, " ").trim(),
    })),
  }));
  fs.mkdirSync(RESULTS_DIR, { recursive: true });
  fs.writeFileSync(
    path.join(RESULTS_DIR, `${label.replace(/[^a-z0-9]+/gi, "-").toLowerCase()}.json`),
    JSON.stringify({ label, url: page.url(), violations }, null, 2),
  );
  return violations;
}

/** One readable line per failing node: rule, impact, selector, why. */
export function describeViolations(violations: A11yViolation[]): string[] {
  return violations.flatMap((v) =>
    v.nodes.map((n) => `${v.id} (${v.impact ?? "unknown impact"}) at ${n.target}: ${n.summary || v.help}`),
  );
}

/**
 * Scan the page and fail the test on any violation. The assertion is soft, so
 * one test reports every state it scans instead of stopping at the first; the
 * test still fails at its end.
 */
export async function expectAccessible(page: Page, label: string): Promise<void> {
  const violations = await scanA11y(page, label);
  expect.soft(describeViolations(violations), `axe (${WCAG_TAGS.join(", ")}): ${label}`).toEqual([]);
}

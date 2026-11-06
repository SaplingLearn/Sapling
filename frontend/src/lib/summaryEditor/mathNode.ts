import { Node, mergeAttributes } from "@tiptap/core";
import katex from "katex";

export interface MathNodeOptions {
  HTMLAttributes: Record<string, unknown>;
}

declare module "@tiptap/core" {
  interface Commands<ReturnType> {
    mathNode: {
      setMathLatex: (latex: string) => ReturnType;
    };
  }
}

/** Renders LaTeX to a KaTeX HTML string. Never throws (`throwOnError:
 * false`) -- malformed LaTeX (whether AI-generated or student-edited)
 * degrades to KaTeX's own inline error markup instead of crashing the
 * editor's render path. */
export function renderMathHTML(latex: string, block: boolean): string {
  return katex.renderToString(latex, { throwOnError: false, displayMode: block });
}

/** An inline atom node storing raw LaTeX source, rendered via KaTeX. Real
 * glyph rendering needs a NodeView -- a mark can only restyle existing
 * text, it can't replace what's displayed. Editing is click-to-open-a-
 * popup on the raw LaTeX source, not WYSIWYG math editing. */
export const MathNode = Node.create<MathNodeOptions>({
  name: "math",
  group: "inline",
  inline: true,
  atom: true,
  addOptions() {
    return { HTMLAttributes: {} };
  },
  addAttributes() {
    return {
      latex: { default: "" },
      block: { default: false },
    };
  },
  parseHTML() {
    return [{ tag: "span[data-math-latex]" }];
  },
  renderHTML({ HTMLAttributes, node }) {
    return [
      "span",
      mergeAttributes(this.options.HTMLAttributes, HTMLAttributes, {
        "data-math-latex": node.attrs.latex,
        "data-math-block": node.attrs.block ? "true" : "false",
      }),
    ];
  },
  addNodeView() {
    return ({ node, getPos, editor }) => {
      const dom = document.createElement("span");
      dom.className = "summary-math-node";
      dom.innerHTML = renderMathHTML(node.attrs.latex, node.attrs.block);
      dom.addEventListener("click", () => {
        const next = window.prompt("Edit LaTeX:", node.attrs.latex);
        if (next === null || typeof getPos !== "function") return;
        const pos = getPos();
        editor.chain().setNodeSelection(pos).updateAttributes("math", { latex: next }).run();
      });
      return {
        dom,
        update: (updatedNode) => {
          if (updatedNode.type.name !== "math") return false;
          dom.innerHTML = renderMathHTML(updatedNode.attrs.latex, updatedNode.attrs.block);
          return true;
        },
      };
    };
  },
  addCommands() {
    return {
      setMathLatex:
        (latex: string) =>
        ({ commands }) =>
          commands.insertContent({ type: this.name, attrs: { latex, block: false } }),
    };
  },
});

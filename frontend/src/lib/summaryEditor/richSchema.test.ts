// @vitest-environment jsdom
import { describe, it, expect } from "vitest";
import { Editor } from "@tiptap/core";
import StarterKit from "@tiptap/starter-kit";
import Table from "@tiptap/extension-table";
import TableRow from "@tiptap/extension-table-row";
import TableCell from "@tiptap/extension-table-cell";
import TableHeader from "@tiptap/extension-table-header";
import Underline from "@tiptap/extension-underline";
import Highlight from "@tiptap/extension-highlight";

import { MathNode } from "./mathNode";

const extensions = [
  StarterKit, Table.configure({ resizable: false }), TableRow, TableCell, TableHeader,
  Underline, Highlight, MathNode,
];

describe("SummaryEditor's rich schema", () => {
  it("registers table, underline, highlight, and math nodes/marks", () => {
    const editor = new Editor({ extensions });
    expect(editor.schema.nodes.table).toBeDefined();
    expect(editor.schema.nodes.tableRow).toBeDefined();
    expect(editor.schema.nodes.tableCell).toBeDefined();
    expect(editor.schema.nodes.tableHeader).toBeDefined();
    expect(editor.schema.marks.underline).toBeDefined();
    expect(editor.schema.marks.highlight).toBeDefined();
    expect(editor.schema.nodes.math).toBeDefined();
    editor.destroy();
  });

  it("can insert a table via the Table extension's own command", () => {
    const editor = new Editor({
      extensions,
      content: { type: "doc", content: [{ type: "paragraph", content: [] }] },
    });
    const inserted = editor.commands.insertTable({ rows: 2, cols: 2, withHeaderRow: true });
    expect(inserted).toBe(true);
    const json = editor.getJSON();
    expect(json.content?.some((n) => n.type === "table")).toBe(true);
    editor.destroy();
  });

  it("round-trips a backend-built table node unchanged", () => {
    const editor = new Editor({ extensions, content: { type: "doc", content: [] } });
    const tableJSON = {
      type: "table",
      content: [
        { type: "tableRow", content: [{ type: "tableHeader", content: [{ type: "paragraph", content: [{ type: "text", text: "A" }] }] }] },
        { type: "tableRow", content: [{ type: "tableCell", content: [{ type: "paragraph", content: [{ type: "text", text: "1" }] }] }] },
      ],
    };
    // tableCell/tableHeader always carry colspan/rowspan/colwidth attrs in
    // the schema (@tiptap/extension-table-cell), and ProseMirror's
    // Node.toJSON() serializes `attrs` whenever the node type has any —
    // even when they're just the defaults. So a table built without
    // explicit attrs round-trips with those defaults filled in; the
    // expectation below reflects that real round-trip, not a literal replay
    // of the input.
    const expectedJSON = {
      ...tableJSON,
      content: tableJSON.content.map((row) => ({
        ...row,
        content: row.content.map((cell) => ({
          ...cell,
          attrs: { colspan: 1, rowspan: 1, colwidth: null },
        })),
      })),
    };
    editor.commands.setContent({ type: "doc", content: [tableJSON] });
    expect(editor.getJSON().content?.[0]).toEqual(expectedJSON);
    editor.destroy();
  });
});

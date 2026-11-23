import { describe, expect, it } from "vitest";
import { codeEdit, overlapsNoteBlock } from "./codeEditing";

describe("fenced code editing", () => {
  it.each([["{", "}"], ["[", "]"], ["(", ")"], ['"', '"'], ["'", "'"], ["`", "`"]])(
    "wraps a selection with %s and %s",
    (key, close) => {
      expect(codeEdit("~~~js\nword\n~~~", 6, 10, key, false)).toEqual({
        body: "~~~js\n" + key + "word" + close + "\n~~~",
        start: 7,
        end: 11,
      });
    },
  );

  it("leaves prose and closing fence lines alone", () => {
    const note = "Text\n```js\ncode\n```\nMore";
    expect(codeEdit(note, 1, 1, "(", false)).toBeUndefined();
    expect(codeEdit(note, note.indexOf("```", 8), note.indexOf("```", 8), "Tab", false)).toBeUndefined();
    expect(codeEdit(note, note.length, note.length, "Tab", false)).toBeUndefined();
  });

  it("indents and outdents a code line with Tab and Shift+Tab", () => {
    const note = "```\ncode\n```";
    const indented = codeEdit(note, 4, 4, "Tab", false);
    expect(indented).toEqual({ body: "```\n  code\n```", start: 6, end: 6 });
    expect(codeEdit(indented!.body, 6, 6, "Tab", true)).toEqual({ body: note, start: 4, end: 4 });
  });
});

describe("block insertion boundaries", () => {
  it.each(["```js\ncode\n```", "~~~\ncode\n~~~", "$$\nx^2\n$$"])(
    "rejects insertion inside or around an existing block",
    (block) => {
      const text = "Before\n" + block + "\nAfter";
      const inside = text.indexOf("\n", 7) + 1;
      expect(overlapsNoteBlock(text, inside, inside)).toBe(true);
      expect(overlapsNoteBlock(text, 3, text.length)).toBe(true);
      expect(overlapsNoteBlock(text, 0, 6)).toBe(false);
      expect(overlapsNoteBlock(text, text.length, text.length)).toBe(false);
      expect(overlapsNoteBlock(block, block.length, block.length)).toBe(false);
    },
  );

  it("rejects insertion inside an unfinished block", () => {
    const text = "```js\nconst x = 1;";
    expect(overlapsNoteBlock(text, text.length, text.length)).toBe(true);
  });
});

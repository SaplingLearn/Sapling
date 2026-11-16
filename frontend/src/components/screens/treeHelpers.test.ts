import { describe, it, expect } from "vitest";
import type { GraphNode } from "@/lib/data";
import { deleteButtonStyle, highlightIdFor, selectedCourseIdOf } from "./treeHelpers";

const node = { id: "n1", name: "Recursion" } as GraphNode;

describe("selectedCourseIdOf", () => {
  it("maps the 'all' filter to null", () => {
    expect(selectedCourseIdOf("all")).toBeNull();
  });
  it("passes a course id through", () => {
    expect(selectedCourseIdOf("course-1")).toBe("course-1");
  });
});

describe("highlightIdFor", () => {
  it("prefers the suggested node", () => {
    expect(highlightIdFor("s1", node)).toBe("s1");
  });
  it("falls back to the selected node", () => {
    expect(highlightIdFor(undefined, node)).toBe("n1");
    expect(highlightIdFor("", node)).toBe("n1");
  });
  it("is undefined with neither", () => {
    expect(highlightIdFor(undefined, null)).toBeUndefined();
  });
});

describe("deleteButtonStyle", () => {
  it("is a plain full-width button unarmed", () => {
    expect(deleteButtonStyle(false)).toEqual({
      width: "100%", marginTop: 12,
      background: undefined, color: undefined, borderColor: undefined,
    });
  });
  it("uses the error palette armed", () => {
    expect(deleteButtonStyle(true)).toEqual({
      width: "100%", marginTop: 12,
      background: "var(--err-soft)", color: "var(--err)", borderColor: "var(--err)",
    });
  });
});

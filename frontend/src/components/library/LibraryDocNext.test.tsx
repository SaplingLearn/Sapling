// @vitest-environment jsdom
/** The details dialog keeps the old Library panel's next steps (W8.1). */
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";

import type { Document as Doc } from "@/lib/types";

const state = vi.hoisted(() => ({ flags: {} as Record<string, string> }));
vi.mock("@/context/FlagsContext", () => ({ useFlagMap: () => ({ flags: state.flags, ready: true }) }));

import { LibraryDocNext } from "./LibraryDocNext";

const DOC = {
  id: "d1", user_id: "u1", course_id: "c1", file_name: "a.pdf", category: "lecture_notes",
  summary: null, created_at: "", processed_at: null,
  concept_notes: [{ name: "Limits", description: "", node_id: "n1" }],
  check_items_status: "done",
} as unknown as Doc;

afterEach(() => { cleanup(); state.flags = {}; });

describe("LibraryDocNext", () => {
  it("offers the map and a quiz on the document's own concept once checks are ready", () => {
    state.flags = { learning_loop: "on" };
    render(<LibraryDocNext doc={DOC} />);
    expect(screen.getByTestId("library-next-status").textContent).toContain("Checks ready");
    expect(screen.getByTestId("library-next-quiz").getAttribute("href")).toContain("n1");
    expect(screen.getByTestId("library-next-tree").getAttribute("href")).toBe("/tree?course=c1");
  });

  it("offers no quiz while the checks are drafting", () => {
    state.flags = { learning_loop: "on" };
    render(<LibraryDocNext doc={{ ...DOC, check_items_status: "pending" }} />);
    expect(screen.getByTestId("library-next-status").textContent).toContain("Checks drafting");
    expect(screen.queryByTestId("library-next-quiz")).toBeNull();
  });

  it("links to no hidden destination", () => {
    state.flags = { learning_loop: "on", hide_tree: "on", hide_quiz: "on" };
    render(<LibraryDocNext doc={DOC} />);
    expect(screen.queryByTestId("library-next-tree")).toBeNull();
    expect(screen.queryByTestId("library-next-quiz")).toBeNull();
  });
});

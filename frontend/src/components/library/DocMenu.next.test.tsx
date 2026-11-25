// @vitest-environment jsdom
import React from "react";
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { Document as Doc } from "@/lib/types";

const flags = vi.hoisted(() => ({ current: {} as Record<string, string> }));
vi.mock("@/context/FlagsContext", () => ({
  useFlagMap: () => ({ flags: flags.current, ready: true }),
}));

import { DocMenu, type MenuPosition } from "./DocMenu";

const POSITION: MenuPosition = {
  top: "0px", bottom: "auto", right: "0px", maxHeight: "400px", origin: "top right",
};

const DOC: Doc = {
  id: "d1", user_id: "u1", course_id: "c1", file_name: "notes.pdf",
  category: "lecture_notes", summary: null,
  concept_notes: [{ name: "Recursion", description: "", node_id: "n1" }],
  created_at: "2026-03-01T00:00:00Z", processed_at: "2026-03-01T00:00:00Z",
};

function open(doc: Doc) {
  const noop = () => {};
  render(
    <DocMenu
      doc={doc} position={POSITION} closing={false} courses={[]} folders={[]}
      sub={null} onSub={noop} onClose={noop} onRename={noop} onMoveCourse={noop}
      onMoveFolder={noop} onType={noop} onScan={noop} scanState="idle" onTrash={noop}
    />,
  );
}

afterEach(cleanup);

describe("DocMenu next steps (W8.1, carried into the v2 Library)", () => {
  it("links the document's concepts to the Tree and a quiz", () => {
    flags.current = {};
    open(DOC);
    expect(screen.getByTestId("library-next-status")).toHaveTextContent("1 concept added");
    expect(screen.getByTestId("library-next-tree")).toHaveAttribute("href", expect.stringContaining("/tree"));
    expect(screen.getByTestId("library-next-quiz")).toBeInTheDocument();
  });

  it("with the learning loop on, waits for the document's checks", () => {
    flags.current = { learning_loop: "on" };
    open({ ...DOC, check_items_status: "pending" });
    expect(screen.getByTestId("library-next-status")).toHaveTextContent("Checks drafting");
    expect(screen.queryByTestId("library-next-quiz")).toBeNull();
  });

  it("says nothing for a document with no concepts and no course", () => {
    flags.current = {};
    open({ ...DOC, course_id: null, concept_notes: null });
    expect(screen.queryByTestId("library-next")).toBeNull();
  });
});

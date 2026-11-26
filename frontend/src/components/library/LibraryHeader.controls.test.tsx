// @vitest-environment jsdom
/**
 * The header's three controls, pinned.
 *
 * The Study Guide button moved four times during the rebuild — into the
 * header, left of Upload, up a row, and back down — and nothing failed on any
 * of them, because no test named it. The same was true of the sizing the
 * owner asked for: Study Guide, Upload and the search field share one height
 * and one type scale (`primitives.ts::CONTROL_H`), and that agreement was
 * held only by three separate inline styles agreeing by hand.
 *
 * This file is the test that would have caught a drift in either, plus the
 * keyboard exit from the menus, which the handoff never bound.
 */
import React from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";

vi.mock("@/context/UserContext", () => ({
  useUser: () => ({ userId: "u1", userReady: true }),
}));
vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn() }) }));
vi.mock("@/context/FlagsContext", () => ({
  useFlagMap: () => ({ flags: {}, ready: true }),
}));
vi.mock("@/lib/api", () => ({
  getDocuments: vi.fn(),
  getCourses: vi.fn(),
  getFolders: vi.fn(async () => ({ folders: [] })),
  getTrashedDocuments: vi.fn(async () => ({ documents: [] })),
  deleteDocument: vi.fn(), restoreDocument: vi.fn(), purgeDocument: vi.fn(),
  updateDocument: vi.fn(), createBlankDocument: vi.fn(), createFolder: vi.fn(),
  renameFolder: vi.fn(), deleteFolder: vi.fn(), scanDocumentConcepts: vi.fn(),
  scanCourseConcepts: vi.fn(), uploadDocumentStream: vi.fn(),
}));
vi.mock("@/lib/studyGuide/api", () => ({ listGuides: vi.fn(async () => ({ guides: [] })) }));

import { getCourses, getDocuments, type EnrolledCourse } from "@/lib/api";
import { Library } from "./Library";
import { CONTROL_H } from "./primitives";
import { ToastProvider } from "../ToastProvider";

const COURSE = {
  enrollment_id: "e1", course_id: "c1", course_code: "MATH210",
  course_name: "Linear Algebra", color: "#C06020",
} as EnrolledCourse;
const DOC = {
  id: "d1", user_id: "u1", course_id: "c1", file_name: "Determinants Lecture 7.pdf",
  category: "lecture_notes" as const, summary: "Cofactor expansion.",
  concept_notes: [], page_count: 18,
  created_at: "2026-11-05T00:00:00Z", processed_at: "2026-11-05T00:00:00Z",
};

const renderLibrary = async () => {
  render(<ToastProvider><Library /></ToastProvider>);
  await screen.findByTestId("library-doc-d1");
};

beforeEach(() => {
  vi.spyOn(console, "error").mockImplementation(() => {});
  vi.mocked(getDocuments).mockResolvedValue({ documents: [DOC] } as never);
  vi.mocked(getCourses).mockResolvedValue({ courses: [COURSE] });
});
afterEach(cleanup);

describe("the Study Guide button", () => {
  it("is in the header, and links to the Study hub's guides", async () => {
    await renderLibrary();
    const guides = screen.getByTestId("library-guides");
    expect(guides.tagName).toBe("A");
    expect(guides.getAttribute("href")).toMatch(/study/i);
    expect(guides.textContent).toMatch(/study guide/i);
  });

  it("sits immediately before Upload, in that order", async () => {
    await renderLibrary();
    const guides = screen.getByTestId("library-guides");
    const upload = screen.getByTestId("library-upload");
    // `compareDocumentPosition` is order in the document, which is what
    // "before" means here — a flex row renders them left to right.
    const order = guides.compareDocumentPosition(upload);
    expect(order & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it("is the same height and type scale as Upload and the search field", async () => {
    await renderLibrary();
    const guides = screen.getByTestId("library-guides");
    const upload = screen.getByTestId("library-upload");
    const search = screen.getByTestId("library-search").closest("label")!;
    for (const el of [guides, upload, search]) {
      expect(el.style.height, `${el.getAttribute("data-testid") ?? "search"} height`)
        .toBe(`${CONTROL_H}px`);
    }
    // The owner's note was that Upload should match the Study button's scale,
    // not merely its box.
    expect(guides.style.fontSize).toBe(upload.style.fontSize);
  });
});

describe("the header menus close on Escape", () => {
  /**
   * All three of the header's menus, not just Upload. They share `menu` and
   * `onMenu`, so one listener serves them — but "shares the state" is the
   * assumption under the fix, and it is the assumption worth pinning. Sort
   * and Type carry no testid, so they are reached the way a screen reader
   * would: the buttons that own a menu.
   */
  const openers = () =>
    screen.getAllByRole("button", { expanded: false }).filter(
      b => b.getAttribute("aria-haspopup") === "menu");

  it.each([0, 1, 2])("menu %i closes", async (i) => {
    await renderLibrary();
    const all = openers();
    expect(all.length, "three menu buttons in the header").toBe(3);
    fireEvent.click(all[i]);
    await screen.findByRole("menu");

    fireEvent.keyDown(document, { key: "Escape" });
    await waitFor(() => expect(screen.queryByRole("menu")).toBeNull());
  });

  it("a key that is not Escape leaves the menu open", async () => {
    await renderLibrary();
    fireEvent.click(screen.getByTestId("library-upload"));
    await screen.findByRole("menu");

    fireEvent.keyDown(document, { key: "a" });
    expect(screen.queryByRole("menu")).not.toBeNull();
  });

  it("Escape with no menu open does not throw", async () => {
    await renderLibrary();
    expect(() => fireEvent.keyDown(document, { key: "Escape" })).not.toThrow();
  });
});

// The Trash chip is deliberately NOT pinned here. The owner's 2026-11-25 call
// to drop its count was made against a header chip that this Library does not
// have: Trash is the last option of the scope switcher now, an icon and a
// sub-line rather than a word and a tabular count. `Library.carryover.test`
// and `designParity.test` already assert that arrangement, including that no
// `library-trash` testid exists.

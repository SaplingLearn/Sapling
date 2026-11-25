// @vitest-environment jsdom
/**
 * Nothing the old Library did was dropped (handoff README §2.3).
 *
 * The redesign removes the preview panel and the course rail, so each of the
 * old page's capabilities had to land somewhere new. This walks them one by
 * one and finds them — which is the check the handoff actually asks for, and
 * the one that would catch a quiet regression later.
 */
import React from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";

const push = vi.hoisted(() => vi.fn());
vi.mock("@/context/UserContext", () => ({
  useUser: () => ({ userId: "u1", userReady: true }),
}));
vi.mock("next/navigation", () => ({ useRouter: () => ({ push }) }));
vi.mock("@/context/FlagsContext", () => ({
  useFlagMap: () => ({ flags: {}, ready: true }),
}));
vi.mock("@/lib/api", () => ({
  getDocuments: vi.fn(),
  getCourses: vi.fn(),
  deleteDocument: vi.fn(async () => ({ deleted: true })),
  scanDocumentConcepts: vi.fn(),
  scanCourseConcepts: vi.fn(),
  uploadDocumentStream: vi.fn(),
}));
vi.mock("@/lib/libraryApi", () => ({
  getFolders: vi.fn(async () => ({ folders: [] })),
  getTrashedDocuments: vi.fn(async () => ({ documents: [] })),
  restoreDocument: vi.fn(async () => ({ restored: true })),
  purgeDocument: vi.fn(async () => ({ deleted: true, purged: true })),
  updateDocument: vi.fn(async () => ({ id: "d1" })),
  createBlankDocument: vi.fn(),
  createFolder: vi.fn(),
  renameFolder: vi.fn(),
  deleteFolder: vi.fn(),
}));
vi.mock("@/lib/studyGuide/api", () => ({ listGuides: vi.fn(async () => ({ guides: [] })) }));

import {
  deleteDocument, getCourses, getDocuments, scanCourseConcepts,
  scanDocumentConcepts, type EnrolledCourse,
} from "@/lib/api";
import { updateDocument } from "@/lib/libraryApi";
import { Library } from "./Library";
import { ToastProvider } from "../ToastProvider";

const COURSE = {
  enrollment_id: "e1", course_id: "c1", course_code: "MATH210",
  course_name: "Linear Algebra", color: "#C06020",
} as EnrolledCourse;

const DOC = {
  id: "d1", user_id: "u1", course_id: "c1", file_name: "Determinants Lecture 7.pdf",
  category: "lecture_notes" as const,
  summary: "Cofactor expansion, row operations, and why a zero determinant means no inverse.",
  concept_notes: [
    { name: "Determinants", description: "How much a matrix scales area." },
    { name: "Inverses", description: "Undoing a matrix." },
  ],
  page_count: 18,
  created_at: "2026-11-05T00:00:00Z", processed_at: "2026-11-05T00:00:00Z",
};

const renderLibrary = async () => {
  render(<ToastProvider><Library /></ToastProvider>);
  await screen.findByTestId("library-doc-d1");
};

/** Open a row's "⋯" dialog — what replaced the old detail panel. */
async function openRowMenu(id = "d1") {
  const row = screen.getByTestId(`library-doc-${id}`);
  fireEvent.click(row.querySelector('[aria-label="Details and actions"]') as HTMLElement);
  return screen.findByTestId("library-doc-menu");
}

beforeEach(() => {
  vi.spyOn(console, "error").mockImplementation(() => {});
  vi.mocked(getDocuments).mockResolvedValue({ documents: [DOC] } as never);
  vi.mocked(getCourses).mockResolvedValue({ courses: [COURSE] });
  vi.mocked(scanDocumentConcepts).mockResolvedValue({ concepts: [], added: 2, existing: 1 });
  vi.mocked(scanCourseConcepts).mockResolvedValue({ concepts: [], added: 0, existing: 4 });
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.clearAllMocks();
});

describe("the old page's content still has a home", () => {
  it("the summary is the row's own subtitle", async () => {
    await renderLibrary();
    expect(screen.getByTestId("library-doc-d1").textContent).toContain(DOC.summary);
  });

  it("the key concepts are in the row's dialog, with their descriptions", async () => {
    await renderLibrary();
    const menu = await openRowMenu();
    expect(within(menu).getByText("Key Concepts (2)")).toBeTruthy();
    const chip = within(menu).getByText("Determinants");
    expect(chip.getAttribute("title")).toBe("How much a matrix scales area.");
    expect(within(menu).getByText("Inverses")).toBeTruthy();
  });

  it("the summary is in the dialog too, where the panel used to show it", async () => {
    await renderLibrary();
    const menu = await openRowMenu();
    expect(within(menu).getByText("Summary")).toBeTruthy();
    expect(menu.textContent).toContain(DOC.summary);
  });

  it("a document with neither says nothing rather than showing empty headings", async () => {
    vi.mocked(getDocuments).mockResolvedValue({
      documents: [{ ...DOC, summary: null, concept_notes: null }],
    } as never);
    await renderLibrary();
    const menu = await openRowMenu();
    expect(within(menu).queryByText("Summary")).toBeNull();
    expect(within(menu).queryByText(/^Key Concepts/)).toBeNull();
  });
});

describe("the old page's actions all still work", () => {
  it("the per-document concept scan runs and reports what it added", async () => {
    await renderLibrary();
    await openRowMenu();
    fireEvent.click(screen.getByTestId("library-detail-scan"));
    await waitFor(() => expect(vi.mocked(scanDocumentConcepts)).toHaveBeenCalledWith("d1", "u1"));
    expect(await screen.findByText(/Added 2 concepts to your graph/)).toBeTruthy();
  });

  it("the course-wide scan is offered while one course is open", async () => {
    await renderLibrary();
    // It is scoped to a course, so it is absent from All Documents.
    expect(screen.queryByTestId("library-course-scan")).toBeNull();

    fireEvent.click(screen.getByTestId("library-course-switcher"));
    fireEvent.click(screen.getByRole("option", { name: /MATH210/ }));
    fireEvent.click(await screen.findByTestId("library-course-scan"));

    await waitFor(() => expect(vi.mocked(scanCourseConcepts)).toHaveBeenCalledWith("c1", "u1"));
    expect(await screen.findByText(/already covers it \(4 concepts\)/)).toBeTruthy();
  });

  it("the category change the old page had is the dialog's Type", async () => {
    await renderLibrary();
    await openRowMenu();
    fireEvent.click(screen.getByRole("menuitem", { name: /^Type/ }));
    fireEvent.click(await screen.findByRole("menuitemradio", { name: /Slides/ }));
    await waitFor(() => expect(vi.mocked(updateDocument))
      .toHaveBeenCalledWith("d1", "u1", { category: "slides" }));
  });

  it("delete still deletes — and is now undoable", async () => {
    await renderLibrary();
    await openRowMenu();
    fireEvent.click(screen.getByTestId("library-detail-delete"));

    await waitFor(() => expect(vi.mocked(deleteDocument)).toHaveBeenCalledWith("d1", "u1"));
    const toast = await screen.findByTestId("library-toast");
    expect(toast.textContent).toContain("Moved to Trash");
    expect(within(toast).getByTestId("library-toast-undo")).toBeTruthy();
  });

  it("double-clicking a row opens its notes, as the design specifies", async () => {
    await renderLibrary();
    fireEvent.doubleClick(screen.getByTestId("library-doc-d1"));
    expect(push).toHaveBeenCalledWith("/library/d1/notes");
  });

  it("the search still reaches the summary and the concepts", async () => {
    await renderLibrary();
    const search = screen.getByTestId("library-search");

    fireEvent.change(search, { target: { value: "cofactor" } });
    expect(screen.getByTestId("library-doc-d1").textContent).toContain("In summary:");

    fireEvent.change(search, { target: { value: "inverses" } });
    expect(screen.getByTestId("library-doc-d1").textContent).toContain("Linked concept: Inverses");

    fireEvent.change(search, { target: { value: "nothing matches this" } });
    expect(screen.queryByTestId("library-doc-d1")).toBeNull();
    expect(screen.getByTestId("library-empty")).toBeTruthy();
  });

  it("`/` focuses the search and Escape clears it", async () => {
    await renderLibrary();
    const search = screen.getByTestId("library-search") as HTMLInputElement;

    fireEvent.keyDown(window, { key: "/" });
    expect(document.activeElement).toBe(search);

    fireEvent.change(search, { target: { value: "determinants" } });
    fireEvent.keyDown(search, { key: "Escape" });
    expect(search.value).toBe("");
  });

  it("the List ⇄ Panel toggle still switches the layout", async () => {
    await renderLibrary();
    expect(screen.getByTestId("library-view-list").getAttribute("aria-selected")).toBe("true");

    fireEvent.click(screen.getByTestId("library-view-panel"));
    expect(screen.getByTestId("library-view-panel").getAttribute("aria-selected")).toBe("true");
    // The switch cross-slides, so for one slide BOTH views are mounted and the
    // document is drawn twice — the outgoing copy `aria-hidden`. Wait for the
    // leaving half to go before asserting there is one card.
    await waitFor(() =>
      expect(screen.getAllByTestId("library-doc-d1")).toHaveLength(1));
  });

  it("the course scope filters as the old rail did", async () => {
    vi.mocked(getDocuments).mockResolvedValue({
      documents: [DOC, { ...DOC, id: "d2", course_id: null, file_name: "Loose.pdf" }],
    } as never);
    await renderLibrary();
    expect(screen.getByTestId("library-doc-d2")).toBeTruthy();

    fireEvent.click(screen.getByTestId("library-course-switcher"));
    fireEvent.click(screen.getByRole("option", { name: /MATH210/ }));
    expect(screen.queryByTestId("library-doc-d2")).toBeNull();

    fireEvent.click(screen.getByTestId("library-course-switcher"));
    fireEvent.click(screen.getByRole("option", { name: /No Course/ }));
    expect(screen.getByTestId("library-doc-d2")).toBeTruthy();
    expect(screen.queryByTestId("library-doc-d1")).toBeNull();
  });
});

describe("what the redesign adds, end to end", () => {
  it("the Trash holds a deleted document, restores it, and purges it", async () => {
    const { getTrashedDocuments } = await import("@/lib/libraryApi");
    vi.mocked(getTrashedDocuments).mockResolvedValue({
      documents: [{ ...DOC, id: "t1", deleted_at: "2026-11-10T00:00:00Z" }],
    } as never);
    await renderLibrary();

    // The Trash is the course switcher's last option.
    fireEvent.click(screen.getByTestId("library-course-switcher"));
    fireEvent.click(screen.getByRole("option", { name: /Trash/ }));
    const row = await screen.findByTestId("library-doc-t1");
    expect(within(row).getByText("Restore")).toBeTruthy();

    // Empty Trash takes two presses, as the design's copy says.
    const empty = screen.getByTestId("library-empty-trash");
    expect(empty.textContent).toBe("Empty Trash");
    fireEvent.click(empty);
    expect(screen.getByTestId("library-empty-trash").textContent)
      .toBe("Click Again to Empty Trash");
  });

  it("the switcher lists the Trash last, with its count, and picking it opens the Trash", async () => {
    const { getTrashedDocuments } = await import("@/lib/libraryApi");
    vi.mocked(getTrashedDocuments).mockResolvedValue({
      documents: [
        { ...DOC, id: "t1", deleted_at: "2026-11-10T00:00:00Z" },
        { ...DOC, id: "t2", file_name: "Old Notes.pdf", deleted_at: "2026-11-11T00:00:00Z" },
      ],
    } as never);
    await renderLibrary();
    // No Trash chip beside the switcher any more.
    expect(screen.queryByTestId("library-trash")).toBeNull();

    const switcher = screen.getByTestId("library-course-switcher");
    fireEvent.click(switcher);
    const options = screen.getAllByRole("option");
    const trash = options[options.length - 1];
    expect(trash.textContent).toContain("Trash");
    await waitFor(() =>
      expect(trash.textContent).toContain("Deleted after 30 days · 2 documents"));
    expect(trash.getAttribute("aria-selected")).toBe("false");

    fireEvent.click(trash);
    // The heading names the Trash, and its rows offer Restore.
    await waitFor(() => expect(switcher.textContent).toContain("Trash"));
    const row = await screen.findByTestId("library-doc-t1");
    expect(within(row).getByText("Restore")).toBeTruthy();

    // A selection there offers Restore and Delete Forever, not Move To.
    fireEvent.click(screen.getByLabelText("Select Determinants Lecture 7"));
    const bar = await screen.findByTestId("library-bulk-bar");
    expect(within(bar).getByText("Restore")).toBeTruthy();
    expect(within(bar).getByText("Delete Forever")).toBeTruthy();
    expect(within(bar).queryByText("Move To")).toBeNull();

    // And reopened, the switcher marks the Trash as the open scope.
    fireEvent.click(switcher);
    const reopened = screen.getAllByRole("option");
    expect(reopened[reopened.length - 1].getAttribute("aria-selected")).toBe("true");
  });

  it("a row can be renamed in place", async () => {
    await renderLibrary();
    await openRowMenu();
    fireEvent.click(screen.getByRole("menuitem", { name: "Rename" }));

    const input = await screen.findByLabelText("Name") as HTMLInputElement;
    expect(input.value).toBe("Determinants Lecture 7");
    fireEvent.change(input, { target: { value: "Determinants, revised" } });
    fireEvent.blur(input);

    // The extension the row hides is put back on the stored name.
    await waitFor(() => expect(vi.mocked(updateDocument))
      .toHaveBeenCalledWith("d1", "u1", { file_name: "Determinants, revised.pdf" }));
  });

  it("the current row steps aside for checked rows, and stays gone after Clear", async () => {
    await renderLibrary();
    const row = screen.getByTestId("library-doc-d1");
    fireEvent.click(row);
    expect(row.getAttribute("aria-selected")).toBe("true");
    // A neutral tint with no outline: never the selection bar's green.
    expect(row.style.background).not.toBe("");
    expect(row.style.boxShadow).toBe("");

    fireEvent.click(screen.getByLabelText("Select all"));
    expect(row.getAttribute("aria-selected")).toBe("false");

    const bar = await screen.findByTestId("library-bulk-bar");
    fireEvent.click(within(bar).getByText("Clear"));
    await waitFor(() => expect(screen.queryByTestId("library-bulk-bar")).toBeNull());
    expect(row.getAttribute("aria-selected")).toBe("false");
  });

  it("checking rows offers the bulk bar, and clears", async () => {
    await renderLibrary();
    fireEvent.click(screen.getByLabelText("Select Determinants Lecture 7"));
    const bar = await screen.findByTestId("library-bulk-bar");
    expect(bar.textContent).toContain("1 Selected");

    fireEvent.click(within(bar).getByText("Clear"));
    // It plays its exit before it goes (BulkBarReveal), still reading what it
    // read, and then it is gone.
    expect(screen.getByTestId("library-bulk-reveal").dataset.phase).toBe("out");
    expect(bar.textContent).toContain("1 Selected");
    await waitFor(() => expect(screen.queryByTestId("library-bulk-bar")).toBeNull());
  });

  it("clearing the selection closes an open Move To menu with it", async () => {
    await renderLibrary();
    fireEvent.click(screen.getByLabelText("Select Determinants Lecture 7"));
    const bar = await screen.findByTestId("library-bulk-bar");
    fireEvent.click(within(bar).getByText("Move To"));
    expect(await screen.findByTestId("library-bulk-menu")).toBeTruthy();

    fireEvent.click(within(bar).getByText("Clear"));
    await waitFor(() => expect(screen.queryByTestId("library-bulk-bar")).toBeNull());

    // Selecting again brings the bar back with its menu shut.
    fireEvent.click(screen.getByLabelText("Select Determinants Lecture 7"));
    await screen.findByTestId("library-bulk-bar");
    expect(screen.queryByTestId("library-bulk-menu")).toBeNull();
  });
});

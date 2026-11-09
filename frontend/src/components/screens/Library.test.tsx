// @vitest-environment jsdom
/**
 * Library redesign ("Sapling Library.dc.html"): explorer, filters, preview,
 * folders, moves and deletes with undo, rename, and + New.
 */

import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, cleanup, fireEvent, act, within, waitFor } from "@testing-library/react";

const push = vi.fn();
let navSections: { label: string; items: { href: string }[] }[] = [];

vi.mock("@/context/UserContext", () => ({ useUser: () => ({ userId: "u1", userReady: true }) }));
vi.mock("@/lib/useIsMobile", () => ({ useIsMobile: () => false }));
vi.mock("@/lib/useNavSections", () => ({ useVisibleNavSections: () => navSections }));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push }),
  // The Library seeds its course/type filters from the URL (the Study hub
  // links in with ?course=…&type=study_guide); unset here = no filter.
  useSearchParams: () => new URLSearchParams(),
}));
vi.mock("../DocumentUploadModal", () => ({
  DocumentUploadModal: ({ open }: { open: boolean }) => (open ? <div data-testid="upload-modal" /> : null),
}));
vi.mock("@/lib/api", () => ({
  getDocuments: vi.fn(),
  deleteDocument: vi.fn(async () => ({ deleted: true })),
  getCourses: vi.fn(),
  createNote: vi.fn(),
}));
vi.mock("@/lib/libraryApi", () => ({
  getLibraryFolders: vi.fn(),
  createLibraryFolder: vi.fn(),
  renameLibraryFolder: vi.fn(async () => ({})),
  deleteLibraryFolder: vi.fn(async () => ({ deleted: true })),
  moveDocumentsToFolder: vi.fn(async () => ({ moved: 1 })),
  renameLibraryDocument: vi.fn(),
}));

import { Library } from "./Library";
import { ToastProvider } from "../ToastProvider";
import { getDocuments, getCourses, deleteDocument, createNote } from "@/lib/api";
import {
  getLibraryFolders, createLibraryFolder, moveDocumentsToFolder, renameLibraryDocument,
} from "@/lib/libraryApi";

const course = (id: string, code: string, name: string, color: string | null) => ({
  enrollment_id: `e-${id}`, course_id: id, course_code: code, course_name: name, school: "", department: "",
  color, nickname: null, node_count: 0, enrolled_at: "", term: "Fall 2026",
});

const DOCS = [
  {
    id: "d1", user_id: "u1", course_id: "c1", file_name: "Recursion Workshop.pdf", category: "lecture_notes",
    summary: "Explore base cases and recursive calls.", created_at: "2026-11-06T12:00:00Z", processed_at: "x",
    concept_notes: [{ name: "Functions", description: "A function maps inputs." }, { name: "Recursion", description: "A function that calls itself." }],
  },
  {
    id: "d2", user_id: "u1", course_id: "c2", file_name: "Determinants.pptx", category: "slides",
    summary: "Cofactor expansion and row operations.", created_at: "2026-11-05T12:00:00Z", processed_at: "x",
    concept_notes: [{ name: "Inverses", description: "Undo a matrix." }],
  },
  {
    id: "d3", user_id: "u1", course_id: "c2", file_name: "Problem Set 6.docx", category: "assignment",
    summary: "Twelve problems on spanning sets.", created_at: "2026-11-03T12:00:00Z", processed_at: "x", concept_notes: [],
  },
];

function setup(placements: Record<string, string> = {}) {
  vi.mocked(getDocuments).mockResolvedValue({ documents: DOCS } as never);
  vi.mocked(getCourses).mockResolvedValue({ courses: [course("c1", "CS101", "Intro to CS", "#2868B0"), course("c2", "MATH210", "Linear Algebra", null)] } as never);
  vi.mocked(getLibraryFolders).mockResolvedValue({
    folders: [{ id: "f1", course_id: "c2", name: "Midterm Prep", created_at: "" }],
    placements,
  });
  return render(<ToastProvider><Library /></ToastProvider>);
}

beforeEach(() => { navSections = [{ label: "Tools", items: [{ href: "/notetaker" }] }]; });
afterEach(() => { cleanup(); document.body.innerHTML = ""; vi.clearAllMocks(); vi.useRealTimers(); });

describe("Library list + preview", () => {
  it("lists documents newest first with course, type and added date, and previews the first", async () => {
    setup();
    const row = await screen.findByTestId("library-doc-d1");
    expect(row.textContent).toContain("Recursion Workshop");
    expect(row.textContent).toContain("CS101");
    expect(row.textContent).toContain("Lecture Notes");
    expect(row.textContent).toContain("Nov 6");
    expect(row.textContent).toContain("PDF");
    expect(screen.getByTestId("library-doc-d2").textContent).toContain("PPTX");

    const preview = screen.getByTestId("library-preview");
    expect(within(preview).getByRole("heading", { name: "Recursion Workshop" })).toBeTruthy();
    expect(preview.textContent).toContain("CS101 · Intro to CS");
    expect(preview.textContent).toContain("Explore base cases");
    expect(preview.textContent).toContain("Linked Concepts");
    expect(preview.textContent).toContain("Recursion");
  });

  it("type chips count and filter", async () => {
    setup();
    await screen.findByTestId("library-doc-d1");
    expect(screen.getByTestId("library-type-all").textContent).toContain("3");
    fireEvent.click(screen.getByTestId("library-type-slides"));
    expect(screen.queryByTestId("library-doc-d1")).toBeNull();
    expect(screen.getByTestId("library-doc-d2")).toBeTruthy();
  });

  it("search matches concept names and says why", async () => {
    setup();
    await screen.findByTestId("library-doc-d1");
    fireEvent.change(screen.getByTestId("library-search"), { target: { value: "inverses" } });
    expect(screen.queryByTestId("library-doc-d1")).toBeNull();
    expect(screen.getByTestId("library-doc-d2").textContent).toContain("Linked concept: Inverses");
  });

  it("selecting a course hides foldered documents and shows the folder", async () => {
    setup({ d2: "f1" });
    await screen.findByTestId("library-doc-d1");
    fireEvent.click(screen.getByTestId("library-course-filter-c2"));
    expect(screen.getByTestId("library-folder-item-f1").textContent).toContain("1 document");
    expect(screen.queryByTestId("library-doc-d2")).toBeNull();
    expect(screen.getByTestId("library-doc-d3")).toBeTruthy();

    fireEvent.click(screen.getByTestId("library-folder-f1"));
    expect(screen.getByTestId("library-location-title").textContent).toContain("MATH210 / Midterm Prep");
    expect(screen.getByTestId("library-doc-d2")).toBeTruthy();
  });

  it("Open shows the reading view", async () => {
    setup();
    await screen.findByTestId("library-doc-d1");
    fireEvent.click(screen.getByTestId("library-open"));
    const reader = screen.getByTestId("library-reader");
    expect(reader.textContent).toContain("Linked Concepts (2)");
    expect(reader.textContent).toContain("Explore base cases and recursive calls.");
  });
});

describe("Library organisation", () => {
  it("adds a document to a folder from the menu, and Undo puts it back", async () => {
    setup();
    fireEvent.click(await screen.findByTestId("library-doc-d3"));
    fireEvent.click(screen.getByTestId("library-doc-menu"));
    fireEvent.click(screen.getByRole("menuitemradio", { name: /Midterm Prep/ }));
    await waitFor(() => expect(moveDocumentsToFolder).toHaveBeenCalledWith(["d3"], "f1"));
    expect((await screen.findByTestId("library-toast")).textContent).toContain("Moved “Problem Set 6” to MATH210 / Midterm Prep");

    fireEvent.click(screen.getByTestId("library-undo"));
    await waitFor(() => expect(moveDocumentsToFolder).toHaveBeenLastCalledWith(["d3"], null));
  });

  it("only offers folders from the document's own course", async () => {
    setup();
    fireEvent.click(await screen.findByTestId("library-doc-d1"));
    fireEvent.click(screen.getByTestId("library-doc-menu"));
    expect(screen.queryByRole("menuitemradio", { name: /Midterm Prep/ })).toBeNull();
  });

  it("delete waits for the undo window; Undo keeps the document", async () => {
    setup();
    await screen.findByTestId("library-doc-d1");
    vi.useFakeTimers();
    fireEvent.click(screen.getByTestId("library-doc-menu"));
    fireEvent.click(screen.getByTestId("library-doc-delete"));
    fireEvent.click(screen.getByTestId("library-doc-delete"));
    expect(screen.queryByTestId("library-doc-d1")).toBeNull();
    fireEvent.click(screen.getByTestId("library-undo"));
    expect(screen.getByTestId("library-doc-d1")).toBeTruthy();
    act(() => { vi.advanceTimersByTime(6000); });
    expect(deleteDocument).not.toHaveBeenCalled();

    fireEvent.click(screen.getByTestId("library-doc-menu"));
    fireEvent.click(screen.getByTestId("library-doc-delete"));
    fireEvent.click(screen.getByTestId("library-doc-delete"));
    await act(async () => { vi.advanceTimersByTime(5000); });
    expect(deleteDocument).toHaveBeenCalledWith("d1", "u1");
  });

  it("bulk select moves several documents", async () => {
    setup();
    await screen.findByTestId("library-doc-d2");
    fireEvent.click(screen.getByRole("button", { name: "Select Determinants" }));
    fireEvent.click(screen.getByRole("button", { name: "Select Problem Set 6" }));
    expect(screen.getByTestId("library-bulk").textContent).toContain("2 Selected");
    fireEvent.click(screen.getByTestId("library-bulk-move"));
    fireEvent.click(screen.getByTestId("library-bulk-folder-f1"));
    await waitFor(() => expect(moveDocumentsToFolder).toHaveBeenCalledWith(["d2", "d3"], "f1"));
  });

  it("renames from the preview title, keeping the server's name", async () => {
    vi.mocked(renameLibraryDocument).mockResolvedValue({ id: "d1", file_name: "Recursion Lab.pdf" });
    setup();
    await screen.findByTestId("library-doc-d1");
    fireEvent.doubleClick(within(screen.getByTestId("library-preview")).getByRole("heading", { level: 2 }));
    const input = screen.getByTestId("library-rename-input");
    fireEvent.change(input, { target: { value: "Recursion Lab" } });
    fireEvent.keyDown(input, { key: "Enter" });
    fireEvent.blur(input);
    await waitFor(() => expect(renameLibraryDocument).toHaveBeenCalledWith("d1", "Recursion Lab"));
    expect(screen.getByTestId("library-doc-d1").textContent).toContain("Recursion Lab");
  });
});

describe("Library + New", () => {
  it("New Folder appears inline in rename mode; an empty name falls back to the default", async () => {
    vi.mocked(createLibraryFolder).mockResolvedValue({ id: "f9", course_id: "c1", name: "New Folder", created_at: "" });
    setup();
    await screen.findByTestId("library-doc-d1");
    fireEvent.click(screen.getByTestId("library-course-filter-c1"));
    fireEvent.click(screen.getByTestId("library-new"));
    fireEvent.click(screen.getByTestId("library-new-folder"));
    const input = screen.getByTestId("library-new-name") as HTMLInputElement;
    expect(input.value).toBe("New Folder");
    fireEvent.change(input, { target: { value: "  " } });
    fireEvent.blur(input);
    await waitFor(() => expect(createLibraryFolder).toHaveBeenCalledWith("New Folder", "c1"));
    expect(await screen.findByTestId("library-folder-f9")).toBeTruthy();
  });

  it("New Document creates a note in the current course and opens it in the Notetaker", async () => {
    vi.mocked(createNote).mockResolvedValue({ id: "n1" } as never);
    setup();
    await screen.findByTestId("library-doc-d1");
    fireEvent.click(screen.getByTestId("library-course-filter-c2"));
    fireEvent.click(screen.getByTestId("library-new"));
    fireEvent.click(screen.getByTestId("library-new-doc"));
    const input = screen.getByTestId("library-new-name");
    fireEvent.change(input, { target: { value: "Exam questions" } });
    fireEvent.blur(input);
    await waitFor(() => expect(createNote).toHaveBeenCalledWith("u1", "c2", "Exam questions"));
    expect(push).toHaveBeenCalledWith("/notetaker?note=n1");
  });

  it("with the Notetaker hidden, New Document opens the upload dialog", async () => {
    navSections = [];
    setup();
    await screen.findByTestId("library-doc-d1");
    fireEvent.click(screen.getByTestId("library-new"));
    fireEvent.click(screen.getByTestId("library-new-doc"));
    expect(screen.getByTestId("upload-modal")).toBeTruthy();
    expect(createNote).not.toHaveBeenCalled();
  });
});

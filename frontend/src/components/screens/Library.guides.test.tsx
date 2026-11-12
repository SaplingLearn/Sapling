// @vitest-environment jsdom
/**
 * Library: study guides saved from the reader.
 *
 * They are a section of their own over the documents, each a link to its
 * reader. They follow the course filter and the search; the document counts
 * stay document counts; and a guides call that fails (Study hidden by its
 * flag 404s it) leaves the Library as it was.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";

vi.mock("@/context/UserContext", () => ({ useUser: () => ({ userId: "u1", userReady: true }) }));
vi.mock("@/lib/useIsMobile", () => ({ useIsMobile: () => false }));
vi.mock("../DocumentUploadModal", () => ({ DocumentUploadModal: () => null }));
vi.mock("@/lib/api", () => ({
  getDocuments: vi.fn(),
  deleteDocument: vi.fn(),
  getCourses: vi.fn(),
  scanDocumentConcepts: vi.fn(),
  scanCourseConcepts: vi.fn(),
}));
vi.mock("@/lib/studyGuide/api", () => ({ listGuides: vi.fn() }));

import { getCourses, getDocuments, type EnrolledCourse } from "@/lib/api";
import { listGuides } from "@/lib/studyGuide/api";
import type { GuideCard } from "@/lib/studyGuide/types";

import { Library } from "./Library";
import { ToastProvider } from "../ToastProvider";

const course = (id: string, code: string, name: string) =>
  ({ enrollment_id: `enr-${id}`, course_id: id, course_code: code, course_name: name, color: null }) as EnrolledCourse;

const doc = (id: string, name: string, course_id: string | null) => ({
  id, user_id: "u1", course_id, file_name: name, category: "reading" as const,
  summary: null, concept_notes: null, created_at: "2026-04-01T00:00:00Z", processed_at: null,
});

const guide = (over: Partial<GuideCard>) => ({
  id: "g1", title: "Loops and recursion", course_id: "c1", course_name: "Intro to CS",
  scope_label: "Midterm 2", saved_at: "2026-11-11T09:00:00Z", ...over,
}) as GuideCard;

const SAVED_CS = guide({});
const SAVED_MATH = guide({ id: "g2", title: "Limits", course_id: "c2", course_name: "Calculus" });
const UNSAVED = guide({ id: "g3", title: "Arrays cram sheet", saved_at: null });

const renderLibrary = () => render(<ToastProvider><Library /></ToastProvider>);

beforeEach(() => {
  vi.spyOn(console, "error").mockImplementation(() => {});
  vi.mocked(getCourses).mockResolvedValue({ courses: [course("c1", "CS101", "Intro to CS"), course("c2", "MA225", "Calculus")] });
  vi.mocked(getDocuments).mockResolvedValue({ documents: [doc("a", "alpha.pdf", "c1"), doc("b", "beta.pdf", null)] } as never);
  vi.mocked(listGuides).mockResolvedValue({ guides: [SAVED_CS, SAVED_MATH, UNSAVED] });
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.clearAllMocks();
});

describe("Library: saved study guides", () => {
  it("shows each saved guide with its title, class and kind, as a link to the reader", async () => {
    renderLibrary();
    const card = await screen.findByTestId("library-guide-g1");
    expect(vi.mocked(listGuides)).toHaveBeenCalledWith("u1");
    expect(card.tagName).toBe("A");
    expect(card).toHaveAttribute("href", "/study/guide/g1");
    expect(card).toHaveTextContent("Loops and recursion");
    expect(card).toHaveTextContent("Intro to CS");
    expect(card).toHaveTextContent("Study guide");
    expect(screen.getByTestId("library-guide-g2")).toHaveAttribute("href", "/study/guide/g2");
    // A guide that was not saved stays on the Study Guides home only.
    expect(screen.queryByTestId("library-guide-g3")).toBeNull();
    // The documents are still there beside them.
    expect(screen.getByTestId("library-doc-a")).toBeTruthy();
  });

  it("follows the course filter, and has nothing under Uncategorized", async () => {
    renderLibrary();
    await screen.findByTestId("library-guide-g1");
    fireEvent.click(screen.getByTestId("library-course-filter-c2"));
    expect(screen.queryByTestId("library-guide-g1")).toBeNull();
    expect(screen.getByTestId("library-guide-g2")).toBeTruthy();
    fireEvent.click(screen.getByTestId("library-course-filter-uncategorized"));
    expect(screen.queryByTestId("library-guide-g2")).toBeNull();
    expect(screen.getByTestId("library-doc-b")).toBeTruthy();
    fireEvent.click(screen.getByTestId("library-course-filter-all"));
    expect(screen.getByTestId("library-guide-g1")).toBeTruthy();
  });

  it("follows the search, by title or class", async () => {
    renderLibrary();
    await screen.findByTestId("library-guide-g1");
    fireEvent.change(screen.getByTestId("library-search"), { target: { value: "limits" } });
    expect(screen.queryByTestId("library-guide-g1")).toBeNull();
    expect(screen.getByTestId("library-guide-g2")).toBeTruthy();
    fireEvent.change(screen.getByTestId("library-search"), { target: { value: "intro to cs" } });
    expect(screen.getByTestId("library-guide-g1")).toBeTruthy();
    expect(screen.queryByTestId("library-guide-g2")).toBeNull();
  });

  it("shows under a document category only for all and study guide", async () => {
    renderLibrary();
    await screen.findByTestId("library-guide-g1");
    fireEvent.click(screen.getByRole("button", { name: "reading" }));
    expect(screen.queryByTestId("library-guide-g1")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "study guide" }));
    expect(screen.getByTestId("library-guide-g1")).toBeTruthy();
  });

  it("leaves the document counts as document counts", async () => {
    renderLibrary();
    await screen.findByTestId("library-guide-g1");
    expect(screen.getByText(/^2 documents/)).toBeTruthy();
    expect(within(screen.getByTestId("library-course-filter-all")).getByText("2")).toBeTruthy();
    expect(within(screen.getByTestId("library-course-filter-c1")).getByText("1")).toBeTruthy();
    expect(within(screen.getByTestId("library-course-filter-c2")).getByText("0")).toBeTruthy();
  });

  it("a library with saved guides and no documents is not called quiet", async () => {
    vi.mocked(getDocuments).mockResolvedValue({ documents: [] } as never);
    renderLibrary();
    await screen.findByTestId("library-guide-g1");
    expect(screen.queryByText(/Your library is quiet/i)).toBeNull();
  });

  it("a failed guides call means no guides, not a broken Library", async () => {
    vi.mocked(listGuides).mockRejectedValue(new Error("404"));
    renderLibrary();
    expect(await screen.findByTestId("library-doc-a")).toBeTruthy();
    expect(screen.queryByTestId("library-load-error")).toBeNull();
    expect(screen.queryByText("Study guides")).toBeNull();
  });
});

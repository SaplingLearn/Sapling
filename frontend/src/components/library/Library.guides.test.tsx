// @vitest-environment jsdom
/**
 * Library: study guides saved from the reader.
 *
 * They are a section of their own over the documents, each a link to its
 * reader. They follow the course scope and the search; the document counts
 * stay document counts. They are read on their own, so the documents never
 * wait on them; a guides call that fails says so in one line; and nothing is
 * asked for while Study is hidden by its flag (the server 404s it then).
 *
 * Ported from the pre-redesign Library (#769 era) onto the v2 controls: the
 * course RAIL is now the course SWITCHER, and the category PILLS are the Type
 * menu, so the same behaviours are driven through the new affordances.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen, within } from "@testing-library/react";

vi.mock("@/context/UserContext", () => ({ useUser: () => ({ userId: "u1", userReady: true }) }));
vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn() }) }));
vi.mock("@/lib/api", () => ({
  getDocuments: vi.fn(),
  getCourses: vi.fn(),
  getFolders: vi.fn(async () => ({ folders: [] })),
  getTrashedDocuments: vi.fn(async () => ({ documents: [] })),
  deleteDocument: vi.fn(),
  restoreDocument: vi.fn(),
  purgeDocument: vi.fn(),
  updateDocument: vi.fn(),
  createBlankDocument: vi.fn(),
  createFolder: vi.fn(),
  renameFolder: vi.fn(),
  deleteFolder: vi.fn(),
  scanDocumentConcepts: vi.fn(),
  scanCourseConcepts: vi.fn(),
  uploadDocumentStream: vi.fn(),
}));
vi.mock("@/lib/studyGuide/api", () => ({ listGuides: vi.fn() }));
const flagState = vi.hoisted(() => ({ hideStudy: false }));
vi.mock("@/context/FlagsContext", () => ({
  useFlagMap: () => ({ flags: flagState.hideStudy ? { hide_study: "on" } : {}, ready: true }),
}));

import { getCourses, getDocuments, type EnrolledCourse } from "@/lib/api";
import { listGuides } from "@/lib/studyGuide/api";
import type { GuideCard } from "@/lib/studyGuide/types";

import { Library } from "./Library";
import { ToastProvider } from "../ToastProvider";

const course = (id: string, code: string, name: string) =>
  ({
    enrollment_id: `enr-${id}`, course_id: id, course_code: code,
    course_name: name, color: null,
  }) as EnrolledCourse;

const doc = (id: string, name: string, course_id: string | null) => ({
  id, user_id: "u1", course_id, file_name: name, category: "reading" as const,
  summary: null, concept_notes: null, created_at: "2026-04-01T00:00:00Z", processed_at: null,
});

const guide = (over: Partial<GuideCard>) => ({
  id: "g1", title: "Loops and recursion", course_id: "c1", course_name: "Intro to CS",
  course_code: "CS101", scope_label: "Midterm 2", saved_at: "2026-11-11T09:00:00Z", ...over,
}) as GuideCard;

const SAVED_CS = guide({});
const SAVED_MATH = guide({
  id: "g2", title: "Limits", course_id: "c2", course_name: "Calculus", course_code: "MA225",
});
const UNSAVED = guide({ id: "g3", title: "Arrays cram sheet", saved_at: null });

const renderLibrary = () => render(<ToastProvider><Library /></ToastProvider>);

/** Open the course switcher and pick a scope by its label. */
function pickScope(label: string) {
  fireEvent.click(screen.getByTestId("library-course-switcher"));
  fireEvent.click(screen.getByRole("option", { name: new RegExp(label) }));
}

/** Open the Type menu and pick one. */
function pickType(label: string) {
  fireEvent.click(screen.getByRole("button", { name: /^Type/ }));
  fireEvent.click(screen.getByRole("menuitemradio", { name: new RegExp(label) }));
}

beforeEach(() => {
  vi.spyOn(console, "error").mockImplementation(() => {});
  vi.mocked(getCourses).mockResolvedValue({
    courses: [course("c1", "CS101", "Intro to CS"), course("c2", "MA225", "Calculus")],
  });
  vi.mocked(getDocuments).mockResolvedValue({
    documents: [doc("a", "alpha.pdf", "c1"), doc("b", "beta.pdf", null)],
  } as never);
  vi.mocked(listGuides).mockResolvedValue({ guides: [SAVED_CS, SAVED_MATH, UNSAVED] });
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.clearAllMocks();
  flagState.hideStudy = false;
});

describe("Library: saved study guides", () => {
  it("shows each saved guide as a link to its reader, beside the documents", async () => {
    renderLibrary();
    const card = await screen.findByTestId("library-guide-g1");
    expect(vi.mocked(listGuides)).toHaveBeenCalledWith("u1");
    expect(card.tagName).toBe("A");
    expect(card).toHaveAttribute("href", "/study/guide/g1");
    expect(within(card).getByRole("heading", { level: 3, name: "Loops and recursion" })).toBeTruthy();
    expect(screen.getByTestId("library-guide-g2")).toHaveAttribute("href", "/study/guide/g2");
    // A guide that was not saved stays on the Study Guides home only.
    expect(screen.queryByTestId("library-guide-g3")).toBeNull();
    expect(screen.getByTestId("library-doc-a")).toBeTruthy();
  });

  it("follows the course scope, and has nothing under No Course", async () => {
    renderLibrary();
    await screen.findByTestId("library-guide-g1");

    pickScope("MA225");
    expect(screen.queryByTestId("library-guide-g1")).toBeNull();
    expect(screen.getByTestId("library-guide-g2")).toBeTruthy();

    pickScope("No Course");
    expect(screen.queryByTestId("library-guide-g2")).toBeNull();
    expect(screen.getByTestId("library-doc-b")).toBeTruthy();

    pickScope("All Documents");
    expect(screen.getByTestId("library-guide-g1")).toBeTruthy();
  });

  it("follows the search, by title or class (name or code)", async () => {
    renderLibrary();
    await screen.findByTestId("library-guide-g1");
    const search = screen.getByTestId("library-search");

    fireEvent.change(search, { target: { value: "limits" } });
    expect(screen.queryByTestId("library-guide-g1")).toBeNull();
    expect(screen.getByTestId("library-guide-g2")).toBeTruthy();

    fireEvent.change(search, { target: { value: "intro to cs" } });
    expect(screen.getByTestId("library-guide-g1")).toBeTruthy();
    expect(screen.queryByTestId("library-guide-g2")).toBeNull();

    fireEvent.change(search, { target: { value: "ma225" } });
    expect(screen.queryByTestId("library-guide-g1")).toBeNull();
    expect(screen.getByTestId("library-guide-g2")).toBeTruthy();
  });

  it("shows under a document type only for All Types and Study Guide", async () => {
    renderLibrary();
    await screen.findByTestId("library-guide-g1");

    pickType("Reading");
    expect(screen.queryByTestId("library-guide-g1")).toBeNull();

    pickType("Study Guide");
    expect(screen.getByTestId("library-guide-g1")).toBeTruthy();
  });

  it("leaves the scope counts as document counts", async () => {
    renderLibrary();
    await screen.findByTestId("library-guide-g1");
    fireEvent.click(screen.getByTestId("library-course-switcher"));
    expect(screen.getByRole("option", { name: /All Documents/ }).textContent)
      .toContain("2 documents");
    expect(screen.getByRole("option", { name: /CS101/ }).textContent).toContain("1 document");
    expect(screen.getByRole("option", { name: /MA225/ }).textContent).toContain("0 documents");
  });

  it("a library with saved guides and no documents is not called empty", async () => {
    vi.mocked(getDocuments).mockResolvedValue({ documents: [] } as never);
    renderLibrary();
    await screen.findByTestId("library-guide-g1");
    expect(screen.queryByTestId("library-empty")).toBeNull();
  });

  it("shows the documents without waiting for the guides", async () => {
    let answer!: (value: { guides: GuideCard[] }) => void;
    vi.mocked(listGuides).mockReturnValue(new Promise(resolve => { answer = resolve; }));
    renderLibrary();
    expect(await screen.findByTestId("library-doc-a")).toBeTruthy();
    expect(screen.queryByTestId("library-guide-g1")).toBeNull();

    await act(async () => answer({ guides: [SAVED_CS] }));
    expect(screen.getByTestId("library-guide-g1")).toBeTruthy();
  });

  it("is not called empty while the guides are still on their way", async () => {
    vi.mocked(getDocuments).mockResolvedValue({ documents: [] } as never);
    vi.mocked(listGuides).mockReturnValue(new Promise(() => {}));
    renderLibrary();
    await screen.findByTestId("library-search");
    await act(async () => {});
    expect(screen.queryByTestId("library-empty")).toBeNull();
  });

  it("a failed guides call says so in one line with Retry, and the documents still show", async () => {
    vi.mocked(listGuides).mockRejectedValueOnce(new Error("500"));
    renderLibrary();
    expect(await screen.findByTestId("library-guides-error")).toHaveAttribute("role", "alert");
    expect(screen.getByTestId("library-doc-a")).toBeTruthy();
    // The documents loaded: the Library itself did not fail.
    expect(screen.queryByTestId("library-load-error")).toBeNull();

    fireEvent.click(screen.getByTestId("library-guides-retry"));
    expect(await screen.findByTestId("library-guide-g1")).toBeTruthy();
    expect(screen.queryByTestId("library-guides-error")).toBeNull();
    expect(vi.mocked(listGuides)).toHaveBeenCalledTimes(2);
  });

  it("a failed guides call with no documents is not called empty", async () => {
    vi.mocked(getDocuments).mockResolvedValue({ documents: [] } as never);
    vi.mocked(listGuides).mockRejectedValue(new Error("500"));
    renderLibrary();
    await screen.findByTestId("library-guides-error");
    expect(screen.queryByTestId("library-empty")).toBeNull();
  });

  it("asks for no guides while Study is hidden, and an empty Library says so", async () => {
    flagState.hideStudy = true;
    vi.mocked(getDocuments).mockResolvedValue({ documents: [] } as never);
    renderLibrary();
    expect(await screen.findByTestId("library-empty")).toBeTruthy();
    expect(vi.mocked(listGuides)).not.toHaveBeenCalled();
    expect(screen.queryByTestId("library-guides-error")).toBeNull();
  });
});

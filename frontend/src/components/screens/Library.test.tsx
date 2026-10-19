// @vitest-environment jsdom
/**
 * Library (redesign prompt 03) behaviour tests: the visible fetch failure +
 * Retry the baseline lacked, refresh errors that keep prior data, the empty
 * vs no-match states, combined filters in both views, duplicate-enrollment
 * dedupe, the sage selected row, scans that report the response's real
 * counts, deliberate delete with recovery, offline/no-course explanations,
 * and the phone detail as a labelled modal sheet (Escape, focus return,
 * scroll lock).
 */
import React from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { __resetScrollLocksForTests } from "@/lib/useScrollLock";

const viewport = vi.hoisted(() => ({ phone: false }));
vi.mock("@/lib/useIsMobile", () => ({ useIsMobile: () => viewport.phone, MOBILE_BREAKPOINT: 768 }));

vi.mock("@/context/UserContext", () => ({
  useUser: () => ({ userId: "u1", userReady: true }),
}));

vi.mock("next/dynamic", () => ({
  default: () => function MarkdownStub({ children }: { children: React.ReactNode }) {
    return <div data-testid="markdown">{children}</div>;
  },
}));

vi.mock("next/link", () => ({
  default: ({ href, children, ...rest }: { href: string; children: React.ReactNode }) => (
    <a href={href} {...rest}>{children}</a>
  ),
}));

vi.mock("@/lib/api", () => ({
  getDocuments: vi.fn(),
  getCourses: vi.fn(),
  deleteDocument: vi.fn(),
  scanDocumentConcepts: vi.fn(),
  scanCourseConcepts: vi.fn(),
  uploadDocumentStream: vi.fn(),
  updateDocumentCategory: vi.fn(),
  addCourse: vi.fn(),
  deleteCourse: vi.fn(),
  updateCourseColor: vi.fn(),
  onboardingCoursesSearch: vi.fn(async () => ({ courses: [] })),
}));

import { Library, filterDocuments, fileTypeOf, dedupeCourses, scanResultText, NO_FILTERS } from "./Library";
import { ToastProvider } from "../ToastProvider";
import {
  getDocuments,
  getCourses,
  deleteDocument,
  scanDocumentConcepts,
  scanCourseConcepts,
  type EnrolledCourse,
} from "@/lib/api";
import type { Document as Doc } from "@/lib/types";

const mGetDocuments = vi.mocked(getDocuments);
const mGetCourses = vi.mocked(getCourses);
const mDelete = vi.mocked(deleteDocument);
const mScanDoc = vi.mocked(scanDocumentConcepts);
const mScanCourse = vi.mocked(scanCourseConcepts);

const course = (id: string, code: string, enrollment: string, term = "Fall 2026"): EnrolledCourse => ({
  enrollment_id: enrollment,
  course_id: id,
  course_code: code,
  course_name: `${code} name`,
  school: "X",
  department: "D",
  color: null,
  nickname: null,
  node_count: 0,
  enrolled_at: "2026-01-01",
  term,
});

// c-1 is enrolled twice (two offerings) — the filter must list it once.
const COURSES = [course("c-1", "CS101", "e1"), course("c-1", "CS101", "e2", "Spring 2027"), course("c-2", "MATH200", "e3")];

const doc = (over: Partial<Doc> & Pick<Doc, "id" | "file_name">): Doc => ({
  user_id: "u1",
  course_id: "c-1",
  category: "lecture_notes",
  summary: null,
  concept_notes: null,
  created_at: "2026-10-17T12:00:00Z",
  processed_at: "2026-10-17T12:01:00Z",
  ...over,
});

const DOCS: Doc[] = [
  doc({
    id: "d1",
    file_name: "Lecture 01 Python essentials.pdf",
    summary: "Variables, loops and functions.",
    concept_notes: [
      { name: "Variables", description: "Named values." },
      { name: "Loops", description: "Repeat a block." },
    ],
  }),
  doc({ id: "d2", file_name: "Recursion workshop.pptx", category: "slides", summary: "Base cases and recursive calls." }),
  doc({ id: "d3", file_name: "Limits.docx", category: "reading", course_id: "c-2", summary: "Epsilon and delta." }),
  doc({ id: "d4", file_name: "loose-notes.pdf", category: "other", course_id: null }),
];

function renderLibrary() {
  return render(
    <ToastProvider>
      <Library />
    </ToastProvider>,
  );
}

function setOnline(value: boolean) {
  Object.defineProperty(window.navigator, "onLine", { configurable: true, get: () => value });
}

beforeEach(() => {
  viewport.phone = false;
  setOnline(true);
  mGetDocuments.mockReset().mockResolvedValue({ documents: DOCS });
  mGetCourses.mockReset().mockResolvedValue({ courses: COURSES });
  mDelete.mockReset();
  mScanDoc.mockReset();
  mScanCourse.mockReset();
});

afterEach(() => {
  cleanup();
  document.body.innerHTML = "";
  __resetScrollLocksForTests();
  document.body.style.removeProperty("overflow-y");
  document.body.style.removeProperty("overflow-x");
});

const rowIds = () =>
  screen.queryAllByTestId(/^library-doc-/).map((el) => el.getAttribute("data-testid")!.replace("library-doc-", ""));

describe("Library data states", () => {
  it("shows a visible load failure with Retry instead of the empty library, and recovers", async () => {
    mGetDocuments.mockRejectedValueOnce(new Error("HTTP 503"));
    const user = userEvent.setup();
    renderLibrary();

    const alert = await screen.findByTestId("library-load-error");
    expect(alert).toHaveAttribute("role", "alert");
    expect(alert).toHaveTextContent(/couldn't load your library/i);
    expect(alert).toHaveTextContent("HTTP 503");
    expect(screen.queryByTestId("library-empty")).toBeNull();
    expect(screen.getByTestId("library-upload")).toBeDisabled();

    await user.click(screen.getByTestId("library-load-error-retry"));
    await waitFor(() => expect(rowIds()).toEqual(["d1", "d2", "d3", "d4"]));
    expect(mGetDocuments).toHaveBeenCalledTimes(2);
    expect(screen.queryByTestId("library-load-error")).toBeNull();
  });

  it("renders a loading skeleton until the first fetch settles", async () => {
    let resolve!: (v: { documents: Doc[] }) => void;
    mGetDocuments.mockReturnValueOnce(new Promise((r) => { resolve = r; }));
    renderLibrary();
    expect(screen.getByTestId("library-loading")).toHaveAttribute("aria-busy", "true");
    resolve({ documents: DOCS });
    await waitFor(() => expect(screen.queryByTestId("library-loading")).toBeNull());
  });

  it("keeps the loaded materials when a refresh fails, and says so", async () => {
    const user = userEvent.setup();
    renderLibrary();
    await waitFor(() => expect(rowIds()).toHaveLength(4));

    mGetDocuments.mockRejectedValueOnce(new Error("network down"));
    await user.click(screen.getByTestId("library-refresh"));

    const err = await screen.findByTestId("library-refresh-error");
    expect(err).toHaveTextContent(/couldn't refresh/i);
    expect(err).toHaveTextContent("network down");
    expect(rowIds()).toHaveLength(4);
    expect(screen.queryByTestId("library-load-error")).toBeNull();
  });

  it("separates a genuinely empty library from filters that match nothing", async () => {
    mGetDocuments.mockResolvedValueOnce({ documents: [] });
    renderLibrary();
    expect(await screen.findByTestId("library-empty")).toHaveTextContent(/library is quiet/i);
    expect(screen.queryByTestId("library-no-matches")).toBeNull();
    cleanup();

    const user = userEvent.setup();
    renderLibrary();
    await waitFor(() => expect(rowIds()).toHaveLength(4));
    await user.type(screen.getByTestId("library-search"), "zzz-nothing");
    expect(screen.getByTestId("library-no-matches")).toBeInTheDocument();
    expect(screen.queryByTestId("library-empty")).toBeNull();
    await user.click(screen.getByTestId("library-clear-filters"));
    expect(rowIds()).toHaveLength(4);
    expect(screen.getByTestId("library-search")).toHaveValue("");
  });

  it("explains offline and disables network actions without re-sending anything on reconnect", async () => {
    renderLibrary();
    await waitFor(() => expect(rowIds()).toHaveLength(4));
    expect(screen.getByTestId("library-upload")).toBeEnabled();

    setOnline(false);
    fireEvent(window, new Event("offline"));
    expect(await screen.findByTestId("library-offline")).toHaveTextContent(/offline/i);
    expect(screen.getByTestId("library-upload")).toBeDisabled();
    expect(screen.getByTestId("library-upload-hint")).toHaveTextContent(/offline/i);
    expect(rowIds()).toHaveLength(4);

    const calls = mGetDocuments.mock.calls.length;
    setOnline(true);
    fireEvent(window, new Event("online"));
    await waitFor(() => expect(screen.queryByTestId("library-offline")).toBeNull());
    expect(mGetDocuments.mock.calls.length).toBe(calls);
  });

  it("with no course, explains the disabled upload and offers course setup", async () => {
    mGetDocuments.mockResolvedValueOnce({ documents: [] });
    mGetCourses.mockResolvedValueOnce({ courses: [] });
    renderLibrary();
    const upload = await screen.findByTestId("library-upload");
    await waitFor(() => expect(screen.getByTestId("library-upload-hint")).toHaveTextContent(/add a course first/i));
    expect(upload).toBeDisabled();
    expect(upload).toHaveAttribute("aria-describedby", "library-upload-hint");
    expect(screen.getByTestId("library-add-course")).toBeEnabled();
    expect(screen.getByTestId("library-empty-add-course")).toBeEnabled();
  });
});

describe("Library filters", () => {
  afterEach(() => window.history.replaceState(null, "", "/"));

  it("pre-selects ?course= once the courses load (Clov's Materials link), and the filter stays editable", async () => {
    window.history.replaceState(null, "", "/library?course=c-2");
    const user = userEvent.setup();
    renderLibrary();
    const select = screen.getByLabelText("Course", { selector: "select" });
    await waitFor(() => expect(select).toHaveValue("c-2"));
    expect(rowIds()).toEqual(["d3"]);
    // The course scan follows the pre-selected course, as for a manual pick.
    expect(screen.getByTestId("library-course-scan")).toHaveTextContent("MATH200");

    await user.selectOptions(select, "all");
    expect(rowIds()).toEqual(["d1", "d2", "d3", "d4"]);
  });

  it("ignores a ?course= the student is not enrolled in", async () => {
    window.history.replaceState(null, "", "/library?course=not-mine");
    renderLibrary();
    await waitFor(() => expect(rowIds()).toHaveLength(4));
    expect(screen.getByLabelText("Course", { selector: "select" })).toHaveValue("all");
  });

  it("dedupes repeated enrollments into one course option", async () => {
    renderLibrary();
    await waitFor(() => expect(rowIds()).toHaveLength(4));
    const select = screen.getByLabelText("Course", { selector: "select" });
    const labels = within(select).getAllByRole("option").map((o) => o.textContent);
    expect(labels).toEqual(["All courses (4)", "Uncategorized (1)", "CS101 (2)", "MATH200 (1)"]);
  });

  it("combines search (name or summary), course, category and file type identically in list and grid", async () => {
    const user = userEvent.setup();
    renderLibrary();
    await waitFor(() => expect(rowIds()).toHaveLength(4));

    // Summary text matches too, case-insensitively.
    await user.type(screen.getByTestId("library-search"), "RECURSIVE");
    expect(rowIds()).toEqual(["d2"]);
    await user.click(screen.getByTestId("library-view-grid"));
    expect(screen.getByTestId("library-grid")).toBeInTheDocument();
    expect(rowIds()).toEqual(["d2"]);
    await user.clear(screen.getByTestId("library-search"));

    await user.selectOptions(screen.getByTestId("library-course-filter"), "c-1");
    expect(rowIds()).toEqual(["d1", "d2"]);
    await user.selectOptions(screen.getByTestId("library-category-filter"), "slides");
    expect(rowIds()).toEqual(["d2"]);
    await user.click(screen.getByTestId("library-view-list"));
    expect(rowIds()).toEqual(["d2"]);

    await user.selectOptions(screen.getByTestId("library-category-filter"), "all");
    await user.selectOptions(screen.getByTestId("library-course-filter"), "uncategorized");
    expect(rowIds()).toEqual(["d4"]);

    await user.selectOptions(screen.getByTestId("library-course-filter"), "all");
    await user.selectOptions(screen.getByTestId("library-filetype-filter"), "pdf");
    expect(rowIds()).toEqual(["d1", "d4"]);
    expect(screen.getByTestId("library-results-count")).toHaveTextContent("Showing 2 of 4 materials");
  });

  it("pure helpers: file type from the name only, dedupe, filter", () => {
    expect(fileTypeOf("a.PDF")).toBe("pdf");
    expect(fileTypeOf("noext")).toBe("other");
    expect(fileTypeOf(".hidden")).toBe("other");
    expect(dedupeCourses(COURSES).map((c) => c.course_id)).toEqual(["c-1", "c-2"]);
    expect(filterDocuments(DOCS, { ...NO_FILTERS, query: "epsilon" }).map((d) => d.id)).toEqual(["d3"]);
  });
});

describe("Library rows and detail (desktop rail)", () => {
  it("draws the paper icon on every row and marks the selected row with sage + aria-pressed", async () => {
    const user = userEvent.setup();
    renderLibrary();
    await waitFor(() => expect(rowIds()).toHaveLength(4));
    for (const id of rowIds()) {
      expect(screen.getByTestId(`library-doc-${id}`).querySelector('[data-icon="paper"]')).not.toBeNull();
    }
    const row = screen.getByTestId("library-doc-d1");
    expect(row).toHaveAttribute("aria-pressed", "false");
    await user.click(row);
    expect(row).toHaveAttribute("aria-pressed", "true");
    expect(row).toHaveAttribute("data-selected", "true");

    const rail = screen.getByRole("complementary", { name: "Selected material" });
    expect(within(rail).getByRole("heading", { level: 2, name: "Lecture 01 Python essentials.pdf" })).toBeInTheDocument();
    expect(within(rail).getByText("Variables, loops and functions.")).toBeInTheDocument();
    expect(screen.queryByRole("dialog")).toBeNull();

    // Expandable concept notes.
    await user.click(screen.getByTestId("library-concept-toggle-0"));
    expect(screen.getByTestId("library-concept-toggle-0")).toHaveAttribute("aria-expanded", "true");
    expect(within(rail).getByText("Named values.")).toBeInTheDocument();
    await user.click(screen.getByTestId("library-concepts-toggle-all"));
    expect(within(rail).getByText("Repeat a block.")).toBeInTheDocument();

    // Ask Clov uses the supported course deep link, not a document attachment.
    expect(screen.getByTestId("library-detail-ask-clov")).toHaveAttribute("href", "/learn?course=c-1");

    await user.click(screen.getByTestId("library-detail-close"));
    expect(row).toHaveAttribute("aria-pressed", "false");
    expect(screen.getByTestId("library-detail-empty")).toBeInTheDocument();
  });

  it("reports the document scan's real counts, and retries a failed scan", async () => {
    mScanDoc.mockRejectedValueOnce(new Error("HTTP 500")).mockResolvedValueOnce({ concepts: [], added: 0, existing: 3 });
    const user = userEvent.setup();
    renderLibrary();
    await waitFor(() => expect(rowIds()).toHaveLength(4));
    await user.click(screen.getByTestId("library-doc-d1"));
    await user.click(screen.getByTestId("library-detail-scan"));
    const status = await screen.findByTestId("library-detail-scan-status");
    await waitFor(() => expect(status).toHaveTextContent(/scan failed: HTTP 500/i));
    await user.click(screen.getByTestId("library-detail-scan-status-retry"));
    await waitFor(() =>
      expect(screen.getByTestId("library-detail-scan-status")).toHaveTextContent(
        "No new concepts: CS101's graph already covers the 3 concepts found.",
      ),
    );
    expect(mScanDoc).toHaveBeenCalledWith("d1", "u1");
  });

  it("offers the course scan only for a specific course and shows its counts", async () => {
    mScanCourse.mockResolvedValueOnce({ concepts: ["a", "b"], added: 2, existing: 5 });
    const user = userEvent.setup();
    renderLibrary();
    await waitFor(() => expect(rowIds()).toHaveLength(4));
    expect(screen.queryByTestId("library-course-scan")).toBeNull();
    await user.selectOptions(screen.getByTestId("library-course-filter"), "uncategorized");
    expect(screen.queryByTestId("library-course-scan")).toBeNull();
    await user.selectOptions(screen.getByTestId("library-course-filter"), "c-1");
    await user.click(screen.getByTestId("library-course-scan"));
    await waitFor(() =>
      expect(screen.getByTestId("library-course-scan-status")).toHaveTextContent(
        "Added 2 concepts to CS101's knowledge graph; 5 were already there.",
      ),
    );
    expect(mScanCourse).toHaveBeenCalledWith("c-1", "u1");
  });

  it("deletes only after a second click; a failed delete keeps the row and offers recovery", async () => {
    mDelete.mockRejectedValueOnce(new Error("HTTP 502")).mockResolvedValueOnce({ deleted: true });
    const user = userEvent.setup();
    renderLibrary();
    await waitFor(() => expect(rowIds()).toHaveLength(4));
    await user.click(screen.getByTestId("library-doc-d2"));

    const del = screen.getByTestId("library-detail-delete");
    await user.click(del);
    expect(mDelete).not.toHaveBeenCalled();
    expect(del).toHaveTextContent(/click again/i);
    await user.click(del);
    const err = await screen.findByTestId("library-detail-delete-error");
    expect(err).toHaveTextContent(/still in your library/i);
    expect(rowIds()).toContain("d2");

    mGetDocuments.mockResolvedValueOnce({ documents: DOCS.filter((d) => d.id !== "d2") });
    await user.click(screen.getByTestId("library-detail-delete-error-retry"));
    await waitFor(() => expect(rowIds()).toEqual(["d1", "d3", "d4"]));
    expect(mDelete).toHaveBeenLastCalledWith("d2", "u1");
    expect(screen.getByTestId("library-detail-empty")).toBeInTheDocument();
  });
});

describe("Library phone detail sheet", () => {
  it("opens a labelled modal sheet; Escape closes it, restores focus and releases the scroll lock", async () => {
    viewport.phone = true;
    const user = userEvent.setup();
    renderLibrary();
    await waitFor(() => expect(rowIds()).toHaveLength(4));
    expect(screen.queryByRole("complementary")).toBeNull();

    const row = screen.getByTestId("library-doc-d2");
    expect(row).toHaveAttribute("aria-haspopup", "dialog");
    row.focus();
    await user.keyboard("{Enter}");

    const sheet = await screen.findByRole("dialog", { name: "Recursion workshop.pptx" });
    expect(sheet).toHaveAttribute("aria-modal", "true");
    expect(sheet).toHaveClass("sheet--bottom");
    expect(within(sheet).getByText("Base cases and recursive calls.")).toBeInTheDocument();
    expect(within(sheet).getByRole("button", { name: "Close" })).toBeInTheDocument();
    expect(document.body.style.getPropertyValue("overflow-y")).toBe("hidden");
    await waitFor(() => expect(sheet.contains(document.activeElement)).toBe(true));

    fireEvent.keyDown(sheet, { key: "Escape" });
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(document.activeElement).toBe(row);
    expect(document.body.style.getPropertyValue("overflow-y")).toBe("");
    expect(row).toHaveAttribute("aria-pressed", "false");
  });

  it("closes from the sheet's Close button", async () => {
    viewport.phone = true;
    const user = userEvent.setup();
    renderLibrary();
    await waitFor(() => expect(rowIds()).toHaveLength(4));
    await user.click(screen.getByTestId("library-doc-d1"));
    await screen.findByRole("dialog", { name: "Lecture 01 Python essentials.pdf" });
    await user.click(screen.getByTestId("library-detail-close"));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  });
});

describe("scanResultText", () => {
  it("only reports counts, never mastery", () => {
    expect(scanResultText({ added: 1, existing: 0 }, "CS101")).toBe("Added 1 concept to CS101's knowledge graph.");
    expect(scanResultText({ added: 0, existing: 0 }, "CS101")).toMatch(/nothing to add/i);
    for (const t of [scanResultText({ added: 3, existing: 1 }, "X"), scanResultText({ added: 0, existing: 2 }, "X")]) {
      expect(t).not.toMatch(/master|learned|\bknows?\b/i);
    }
  });
});

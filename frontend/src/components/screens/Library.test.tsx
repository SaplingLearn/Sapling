// @vitest-environment jsdom
import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, cleanup } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import React from "react";

vi.mock("@/context/UserContext", () => ({
  useUser: () => ({ userId: "u1", userReady: true }),
}));

// Stable spies at module scope (not a fresh object per call) — matches
// SummaryEditor.test.tsx's convention, so a toast-dependent useCallback
// (e.g. runCourseScan) doesn't get a fresh dependency identity every
// render and risk a re-render loop.
const toastSpies = { success: vi.fn(), error: vi.fn(), info: vi.fn(), warn: vi.fn(), show: vi.fn(), dismiss: vi.fn() };
vi.mock("../ToastProvider", () => ({
  useToast: () => toastSpies,
}));

const mockGetDocuments = vi.fn();
vi.mock("@/lib/api", () => ({
  getDocuments: (...args: unknown[]) => mockGetDocuments(...args),
  getCourses: vi.fn().mockResolvedValue({ courses: [] }),
  deleteDocument: vi.fn(),
  scanDocumentConcepts: vi.fn(),
  scanCourseConcepts: vi.fn(),
}));

import { Library } from "./Library";

afterEach(cleanup);

describe("Library — summary doc link", () => {
  it("shows an Open summary link when the document has a summary doc, and renders the preview text", async () => {
    mockGetDocuments.mockResolvedValue({
      documents: [{
        id: "d1", user_id: "u1", course_id: null, file_name: "Lecture 4.pdf",
        category: "lecture_notes",
        summary_doc_id: "sd1", summary_preview: "Mitosis overview.", summary_source_count: 1,
        concept_notes: null, created_at: "2026-01-01T00:00:00Z", processed_at: null,
      }],
    });

    render(<Library />);
    await userEvent.click(await screen.findByTestId("library-doc-d1"));

    const link = await screen.findByRole("link", { name: "Open summary" });
    expect(link).toHaveAttribute("href", "/library/summaries/sd1");
    // The underlying grid card (behind the drawer) also renders the same
    // preview text, so there are two matches in the DOM once the drawer is
    // open — a bare getAllByText(...).length > 0 would pass even if the
    // drawer itself rendered no preview at all (the grid card alone already
    // satisfies it). Scope to the drawer's own summary block instead, by
    // walking up from the link to its wrapper div (the one rendered by
    // {doc.summary_doc_id && (<div>...<Link>Open summary</Link></div>)}),
    // which is the one place that actually proves the drawer shows it.
    expect(link.closest("div")).toHaveTextContent("Mitosis overview.");
  });
});

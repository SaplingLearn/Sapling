// @vitest-environment jsdom
import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, cleanup } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import React from "react";

vi.mock("@/context/UserContext", () => ({
  useUser: () => ({ userId: "u1", userReady: true }),
}));

vi.mock("../ToastProvider", () => ({
  useToast: () => ({ success: vi.fn(), error: vi.fn(), info: vi.fn() }),
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
    // The underlying grid card (behind the modal overlay) also renders the
    // same preview text, so there are two matches in the DOM — assert at
    // least one rather than a single unique match.
    expect(screen.getAllByText("Mitosis overview.").length).toBeGreaterThan(0);
  });
});

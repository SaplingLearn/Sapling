// @vitest-environment jsdom
/**
 * Library — load-error state and per-document concept scan (#769).
 *
 *   1. A failed load is not an empty library: it renders an error state with
 *      a retry, never "Your library is quiet".
 *   2. The detail panel is reused when the selected document changes in place
 *      (reachable by keyboard behind the overlay), so a scan started on doc A
 *      must not mark doc B "done".
 */

import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, cleanup, act, fireEvent } from "@testing-library/react";

vi.mock("@/context/UserContext", () => ({
  useUser: () => ({ userId: "u1", userReady: true }),
}));

vi.mock("@/lib/useIsMobile", () => ({
  useIsMobile: () => false,
}));

vi.mock("../DocumentUploadModal", () => ({
  DocumentUploadModal: () => null,
}));

vi.mock("@/lib/api", () => ({
  getDocuments: vi.fn(),
  deleteDocument: vi.fn(),
  getCourses: vi.fn(async () => ({ courses: [] })),
  scanDocumentConcepts: vi.fn(),
  scanCourseConcepts: vi.fn(),
}));

import { Library } from "./Library";
import { ToastProvider } from "../ToastProvider";
import { getDocuments, scanDocumentConcepts } from "@/lib/api";

const mockedDocs = vi.mocked(getDocuments);
const mockedScan = vi.mocked(scanDocumentConcepts);

const doc = (id: string, name: string) => ({
  id, user_id: "u1", course_id: null, file_name: name, category: "reading" as const,
  summary: null, concept_notes: null, created_at: "2026-04-01T00:00:00Z", processed_at: null,
});

function renderLibrary() {
  return render(
    <ToastProvider>
      <Library />
    </ToastProvider>,
  );
}

beforeEach(() => {
  vi.spyOn(console, "error").mockImplementation(() => {});
});

afterEach(() => {
  cleanup();
  document.body.innerHTML = "";
  vi.restoreAllMocks();
  vi.clearAllMocks();
});

describe("Library load failure (#769)", () => {
  it("shows an error state with retry, not the empty-library copy", async () => {
    mockedDocs.mockRejectedValueOnce(new Error("500"));
    renderLibrary();

    expect(await screen.findByTestId("library-load-error")).toBeTruthy();
    expect(screen.queryByText(/Your library is quiet/i)).toBeNull();

    mockedDocs.mockResolvedValueOnce({ documents: [doc("a", "alpha.pdf")] } as never);
    fireEvent.click(screen.getByTestId("library-load-retry"));
    expect(await screen.findByTestId("library-doc-a")).toBeTruthy();
    expect(screen.queryByTestId("library-load-error")).toBeNull();
  });

  it("an empty library still reads as empty", async () => {
    mockedDocs.mockResolvedValueOnce({ documents: [] } as never);
    renderLibrary();

    expect(await screen.findByText(/Your library is quiet/i)).toBeTruthy();
    expect(screen.queryByTestId("library-load-error")).toBeNull();
  });
});

describe("Library concept scan belongs to the document it ran on (#769)", () => {
  it("a scan started on doc A doesn't mark doc B done", async () => {
    mockedDocs.mockResolvedValue({ documents: [doc("a", "alpha.pdf"), doc("b", "beta.pdf")] } as never);
    let resolveScan!: (v: { added: number; existing: number }) => void;
    mockedScan.mockReturnValueOnce(new Promise(r => { resolveScan = r; }) as never);
    renderLibrary();

    fireEvent.click(await screen.findByTestId("library-doc-a"));
    fireEvent.click(screen.getByTestId("library-detail-scan"));
    expect(screen.getByTestId("library-detail-scan")).toHaveTextContent("Scanning");

    // Switch documents in place (the overlay doesn't stop keyboard focus).
    fireEvent.click(screen.getByTestId("library-doc-b"));
    expect(screen.getByRole("heading", { name: "beta.pdf" })).toBeTruthy();

    await act(async () => { resolveScan({ added: 3, existing: 1 }); });
    expect(screen.getByTestId("library-detail-scan")).toHaveTextContent(/^Scan$/);
  });
});

// @vitest-environment jsdom
/**
 * Library: load-error state and overlapping reloads (#769).
 *
 *   1. A failed load is not an empty library: it renders an error state with
 *      a retry, never the empty-library copy.
 *   2. A failed folders load does not take the documents down with it.
 */

import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, cleanup, fireEvent } from "@testing-library/react";

vi.mock("@/context/UserContext", () => ({ useUser: () => ({ userId: "u1", userReady: true }) }));
vi.mock("@/lib/useIsMobile", () => ({ useIsMobile: () => false }));
vi.mock("@/lib/useNavSections", () => ({ useVisibleNavSections: () => [] }));
vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn() }) }));
vi.mock("../DocumentUploadModal", () => ({ DocumentUploadModal: () => null }));
vi.mock("@/lib/api", () => ({
  getDocuments: vi.fn(),
  deleteDocument: vi.fn(),
  getCourses: vi.fn(async () => ({ courses: [] })),
  createNote: vi.fn(),
}));
vi.mock("@/lib/libraryApi", () => ({
  getLibraryFolders: vi.fn(async () => ({ folders: [], placements: {} })),
  createLibraryFolder: vi.fn(),
  renameLibraryFolder: vi.fn(),
  deleteLibraryFolder: vi.fn(),
  moveDocumentsToFolder: vi.fn(),
  renameLibraryDocument: vi.fn(),
}));

import { Library } from "./Library";
import { ToastProvider } from "../ToastProvider";
import { getDocuments } from "@/lib/api";
import { getLibraryFolders } from "@/lib/libraryApi";

const mockedDocs = vi.mocked(getDocuments);

const doc = (id: string, name: string) => ({
  id, user_id: "u1", course_id: null, file_name: name, category: "reading" as const,
  summary: null, concept_notes: null, created_at: "2026-04-01T00:00:00Z", processed_at: null,
});

const renderLibrary = () => render(<ToastProvider><Library /></ToastProvider>);

beforeEach(() => { vi.spyOn(console, "error").mockImplementation(() => {}); });
afterEach(() => { cleanup(); document.body.innerHTML = ""; vi.restoreAllMocks(); vi.clearAllMocks(); });

describe("Library load failure (#769)", () => {
  it("shows an error state with retry, not the empty-library copy", async () => {
    mockedDocs.mockRejectedValueOnce(new Error("500"));
    renderLibrary();

    expect(await screen.findByTestId("library-load-error")).toBeTruthy();
    expect(screen.queryByText(/Nothing Here Yet/i)).toBeNull();

    mockedDocs.mockResolvedValueOnce({ documents: [doc("a", "alpha.pdf")] } as never);
    fireEvent.click(screen.getByTestId("library-load-retry"));
    expect(await screen.findByTestId("library-doc-a")).toBeTruthy();
    expect(screen.queryByTestId("library-load-error")).toBeNull();
  });

  it("an empty library still reads as empty", async () => {
    mockedDocs.mockResolvedValueOnce({ documents: [] } as never);
    renderLibrary();

    expect(await screen.findByText(/Nothing Here Yet/i)).toBeTruthy();
    expect(screen.queryByTestId("library-load-error")).toBeNull();
  });

  it("a failed folders load still shows the documents", async () => {
    vi.mocked(getLibraryFolders).mockRejectedValueOnce(new Error("500"));
    mockedDocs.mockResolvedValueOnce({ documents: [doc("a", "alpha.pdf")] } as never);
    renderLibrary();

    expect(await screen.findByTestId("library-doc-a")).toBeTruthy();
    expect(screen.queryByTestId("library-load-error")).toBeNull();
  });
});

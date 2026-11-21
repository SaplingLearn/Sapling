// @vitest-environment jsdom
/**
 * Library — the load-error state and the per-document concept scan (#769).
 *
 *   1. A failed load is not an empty library: it renders an error state with
 *      a retry, never the empty-state copy.
 *   2. The "⋯" dialog is reused when the open document changes, so a scan
 *      started on doc A must not mark doc B "done". (The redesign moved the
 *      scan out of the detail panel and into that dialog; the guarantee is
 *      the same one, on the control that replaced it.)
 */
import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, cleanup, act, fireEvent } from "@testing-library/react";

vi.mock("@/context/UserContext", () => ({
  useUser: () => ({ userId: "u1", userReady: true }),
}));
vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn() }) }));
vi.mock("@/context/FlagsContext", () => ({
  useFlagMap: () => ({ flags: {}, ready: true }),
}));

vi.mock("@/lib/api", () => ({
  getDocuments: vi.fn(),
  getCourses: vi.fn(async () => ({ courses: [] })),
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

vi.mock("@/lib/studyGuide/api", () => ({
  listGuides: vi.fn(async () => ({ guides: [] })),
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

/** Open a row's "⋯" dialog. The design positions it against the section. */
function openRowMenu(id: string) {
  const row = screen.getByTestId(`library-doc-${id}`);
  const dots = row.querySelector('[aria-label="Details and actions"]') as HTMLElement;
  fireEvent.click(dots);
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
    expect(screen.queryByTestId("library-empty")).toBeNull();

    mockedDocs.mockResolvedValueOnce({ documents: [doc("a", "alpha.pdf")] } as never);
    fireEvent.click(screen.getByTestId("library-load-retry"));
    expect(await screen.findByTestId("library-doc-a")).toBeTruthy();
    expect(screen.queryByTestId("library-load-error")).toBeNull();
  });

  it("an empty library still reads as empty", async () => {
    mockedDocs.mockResolvedValueOnce({ documents: [] } as never);
    renderLibrary();

    expect(await screen.findByTestId("library-empty")).toBeTruthy();
    expect(screen.queryByTestId("library-load-error")).toBeNull();
  });
});

describe("Library concept scan belongs to the document it ran on (#769)", () => {
  it("a scan started on doc A doesn't mark doc B done", async () => {
    mockedDocs.mockResolvedValue({
      documents: [doc("a", "alpha.pdf"), doc("b", "beta.pdf")],
    } as never);
    let resolveScan!: (v: { added: number; existing: number; concepts: string[] }) => void;
    mockedScan.mockReturnValueOnce(new Promise(r => { resolveScan = r; }) as never);
    renderLibrary();

    await screen.findByTestId("library-doc-a");
    openRowMenu("a");
    fireEvent.click(screen.getByTestId("library-detail-scan"));
    expect(screen.getByTestId("library-detail-scan")).toHaveTextContent("Scanning");

    // The same dialog, pointed at another document.
    openRowMenu("b");
    fireEvent.click(screen.getByTestId("library-doc-b"));
    openRowMenu("b");
    expect(screen.getByTestId("library-detail-scan"))
      .toHaveTextContent("Scan to Knowledge Graph");

    await act(async () => { resolveScan({ added: 3, existing: 1, concepts: [] }); });
    // Still B's menu, still unscanned: A's result stayed with A.
    expect(screen.getByTestId("library-detail-scan"))
      .toHaveTextContent("Scan to Knowledge Graph");
  });
});

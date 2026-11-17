// @vitest-environment jsdom
/**
 * The Import dialog's library documents are read when the dialog is first
 * opened, not with the page: `GET /api/documents/user/{id}` carries every
 * document's summary and notes, and most visits never import.
 */

import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, cleanup, act } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams(""),
}));

vi.mock("@/context/UserContext", () => ({
  useUser: () => ({ userId: "u1", userReady: true }),
}));

vi.mock("@/lib/useIsMobile", () => ({
  useIsMobile: () => false,
}));

// The dialog itself is pinned in components/flashcards; here it only shows
// what the page hands it.
vi.mock("@/components/flashcards/FlashcardImportModal", () => ({
  FlashcardImportModal: (p: { open: boolean; onClose: () => void; documents: { file_name: string }[]; documentsLoading?: boolean }) =>
    (p.open ? (
      <div role="dialog" aria-label="Import flashcards">
        <span data-testid="import-docs">{p.documentsLoading ? "loading" : p.documents.map(d => d.file_name).join(",") || "none"}</span>
        <button type="button" onClick={p.onClose}>Close import</button>
      </div>
    ) : null),
}));

vi.mock("@/lib/api", () => ({
  getCourses: vi.fn(async () => ({ courses: [] })),
  getFlashcards: vi.fn(async () => ({ flashcards: [] })),
  generateFlashcards: vi.fn(),
  rateFlashcard: vi.fn(),
  deleteFlashcard: vi.fn(),
  getDocuments: vi.fn(),
  getGraph: vi.fn(async () => ({ nodes: [], edges: [], stats: {} })),
  getAllAssignments: vi.fn(async () => ({ assignments: [] })),
}));

vi.mock("@/lib/topicChecklistApi", () => ({
  getTopicChecklist: vi.fn(async () => ({ topics: [] })),
}));

vi.mock("@/lib/flashcardSetsApi", async importOriginal => ({
  ...(await importOriginal<typeof import("@/lib/flashcardSetsApi")>()),
  listFlashcardSets: vi.fn(async () => ({ sets: [] })),
  createFlashcardSet: vi.fn(),
  updateFlashcardSet: vi.fn(),
  deleteFlashcardSet: vi.fn(),
  suggestFlashcardSet: vi.fn(),
}));

import { Flashcards } from "./Flashcards";
import { ToastProvider } from "../ToastProvider";
import { getDocuments } from "@/lib/api";

const mockedDocuments = vi.mocked(getDocuments);
const DOCS = { documents: [{ id: "d1", file_name: "notes.pdf" }, { id: "d2", file_name: "slides.pdf" }] };

const renderPage = () => render(<ToastProvider><Flashcards /></ToastProvider>);
const importButton = () => screen.findByRole("button", { name: /Import/ });
const shown = () => screen.getByTestId("import-docs").textContent;

beforeEach(() => {
  mockedDocuments.mockReset();
  vi.spyOn(console, "error").mockImplementation(() => {});
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("Flashcards: the Import dialog's library documents", () => {
  it("are not read with the page", async () => {
    mockedDocuments.mockResolvedValue(DOCS);
    renderPage();
    await screen.findByText(/Add a course to make flashcards for it/);
    await importButton();
    expect(mockedDocuments).not.toHaveBeenCalled();
  });

  it("are read once, when the dialog first opens, and kept for the next open", async () => {
    let answer!: (r: typeof DOCS) => void;
    mockedDocuments.mockReturnValue(new Promise(resolve => { answer = resolve; }));
    renderPage();

    await userEvent.click(await importButton());
    expect(mockedDocuments).toHaveBeenCalledTimes(1);
    expect(mockedDocuments).toHaveBeenCalledWith("u1");
    // Still on its way: not yet "no documents".
    expect(shown()).toBe("loading");

    await act(async () => { answer(DOCS); });
    expect(shown()).toBe("notes.pdf,slides.pdf");

    await userEvent.click(screen.getByRole("button", { name: "Close import" }));
    await userEvent.click(await importButton());
    expect(shown()).toBe("notes.pdf,slides.pdf");
    expect(mockedDocuments).toHaveBeenCalledTimes(1);
  });

  it("an answer that lands after the dialog was closed is there for the next open", async () => {
    let answer!: (r: typeof DOCS) => void;
    mockedDocuments.mockReturnValue(new Promise(resolve => { answer = resolve; }));
    renderPage();
    await userEvent.click(await importButton());
    await userEvent.click(screen.getByRole("button", { name: "Close import" }));
    await act(async () => { answer(DOCS); });

    await userEvent.click(await importButton());
    expect(shown()).toBe("notes.pdf,slides.pdf");
    expect(mockedDocuments).toHaveBeenCalledTimes(1);
  });

  it("a failed read shows no documents, and the next open tries again", async () => {
    mockedDocuments.mockRejectedValueOnce(new Error("boom"));
    mockedDocuments.mockResolvedValue(DOCS);
    renderPage();

    await userEvent.click(await importButton());
    await act(async () => {});
    expect(shown()).toBe("none");

    await userEvent.click(screen.getByRole("button", { name: "Close import" }));
    await userEvent.click(await importButton());
    await act(async () => {});
    expect(shown()).toBe("notes.pdf,slides.pdf");
    expect(mockedDocuments).toHaveBeenCalledTimes(2);
  });
});

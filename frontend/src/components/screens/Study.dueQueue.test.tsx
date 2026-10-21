// @vitest-environment jsdom
/**
 * Study → Flashcards with the learning loop (PKG-12): the "Due today" panel renders
 * only when getLoopStatus says the loop is on; a definitive inactive result keeps
 * legacy flashcards alone, while an outage offers retry without hiding flashcards.
 */

import React from "react";
import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, cleanup, fireEvent, waitFor } from "@testing-library/react";

vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams("mode=cards"),
}));

vi.mock("@/context/UserContext", () => ({
  useUser: () => ({ userId: "u1", userReady: true }),
}));

vi.mock("@/lib/useIsMobile", () => ({
  useIsMobile: () => false,
}));

vi.mock("@/components/flashcards/FlashcardImportModal", () => ({
  FlashcardImportModal: () => null,
}));

vi.mock("../learn/DueQueue", () => ({
  DueQueue: ({ userId, courseId }: { userId: string; courseId?: string }) => (
    <div data-testid="review-due-panel">{`${userId}:${courseId ?? "-"}`}</div>
  ),
}));

vi.mock("@/lib/api", () => ({
  getCourses: vi.fn(async () => ({ courses: [] })),
  getStudyGuideExams: vi.fn(async () => ({ exams: [] })),
  getStudyGuide: vi.fn(),
  regenerateStudyGuide: vi.fn(),
  getCachedStudyGuides: vi.fn(async () => ({ guides: [] })),
  getFlashcards: vi.fn(async () => ({ flashcards: [] })),
  generateFlashcards: vi.fn(),
  rateFlashcard: vi.fn(),
  deleteFlashcard: vi.fn(),
  getDocuments: vi.fn(async () => ({ documents: [] })),
  getLoopStatus: vi.fn(),
}));

import { Study } from "./Study";
import { ToastProvider } from "../ToastProvider";
import { getLoopStatus, getFlashcards } from "@/lib/api";

const mockedStatus = vi.mocked(getLoopStatus);

function renderStudy() {
  return render(
    <ToastProvider>
      <Study />
    </ToastProvider>,
  );
}

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("Study flashcards — Due today behind the loop", () => {
  it("shows migration guidance instead of an empty-card claim and allows retry", async () => {
    mockedStatus.mockResolvedValue({ active: false });
    const detail = "The connected database needs an update. Apply the pending database migrations.";
    vi.mocked(getFlashcards).mockRejectedValueOnce(Object.assign(new Error(JSON.stringify({ detail })), { status: 503, body: { detail } }));
    renderStudy();
    expect(await screen.findByRole("alert")).toHaveTextContent(detail);
    expect(screen.queryByText("No cards here yet")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Retry flashcards" }));
    await screen.findByText("No cards here yet");
    expect(screen.queryByRole("alert")).toBeNull();
  });
  it("renders the due queue when the loop is active", async () => {
    mockedStatus.mockResolvedValue({ active: true });
    renderStudy();
    expect((await screen.findByTestId("review-due-panel")).textContent).toBe("u1:-");
    expect(mockedStatus).toHaveBeenCalledWith("u1");
    expect(screen.getByText("No cards here yet")).toBeTruthy(); // the legacy UI stays below
  });

  it("keeps the legacy UI alone when the loop is inactive", async () => {
    mockedStatus.mockResolvedValue({ active: false });
    renderStudy();
    await screen.findByText("No cards here yet");
    expect(screen.queryByTestId("review-due-panel")).toBeNull();
  });

  it("offers retry after a failed status read while retaining flashcards", async () => {
    mockedStatus.mockRejectedValueOnce(new Error("network")).mockResolvedValueOnce({ active: true });
    renderStudy();
    await screen.findByText("No cards here yet");
    expect(screen.queryByTestId("review-due-panel")).toBeNull();
    fireEvent.click(await screen.findByRole("button", { name: "Retry due reviews" }));
    expect(await screen.findByTestId("review-due-panel")).toBeTruthy();
    await waitFor(() => expect(mockedStatus).toHaveBeenCalledTimes(2));
    expect(screen.getByText("No cards here yet")).toBeTruthy();
  });
});

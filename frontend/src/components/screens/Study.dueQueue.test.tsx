// @vitest-environment jsdom
/**
 * Study → Flashcards with the learning loop (PKG-12): the "Due today" panel renders
 * only when getLoopStatus says the loop is on; a 404 (inactive) or any error keeps the
 * legacy flashcards UI exactly as it was.
 */

import React from "react";
import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, cleanup } from "@testing-library/react";

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
import { getLoopStatus } from "@/lib/api";

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

  it("treats a failed probe as inactive", async () => {
    mockedStatus.mockRejectedValue(new Error("network"));
    renderStudy();
    await screen.findByText("No cards here yet");
    expect(screen.queryByTestId("review-due-panel")).toBeNull();
  });
});

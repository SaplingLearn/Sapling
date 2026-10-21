// @vitest-environment jsdom
import React from "react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { SavedStudyGuides } from "../study/SavedStudyGuides";
import { getCachedStudyGuides, getSavedStudyGuide, getStudyGuide, regenerateStudyGuide } from "@/lib/api";

vi.mock("@/lib/api", async (original) => ({
  ...await original<typeof import("@/lib/api")>(),
  getCachedStudyGuides: vi.fn(), getSavedStudyGuide: vi.fn(), getStudyGuide: vi.fn(), regenerateStudyGuide: vi.fn(),
}));
const entry = { id: "saved-1", course_id: "c1", exam_id: "e1", course_name: "Biology", exam_title: "Earlier midterm", overview: "", generated_at: "2026-01-01", semester: "Spring 2026" };
beforeEach(() => {
  vi.mocked(getCachedStudyGuides).mockResolvedValue({ guides: [entry] });
  vi.mocked(getSavedStudyGuide).mockResolvedValue({ cached: true, generated_at: "2026-01-01", guide: { exam: "Earlier midterm", due_date: "2026-02-01", overview: "Saved coverage", topics: [{ name: "Cells", importance: "Foundational", concepts: ["Cell walls"] }] } });
});
afterEach(() => { cleanup(); vi.clearAllMocks(); });

it("opens a saved guide by its stable ID without generating or changing its semester", async () => {
  render(<SavedStudyGuides userId="u" courseId="c1" semester="" />);
  expect(getCachedStudyGuides).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "Earlier saved guides" }));
  fireEvent.click(await screen.findByRole("button", { name: "Earlier midterm" }));
  await screen.findByText("Cell walls");
  expect(getSavedStudyGuide).toHaveBeenCalledWith("u", "saved-1", expect.any(AbortSignal));
  expect(getStudyGuide).not.toHaveBeenCalled();
  expect(regenerateStudyGuide).not.toHaveBeenCalled();
});

it("filters history to the selected course and semester", async () => {
  render(<SavedStudyGuides userId="u" courseId="c1" semester="Fall 2026" />);
  fireEvent.click(screen.getByRole("button", { name: "Earlier saved guides" }));
  await screen.findByText("No earlier saved guides for this course and semester.");
  expect(screen.queryByRole("button", { name: "Earlier midterm" })).toBeNull();
});

it("reports a deleted saved guide without regenerating it", async () => {
  vi.mocked(getSavedStudyGuide).mockRejectedValueOnce(new Error('{"detail":"This saved guide is no longer available."}'));
  render(<SavedStudyGuides userId="u" courseId="c1" semester="" />);
  fireEvent.click(screen.getByRole("button", { name: "Earlier saved guides" }));
  fireEvent.click(await screen.findByRole("button", { name: "Earlier midterm" }));
  await screen.findByRole("alert");
  expect(getStudyGuide).not.toHaveBeenCalled();
});

it("aborts a delayed content read when the course changes", async () => {
  vi.mocked(getSavedStudyGuide).mockImplementationOnce(() => new Promise(() => {}));
  const view = render(<SavedStudyGuides userId="u" courseId="c1" semester="" />);
  fireEvent.click(screen.getByRole("button", { name: "Earlier saved guides" }));
  fireEvent.click(await screen.findByRole("button", { name: "Earlier midterm" }));
  const signal = vi.mocked(getSavedStudyGuide).mock.calls[0][2];
  view.rerender(<SavedStudyGuides userId="u" courseId="other" semester="" />);
  await waitFor(() => expect(signal?.aborted).toBe(true));
});

// @vitest-environment jsdom
/**
 * Study screen: the hub, and what became of the retired `?mode=` panes.
 *
 * The tabbed Study screen is gone — Study Guide lives in the Library,
 * Flashcards and Quiz have pages of their own. `?mode=guide` / `?mode=cards`
 * survive only as redirects, so a bookmark or an open tab still lands
 * somewhere real.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, cleanup, waitFor } from "@testing-library/react";

const replace = vi.fn();
const search = { qs: "" };
vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace, push: vi.fn() }),
  useSearchParams: () => new URLSearchParams(search.qs),
}));
vi.mock("@/context/UserContext", () => ({ useUser: () => ({ userId: "u1", userReady: true }) }));
vi.mock("@/lib/useIsMobile", () => ({ useIsMobile: () => false }));
vi.mock("@/lib/topicChecklistApi", () => ({ getTopicChecklist: vi.fn(async () => ({ topics: [] })) }));
vi.mock("@/lib/api", () => ({
  getCourses: vi.fn(async () => ({ courses: [] })),
  getGraph: vi.fn(async () => ({ nodes: [], edges: [], stats: {} })),
  getAllAssignments: vi.fn(async () => ({ assignments: [] })),
  saveAssignments: vi.fn(),
  updateAssignment: vi.fn(),
  deleteAssignment: vi.fn(),
  getFlashcards: vi.fn(async () => ({ flashcards: [] })),
  getCachedStudyGuides: vi.fn(async () => ({ guides: [] })),
}));
vi.mock("@/lib/quiz/api", () => ({ listAttempts: vi.fn(async () => ({ attempts: [] })) }));
vi.mock("@/lib/studyApi", () => ({
  getStudyDaily: vi.fn(async () => ({ goal_minutes: 30, days: [] })),
  setStudyDailyGoal: vi.fn(),
}));

import { Study } from "./Study";
import { ToastProvider } from "../ToastProvider";

const renderStudy = () => render(<ToastProvider><Study /></ToastProvider>);

beforeEach(() => { search.qs = ""; replace.mockReset(); });
afterEach(cleanup);

describe("Study — the retired ?mode= panes", () => {
  it("sends ?mode=guide to the Study Guide page, keeping the course", async () => {
    search.qs = "mode=guide&course=c1";
    renderStudy();
    await waitFor(() => expect(replace).toHaveBeenCalledWith("/study/guide?course=c1"));
  });

  it("sends ?mode=cards to the Flashcards page, keeping the course", async () => {
    search.qs = "mode=cards&course=c1";
    renderStudy();
    await waitFor(() => expect(replace).toHaveBeenCalledWith("/flashcards?course=c1"));
  });

  it("redirects a course-less pane link too", async () => {
    search.qs = "mode=cards";
    renderStudy();
    await waitFor(() => expect(replace).toHaveBeenCalledWith("/flashcards"));
  });

  it("paints nothing while redirecting, so the hub never flashes first", () => {
    search.qs = "mode=guide";
    const { container } = renderStudy();
    // ToastProvider's own wrapper is all that's left.
    expect(container.querySelector("h1")).toBeNull();
  });

  it("renders the hub for a bare /study, with no redirect", async () => {
    renderStudy();
    expect(await screen.findByRole("heading", { name: "Study" })).toBeTruthy();
    expect(replace).not.toHaveBeenCalled();
  });

  it("ignores an unknown mode rather than redirecting somewhere arbitrary", async () => {
    search.qs = "mode=nonsense";
    renderStudy();
    expect(await screen.findByRole("heading", { name: "Study" })).toBeTruthy();
    expect(replace).not.toHaveBeenCalled();
  });
});

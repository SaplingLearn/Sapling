// @vitest-environment jsdom
/**
 * TranscriptModal (#139) — cumulative GPA + per-semester transcript over
 * GET /api/gradebook/gpa. Pins the same two contract layers as
 * modals.dialog.test.tsx:
 *
 * 1. Dialog semantics — closed renders nothing; open renders a labelled
 *    dialog (aria-modal, aria-labelledby → visible heading), moves focus
 *    inside, and closes on Escape.
 * 2. Failure surfacing (#166/#463 pattern) — a rejected load toasts AND
 *    leaves an inline retry that refetches; it must never render as an
 *    empty-but-fine transcript.
 */

import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, cleanup, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

const toastError = vi.hoisted(() => vi.fn());
// One STABLE toast object across renders — the real ToastProvider memoizes
// its context value, and the modal's load callback (an effect dep) keys on
// that stability. A fresh object per render would re-fire the fetch effect
// forever, which no real render does.
const toastApi = vi.hoisted(() => ({
  show: () => {},
  dismiss: () => {},
  success: () => {},
  error: toastError,
  info: () => {},
  warn: () => {},
}));
vi.mock("@/components/ToastProvider", () => ({
  useToast: () => toastApi,
}));

vi.mock("@/lib/api", () => ({
  getGpa: vi.fn(),
}));

import { TranscriptModal } from "./TranscriptModal";
import { getGpa } from "@/lib/api";
import type { GpaReport } from "@/lib/types";

const mockedGetGpa = vi.mocked(getGpa);

const REPORT: GpaReport = {
  gpa: 3.42,
  semester: null,
  scope: "cumulative",
  courses: [
    {
      course_id: "cs101",
      course_code: "CS101",
      semester: "Fall 2025",
      credits: 4,
      percent: 91.5,
      letter: "A-",
      grade_points: 3.7,
    },
    {
      course_id: "math210",
      course_code: "MATH210",
      semester: "Spring 2026",
      credits: 3,
      percent: 84.0,
      letter: "B",
      grade_points: 3.0,
    },
    {
      course_id: "bio110",
      course_code: "BIO110",
      semester: "Spring 2026",
      credits: null,
      percent: null,
      letter: null,
      grade_points: null,
    },
  ],
};

beforeEach(() => {
  mockedGetGpa.mockResolvedValue(REPORT);
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
  toastError.mockClear();
});

describe("TranscriptModal", () => {
  it("renders nothing while closed and never fetches", () => {
    render(<TranscriptModal open={false} userId="u1" onClose={() => {}} />);

    expect(screen.queryByRole("dialog")).toBeNull();
    expect(mockedGetGpa).not.toHaveBeenCalled();
  });

  it("opens as a labelled dialog and closes on Escape", async () => {
    const onClose = vi.fn();
    render(<TranscriptModal open userId="u1" onClose={onClose} />);

    const dialog = await screen.findByRole("dialog");
    expect(dialog).toHaveAttribute("aria-modal", "true");
    const heading = screen.getByRole("heading", { name: "Transcript" });
    expect(dialog.getAttribute("aria-labelledby")).toBe(heading.id);

    // Dialog moves focus on a 20ms timer; Escape only reaches the handler
    // once focus is inside the panel (same rationale as modals.dialog.test).
    await waitFor(() => expect(dialog.contains(document.activeElement)).toBe(true));

    await userEvent.keyboard("{Escape}");
    await waitFor(() => expect(onClose).toHaveBeenCalled());
  });

  it("fetches the cumulative report and renders GPA + per-semester sections", async () => {
    render(<TranscriptModal open userId="u1" onClose={() => {}} />);

    // Cumulative scope: getGpa is called WITHOUT a semester.
    await waitFor(() => expect(mockedGetGpa).toHaveBeenCalledWith("u1"));

    const gpa = await screen.findByTestId("gradebook-transcript-gpa");
    expect(gpa.textContent).toMatch(/\d\.\d\d/);
    expect(gpa.textContent).toContain("3.42");

    // Sections group by term, most recent first.
    expect(screen.getByText("Spring 2026")).toBeInTheDocument();
    expect(screen.getByText("Fall 2025")).toBeInTheDocument();

    // Course rows: code + letter, and the ungraded row reads as in-progress
    // rather than pretending to be a 0.0.
    expect(screen.getByText("CS101")).toBeInTheDocument();
    expect(screen.getByText("MATH210")).toBeInTheDocument();
    expect(screen.getByText("BIO110")).toBeInTheDocument();
    expect(screen.getByText(/in progress/i)).toBeInTheDocument();
  });

  it("shows a loading state while the report is in flight", async () => {
    let resolve!: (r: GpaReport) => void;
    mockedGetGpa.mockReturnValue(
      new Promise<GpaReport>((r) => {
        resolve = r;
      }),
    );

    render(<TranscriptModal open userId="u1" onClose={() => {}} />);

    await screen.findByRole("dialog");
    expect(screen.queryByTestId("gradebook-transcript-gpa")).toBeNull();

    resolve(REPORT);
    expect(await screen.findByTestId("gradebook-transcript-gpa")).toBeInTheDocument();
  });

  it("toasts on failure and retries from the inline button", async () => {
    mockedGetGpa.mockRejectedValueOnce(new Error("HTTP 500: boom"));

    render(<TranscriptModal open userId="u1" onClose={() => {}} />);

    await screen.findByRole("dialog");
    await waitFor(() => expect(toastError).toHaveBeenCalled());

    // Failed load must not render as an empty transcript.
    expect(screen.queryByTestId("gradebook-transcript-gpa")).toBeNull();

    // Second call (the retry) resolves — beforeEach's mockResolvedValue.
    await userEvent.click(screen.getByTestId("gradebook-transcript-retry"));

    expect(await screen.findByTestId("gradebook-transcript-gpa")).toBeInTheDocument();
    expect(mockedGetGpa).toHaveBeenCalledTimes(2);
  });
});

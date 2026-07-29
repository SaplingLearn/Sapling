// @vitest-environment jsdom
/**
 * Component tests for the Calendar screen: the view switch (#295) and the
 * load-failure surfacing (#185).
 *
 * View switch: the #295 fix wraps the calendar body in `AnimatePresence` +
 * a keyed `motion.div` so switching Month/Week/Day/Table crossfades instead
 * of snapping. Animation itself isn't asserted here — framer-motion is
 * stubbed to a passthrough so assertions don't race the real 220ms
 * transition. What these tests guard is the behavior the wrapper must
 * preserve: the correct view renders for each toggle state, the loading
 * skeleton still shows first, and nothing leaks between views.
 *
 * Load failure (#185): a failed INITIAL fetch renders the error banner +
 * retry instead of a normal-looking empty calendar; a failed BACKGROUND
 * reload (post-delete/export/reconnect) toasts and keeps the loaded view —
 * it must never blank real data behind the banner (PR #463 review).
 *
 * Unique per-view markers used below (with zero assignments):
 *   - Month  : weekday header row ("Mon".."Sun"), and NO em-dash filler.
 *   - Week   : an em-dash (U+2014) filler in each empty day cell.
 *   - Day    : "Nothing scheduled." empty state.
 *   - Table  : a real <table> + "No assignments yet." empty row.
 */

import React from "react";
import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, cleanup, fireEvent, waitFor } from "@testing-library/react";

const EM_DASH = "—"; // WeekView's empty-day filler

// Passthrough framer-motion so the keyed body renders synchronously.
type Kids = { children?: React.ReactNode };
vi.mock("framer-motion", () => ({
  AnimatePresence: ({ children }: Kids) => <>{children}</>,
  motion: new Proxy(
    {},
    { get: () => ({ children }: Kids) => <div>{children}</div> },
  ),
  useReducedMotion: () => false,
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: vi.fn(), push: vi.fn() }),
  useSearchParams: () => new URLSearchParams(""),
}));

vi.mock("@/context/UserContext", () => ({
  useUser: () => ({ userId: "u1", userReady: true }),
}));

// Hoisted shared spies so tests can assert on toast traffic (the background
// reload-failure path surfaces via toast.error, not the banner).
const toastSpies = vi.hoisted(() => ({
  success: vi.fn(),
  error: vi.fn(),
  warn: vi.fn(),
}));
vi.mock("../ToastProvider", () => ({
  useToast: () => toastSpies,
}));

vi.mock("@/lib/useConfirm", () => ({
  useConfirm: () => ({ armed: false, trigger: vi.fn(), reset: vi.fn() }),
}));

vi.mock("@/lib/useScrollLock", () => ({ useScrollLock: () => {} }));

vi.mock("../Icon", () => ({
  Icon: ({ name }: { name: string }) => <span data-testid={`icon-${name}`} />,
}));

vi.mock("../CustomSelect", () => ({
  CustomSelect: ({ value }: { value?: string }) => (
    <div data-testid="custom-select">{value}</div>
  ),
}));

vi.mock("../DocumentUploadModal", () => ({ DocumentUploadModal: () => null }));

vi.mock("../Skeleton", () => ({
  CalendarMonthSkeleton: () => <div data-testid="calendar-skeleton" />,
}));

// TopBar just needs to surface `actions` (which hold the view Toggle) and
// the subtitle so the test can drive and inspect the switch.
vi.mock("../TopBar", () => ({
  TopBar: ({ subtitle, actions }: { subtitle?: React.ReactNode; actions?: React.ReactNode }) => (
    <div>
      <div data-testid="subtitle">{subtitle}</div>
      <div data-testid="actions">{actions}</div>
    </div>
  ),
}));

vi.mock("@/lib/api", () => ({
  getAllAssignments: vi.fn(() => Promise.resolve({ assignments: [] })),
  getCourses: vi.fn(() => Promise.resolve({ courses: [] })),
  getCalendarStatus: vi.fn(() => Promise.resolve({ connected: false })),
  disconnectCalendar: vi.fn(),
  syncCalendar: vi.fn(),
  calendarAuthUrl: vi.fn(() => "#"),
  updateAssignment: vi.fn(),
  deleteAssignment: vi.fn(),
  importGoogleEvents: vi.fn(),
  exportToGoogleCalendar: vi.fn(),
}));

import { Calendar } from "./Calendar";
import { getAllAssignments } from "@/lib/api";

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

const clickView = (label: string) =>
  fireEvent.click(screen.getByRole("button", { name: label }));

describe("Calendar — loading", () => {
  it("shows the skeleton before data loads, then the month grid", async () => {
    render(<Calendar />);
    // Before the load promise resolves, the skeleton is the keyed body.
    expect(screen.getByTestId("calendar-skeleton")).toBeInTheDocument();
    // Once loaded it crossfades to the default Month view.
    await waitFor(() => expect(screen.getByText("Mon")).toBeInTheDocument());
    expect(screen.queryByTestId("calendar-skeleton")).toBeNull();
  });
});

describe("Calendar — view switch (#295)", () => {
  const loaded = async () => {
    render(<Calendar />);
    await waitFor(() => expect(screen.getByText("Mon")).toBeInTheDocument());
  };

  it("defaults to the Month view", async () => {
    await loaded();
    // Month header is present; the week/day/table markers are not.
    expect(screen.getByText("Sun")).toBeInTheDocument();
    expect(screen.queryByText(EM_DASH)).toBeNull();
    expect(screen.queryByText("Nothing scheduled.")).toBeNull();
    expect(screen.queryByRole("table")).toBeNull();
  });

  it("switches to the Week view", async () => {
    await loaded();
    clickView("Week");
    // Empty week renders an em-dash filler in each of the 7 day cells.
    const fillers = await screen.findAllByText(EM_DASH);
    expect(fillers.length).toBe(7);
    expect(screen.queryByRole("table")).toBeNull();
    expect(screen.queryByText("Nothing scheduled.")).toBeNull();
  });

  it("switches to the Day view", async () => {
    await loaded();
    clickView("Day");
    expect(await screen.findByText("Nothing scheduled.")).toBeInTheDocument();
    expect(screen.queryByText(EM_DASH)).toBeNull();
    expect(screen.queryByRole("table")).toBeNull();
  });

  it("switches to the Table view", async () => {
    await loaded();
    clickView("Table");
    expect(await screen.findByRole("table")).toBeInTheDocument();
    expect(screen.getByText("No assignments yet.")).toBeInTheDocument();
    expect(screen.getByTestId("subtitle")).toHaveTextContent("All assignments");
  });

  it("does not leak the previous view's body when switching (no double-render)", async () => {
    await loaded();
    clickView("Day");
    expect(await screen.findByText("Nothing scheduled.")).toBeInTheDocument();
    // Switching away must remove the Day body entirely.
    clickView("Month");
    await waitFor(() => expect(screen.queryByText("Nothing scheduled.")).toBeNull());
    expect(screen.getByText("Mon")).toBeInTheDocument();
  });
});

describe("Calendar — load failure (#185)", () => {
  it("shows an error banner with retry instead of the empty calendar when load fails", async () => {
    vi.mocked(getAllAssignments).mockRejectedValueOnce(new Error("HTTP 500"));
    render(<Calendar />);
    const banner = await screen.findByTestId("calendar-load-error");
    expect(banner).toBeInTheDocument();
    expect(screen.getByTestId("calendar-load-retry")).toBeInTheDocument();
    // The failure must not masquerade as a legitimately empty account: no
    // month grid, and none of the per-view empty-state copy.
    expect(screen.queryByText("Mon")).toBeNull();
    expect(screen.queryByText("No assignments yet.")).toBeNull();
    expect(screen.queryByTestId("calendar-skeleton")).toBeNull();
  });

  it("retry re-fetches; a successful retry clears the banner and renders the calendar", async () => {
    vi.mocked(getAllAssignments).mockRejectedValueOnce(new Error("HTTP 500"));
    render(<Calendar />);
    const retry = await screen.findByTestId("calendar-load-retry");
    // The once-rejection is consumed; the base mock resolves from here on.
    fireEvent.click(retry);
    await waitFor(() => expect(screen.queryByTestId("calendar-load-error")).toBeNull());
    expect(screen.getByText("Mon")).toBeInTheDocument();
  });

  it("a failing BACKGROUND reload toasts and keeps the loaded view — never the banner (PR #463 review)", async () => {
    // Initial load succeeds with one real assignment…
    vi.mocked(getAllAssignments).mockResolvedValueOnce({
      assignments: [
        {
          id: "a-1",
          title: "Problem Set 4",
          course_id: "c-1",
          course_code: "CS101",
          course_name: "Intro CS",
          due_date: "2026-03-20",
          assignment_type: "homework",
          notes: "",
        },
      ],
    } as never);
    vi.spyOn(window, "confirm").mockReturnValue(true);

    render(<Calendar />);
    clickView("Table");
    await screen.findByText("Problem Set 4");

    // …then the reload triggered by a successful delete fails.
    vi.mocked(getAllAssignments).mockRejectedValueOnce(new Error("HTTP 500"));
    fireEvent.click(screen.getByTitle("Delete"));

    await waitFor(() =>
      expect(toastSpies.error).toHaveBeenCalledWith(
        expect.stringContaining("Couldn't refresh the calendar"),
      ),
    );
    // The already-loaded view survives: no full-page banner, table intact
    // (the row itself remains because the failed reload changed no data).
    expect(screen.queryByTestId("calendar-load-error")).toBeNull();
    expect(screen.getByText("Problem Set 4")).toBeInTheDocument();
  });
});

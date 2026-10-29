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

const navigation = vi.hoisted(() => ({
  router: { replace: vi.fn(), push: vi.fn() },
  params: new URLSearchParams(),
}));
vi.mock("next/navigation", () => ({
  useRouter: () => navigation.router,
  useSearchParams: () => navigation.params,
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
import { exportToGoogleCalendar, getAllAssignments, getCalendarStatus, syncCalendar, updateAssignment } from "@/lib/api";
import * as clock from "@/lib/testMode";

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
  vi.restoreAllMocks();
  navigation.params = new URLSearchParams();
});

describe("Calendar — Google connection feedback", () => {
  it("exports all only once while pending and explains the one-time export", async () => {
    vi.mocked(getCalendarStatus).mockResolvedValueOnce({ connected: true }).mockResolvedValueOnce({ connected: true });
    let finish!: (value: { synced_count: number }) => void;
    vi.mocked(syncCalendar).mockReturnValueOnce(new Promise(resolve => { finish = resolve; }));
    render(<Calendar />);
    await screen.findByText("Mon");
    expect(screen.getByText(/Later edits and deletions/)).toBeInTheDocument();
    const button = screen.getByRole("button", { name: "Export all to Google" });
    fireEvent.click(button);
    fireEvent.click(button);
    expect(syncCalendar).toHaveBeenCalledTimes(1);
    expect(button).toBeDisabled();
    finish({ synced_count: 2 });
    await waitFor(() => expect(toastSpies.success).toHaveBeenCalledWith("Exported 2 new events to Google."));
    await waitFor(() => expect(getAllAssignments).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(screen.getByRole("button", { name: "Export all to Google" })).toBeEnabled());
  });

  it.each(["access_denied", "google_not_configured", "missing_code", "invalid_state", "oauth_exchange_failed", "unexpected", "__proto__", "toString"])(
    "explains OAuth failure %s and clears the callback parameter", async (error) => {
      navigation.params = new URLSearchParams(`calendar_error=${error}&view=table`);
      render(<Calendar />);
      await screen.findByText("Mon");
      expect(toastSpies.error).toHaveBeenCalledWith(expect.stringContaining("Google Calendar"));
      expect(toastSpies.error).toHaveBeenCalledTimes(1);
      expect(navigation.router.replace).toHaveBeenCalledWith("/calendar?view=table");
      expect(screen.getByRole("button", { name: "Connect Google" })).toBeInTheDocument();
    },
  );
});

describe("Calendar — month navigation", () => {
  it.each([
    [2026, 0, 31, "Next", "February 2026"],
    [2026, 2, 31, "Prev", "February 2026"],
    [2024, 0, 31, "Next", "February 2024"],
    [2026, 11, 31, "Next", "January 2027"],
  ])("moves one month from %i/%i/%i", async (year, month, day, button, expected) => {
    vi.spyOn(clock, "now").mockReturnValue(new Date(year, month, day, 12).getTime());
    render(<Calendar />);
    await screen.findByText("Mon");
    fireEvent.click(screen.getByRole("button", { name: button }));
    expect(screen.getByTestId("subtitle")).toHaveTextContent(expected);
  });
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

describe("Calendar — undated assignments", () => {
  // Gradebook and Gradescope items can carry due_date = null (0012 dropped
  // NOT NULL). The month grid used to call `due_date.slice` on every row and
  // crashed the whole page into the error boundary on load.
  const undated = {
    assignments: [
      {
        id: "a-nodate",
        title: "Participation",
        course_id: "c-1",
        due_date: null,
        assignment_type: "other",
        notes: "",
      },
    ],
  } as never;

  it("renders the month grid instead of crashing", async () => {
    vi.mocked(getAllAssignments).mockResolvedValueOnce(undated);
    render(<Calendar />);
    await waitFor(() => expect(screen.getByText("Mon")).toBeInTheDocument());
  });

  it("keeps undated items out of the week and day grids", async () => {
    vi.mocked(getAllAssignments).mockResolvedValueOnce(undated);
    render(<Calendar />);
    await waitFor(() => expect(screen.getByText("Mon")).toBeInTheDocument());

    clickView("Week");
    expect(await screen.findAllByText(EM_DASH)).toHaveLength(7);
    expect(screen.queryByText("Participation")).toBeNull();
    clickView("Day");
    expect(screen.getByText("Nothing scheduled.")).toBeInTheDocument();
    expect(screen.queryByText("Participation")).toBeNull();
  });

  it("lists the undated item in the table with a 'No date' label", async () => {
    vi.mocked(getAllAssignments).mockResolvedValueOnce(undated);
    render(<Calendar />);
    clickView("Table");
    await screen.findByText("Participation");
    expect(screen.getByText("No date")).toBeInTheDocument();
  });

  it("sorts undated rows last in both directions", async () => {
    vi.mocked(getAllAssignments).mockResolvedValueOnce({
      assignments: [
        { id: "a-late", title: "Late essay", due_date: "2026-04-01" },
        { id: "a-nodate", title: "Participation", due_date: null },
        { id: "a-early", title: "Early quiz", due_date: "2026-03-20" },
      ],
    } as never);
    render(<Calendar />);
    clickView("Table");
    await screen.findByText("Participation");
    const titles = () =>
      screen.getAllByRole("row").slice(1).map((r) => r.querySelector("strong")?.textContent);

    expect(titles()).toEqual(["Early quiz", "Late essay", "Participation"]);
    fireEvent.click(screen.getByRole("button", { name: "Toggle sort direction" }));
    expect(titles()).toEqual(["Late essay", "Early quiz", "Participation"]);
  });

  it("saving an edit to an undated row sends due_date null, never an empty string", async () => {
    // Initial load, then the reload after a successful save.
    vi.mocked(getAllAssignments).mockResolvedValueOnce(undated).mockResolvedValueOnce(undated);
    vi.mocked(updateAssignment).mockResolvedValueOnce({ updated: true } as never);
    render(<Calendar />);
    clickView("Table");
    await screen.findByText("Participation");

    fireEvent.click(screen.getByTitle("Edit"));
    fireEvent.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() => expect(updateAssignment).toHaveBeenCalledTimes(1));
    expect(vi.mocked(updateAssignment).mock.calls[0][2]).toMatchObject({ due_date: null });
  });

  it("keeps the enrollment course read-only when editing an assignment", async () => {
    vi.mocked(getAllAssignments).mockResolvedValueOnce({ assignments: [{
      id: "a-1", title: "Essay", course_id: "c-1", course_code: "ENG101", due_date: null,
    }] } as never);
    render(<Calendar />);
    clickView("Table");
    await screen.findByText("Essay");
    fireEvent.click(screen.getByTitle("Edit"));
    expect(screen.getByText("ENG101")).toBeInTheDocument();
    // Only assignment type remains selectable; the course is enrollment-owned.
    expect(screen.getAllByTestId("custom-select")).toHaveLength(2);
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(updateAssignment).toHaveBeenCalled());
    expect(vi.mocked(updateAssignment).mock.calls[0][2]).not.toHaveProperty("course_id");
    expect(vi.mocked(updateAssignment).mock.calls[0][2]).not.toHaveProperty("notes");
  });

  it("clears an existing due date and reloads the row as undated", async () => {
    vi.mocked(getAllAssignments)
      .mockResolvedValueOnce({ assignments: [{ id: "a-nodate", title: "Participation", due_date: "2026-03-20" }] } as never)
      .mockResolvedValueOnce(undated);
    vi.mocked(updateAssignment).mockResolvedValueOnce({ updated: true } as never);
    render(<Calendar />);
    clickView("Table");
    await screen.findByText("Participation");

    fireEvent.click(screen.getByTitle("Edit"));
    fireEvent.change(screen.getByDisplayValue("2026-03-20"), { target: { value: "" } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() => expect(updateAssignment).toHaveBeenCalledTimes(1));
    expect(vi.mocked(updateAssignment).mock.calls[0][2]).toMatchObject({ due_date: null });
    expect(await screen.findByText("No date")).toBeInTheDocument();
  });

  it("exports an undated CSV cell as empty while preserving quoted text", async () => {
    vi.mocked(getAllAssignments).mockResolvedValueOnce({
      assignments: [{ id: "a-nodate", title: 'Participation, "discussion"', course_code: "CS101", due_date: null, assignment_type: "other", notes: 'Bring "notes"' }],
    } as never);
    const createObjectURL = vi.fn<(blob: Blob) => string>(() => "blob:calendar-csv");
    const revokeObjectURL = vi.fn();
    vi.stubGlobal("URL", class extends URL {
      static createObjectURL = createObjectURL;
      static revokeObjectURL = revokeObjectURL;
    });
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
    try {
      render(<Calendar />);
      clickView("Table");
      await screen.findByText('Participation, "discussion"');
      fireEvent.click(screen.getByRole("button", { name: "Export CSV" }));

      const blob = createObjectURL.mock.calls[0][0] as Blob;
      const csv = await new Promise<string>((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = () => resolve(String(reader.result));
        reader.onerror = () => reject(reader.error);
        reader.readAsText(blob);
      });
      expect(csv).toBe('"Title","Course","Type","Due Date","Notes"\n"Participation, ""discussion""","CS101","other","","Bring ""notes"""');
      expect(click).toHaveBeenCalledTimes(1);
      expect(revokeObjectURL).toHaveBeenCalledWith("blob:calendar-csv");
    } finally {
      click.mockRestore();
      vi.unstubAllGlobals();
    }
  });

  it("reports skipped undated rows after exporting a mixed selection to Google", async () => {
    const mixed = { assignments: [
      { id: "a-nodate", title: "Participation", due_date: null },
      { id: "a-dated", title: "Exam", due_date: "2026-03-20" },
    ] } as never;
    vi.mocked(getAllAssignments).mockResolvedValueOnce(mixed).mockResolvedValueOnce(mixed);
    vi.mocked(getCalendarStatus).mockResolvedValueOnce({ connected: true });
    vi.mocked(exportToGoogleCalendar).mockResolvedValueOnce({ exported_count: 1, skipped_count: 1 });
    render(<Calendar />);
    clickView("Table");
    await screen.findByText("Participation");
    fireEvent.click(screen.getByRole("checkbox", { name: "Select all assignments" }));
    fireEvent.click(screen.getByRole("button", { name: "Export to Google" }));

    await waitFor(() => expect(exportToGoogleCalendar).toHaveBeenCalledWith("u1", ["a-nodate", "a-dated"]));
    expect(toastSpies.success).toHaveBeenCalledWith("Exported 1 (1 skipped).");
    expect(await screen.findByText("No date")).toBeInTheDocument();
  });
});

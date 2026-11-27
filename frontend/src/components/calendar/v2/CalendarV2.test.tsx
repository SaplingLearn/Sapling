// @vitest-environment jsdom
/**
 * The redesigned calendar (`calendar_v2`) against its design boards,
 * `./__fixtures__/*.design.html`, kept verbatim from the Claude Design canvas
 * (words and structure, not pixels): the Agenda, Month, Week and Semester
 * views, the course filter, an item opened in its panel (edit, add, delete)
 * and the empty state. "Today" is Wed, Mar 11 2026, the boards' day.
 */
import fs from "node:fs";
import path from "node:path";
import React from "react";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const { flags, api } = vi.hoisted(() => ({
  flags: {} as Record<string, string>,
  api: {
    updateAssignment: vi.fn(), saveAssignments: vi.fn(), deleteAssignment: vi.fn(), exportToGoogleCalendar: vi.fn(),
    getGraph: vi.fn(), getTopicChecklist: vi.fn(),
  },
}));
vi.mock("@/context/FlagsContext", () => ({ useFlag: (k: string) => flags[k] ?? "off", useFlagMap: () => ({ flags, ready: true }) }));
vi.mock("@/context/UserContext", () => ({ useUser: () => ({ userId: "u1", userReady: true }) }));
vi.mock("@/lib/api", async (orig) => ({
  ...(await orig<typeof import("@/lib/api")>()),
  updateAssignment: (...a: unknown[]) => api.updateAssignment(...a),
  saveAssignments: (...a: unknown[]) => api.saveAssignments(...a),
  deleteAssignment: (...a: unknown[]) => api.deleteAssignment(...a),
  exportToGoogleCalendar: (...a: unknown[]) => api.exportToGoogleCalendar(...a),
  getGraph: (...a: unknown[]) => api.getGraph(...a),
}));
vi.mock("@/lib/topicChecklistApi", () => ({ getTopicChecklist: (...a: unknown[]) => api.getTopicChecklist(...a) }));
vi.mock("next/link", () => ({
  default: React.forwardRef<HTMLAnchorElement, React.AnchorHTMLAttributes<HTMLAnchorElement>>(function LinkStub(props, ref) {
    return <a ref={ref} {...props} />;
  }),
}));

import type { Assignment, EnrolledCourse } from "@/lib/api";
import { CALENDAR_COPY, CalendarV2, type CalendarV2Props } from "./CalendarV2";
import { VIEWS_COPY } from "./CalendarViews";
import { PANEL_COPY } from "./ItemPanel";

const board = (name: string) => fs.readFileSync(path.join(__dirname, "__fixtures__", `${name}.design.html`), "utf8").replace(/&#39;|&rsquo;|’/g, "'");
const NOW = new Date(2026, 2, 11, 12);
const COURSES = [
  { course_id: "cs", course_code: "CS 112", course_name: "Data Structures", color: "#3a6ea5" },
  { course_id: "ma", course_code: "MA 123", course_name: "Calculus", color: "#b5602a" },
] as EnrolledCourse[];
const a = (id: string, title: string, due: string, course_id: string, assignment_type = "homework") =>
  ({ id, user_id: "u1", title, due_date: due, course_id, assignment_type, notes: "" } as Assignment);
const ASSIGNMENTS = [
  a("mid1", "Midterm Exam", "2026-03-02", "cs", "exam"),
  a("hw7", "HW 7", "2026-03-12", "cs"),
  a("q4", "Quiz 4", "2026-03-13", "ma", "quiz"),
  a("mid2", "Midterm 2", "2026-03-20", "cs", "exam"),
  a("mid3", "Midterm", "2026-03-30", "ma", "exam"),
  a("prop", "Project proposal", "2026-03-31", "cs"),
  a("prac", "Lab practical", "2026-04-01", "ma", "exam"),
];

function renderCalendar(over: Partial<CalendarV2Props> = {}) {
  const props: CalendarV2Props = {
    assignments: ASSIGNMENTS, courses: COURSES, now: NOW, googleConnected: false, importingGoogle: false, disconnectArmed: false,
    onImportSyllabus: vi.fn(), onConnectGoogle: vi.fn(), onSyncGoogle: vi.fn(), onViewGoogleEvents: vi.fn(),
    onDisconnectGoogle: vi.fn(), onExportCsv: vi.fn(), onReload: vi.fn(), ...over,
  };
  render(<CalendarV2 {...props} />);
  return props;
}

beforeEach(() => {
  api.updateAssignment.mockResolvedValue({ updated: true });
  api.saveAssignments.mockResolvedValue({ saved_count: 1 });
  api.deleteAssignment.mockResolvedValue({ deleted: true });
  api.exportToGoogleCalendar.mockResolvedValue({ exported_count: 1, skipped_count: 0 });
  api.getGraph.mockResolvedValue({ nodes: [
    { id: "n1", concept_name: "Hash tables", subject: "Data Structures", mastery_score: 0.97, mastery_tier: "mastered", course_id: "cs" },
    { id: "n2", concept_name: "Heaps", subject: "Data Structures", mastery_score: 0.2, mastery_tier: "struggling", course_id: "cs" },
  ], edges: [], stats: {} });
  api.getTopicChecklist.mockImplementation(async (_u: string, cid: string) => ({
    topics: cid === "cs" ? [
      { id: "t1", name: "Hash tables", node_id: "n1", assessment_ids: ["mid2"], assessments: [] },
      { id: "t2", name: "Heaps", node_id: "n2", assessment_ids: ["mid2"], assessments: [] },
    ] : [],
  }));
});
afterEach(() => {
  cleanup();
  vi.clearAllMocks();
  for (const k of Object.keys(flags)) delete flags[k];
});

describe("the boards", () => {
  it.each([
    ["agenda", [VIEWS_COPY.earlier(1, { title: "Midterm Exam", day: new Date(2026, 2, 2) } as never), VIEWS_COPY.prepare,
      CALENDAR_COPY.allCourses, CALENDAR_COPY.importSyllabus, CALENDAR_COPY.googleOff,
      CALENDAR_COPY.busiestText(3, 2), CALENDAR_COPY.prepareFor("MA 123 Midterm"), ...Object.values(CALENDAR_COPY.views)]],
    ["month", ["March 2026", CALENDAR_COPY.today, CALENDAR_COPY.prev.month, CALENDAR_COPY.next.month, CALENDAR_COPY.allCourses, VIEWS_COPY.exam]],
    ["semester", ["Mar 2 – Apr 26", CALENDAR_COPY.prev.semester, CALENDAR_COPY.next.semester, CALENDAR_COPY.busiest("Mar 30 – Apr 5"), VIEWS_COPY.thisWeek, VIEWS_COPY.busiest, VIEWS_COPY.course, "Nothing due"]],
    ["detail", [PANEL_COPY.fromOutline, PANEL_COPY.prepare, PANEL_COPY.studyGuide, PANEL_COPY.details, PANEL_COPY.edit, PANEL_COPY.google, PANEL_COPY.delete, "5 of 8 concepts ready"]],
    ["empty", [CALENDAR_COPY.emptyTitle, CALENDAR_COPY.emptyText, CALENDAR_COPY.emptyImport, CALENDAR_COPY.emptyAdd, CALENDAR_COPY.emptyGoogle, ...CALENDAR_COPY.emptySteps.flat()]],
    ["phone", ["Tomorrow", "In 2 days", "This week", "Next week"]],
  ])("%s says what the app says", (name, copy) => {
    const html = board(name as string);
    for (const s of copy as string[]) expect(html, s).toContain(s);
  });
});

describe("Agenda (the default)", () => {
  it("lists what is ahead by week, soonest first, with countdowns; the past behind a button", () => {
    renderCalendar();
    expect(screen.getByTestId("calendar-v2").getAttribute("data-view")).toBe("agenda");
    const thisWeek = screen.getByTestId("calendar-group-calendar-this-h");
    expect(within(thisWeek).getAllByRole("listitem").map((li) => li.getAttribute("data-testid"))).toEqual(["calendar-item-hw7", "calendar-item-q4"]);
    expect(within(screen.getByTestId("calendar-item-hw7")).getByText("Tomorrow")).toBeTruthy();
    expect(screen.queryByTestId("calendar-item-mid1")).toBeNull();
    fireEvent.click(screen.getByTestId("calendar-earlier"));
    expect(screen.getByTestId("calendar-item-mid1")).toBeTruthy();
    expect(screen.getByTestId("calendar-busiest").textContent).toContain(CALENDAR_COPY.busiest("Mar 30 – Apr 5"));
    expect(screen.getByTestId("calendar-google-card").textContent).toContain(CALENDAR_COPY.googleOff);
    // milestones off: no readiness and no Prepare
    expect(screen.queryByTestId("calendar-prepare-mid2")).toBeNull();
    expect(api.getGraph).not.toHaveBeenCalled();
  });

  it("with milestones on, an exam shows its readiness and Prepare opens its milestone in the Tutor", async () => {
    flags.milestones = "on";
    flags.learning_loop = "on";
    renderCalendar();
    const row = screen.getByTestId("calendar-item-mid2");
    await waitFor(() => expect(row.textContent).toContain("1 of 2 concepts ready"));
    expect(within(row).getByTestId("calendar-prepare-mid2").getAttribute("href")).toBe("/learn?course=cs&milestone=mid2");
  });

  it("milestones is a loop flag: with the loop off the calendar shows no readiness and no Prepare, and reads no graph", async () => {
    flags.milestones = "on"; // stored on, but /api/flags does not apply the loop's gate
    renderCalendar();
    await act(async () => {});
    expect(screen.queryByTestId("calendar-prepare-mid2")).toBeNull();
    expect(screen.getByTestId("calendar-item-mid2").textContent).not.toContain("concepts ready");
    expect(api.getGraph).not.toHaveBeenCalled();
  });

  it("an assignment with no date is listed under No date yet, and Set a date opens its form", async () => {
    const undated = { ...a("read", "Reading response", "", "cs"), due_date: null } as unknown as Assignment;
    const props = renderCalendar({ assignments: [...ASSIGNMENTS, undated] });
    const section = screen.getByTestId("calendar-undated");
    expect(within(section).getByText("Reading response")).toBeTruthy();
    fireEvent.click(within(section).getByRole("button", { name: /Set a date for Reading response/ }));
    const panel = screen.getByTestId("calendar-panel");
    expect(within(panel).getByTestId("calendar-panel-form")).toBeTruthy();
    expect((within(panel).getByTestId("calendar-field-date") as HTMLInputElement).value).toBe("");
    await act(async () => { fireEvent.click(within(panel).getByTestId("calendar-panel-save")); });
    expect(within(panel).getByRole("alert").textContent).toBe(PANEL_COPY.needDate);
    fireEvent.change(within(panel).getByTestId("calendar-field-date"), { target: { value: "2026-03-25" } });
    await act(async () => { fireEvent.click(within(panel).getByTestId("calendar-panel-save")); });
    expect(api.updateAssignment).toHaveBeenCalledWith("read", "u1", expect.objectContaining({ due_date: "2026-03-25" }));
    expect(props.onReload).toHaveBeenCalled();
    expect(screen.queryByTestId("calendar-panel")).toBeNull();
  });

  it("the course filter also lists and hides a course that has only undated assignments", () => {
    const undated = { ...a("read", "Reading response", "", "ma"), due_date: null } as unknown as Assignment;
    renderCalendar({ assignments: [a("hw7", "HW 7", "2026-03-12", "cs"), undated] });
    expect(screen.getByTestId("calendar-undated")).toBeTruthy();
    fireEvent.click(screen.getByTestId("calendar-courses"));
    fireEvent.click(screen.getByTestId("calendar-course-ma"));
    expect(screen.queryByTestId("calendar-undated")).toBeNull();
  });

  it("a day picked in the mini month opens its week and focus moves to the week's heading", () => {
    renderCalendar();
    fireEvent.click(within(screen.getByTestId("calendar-mini")).getByRole("button", { name: /Fri Mar 13/ }));
    expect(screen.getByTestId("calendar-v2").getAttribute("data-view")).toBe("week");
    expect(document.activeElement).toBe(screen.getByTestId("calendar-period"));
  });

  it("only undated assignments: no empty state, the No date yet list instead", () => {
    const undated = { ...a("read", "Reading response", "", "cs"), due_date: null } as unknown as Assignment;
    renderCalendar({ assignments: [undated] });
    expect(screen.queryByTestId("calendar-empty")).toBeNull();
    expect(screen.getByTestId("calendar-undated")).toBeTruthy();
  });

  it("the course filter is one dropdown: untick a course to hide it, All courses brings it back, Escape closes it", () => {
    renderCalendar();
    const button = screen.getByTestId("calendar-courses");
    expect(button.textContent).toBe(CALENDAR_COPY.allCourses);
    expect(screen.queryByTestId("calendar-courses-menu")).toBeNull();
    fireEvent.click(button);
    expect(button.getAttribute("aria-expanded")).toBe("true");
    const ma = screen.getByTestId("calendar-course-ma") as HTMLInputElement;
    expect(ma.checked).toBe(true);
    fireEvent.click(ma);
    expect(ma.checked).toBe(false);
    expect(screen.queryByTestId("calendar-item-q4")).toBeNull();
    expect(button.textContent).toBe("CS 112"); // one course left: its name
    fireEvent.click(screen.getByTestId("calendar-course-all"));
    expect(screen.getByTestId("calendar-item-q4")).toBeTruthy();
    expect(button.textContent).toBe(CALENDAR_COPY.allCourses);
    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByTestId("calendar-courses-menu")).toBeNull();
    expect(document.activeElement).toBe(button);
  });

  it("no subtitle under the title", () => {
    renderCalendar();
    expect(screen.queryByText(/due this week/)).toBeNull();
  });
});

describe("Month, Week and Semester", () => {
  it("Month: today marked, the arrows move a month each way, a pill opens the item", () => {
    renderCalendar();
    fireEvent.click(screen.getByTestId("calendar-view-month"));
    expect(screen.getByTestId("calendar-period").textContent).toBe("March 2026");
    // the month's name leads; the arrows and Today follow it
    const order = ["calendar-period", "calendar-prev", "calendar-today", "calendar-next"].map((id) => screen.getByTestId(id));
    for (let i = 1; i < order.length; i++) {
      expect(order[i - 1].compareDocumentPosition(order[i]) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    }
    expect(screen.getByTestId("calendar-day-2026-03-11").getAttribute("aria-current")).toBe("date");
    fireEvent.click(screen.getByTestId("calendar-prev"));
    expect(screen.getByTestId("calendar-period").textContent).toBe("February 2026");
    fireEvent.click(screen.getByTestId("calendar-next"));
    fireEvent.click(screen.getByTestId("calendar-next"));
    expect(screen.getByTestId("calendar-period").textContent).toBe("April 2026");
    fireEvent.click(screen.getByRole("button", { name: CALENDAR_COPY.today }));
    fireEvent.click(screen.getByTestId("calendar-pill-q4"));
    expect(screen.getByTestId("calendar-panel")).toBeTruthy();
  });

  it("Week: the seven days of this week", () => {
    renderCalendar();
    fireEvent.click(screen.getByTestId("calendar-view-week"));
    expect(screen.getByTestId("calendar-period").textContent).toBe("Mar 9 – 15");
    expect(within(screen.getByTestId("calendar-week")).getByTestId("calendar-pill-hw7")).toBeTruthy();
  });

  it("Semester: a row per course, a column per week; this week and the busiest marked; a chip opens its item", () => {
    renderCalendar();
    fireEvent.click(screen.getByTestId("calendar-view-semester"));
    const grid = screen.getByRole("table", { name: "Week by week" });
    expect(within(grid).getAllByRole("rowheader").map((h) => h.textContent)).toEqual(["CS 112", "MA 123"]);
    const heads = within(grid).getAllByTestId("calendar-week-load");
    expect(heads).toHaveLength(8);
    expect(heads[1].textContent).toContain(VIEWS_COPY.thisWeek);
    expect(heads.find((h) => h.textContent?.includes(VIEWS_COPY.busiest))?.textContent).toContain("3 due, 2 exams");
    const chip = within(grid).getByTestId("calendar-mark-mid2");
    expect(chip.getAttribute("aria-label")).toBe("Midterm 2, CS 112, Exam, Fri Mar 20");
    fireEvent.click(chip);
    expect(screen.getByTestId("calendar-panel")).toBeTruthy();
  });
});

describe("the item panel", () => {
  it("opens on its heading, edits, saves through the calendar and returns focus on close", async () => {
    const props = renderCalendar();
    const title = within(screen.getByTestId("calendar-item-hw7")).getByRole("button", { name: /HW 7/ });
    fireEvent.click(title);
    const panel = screen.getByTestId("calendar-panel");
    expect(document.activeElement?.textContent).toBe("HW 7");
    fireEvent.click(within(panel).getByTestId("calendar-panel-edit"));
    // Edit removes the Edit button: focus moves to the form's first field
    expect(document.activeElement).toBe(within(panel).getByTestId("calendar-field-title"));
    fireEvent.change(within(panel).getByTestId("calendar-field-title"), { target: { value: "HW 7: Hash tables" } });
    fireEvent.change(within(panel).getByTestId("calendar-field-date"), { target: { value: "2026-03-13" } });
    await act(async () => { fireEvent.click(within(panel).getByTestId("calendar-panel-save")); });
    expect(api.updateAssignment).toHaveBeenCalledWith("hw7", "u1", expect.objectContaining({ title: "HW 7: Hash tables", due_date: "2026-03-13", course_id: "cs" }));
    expect(props.onReload).toHaveBeenCalled();
    // Saving removes Save: focus goes back to Edit
    expect(document.activeElement).toBe(within(panel).getByTestId("calendar-panel-edit"));
    fireEvent.keyDown(document.activeElement!, { key: "Escape" });
    expect(screen.queryByTestId("calendar-panel")).toBeNull();
    await waitFor(() => expect(document.activeElement).toBe(title));
  });

  it("Edit after a Cancel starts from the item, not the cancelled change", () => {
    renderCalendar();
    fireEvent.click(within(screen.getByTestId("calendar-item-hw7")).getByRole("button", { name: /HW 7/ }));
    const panel = screen.getByTestId("calendar-panel");
    fireEvent.click(within(panel).getByTestId("calendar-panel-edit"));
    fireEvent.change(within(panel).getByTestId("calendar-field-title"), { target: { value: "Something else" } });
    fireEvent.click(within(panel).getByRole("button", { name: PANEL_COPY.cancel }));
    fireEvent.click(within(panel).getByTestId("calendar-panel-edit"));
    expect((within(panel).getByTestId("calendar-field-title") as HTMLInputElement).value).toBe("HW 7");
  });

  it("Add to Google disables itself once sent, and focus moves to the heading", async () => {
    renderCalendar({ googleConnected: true });
    fireEvent.click(within(screen.getByTestId("calendar-item-mid2")).getByRole("button", { name: /Midterm 2/ }));
    const google = screen.getByTestId("calendar-panel-google");
    google.focus();
    await act(async () => { fireEvent.click(google); });
    expect((google as HTMLButtonElement).disabled).toBe(true);
    expect(document.activeElement?.id).toBe("calendar-panel-title");
  });

  it("Cancel hands focus back to Edit; the calendar behind an open panel is inert", () => {
    renderCalendar();
    fireEvent.click(within(screen.getByTestId("calendar-item-hw7")).getByRole("button", { name: /HW 7/ }));
    expect(screen.getByTestId("calendar-shell").hasAttribute("inert")).toBe(true);
    const panel = screen.getByTestId("calendar-panel");
    fireEvent.click(within(panel).getByTestId("calendar-panel-edit"));
    fireEvent.click(within(panel).getByRole("button", { name: PANEL_COPY.cancel }));
    expect(document.activeElement).toBe(within(panel).getByTestId("calendar-panel-edit"));
    fireEvent.keyDown(document.activeElement!, { key: "Escape" });
    expect(screen.getByTestId("calendar-shell").hasAttribute("inert")).toBe(false);
  });

  it("after a save the open panel shows the reloaded item, not the one it opened with", () => {
    const base = {
      courses: COURSES, now: NOW, googleConnected: false, importingGoogle: false, disconnectArmed: false,
      onImportSyllabus: vi.fn(), onConnectGoogle: vi.fn(), onSyncGoogle: vi.fn(), onViewGoogleEvents: vi.fn(),
      onDisconnectGoogle: vi.fn(), onExportCsv: vi.fn(), onReload: vi.fn(),
    };
    const view = render(<CalendarV2 {...base} assignments={ASSIGNMENTS} />);
    fireEvent.click(within(screen.getByTestId("calendar-item-hw7")).getByRole("button", { name: /HW 7/ }));
    const renamed = ASSIGNMENTS.map((x) => (x.id === "hw7" ? { ...x, title: "HW 7: Hash tables", course_id: "ma" } : x));
    view.rerender(<CalendarV2 {...base} assignments={renamed} />);
    const panel = screen.getByTestId("calendar-panel");
    expect(within(panel).getByRole("heading", { level: 2 }).textContent).toBe("HW 7: Hash tables");
    expect(panel.textContent).toContain("MA 123");
    // and deleted elsewhere: the panel closes
    view.rerender(<CalendarV2 {...base} assignments={ASSIGNMENTS.filter((x) => x.id !== "hw7")} />);
    expect(screen.queryByTestId("calendar-panel")).toBeNull();
  });

  it("Delete asks twice, then deletes and closes", async () => {
    const props = renderCalendar();
    fireEvent.click(within(screen.getByTestId("calendar-item-q4")).getByRole("button", { name: /Quiz 4/ }));
    const del = screen.getByTestId("calendar-panel-delete");
    fireEvent.click(del);
    expect(del.textContent).toBe(PANEL_COPY.confirmDelete);
    expect(api.deleteAssignment).not.toHaveBeenCalled();
    await act(async () => { fireEvent.click(del); });
    expect(api.deleteAssignment).toHaveBeenCalledWith("q4", "u1");
    expect(props.onReload).toHaveBeenCalled();
    expect(screen.queryByTestId("calendar-panel")).toBeNull();
  });

  it("a failed delete keeps the panel open and says so", async () => {
    api.deleteAssignment.mockRejectedValueOnce(new Error("boom"));
    const props = renderCalendar();
    fireEvent.click(within(screen.getByTestId("calendar-item-q4")).getByRole("button", { name: /Quiz 4/ }));
    const del = screen.getByTestId("calendar-panel-delete");
    fireEvent.click(del);
    await act(async () => { fireEvent.click(del); });
    expect(screen.getByTestId("calendar-panel")).toBeTruthy();
    expect(screen.getByTestId("calendar-panel-delete-error").getAttribute("role")).toBe("alert");
    expect(props.onReload).not.toHaveBeenCalled();
  });

  it("a More action that only closes the menu hands focus back to More; Add a date's panel returns it there", async () => {
    const props = renderCalendar();
    const more = screen.getByTestId("calendar-more");
    fireEvent.click(more);
    fireEvent.click(screen.getByRole("button", { name: CALENDAR_COPY.exportCsv }));
    expect(props.onExportCsv).toHaveBeenCalled();
    expect(document.activeElement).toBe(more);
    fireEvent.click(more);
    fireEvent.click(screen.getByTestId("calendar-add-date"));
    fireEvent.keyDown(document.activeElement!, { key: "Escape" });
    await waitFor(() => expect(document.activeElement).toBe(more));
  });

  it("More → Add a date saves a new one; Google sends one when connected", async () => {
    renderCalendar({ googleConnected: true });
    fireEvent.click(screen.getByTestId("calendar-more"));
    fireEvent.click(screen.getByTestId("calendar-add-date"));
    const panel = screen.getByTestId("calendar-panel");
    expect(within(panel).getByRole("heading", { name: PANEL_COPY.newTitle })).toBeTruthy();
    await act(async () => { fireEvent.click(within(panel).getByTestId("calendar-panel-save")); });
    expect(within(panel).getByRole("alert").textContent).toBe(PANEL_COPY.needName);
    fireEvent.change(within(panel).getByTestId("calendar-field-title"), { target: { value: "Quiz 5" } });
    fireEvent.change(within(panel).getByTestId("calendar-field-type"), { target: { value: "quiz" } });
    await act(async () => { fireEvent.click(within(panel).getByTestId("calendar-panel-save")); });
    expect(api.saveAssignments).toHaveBeenCalledWith("u1", [expect.objectContaining({ title: "Quiz 5", due_date: "2026-03-11", assignment_type: "quiz", course_id: "cs" })]);
    expect(screen.queryByTestId("calendar-panel")).toBeNull();
    fireEvent.click(within(screen.getByTestId("calendar-item-mid2")).getByRole("button", { name: /Midterm 2/ }));
    await act(async () => { fireEvent.click(screen.getByTestId("calendar-panel-google")); });
    expect(api.exportToGoogleCalendar).toHaveBeenCalledWith("u1", ["mid2"]);
    expect(screen.getByTestId("calendar-panel-google").textContent).toBe(PANEL_COPY.sentToGoogle);
  });

  it("an exam's panel lists its concepts' levels and the ways to prepare, with milestones on", async () => {
    flags.milestones = "on";
    flags.learning_loop = "on";
    renderCalendar();
    await waitFor(() => expect(screen.getByTestId("calendar-item-mid2").textContent).toContain("concepts ready"));
    fireEvent.click(within(screen.getByTestId("calendar-item-mid2")).getByRole("button", { name: /Midterm 2/ }));
    const ready = screen.getByTestId("calendar-panel-readiness");
    expect(within(ready).getByText("Hash tables")).toBeTruthy();
    expect(within(ready).getByTestId("calendar-panel-prepare").getAttribute("href")).toBe("/learn?course=cs&milestone=mid2");
    expect(within(ready).getByTestId("calendar-panel-study-guide").getAttribute("href")).toBe("/study/guide?course=cs");
  });
});

it("nothing on it: the empty state's import, add and Google", () => {
  const props = renderCalendar({ assignments: [] });
  expect(screen.getByTestId("calendar-empty")).toBeTruthy();
  fireEvent.click(screen.getByTestId("calendar-empty-import"));
  expect(props.onImportSyllabus).toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: CALENDAR_COPY.emptyGoogle }));
  expect(props.onConnectGoogle).toHaveBeenCalled();
  fireEvent.click(screen.getByTestId("calendar-empty-add"));
  expect(screen.getByTestId("calendar-panel")).toBeTruthy();
});

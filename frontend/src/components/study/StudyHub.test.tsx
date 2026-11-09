// @vitest-environment jsdom
/**
 * Study hub (Sapling Study v2): every panel renders from the real clients, and
 * each control does what the design says (tabs, tool buttons -> tool pages, manage
 * dates -> calendar writes, legend filter, tile menu).
 */
import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, cleanup, fireEvent, waitFor, within } from "@testing-library/react";

const push = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push }),
  usePathname: () => "/study",
  useSearchParams: () => new URLSearchParams(),
}));
vi.mock("@/context/UserContext", () => ({ useUser: () => ({ userId: "u1", userReady: true }) }));

vi.mock("@/lib/api", () => ({
  getGraph: vi.fn(),
  getAllAssignments: vi.fn(),
  saveAssignments: vi.fn(async () => ({ saved_count: 1 })),
  updateAssignment: vi.fn(async () => ({ updated: true })),
  deleteAssignment: vi.fn(async () => ({ deleted: true })),
  getFlashcards: vi.fn(),
  getCachedStudyGuides: vi.fn(),
}));
vi.mock("@/lib/quiz/api", () => ({ listAttempts: vi.fn() }));
vi.mock("@/lib/studyApi", () => ({ getStudyDaily: vi.fn(), setStudyDailyGoal: vi.fn(async (_u: string, m: number) => ({ goal_minutes: m })) }));
vi.mock("@/lib/topicChecklistApi", () => ({ getTopicChecklist: vi.fn() }));

import { StudyHub } from "./StudyHub";
import { ToastProvider } from "../ToastProvider";
import * as api from "@/lib/api";
import { listAttempts } from "@/lib/quiz/api";
import { getStudyDaily, setStudyDailyGoal } from "@/lib/studyApi";
import { getTopicChecklist } from "@/lib/topicChecklistApi";
import type { EnrolledCourse } from "@/lib/api";

const TODAY = new Date(2026, 10, 8, 12);
const iso = (d: number) => `2026-11-${String(d).padStart(2, "0")}`;
const COURSE = { course_id: "c1", course_code: "CS101", course_name: "Intro to CS", color: "#2868B0" } as EnrolledCourse;
const node = (id: string, name: string, tier: string, score: number) => ({ id, course_id: "c1", concept_name: name, mastery_tier: tier, mastery_score: score });

beforeEach(() => {
  vi.clearAllMocks(); // call history only; each test's implementations are set below
  push.mockReset();
  // No outline by default: the roadmap keeps its prerequisite-layer fallback,
  // which is what these assertions were written against.
  vi.mocked(getTopicChecklist).mockResolvedValue({ topics: [] } as never);
  vi.mocked(api.getGraph).mockResolvedValue({
    nodes: [
      node("var", "Variables", "mastered", 0.96),
      node("loop", "Loops", "learning", 0.6),
      node("rec", "Recursion", "struggling", 0.3),
      node("arr", "Arrays", "unexplored", 0),
    ],
    edges: [
      { source: "var", target: "loop", relationship_type: "prerequisite" },
      { source: "loop", target: "rec", relationship_type: "prerequisite" },
    ],
    stats: {},
  });
  vi.mocked(api.getAllAssignments).mockResolvedValue({
    assignments: [
      { id: "hw", user_id: "u1", title: "Lab 5", due_date: iso(10), assignment_type: "homework", course_id: "c1" },
      { id: "e2", user_id: "u1", title: "Exam 2", due_date: iso(18), assignment_type: "exam", course_id: "c1" },
      { id: "q1", user_id: "u1", title: "Quiz 3", due_date: iso(20), assignment_type: "quiz", course_id: "c1" },
      { id: "other", user_id: "u1", title: "Other Final", due_date: iso(20), assignment_type: "exam", course_id: "c2" },
    ],
  });
  vi.mocked(api.getFlashcards).mockResolvedValue({ flashcards: [{ id: "f1", topic: "Loops", last_reviewed_at: new Date(2026, 10, 8, 9).toISOString() }] });
  vi.mocked(api.getCachedStudyGuides).mockResolvedValue({ guides: [] });
  vi.mocked(listAttempts).mockResolvedValue({
    total: 1, limit: 100, offset: 0,
    attempts: [{
      quiz_id: "a1", status: "completed", concept_node_id: "rec", concept_name: "Recursion", course_id: "c1",
      score: 6, total: 10, difficulty: "medium", mastery_before: 0.25, mastery_after: 0.3, mastery_delta: 0.05,
      created_at: new Date(2026, 10, 7, 10).toISOString(), completed_at: new Date(2026, 10, 7, 10, 10).toISOString(),
    }],
  });
  vi.mocked(getStudyDaily).mockResolvedValue({
    goal_minutes: 40, today: iso(8),
    days: [2, 3, 4, 5, 6, 7, 8].map(d => ({ date: iso(d), minutes: d === 8 ? 25 : 10, quiz: d === 8 ? 10 : 0, flashcards: 5, tutor: d === 8 ? 10 : 5, quizzes: 1, cards: 10, sessions: 1 })),
  });
  vi.spyOn(console, "error").mockImplementation(() => {});
});
afterEach(() => { cleanup(); vi.restoreAllMocks(); });

const renderHub = (props: Partial<React.ComponentProps<typeof StudyHub>> = {}) => render(
  <ToastProvider>
    <StudyHub courses={[COURSE]} coursesReady semester="" semesterReady isMobile={false} today={TODAY} {...props} />
  </ToastProvider>,
);

describe("StudyHub", () => {
  it("renders readiness, exam tabs, deadline pill and bell from real data", async () => {
    renderHub();
    // mean of 96, 60, 30, 0
    await waitFor(() => expect(screen.getByTestId("readiness-pct").textContent).toBe("47%"));
    expect(screen.getByText("Ready for Exam 2")).toBeTruthy();
    const tabs = screen.getAllByRole("tab").map(t => t.textContent);
    expect(tabs).toEqual(["Exam 2Wed, Nov 18", "Quiz 3Fri, Nov 20"]); // homework never a tab
    expect(screen.getByText("Lab 5 due in 2 days")).toBeTruthy();
    expect(screen.getByLabelText("Upcoming deadlines, 1 this week")).toBeTruthy();
    // Up Next is the struggling concept, with its prerequisite and last quiz.
    const card = screen.getByTestId("focus-card");
    expect(within(card).getByText("Up Next")).toBeTruthy();
    expect(within(card).getByText("Recursion")).toBeTruthy();
    expect(within(card).getByText("Loops")).toBeTruthy();
    expect(within(card).getByText("60%")).toBeTruthy();
    expect(within(card).getByText(/6\/10 correct · Yesterday/)).toBeTruthy();
    // Legend counts.
    expect(screen.getByRole("button", { name: /1\s*Struggling/ })).toBeTruthy();
    // Daily goal and recent activity.
    const goalCard = screen.getByTestId("daily-goal");
    expect(within(goalCard).getByRole("button", { name: /Daily goal: 40 minutes/ })).toBeTruthy();
    expect(within(goalCard).getByText("15 min to go")).toBeTruthy();
    expect(within(goalCard).queryByLabelText("Edit daily goal")).toBeNull(); // the gear is gone
    expect(screen.getAllByText("Recursion Quiz")).toHaveLength(2); // Last Quiz box + recent activity
    expect(screen.getByTitle("Mastery change from this quiz").textContent).toBe("Recursion+5%");
    expect(screen.getByText("1 card")).toBeTruthy();
  });

  it("names the roadmap columns from the course's checklist, not the fallback labels", async () => {
    const topic = (id: string, name: string, parent_id: string | null, node_id: string | null) =>
      ({ id, name, parent_id, node_id });
    vi.mocked(getTopicChecklist).mockResolvedValue({ topics: [
      topic("fundamentals", "Programming Fundamentals", null, null),
      topic("control-flow", "Control Flow", null, null),
      topic("t-var", "Variables", "fundamentals", "var"),
      topic("t-arr", "Arrays", "fundamentals", "arr"),
      topic("t-loop", "Loops", "control-flow", "loop"),
      topic("t-rec", "Recursion", "control-flow", "rec"),
    ] } as never);
    renderHub();
    const roadmap = await screen.findByLabelText("Roadmap");
    await waitFor(() => expect(within(roadmap).getByText("Programming Fundamentals")).toBeTruthy());
    expect(within(roadmap).getByText("Control Flow")).toBeTruthy();
    expect(within(roadmap).queryByText("Foundations")).toBeNull();
    expect(within(roadmap).queryByText("Core Methods")).toBeNull();
  });

  it("keeps the fallback labels when the course has no checklist", async () => {
    renderHub(); // beforeEach mocks an empty outline
    const roadmap = await screen.findByLabelText("Roadmap");
    await waitFor(() => expect(within(roadmap).getByText("Foundations")).toBeTruthy());
  });

  it("shows a skeleton while loading, never the add-a-course empty state", async () => {
    // The course list has not come back yet: an empty `courses` here means
    // "not loaded", not "this student has none".
    renderHub({ courses: [], coursesReady: false });
    expect(screen.getByRole("status", { name: "Loading your study hub" })).toBeTruthy();
    expect(screen.queryByText(/Add a course to get a study roadmap/)).toBeNull();
  });

  it("keeps the skeleton up until the concepts land", async () => {
    renderHub();
    expect(screen.getByRole("status", { name: "Loading your study hub" })).toBeTruthy();
    // Once the graph resolves the real hub replaces it.
    await waitFor(() => expect(screen.queryByRole("status", { name: "Loading your study hub" })).toBeNull());
    expect(screen.getByTestId("readiness-pct")).toBeTruthy();
  });

  it("shows the empty state once the load finishes with no courses", async () => {
    renderHub({ courses: [], coursesReady: true });
    expect(await screen.findByText(/Add a course to get a study roadmap/)).toBeTruthy();
    expect(screen.queryByRole("status", { name: "Loading your study hub" })).toBeNull();
  });

  it("a concept's own menu sends every tool to THAT concept", async () => {
    renderHub();
    await screen.findByText("Ready for Exam 2");
    // Open the struggling concept's tile menu.
    fireEvent.click(screen.getByTestId("tile-rec"));
    const menu = await screen.findByRole("menu");
    const href = (name: RegExp) =>
      within(menu).getByRole("menuitem", { name }).getAttribute("href");
    expect(href(/Quiz Me/)).toContain("concept=rec");
    expect(href(/Flashcards/)).toBe("/flashcards?course=c1&concepts=Recursion&start=1");
    // The course's material FOR this concept, not its study-guide shelf.
    expect(href(/Study Guide/)).toBe("/library?course=c1&q=Recursion");
  });

  it("the toolbar's Study Guide stays course-level", async () => {
    renderHub();
    await screen.findByText("Ready for Exam 2");
    fireEvent.click(screen.getByRole("button", { name: "Study Guide" }));
    expect(push).toHaveBeenLastCalledWith("/library?course=c1&type=study_guide");
  });

  it("bell lists every deadline with a colored countdown", async () => {
    renderHub();
    await screen.findByText("Ready for Exam 2");
    fireEvent.click(screen.getByLabelText("Upcoming deadlines, 1 this week"));
    const panel = screen.getByRole("dialog", { name: "Upcoming deadlines" });
    expect(within(panel).getByText("in 2 days").getAttribute("style")).toContain("rgb(168, 68, 63)");
    expect(within(panel).getByText("in 10 days")).toBeTruthy();
    fireEvent.click(within(panel).getByText("Quiz 3"));
    expect(screen.getByText("Ready for Quiz 3")).toBeTruthy();
  });

  it("Quiz goes straight to a started quiz, no picker in between", async () => {
    renderHub();
    await screen.findByText("Ready for Exam 2");
    fireEvent.click(screen.getByRole("button", { name: "Quiz" }));
    expect(screen.queryByRole("dialog")).toBeNull();
    // Struggling + learning is Loops and Recursion: two concepts, and a quiz is
    // one concept or the whole course, so this is the course's quiz.
    expect(push).toHaveBeenLastCalledWith("/quiz?course=c1&from=link&return=%2Fstudy&start=1");
  });

  it("Flashcards and Study Guide go straight to their tool pages", async () => {
    renderHub();
    await screen.findByText("Ready for Exam 2");
    fireEvent.click(screen.getByRole("button", { name: "Study Guide" }));
    // Study guides are Library documents now, filed by course and type.
    expect(push).toHaveBeenLastCalledWith("/library?course=c1&type=study_guide");
    fireEvent.click(screen.getByRole("button", { name: "Flashcards" }));
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(push).toHaveBeenLastCalledWith("/flashcards?course=c1&concepts=Loops%7CRecursion&start=1");
  });

  it("legend chips filter the roadmap and tiles open their action menu", async () => {
    renderHub();
    await screen.findByText("Ready for Exam 2");
    fireEvent.click(screen.getByRole("button", { name: /1\s*Mastered/ }));
    expect(screen.getByTestId("tile-var").style.opacity).toBe("1");
    expect(screen.getByTestId("tile-rec").style.opacity).toBe("0.3");
    fireEvent.click(screen.getByTestId("tile-loop"));
    const menu = screen.getByRole("menu");
    expect(within(menu).getByText("1 Flashcards")).toBeTruthy();
    // The menu items are real links now (middle-click / open-in-new-tab),
    // so the destination is the href rather than a router.push argument.
    // Both ask the tool to START, not just to open.
    expect(within(menu).getByRole("menuitem", { name: /Quiz Me/ }).getAttribute("href"))
      .toBe("/quiz?concept=loop&from=link&return=%2Fstudy&start=1");
    expect(within(menu).getByRole("menuitem", { name: /1 Flashcards/ }).getAttribute("href"))
      .toBe("/flashcards?course=c1&concepts=Loops&start=1");
  });

  it("only one tile menu is open; Esc and an outside press close it", async () => {
    renderHub();
    await screen.findByText("Ready for Exam 2");
    const loop = screen.getByTestId("tile-loop");
    fireEvent.click(loop);
    expect(screen.getAllByRole("menu")).toHaveLength(1);
    expect(loop.getAttribute("aria-expanded")).toBe("true");
    // The open menu's tile (and its column) are lifted over the later tiles,
    // or the next tile paints over the menu.
    expect(loop.style.zIndex).toBe("2");
    expect(screen.getByTestId("tile-rec").style.zIndex).toBe("");

    // Esc closes it and hands focus back to the tile.
    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByRole("menu")).toBeNull();
    expect(document.activeElement).toBe(loop);

    // A press on another tile swaps the menu over rather than stacking two.
    fireEvent.click(loop);
    const rec = screen.getByTestId("tile-rec");
    fireEvent.pointerDown(rec);
    fireEvent.click(rec);
    const menus = screen.getAllByRole("menu");
    expect(menus).toHaveLength(1);
    expect(rec.contains(menus[0])).toBe(true);

    // A press inside the menu keeps it; a press anywhere else closes it.
    fireEvent.pointerDown(menus[0]);
    expect(screen.getAllByRole("menu")).toHaveLength(1);
    fireEvent.pointerDown(document.body);
    expect(screen.queryByRole("menu")).toBeNull();
  });

  it("hovering a tile never swaps the focus card or the gap warning (no layout jump)", async () => {
    renderHub();
    await screen.findByText("Ready for Exam 2");
    const card = screen.getByTestId("focus-card");
    expect(within(card).getByText("Recursion")).toBeTruthy();
    expect(screen.getByTestId("focus-gap-warning").textContent).toContain("Recursion");
    // Hovering the mastered tile (no gap) used to unmount the warning and
    // re-render the card for Variables, reflowing the roadmap under the pointer.
    fireEvent.mouseEnter(screen.getByTestId("tile-var"));
    expect(within(card).getByText("Recursion")).toBeTruthy();
    expect(screen.getByTestId("focus-gap-warning").textContent).toContain("Recursion");
    fireEvent.mouseLeave(screen.getByTestId("tile-var"));
    // A click is what moves the focus.
    fireEvent.click(screen.getByTestId("tile-var"));
    expect(within(screen.getByTestId("focus-card")).getByText("Variables")).toBeTruthy();
    expect(screen.queryByTestId("focus-gap-warning")).toBeNull();
  });

  it("Exams and Deadlines writes through the calendar endpoints", async () => {
    renderHub();
    await screen.findByText("Ready for Exam 2");
    fireEvent.click(screen.getByLabelText("Manage exams and deadlines"));
    const dlg = screen.getByRole("dialog", { name: "Exams and deadlines" });
    const names = within(dlg).getAllByLabelText("Name") as HTMLInputElement[];
    expect(names.map(n => n.value)).toEqual(["Lab 5", "Exam 2", "Quiz 3"]);
    fireEvent.change(names[1], { target: { value: "Exam Two" } });
    fireEvent.click(within(dlg).getAllByLabelText("Remove")[0]);
    fireEvent.click(within(dlg).getByText("+ Add Exam or Deadline"));
    const fresh = within(dlg).getAllByLabelText("Name").at(-1) as HTMLInputElement;
    fireEvent.change(fresh, { target: { value: "Final" } });
    fireEvent.click(within(dlg).getByText("Save Dates"));
    await waitFor(() => expect(api.saveAssignments).toHaveBeenCalled());
    expect(api.deleteAssignment).toHaveBeenCalledWith("hw", "u1");
    expect(api.updateAssignment).toHaveBeenCalledWith("e2", "u1", { title: "Exam Two" });
    expect(api.saveAssignments).toHaveBeenCalledWith("u1", [{ title: "Final", course_id: "c1", due_date: iso(15), assignment_type: "exam" }]);
  });

  it("saving dates never deletes rows the modal never showed (opened before they loaded)", async () => {
    let release!: () => void;
    const loaded = vi.mocked(api.getAllAssignments).getMockImplementation()!;
    vi.mocked(api.getAllAssignments).mockImplementationOnce(
      (...args) => new Promise(res => { release = () => res(loaded(...args)); }),
    );
    renderHub();
    // Open the modal while the course's assignments are still in flight.
    fireEvent.click(await screen.findByLabelText("Manage exams and deadlines"));
    const dlg = screen.getByRole("dialog", { name: "Exams and deadlines" });
    expect(within(dlg).queryAllByLabelText("Name")).toHaveLength(0);
    release();
    await screen.findByText("Ready for Exam 2"); // the list arrives under the open modal
    fireEvent.click(within(dlg).getByText("+ Add Exam or Deadline"));
    fireEvent.change(within(dlg).getAllByLabelText("Name").at(-1)!, { target: { value: "Final" } });
    fireEvent.click(within(dlg).getByText("Save Dates"));
    await waitFor(() => expect(api.saveAssignments).toHaveBeenCalled());
    expect(api.deleteAssignment).not.toHaveBeenCalled();
    expect(api.updateAssignment).not.toHaveBeenCalled();
  });

  it("the daily goal can be changed", async () => {
    renderHub();
    // The target itself is the edit button; the stepper snaps to 5s.
    fireEvent.click(await screen.findByRole("button", { name: /Daily goal: 40 minutes/ }));
    fireEvent.change(screen.getByLabelText("Daily goal in minutes"), { target: { value: "47" } });
    fireEvent.click(screen.getByRole("button", { name: "Increase goal" }));
    expect((screen.getByLabelText("Daily goal in minutes") as HTMLInputElement).value).toBe("50");
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await screen.findByRole("button", { name: /Daily goal: 50 minutes/ });
    expect(setStudyDailyGoal).toHaveBeenCalledWith("u1", 50);
  });

  it("Escape cancels a goal edit without saving", async () => {
    renderHub();
    fireEvent.click(await screen.findByRole("button", { name: /Daily goal: 40 minutes/ }));
    const input = screen.getByLabelText("Daily goal in minutes");
    fireEvent.change(input, { target: { value: "90" } });
    fireEvent.keyDown(input, { key: "Escape" });
    expect(screen.queryByLabelText("Daily goal in minutes")).toBeNull();
    expect(screen.getByRole("button", { name: /Daily goal: 40 minutes/ })).toBeTruthy();
    expect(setStudyDailyGoal).not.toHaveBeenCalled();
  });
});

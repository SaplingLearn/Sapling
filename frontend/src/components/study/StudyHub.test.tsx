// @vitest-environment jsdom
/**
 * Study hub (Sapling Study v2): every panel renders from the real clients, and
 * each control does what the design says (tabs, tool buttons -> tool pages, manage
 * dates -> calendar writes, legend filter, tile menu).
 */
import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, cleanup, fireEvent, waitFor, within, act } from "@testing-library/react";

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
vi.mock("@/lib/topicChecklistApi", () => ({ getTopicChecklist: vi.fn(), refreshTopicChecklist: vi.fn() }));
const flagState = vi.hoisted(() => ({ hideQuiz: false }));
vi.mock("@/context/FlagsContext", () => ({
  useFlagMap: () => ({ flags: flagState.hideQuiz ? { hide_quiz: "on" } : {}, ready: true }),
}));

import { StudyHub } from "./StudyHub";
import { ToastProvider } from "../ToastProvider";
import * as api from "@/lib/api";
import { listAttempts } from "@/lib/quiz/api";
import { getStudyDaily, setStudyDailyGoal } from "@/lib/studyApi";
import { getTopicChecklist, refreshTopicChecklist } from "@/lib/topicChecklistApi";
import type { EnrolledCourse } from "@/lib/api";

const TODAY = new Date(2026, 10, 8, 12);
const iso = (d: number) => `2026-11-${String(d).padStart(2, "0")}`;
const COURSE = { course_id: "c1", course_code: "CS101", course_name: "Intro to CS", color: "#2868B0" } as EnrolledCourse;
const COURSE2 = { course_id: "c2", course_code: "MA225", course_name: "Calculus", color: "#B04A28" } as EnrolledCourse;
const node = (id: string, name: string, tier: string, score: number) => ({ id, course_id: "c1", concept_name: name, mastery_tier: tier, mastery_score: score });
/** A checklist topic: `on` lists the assessment ids the outline puts it on. */
const topic = (id: string, name: string, parent_id: string | null, node_id: string | null, on: string[] = []) =>
  ({ id, name, parent_id, node_id, assessments: on.map(a => ({ id: a })) });
/** An outline that puts the four concepts under two real categories. */
const CATEGORISED = [
  topic("fundamentals", "Programming Fundamentals", null, null),
  topic("control-flow", "Control Flow", null, null),
  topic("t-var", "Variables", "fundamentals", "var"),
  topic("t-arr", "Arrays", "fundamentals", "arr"),
  topic("t-loop", "Loops", "control-flow", "loop"),
  topic("t-rec", "Recursion", "control-flow", "rec"),
];
/** The readiness label once the exams have loaded. With no outline linking
 *  concepts to Exam 2 (the default below) the band speaks for the whole course
 *  and says so, so this, not "Ready for Exam 2", is the "page has loaded" text. */
const COURSE_READINESS = "CS101 Readiness";
const hubLoaded = () => screen.findByText(COURSE_READINESS);

beforeEach(() => {
  vi.clearAllMocks(); // call history only; each test's implementations are set below
  push.mockReset();
  // No outline by default, and none to generate: the roadmap keeps its
  // prerequisite-layer fallback, which is what these assertions were written
  // against, and no exam has concepts of its own.
  vi.mocked(getTopicChecklist).mockResolvedValue({ topics: [], needs_refresh: false } as never);
  vi.mocked(refreshTopicChecklist).mockResolvedValue({ topics: [], needs_refresh: false } as never);
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
    // Nothing links concepts to Exam 2, so that 47% is the course's and is
    // labelled as the course's. The tab still carries the exam's title.
    expect(screen.getByText(COURSE_READINESS)).toBeTruthy();
    expect(screen.queryByText("Ready for Exam 2")).toBeNull();
    const tabs = screen.getAllByRole("tab").map(t => t.textContent);
    expect(tabs).toEqual(["Exam 2Wed, Nov 18", "Quiz 3Fri, Nov 20"]); // homework never a tab
    // Due-soon work is not called out on the page; the bell counts and lists it.
    expect(screen.queryByText(/Lab 5/)).toBeNull();
    expect(screen.getByLabelText("Upcoming deadlines, 1 this week")).toBeTruthy();
    // Up Next is the struggling concept, with its prerequisite and last quiz.
    const card = screen.getByTestId("focus-card");
    expect(within(card).getByText("Up Next")).toBeTruthy();
    expect(within(card).getByText("Recursion")).toBeTruthy();
    expect(within(card).getByText("Loops")).toBeTruthy();
    // The block names the concept and how to start on it; no quiz history.
    expect(within(card).getByRole("link", { name: "Start quiz" })).toBeTruthy();
    expect(within(card).queryByText(/Last Quiz/i)).toBeNull();
    // Legend counts.
    expect(screen.getByRole("button", { name: /1\s*Struggling/ })).toBeTruthy();
    // Daily goal and recent activity.
    const goalCard = screen.getByTestId("daily-goal");
    expect(within(goalCard).getByRole("button", { name: /Daily goal: 40 minutes/ })).toBeTruthy();
    expect(within(goalCard).getByText("15 min to go")).toBeTruthy();
    expect(within(goalCard).queryByLabelText("Edit daily goal")).toBeNull(); // the gear is gone
    expect(screen.getAllByText("Recursion Quiz")).toHaveLength(1); // recent activity only
    expect(screen.getByTitle("Mastery change from this quiz").textContent).toBe("Recursion+5%");
    expect(screen.getByText("1 card")).toBeTruthy();
  });

  it("offers Quiz in the Study tools unless hide_quiz hides it (#620)", async () => {
    renderHub();
    await waitFor(() => expect(screen.getByTestId("readiness-pct").textContent).toBe("47%"));
    const tools = screen.getByRole("navigation", { name: "Study tools" });
    expect(within(tools).getByRole("button", { name: "Quiz" })).toBeTruthy();
    cleanup();

    flagState.hideQuiz = true;
    try {
      renderHub();
      await waitFor(() => expect(screen.getByTestId("readiness-pct").textContent).toBe("47%"));
      const hidden = screen.getByRole("navigation", { name: "Study tools" });
      expect(within(hidden).queryByRole("button", { name: "Quiz" })).toBeNull();
      expect(within(hidden).getByRole("button", { name: "Flashcards" })).toBeTruthy();
    } finally {
      flagState.hideQuiz = false;
    }
  });

  it("names the roadmap columns from the course's checklist, not the fallback labels", async () => {
    vi.mocked(getTopicChecklist).mockResolvedValue({ topics: CATEGORISED } as never);
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
    await hubLoaded();
    // Open the struggling concept's "..." menu.
    fireEvent.click(screen.getByRole("button", { name: "Actions for Recursion" }));
    const menu = await screen.findByRole("menu");
    const href = (name: RegExp) =>
      within(menu).getByRole("menuitem", { name }).getAttribute("href");
    expect(href(/Quiz Me/)).toContain("concept=rec");
    expect(href(/Flashcards/)).toBe("/flashcards?course=c1&concepts=Recursion&start=1");
    // No Study Guide here: a guide is per exam, not per concept (header only).
    expect(within(menu).queryByRole("menuitem", { name: /Study Guide/i })).toBeNull();
    expect(within(screen.getByTestId("focus-card")).queryByText(/study guide/i)).toBeNull();
  });

  it("the header's Study Guide opens the guide page on this course, no exam picked for you", async () => {
    renderHub();
    await hubLoaded();
    fireEvent.click(screen.getByRole("button", { name: "Study Guide" }));
    expect(push).toHaveBeenLastCalledWith("/study/guide?course=c1");
  });

  it("bell lists every deadline with a colored countdown", async () => {
    renderHub();
    await hubLoaded();
    fireEvent.click(screen.getByLabelText("Upcoming deadlines, 1 this week"));
    const panel = screen.getByRole("dialog", { name: "Upcoming deadlines" });
    expect(within(panel).getByText("in 2 days").getAttribute("style")).toContain("var(--err)");
    expect(within(panel).getByText("in 10 days")).toBeTruthy();
    // A dated exam or quiz in the list selects its tab.
    const selected = () => screen.getAllByRole("tab").filter(t => t.getAttribute("aria-selected") === "true").map(t => t.textContent);
    expect(selected()).toEqual(["Exam 2Wed, Nov 18"]);
    fireEvent.click(within(panel).getByText("Quiz 3"));
    expect(selected()).toEqual(["Quiz 3Fri, Nov 20"]);
  });

  it("the header's Quiz opens the quiz page on this course without starting one", async () => {
    renderHub();
    await hubLoaded();
    fireEvent.click(screen.getByRole("button", { name: "Quiz" }));
    expect(screen.queryByRole("dialog")).toBeNull();
    // No start=1: the quiz home offers this course; the student starts it.
    expect(push).toHaveBeenLastCalledWith("/quiz?course=c1&from=link&return=%2Fstudy%3Fcourse%3Dc1");
  });

  it("the header's Flashcards and Study Guide open their pages on this course", async () => {
    renderHub();
    await hubLoaded();
    fireEvent.click(screen.getByRole("button", { name: "Study Guide" }));
    expect(push).toHaveBeenLastCalledWith("/study/guide?course=c1");
    fireEvent.click(screen.getByRole("button", { name: "Flashcards" }));
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(push).toHaveBeenLastCalledWith("/flashcards?course=c1");
  });

  it("legend chips filter the roadmap and a tile's ... opens its action menu", async () => {
    renderHub();
    await hubLoaded();
    fireEvent.click(screen.getByRole("button", { name: /1\s*Mastered/ }));
    expect(screen.getByTestId("tile-var").style.opacity).toBe("1");
    expect(screen.getByTestId("tile-rec").style.opacity).toBe("0.3");
    // The tile itself only selects; the menu is behind its "..." button.
    fireEvent.click(screen.getByTestId("tile-loop"));
    expect(screen.queryByRole("menu")).toBeNull();
    fireEvent.click(screen.getByTestId("tile-actions-loop"));
    const menu = screen.getByRole("menu");
    expect(within(menu).getByText("1 Flashcards")).toBeTruthy();
    // The menu items are real links now (middle-click / open-in-new-tab),
    // so the destination is the href rather than a router.push argument.
    // Both ask the tool to START, not just to open.
    expect(within(menu).getByRole("menuitem", { name: /Quiz Me/ }).getAttribute("href"))
      .toBe("/quiz?concept=loop&from=link&return=%2Fstudy%3Fcourse%3Dc1&start=1");
    expect(within(menu).getByRole("menuitem", { name: /1 Flashcards/ }).getAttribute("href"))
      .toBe("/flashcards?course=c1&concepts=Loops&start=1");
  });

  it("only one tile menu is open; Esc and an outside press close it", async () => {
    renderHub();
    await hubLoaded();
    const loop = screen.getByTestId("tile-loop");
    const loopMore = screen.getByTestId("tile-actions-loop");
    fireEvent.click(loopMore);
    expect(screen.getAllByRole("menu")).toHaveLength(1);
    expect(loopMore.getAttribute("aria-expanded")).toBe("true");
    // The open menu's tile (and its column) are lifted over the later tiles,
    // or the next tile paints over the menu.
    expect(loop.style.zIndex).toBe("2");
    expect(screen.getByTestId("tile-rec").style.zIndex).toBe("");

    // Esc closes it and hands focus back to the "..." that opened it.
    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByRole("menu")).toBeNull();
    expect(document.activeElement).toBe(loopMore);

    // Opening another tile's menu swaps it over rather than stacking two.
    fireEvent.click(loopMore);
    const rec = screen.getByTestId("tile-rec");
    const recMore = screen.getByTestId("tile-actions-rec");
    fireEvent.pointerDown(recMore);
    fireEvent.click(recMore);
    const menus = screen.getAllByRole("menu");
    expect(menus).toHaveLength(1);
    expect(rec.contains(menus[0])).toBe(true);

    // A press inside the menu keeps it; a press anywhere else closes it.
    fireEvent.pointerDown(menus[0]);
    expect(screen.getAllByRole("menu")).toHaveLength(1);
    fireEvent.pointerDown(document.body);
    expect(screen.queryByRole("menu")).toBeNull();
  });

  it("hovering a tile never swaps the focus card (no layout jump); the gap shows on the tile", async () => {
    renderHub();
    await hubLoaded();
    const card = screen.getByTestId("focus-card");
    expect(within(card).getByText("Recursion")).toBeTruthy();
    // The prerequisite gap is no longer a banner beside the figure; it is the
    // mark (with the reason as its tooltip) on the concept's own tile.
    expect(screen.queryByTestId("focus-gap-warning")).toBeNull();
    expect(within(screen.getByTestId("tile-rec")).getByTitle(/isn't mastered yet/)).toBeTruthy();
    // Hovering another tile used to re-render the card for it, reflowing the
    // roadmap under the pointer.
    fireEvent.mouseEnter(screen.getByTestId("tile-var"));
    expect(within(card).getByText("Recursion")).toBeTruthy();
    fireEvent.mouseLeave(screen.getByTestId("tile-var"));
    // A click is what moves the focus.
    fireEvent.click(screen.getByTestId("tile-var"));
    expect(within(screen.getByTestId("focus-card")).getByText("Variables")).toBeTruthy();
  });

  it("the + beside the exam tabs opens the editor on a new row, ready to type", async () => {
    renderHub();
    await hubLoaded();
    fireEvent.click(screen.getByRole("button", { name: "Add exam or deadline" }));
    const dlg = screen.getByRole("dialog", { name: "Exams and deadlines" });
    const names = within(dlg).getAllByLabelText("Name") as HTMLInputElement[];
    expect(names.map(n => n.value)).toEqual(["Lab 5", "Exam 2", "Quiz 3", ""]);
    await waitFor(() => expect(document.activeElement).toBe(names.at(-1)));
    fireEvent.change(names.at(-1)!, { target: { value: "Final" } });
    fireEvent.click(within(dlg).getByText("Save Dates"));
    await waitFor(() => expect(api.saveAssignments).toHaveBeenCalledWith(
      "u1", [{ title: "Final", course_id: "c1", due_date: iso(15), assignment_type: "exam" }], // a week out
    ));
    expect(api.deleteAssignment).not.toHaveBeenCalled();
  });

  it("Exams and Deadlines writes through the calendar endpoints", async () => {
    renderHub();
    await hubLoaded();
    // The dates editor, for changing what is there: the bell's Manage Dates.
    fireEvent.click(screen.getByLabelText(/^Upcoming deadlines, /));
    fireEvent.click(screen.getByText("Manage Dates"));
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
    fireEvent.click(await screen.findByLabelText(/^Upcoming deadlines, /));
    fireEvent.click(screen.getByText("Manage Dates"));
    const dlg = screen.getByRole("dialog", { name: "Exams and deadlines" });
    expect(within(dlg).queryAllByLabelText("Name")).toHaveLength(0);
    release();
    await hubLoaded(); // the list arrives under the open modal
    fireEvent.click(within(dlg).getByText("+ Add Exam or Deadline"));
    fireEvent.change(within(dlg).getAllByLabelText("Name").at(-1)!, { target: { value: "Final" } });
    fireEvent.click(within(dlg).getByText("Save Dates"));
    await waitFor(() => expect(api.saveAssignments).toHaveBeenCalled());
    expect(api.deleteAssignment).not.toHaveBeenCalled();
    expect(api.updateAssignment).not.toHaveBeenCalled();
  });

  it("Recent Activity shows four rows; Show all opens the full list in a modal", async () => {
    vi.mocked(listAttempts).mockResolvedValue({
      total: 6, limit: 100, offset: 0,
      attempts: [1, 2, 3, 4, 5, 6].map(n => ({
        quiz_id: `a${n}`, status: "completed", concept_node_id: "rec", concept_name: `Topic ${n}`, course_id: "c1",
        score: 6, total: 10, difficulty: "medium", mastery_before: null, mastery_after: null, mastery_delta: null,
        // All later than the fixture's flashcard review (Nov 8, 09:00), so the
        // four newest rows are quizzes.
        created_at: new Date(2026, 10, 8, 10, n).toISOString(), completed_at: new Date(2026, 10, 8, 10, 10 + n).toISOString(),
      })),
    } as never);
    renderHub();
    await hubLoaded();
    const rail = screen.getByRole("region", { name: "Recent activity" });
    const titlesIn = (el: HTMLElement) => within(el).queryAllByText(/^Topic \d Quiz$/).map(e => e.textContent);
    // Newest first, four of the six.
    await waitFor(() => expect(titlesIn(rail)).toEqual(["Topic 6 Quiz", "Topic 5 Quiz", "Topic 4 Quiz", "Topic 3 Quiz"]));
    const toggle = within(rail).getByRole("button", { name: /Show all 7/ }); // six quizzes + the fixture's flashcard review
    fireEvent.click(toggle);
    // The rail itself never grows: the full list is in a dialog.
    expect(titlesIn(rail)).toHaveLength(4);
    const dialog = screen.getByRole("dialog", { name: "Recent activity" });
    expect(titlesIn(dialog)).toHaveLength(6);
    expect(within(dialog).getByText("Loops")).toBeTruthy(); // the flashcard review too
    fireEvent.click(within(dialog).getByRole("button", { name: "Close" }));
    expect(screen.queryByRole("dialog", { name: "Recent activity" })).toBeNull();
    expect(titlesIn(rail)).toHaveLength(4);
  });

  it("Recent Activity offers no Show all when there are four rows or fewer", async () => {
    renderHub();
    await hubLoaded();
    expect(screen.queryByTestId("recent-toggle")).toBeNull();
  });

  it("the daily goal is changed with one tap on a preset", async () => {
    renderHub();
    // The target itself is the edit button; it opens the presets in its place.
    fireEvent.click(await screen.findByRole("button", { name: /Daily goal: 40 minutes/ }));
    const presets = screen.getByRole("radiogroup", { name: /Daily goal/ });
    expect(within(presets).getAllByRole("radio").map(r => r.textContent)).toEqual(["15", "30", "45", "60", "90"]);
    fireEvent.click(within(presets).getByRole("radio", { name: "60 minutes" }));
    await screen.findByRole("button", { name: /Daily goal: 60 minutes/ });
    expect(setStudyDailyGoal).toHaveBeenCalledWith("u1", 60);
    expect(screen.queryByRole("radiogroup")).toBeNull();
  });

  it("any other number goes through the custom field", async () => {
    renderHub();
    fireEvent.click(await screen.findByRole("button", { name: /Daily goal: 40 minutes/ }));
    // 40 is not a preset, so the custom slot shows it as the current choice.
    const custom = screen.getByRole("button", { name: /Custom goal: 40 minutes/ });
    expect(custom.getAttribute("aria-pressed")).toBe("true");
    fireEvent.click(custom);
    const input = screen.getByLabelText("Daily goal in minutes") as HTMLInputElement;
    expect(input.value).toBe("40");
    fireEvent.change(input, { target: { value: "47" } });
    fireEvent.click(screen.getByRole("button", { name: "Set" }));
    await screen.findByRole("button", { name: /Daily goal: 47 minutes/ });
    expect(setStudyDailyGoal).toHaveBeenCalledWith("u1", 47);
  });

  it("Escape, or a press elsewhere, cancels a goal edit without saving", async () => {
    renderHub();
    fireEvent.click(await screen.findByRole("button", { name: /Daily goal: 40 minutes/ }));
    fireEvent.keyDown(screen.getByRole("radiogroup"), { key: "Escape" });
    expect(screen.queryByRole("radiogroup")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: /Daily goal: 40 minutes/ }));
    fireEvent.pointerDown(document.body);
    expect(screen.queryByRole("radiogroup")).toBeNull();
    expect(screen.getByRole("button", { name: /Daily goal: 40 minutes/ })).toBeTruthy();
    expect(setStudyDailyGoal).not.toHaveBeenCalled();
  });
});

/** Pick a course in the header's dropdown. */
const pickCourse = (code: string) => {
  fireEvent.click(screen.getAllByRole("button").find(b => b.getAttribute("aria-haspopup") === "listbox")!);
  fireEvent.click(screen.getByRole("option", { name: new RegExp(code) }));
};
const roadmapText = (text: string) => within(screen.getByLabelText("Roadmap")).queryByText(text);
/** A refresh that stays in flight until the test lands it. */
const pendingRefresh = () => {
  let land!: (topics: unknown[]) => void;
  vi.mocked(refreshTopicChecklist).mockReturnValue(
    new Promise(res => { land = topics => res({ topics, needs_refresh: false }); }) as never,
  );
  return (topics: unknown[]) => act(async () => { land(topics); });
};

describe("StudyHub generates the course's topic outline", () => {
  it("asks for it once when the read says it needs generating, and uses it when it lands", async () => {
    vi.mocked(getTopicChecklist).mockResolvedValue({ topics: [], needs_refresh: true } as never);
    const land = pendingRefresh();
    renderHub();
    // What the read returned shows first: the fallback columns.
    await hubLoaded();
    await waitFor(() => expect(roadmapText("Foundations")).toBeTruthy());
    await waitFor(() => expect(refreshTopicChecklist).toHaveBeenCalledTimes(1));
    expect(refreshTopicChecklist).toHaveBeenCalledWith("u1", "c1", undefined);
    expect(roadmapText("Programming Fundamentals")).toBeNull();
    await land(CATEGORISED);
    expect(roadmapText("Programming Fundamentals")).toBeTruthy();
    expect(roadmapText("Control Flow")).toBeTruthy();
    expect(roadmapText("Foundations")).toBeNull();
    expect(refreshTopicChecklist).toHaveBeenCalledTimes(1);
  });

  it("does not ask when the course's outline is current", async () => {
    vi.mocked(getTopicChecklist).mockResolvedValue({ topics: CATEGORISED, needs_refresh: false } as never);
    renderHub();
    await hubLoaded();
    await waitFor(() => expect(roadmapText("Programming Fundamentals")).toBeTruthy());
    expect(refreshTopicChecklist).not.toHaveBeenCalled();
  });

  it("does not ask when there is no outline and nothing to generate one from", async () => {
    // The beforeEach read: no topics, and `needs_refresh` false (no sources).
    renderHub();
    await hubLoaded();
    await waitFor(() => expect(roadmapText("Foundations")).toBeTruthy());
    expect(refreshTopicChecklist).not.toHaveBeenCalled();
  });

  it("a failed generation is silent, keeps what the read returned, and is not retried", async () => {
    vi.mocked(getTopicChecklist).mockResolvedValue({ topics: CATEGORISED, needs_refresh: true } as never);
    vi.mocked(refreshTopicChecklist).mockRejectedValue(
      Object.assign(new Error("Please wait before generating another checklist."), { status: 429 }),
    );
    renderHub({ courses: [COURSE, COURSE2] });
    await hubLoaded();
    await waitFor(() => expect(console.error).toHaveBeenCalledWith("study checklist refresh failed", expect.anything()));
    // The stale outline the read returned is still what the roadmap shows.
    expect(roadmapText("Programming Fundamentals")).toBeTruthy();
    expect(screen.getByTestId("readiness-pct").textContent).toBe("47%");
    // A toast is the only `status` once the skeleton is gone.
    expect(screen.queryByRole("status")).toBeNull();
    // The effect re-running (away and back) reads again but does not ask again.
    pickCourse("MA225");
    pickCourse("CS101");
    await waitFor(() => expect(vi.mocked(getTopicChecklist).mock.calls.map(c => c[1])).toEqual(["c1", "c2", "c1"]));
    await waitFor(() => expect(roadmapText("Programming Fundamentals")).toBeTruthy());
    expect(refreshTopicChecklist).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole("status")).toBeNull();
  });

  describe("across a course switch", () => {
    beforeEach(() => {
      // Only CS101 has an outline to generate. Calculus has two concepts of its own.
      vi.mocked(getTopicChecklist).mockImplementation(
        async (_u: string, cid: string) => ({ topics: [], needs_refresh: cid === "c1" }) as never,
      );
      vi.mocked(api.getGraph).mockResolvedValue({
        nodes: [
          node("var", "Variables", "mastered", 0.96),
          node("loop", "Loops", "learning", 0.6),
          { ...node("lim", "Limits", "learning", 0.5), course_id: "c2" },
          { ...node("der", "Derivatives", "unexplored", 0), course_id: "c2" },
        ],
        edges: [], stats: {},
      });
    });

    it("an outline that lands after the student left its course is not applied to the next one", async () => {
      const land = pendingRefresh();
      renderHub({ courses: [COURSE, COURSE2] });
      await waitFor(() => expect(refreshTopicChecklist).toHaveBeenCalledTimes(1));
      pickCourse("MA225");
      await screen.findByTestId("tile-lim");
      // Shaped so that it WOULD rename Calculus's columns if it were applied.
      await land([
        topic("leak", "Leaked Unit", null, null),
        topic("t-lim", "Limits", "leak", "lim"),
        topic("t-der", "Derivatives", "leak", "der"),
      ]);
      expect(roadmapText("Leaked Unit")).toBeNull();
      expect(roadmapText("Foundations")).toBeTruthy();
      expect(refreshTopicChecklist).toHaveBeenCalledTimes(1); // Calculus needed none
    });

    it("coming back while it is still generating picks up that attempt instead of starting another", async () => {
      const land = pendingRefresh();
      renderHub({ courses: [COURSE, COURSE2] });
      await waitFor(() => expect(refreshTopicChecklist).toHaveBeenCalledTimes(1));
      pickCourse("MA225");
      await screen.findByTestId("tile-lim");
      pickCourse("CS101");
      await screen.findByTestId("tile-var");
      await waitFor(() => expect(vi.mocked(getTopicChecklist).mock.calls.map(c => c[1])).toEqual(["c1", "c2", "c1"]));
      await land([
        topic("basics", "Basics", null, null),
        topic("t-var", "Variables", "basics", "var"),
        topic("t-loop", "Loops", "basics", "loop"),
      ]);
      await waitFor(() => expect(roadmapText("Basics")).toBeTruthy());
      expect(refreshTopicChecklist).toHaveBeenCalledTimes(1);
    });
  });
});

describe("StudyHub readiness follows the selected exam", () => {
  const squares = () => within(screen.getByLabelText("Readiness")).getByRole("img").querySelectorAll("button");
  const legend = () => ["Mastered", "Learning", "Struggling", "Not Started"]
    .map(l => screen.getByRole("button", { name: new RegExp(`^\\d+\\s*${l}$`) }).textContent);

  beforeEach(() => {
    // Loops gained 10 points this week; nothing else moved.
    vi.mocked(api.getGraph).mockResolvedValue({
      nodes: [
        node("var", "Variables", "mastered", 0.96),
        { ...node("loop", "Loops", "learning", 0.6), mastery_events: [{ delta: 0.1, created_at: new Date(2026, 10, 6).toISOString() }] },
        node("rec", "Recursion", "struggling", 0.3),
        node("arr", "Arrays", "unexplored", 0),
      ],
      edges: [
        { source: "var", target: "loop", relationship_type: "prerequisite" },
        { source: "loop", target: "rec", relationship_type: "prerequisite" },
      ],
      stats: {},
    });
  });

  it("an exam the outline links to concepts is measured on those concepts only", async () => {
    // Exam 2 is on Loops and Recursion (and on a topic the graph never matched).
    vi.mocked(getTopicChecklist).mockResolvedValue({ topics: [
      topic("fundamentals", "Programming Fundamentals", null, null),
      topic("control-flow", "Control Flow", null, null),
      topic("t-var", "Variables", "fundamentals", "var"),
      topic("t-arr", "Arrays", "fundamentals", "arr"),
      topic("t-loop", "Loops", "control-flow", "loop", ["e2"]),
      topic("t-rec", "Recursion", "control-flow", "rec", ["e2"]),
      topic("t-big-o", "Big-O", "control-flow", null, ["e2"]),
    ], needs_refresh: false } as never);
    renderHub();
    expect(await screen.findByText("Ready for Exam 2")).toBeTruthy();
    expect(screen.queryByText(COURSE_READINESS)).toBeNull();
    // mean of 60 and 30, not of all four (47)
    expect(screen.getByTestId("readiness-pct").textContent).toBe("45%");
    // 10 points over two concepts, not over four (+3%)
    expect(screen.getByText("+5% this week")).toBeTruthy();
    expect(squares()).toHaveLength(2);
    expect(legend()).toEqual(["0 Mastered", "1 Learning", "1 Struggling", "0 Not Started"]);

    // The rest of the page is still the whole course: all four concepts on the
    // roadmap, Up Next unchanged, and the legend still filters the roadmap.
    for (const id of ["var", "loop", "rec", "arr"]) expect(screen.getByTestId(`tile-${id}`)).toBeTruthy();
    expect(within(screen.getByTestId("focus-card")).getByText("Recursion")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: /^1\s*Learning$/ }));
    expect(screen.getByTestId("tile-loop").style.opacity).toBe("1");
    expect(screen.getByTestId("tile-var").style.opacity).toBe("0.3");

    // Quiz 3 has nothing linked: the course's number, under the course's name.
    fireEvent.click(screen.getByRole("tab", { name: /Quiz 3/ }));
    expect(screen.getByText(COURSE_READINESS)).toBeTruthy();
    expect(screen.queryByText(/^Ready for/)).toBeNull();
    expect(screen.getByTestId("readiness-pct").textContent).toBe("47%");
    expect(screen.getByText("+3% this week")).toBeTruthy();
    expect(squares()).toHaveLength(4);
    expect(legend()).toEqual(["1 Mastered", "1 Learning", "1 Struggling", "1 Not Started"]);
  });

  it("an exam with no linked concept shows the course's readiness under the course's name", async () => {
    // The outline exists, but only Quiz 3 has concepts; Exam 2's one topic
    // never matched a graph node.
    vi.mocked(getTopicChecklist).mockResolvedValue({ topics: [
      topic("t-loop", "Loops", null, "loop", ["q1"]),
      topic("t-big-o", "Big-O", null, null, ["e2"]),
    ], needs_refresh: false } as never);
    renderHub();
    expect(await hubLoaded()).toBeTruthy();
    expect(screen.getByRole("tab", { selected: true }).textContent).toBe("Exam 2Wed, Nov 18");
    expect(screen.queryByText("Ready for Exam 2")).toBeNull();
    expect(screen.getByTestId("readiness-pct").textContent).toBe("47%"); // mean of 96, 60, 30, 0
    expect(squares()).toHaveLength(4);
    expect(legend()).toEqual(["1 Mastered", "1 Learning", "1 Struggling", "1 Not Started"]);
  });
});

// @vitest-environment jsdom
/**
 * Milestones in the Tutor (`milestones`), against the Claude Design boards
 * (learn/__fixtures__/milestone.design.html, new-session.design.html,
 * sidebar.design.html): the Study hub's exams and their concept links, read
 * the Tutor's way. Words and structure, not pixels.
 */
import fs from "node:fs";
import path from "node:path";
import React from "react";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const { flags, api } = vi.hoisted(() => ({
  flags: {} as Record<string, string>,
  api: { all: vi.fn(), upcoming: vi.fn(), checklist: vi.fn(), guides: vi.fn() },
}));
vi.mock("@/context/FlagsContext", () => ({ useFlag: (k: string) => flags[k] ?? "off", useFlagMap: () => ({ flags, ready: true }) }));
vi.mock("@/context/UserContext", () => ({ useUser: () => ({ userId: "u1", userReady: true }) }));
vi.mock("@/lib/api", async (orig) => ({
  ...(await orig<typeof import("@/lib/api")>()),
  getAllAssignments: (...a: unknown[]) => api.all(...a), getUpcomingAssignments: (...a: unknown[]) => api.upcoming(...a),
}));
vi.mock("@/lib/topicChecklistApi", () => ({ getTopicChecklist: (...a: unknown[]) => api.checklist(...a) }));
vi.mock("@/lib/studyGuide/api", () => ({ listGuides: (...a: unknown[]) => api.guides(...a) }));
vi.mock("next/link", () => ({
  default: React.forwardRef<HTMLAnchorElement, React.AnchorHTMLAttributes<HTMLAnchorElement>>(function LinkStub(props, ref) {
    return <a ref={ref} {...props} />;
  }),
}));

import type { EnrolledCourse } from "@/lib/api";
import type { GraphNode } from "@/lib/data";
import { CourseSlot } from "./CourseV2";
import { MILESTONE_COPY, MilestonePage, levelBreakdown } from "./MilestonePage";
import { __resetMilestonesForTests, countdown, coveredConcepts, daysUntil, milestoneHeadline, milestonesOf, prepareGoal, readinessOf } from "./milestones";
import { NewSessionV2 } from "./NewSessionV2";
import { TutorSidebar } from "./TutorSidebar";

const read = (f: string) => fs.readFileSync(path.join(__dirname, "../__fixtures__", f), "utf8").replace(/&#39;|&rsquo;|’/g, "'");
const TODAY = new Date(2026, 10, 26, 12);
const iso = (days: number) => {
  const d = new Date(); d.setDate(d.getDate() + days);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
};
const node = (id: string, name: string, skill: number | null): GraphNode =>
  ({ id, name, mastery_score: skill ?? 0, mastery_tier: skill == null ? "unexplored" : skill >= 0.8 ? "mastered" : skill >= 0.3 ? "learning" : "struggling", skill } as unknown as GraphNode);
// Midterm 2 covers stacks (Proficient), hash tables (Developing), collisions (Getting started) and queues (not started)
const NODES = [node("st", "Stacks", 0.9), node("ht", "Hash tables", 0.5), node("cr", "Collision resolution", 0.2), node("q", "Queues", null)];
const COURSE = { course_id: "c1", course_code: "CS 112", course_name: "Introduction to Computer Science II" } as EnrolledCourse;
const ASSIGNMENTS = [
  { id: "mid", user_id: "u1", title: "Midterm 2", due_date: iso(13), assignment_type: "exam", course_id: "c1" },
  { id: "hw", user_id: "u1", title: "HW 7", due_date: iso(6), assignment_type: "homework", course_id: "c1" },
  { id: "old", user_id: "u1", title: "Midterm 1", due_date: iso(-20), assignment_type: "exam", course_id: "c1" },
  { id: "ma", user_id: "u1", title: "Exam 3", due_date: iso(20), assignment_type: "exam", course_id: "c2" },
];
const CHECKLIST = { topics: ["st", "ht", "cr", "q"].map((id) => ({ id: `t-${id}`, node_id: id, assessment_ids: ["mid"], assessments: [] })) };

beforeEach(() => {
  __resetMilestonesForTests();
  api.all.mockResolvedValue({ assignments: ASSIGNMENTS });
  api.upcoming.mockResolvedValue({ assignments: ASSIGNMENTS.filter((a) => a.id !== "old") });
  api.checklist.mockResolvedValue(CHECKLIST);
  api.guides.mockResolvedValue({ guides: [
    { id: "g1", title: "Midterm 2 guide", course_id: "c1", scope_kind: "exam", scope_label: "Midterm 2" },
    { id: "g2", title: "Course guide", course_id: "c1", scope_kind: "course", scope_label: "CS 112" },
  ] });
});
afterEach(() => {
  cleanup();
  vi.clearAllMocks();
  for (const k of Object.keys(flags)) delete flags[k];
});

describe("the milestone model", () => {
  it("every course's dated work still ahead, soonest first, with its countdown", () => {
    const ms = milestonesOf(ASSIGNMENTS as never, new Date());
    expect(ms.map((m) => [m.id, m.courseId, m.type, m.days])).toEqual([["hw", "c1", "Homework", 6], ["mid", "c1", "Exam", 13], ["ma", "c2", "Exam", 20]]);
    expect(daysUntil("2026-12-09", TODAY)).toBe(13);
    expect([countdown(0), countdown(1), countdown(13)]).toEqual(["Today", "Tomorrow", "13 days"]);
    expect(milestoneHeadline({ title: "Midterm 2", days: 13 })).toBe("Midterm 2 in 13 days");
    expect(milestoneHeadline({ title: "Midterm 2", days: 1 })).toBe("Midterm 2 is tomorrow");
  });

  it("readiness: Proficient is exam-ready; the levels present, high to low", () => {
    const covered = coveredConcepts(["st", "ht", "cr", "q", "gone"], NODES);
    expect(covered.map((c) => [c.id, c.level, c.ready])).toEqual([
      ["st", "profic", true], ["ht", "develop", false], ["cr", "novice", false], ["q", "not_started", false],
    ]);
    const r = readinessOf(covered);
    expect([r.ready, r.total]).toEqual([1, 4]);
    expect(levelBreakdown(r.counts)).toBe("1 Proficient, 1 Developing, 1 Getting started, 1 Not started");
  });

  it("Prepare: a goal on the concepts not ready yet, weakest first, within the goal's cap; none when all are ready", () => {
    const covered = coveredConcepts(["st", "ht", "cr", "q"], NODES);
    expect(prepareGoal({ title: "Midterm 2" }, covered)).toEqual({
      topic: "Prepare for Midterm 2", goal: { text: "Prepare for Midterm 2", target_node_ids: ["q", "cr", "ht"] },
    });
    expect(prepareGoal({ title: "Midterm 2" }, coveredConcepts(["st"], NODES))).toBeNull();
    const many = Array.from({ length: 20 }, (_, i) => node(`n${i}`, `N${i}`, 0.1));
    expect(prepareGoal({ title: "Final" }, coveredConcepts(many.map((n) => n.id), many))!.goal.target_node_ids).toHaveLength(12);
  });
});

describe("parity with the design boards", () => {
  it.each([
    ["milestone.design.html", MILESTONE_COPY.prepare], ["milestone.design.html", MILESTONE_COPY.covers],
    ["milestone.design.html", MILESTONE_COPY.sessions("Midterm 2")], ["milestone.design.html", MILESTONE_COPY.saved("Midterm 2")],
    ["milestone.design.html", MILESTONE_COPY.ready(3, 8)], ["sidebar.design.html", countdown(13)],
    ["new-session.design.html", "Prepare for Midterm 2"], ["new-session.design.html", "Start preparing"],
  ])("%s says %j", (file, text) => {
    expect(read(file)).toContain(text);
  });
});

describe("the milestone page", () => {
  const props = (over: Partial<React.ComponentProps<typeof MilestonePage>> = {}) => ({
    course: COURSE, milestone: { id: "mid", courseId: "c1", title: "Midterm 2", iso: iso(13), days: 13, type: "Exam" as const },
    conceptIds: ["st", "ht", "cr", "q"], nodes: NODES,
    sessions: [{ id: "s1", topic: "Prepare for Midterm 2", courseId: "c1", startedAt: new Date().toISOString(), open: true },
      { id: "s2", topic: "Recursion", courseId: "c1", startedAt: new Date().toISOString(), open: false }],
    onBack: vi.fn(), onOpen: vi.fn(), onLearn: vi.fn(), onStartGoal: vi.fn(), ...over,
  });

  it("the headline takes focus; how many are ready, what it covers, its sessions and saved guides; Prepare starts the goal", async () => {
    const p = props();
    render(<MilestonePage {...p} />);
    expect(screen.getByRole("heading", { name: "Midterm 2 in 13 days" })).toHaveFocus();
    expect(screen.getByRole("heading", { name: "1 of 4 concepts are exam-ready" })).toBeTruthy();
    expect(screen.getByTestId("tutor-milestone-levels").textContent).toBe("1 Proficient, 1 Developing, 1 Getting started, 1 Not started");
    expect(screen.getByTestId("tutor-milestone-concept-q").getAttribute("data-level")).toBe("not_started");
    const sessions = screen.getByRole("heading", { name: "Sessions for Midterm 2" }).parentElement!;
    expect(within(sessions).getAllByRole("button").map((b) => b.textContent)).toEqual([expect.stringContaining("Prepare for Midterm 2")]);
    expect(await screen.findByTestId("tutor-milestone-guide-g1")).toBeTruthy();
    expect(screen.queryByTestId("tutor-milestone-guide-g2")).toBeNull(); // the course's guide, not the exam's
    fireEvent.click(screen.getByTestId("tutor-milestone-prepare"));
    expect(p.onStartGoal).toHaveBeenCalledWith("Prepare for Midterm 2", { text: "Prepare for Midterm 2", target_node_ids: ["q", "cr", "ht"] });
    fireEvent.click(screen.getByTestId("tutor-milestone-back"));
    expect(p.onBack).toHaveBeenCalled();
  });

  it("nothing linked to it: says so, and Prepare waits", () => {
    render(<MilestonePage {...props({ conceptIds: [] })} />);
    expect(screen.getByTestId("tutor-milestone-unlinked").textContent).toBe("No topics are linked to Midterm 2 yet.");
    expect((screen.getByTestId("tutor-milestone-prepare") as HTMLButtonElement).disabled).toBe(true);
  });
});

describe("where milestones show (milestones on)", () => {
  const slot = (over: Partial<React.ComponentProps<typeof CourseSlot>> = {}) => (
    <CourseSlot course={COURSE} sessions={[]} concepts={NODES} edges={[]} materials={[]} retentionDue={false} dueCount={0}
      dueHref={null} libraryHref={null} onOpen={() => {}} onAll={() => {}} onLearn={() => {}}
      onMilestone={vi.fn()} onStartGoal={vi.fn()} {...over} />
  );

  it("the course page's Coming up: each row says how ready and opens its milestone", async () => {
    flags.course_page_v2 = "on";
    flags.milestones = "on";
    const onMilestone = vi.fn();
    render(slot({ onMilestone }));
    expect((await screen.findByTestId("tutor-course-due-ready-mid")).textContent).toBe("1 of 4 ready");
    fireEvent.click(within(screen.getByTestId("tutor-course-due-mid")).getByRole("button"));
    expect(onMilestone).toHaveBeenCalledWith("mid");
  });

  it("a milestone picked: its page, in the course view", async () => {
    flags.milestones = "on";
    render(slot({ milestoneId: "mid" }));
    expect(await screen.findByRole("heading", { name: "Midterm 2 in 13 days" })).toBeTruthy();
  });

  it("milestones off: the course page, whatever is picked", () => {
    flags.course_page_v2 = "on";
    render(slot({ milestoneId: "mid" }));
    expect(screen.getByTestId("tutor-course-v2")).toBeTruthy();
    expect(api.all).not.toHaveBeenCalled();
  });

  it("the sidebar: a course's next dated work within a month, under it, with its countdown", async () => {
    flags.milestones = "on";
    const onMilestone = vi.fn();
    render(<TutorSidebar courses={[COURSE, { course_id: "c2", course_code: "MA 242", course_name: "Linear Algebra" } as EnrolledCourse]}
      courseId="c1" sessions={[]} currentSessionId={null} currentCourseView={null} query="" setQuery={() => {}} newDisabled={false}
      showNew onNew={() => {}} onCourse={() => {}} onOpen={() => {}} onAll={() => {}} onHide={() => {}} onMilestone={onMilestone} />);
    const mid = await screen.findByTestId("tutor-milestone-mid");
    expect(mid.textContent).toBe("Midterm 213 days");
    expect(screen.getByTestId("tutor-milestone-hw").textContent).toBe("HW 76 days");
    expect(screen.getByTestId("tutor-milestone-ma").textContent).toBe("Exam 320 days");
    expect(screen.queryByTestId("tutor-milestone-old")).toBeNull(); // already sat
    fireEvent.click(mid);
    expect(onMilestone).toHaveBeenCalledWith("c1", "mid");
  });

  it("New session: Prepare for the next exam with concepts linked, picked first; it starts the goal", async () => {
    flags.milestones = "on";
    const onStartGoal = vi.fn();
    render(<NewSessionV2 courseName="CS 112" continueTitle={null} startWith={null} dueCount={0} dueHref={null} busy={false}
      starting={false} closesCurrent={null} onContinue={() => {}} onStart={() => {}} onStartWith={() => {}} onGoal={() => {}}
      courseId="c1" nodes={NODES} onStartGoal={onStartGoal} />);
    const prepare = await screen.findByRole("radio", { name: /Prepare for Midterm 2/ });
    expect(prepare).toBeChecked();
    expect(screen.getByTestId("tutor-new-intent-prepare").textContent).toContain("4 concepts. Starts with a short check-in.");
    fireEvent.click(screen.getByTestId("loop-start-guided"));
    expect(onStartGoal).toHaveBeenCalledWith("Prepare for Midterm 2", { text: "Prepare for Midterm 2", target_node_ids: ["q", "cr", "ht"] });
    await waitFor(() => expect(screen.getByTestId("loop-start-guided").textContent).toBe("Start preparing"));
  });
});

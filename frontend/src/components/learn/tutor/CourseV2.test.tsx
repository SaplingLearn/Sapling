// @vitest-environment jsdom
/**
 * The Tutor's course page, rebuilt (Tutor redesign phase 4, `course_page_v2`)
 * against its design board, `../__fixtures__/course.design.html`, kept
 * verbatim (words and structure, not pixels). The board's readiness bars on
 * Coming up, its review minutes and its Library column are not built.
 */
import fs from "node:fs";
import path from "node:path";
import React from "react";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const flags: Record<string, string> = {};
const upcoming = vi.fn();
const cards = vi.fn();
const guides = vi.fn();
vi.mock("@/context/FlagsContext", () => ({ useFlag: (k: string) => flags[k] ?? "off" }));
vi.mock("@/context/UserContext", () => ({ useUser: () => ({ userId: "u1", userReady: true }) }));
vi.mock("@/lib/api", async (orig) => ({ ...(await orig<typeof import("@/lib/api")>()),
  getUpcomingAssignments: (...a: unknown[]) => upcoming(...a), getFlashcards: (...a: unknown[]) => cards(...a) }));
vi.mock("@/lib/studyGuide/api", () => ({ listGuides: (...a: unknown[]) => guides(...a) }));
vi.mock("next/link", () => ({
  default: React.forwardRef<HTMLAnchorElement, React.AnchorHTMLAttributes<HTMLAnchorElement>>(function LinkStub(props, ref) {
    return <a ref={ref} {...props} />;
  }),
}));

import type { EnrolledCourse } from "@/lib/api";
import type { GraphEdge, GraphNode } from "@/lib/data";
import { COURSE_COPY, CourseSlot, dueWhen, readyConcepts } from "./CourseV2";

const DESIGN = fs.readFileSync(path.join(__dirname, "../__fixtures__/course.design.html"), "utf8").replace(/&#39;|&rsquo;|’/g, "'");
const node = (id: string, name: string, skill: number | null): GraphNode =>
  ({ id, name, mastery_score: skill ?? 0, mastery_tier: skill == null ? "unexplored" : skill >= 0.8 ? "mastered" : skill >= 0.3 ? "learning" : "struggling", skill } as unknown as GraphNode);
const prereq = (source: string, target: string): GraphEdge => ({ source, target, strength: 1, relationship_type: "prerequisite" });
// Arrays is proficient; Stacks and Queues build on it; Hash tables builds on
// Stacks (still developing), so it is not ready; Trees has no prerequisite.
const NODES = [node("ar", "Arrays", 0.9), node("st", "Stacks", 0.44), node("q", "Queues", 0.31), node("ht", "Hash tables", 0.22), node("tr", "Trees", null)];
const EDGES = [prereq("ar", "st"), prereq("ar", "q"), prereq("st", "ht"), { source: "ar", target: "tr", strength: 1, relationship_type: "related" as const }];
const COURSE = { course_id: "c1", course_name: "Introduction to Computer Science II", course_code: "CS 112" } as EnrolledCourse;
const NOW = new Date(2026, 10, 26, 12);

beforeEach(() => {
  cards.mockResolvedValue({ flashcards: [] });
  guides.mockResolvedValue({ guides: [] });
  upcoming.mockReset();
  upcoming.mockResolvedValue({ assignments: [
    { id: "a2", user_id: "u1", title: "Midterm 2", due_date: "2026-12-09", course_id: "c1" },
    { id: "a1", user_id: "u1", title: "HW 7", due_date: "2026-12-02", course_id: "c1" },
    { id: "a0", user_id: "u1", title: "HW 6", due_date: "2026-11-20", course_id: "c1" }, // past
    { id: "b1", user_id: "u1", title: "MA Exam 3", due_date: "2026-12-01", course_id: "c2" }, // another course
  ] });
});
afterEach(() => {
  cleanup();
  vi.useRealTimers();
  for (const k of Object.keys(flags)) delete flags[k];
});

function renderCourse(over: Partial<React.ComponentProps<typeof CourseSlot>> = {}) {
  const onLearn = vi.fn();
  render(
    <CourseSlot course={COURSE} sessions={[]} concepts={NODES} edges={EDGES} materials={[{ id: "m1", file_name: "Lecture 14: Hashing" }]}
      retentionDue={false} dueCount={7} dueHref="/study" libraryHref="/library" onOpen={() => {}} onAll={() => {}} onLearn={onLearn} {...over} />,
  );
  return { onLearn };
}

describe("what the page says", () => {
  it("ready to learn: below Proficient, every direct prerequisite Proficient, strongest first", () => {
    expect(readyConcepts(NODES, EDGES).map((c) => [c.name, c.hasPrereqs])).toEqual([["Stacks", true], ["Queues", true], ["Trees", false]]);
    // a prerequisite cycle hides both rather than vouching for either
    expect(readyConcepts([node("a", "A", 0.2), node("b", "B", 0.2)], [prereq("a", "b"), prereq("b", "a")])).toEqual([]);
  });

  it("a due date reads as its day and how far off it is; a past one is not coming up", () => {
    expect(dueWhen("2026-12-02", NOW)).toMatch(/, in 6 days$/);
    expect(dueWhen("2026-11-27", NOW)).toMatch(/, tomorrow$/);
    expect(dueWhen("2026-11-26", NOW)).toMatch(/, today$/);
    expect(dueWhen("2026-11-20", NOW)).toBeNull();
    expect(dueWhen(null, NOW)).toBeNull();
  });
});

describe("parity with the design board", () => {
  it.each([COURSE_COPY.ready, COURSE_COPY.readyLine, COURSE_COPY.sessions, COURSE_COPY.allSessions, COURSE_COPY.comingUp,
    COURSE_COPY.materials, COURSE_COPY.upload, COURSE_COPY.open, COURSE_COPY.learn, "Review", "Developing", "Getting started"])("the board says %j", (text) => {
    expect(DESIGN).toContain(text);
  });

  it("course_page_v2 on: ready concepts with level and Learn, the course's upcoming work soonest first", async () => {
    flags.course_page_v2 = "on";
    const { onLearn } = renderCourse();
    expect(screen.getByRole("heading", { name: COURSE_COPY.ready })).toHaveFocus(); // A135
    const ready = screen.getByRole("heading", { name: COURSE_COPY.ready }).parentElement!;
    expect(within(ready).getAllByRole("listitem").map((li) => li.getAttribute("data-testid"))).toEqual(
      ["tutor-course-ready-st", "tutor-course-ready-q", "tutor-course-ready-tr"]);
    expect(within(ready).queryByText(COURSE_COPY.readyLine)).toBeNull(); // Trees has no prerequisite to vouch for
    fireEvent.click(screen.getByRole("button", { name: "Learn Stacks" }));
    expect(onLearn).toHaveBeenCalledWith({ id: "st", name: "Stacks" });
    await waitFor(() => expect(screen.getByTestId("tutor-course-due-a1")).toBeTruthy());
    const coming = screen.getByRole("heading", { name: COURSE_COPY.comingUp }).parentElement!;
    expect(within(coming).getAllByRole("listitem").map((li) => li.getAttribute("data-testid"))).toEqual(["tutor-course-due-a1", "tutor-course-due-a2"]);
    expect(screen.getByTestId("tutor-course-review").textContent).toContain("7 reviews due");
  });

  it("the review note steps aside for the sidebar's Review (session_v2); a retention check due here takes the note", async () => {
    flags.course_page_v2 = "on";
    flags.session_v2 = "on";
    renderCourse();
    expect(screen.queryByTestId("tutor-course-review")).toBeNull();
    cleanup();
    renderCourse({ retentionDue: true });
    expect(screen.getByTestId("tutor-course-retention").textContent).toContain("A retention check is ready for this course.");
    expect(screen.getByRole("link", { name: COURSE_COPY.startCheck }).getAttribute("href")).toBe("/study?retention-course=c1");
    await waitFor(() => expect(upcoming).toHaveBeenCalled());
  });

  it("a failed upcoming read says so, with a retry, never its empty line", async () => {
    flags.course_page_v2 = "on";
    upcoming.mockRejectedValueOnce(new Error("down"));
    renderCourse();
    expect(await screen.findByTestId("tutor-course-upcoming-error")).toBeTruthy();
    expect(screen.queryByText(COURSE_COPY.nothingUp)).toBeNull();
  });

  it("course_page_v2 off: the page as before", () => {
    renderCourse();
    expect(screen.getByTestId("tutor-course-page")).toBeTruthy();
    expect(screen.queryByTestId("tutor-course-v2")).toBeNull();
    expect(upcoming).not.toHaveBeenCalled();
  });

  it("the Library: the course's study guides and how many flashcards it has, from Study's reads", async () => {
    flags.course_page_v2 = "on";
    guides.mockResolvedValue({ guides: [
      { id: "g1", title: "Midterm 2 guide", course_id: "c1" }, { id: "g9", title: "Other course", course_id: "c2" },
    ] });
    cards.mockResolvedValue({ flashcards: [{ id: "f1", course_id: "c1" }, { id: "f2", course_id: "c1" }, { id: "f3", course_id: "c2" }] });
    renderCourse();
    const lib = await screen.findByTestId("tutor-course-library");
    expect(within(lib).getByTestId("tutor-course-guide-g1").getAttribute("href")).toBe("/study/guide/g1");
    expect(within(lib).queryByText("Other course")).toBeNull();
    expect(within(lib).getByTestId("tutor-course-flashcards").getAttribute("href")).toBe("/flashcards?course=c1");
    expect(lib.textContent).toContain("2 cards");
  });

  it("an empty Library, or Study hidden: no Library", async () => {
    flags.course_page_v2 = "on";
    renderCourse();
    await waitFor(() => expect(guides).toHaveBeenCalled());
    expect(screen.queryByTestId("tutor-course-library")).toBeNull();
    cleanup();
    guides.mockClear();
    flags.hide_study = "on";
    renderCourse();
    expect(guides).not.toHaveBeenCalled();
  });
});

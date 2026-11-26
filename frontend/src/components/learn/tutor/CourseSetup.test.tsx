// @vitest-environment jsdom
/**
 * Course setup (Tutor redesign, `course_setup`) against its design board,
 * `../__fixtures__/setup.design.html`, kept verbatim (words and structure,
 * not pixels): the steps, the review's two parts (the exams and assignments
 * with a date each, the concepts each ticked) and Confirm. Confirm writes only
 * the changes: the upload already put the syllabus's dates on the calendar.
 */
import fs from "node:fs";
import path from "node:path";
import React from "react";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const { flags, api } = vi.hoisted(() => ({
  flags: {} as Record<string, string>,
  api: {
    uploadSyllabus: vi.fn(), getAllAssignments: vi.fn(), deleteAssignment: vi.fn(), updateAssignment: vi.fn(),
    saveAssignments: vi.fn(), fetchJSON: vi.fn(), getUpcomingAssignments: vi.fn(), getFlashcards: vi.fn(),
  },
}));
vi.mock("@/context/FlagsContext", () => ({ useFlag: (k: string) => flags[k] ?? "off" }));
vi.mock("@/context/UserContext", () => ({ useUser: () => ({ userId: "u1", userReady: true }) }));
vi.mock("@/lib/api", async (orig) => ({
  ...(await orig<typeof import("@/lib/api")>()),
  ...Object.fromEntries(Object.entries(api).map(([k, fn]) => [k, (...a: unknown[]) => fn(...a)])),
}));
vi.mock("@/lib/studyGuide/api", () => ({ listGuides: async () => ({ guides: [] }) }));
vi.mock("next/link", () => ({
  default: React.forwardRef<HTMLAnchorElement, React.AnchorHTMLAttributes<HTMLAnchorElement>>(function LinkStub(props, ref) {
    return <a ref={ref} {...props} />;
  }),
}));

import type { EnrolledCourse } from "@/lib/api";
import type { GraphNode } from "@/lib/data";
import { CourseSetup, SETUP_COPY } from "./CourseSetup";
import { CourseSlot } from "./CourseV2";

const BOARD = fs.readFileSync(path.join(__dirname, "../__fixtures__/setup.design.html"), "utf8").replace(/&#39;|&rsquo;|’/g, "'");
const COURSE = { course_id: "c1", course_name: "Introduction to Computer Science II", course_code: "CS 112" } as EnrolledCourse;
const node = (id: string, name: string, tier: GraphNode["mastery_tier"] = "unexplored") =>
  ({ id, name, course_id: "c1", mastery_tier: tier, mastery_score: tier === "unexplored" ? 0 : 0.5 } as GraphNode);
const NODES = [node("ar", "Arrays", "learning"), node("tr", "Tries"), node("bs", "Binary search trees")];

beforeEach(() => {
  api.uploadSyllabus.mockResolvedValue({ id: "d1", category: "syllabus", summary: null, categories: [], assignments: [] });
  api.getAllAssignments.mockResolvedValue({ assignments: [
    { id: "a1", user_id: "u1", title: "Midterm 1", due_date: "2026-10-21", course_id: "c1", assignment_type: "exam" },
    { id: "a2", user_id: "u1", title: "HW 7", due_date: "2026-12-02", course_id: "c1", assignment_type: "homework" },
    { id: "b1", user_id: "u1", title: "MA Exam 3", due_date: "2026-12-01", course_id: "c2", assignment_type: "exam" },
  ] });
  api.deleteAssignment.mockResolvedValue({ deleted: true });
  api.updateAssignment.mockResolvedValue({ updated: true });
  api.saveAssignments.mockResolvedValue({ saved_count: 1 });
  api.fetchJSON.mockResolvedValue({ removed: ["tr"], kept: [] });
  api.getUpcomingAssignments.mockResolvedValue({ assignments: [] });
  api.getFlashcards.mockResolvedValue({ flashcards: [] });
});
afterEach(() => {
  cleanup();
  vi.clearAllMocks();
  for (const k of Object.keys(flags)) delete flags[k];
});

function renderSetup() {
  const props = { onClose: vi.fn(), onStart: vi.fn(), onConceptsChanged: vi.fn(async () => {}) };
  render(<CourseSetup course={COURSE} concepts={NODES} hasMaterials {...props} />);
  return props;
}

const upload = async () => {
  const file = new File(["syllabus"], "cs112.pdf", { type: "application/pdf" });
  await act(async () => { fireEvent.change(screen.getByTestId("tutor-setup-file"), { target: { files: [file] } }); });
  return file;
};

describe("the board", () => {
  it("says what the board says", () => {
    for (const s of [
      SETUP_COPY.found("CS 112"), SETUP_COPY.dates, SETUP_COPY.datesLine, SETUP_COPY.concepts(18),
      SETUP_COPY.conceptsLine, SETUP_COPY.practice, SETUP_COPY.confirm, SETUP_COPY.addDate, SETUP_COPY.remove,
      SETUP_COPY.stepsLabel, ...SETUP_COPY.steps,
    ]) expect(BOARD, s).toContain(s);
  });
});

describe("the setup", () => {
  it("uploads the syllabus, then reviews what it found; Confirm writes only the changes", async () => {
    const props = renderSetup();
    expect(document.activeElement?.textContent).toBe(SETUP_COPY.uploadTitle("CS 112"));
    const steps = screen.getByTestId("tutor-setup-steps");
    expect(within(steps).getByText("Syllabus").closest("li")!.getAttribute("aria-current")).toBe("step");
    const file = await upload();
    expect(api.uploadSyllabus).toHaveBeenCalledWith({ userId: "u1", courseId: "c1", file });
    expect(props.onConceptsChanged).toHaveBeenCalledTimes(1);
    await waitFor(() => expect(document.activeElement?.textContent).toBe(SETUP_COPY.found("CS 112")));
    expect(within(steps).getByText("Review").closest("li")!.getAttribute("aria-current")).toBe("step");
    expect(within(steps).getByText("Syllabus").closest("li")!.textContent).toContain(`(${SETUP_COPY.done})`);

    // The course's dated work only, each a labelled date.
    await screen.findByTestId("tutor-setup-row-a1");
    expect(screen.queryByTestId("tutor-setup-row-b1")).toBeNull();
    const midterm = screen.getByLabelText("Midterm 1") as HTMLInputElement;
    expect(midterm.value).toBe("2026-10-21");
    fireEvent.change(midterm, { target: { value: "2026-10-23" } });
    fireEvent.click(screen.getByRole("button", { name: "Remove HW 7" }));
    await waitFor(() => expect(document.activeElement).toBe(screen.getByTestId("tutor-setup-add-date")));
    fireEvent.click(screen.getByTestId("tutor-setup-add-date"));
    const name = await waitFor(() => {
      const el = document.activeElement as HTMLInputElement;
      expect(el.getAttribute("aria-label")).toBe(SETUP_COPY.name);
      return el;
    });
    fireEvent.change(name, { target: { value: "HW 8" } });
    const newDate = screen.getByLabelText(SETUP_COPY.date("HW 8")) as HTMLInputElement;
    fireEvent.change(newDate, { target: { value: "2026-12-09" } });

    // Concepts: every one ticked; a started one cannot be unticked.
    expect(screen.getByRole("heading", { name: SETUP_COPY.concepts(3) })).toBeTruthy();
    const arrays = within(screen.getByTestId("tutor-setup-concept-ar")).getByRole("checkbox") as HTMLInputElement;
    expect(arrays.checked && arrays.disabled).toBe(true);
    expect(screen.getByText(SETUP_COPY.startedStay)).toBeTruthy();
    fireEvent.click(within(screen.getByTestId("tutor-setup-concept-tr")).getByRole("checkbox"));
    expect(screen.getByRole("heading", { name: SETUP_COPY.concepts(2) })).toBeTruthy();

    await act(async () => { fireEvent.click(screen.getByTestId("tutor-setup-confirm")); });
    await screen.findByTestId("tutor-setup-done");
    expect(api.deleteAssignment).toHaveBeenCalledWith("a2", "u1");
    expect(api.updateAssignment).toHaveBeenCalledWith("a1", "u1", { due_date: "2026-10-23" });
    expect(api.saveAssignments).toHaveBeenCalledWith("u1", [{ title: "HW 8", due_date: "2026-12-09", assignment_type: "homework", course_id: "c1" }]);
    const exclude = api.fetchJSON.mock.calls.find((c) => c[0] === "/api/learn/setup/exclude-concepts")!;
    expect(JSON.parse(exclude[1].body)).toEqual({ user_id: "u1", course_id: "c1", node_ids: ["tr"] });
    expect(props.onConceptsChanged).toHaveBeenCalledTimes(2);
    expect(document.activeElement?.textContent).toBe(SETUP_COPY.doneTitle("CS 112"));
    expect(screen.getByTestId("tutor-setup-done").textContent).toContain(SETUP_COPY.doneLine(2, 2));
    fireEvent.click(screen.getByTestId("tutor-setup-start"));
    expect(props.onStart).toHaveBeenCalled();
  });

  it("skipping the upload reviews what is there; no change, no write", async () => {
    renderSetup();
    fireEvent.click(screen.getByTestId("tutor-setup-skip"));
    await waitFor(() => expect(document.activeElement?.textContent).toBe(SETUP_COPY.review("CS 112")));
    await screen.findByTestId("tutor-setup-row-a1");
    await act(async () => { fireEvent.click(screen.getByTestId("tutor-setup-confirm")); });
    await screen.findByTestId("tutor-setup-done");
    expect(api.uploadSyllabus).not.toHaveBeenCalled();
    expect(api.deleteAssignment).not.toHaveBeenCalled();
    expect(api.updateAssignment).not.toHaveBeenCalled();
    expect(api.saveAssignments).not.toHaveBeenCalled();
    expect(api.fetchJSON).not.toHaveBeenCalled();
  });

  it("a failed upload says so and stays on the syllabus step", async () => {
    api.uploadSyllabus.mockRejectedValue(new Error("boom"));
    renderSetup();
    await upload();
    expect((await screen.findByTestId("tutor-setup-error")).getAttribute("role")).toBe("alert");
    expect(screen.getByTestId("tutor-setup").getAttribute("data-step")).toBe("syllabus");
  });

  it("a concept write that fails can be retried without writing the dates twice", async () => {
    api.fetchJSON.mockRejectedValueOnce(new Error("down"));
    renderSetup();
    fireEvent.click(screen.getByTestId("tutor-setup-skip"));
    await screen.findByTestId("tutor-setup-row-a1");
    fireEvent.click(screen.getByRole("button", { name: "Remove HW 7" }));
    fireEvent.click(within(screen.getByTestId("tutor-setup-concept-tr")).getByRole("checkbox"));
    await act(async () => { fireEvent.click(screen.getByTestId("tutor-setup-confirm")); });
    expect(await screen.findByTestId("tutor-setup-error")).toBeTruthy();
    await act(async () => { fireEvent.click(screen.getByTestId("tutor-setup-confirm")); });
    await screen.findByTestId("tutor-setup-done");
    expect(api.deleteAssignment).toHaveBeenCalledTimes(1);
    expect(api.fetchJSON).toHaveBeenCalledTimes(2);
  });
});

describe("the course page's way in", () => {
  const slot = (over: Partial<React.ComponentProps<typeof CourseSlot>> = {}) => render(
    <CourseSlot course={COURSE} sessions={[]} concepts={NODES} edges={[]} materials={[]} retentionDue={false} dueCount={0}
      dueHref={null} libraryHref={null} onOpen={() => {}} onAll={() => {}} onLearn={() => {}}
      onStartCourse={() => {}} onConceptsChanged={async () => {}} {...over} />,
  );

  it("course_setup off: no way in", () => {
    flags.course_page_v2 = "on";
    slot();
    expect(screen.queryByTestId("tutor-course-setup")).toBeNull();
  });

  it("course_setup on: Coming up opens the setup, and its back link returns", async () => {
    flags.course_page_v2 = "on";
    flags.course_setup = "on";
    slot();
    fireEvent.click(screen.getByTestId("tutor-course-setup"));
    expect(screen.getByTestId("tutor-setup")).toBeTruthy();
    fireEvent.click(screen.getByTestId("tutor-setup-back"));
    expect(await screen.findByTestId("tutor-course-v2")).toBeTruthy();
  });
});

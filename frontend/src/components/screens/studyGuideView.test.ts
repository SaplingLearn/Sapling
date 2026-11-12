import { describe, it, expect } from "vitest";
import {
  examGoneBody,
  examPickerPlaceholder,
  guideLoadProblem,
  isOpenGuide,
  loadTerm,
  noExamsBody,
  stepNumberColor,
} from "./studyGuideView";

describe("stepNumberColor", () => {
  it("lights the step once it has a value, whatever the prerequisite", () => {
    expect(stepNumberColor("c1", "")).toBe("var(--accent)");
    expect(stepNumberColor("e1", "c1")).toBe("var(--accent)");
  });

  it("dims a step whose prerequisite is done", () => {
    expect(stepNumberColor("", "c1")).toBe("var(--text-dim)");
  });

  it("mutes a step with neither", () => {
    expect(stepNumberColor("", "")).toBe("var(--text-muted)");
  });
});

describe("examPickerPlaceholder", () => {
  it("says Loading… while the exams load, course or not", () => {
    expect(examPickerPlaceholder(true, "c1")).toBe("Loading…");
    expect(examPickerPlaceholder(true, "")).toBe("Loading…");
  });

  it("asks for an exam once a course is picked", () => {
    expect(examPickerPlaceholder(false, "c1")).toBe("Pick an exam…");
  });

  it("asks for a course first otherwise", () => {
    expect(examPickerPlaceholder(false, "")).toBe("Select a course first");
  });
});

describe("isOpenGuide", () => {
  const entry = { course_id: "c1", exam_id: "e1" };

  it("matches only when both course and exam match", () => {
    expect(isOpenGuide(entry, "c1", "e1")).toBe(true);
    expect(isOpenGuide(entry, "c1", "e2")).toBe(false);
    expect(isOpenGuide(entry, "c2", "e1")).toBe(false);
    expect(isOpenGuide(entry, "", "")).toBe(false);
  });
});

describe("guideLoadProblem", () => {
  const load = { courseId: "c1", examId: "e1", semester: "Fall 2025" };
  const http = (status: number, detail: string) => Object.assign(new Error(JSON.stringify({ detail })), { status });

  it("a deleted exam (or a 404 that says nothing) is plainly missing", () => {
    expect(guideLoadProblem(http(404, "Exam not found. It may have been deleted — pick another exam."), load)).toEqual({ kind: "missing" });
    expect(guideLoadProblem(Object.assign(new Error(""), { status: 404 }), load)).toEqual({ kind: "missing" });
  });

  it("any other 404 carries the server's sentence (#475 F4)", () => {
    expect(guideLoadProblem(http(404, "No offering of this course in that semester."), load))
      .toEqual({ kind: "missing", message: "No offering of this course in that semester." });
  });

  it("anything else failed, and remembers the load to replay", () => {
    const problem = guideLoadProblem(http(502, "Study guide generation failed."), load);
    expect(problem).toMatchObject({ kind: "failed", ...load });
    expect(problem.message).toBeTruthy();
  });
});

describe("loadTerm", () => {
  it("follows the active selector when the load has no term of its own", () => {
    expect(loadTerm(undefined, "Fall 2025")).toBe("Fall 2025");
    expect(loadTerm(undefined, "")).toBeUndefined();
  });

  it("an override wins, and an empty one means unscoped", () => {
    expect(loadTerm("Spring 2026", "Fall 2025")).toBe("Spring 2026");
    expect(loadTerm("", "Fall 2025")).toBeUndefined();
  });
});

describe("where an exam is added", () => {
  it("is the Calendar page, as before", () => {
    expect(noExamsBody(false)).toBe("Study guides are built one exam at a time. Import a syllabus on the Calendar page, or add an assignment with type = Exam, and it'll show up here.");
    expect(examGoneBody(false)).toBe("It was probably deleted. Pick another exam above, or add one on the Calendar page to build a guide for it.");
  });

  it("is the Study hub when the Calendar is hidden from this student", () => {
    for (const body of [noExamsBody(true), examGoneBody(true)]) {
      expect(body).not.toMatch(/Calendar/);
      expect(body).toMatch(/Add Exam or Deadline.* on the Study page/);
    }
  });
});

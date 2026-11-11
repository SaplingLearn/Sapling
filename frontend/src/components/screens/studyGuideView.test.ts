import { describe, it, expect } from "vitest";
import { examPickerPlaceholder, isOpenGuide, stepNumberColor } from "./studyGuideView";

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

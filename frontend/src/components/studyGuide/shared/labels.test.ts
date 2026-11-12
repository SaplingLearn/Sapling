import { describe, expect, it } from "vitest";

import { dueDateText, dueDay } from "./dates";
import { DEPTH_LABEL, GOAL_LABEL, newLecturesText, plural } from "./labels";

describe("labels", () => {
  it("names every goal and depth", () => {
    expect(GOAL_LABEL).toEqual({ practice: "Practice", review: "Review", exam_prep: "Exam prep" });
    expect(DEPTH_LABEL).toEqual({ cram: "Cram sheet", standard: "Standard", deep: "Deep review" });
  });

  it("counts in the singular and the plural", () => {
    expect(plural(1, "section")).toBe("1 section");
    expect(plural(0, "section")).toBe("0 sections");
    expect(plural(3, "section")).toBe("3 sections");
  });

  it("counts the lectures added since, and says nothing for none", () => {
    expect(newLecturesText(0)).toBe("");
    expect(newLecturesText(1)).toBe("1 new lecture");
    expect(newLecturesText(2)).toBe("2 new lectures");
  });
});

describe("due dates", () => {
  it("reads a date or a timestamp as the day that was written", () => {
    expect(dueDay("2026-03-17")).toBe(Date.UTC(2026, 2, 17));
    expect(dueDay("2026-03-17T23:30:00-05:00")).toBe(Date.UTC(2026, 2, 17));
    expect(dueDay(null)).toBeNull();
    expect(dueDay("soon")).toBeNull();
  });

  it("names the day without the year", () => {
    expect(dueDateText("2026-03-17")).toBe("Tue, Mar 17");
    expect(dueDateText("2026-11-21T00:00:00Z")).toBe("Sat, Nov 21");
    expect(dueDateText(null)).toBe("");
    expect(dueDateText("soon")).toBe("");
  });
});

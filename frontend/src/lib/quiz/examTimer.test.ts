import { describe, it, expect } from "vitest";
import { examTwinDurationSeconds, formatExamClock } from "./examTimer";

describe("examTwinDurationSeconds", () => {
  it("uses 90s per question with a 3-minute floor", () => {
    expect(examTwinDurationSeconds(1)).toBe(180);
    expect(examTwinDurationSeconds(3)).toBe(270);
  });
});

describe("formatExamClock", () => {
  it("formats m:ss", () => {
    expect(formatExamClock(125)).toBe("2:05");
    expect(formatExamClock(0)).toBe("0:00");
  });
});

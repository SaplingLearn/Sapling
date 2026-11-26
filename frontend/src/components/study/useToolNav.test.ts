/**
 * W7.9 / W7.D2: hub header Quiz → course home (no start=1); concept Quiz → start=1.
 * useToolNav itself needs a router; the href builders are the contract under test.
 */
import { describe, expect, it } from "vitest";
import { buildQuizHref } from "@/lib/quiz/source";
import { studyHref } from "@/lib/toolHrefs";

describe("Study hub Quiz hrefs (W7.9)", () => {
  it("tool home opens the course Quiz launcher without starting", () => {
    const href = buildQuizHref(
      { course: "c1" },
      { kind: "link", returnTo: studyHref("c1") },
    );
    expect(href).toBe("/quiz?course=c1&from=link&return=%2Fstudy%3Fcourse%3Dc1");
    expect(href).not.toContain("start=");
  });

  it("concept Quiz starts Practice and returns to Study", () => {
    expect(
      buildQuizHref(
        { concept: "loop" },
        { kind: "link", returnTo: studyHref("c1") },
        { start: true },
      ),
    ).toBe("/quiz?concept=loop&from=link&return=%2Fstudy%3Fcourse%3Dc1&start=1");
  });
});

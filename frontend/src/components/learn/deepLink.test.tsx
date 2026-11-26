// @vitest-environment jsdom
/**
 * The Learn deep links (learn/deepLink.ts), and `?milestone=` (the calendar's
 * Prepare): with `course`, it opens that exam's milestone page in the Tutor,
 * once, when the course is one of the student's.
 */
import { renderHook } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { hasDeepLink, readDeepLink, useMilestoneLink } from "./deepLink";

const params = (q: string) => new URLSearchParams(q);

describe("deep links", () => {
  it("reads milestone beside course, and counts it as a deep link", () => {
    const d = readDeepLink(params("course=cs&milestone=mid2"));
    expect(d.course).toBe("cs");
    expect(d.milestone).toBe("mid2");
    expect(hasDeepLink(d)).toBe(true);
    expect(hasDeepLink(readDeepLink(params("")))).toBe(false);
  });

  it("opens the milestone once its course is the student's, and only once", () => {
    const show = vi.fn();
    const d = readDeepLink(params("course=cs&milestone=mid2"));
    const { rerender } = renderHook(({ courses }) => useMilestoneLink(d, courses, show), { initialProps: { courses: null as { course_id: string }[] | null } });
    expect(show).not.toHaveBeenCalled();
    rerender({ courses: [{ course_id: "ma" }] });
    expect(show).not.toHaveBeenCalled();
    rerender({ courses: [{ course_id: "ma" }, { course_id: "cs" }] });
    expect(show).toHaveBeenCalledWith("cs", "mid2");
    rerender({ courses: [{ course_id: "cs" }] });
    expect(show).toHaveBeenCalledTimes(1);
  });

  it("a milestone without a course opens nothing", () => {
    const show = vi.fn();
    renderHook(() => useMilestoneLink(readDeepLink(params("milestone=mid2")), [{ course_id: "cs" }], show));
    expect(show).not.toHaveBeenCalled();
  });
});

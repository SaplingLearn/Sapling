// @vitest-environment jsdom
import { renderHook, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ACTIVE_SEMESTER_STORAGE_KEY } from "@/lib/useActiveSemester";
import { useTutorCourses } from "./useTutorLists";

const past = { course_id: "c-old", term: "Fall 2025" };
const now1 = { course_id: "c-a", term: "Spring 2026" };
const now2 = { course_id: "c-b", terms: ["Fall 2025", "Spring 2026"] };

afterEach(() => localStorage.clear());

describe("useTutorCourses (#866 audit Z65)", () => {
  it("lists the active semester's courses and opens on the first of them", async () => {
    localStorage.setItem(ACTIVE_SEMESTER_STORAGE_KEY, "Spring 2026");
    const pick = vi.fn();
    const { result } = renderHook(() => useTutorCourses([past, now1, now2], null, pick));
    await waitFor(() => expect(result.current).toEqual([now1, now2]));
    await waitFor(() => expect(pick).toHaveBeenCalledWith("c-a"));
  });

  it("keeps a course already picked (a ?course= link to a past term), and lists every course with no semester", async () => {
    const pick = vi.fn();
    const { result } = renderHook(() => useTutorCourses([past, now1], "c-old", pick));
    await waitFor(() => expect(result.current).toEqual([past, now1]));
    expect(pick).not.toHaveBeenCalled();
  });

  it("falls back to every course when none is in the chosen semester", async () => {
    localStorage.setItem(ACTIVE_SEMESTER_STORAGE_KEY, "Summer 2030");
    const pick = vi.fn();
    const { result } = renderHook(() => useTutorCourses([past, now1], null, pick));
    await waitFor(() => expect(result.current).toEqual([past, now1]));
    await waitFor(() => expect(pick).toHaveBeenCalledWith("c-old"));
  });
});

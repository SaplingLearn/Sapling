// @vitest-environment jsdom
import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  ACTIVE_SEMESTER_STORAGE_KEY,
  distinctTerms,
  ensureDefaultActiveSemester,
  resolveActiveSemester,
} from "./useActiveSemester";

const c = (term: string) => ({ term });

describe("distinctTerms", () => {
  it("dedups preserving first-seen order and drops blanks", () => {
    expect(distinctTerms([c("Fall 2025"), c("Spring 2026"), c("Fall 2025"), c("")]))
      .toEqual(["Fall 2025", "Spring 2026"]);
  });
});

describe("resolveActiveSemester", () => {
  it("keeps the active value when it is among the enrolled terms", () => {
    expect(resolveActiveSemester("Fall 2025", [c("Fall 2025"), c("Spring 2026")]))
      .toBe("Fall 2025");
  });

  it("defaults to the most-recently-enrolled term when active is unset/stale", () => {
    // courses arrive enrolled_at ascending → last is most recent.
    expect(resolveActiveSemester("", [c("Fall 2025"), c("Spring 2026")]))
      .toBe("Spring 2026");
    expect(resolveActiveSemester("Winter 1999", [c("Fall 2025"), c("Spring 2026")]))
      .toBe("Spring 2026");
  });

  it("returns empty string when there are no terms", () => {
    expect(resolveActiveSemester("", [])).toBe("");
  });
});

describe("ensureDefaultActiveSemester", () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  it("persists the first label and notifies mounted hooks when nothing is stored", () => {
    const listener = vi.fn();
    window.addEventListener("sapling-active-semester-change", listener);
    ensureDefaultActiveSemester(["Spring 2026", "Fall 2025"]);
    expect(window.localStorage.getItem(ACTIVE_SEMESTER_STORAGE_KEY)).toBe("Spring 2026");
    expect(listener).toHaveBeenCalledTimes(1);
    window.removeEventListener("sapling-active-semester-change", listener);
  });

  it("never overwrites an already-stored semester", () => {
    window.localStorage.setItem(ACTIVE_SEMESTER_STORAGE_KEY, "Fall 2025");
    ensureDefaultActiveSemester(["Spring 2026"]);
    expect(window.localStorage.getItem(ACTIVE_SEMESTER_STORAGE_KEY)).toBe("Fall 2025");
  });

  it("no-ops when there is no usable label (screen stays unscoped)", () => {
    ensureDefaultActiveSemester([]);
    ensureDefaultActiveSemester([""]);
    expect(window.localStorage.getItem(ACTIVE_SEMESTER_STORAGE_KEY)).toBeNull();
  });
});

/**
 * The shared nav list and its hide_* flags (#620).
 */
import { describe, it, expect } from "vitest";

import {
  NAV_SECTIONS, SIDEBAR_MORE, SIDEBAR_PRIMARY, navFlagForPath, sidebarActiveKey, visibleNavSections,
} from "./navFeatures";
import { SHELL_PREFIXES } from "./appRoutes";

const allItems = NAV_SECTIONS.flatMap((s) => s.items);

describe("NAV_SECTIONS", () => {
  it("flags every destination except Dashboard, one distinct hide_ flag each", () => {
    const flagged = allItems.filter((i) => i.flag);
    expect(allItems.filter((i) => !i.flag).map((i) => i.href)).toEqual(["/dashboard"]);
    expect(new Set(flagged.map((i) => i.flag)).size).toBe(flagged.length);
    for (const i of flagged) expect(i.flag).toMatch(/^hide_[a-z_]+$/);
  });

  it("every destination is an app-shell route", () => {
    for (const i of allItems) expect(SHELL_PREFIXES as readonly string[]).toContain(i.href);
  });
});

describe("navFlagForPath", () => {
  it("maps a destination and the paths below it to its flag", () => {
    expect(navFlagForPath("/quiz")).toBe("hide_quiz");
    expect(navFlagForPath("/quiz/abc")).toBe("hide_quiz");
    expect(navFlagForPath("/learn")).toBe("hide_tutor");
    expect(navFlagForPath("/course-planner/x")).toBe("hide_course_planner");
  });

  it("is null for unflagged routes and look-alikes", () => {
    for (const p of ["/dashboard", "/settings", "/admin", "/profile/x", "/quizzes", "/learn-more", "", null, undefined]) {
      expect(navFlagForPath(p), String(p)).toBeNull();
    }
  });
});

describe("visibleNavSections", () => {
  it("shows everything when nothing is hidden", () => {
    expect(visibleNavSections(() => false)).toEqual(NAV_SECTIONS);
  });

  it("drops hidden items, and a section left empty", () => {
    const hidden = new Set(["hide_quiz", "hide_social", "hide_achievements"]);
    const out = visibleNavSections((f) => hidden.has(f));
    const hrefs = out.flatMap((s) => s.items.map((i) => i.href));
    expect(hrefs).not.toContain("/quiz");
    expect(hrefs).toContain("/tree");
    expect(out.map((s) => s.label)).toEqual(["Learn", "Organize", "Tools"]);
  });

  it("never hides Dashboard", () => {
    const out = visibleNavSections(() => true);
    expect(out).toEqual([{ label: "Learn", items: [NAV_SECTIONS[0].items[0]] }]);
  });
});

describe("the Pen sidebar's view of the list", () => {
  it("shows every destination exactly once: in the six or in More", () => {
    const shown = [...SIDEBAR_PRIMARY.map((e) => e.href), ...SIDEBAR_MORE.map((i) => i.href)];
    for (const i of allItems) expect(shown.filter((h) => h === i.href), i.href).toHaveLength(1);
  });

  it("takes each of the six's hide_ flag from the destination it names", () => {
    for (const e of SIDEBAR_PRIMARY) {
      const path = e.href.split("?")[0];
      expect(e.flag ?? null, e.key).toBe(navFlagForPath(path));
    }
    const tutor = SIDEBAR_PRIMARY.find((e) => e.key === "tutor-view");
    expect(tutor).toMatchObject({ href: "/learn?view=tutor", flag: "hide_tutor", requires: "tutor_view" });
  });

  it("picks one active key: Learn vs Tutor by ?view=, More routes, Settings, Admin", () => {
    expect(sidebarActiveKey("/learn", null, true)).toBe("learn");
    expect(sidebarActiveKey("/learn", "tutor", true)).toBe("tutor-view");
    expect(sidebarActiveKey("/learn", "tutor", false)).toBe("learn");
    expect(sidebarActiveKey("/tree", null, true)).toBe("tree");
    expect(sidebarActiveKey("/course-planner/x", null, true)).toBe("course-planner");
    expect(sidebarActiveKey("/settings/connections", null, true)).toBe("settings");
    expect(sidebarActiveKey("/admin", null, true)).toBe("admin");
    for (const p of ["/profile/u1", "/learn-more", "", null]) expect(sidebarActiveKey(p, null, true), String(p)).toBeNull();
  });
});

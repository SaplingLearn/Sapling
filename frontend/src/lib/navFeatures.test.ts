/**
 * The shared nav list and its hide_* flags (#620).
 */
import { describe, it, expect } from "vitest";

import {
  NAV_PATH_ALIASES, NAV_SECTIONS, NESTED_NAV_FEATURES, navFlagForPath, visibleNavSections,
} from "./navFeatures";
import { SHELL_PREFIXES } from "./appRoutes";
import { STUDY_TOOL_PATHS } from "./toolHrefs";

const allItems = NAV_SECTIONS.flatMap((s) => s.items);

describe("NAV_SECTIONS", () => {
  it("flags every destination except Dashboard, one distinct hide_ flag each", () => {
    const flagged = allItems.filter((i) => i.flag);
    expect(allItems.filter((i) => !i.flag).map((i) => i.href)).toEqual(["/dashboard"]);
    expect(new Set(flagged.map((i) => i.flag)).size).toBe(flagged.length);
    for (const i of flagged) expect(i.flag).toMatch(/^hide_[a-z_]+$/);
  });

  it("keeps Quiz inside Study rather than the primary navigation", () => {
    expect(allItems.some(item => item.href === "/quiz")).toBe(false);
    expect(allItems.some(item => item.href === "/study")).toBe(true);
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
    for (const p of [
      "/dashboard", "/settings", "/admin", "/profile/x", "/quizzes", "/learn-more",
      "/flashcard", "/flashcards-import", "/study-guide", "", null, undefined,
    ]) {
      expect(navFlagForPath(p), String(p)).toBeNull();
    }
  });

  it("gates the Study tools with Study's flag, wherever they are served", () => {
    // /flashcards is a Study page outside /study: before the alias table it
    // resolved to null, so hide_study left it reachable with its API 404ing.
    for (const p of ["/study", "/study/guide", "/flashcards", "/flashcards/deck-1"]) {
      expect(navFlagForPath(p), p).toBe("hide_study");
    }
  });

  it("Quiz keeps its own flag even though it is a Study tool", () => {
    expect(navFlagForPath("/quiz")).toBe("hide_quiz");
  });
});

describe("visibleNavSections", () => {
  it("shows everything when nothing is hidden", () => {
    expect(visibleNavSections(() => false)).toEqual(NAV_SECTIONS);
  });

  it("drops hidden items, and a section left empty", () => {
    const hidden = new Set(["hide_study", "hide_social", "hide_achievements"]);
    const out = visibleNavSections((f) => hidden.has(f));
    const hrefs = out.flatMap((s) => s.items.map((i) => i.href));
    expect(hrefs).not.toContain("/study");
    expect(hrefs).toContain("/tree");
    expect(out.map((s) => s.label)).toEqual(["Learn", "Organize", "Tools"]);
  });

  it("never hides Dashboard", () => {
    const out = visibleNavSections(() => true);
    expect(out).toEqual([{ label: "Learn", items: [NAV_SECTIONS[0].items[0]] }]);
  });
});

describe("NESTED_NAV_FEATURES", () => {
  const sectionFlags = NAV_SECTIONS.flatMap((s) => s.items.map((i) => i.flag)).filter(Boolean);
  const sectionLabels = NAV_SECTIONS.map((s) => s.label);

  it("each has its own hide_ flag, not one a nav row already uses", () => {
    for (const n of NESTED_NAV_FEATURES) {
      expect(n.flag).toMatch(/^hide_[a-z_]+$/);
      expect(sectionFlags).not.toContain(n.flag);
    }
    expect(new Set(NESTED_NAV_FEATURES.map((n) => n.flag)).size).toBe(NESTED_NAV_FEATURES.length);
  });

  it("names a real nav section and an href no nav row covers", () => {
    const rowHrefs = NAV_SECTIONS.flatMap((s) => s.items.map((i) => i.href));
    for (const n of NESTED_NAV_FEATURES) {
      expect(sectionLabels).toContain(n.section);
      expect(rowHrefs.some((h) => n.href === h || n.href.startsWith(h + "/"))).toBe(false);
    }
  });

  it("gates its own pages", () => {
    for (const n of NESTED_NAV_FEATURES) {
      expect(navFlagForPath(n.href)).toBe(n.flag);
      expect(navFlagForPath(`${n.href}/x`)).toBe(n.flag);
    }
  });
});

describe("NAV_PATH_ALIASES", () => {
  const rows = NAV_SECTIONS.flatMap((s) => s.items);
  const covers = (href: string, path: string) => path === href || path.startsWith(href + "/");

  it("each is owned by a flagged nav row and gated by that row's flag", () => {
    for (const a of NAV_PATH_ALIASES) {
      const owner = rows.find((i) => i.href === a.owner);
      expect(owner?.flag, a.path).toBeTruthy();
      expect(navFlagForPath(a.path)).toBe(owner?.flag);
      expect(navFlagForPath(`${a.path}/x`)).toBe(owner?.flag);
    }
  });

  it("names a path that no nav row, nested feature or other alias already covers", () => {
    const taken = [...rows.map((i) => i.href), ...NESTED_NAV_FEATURES.map((n) => n.href)];
    for (const a of NAV_PATH_ALIASES) {
      expect(taken.some((h) => covers(h, a.path) || covers(a.path, h)), a.path).toBe(false);
    }
    expect(new Set(NAV_PATH_ALIASES.map((a) => a.path)).size).toBe(NAV_PATH_ALIASES.length);
  });

  it("is an app-shell route, or the gate never sees its flags", () => {
    // FlagsProvider loads flags only on SHELL_PREFIXES; off them useFlagMap
    // answers "ready, empty" and NavFeatureGate lets the page through.
    for (const a of NAV_PATH_ALIASES) {
      expect(SHELL_PREFIXES as readonly string[], a.path).toContain(a.path);
    }
  });

  it("a Study-owned page keeps Study selected in the nav", () => {
    for (const a of NAV_PATH_ALIASES.filter((x) => x.owner === "/study")) {
      expect(STUDY_TOOL_PATHS, a.path).toContain(a.path);
    }
  });
});

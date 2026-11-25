// @vitest-environment jsdom
/**
 * The Up Next block's prerequisite line: its chips clip, and nothing else on
 * the line does, so the gap mark's reason and the "+N more" list open below
 * it where they can be seen.
 */
import { readFileSync } from "node:fs";
import path from "node:path";
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";

vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn() }), usePathname: () => "/study" }));

import { FocusCard } from "./FocusCard";
import f from "./FocusCard.module.css";
import type { Concept } from "./studyModel";
import type { ToolNav } from "./useToolNav";

const concept = (id: string, name: string, gap = ""): Concept => ({
  id, name, st: "progress", m: 40, lastStudied: null, pre: [], post: [], step: 0, group: "Core", gap, weekDelta: 0,
});
const NAV: ToolNav = {
  leaving: false,
  leaveTo: () => {},
  toolHome: () => "/",
  quizHref: () => "/quiz",
  cardsHref: () => "/flashcards",
  learnHref: () => "/learn",
};
const PREREQS = [
  concept("var", "Variables"),
  concept("arr", "Arrays"),
  concept("loop", "Loops"),
  concept("fn", "Functions"),
];

/** The block's one clipping box on the prerequisite line (`overflow: hidden`
 *  in FocusCard.module.css; jsdom applies no stylesheet, so it is named). */
const CLIPS = [f.prereqChips];

/** The element between `el` and the block that cuts off whatever overflows it. */
function clipperOf(el: HTMLElement): HTMLElement | null {
  for (let at = el.parentElement; at && at.dataset.testid !== "focus-card"; at = at.parentElement) {
    if (CLIPS.some(c => at!.classList.contains(c)) || at.style.overflow === "hidden") return at;
  }
  return null;
}

function renderCard() {
  const focused = concept("rec", "Recursion", "Loops isn't mastered yet.");
  return render(<FocusCard concept={focused} upNext masteredExam={null} prereqs={PREREQS} cardCount={0} quizShown nav={NAV} />);
}

afterEach(cleanup);

describe("the prerequisite line", () => {
  it("clips its chips, so a long name is cut inside the line", () => {
    renderCard();
    const chip = screen.getByTitle(/^Variables · /);
    expect(clipperOf(chip)).toBe(chip.parentElement);
  });

  it("opens the gap mark's reason where nothing clips it", () => {
    renderCard();
    fireEvent.focus(screen.getByLabelText(/Recursion · Loops isn't mastered yet/));
    expect(clipperOf(screen.getByRole("tooltip"))).toBeNull();
  });

  it("opens the '+N more' list where nothing clips it", () => {
    renderCard();
    fireEvent.focus(screen.getByText("+2 more"));
    expect(clipperOf(screen.getByText("Functions"))).toBeNull();
  });
});

describe("the concept's name beside the actions", () => {
  // jsdom has no layout, so this pins the structure the stylesheet relies on:
  // the name wraps (the .focusName rule, which breaks a long word rather than
  // cutting it) with its full text in a title, and nothing fixes the width of
  // the column it is in. StudyHub.module.css gives that column a floor
  // (--focus-text-min) and lets the actions wrap under it below that.
  it("is the wrapping name, titled with the full text, in a column with no fixed width", () => {
    renderCard();
    const name = screen.getByText("Recursion", { selector: "span[title]" });
    expect(name.getAttribute("title")).toBe("Recursion");
    expect(name.className).toContain("focusName");
    for (let at = name.parentElement; at && at.dataset.testid !== "focus-card"; at = at.parentElement) {
      expect(at.style.width).toBe("");
      expect(at.style.minWidth).toBe("");
      expect(at.style.flexBasis).toBe("");
    }
  });

  it("keeps the concept and its actions as siblings, so the actions can wrap below", () => {
    renderCard();
    const name = screen.getByText("Recursion", { selector: "span[title]" });
    const main = name.closest<HTMLElement>("[class*='focusMain']");
    const actions = screen.getByRole("navigation", { name: "Study Recursion" });
    expect(main).not.toBeNull();
    expect(actions.className).toContain("focusActions");
    expect(main!.parentElement).toBe(actions.parentElement);
    expect(main!.parentElement!.className).toContain("focusBody");
  });

  it("wraps the actions under the concept when they would squeeze it (the stylesheet)", () => {
    const css = readFileSync(path.resolve(__dirname, "StudyHub.module.css"), "utf8");
    const wide = css.slice(css.indexOf("@container focus (min-width: 480px)"));
    const rule = wide.slice(0, wide.indexOf("\n}") + 2);
    expect(rule).toMatch(/\.focusBody \{[^}]*flex-wrap: wrap/);
    expect(rule).toMatch(/\.focusMain \{[^}]*flex: 1 1 var\(--focus-text-min\)/);
    expect(css).toMatch(/--focus-text-min: calc\(var\(--sp-\d+\)/);
    expect(css).toMatch(/\.focusName \{[^}]*overflow-wrap: anywhere/);
  });
});

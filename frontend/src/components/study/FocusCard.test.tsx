// @vitest-environment jsdom
/**
 * The Up Next block's prerequisite line: its chips clip, and nothing else on
 * the line does, so the gap mark's reason and the "+N more" list open below
 * it where they can be seen.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";

vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn() }), usePathname: () => "/study" }));

import { FocusCard } from "./FocusCard";
import type { Concept } from "./studyModel";
import type { ToolNav } from "./useToolNav";

const concept = (id: string, name: string, gap = ""): Concept => ({
  id, name, st: "progress", m: 40, lastStudied: null, pre: [], post: [], step: 0, group: "Core", gap, weekDelta: 0,
});
const NAV: ToolNav = { leaving: false, leaveTo: () => {}, toolHome: () => "/", quizHref: () => "/quiz", cardsHref: () => "/flashcards" };
const PREREQS = [
  concept("var", "Variables"),
  concept("arr", "Arrays"),
  concept("loop", "Loops"),
  concept("fn", "Functions"),
];

/** The element between `el` and the block that cuts off whatever overflows it. */
function clipperOf(el: HTMLElement): HTMLElement | null {
  for (let at = el.parentElement; at && at.dataset.testid !== "focus-card"; at = at.parentElement) {
    if (at.style.overflow === "hidden") return at;
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

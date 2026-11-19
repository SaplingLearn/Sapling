// @vitest-environment jsdom
/**
 * PR #866 U7b: the phase stepper at the top of the conversation (wireframe D):
 * Check-in · Plan · Learn · Wrap-up, from the loop's phase — passed steps
 * ticked, the current one numbered and marked `aria-current="step"`, later
 * ones dimmed; an ordered list a screen reader reads in order.
 */
import { afterEach, describe, expect, it } from "vitest";
import { cleanup, render, screen, within } from "@testing-library/react";
import type { LoopPhase } from "@/lib/api";
import { PhaseStepper, stepOf } from "./PhaseStepper";

afterEach(cleanup);

const LABELS = ["Check-in", "Plan", "Learn", "Wrap-up"];

function steps() {
  const list = screen.getByRole("list", { name: "Session progress" });
  expect(list.tagName).toBe("OL");
  return within(list).getAllByRole("listitem");
}

describe("PhaseStepper", () => {
  it.each<[LoopPhase, number]>([
    ["probe", 0],
    ["plan", 1],
    ["teach", 2],
    ["check", 2],
    ["feedback", 2],
    ["close", 3],
  ])("%s is step %i", (phase, at) => {
    expect(stepOf(phase)).toBe(at);
    render(<PhaseStepper phase={phase} />);
    const items = steps();
    expect(items.map((li) => li.querySelector("span:nth-child(2)")?.textContent)).toEqual(LABELS);
    items.forEach((li, i) => {
      const state = i < at ? "done" : i === at ? "current" : "todo";
      expect(li.dataset.state).toBe(state);
      expect(li.getAttribute("aria-current")).toBe(i === at ? "step" : null);
      const mark = li.querySelector("[aria-hidden]")!;
      // a tick before the current step, a number from it on
      if (state === "done") {
        expect(mark.querySelector("svg")).not.toBeNull();
        expect(li.textContent?.trim()).toBe(`${LABELS[i]} (done)`);
      } else {
        expect(mark.textContent).toBe(String(i + 1));
      }
    });
  });

  it("marks exactly one step current", () => {
    render(<PhaseStepper phase="teach" />);
    const current = steps().filter((li) => li.getAttribute("aria-current") === "step");
    expect(current).toHaveLength(1);
    expect(current[0].textContent).toBe("3Learn");
  });
});

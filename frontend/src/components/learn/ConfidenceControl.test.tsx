// @vitest-environment jsdom
/**
 * ConfidenceControl (learning-loop spec §13 A127): the optional "How sure are
 * you?" control on the loop's check and probe cards and the review card.
 *   - a radio group labelled by its visible question, three levels in scale
 *     order, none chosen until the student chooses (a skip is absent);
 *   - one tab stop (the chosen level, else the first); the arrow keys move AND
 *     choose, wrapping, Home / End go to the ends; Space / Enter choose;
 *   - "Clear" takes a choice back (skipping stays possible) and keeps the
 *     keyboard in the group;
 *   - every level carries a visible focus ring (`.option:focus-visible`);
 *   - every testid comes from the caller's prefix.
 */
import React from "react";
import fs from "node:fs";
import path from "node:path";
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import type { StudentConfidence } from "@/lib/api";
import { CONFIDENCE_LEVELS, ConfidenceControl } from "./ConfidenceControl";

afterEach(cleanup);

/** The control as a card uses it: controlled, with a field before and Submit after. */
function Card({ onChange = vi.fn(), disabled = false }: { onChange?: (v: StudentConfidence | null) => void; disabled?: boolean }) {
  const [value, setValue] = React.useState<StudentConfidence | null>(null);
  return (
    <div>
      <textarea data-testid="answer" aria-label="Your answer" />
      <ConfidenceControl
        testIdPrefix="x-confidence"
        value={value}
        onChange={(v) => {
          setValue(v);
          onChange(v);
        }}
        disabled={disabled}
      />
      <button data-testid="submit">Submit</button>
    </div>
  );
}

const option = (level: string) => screen.getByTestId(`x-confidence-${level}`);
const checked = () =>
  CONFIDENCE_LEVELS.filter(({ level }) => option(level).getAttribute("aria-checked") === "true").map((o) => o.level);

describe("ConfidenceControl", () => {
  it("is a radio group labelled by its question, with nothing chosen", () => {
    render(<Card />);
    const group = screen.getByRole("radiogroup", { name: "How sure are you? (optional)" });
    expect(group.getAttribute("data-testid")).toBe("x-confidence");
    const radios = screen.getAllByRole("radio");
    expect(radios.map((r) => r.textContent)).toEqual(["Guessing", "Fairly sure", "Sure"]);
    expect(CONFIDENCE_LEVELS.map((o) => o.level)).toEqual(["guessing", "fairly_sure", "sure"]);
    expect(checked()).toEqual([]); // a skip is absent, never a default level
    expect(screen.queryByTestId("x-confidence-clear")).toBeNull();
  });

  it("chooses a level on click and reports it", async () => {
    const onChange = vi.fn();
    render(<Card onChange={onChange} />);
    await userEvent.click(option("sure"));
    expect(onChange).toHaveBeenLastCalledWith("sure");
    expect(checked()).toEqual(["sure"]);
  });

  it("is one tab stop: the first level until one is chosen, then the chosen one", async () => {
    render(<Card />);
    const tabStops = () => screen.getAllByRole("radio").filter((r) => r.tabIndex === 0).map((r) => r.textContent);
    expect(tabStops()).toEqual(["Guessing"]);
    await userEvent.click(option("fairly_sure"));
    expect(tabStops()).toEqual(["Fairly sure"]);
    screen.getByTestId("answer").focus();
    await userEvent.tab();
    expect(document.activeElement).toBe(option("fairly_sure"));
    await userEvent.tab(); // past "Clear"
    await userEvent.tab();
    expect(document.activeElement).toBe(screen.getByTestId("submit"));
  });

  it("moves and chooses with the arrow keys, wrapping, and Home / End", async () => {
    const onChange = vi.fn();
    render(<Card onChange={onChange} />);
    screen.getByTestId("answer").focus();
    await userEvent.tab();
    expect(document.activeElement).toBe(option("guessing"));
    expect(onChange).not.toHaveBeenCalled(); // focusing chooses nothing
    await userEvent.keyboard("{ArrowRight}");
    expect(checked()).toEqual(["fairly_sure"]);
    expect(document.activeElement).toBe(option("fairly_sure"));
    await userEvent.keyboard("{ArrowDown}");
    expect(checked()).toEqual(["sure"]);
    await userEvent.keyboard("{ArrowRight}"); // wraps to the first
    expect(checked()).toEqual(["guessing"]);
    expect(document.activeElement).toBe(option("guessing"));
    await userEvent.keyboard("{ArrowLeft}"); // wraps to the last
    expect(checked()).toEqual(["sure"]);
    await userEvent.keyboard("{ArrowUp}");
    expect(checked()).toEqual(["fairly_sure"]);
    await userEvent.keyboard("{Home}");
    expect(checked()).toEqual(["guessing"]);
    await userEvent.keyboard("{End}");
    expect(checked()).toEqual(["sure"]);
    expect(document.activeElement).toBe(option("sure"));
  });

  it("chooses the focused level with Space or Enter", async () => {
    render(<Card />);
    option("fairly_sure").focus();
    await userEvent.keyboard(" ");
    expect(checked()).toEqual(["fairly_sure"]);
    option("sure").focus();
    await userEvent.keyboard("{Enter}");
    expect(checked()).toEqual(["sure"]);
  });

  it("clears a choice back to none and keeps the keyboard in the group", async () => {
    const onChange = vi.fn();
    render(<Card onChange={onChange} />);
    await userEvent.click(option("guessing"));
    await userEvent.click(screen.getByTestId("x-confidence-clear"));
    expect(onChange).toHaveBeenLastCalledWith(null);
    expect(checked()).toEqual([]);
    expect(screen.queryByTestId("x-confidence-clear")).toBeNull();
    expect(document.activeElement).toBe(option("guessing"));
  });

  it("is disabled while the card is busy", () => {
    render(<Card disabled />);
    for (const radio of screen.getAllByRole("radio")) expect((radio as HTMLButtonElement).disabled).toBe(true);
  });

  it("draws a visible focus ring on every level", () => {
    const css = fs.readFileSync(path.resolve(__dirname, "ConfidenceControl.module.css"), "utf8");
    const rule = css.match(/\.option:focus-visible[^{]*\{([^}]*)\}/);
    expect(rule).not.toBeNull();
    expect(rule![1]).toMatch(/outline:\s*2px solid var\(--accent\)/);
    expect(css).not.toMatch(/outline:\s*(none|0)\b/);
    render(<Card />);
    for (const radio of screen.getAllByRole("radio")) expect(radio.className).toMatch(/option/);
  });
});

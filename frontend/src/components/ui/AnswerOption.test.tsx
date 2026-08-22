// @vitest-environment jsdom
import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, cleanup, fireEvent } from "@testing-library/react";
import React from "react";
import fs from "node:fs";
import path from "node:path";
import { AnswerOption, type AnswerState } from "./AnswerOption";

afterEach(cleanup);

const TEXT = "It stops the recursion by returning a result";

function setup(state: AnswerState, over: Partial<React.ComponentProps<typeof AnswerOption>> = {}) {
  const onSelect = vi.fn();
  const utils = render(
    <AnswerOption
      letter="B"
      text={TEXT}
      state={state}
      onSelect={onSelect}
      testid="quiz-answer-option-B"
      {...over}
    />,
  );
  return { onSelect, ...utils };
}

describe("AnswerOption", () => {
  it("is a radio carrying the letter and the text", () => {
    setup("default");
    const row = screen.getByRole("radio");
    expect(row).toHaveAttribute("aria-checked", "false");
    expect(row).toHaveTextContent("B");
    expect(row).toHaveTextContent(TEXT);
    expect(row).toHaveClass("answer-option", "answer-option--default");
    expect(row).toHaveAttribute("data-testid", "quiz-answer-option-B");
  });

  it("is checked when selected, and when it was the chosen wrong answer", () => {
    setup("selected");
    expect(screen.getByRole("radio")).toHaveAttribute("aria-checked", "true");
    cleanup();
    setup("chosen-wrong");
    expect(screen.getByRole("radio")).toHaveAttribute("aria-checked", "true");
    cleanup();
    setup("correct");
    // `correct` is the answer, not the student's pick.
    expect(screen.getByRole("radio")).toHaveAttribute("aria-checked", "false");
  });

  it("selects on click and on Enter/Space, because it is a real button", () => {
    const { onSelect } = setup("default");
    const row = screen.getByRole("radio");
    fireEvent.click(row);
    fireEvent.keyDown(row, { key: "Enter" });
    fireEvent.keyUp(row, { key: " " });
    // jsdom doesn't synthesise the click for key events, so assert the type
    // that actually carries them: a <button>, which browsers do it for.
    expect(row.tagName).toBe("BUTTON");
    expect(row).toHaveAttribute("type", "button");
    expect(onSelect).toHaveBeenCalledTimes(1);
  });

  it("stays focusable but inert when disabled", () => {
    const { onSelect } = setup("muted", { disabled: true });
    const row = screen.getByRole("radio");
    expect(row).toHaveAttribute("aria-disabled", "true");
    expect(row).not.toHaveAttribute("disabled");
    fireEvent.click(row);
    expect(onSelect).not.toHaveBeenCalled();
  });

  it("never signals a verdict by colour alone — a mark and a spoken suffix too", () => {
    setup("correct");
    expect(screen.getByRole("radio")).toHaveAccessibleName(`B. ${TEXT} — correct answer`);
    expect(screen.getByRole("radio").querySelector(".answer-option__mark")!.textContent).toBe("✓");
    cleanup();
    setup("chosen-wrong");
    expect(screen.getByRole("radio")).toHaveAccessibleName(
      `B. ${TEXT} — your answer, incorrect`,
    );
    expect(screen.getByRole("radio").querySelector(".answer-option__mark")!.textContent).toBe("✕");
  });

  it("reserves the mark slot in every state so the reveal never reflows the row", () => {
    for (const state of ["default", "selected", "correct", "chosen-wrong", "muted"] as const) {
      const { container } = render(
        <AnswerOption letter="A" text={TEXT} state={state} onSelect={() => {}} />,
      );
      expect(container.querySelector(".answer-option__mark")).not.toBeNull();
      cleanup();
    }
  });

  it("hides the letter and the mark from the accessible name, which the label carries", () => {
    setup("correct");
    const row = screen.getByRole("radio");
    expect(row.querySelector(".answer-option__letter")).toHaveAttribute("aria-hidden", "true");
    expect(row.querySelector(".answer-option__mark")).toHaveAttribute("aria-hidden", "true");
  });

  it("draws its text at the design's 15px, which the --fs-* scale has no step for", () => {
    const css = fs.readFileSync(path.resolve(__dirname, "../../app/globals.css"), "utf8");
    expect(css).toMatch(/--answer-text-fs:\s*15px;/);
    expect(css).toMatch(
      /\.answer-option__text \{[^}]*font-size:\s*var\(--answer-text-fs\)[^}]*\}/,
    );
  });

  it("defaults its tab stop to checked-only, and honours an explicit one", () => {
    setup("default");
    expect(screen.getByRole("radio")).toHaveAttribute("tabindex", "-1");
    cleanup();
    setup("selected");
    expect(screen.getByRole("radio")).toHaveAttribute("tabindex", "0");
    cleanup();
    // A group with nothing selected makes its first row the tab stop.
    setup("default", { tabIndex: 0 });
    expect(screen.getByRole("radio")).toHaveAttribute("tabindex", "0");
  });
});

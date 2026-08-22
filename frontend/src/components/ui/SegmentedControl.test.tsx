// @vitest-environment jsdom
import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, cleanup, fireEvent } from "@testing-library/react";
import React from "react";
import { SegmentedControl } from "./SegmentedControl";

afterEach(cleanup);

const OPTIONS = [
  { value: "easy", label: "easy" },
  { value: "medium", label: "medium" },
  { value: "hard", label: "hard" },
];

function setup(over: Partial<React.ComponentProps<typeof SegmentedControl<string>>> = {}) {
  const onChange = vi.fn();
  const utils = render(
    <SegmentedControl
      options={OPTIONS}
      value="medium"
      onChange={onChange}
      ariaLabel="Difficulty"
      testid="quiz-seg-difficulty"
      {...over}
    />,
  );
  return { onChange, ...utils };
}

describe("SegmentedControl", () => {
  it("is a labelled radiogroup of radios with exactly one checked", () => {
    setup();
    const group = screen.getByRole("radiogroup", { name: "Difficulty" });
    expect(group).toBeInTheDocument();
    const radios = screen.getAllByRole("radio");
    expect(radios).toHaveLength(3);
    expect(radios.filter((r) => r.getAttribute("aria-checked") === "true")).toHaveLength(1);
    expect(screen.getByRole("radio", { name: "medium" })).toHaveAttribute("aria-checked", "true");
  });

  it("gives the group one tab stop — the selected option", () => {
    setup();
    expect(screen.getByRole("radio", { name: "medium" })).toHaveAttribute("tabindex", "0");
    expect(screen.getByRole("radio", { name: "easy" })).toHaveAttribute("tabindex", "-1");
    expect(screen.getByRole("radio", { name: "hard" })).toHaveAttribute("tabindex", "-1");
  });

  it("puts the tab stop on the first option when nothing is selected yet", () => {
    setup({ value: "" });
    expect(screen.getByRole("radio", { name: "easy" })).toHaveAttribute("tabindex", "0");
  });

  it("selects on click", () => {
    const { onChange } = setup();
    fireEvent.click(screen.getByRole("radio", { name: "hard" }));
    expect(onChange).toHaveBeenCalledWith("hard");
  });

  it("moves and selects with the arrow keys, wrapping at both ends", () => {
    const { onChange } = setup();
    const group = screen.getByRole("radiogroup");
    fireEvent.keyDown(group, { key: "ArrowRight" });
    expect(onChange).toHaveBeenLastCalledWith("hard");
    fireEvent.keyDown(group, { key: "ArrowLeft" });
    expect(onChange).toHaveBeenLastCalledWith("easy");
    cleanup();

    const last = setup({ value: "hard" });
    fireEvent.keyDown(screen.getByRole("radiogroup"), { key: "ArrowRight" });
    expect(last.onChange).toHaveBeenLastCalledWith("easy");
  });

  it("treats up/down like left/right, and Home/End as the ends", () => {
    const { onChange } = setup();
    const group = screen.getByRole("radiogroup");
    fireEvent.keyDown(group, { key: "ArrowDown" });
    expect(onChange).toHaveBeenLastCalledWith("hard");
    fireEvent.keyDown(group, { key: "ArrowUp" });
    expect(onChange).toHaveBeenLastCalledWith("easy");
    fireEvent.keyDown(group, { key: "Home" });
    expect(onChange).toHaveBeenLastCalledWith("easy");
    fireEvent.keyDown(group, { key: "End" });
    expect(onChange).toHaveBeenLastCalledWith("hard");
  });

  it("moves focus with the selection so the keyboard user follows it", () => {
    setup();
    fireEvent.keyDown(screen.getByRole("radiogroup"), { key: "ArrowRight" });
    expect(document.activeElement).toBe(screen.getByRole("radio", { name: "hard" }));
  });

  it("skips a disabled option rather than landing on it", () => {
    const { onChange } = setup({
      options: [
        { value: "easy", label: "easy" },
        { value: "medium", label: "medium" },
        { value: "hard", label: "hard", disabled: true },
      ],
    });
    fireEvent.keyDown(screen.getByRole("radiogroup"), { key: "ArrowRight" });
    expect(onChange).toHaveBeenLastCalledWith("easy"); // wrapped past `hard`
    fireEvent.click(screen.getByRole("radio", { name: "hard" }));
    expect(onChange).not.toHaveBeenCalledWith("hard");
    expect(screen.getByRole("radio", { name: "hard" })).toHaveAttribute("aria-disabled", "true");
  });

  it("suffixes each option's testid with its value", () => {
    setup();
    expect(screen.getByTestId("quiz-seg-difficulty")).toBeInTheDocument();
    expect(screen.getByTestId("quiz-seg-difficulty-easy")).toBeInTheDocument();
    expect(screen.getByTestId("quiz-seg-difficulty-hard")).toBeInTheDocument();
  });

  it("takes numeric values, which is how the question-count row uses it", () => {
    const onChange = vi.fn();
    render(
      <SegmentedControl
        options={[3, 5, 10].map((v) => ({ value: v, label: `${v} questions` }))}
        value={5}
        onChange={onChange}
        ariaLabel="Length"
        testid="quiz-seg-count"
      />,
    );
    fireEvent.click(screen.getByRole("radio", { name: "10 questions" }));
    expect(onChange).toHaveBeenCalledWith(10);
    expect(screen.getByTestId("quiz-seg-count-3")).toBeInTheDocument();
  });
});

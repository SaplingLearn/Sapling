// @vitest-environment jsdom
/**
 * WrittenAnswer once it is marked or locked, and the small accessibility
 * wiring WrittenAnswer.test.tsx doesn't pin: what the field is described by,
 * what replaces the read-back, and how the key row behaves.
 */
import React from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { WrittenAnswer, type WrittenAnswerProps } from "./WrittenAnswer";

afterEach(cleanup);

function renderField(over: Partial<WrittenAnswerProps> = {}) {
  return render(
    <WrittenAnswer type="numeric" value="" disabled={false} onChange={vi.fn()} onSubmit={vi.fn()} describedBy="hint" {...over} />,
  );
}

const input = () => screen.getByTestId("quiz-written-answer") as HTMLInputElement;

describe("WrittenAnswer — marked", () => {
  it.each([
    ["correct", "Correct"],
    ["incorrect", "Incorrect"],
  ] as const)("puts %s at the field's end in place of the reading", (verdict, label) => {
    const { container } = renderField({ value: "3/4", verdict, disabled: true });
    const status = container.querySelector(".quiz-written__field .quiz-written__status")!;
    expect(status).toHaveTextContent(label);
    expect(status).toHaveAttribute("aria-hidden", "true");
    expect(status.querySelector(".quiz-written__mark svg")).not.toBeNull();
    expect(screen.queryByTestId("quiz-written-readback")).toBeNull();
    expect(input()).toHaveAttribute("aria-describedby", "hint");
  });

  it("drops the problem line once marked, but keeps the field invalid", () => {
    const { container } = renderField({ type: "symbolic", value: "sin(x)", verdict: "incorrect", disabled: true });
    expect(container.querySelector(".quiz-written__problem")).toBeNull();
    expect(input()).toHaveAttribute("aria-invalid", "true");
  });

  it("has no verdict attribute or status before it is marked", () => {
    const { container } = renderField({ value: "3/4" });
    expect(container.querySelector(".quiz-written")).not.toHaveAttribute("data-verdict");
    expect(container.querySelector(".quiz-written__status")).toBeNull();
  });
});

describe("WrittenAnswer — read-back wiring", () => {
  it("describes the field by the reading too, while one is shown", () => {
    renderField({ value: "3/4" });
    expect(input()).toHaveAttribute("aria-describedby", "hint quiz-written-readback");
    expect(input()).not.toHaveAttribute("aria-invalid");
    const readBack = screen.getByTestId("quiz-written-readback");
    expect(readBack).toHaveClass("quiz-written__reading");
    expect(readBack).toHaveAttribute("data-ok", "true");
    expect(readBack).toHaveAttribute("aria-live", "polite");
  });

  it("puts a problem under the keys, not in the field", () => {
    const { container } = renderField({ value: "10 units" });
    const readBack = screen.getByTestId("quiz-written-readback");
    expect(readBack).toHaveClass("quiz-written__readback");
    expect(readBack).toHaveAttribute("data-ok", "false");
    expect(readBack.closest(".quiz-written__problem")).not.toBeNull();
    expect(container.querySelector(".quiz-written__field [data-testid='quiz-written-readback']")).toBeNull();
    // The problem paragraph is the last thing in the widget.
    expect(container.querySelector(".quiz-written")!.lastElementChild).toHaveClass("quiz-written__problem");
  });

  it("reads a percentage back as the number the grader sees, and skips e-notation it already shows", () => {
    renderField({ value: "75%" });
    expect(screen.getByTestId("quiz-written-readback")).toHaveTextContent("Reads as 0.75");
    cleanup();
    renderField({ value: "6.02e23" });
    expect(screen.queryByTestId("quiz-written-readback")).toBeNull();
  });

  it("reads nothing back for a blank or a short answer", () => {
    renderField({ value: "   " });
    expect(screen.queryByTestId("quiz-written-readback")).toBeNull();
    cleanup();
    renderField({ type: "short_answer", value: "10 units" });
    expect(screen.queryByTestId("quiz-written-readback")).toBeNull();
  });
});

describe("WrittenAnswer — the field and its keys", () => {
  it.each([
    ["short_answer", "Type your answer", "text", "true"],
    ["numeric", "e.g. 42, 3/4, 0.75, 75% or 3×10⁸", "decimal", "false"],
    ["symbolic", "e.g. 2(x + 1) or x² − 1", "text", "false"],
  ] as const)("sets up a %s field", (type, placeholder, inputMode, spellCheck) => {
    const { container } = renderField({ type, labelledBy: "lab stem" });
    expect(input()).toHaveAttribute("placeholder", placeholder);
    expect(input()).toHaveAttribute("inputmode", inputMode);
    expect(input()).toHaveAttribute("spellcheck", spellCheck);
    expect(input()).toHaveAttribute("aria-labelledby", "lab stem");
    expect(input()).toHaveAttribute("maxlength", "2000");
    expect(input()).toHaveAttribute("autocomplete", "off");
    expect(container.querySelector(".quiz-written")).toHaveAttribute("data-format", type);
  });

  it("locks every key and the toggle with the field", () => {
    renderField({ type: "symbolic", value: "x", disabled: true });
    expect(input()).toBeDisabled();
    for (const key of screen.getAllByRole("button")) expect(key).toBeDisabled();
  });

  it("keeps focus in the field when a key or the toggle is pressed", () => {
    renderField({ type: "symbolic" });
    expect(fireEvent.mouseDown(screen.getByTestId("quiz-key-plus"))).toBe(false);
    expect(fireEvent.mouseDown(screen.getByTestId("quiz-key-more"))).toBe(false);
  });

  it("names the toggle by what it will do, and closes again", () => {
    renderField({ type: "symbolic" });
    const toggle = screen.getByTestId("quiz-key-more");
    expect(toggle).toHaveAttribute("aria-label", "Show number keys");
    expect(toggle).toHaveAttribute("aria-controls", "quiz-written-more");
    fireEvent.click(toggle);
    expect(toggle).toHaveAttribute("aria-label", "Hide number keys");
    expect(screen.getByRole("group", { name: "Insert a number" })).toHaveAttribute("id", "quiz-written-more");
    fireEvent.click(toggle);
    expect(screen.queryByRole("group", { name: "Insert a number" })).toBeNull();
  });

  it("orders the numeric keys as the pad lacks them", () => {
    renderField({ type: "numeric" });
    const ids = screen.getAllByRole("button").map(b => b.getAttribute("data-testid"));
    expect(ids).toEqual(["quiz-key-minus", "quiz-key-fraction", "quiz-key-percent", "quiz-key-exponent", "quiz-key-space"]);
  });

  it("places the caret even when the typed text stores unchanged", () => {
    const onChange = vi.fn();
    renderField({ type: "symbolic", value: "x^2", onChange });
    // "x²" typed over itself: nothing to store, the caret still lands.
    input().setSelectionRange(0, 0);
    fireEvent.change(input(), { target: { value: "x²", selectionStart: 1 } });
    expect(onChange).not.toHaveBeenCalled();
    expect(input().selectionStart).toBe(1);
  });
});

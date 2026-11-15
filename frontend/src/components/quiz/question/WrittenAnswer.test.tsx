// @vitest-environment jsdom
import React from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { WrittenAnswer, type WrittenType } from "./WrittenAnswer";

afterEach(cleanup);

/** A controlled harness: the input writes back through `onChange`, as the
 *  quiz session does. */
function Harness({ type, initial = "", onSubmit = vi.fn() }: { type: WrittenType; initial?: string; onSubmit?: () => void }) {
  const [value, setValue] = React.useState(initial);
  return (
    <WrittenAnswer type={type} value={value} disabled={false} onChange={setValue} onSubmit={onSubmit} describedBy="hint" />
  );
}

const input = () => screen.getByTestId("quiz-written-answer") as HTMLInputElement;

describe("WrittenAnswer", () => {
  it("gives short answers a plain line with no symbol keys or read-back", () => {
    render(<Harness type="short_answer" initial="base case" />);
    expect(screen.queryByRole("group", { name: "Insert a symbol" })).toBeNull();
    expect(screen.queryByTestId("quiz-written-readback")).toBeNull();
  });

  it.each([
    ["numeric", "3/4"],
    ["symbolic", "x^2 - 1"],
  ] as const)("accepts valid %s without preview or placeholder text", (type, initial) => {
    const onSubmit = vi.fn();
    render(<Harness type={type} initial={initial} onSubmit={onSubmit} />);
    expect(screen.queryByTestId("quiz-written-readback")).toBeNull();
    expect(input()).not.toHaveAttribute("placeholder");
    fireEvent.keyDown(input(), { key: "Enter" });
    expect(onSubmit).toHaveBeenCalledOnce();
  });

  it.each([
    ["numeric", "10 units"],
    ["symbolic", "sin(x)"],
    ["symbolic", "x^"],
  ] as const)("blocks invalid %s answers on Enter without a warning", (type, initial) => {
    const onSubmit = vi.fn();
    render(<Harness type={type} initial={initial} onSubmit={onSubmit} />);
    expect(screen.queryByTestId("quiz-written-readback")).toBeNull();
    expect(input()).toHaveAttribute("aria-invalid", "true");
    fireEvent.keyDown(input(), { key: "Enter" });
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("submits on Enter, but not mid-composition", () => {
    const onSubmit = vi.fn();
    render(<Harness type="short_answer" initial="ATP" onSubmit={onSubmit} />);
    fireEvent.keyDown(input(), { key: "Enter", isComposing: true });
    expect(onSubmit).not.toHaveBeenCalled();
    fireEvent.keyDown(input(), { key: "Enter" });
    expect(onSubmit).toHaveBeenCalledOnce();
  });
});

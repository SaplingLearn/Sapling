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

  it("reads valid numbers back without symbol keys", () => {
    render(<Harness type="numeric" initial="3/4" />);
    expect(screen.queryByRole("group", { name: "Insert a symbol" })).toBeNull();
    expect(screen.getByTestId("quiz-written-readback")).toHaveTextContent("Reads as 0.75");
  });

  it("previews algebra with real superscripts", () => {
    render(<Harness type="symbolic" initial="x^2 - 1" />);
    const readBack = screen.getByTestId("quiz-written-readback");
    expect(readBack).toHaveTextContent("Reads as x2 − 1");
    expect(readBack.querySelector("sup")).toHaveTextContent("2");
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

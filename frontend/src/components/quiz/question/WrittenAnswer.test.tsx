// @vitest-environment jsdom
import React from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
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
    expect(input().getAttribute("inputmode")).toBe("text");
    expect(screen.queryByRole("group", { name: "Insert a symbol" })).toBeNull();
    expect(screen.queryByTestId("quiz-written-readback")).toBeNull();
  });

  it("gives numbers the decimal keypad, the keys it lacks, and a read-back", () => {
    render(<Harness type="numeric" initial="3/4" />);
    expect(input().getAttribute("inputmode")).toBe("decimal");
    for (const id of ["minus", "fraction", "percent", "exponent"]) {
      expect(screen.getByTestId(`quiz-key-${id}`)).toBeInTheDocument();
    }
    expect(screen.getByTestId("quiz-written-readback")).toHaveTextContent("Reads as 0.75");
  });

  it("says when a number can't be read, and marks the input invalid", () => {
    render(<Harness type="numeric" initial="10 units" />);
    expect(screen.getByTestId("quiz-written-readback")).toHaveTextContent("Not a number the grader can read");
    expect(input()).toHaveAttribute("aria-invalid", "true");
  });

  it("previews algebra with real superscripts", () => {
    render(<Harness type="symbolic" initial="x^2 - 1" />);
    const readBack = screen.getByTestId("quiz-written-readback");
    expect(readBack).toHaveTextContent("Reads as x2 − 1");
    expect(readBack.querySelector("sup")).toHaveTextContent("2");
  });

  it("warns about a function before it is submitted", () => {
    render(<Harness type="symbolic" initial="sin(x)" />);
    expect(screen.getByTestId("quiz-written-readback")).toHaveTextContent("Functions like sin");
  });

  it("inserts a key at the cursor, and brackets leave the cursor inside", async () => {
    vi.useFakeTimers({ toFake: ["requestAnimationFrame"] });
    render(<Harness type="symbolic" initial="2+1" />);
    input().setSelectionRange(1, 1);
    fireEvent.click(screen.getByTestId("quiz-key-brackets"));
    expect(input().value).toBe("2()+1");
    await act(async () => {
      vi.runAllTimers();
    });
    expect(input().selectionStart).toBe(2);
    vi.useRealTimers();
  });

  it("replaces a selection with the key", () => {
    render(<Harness type="numeric" initial="12" />);
    input().setSelectionRange(0, 2);
    fireEvent.click(screen.getByTestId("quiz-key-minus"));
    expect(input().value).toBe("-");
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

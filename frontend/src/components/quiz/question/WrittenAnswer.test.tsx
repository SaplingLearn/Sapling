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

  it("gives numbers the decimal keypad, the keys it lacks, and a reading inside the field", () => {
    render(<Harness type="numeric" initial="3/4" />);
    expect(input().getAttribute("inputmode")).toBe("decimal");
    for (const id of ["minus", "fraction", "percent", "exponent"]) {
      expect(screen.getByTestId(`quiz-key-${id}`)).toBeInTheDocument();
    }
    const readBack = screen.getByTestId("quiz-written-readback");
    expect(readBack).toHaveTextContent("Reads as 0.75");
    expect(readBack.closest(".quiz-written__field")).not.toBeNull();
  });

  it("says when a number can't be read, and marks the input invalid", () => {
    render(<Harness type="numeric" initial="10 units" />);
    expect(screen.getByTestId("quiz-written-readback")).toHaveTextContent("Not a number the grader can read");
    expect(input()).toHaveAttribute("aria-invalid", "true");
  });

  it("typesets algebra in the field itself, and keeps ASCII for the grader", () => {
    const onChange = vi.fn();
    render(<WrittenAnswer type="symbolic" value="x^2 - 1" disabled={false} onChange={onChange} onSubmit={vi.fn()} describedBy="hint" />);
    expect(input().value).toBe("x² − 1");
    expect(screen.queryByTestId("quiz-written-readback")).toBeNull();
    // Typing into the typeset text hands the session plain ASCII.
    fireEvent.change(input(), { target: { value: "x² − 13" } });
    expect(onChange).toHaveBeenLastCalledWith("x^2 - 13");
  });

  it("keeps the caret after the character just typed when it joins an exponent", () => {
    render(<Harness type="symbolic" initial="x^2+1" />);
    expect(input().value).toBe("x²+1");
    // Type "3" between ² and +: it joins the exponent (the grader reads x^23).
    const typed = "x²3+1";
    input().setSelectionRange(3, 3);
    fireEvent.change(input(), { target: { value: typed, selectionStart: 3 } });
    expect(input().value).toBe("x²³+1");
    expect(input().selectionStart).toBe(3);
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
    expect(input().value).toBe("−"); // shown as a true minus, stored as "-"
  });

  it("typesets e-notation in the number field, and stores the e", () => {
    const onChange = vi.fn();
    render(<WrittenAnswer type="numeric" value="3e8" disabled={false} onChange={onChange} onSubmit={vi.fn()} describedBy="hint" />);
    expect(input().value).toBe("3×10⁸");
    fireEvent.change(input(), { target: { value: "3×10⁸5" } });
    expect(onChange).toHaveBeenLastCalledWith("3e85");
  });

  it("submits on Enter, but not mid-composition", () => {
    const onSubmit = vi.fn();
    render(<Harness type="short_answer" initial="ATP" onSubmit={onSubmit} />);
    fireEvent.keyDown(input(), { key: "Enter", isComposing: true });
    expect(onSubmit).not.toHaveBeenCalled();
    fireEvent.keyDown(input(), { key: "Enter" });
    expect(onSubmit).toHaveBeenCalledOnce();
  });

  it("adds no read-back when the number already reads as typed", () => {
    render(<Harness type="numeric" initial="15" />);
    expect(screen.queryByTestId("quiz-written-readback")).toBeNull();
    expect(input()).toHaveAttribute("aria-describedby", "hint");
  });

  it.each(["short_answer", "numeric", "symbolic"] as const)("renders %s in the app's standard field", type => {
    render(<Harness type={type} />);
    expect(input()).toHaveClass("field", `quiz-written__input--${type}`);
  });

  it("carries the verdict on the field once the answer is marked", () => {
    const { container } = render(
      <WrittenAnswer type="short_answer" value="x" disabled verdict="incorrect" onChange={vi.fn()} onSubmit={vi.fn()} describedBy="hint" />,
    );
    expect(container.querySelector(".quiz-written")).toHaveAttribute("data-verdict", "incorrect");
  });
});

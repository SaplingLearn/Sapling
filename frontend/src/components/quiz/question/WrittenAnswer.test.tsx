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

  it("inserts a key at the cursor, and brackets leave the cursor inside", () => {
    render(<Harness type="symbolic" initial="2+1" />);
    input().setSelectionRange(1, 1);
    fireEvent.click(screen.getByTestId("quiz-key-brackets"));
    expect(input().value).toBe("2()+1");
    expect(input().selectionStart).toBe(2);
    expect(input().selectionEnd).toBe(2);
  });

  it("has the cursor inside the brackets before the next keystroke, with no frame in between", () => {
    // The quiz-written E2E types straight after the click. The cursor used to
    // move in a requestAnimationFrame, so "x" landed after ")" first: freeze
    // frames and the move must already have happened when the click returns.
    vi.useFakeTimers({ toFake: ["requestAnimationFrame"] });
    try {
      render(<Harness type="symbolic" initial="2" />);
      input().focus();
      input().setSelectionRange(1, 1);
      fireEvent.click(screen.getByTestId("quiz-key-brackets"));
      const at = input().selectionStart ?? -1;
      // What the browser does with the next typed character: insert at the cursor.
      fireEvent.change(input(), { target: { value: input().value.slice(0, at) + "x" + input().value.slice(at) } });
      expect(input().value).toBe("2(x)");
    } finally {
      vi.useRealTimers();
    }
  });

  it("moves the cursor once a parent that answers later writes the value", () => {
    let release: (() => void) | undefined;
    function LateHarness() {
      const [value, setValue] = React.useState("2");
      return (
        <WrittenAnswer
          type="symbolic"
          value={value}
          disabled={false}
          onChange={text => {
            release = () => setValue(text);
          }}
          onSubmit={vi.fn()}
          describedBy="hint"
        />
      );
    }
    render(<LateHarness />);
    input().setSelectionRange(1, 1);
    fireEvent.click(screen.getByTestId("quiz-key-brackets"));
    expect(input().value).toBe("2");
    act(() => release?.());
    expect(input().value).toBe("2()");
    expect(input().selectionStart).toBe(2);
  });

  it("drops a pending cursor move once the student types", () => {
    let release: (() => void) | undefined;
    function LateHarness() {
      const [value, setValue] = React.useState("2");
      return (
        <WrittenAnswer
          type="symbolic"
          value={value}
          disabled={false}
          onChange={text => {
            if (text === "2()") release = () => setValue(text);
            else setValue(text);
          }}
          onSubmit={vi.fn()}
          describedBy="hint"
        />
      );
    }
    render(<LateHarness />);
    input().setSelectionRange(1, 1);
    fireEvent.click(screen.getByTestId("quiz-key-brackets"));
    fireEvent.change(input(), { target: { value: "2x" } });
    expect(input().value).toBe("2x");
    act(() => release?.());
    // The late "2()" still arrives, but the cursor stays where the browser put it.
    expect(input().value).toBe("2()");
    expect(input().selectionStart).toBe(3);
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

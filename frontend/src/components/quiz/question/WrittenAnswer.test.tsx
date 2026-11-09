// @vitest-environment jsdom
import React from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { WrittenAnswer, type WrittenType } from "./WrittenAnswer";

afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

/** A controlled harness: the input writes back through `onChange`, as the
 *  quiz session does. `accept={false}` is an owner that refuses the write
 *  (the session drops writes while an answer is being submitted). */
function Harness({ type, initial = "", onSubmit = vi.fn(), accept = true }: {
  type: WrittenType; initial?: string; onSubmit?: () => void; accept?: boolean;
}) {
  const [value, setValue] = React.useState(initial);
  return (
    <WrittenAnswer
      type={type}
      value={value}
      disabled={false}
      onChange={next => { if (accept) setValue(next); }}
      onSubmit={onSubmit}
      describedBy="hint"
    />
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

  it("inserts a key at the cursor, and brackets leave the cursor inside — in the click's own task", () => {
    // No animation frame runs in this test: the cursor has to be in place
    // when the click returns, before any keystroke can follow it.
    vi.useFakeTimers({ toFake: ["requestAnimationFrame"] });
    render(<Harness type="symbolic" initial="2+1" />);
    input().focus();
    input().setSelectionRange(1, 1);
    fireEvent.click(screen.getByTestId("quiz-key-brackets"));
    expect(input().value).toBe("2()+1");
    expect([input().selectionStart, input().selectionEnd]).toEqual([2, 2]);
    expect(document.activeElement).toBe(input());
  });

  // The quiz-written E2E journey's regression: "2", "( )", then "x + 1" typed
  // at once read "2( 1)x +". Writing "2()" moves the cursor to the end; the
  // cursor used to go inside the brackets only at the next animation frame, so
  // the keys typed before that frame went in at the end and the frame then put
  // the cursor back behind them. However late a frame comes, typing straight
  // after a key continues where the key left the cursor.
  it("keeps typing inside the brackets when the next frame comes late", async () => {
    vi.useFakeTimers({ toFake: ["requestAnimationFrame"] });
    const user = userEvent.setup();
    render(<Harness type="symbolic" initial="2" />);
    input().focus();
    input().setSelectionRange(1, 1);
    fireEvent.click(screen.getByTestId("quiz-key-brackets"));
    await user.keyboard("x +");
    await act(async () => {
      vi.runAllTimers(); // the frame arrives mid-typing
    });
    await user.keyboard(" 1");
    expect(input().value).toBe("2(x + 1)");
    expect(screen.getByTestId("quiz-written-readback")).toHaveTextContent("Reads as 2(x + 1)");
  });

  it("leaves the value and the student's cursor alone when the write is refused", () => {
    vi.useFakeTimers({ toFake: ["requestAnimationFrame"] });
    render(<Harness type="symbolic" initial="2+1" accept={false} />);
    input().focus();
    input().setSelectionRange(1, 1);
    fireEvent.click(screen.getByTestId("quiz-key-brackets"));
    act(() => {
      vi.runAllTimers();
    });
    expect(input().value).toBe("2+1");
    expect([input().selectionStart, input().selectionEnd]).toEqual([1, 1]);
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

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

  it("treats a type outside the known formats as plain text with no keys", () => {
    // QuizQuestion casts the wire's type, so an unknown one can arrive here.
    const type = "free_response" as WrittenType;
    expect(() => render(<Harness type={type} initial="x^2 3e8" />)).not.toThrow();
    expect(input().value).toBe("x^2 3e8");
    expect(input().getAttribute("inputmode")).toBe("text");
    expect(screen.queryByRole("group", { name: "Insert a symbol" })).toBeNull();
    expect(screen.queryByRole("group", { name: "Insert a number" })).toBeNull();
    expect(screen.queryByTestId("quiz-key-more")).toBeNull();
    expect(screen.queryByTestId("quiz-written-readback")).toBeNull();
    fireEvent.change(input(), { target: { value: "x^2 3e8 + 1" } });
    expect(input().value).toBe("x^2 3e8 + 1");
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

  it("gives algebra a plus key, and a 123 toggle for the digits a phone keyboard hides", () => {
    render(<Harness type="symbolic" initial="x" />);
    input().setSelectionRange(1, 1);
    fireEvent.click(screen.getByTestId("quiz-key-plus"));
    expect(input().value).toBe("x+");
    const toggle = screen.getByTestId("quiz-key-more");
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByTestId("quiz-key-digit-3")).toBeNull();
    fireEvent.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    fireEvent.click(screen.getByTestId("quiz-key-digit-3"));
    fireEvent.click(screen.getByTestId("quiz-key-point"));
    fireEvent.click(screen.getByTestId("quiz-key-digit-5"));
    expect(input().value).toBe("x+3.5");
  });

  it("gives numbers a space key, for a mixed number the decimal pad can't type", () => {
    render(<Harness type="numeric" initial="1" />);
    input().setSelectionRange(1, 1);
    fireEvent.click(screen.getByTestId("quiz-key-space"));
    fireEvent.click(screen.getByTestId("quiz-key-fraction"));
    expect(input().value).toBe("1 /");
    expect(screen.queryByTestId("quiz-key-more")).toBeNull();
  });

  it("warns about a power the grader refuses, under the keys", () => {
    render(<Harness type="symbolic" initial="x^10" />);
    const problem = screen.getByTestId("quiz-written-readback");
    expect(problem).toHaveTextContent("whole numbers from −8 to 8");
    expect(input()).toHaveAttribute("aria-invalid", "true");
  });
});

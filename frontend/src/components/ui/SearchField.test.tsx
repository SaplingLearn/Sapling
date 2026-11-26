// @vitest-environment jsdom
import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, cleanup, fireEvent, act } from "@testing-library/react";
import React from "react";
import { SearchField, type SearchFieldProps } from "./SearchField";

afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

/** A controlled host, so typing really changes `value` the way a screen would. */
function Host(props: Partial<SearchFieldProps> & { initial?: string; onValue?: (v: string) => void }) {
  const { initial = "", onValue, ...rest } = props;
  const [value, setValue] = React.useState(initial);
  return (
    <SearchField
      label="Search your guides"
      placeholder="Search your guides"
      testid="guides-search"
      {...rest}
      value={value}
      onChange={(v) => {
        setValue(v);
        onValue?.(v);
      }}
    />
  );
}

const input = () => screen.getByTestId("guides-search") as HTMLInputElement;

describe("SearchField", () => {
  it("is a searchbox named by its label, not its placeholder", () => {
    render(<Host label="Search your study guides" />);
    const box = screen.getByRole("searchbox", { name: "Search your study guides" });
    expect(box).toBe(input());
    expect(box).toHaveAttribute("type", "search");
    expect(box).toHaveAttribute("placeholder", "Search your guides");
  });

  it("puts the testid on the native input and reports every keystroke", () => {
    const onValue = vi.fn();
    render(<Host onValue={onValue} />);
    fireEvent.change(input(), { target: { value: "mid" } });
    expect(onValue).toHaveBeenLastCalledWith("mid");
    expect(input().value).toBe("mid");
  });

  it("shows the clear button only while there is text, and clearing refocuses the input", () => {
    const onValue = vi.fn();
    render(<Host initial="" onValue={onValue} />);
    expect(screen.queryByRole("button", { name: "Clear search" })).toBeNull();

    fireEvent.change(input(), { target: { value: "midterm" } });
    const clear = screen.getByTestId("guides-search-clear");
    expect(clear).toHaveAttribute("type", "button");
    expect(clear).toHaveAccessibleName("Clear search");

    fireEvent.click(clear);
    expect(onValue).toHaveBeenLastCalledWith("");
    expect(input().value).toBe("");
    expect(document.activeElement).toBe(input());
    expect(screen.queryByRole("button", { name: "Clear search" })).toBeNull();
  });

  it("can hide the clear button", () => {
    render(<Host initial="midterm" clearable={false} />);
    expect(screen.queryByRole("button", { name: "Clear search" })).toBeNull();
  });

  describe("Escape is two-step", () => {
    it("with text, clears it and stops the event there", () => {
      // `outer` stands for a Dialog/Sheet's React onKeyDown; `onDocument` for
      // the document listeners Manage Courses and the Notetaker picker close on.
      const outer = vi.fn();
      const onDocument = vi.fn();
      document.addEventListener("keydown", onDocument);
      render(
        <div onKeyDown={outer}>
          <Host initial="midterm" />
        </div>,
      );
      const event = new KeyboardEvent("keydown", { key: "Escape", bubbles: true, cancelable: true });
      act(() => {
        input().dispatchEvent(event);
      });
      document.removeEventListener("keydown", onDocument);
      expect(input().value).toBe("");
      expect(event.defaultPrevented).toBe(true);
      expect(outer).not.toHaveBeenCalled();
      expect(onDocument).not.toHaveBeenCalled();
    });

    it("when empty, leaves Escape alone so a modal or Sheet can close", () => {
      const outer = vi.fn();
      const onDocument = vi.fn();
      document.addEventListener("keydown", onDocument);
      render(
        <div onKeyDown={outer}>
          <Host initial="" />
        </div>,
      );
      const event = new KeyboardEvent("keydown", { key: "Escape", bubbles: true, cancelable: true });
      act(() => {
        input().dispatchEvent(event);
      });
      document.removeEventListener("keydown", onDocument);
      expect(event.defaultPrevented).toBe(false);
      expect(outer).toHaveBeenCalledTimes(1);
      expect(onDocument).toHaveBeenCalledTimes(1);
    });

    it("can be turned off", () => {
      render(<Host initial="midterm" escapeClears={false} />);
      fireEvent.keyDown(input(), { key: "Escape" });
      expect(input().value).toBe("midterm");
    });

    it("lets the caller's onKeyDown run first and opt out with preventDefault", () => {
      const onKeyDown = vi.fn((e: React.KeyboardEvent) => e.preventDefault());
      render(<Host initial="midterm" onKeyDown={onKeyDown} />);
      fireEvent.keyDown(input(), { key: "Escape" });
      expect(onKeyDown).toHaveBeenCalledTimes(1);
      expect(input().value).toBe("midterm");
    });
  });

  describe("the / shortcut", () => {
    it("focuses the field from anywhere outside an editable element, and shows a hint", () => {
      render(
        <>
          <button type="button" data-testid="elsewhere">elsewhere</button>
          <Host shortcut="/" />
        </>,
      );
      expect(input()).toHaveAttribute("aria-keyshortcuts", "/");
      expect(screen.getByText("/")).toHaveAttribute("aria-hidden", "true");

      screen.getByTestId("elsewhere").focus();
      fireEvent.keyDown(screen.getByTestId("elsewhere"), { key: "/" });
      expect(document.activeElement).toBe(input());
    });

    it("does not steal / while the user is typing in another field", () => {
      render(
        <>
          <textarea data-testid="note" />
          <Host shortcut="/" />
        </>,
      );
      const note = screen.getByTestId("note");
      note.focus();
      fireEvent.keyDown(note, { key: "/" });
      expect(document.activeElement).toBe(note);
    });

    it("swaps the hint for the clear button once there is text", () => {
      render(<Host shortcut="/" initial="midterm" />);
      expect(screen.queryByText("/")).toBeNull();
      expect(screen.getByRole("button", { name: "Clear search" })).toBeInTheDocument();
    });

    it("does nothing without the prop", () => {
      render(
        <>
          <button type="button" data-testid="elsewhere">elsewhere</button>
          <Host />
        </>,
      );
      screen.getByTestId("elsewhere").focus();
      fireEvent.keyDown(screen.getByTestId("elsewhere"), { key: "/" });
      expect(document.activeElement).toBe(screen.getByTestId("elsewhere"));
    });
  });

  describe("onDebouncedChange", () => {
    it("fires once typing settles, with the latest value, and not on mount", () => {
      vi.useFakeTimers();
      const onDebounced = vi.fn();
      render(<Host initial="ri" onDebouncedChange={onDebounced} debounceMs={350} />);
      act(() => { vi.advanceTimersByTime(1000); });
      expect(onDebounced).not.toHaveBeenCalled();

      fireEvent.change(input(), { target: { value: "ric" } });
      act(() => { vi.advanceTimersByTime(200); });
      fireEvent.change(input(), { target: { value: "rich" } });
      act(() => { vi.advanceTimersByTime(349); });
      expect(onDebounced).not.toHaveBeenCalled();
      act(() => { vi.advanceTimersByTime(1); });
      expect(onDebounced).toHaveBeenCalledTimes(1);
      expect(onDebounced).toHaveBeenLastCalledWith("rich");
    });

    it("defaults to 200ms", () => {
      vi.useFakeTimers();
      const onDebounced = vi.fn();
      render(<Host onDebouncedChange={onDebounced} />);
      fireEvent.change(input(), { target: { value: "cs" } });
      act(() => { vi.advanceTimersByTime(199); });
      expect(onDebounced).not.toHaveBeenCalled();
      act(() => { vi.advanceTimersByTime(1); });
      expect(onDebounced).toHaveBeenCalledWith("cs");
    });

    it("reports a clear at once, without waiting out the debounce", () => {
      vi.useFakeTimers();
      const onDebounced = vi.fn();
      render(<Host initial="" onDebouncedChange={onDebounced} />);
      fireEvent.change(input(), { target: { value: "cs" } });
      act(() => { vi.advanceTimersByTime(200); });
      expect(onDebounced).toHaveBeenLastCalledWith("cs");

      fireEvent.change(input(), { target: { value: "cs 2" } });
      fireEvent.click(screen.getByRole("button", { name: "Clear search" }));
      expect(onDebounced).toHaveBeenLastCalledWith("");
      act(() => { vi.advanceTimersByTime(1000); });
      expect(onDebounced).toHaveBeenCalledTimes(2);
    });
  });

  it("announces `status` in a polite live region that exists from the first render", () => {
    const { rerender } = render(
      <SearchField label="Search your guides" value="" onChange={() => {}} status="" />,
    );
    const region = screen.getByRole("status");
    expect(region).toHaveTextContent("");
    rerender(<SearchField label="Search your guides" value="zz" onChange={() => {}} status="No guide matches “zz”." />);
    expect(screen.getByRole("status")).toBe(region);
    expect(region).toHaveTextContent("No guide matches “zz”.");
  });

  it("renders no live region when the caller does not use one", () => {
    render(<Host />);
    expect(screen.queryByRole("status")).toBeNull();
  });

  it("marks the input busy while loading", () => {
    render(<Host loading />);
    expect(input()).toHaveAttribute("aria-busy", "true");
  });

  it("is a search landmark only when asked", () => {
    const { rerender } = render(<SearchField label="Search documents" value="" onChange={() => {}} />);
    expect(screen.queryByRole("search")).toBeNull();
    rerender(<SearchField label="Search documents" value="" onChange={() => {}} landmark />);
    expect(screen.getByRole("search")).toContainElement(screen.getByRole("searchbox"));
  });

  it("renders trailing controls inside the field, before the clear button", () => {
    render(
      <Host
        initial="photo"
        trailing={<button type="button" data-testid="library-sort">Sort</button>}
      />,
    );
    const sort = screen.getByTestId("library-sort");
    const clear = screen.getByRole("button", { name: "Clear search" });
    expect(sort.compareDocumentPosition(clear) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    // No <label> around them: a label may not contain other controls.
    expect(input().closest("label")).toBeNull();
  });

  it("forwards inputRef and inputProps (a picker's combobox attributes)", () => {
    const ref = React.createRef<HTMLInputElement>();
    render(
      <Host
        inputRef={ref}
        inputProps={{ role: "combobox", "aria-expanded": true, "aria-controls": "topic-list" }}
      />,
    );
    expect(ref.current).toBe(input());
    const box = screen.getByRole("combobox", { name: "Search your guides" });
    expect(box).toHaveAttribute("aria-expanded", "true");
    expect(box).toHaveAttribute("aria-controls", "topic-list");
  });

  it("focuses the input when the wrapper's own padding is pressed", () => {
    const { container } = render(<Host />);
    const wrapper = container.querySelector(".search-field") as HTMLElement;
    fireEvent.mouseDown(wrapper);
    expect(document.activeElement).toBe(input());
  });

  it("applies size, variant and layout classes to the wrapper", () => {
    const { container } = render(
      <Host size="lg" variant="bare" className="guides-toolbar__search" style={{ maxWidth: 354 }} />,
    );
    const wrapper = container.querySelector(".search-field") as HTMLElement;
    expect(wrapper).toHaveClass("search-field--lg", "search-field--bare", "guides-toolbar__search");
    expect(wrapper.style.maxWidth).toBe("354px");
  });
});

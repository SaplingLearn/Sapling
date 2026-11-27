// @vitest-environment jsdom
import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, act, cleanup } from "@testing-library/react";
import { useOverlayBehaviour } from "./Dialog";

function Panel({ open }: { open: boolean }) {
  const { panelRef } = useOverlayBehaviour({ open, onClose: () => {} });
  return (
    <div ref={panelRef} tabIndex={-1} data-testid="panel">
      <button>Close</button>
      <input data-testid="field" />
    </div>
  );
}

describe("useOverlayBehaviour initial focus", () => {
  afterEach(() => { cleanup(); vi.useRealTimers(); });

  it("moves focus to the first focusable element after opening", () => {
    vi.useFakeTimers();
    render(<Panel open />);
    act(() => { vi.advanceTimersByTime(25); });
    expect(screen.getByRole("button", { name: "Close" })).toHaveFocus();
  });

  it("leaves focus where the user put it if they clicked in first", () => {
    vi.useFakeTimers();
    render(<Panel open />);
    // The user focuses the field before the 20ms focus pass runs.
    act(() => { screen.getByTestId("field").focus(); });
    act(() => { vi.advanceTimersByTime(25); });
    expect(screen.getByTestId("field")).toHaveFocus();
  });
});

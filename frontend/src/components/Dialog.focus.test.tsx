// @vitest-environment jsdom
/** Where a dialog's focus goes on opening, and what it must not take it from. */
import { act, cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import Dialog from "./Dialog";

beforeEach(() => { vi.useFakeTimers(); });
afterEach(() => { cleanup(); vi.useRealTimers(); });

const open = () =>
  render(
    <Dialog open onClose={() => {}} title="A dialog">
      <input aria-label="Name" />
    </Dialog>,
  );

describe("Dialog focus on opening", () => {
  it("moves focus into the panel", () => {
    open();
    act(() => { vi.advanceTimersByTime(50); });
    expect(screen.getByRole("dialog")).toContainElement(document.activeElement as HTMLElement);
  });

  it("leaves focus on a control the student reached first", () => {
    open();
    screen.getByLabelText("Name").focus();
    act(() => { vi.advanceTimersByTime(50); });
    expect(screen.getByLabelText("Name")).toHaveFocus();
  });
});

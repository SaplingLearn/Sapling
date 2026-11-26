// @vitest-environment jsdom
/**
 * The selection bar animates in and out (BulkBarReveal), and its Move To menu
 * opens and closes like every other Library menu.
 *
 * jsdom runs no CSS animations, so these pin the state the animation is driven
 * by: the phase, the keyframes each wrapper plays, and when the bar unmounts.
 */
import React from "react";
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { BULK_IN_MS, BULK_OUT_MS, BulkBar, BulkBarReveal, type BulkBarProps } from "./LibraryBits";
import { MENU_IN, MENU_OUT } from "./primitives";
import { twStyle } from "@/test-utils/twStyle";

const noop = () => {};
const BAR: Omit<BulkBarProps, "count"> = {
  isTrash: false, menuOpen: false, onMenu: noop, courses: [], folders: [],
  onMoveCourse: noop, onMoveFolder: noop, onRestore: noop, onDelete: noop,
  deleteConfirm: false, onClear: noop,
};

function Harness({ count, ...rest }: Partial<BulkBarProps> & { count: number }) {
  return (
    <BulkBarReveal open={count > 0}>
      <BulkBar {...BAR} {...rest} count={count} />
    </BulkBarReveal>
  );
}

const reveal = () => screen.getByTestId("library-bulk-reveal");
const clip = () => reveal().firstElementChild as HTMLElement;
const advance = (ms: number) => act(() => { vi.advanceTimersByTime(ms); });

beforeEach(() => { vi.useFakeTimers(); });
afterEach(() => { cleanup(); vi.useRealTimers(); });

describe("the selection bar's reveal", () => {
  it("renders nothing while nothing is selected", () => {
    render(<Harness count={0} />);
    expect(screen.queryByTestId("library-bulk-reveal")).toBeNull();
    expect(screen.queryByTestId("library-bulk-bar")).toBeNull();
  });

  it("enters by opening its row and dropping the bar in, then rests", () => {
    const view = render(<Harness count={0} />);
    view.rerender(<Harness count={1} />);

    expect(reveal().dataset.phase).toBe("in");
    expect(twStyle(reveal()).animation).toBe(
      `sapBulkRowIn ${BULK_IN_MS}ms cubic-bezier(0.2, 0.7, 0.2, 1) both`);
    expect(twStyle(clip()).animation).toBe(
      `sapBulkIn ${BULK_IN_MS}ms cubic-bezier(0.2, 0.7, 0.2, 1) both`);
    expect(clip()).toHaveTwStyle({ overflow: "hidden" });
    expect(screen.getByTestId("library-bulk-bar").textContent).toContain("1 Selected");

    advance(BULK_IN_MS);
    // At rest both wrappers are inert: no animation, and no clip, so the bar
    // is exactly the bar and the Move To menu can hang out of it.
    expect(reveal().dataset.phase).toBe("idle");
    expect(twStyle(reveal()).animation).toBe("");
    expect(twStyle(clip()).animation).toBe("");
    expect(twStyle(clip()).overflow).toBe("");
  });

  it("a count change while it is open does not replay the entrance", () => {
    const view = render(<Harness count={0} />);
    view.rerender(<Harness count={1} />);
    const bar = screen.getByTestId("library-bulk-bar");
    const entrance = twStyle(clip()).animation;

    // Mid-entrance: same element, same animation, and the timer is not reset.
    advance(BULK_IN_MS / 2);
    view.rerender(<Harness count={2} />);
    expect(screen.getByTestId("library-bulk-bar")).toBe(bar);
    expect(twStyle(clip()).animation).toBe(entrance);
    expect(bar.textContent).toContain("2 Selected");
    advance(BULK_IN_MS / 2);
    expect(reveal().dataset.phase).toBe("idle");

    // At rest: it stays at rest.
    view.rerender(<Harness count={3} />);
    expect(screen.getByTestId("library-bulk-bar")).toBe(bar);
    expect(reveal().dataset.phase).toBe("idle");
    expect(twStyle(clip()).animation).toBe("");
    expect(bar.textContent).toContain("3 Selected");
  });

  it("clearing keeps it mounted through the exit, showing the last count, then removes it", () => {
    const view = render(<Harness count={0} />);
    view.rerender(<Harness count={2} />);
    advance(BULK_IN_MS);

    view.rerender(<Harness count={0} />);
    expect(reveal().dataset.phase).toBe("out");
    expect(twStyle(reveal()).animation).toBe(
      `sapBulkRowOut ${BULK_OUT_MS}ms cubic-bezier(0.4, 0, 1, 1) both`);
    expect(twStyle(clip()).animation).toBe(
      `sapBulkOut ${BULK_OUT_MS}ms cubic-bezier(0.4, 0, 1, 1) both`);
    expect(clip()).toHaveTwStyle({ pointerEvents: "none" });
    // What it showed last, not "0 Selected".
    expect(screen.getByTestId("library-bulk-bar").textContent).toContain("2 Selected");

    advance(BULK_OUT_MS - 1);
    expect(screen.queryByTestId("library-bulk-bar")).not.toBeNull();
    advance(1);
    expect(screen.queryByTestId("library-bulk-reveal")).toBeNull();
    expect(screen.queryByTestId("library-bulk-bar")).toBeNull();
  });

  it("selecting again mid-exit turns it back around instead of unmounting", () => {
    const view = render(<Harness count={0} />);
    view.rerender(<Harness count={1} />);
    advance(BULK_IN_MS);
    view.rerender(<Harness count={0} />);
    advance(BULK_OUT_MS / 2);

    view.rerender(<Harness count={1} />);
    expect(reveal().dataset.phase).toBe("in");
    expect(twStyle(clip()).pointerEvents).toBe("");
    advance(BULK_OUT_MS);
    expect(screen.getByTestId("library-bulk-bar").textContent).toContain("1 Selected");
    advance(BULK_IN_MS);
    expect(reveal().dataset.phase).toBe("idle");
  });
});

describe("the Move To menu", () => {
  it("opens with the Library's menu entrance and closes with its exit", () => {
    const view = render(<Harness count={1} menuOpen />);
    const menu = screen.getByTestId("library-bulk-menu");
    expect(twStyle(menu).animation).toBe(MENU_IN);
    expect(menu).toHaveTwStyle({ transformOrigin: "top right" });

    view.rerender(<Harness count={1} menuOpen menuClosing />);
    expect(twStyle(screen.getByTestId("library-bulk-menu")).animation).toBe(MENU_OUT);
  });

  it("is reached from the Move To button", () => {
    const onMenu = vi.fn();
    render(<Harness count={1} onMenu={onMenu} />);
    fireEvent.click(screen.getByText("Move To"));
    expect(onMenu).toHaveBeenCalledWith(true);
  });
});


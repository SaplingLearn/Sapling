// @vitest-environment jsdom
/**
 * The corner Report button rises above any control under it (useCornerDodge):
 * the tutor composer's Send, a card's action scrolled to the bottom edge.
 */
import React from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, render, screen } from "@testing-library/react";
import { DODGE_GAP, SETTLE_MS, liftFor, nextLift, type Box } from "./useCornerDodge";

vi.mock("next/navigation", () => ({ usePathname: () => "/learn" }));
vi.mock("./ReportIssueFlow", () => ({ ReportIssueFlow: () => null }));

import { ShellCornerActions } from "./ShellActions";

/** A page element with a laid-out box, for the hit test below. */
function placed(tag: string, box: Box, parent: HTMLElement = document.body): HTMLElement {
  const el = document.createElement(tag);
  el.getBoundingClientRect = () => ({ ...box, x: box.left, y: box.top, width: box.right - box.left, height: box.bottom - box.top, toJSON: () => box }) as DOMRect;
  parent.appendChild(el);
  return el;
}

const inside = (box: DOMRect, x: number, y: number) => x >= box.left && x <= box.right && y >= box.top && y <= box.bottom;

/** `document.elementsFromPoint` over every element that has a box (jsdom has no layout). */
function hitTestPlacedElements() {
  document.elementsFromPoint = (x: number, y: number) =>
    [...document.querySelectorAll<HTMLElement>("*")].filter((el) => {
      const rect = el.getBoundingClientRect();
      return rect.width > 0 && inside(rect, x, y);
    }).reverse();
}

const RESTING: Box = { left: 900, right: 930, top: 700, bottom: 730 };

beforeEach(() => {
  hitTestPlacedElements();
});

afterEach(() => {
  cleanup();
  document.body.innerHTML = "";
  vi.useRealTimers();
});

describe("liftFor", () => {
  const own = () => placed("div", RESTING);

  it("stays put when nothing is under it", () => {
    placed("button", { left: 100, right: 200, top: 700, bottom: 730 }); // elsewhere on the row
    expect(liftFor(RESTING, own(), 240)).toBe(0);
  });

  it("rises just above a control under it", () => {
    placed("button", { left: 880, right: 940, top: 690, bottom: 726 }); // the composer's Send
    expect(liftFor(RESTING, own(), 240)).toBe(730 - 690 + DODGE_GAP);
  });

  it("keeps rising past a control its first rise would cover", () => {
    placed("button", { left: 880, right: 940, top: 690, bottom: 726 });
    placed("textarea", { left: 600, right: 940, top: 640, bottom: 686 }); // above Send, under the first rise
    expect(liftFor(RESTING, own(), 240)).toBe(730 - 640 + DODGE_GAP);
  });

  it("counts a control by its own box when the hit is on its content", () => {
    const button = placed("button", { left: 880, right: 940, top: 680, bottom: 726 });
    placed("span", { left: 890, right: 935, top: 690, bottom: 720 }, button); // the label inside it
    expect(liftFor(RESTING, own(), 240)).toBe(730 - 680 + DODGE_GAP);
  });

  it("ignores plain content and its own controls", () => {
    placed("p", { left: 0, right: 1000, top: 600, bottom: 760 });
    const self = own();
    placed("button", RESTING, self);
    expect(liftFor(RESTING, self, 240)).toBe(0);
  });

  it("never rises past its cap", () => {
    placed("textarea", { left: 0, right: 1000, top: 200, bottom: 760 });
    expect(liftFor(RESTING, own(), 120)).toBe(120);
  });
});

describe("nextLift", () => {
  const own = () => placed("div", RESTING);

  it("goes back to rest once its spot is clear", () => {
    expect(nextLift(RESTING, own(), 240, 48)).toBe(0);
  });

  it("stays where it is while that spot is clear, rather than hopping to a new one", () => {
    placed("button", { left: 880, right: 940, top: 690, bottom: 726 }); // still under the resting spot
    // risen 100px earlier (above a control that has since scrolled away): still clear, so it stays
    expect(nextLift(RESTING, own(), 240, 100)).toBe(100);
  });

  it("finds the lowest clear spot when where it is is covered too", () => {
    placed("button", { left: 880, right: 940, top: 690, bottom: 726 });
    placed("button", { left: 880, right: 940, top: 590, bottom: 640 }); // under the 100px spot
    expect(nextLift(RESTING, own(), 240, 100)).toBe(730 - 690 + DODGE_GAP);
  });
});

describe("ShellCornerActions", () => {
  /** The corner's box follows its transform, as a laid-out one does. */
  function layOut(corner: HTMLElement) {
    corner.getBoundingClientRect = () => {
      const lift = Number(/translateY\((-?[\d.]+)px\)/.exec(corner.style.transform)?.[1] ?? 0);
      const box = { ...RESTING, top: RESTING.top + lift, bottom: RESTING.bottom + lift };
      return { ...box, x: box.left, y: box.top, width: 30, height: 30, toJSON: () => box } as DOMRect;
    };
  }

  it("rises above the page's control once the page settles, and drops back when it goes", async () => {
    vi.useFakeTimers();
    const send = placed("button", { left: 880, right: 940, top: 690, bottom: 726 });
    const corner = document.createElement("div");
    document.body.appendChild(corner);
    render(<ShellCornerActions />, { container: corner });
    const actions = screen.getByTestId("shell-corner-actions");
    layOut(actions);
    await act(async () => { vi.advanceTimersByTime(SETTLE_MS + 1); });
    expect(actions.style.transform).toBe(`translateY(-${730 - 690 + DODGE_GAP}px)`);
    await act(async () => {
      send.remove();
      await Promise.resolve(); // the MutationObserver's microtask
      vi.advanceTimersByTime(SETTLE_MS + 1);
    });
    expect(actions.style.transform).toBe("");
  });

  it("does nothing until the page has been quiet for a moment", async () => {
    vi.useFakeTimers();
    placed("button", { left: 880, right: 940, top: 690, bottom: 726 });
    const corner = document.createElement("div");
    document.body.appendChild(corner);
    render(<ShellCornerActions />, { container: corner });
    const actions = screen.getByTestId("shell-corner-actions");
    layOut(actions);
    await act(async () => { vi.advanceTimersByTime(SETTLE_MS / 2); });
    document.dispatchEvent(new Event("scroll")); // still scrolling: the wait starts over
    await act(async () => { vi.advanceTimersByTime(SETTLE_MS / 2 + 10); });
    expect(actions.style.transform).toBe("");
    await act(async () => { vi.advanceTimersByTime(SETTLE_MS); });
    expect(actions.style.transform).not.toBe("");
  });
});

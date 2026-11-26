// @vitest-environment jsdom
/**
 * The List ⇄ Panel switcher: one thumb, measured under the selected tab, that
 * moves when the value changes; Left/Right switch from the keyboard.
 *
 * jsdom does no layout, so each tab's offsetLeft/offsetWidth is stubbed from
 * a table keyed on its testid — as a browser would report them for a track
 * with 4px padding and a 2px gap.
 */
import React from "react";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterAll, afterEach, beforeAll, describe, expect, it, vi } from "vitest";

import { ViewSwitcher, type ViewSwitcherOption } from "./ViewSwitcher";
import { twStyle } from "@/test-utils/twStyle";

type View = "list" | "panel";
const OPTIONS: ViewSwitcherOption<View>[] = [
  { key: "list", label: "List" },
  { key: "panel", label: "Panel" },
];

/** List: 4px in, 72 wide. Panel: after List and the 2px gap, 84 wide. */
const BOXES: Record<string, { left: number; width: number }> = {
  "library-view-list": { left: 4, width: 72 },
  "library-view-panel": { left: 78, width: 84 },
};
const box = (el: HTMLElement) => BOXES[el.dataset.testid ?? ""] ?? { left: 0, width: 0 };

const originals = {
  offsetLeft: Object.getOwnPropertyDescriptor(HTMLElement.prototype, "offsetLeft"),
  offsetWidth: Object.getOwnPropertyDescriptor(HTMLElement.prototype, "offsetWidth"),
};

beforeAll(() => {
  Object.defineProperty(HTMLElement.prototype, "offsetLeft", {
    configurable: true, get(this: HTMLElement) { return box(this).left; },
  });
  Object.defineProperty(HTMLElement.prototype, "offsetWidth", {
    configurable: true, get(this: HTMLElement) { return box(this).width; },
  });
});
afterAll(() => {
  for (const [name, d] of Object.entries(originals)) {
    if (d) Object.defineProperty(HTMLElement.prototype, name, d);
  }
});
afterEach(() => { cleanup(); });

function Harness({ initial = "list" as View, onChange = (_: View) => {} }) {
  const [value, setValue] = React.useState<View>(initial);
  return (
    <ViewSwitcher
      options={OPTIONS}
      value={value}
      onChange={v => { setValue(v); onChange(v); }}
      label="Layout"
      testIdPrefix="library-view"
      style={{ marginLeft: 16 }}
    />
  );
}

const thumb = () => screen.getByTestId("library-view-thumb");
const tab = (k: View) => screen.getByTestId(`library-view-${k}`);

describe("the List ⇄ Panel switcher", () => {
  it("lays its one thumb under the selected tab on first paint, in the design's pill", () => {
    render(<Harness />);
    expect(thumb()).toHaveTwStyle({ transform: "translateX(4px)" });
    expect(thumb()).toHaveTwStyle({ width: "72px" });
    expect(thumb()).toHaveTwStyle({ borderRadius: "9px" });
    expect(thumb()).toHaveTwStyle({ background: "rgb(253, 252, 249)" });
    expect(thumb()).toHaveTwStyle({ boxShadow: "0 1px 2px rgba(25,37,11,0.10)" });
    // The slide is a class (so reduced motion can switch it off), never an
    // entrance: the thumb is created where it rests.
    expect(thumb()).toHaveClass("sapSwitchThumb");
    expect(thumb().className).not.toMatch(/animate|\[animation/);
    expect(twStyle(thumb()).animation).toBe("");
    // Only one pill: the tabs themselves are bare once the thumb is measured.
    expect(tab("list")).toHaveTwStyle({ background: "transparent" });
    expect(tab("list")).toHaveTwStyle({ color: "rgb(26, 24, 20)" });
    expect(tab("panel")).toHaveTwStyle({ color: "rgb(111, 104, 87)" });
  });

  it("keeps the track's resting look: padding, gap, radius, colour and margin", () => {
    render(<Harness />);
    const track = screen.getByRole("tablist", { name: "Layout" });
    expect(track).toHaveTwStyle({ padding: "4px" });
    expect(track).toHaveTwStyle({ gap: "2px" });
    expect(track).toHaveTwStyle({ height: "40px" });
    expect(track).toHaveTwStyle({ borderRadius: "12px" });
    expect(track).toHaveTwStyle({ background: "#F4F1EA" });
    expect(track).toHaveTwStyle({ marginLeft: "16px" });
    expect(tab("list")).toHaveTwStyle({ borderRadius: "9px" });
    expect(tab("list")).toHaveTwStyle({ padding: "0px 14px" });
  });

  it("moves the thumb to the tab that is chosen, without a second thumb", () => {
    render(<Harness />);
    const first = thumb();
    fireEvent.click(tab("panel"));

    expect(tab("panel").getAttribute("aria-selected")).toBe("true");
    expect(tab("list").getAttribute("aria-selected")).toBe("false");
    // The same element, moved: that is what lets the transition slide it.
    expect(thumb()).toBe(first);
    expect(thumb()).toHaveTwStyle({ transform: "translateX(78px)" });
    expect(thumb()).toHaveTwStyle({ width: "84px" });
    expect(screen.getAllByTestId("library-view-thumb")).toHaveLength(1);
    expect(tab("panel")).toHaveTwStyle({ color: "rgb(26, 24, 20)" });
  });

  it("re-measures on resize", () => {
    render(<Harness />);
    BOXES["library-view-list"] = { left: 4, width: 90 };
    try {
      fireEvent(window, new Event("resize"));
      expect(thumb()).toHaveTwStyle({ width: "90px" });
    } finally {
      BOXES["library-view-list"] = { left: 4, width: 72 };
    }
  });

  it("Left and Right move to the neighbour, select it and focus it, wrapping", () => {
    const onChange = vi.fn();
    render(<Harness onChange={onChange} />);
    // Only the selected tab is in the Tab order.
    expect(tab("list").tabIndex).toBe(0);
    expect(tab("panel").tabIndex).toBe(-1);

    tab("list").focus();
    fireEvent.keyDown(tab("list"), { key: "ArrowRight" });
    expect(onChange).toHaveBeenLastCalledWith("panel");
    expect(tab("panel").getAttribute("aria-selected")).toBe("true");
    expect(document.activeElement).toBe(tab("panel"));
    expect(thumb()).toHaveTwStyle({ transform: "translateX(78px)" });

    fireEvent.keyDown(tab("panel"), { key: "ArrowRight" });
    expect(onChange).toHaveBeenLastCalledWith("list");
    expect(document.activeElement).toBe(tab("list"));

    fireEvent.keyDown(tab("list"), { key: "ArrowLeft" });
    expect(onChange).toHaveBeenLastCalledWith("panel");
    expect(thumb()).toHaveTwStyle({ transform: "translateX(78px)" });

    fireEvent.keyDown(tab("panel"), { key: "Enter" });
    expect(onChange).toHaveBeenCalledTimes(3);
  });
});

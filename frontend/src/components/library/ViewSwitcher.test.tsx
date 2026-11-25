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
    expect(thumb().style.transform).toBe("translateX(4px)");
    expect(thumb().style.width).toBe("72px");
    expect(thumb().style.borderRadius).toBe("9px");
    expect(thumb().style.background).toBe("rgb(253, 252, 249)");
    expect(thumb().style.boxShadow).toBe("0 1px 2px rgba(25,37,11,0.10)");
    // The slide is a class (so reduced motion can switch it off), never an
    // entrance: the thumb is created where it rests.
    expect(thumb().className).toBe("sapSwitchThumb");
    expect(thumb().style.animation).toBe("");
    // Only one pill: the tabs themselves are bare once the thumb is measured.
    expect(tab("list").style.background).toBe("transparent");
    expect(tab("list").style.color).toBe("rgb(26, 24, 20)");
    expect(tab("panel").style.color).toBe("rgb(111, 104, 87)");
  });

  it("keeps the track's resting look: padding, gap, radius, colour and margin", () => {
    render(<Harness />);
    const track = screen.getByRole("tablist", { name: "Layout" });
    expect(track.style.padding).toBe("4px");
    expect(track.style.gap).toBe("2px");
    expect(track.style.height).toBe("40px");
    expect(track.style.borderRadius).toBe("12px");
    expect(track.style.background).toBe("rgb(244, 241, 234)");
    expect(track.style.marginLeft).toBe("16px");
    expect(tab("list").style.borderRadius).toBe("9px");
    expect(tab("list").style.padding).toBe("0px 14px");
  });

  it("moves the thumb to the tab that is chosen, without a second thumb", () => {
    render(<Harness />);
    const first = thumb();
    fireEvent.click(tab("panel"));

    expect(tab("panel").getAttribute("aria-selected")).toBe("true");
    expect(tab("list").getAttribute("aria-selected")).toBe("false");
    // The same element, moved: that is what lets the transition slide it.
    expect(thumb()).toBe(first);
    expect(thumb().style.transform).toBe("translateX(78px)");
    expect(thumb().style.width).toBe("84px");
    expect(screen.getAllByTestId("library-view-thumb")).toHaveLength(1);
    expect(tab("panel").style.color).toBe("rgb(26, 24, 20)");
  });

  it("re-measures on resize", () => {
    render(<Harness />);
    BOXES["library-view-list"] = { left: 4, width: 90 };
    try {
      fireEvent(window, new Event("resize"));
      expect(thumb().style.width).toBe("90px");
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
    expect(thumb().style.transform).toBe("translateX(78px)");

    fireEvent.keyDown(tab("panel"), { key: "ArrowRight" });
    expect(onChange).toHaveBeenLastCalledWith("list");
    expect(document.activeElement).toBe(tab("list"));

    fireEvent.keyDown(tab("list"), { key: "ArrowLeft" });
    expect(onChange).toHaveBeenLastCalledWith("panel");
    expect(thumb().style.transform).toBe("translateX(78px)");

    fireEvent.keyDown(tab("panel"), { key: "Enter" });
    expect(onChange).toHaveBeenCalledTimes(3);
  });
});

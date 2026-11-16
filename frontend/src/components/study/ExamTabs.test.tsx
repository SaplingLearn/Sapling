// @vitest-environment jsdom
/**
 * The selected tab's line: one line, under the selected tab, sliding over
 * from the tab that had it. jsdom has no layout, so the tabs' offsets are
 * given here; the slide itself is a fake Web Animations call.
 */
import React from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { ExamTabs, tabStep, type ExamTabsProps } from "./ExamTabs";
import { HUB_EASE, HUB_SWITCH_MS } from "./hubMotion";
import type { Assessment } from "./studyModel";

const TODAY = new Date(2026, 10, 8, 12);
const exam = (id: string, title: string, iso: string): Assessment => ({ id, type: "Exam", rawType: "exam", title, iso });
const EXAMS = [exam("e1", "Exam 1", "2026-11-01"), exam("e2", "Midterm 2", "2026-11-18"), exam("fin", "Final", "2026-12-15")];
/** Where each tab sits in the row: left edge and width. */
const PLACE: Record<string, [number, number]> = { e1: [0, 60], e2: [88, 90], fin: [206, 45] };

const tabsProps = (selected: string | null, over: Partial<ExamTabsProps> = {}): ExamTabsProps => ({
  courseId: "c1", courseLabel: "CS101", exams: EXAMS, exam: EXAMS.find(e => e.id === selected) ?? null,
  upcoming: [], soon: 0, today: TODAY, bellOpen: false, onBell: () => {}, onSelectExam: () => {},
  onPickDeadline: () => {}, onAdd: () => {}, onManage: () => {}, ...over,
});

type Slide = { el: HTMLElement; frames: Keyframe[]; timing: KeyframeAnimationOptions; cancel: ReturnType<typeof vi.fn> };
let slides: Slide[];
let reduced: boolean;
const realMatchMedia = window.matchMedia;
const lines = () => [...document.querySelectorAll<HTMLElement>("[data-tab-line]")];

beforeEach(() => {
  slides = [];
  reduced = false;
  window.matchMedia = ((query: string) => ({ matches: reduced && query.includes("reduce") })) as unknown as typeof window.matchMedia;
  const placeOf = (el: HTMLElement) => PLACE[el.dataset.tab ?? ""] ?? [0, 0];
  Object.defineProperty(HTMLElement.prototype, "offsetLeft", { configurable: true, get(this: HTMLElement) { return placeOf(this)[0]; } });
  Object.defineProperty(HTMLElement.prototype, "offsetWidth", { configurable: true, get(this: HTMLElement) { return placeOf(this)[1]; } });
  HTMLElement.prototype.animate = function (this: HTMLElement, frames: Keyframe[], timing: KeyframeAnimationOptions) {
    const slide = { el: this, frames, timing, cancel: vi.fn() };
    slides.push(slide);
    return slide as unknown as Animation;
  } as unknown as typeof HTMLElement.prototype.animate;
});
afterEach(() => {
  cleanup();
  window.matchMedia = realMatchMedia;
  for (const prop of ["offsetLeft", "offsetWidth", "animate"]) delete (HTMLElement.prototype as unknown as Record<string, unknown>)[prop];
});

describe("ExamTabs' selected line", () => {
  it("is one line, inside the selected tab, and nothing slides on first paint", () => {
    render(<ExamTabs {...tabsProps("e2")} />);
    expect(lines()).toHaveLength(1);
    expect(screen.getByRole("tab", { selected: true }).contains(lines()[0])).toBe(true);
    expect(lines()[0].getAttribute("aria-hidden")).toBe("true");
    // The tab's name is still only its title and date.
    expect(screen.getByRole("tab", { selected: true }).textContent).toBe("Midterm 2Wed, Nov 18");
    expect(slides).toEqual([]);
  });

  it("slides from the tab that was selected, starting at its place and width, on the hub's clock", () => {
    const { rerender } = render(<ExamTabs {...tabsProps("e2")} />);
    rerender(<ExamTabs {...tabsProps("e1")} />);
    expect(lines()).toHaveLength(1);
    expect(screen.getByRole("tab", { name: /Exam 1/ }).contains(lines()[0])).toBe(true);
    expect(slides).toHaveLength(1);
    expect(slides[0].el).toBe(lines()[0]);
    // From Midterm 2 (88, 90 wide) to Exam 1 (0, 60 wide): 88px right and half as wide again.
    expect(slides[0].frames).toEqual([{ transform: "translateX(88px) scaleX(1.5)" }, { transform: "none" }]);
    // The whole length of the switch: the line never waits for the content swap.
    expect(slides[0].timing).toEqual({ delay: 0, duration: HUB_SWITCH_MS, easing: HUB_EASE });
    expect(lines()[0].style.transformOrigin).toBe("0 50%");
  });

  it("a second switch mid-slide cancels the first and starts from the tab just left", () => {
    const { rerender } = render(<ExamTabs {...tabsProps("e2")} />);
    rerender(<ExamTabs {...tabsProps("e1")} />);
    rerender(<ExamTabs {...tabsProps("fin")} />);
    expect(slides).toHaveLength(2);
    expect(slides[0].cancel).toHaveBeenCalledTimes(1);
    expect(slides[1].frames[0]).toEqual({ transform: `translateX(-206px) scaleX(${60 / 45})` });
    expect(lines()).toHaveLength(1);
    expect(screen.getByRole("tab", { name: /Final/ }).contains(lines()[0])).toBe(true);
  });

  it("does not slide in from a tab that is no longer there, or to no tab at all", () => {
    const { rerender } = render(<ExamTabs {...tabsProps("e2")} />);
    rerender(<ExamTabs {...tabsProps("fin", { exams: [EXAMS[2]] })} />);
    rerender(<ExamTabs {...tabsProps(null, { exams: [] })} />);
    expect(slides).toEqual([]);
    expect(lines()).toEqual([]);
  });

  it("under reduced motion the line is simply under the new tab", () => {
    reduced = true;
    const { rerender } = render(<ExamTabs {...tabsProps("e2")} />);
    rerender(<ExamTabs {...tabsProps("fin")} />);
    expect(slides).toEqual([]);
    expect(screen.getByRole("tab", { name: /Final/ }).contains(lines()[0])).toBe(true);
    expect(lines()[0].style.transform).toBe("");
  });

  it("unmounting cancels a slide in flight", () => {
    const { rerender, unmount } = render(<ExamTabs {...tabsProps("e2")} />);
    rerender(<ExamTabs {...tabsProps("e1")} />);
    unmount();
    expect(slides[0].cancel).toHaveBeenCalledTimes(1);
  });
});

describe("ExamTabs' tabs (WAI-ARIA tabs, automatic activation)", () => {
  /** A row whose selection follows `onSelectExam`, as the hub's does. */
  function Row({ initial, onSelect }: { initial: string; onSelect?: (id: string) => void }) {
    const [selected, setSelected] = React.useState(initial);
    return <ExamTabs {...tabsProps(selected, { onSelectExam: id => { onSelect?.(id); setSelected(id); } })} />;
  }
  const tabStops = () => screen.getAllByRole("tab").filter(t => t.tabIndex === 0).map(t => t.dataset.tab);

  it("controls the readiness band and the roadmap, and only the selected tab is in the Tab order", () => {
    render(<ExamTabs {...tabsProps("e2")} />);
    for (const tab of screen.getAllByRole("tab")) {
      expect(tab.getAttribute("aria-controls")).toBe("study-hub-readiness study-hub-roadmap");
    }
    expect(tabStops()).toEqual(["e2"]);
  });

  it("with no tab selected, the first one is the Tab stop", () => {
    render(<ExamTabs {...tabsProps(null)} />);
    expect(tabStops()).toEqual(["e1"]);
  });

  it("the arrow keys, Home and End select the tab they land on and move focus to it", () => {
    const onSelect = vi.fn();
    render(<Row initial="e2" onSelect={onSelect} />);
    const list = screen.getByRole("tablist", { name: "Exams" });
    const tab = (id: string) => screen.getAllByRole("tab").find(t => t.dataset.tab === id)!;
    tab("e2").focus();
    fireEvent.keyDown(document.activeElement!, { key: "ArrowRight" });
    expect(document.activeElement).toBe(tab("fin"));
    expect(tab("fin").getAttribute("aria-selected")).toBe("true");
    expect(tabStops()).toEqual(["fin"]);
    // The arrows wrap round the row.
    fireEvent.keyDown(document.activeElement!, { key: "ArrowRight" });
    expect(document.activeElement).toBe(tab("e1"));
    fireEvent.keyDown(document.activeElement!, { key: "ArrowLeft" });
    expect(document.activeElement).toBe(tab("fin"));
    fireEvent.keyDown(document.activeElement!, { key: "Home" });
    expect(document.activeElement).toBe(tab("e1"));
    fireEvent.keyDown(document.activeElement!, { key: "End" });
    expect(document.activeElement).toBe(tab("fin"));
    expect(onSelect.mock.calls.map(([id]) => id)).toEqual(["fin", "e1", "fin", "e1", "fin"]);
    // Any other key is the page's.
    fireEvent.keyDown(document.activeElement!, { key: "ArrowDown" });
    expect(onSelect).toHaveBeenCalledTimes(5);
    expect(list.contains(document.activeElement)).toBe(true);
  });

  it("with no exam there is no tab list: the add link stands alone", () => {
    render(<ExamTabs {...tabsProps(null, { exams: [] })} />);
    expect(screen.queryByRole("tablist")).toBeNull();
    expect(screen.getByRole("button", { name: "+ Add Exam or Deadline" })).toBeTruthy();
  });
});

describe("tabStep", () => {
  it("wraps the arrows and jumps to the ends; any other key is not a move", () => {
    expect([tabStep("ArrowRight", 2, 3), tabStep("ArrowLeft", 0, 3), tabStep("Home", 2, 3), tabStep("End", 0, 3)]).toEqual([0, 2, 0, 2]);
    expect(tabStep("Enter", 1, 3)).toBeNull();
  });
});

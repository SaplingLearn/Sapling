// @vitest-environment jsdom
/**
 * The selected tab's line: one line, under the selected tab, sliding over
 * from the tab that had it. jsdom has no layout, so the tabs' offsets are
 * given here; the slide itself is a fake Web Animations call.
 */
import React from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { ExamTabs, type ExamTabsProps } from "./ExamTabs";
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
    expect(slides[0].timing).toEqual({ duration: HUB_SWITCH_MS, easing: HUB_EASE });
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

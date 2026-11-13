// @vitest-environment jsdom
/**
 * useFlip against a fake Web Animations API: what it starts for a change,
 * what it leaves in the DOM, and that an interruption or reduced motion
 * leaves nothing behind. jsdom has no layout, so each element's offsets are
 * read from `data-x` / `data-y` here. The motion itself is not exercised.
 */
import React from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render } from "@testing-library/react";
import { HUB_EASE, HUB_STAGGER_MS, HUB_SWITCH_MS } from "./hubMotion";
import { useFlip } from "./useFlip";

type Columns = Record<string, Record<string, number>>;
type Started = { el: HTMLElement; frames: Keyframe[]; timing: KeyframeAnimationOptions; anim: { cancel: ReturnType<typeof vi.fn>; onfinish: null | (() => void) } };

/** Columns side by side (216px apart), each with tiles at the given y; `label` is a line of text keyed on what it says. */
function Board({ columns, trigger, height = 0, label, keyed = true, rootKey = "" }: { columns: Columns; trigger: string; height?: number; label?: string; keyed?: boolean; rootKey?: string }) {
  const root = React.useRef<HTMLDivElement | null>(null);
  useFlip(root, trigger);
  return (
    <section>
      <div ref={root} key={rootKey} data-testid="root" data-h={height}>
        {label && <span key={keyed ? label : "label"} data-flip={`label:${label}`} data-flip-how="fade" data-x={90} data-y={4}>{label}</span>}
        {Object.entries(columns).map(([col, tiles], i) => (
          <div key={col} data-flip={`col:${col}`} data-x={i * 216} className="colEnter">
            {Object.entries(tiles).map(([tile, y]) => (
              <button key={tile} data-flip={`tile:${tile}`} data-testid={`tile-${tile}`} data-y={y}>{tile}</button>
            ))}
          </div>
        ))}
      </div>
    </section>
  );
}

let started: Started[];
let reduced: boolean;
const realMatchMedia = window.matchMedia;
const offsets = ["offsetLeft", "offsetTop", "offsetWidth", "offsetHeight"] as const;
const dataOf: Record<(typeof offsets)[number], string> = { offsetLeft: "x", offsetTop: "y", offsetWidth: "w", offsetHeight: "h" };

beforeEach(() => {
  started = [];
  reduced = false;
  window.matchMedia = ((query: string) => ({ matches: reduced && query.includes("reduce") })) as unknown as typeof window.matchMedia;
  for (const prop of offsets) {
    Object.defineProperty(HTMLElement.prototype, prop, {
      configurable: true,
      get(this: HTMLElement) { return Number(this.dataset[dataOf[prop]] || 0); },
    });
  }
  HTMLElement.prototype.animate = function (this: HTMLElement, frames: Keyframe[], timing: KeyframeAnimationOptions) {
    const anim = { cancel: vi.fn(), onfinish: null };
    started.push({ el: this, frames, timing, anim });
    return anim as unknown as Animation;
  } as unknown as typeof HTMLElement.prototype.animate;
});
afterEach(() => {
  cleanup();
  window.matchMedia = realMatchMedia;
  for (const prop of offsets) delete (HTMLElement.prototype as unknown as Record<string, unknown>)[prop];
  delete (HTMLElement.prototype as unknown as Record<string, unknown>).animate;
});

const WHOLE: Columns = { a: { 1: 30, 2: 76 }, b: { 3: 30, 4: 76 } };
/** Column a is gone (so b sits where it was); in b, tile 3 is gone and tile 4 moved up. */
const EXAM: Columns = { b: { 4: 30 } };
const ghosts = (root: HTMLElement) => [...root.querySelectorAll<HTMLElement>("[inert]")];
const startedOn = (el: Element) => started.filter(s => s.el === el);

describe("useFlip", () => {
  it("starts nothing on mount, or on a commit with the same trigger", () => {
    const { rerender, getByTestId } = render(<Board columns={WHOLE} trigger="" />);
    rerender(<Board columns={EXAM} trigger="" />);
    expect(started).toEqual([]);
    expect(ghosts(getByTestId("root"))).toEqual([]);
  });

  it("slides what stayed, from where it was", () => {
    const { rerender, getByTestId } = render(<Board columns={WHOLE} trigger="" />);
    rerender(<Board columns={EXAM} trigger="e1" />);
    const col = getByTestId("root").querySelector('[data-flip="col:b"]')!;
    expect(startedOn(col).map(s => s.frames)).toEqual([[{ transform: "translate(216px, 0px)" }, { transform: "none" }]]);
    expect(startedOn(getByTestId("tile-4")).map(s => s.frames)).toEqual([[{ transform: "translate(0px, 46px)" }, { transform: "none" }]]);
  });

  it("fades out a copy of what went, where it was, out of reach", () => {
    const { rerender, getByTestId } = render(<Board columns={WHOLE} trigger="" />);
    rerender(<Board columns={EXAM} trigger="e1" />);
    const root = getByTestId("root");
    const [tile, column] = ghosts(root);
    expect(ghosts(root)).toHaveLength(2); // column a whole (not its tiles one by one), and tile 3
    // Tile 3's copy is in its column, at its old place there.
    expect(tile.parentElement).toBe(root.querySelector('[data-flip="col:b"]'));
    expect(tile.textContent).toBe("3");
    expect(tile.style.top).toBe("30px");
    // Column a's copy is at the top level, with its tiles in it.
    expect(column.parentElement).toBe(root);
    expect(column.textContent).toBe("12");
    expect(column.style.animation).toBe("none"); // its entrance class must not replay
    for (const ghost of [tile, column]) {
      expect(ghost.style.position).toBe("absolute");
      expect(ghost.getAttribute("aria-hidden")).toBe("true");
      // Not found by a test id or measured as an item again.
      expect(ghost.outerHTML).not.toMatch(/data-testid|data-flip/);
      expect(startedOn(ghost).map(s => s.frames)).toEqual([[{ opacity: 0, transform: "scale(0.94)", offset: 1 }]]);
    }
    // The live tiles are the only ones a query finds.
    expect(root.querySelectorAll("[data-testid^='tile-']")).toHaveLength(1);
    // A copy goes when its fade ends.
    startedOn(tile)[0].anim.onfinish!();
    expect(ghosts(root)).toEqual([column]);
  });

  it("raises in what came: a tile into its column, a new column whole", () => {
    const { rerender, getByTestId } = render(<Board columns={EXAM} trigger="e1" />);
    rerender(<Board columns={WHOLE} trigger="" />);
    const root = getByTestId("root");
    const a = root.querySelector<HTMLElement>('[data-flip="col:a"]')!;
    const entered = started.filter(s => s.timing.fill === "backwards");
    expect(entered.map(s => s.el)).toEqual([a, getByTestId("tile-3")]);
    for (const s of entered) expect(s.frames).toEqual([{ opacity: 0, transform: "translateY(10px)", offset: 0 }]);
    // Column a's tiles come in with it, not each on its own.
    expect([getByTestId("tile-1"), getByTestId("tile-2")].flatMap(startedOn)).toEqual([]);
    expect(ghosts(root)).toEqual([]);
  });

  it("runs everything on the hub's one clock; what comes in starts a beat later and ends with the rest", () => {
    const { rerender } = render(<Board columns={WHOLE} trigger="" height={400} label="Ready for Exam 2" />);
    rerender(<Board columns={{ b: { 4: 30, 5: 76 } }} trigger="e1" height={160} label="Exam 1 coverage" />);
    const ends = started.map(s => Number(s.timing.delay ?? 0) + Number(s.timing.duration));
    expect(started.length).toBeGreaterThan(5); // a slide, an entrance, copies going, a crossfade, the height
    expect(new Set(ends)).toEqual(new Set([HUB_SWITCH_MS]));
    expect(new Set(started.map(s => s.timing.easing))).toEqual(new Set([HUB_EASE]));
    expect(new Set(started.map(s => s.timing.delay ?? 0))).toEqual(new Set([0, HUB_STAGGER_MS]));
    expect(started.filter(s => s.timing.delay).map(s => s.el.textContent)).toEqual(["5"]);
  });

  it("crossfades in place an item whose key carries its text: no movement either way", () => {
    const { rerender, getByTestId, getByText } = render(<Board columns={{}} trigger="" label="Ready for Exam 2" />);
    rerender(<Board columns={{}} trigger="e1" label="Exam 1 coverage" />);
    const root = getByTestId("root");
    const [old] = ghosts(root);
    expect(ghosts(root)).toHaveLength(1);
    expect(old.textContent).toBe("Ready for Exam 2");
    expect([old.style.left, old.style.top]).toEqual(["90px", "4px"]);
    expect(startedOn(old).map(s => s.frames)).toEqual([[{ opacity: 0, offset: 1 }]]);
    const now = getByText("Exam 1 coverage", { ignore: "[inert]" });
    expect(startedOn(now).map(s => [s.frames, s.timing.delay])).toEqual([[[{ opacity: 0, offset: 0 }], undefined]]);
  });

  it("copies nothing for an element React rewrote in place: its old text is gone", () => {
    const { rerender, getByTestId, getByText } = render(<Board columns={{}} trigger="" label="Ready for Exam 2" keyed={false} />);
    rerender(<Board columns={{}} trigger="e1" label="Exam 1 coverage" keyed={false} />);
    expect(ghosts(getByTestId("root"))).toEqual([]);
    expect(startedOn(getByText("Exam 1 coverage")).map(s => s.frames)).toEqual([[{ opacity: 0, offset: 0 }]]);
  });

  it("an entering item's own CSS entrance is cancelled, so the two do not run over each other", () => {
    const own = { cancel: vi.fn() };
    HTMLElement.prototype.getAnimations = function (this: HTMLElement) {
      return (this.className === "colEnter" ? [own] : []) as unknown as Animation[];
    };
    try {
      const { rerender } = render(<Board columns={EXAM} trigger="e1" />);
      rerender(<Board columns={WHOLE} trigger="" />);
      // Column a came in; column b was there (its entrance, long over, is left alone).
      expect(own.cancel).toHaveBeenCalledTimes(1);
    } finally {
      delete (HTMLElement.prototype as unknown as Record<string, unknown>).getAnimations;
    }
  });

  it("a container that was replaced starts over instead of animating from the old one", () => {
    const { rerender, getByTestId } = render(<Board columns={WHOLE} trigger="" rootKey="course-1" />);
    rerender(<Board columns={EXAM} trigger="e9" rootKey="course-2" />);
    expect(started).toEqual([]);
    expect(ghosts(getByTestId("root"))).toEqual([]);
    // And from there on it animates as usual.
    rerender(<Board columns={WHOLE} trigger="" rootKey="course-2" />);
    expect(started.length).toBeGreaterThan(0);
  });

  it("tweens the container's height when it changed", () => {
    const { rerender, getByTestId } = render(<Board columns={WHOLE} trigger="" height={400} />);
    rerender(<Board columns={EXAM} trigger="e1" height={160} />);
    expect(startedOn(getByTestId("root")).map(s => s.frames)).toEqual([[{ height: "400px" }, { height: "160px" }]]);
    started = [];
    rerender(<Board columns={WHOLE} trigger="" height={160} />);
    expect(startedOn(getByTestId("root"))).toEqual([]);
  });

  it("a second change mid-flight drops the first: its animations are cancelled and its copies removed", () => {
    const { rerender, getByTestId } = render(<Board columns={WHOLE} trigger="" />);
    rerender(<Board columns={EXAM} trigger="e1" />);
    const first = [...started];
    const root = getByTestId("root");
    expect(ghosts(root)).toHaveLength(2);
    rerender(<Board columns={{ a: { 1: 30 } }} trigger="e2" />);
    for (const s of first) expect(s.anim.cancel).toHaveBeenCalledTimes(1);
    // Only the second change's copy is left: column b, which just went.
    expect(ghosts(root).map(g => g.textContent)).toEqual(["4"]);
    expect(root.querySelectorAll("[data-testid^='tile-']")).toHaveLength(1);
  });

  it("unmounting cancels what is running", () => {
    const { rerender, unmount } = render(<Board columns={WHOLE} trigger="" />);
    rerender(<Board columns={EXAM} trigger="e1" />);
    const running = [...started];
    unmount();
    for (const s of running) expect(s.anim.cancel).toHaveBeenCalledTimes(1);
  });

  it("under reduced motion the new state is simply there", () => {
    reduced = true;
    const { rerender, getByTestId } = render(<Board columns={WHOLE} trigger="" height={400} />);
    rerender(<Board columns={EXAM} trigger="e1" height={160} />);
    expect(started).toEqual([]);
    expect(ghosts(getByTestId("root"))).toEqual([]);
    expect(getByTestId("root").querySelectorAll("[style]")).toHaveLength(0);
  });

  it("does nothing where the Web Animations API is missing", () => {
    delete (HTMLElement.prototype as unknown as Record<string, unknown>).animate;
    const { rerender, getByTestId } = render(<Board columns={WHOLE} trigger="" />);
    rerender(<Board columns={EXAM} trigger="e1" />);
    expect(ghosts(getByTestId("root"))).toEqual([]);
  });
});

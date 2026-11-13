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
import { useFlip } from "./useFlip";

type Columns = Record<string, Record<string, number>>;
type Started = { el: HTMLElement; frames: Keyframe[]; timing: KeyframeAnimationOptions; anim: { cancel: ReturnType<typeof vi.fn>; onfinish: null | (() => void) } };

/** Columns side by side (216px apart), each with tiles at the given y. */
function Board({ columns, trigger, height = 0 }: { columns: Columns; trigger: string; height?: number }) {
  const root = React.useRef<HTMLDivElement | null>(null);
  useFlip(root, trigger);
  return (
    <section>
      <div ref={root} data-testid="root" data-h={height}>
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

  it("raises in what came into a column that was there, and leaves a new column to its own entrance", () => {
    const { rerender, getByTestId } = render(<Board columns={EXAM} trigger="e1" />);
    rerender(<Board columns={WHOLE} trigger="" />);
    const root = getByTestId("root");
    const entered = started.filter(s => s.timing.fill === "backwards");
    expect(entered.map(s => s.el)).toEqual([getByTestId("tile-3")]);
    expect(entered[0].frames).toEqual([{ opacity: 0, transform: "translateY(10px)", offset: 0 }]);
    // Column a and its tiles: nothing from here.
    const a = root.querySelector('[data-flip="col:a"]')!;
    expect([a, getByTestId("tile-1"), getByTestId("tile-2")].flatMap(startedOn)).toEqual([]);
    expect(ghosts(root)).toEqual([]);
  });

  it("staggers what comes in, up to a cap", () => {
    const many = Object.fromEntries(Array.from({ length: 9 }, (_, i) => [`n${i}`, 76 + i * 46]));
    const { rerender } = render(<Board columns={{ b: { 4: 30 } }} trigger="e1" />);
    rerender(<Board columns={{ b: { 4: 30, ...many } }} trigger="" />);
    expect(started.filter(s => s.timing.fill === "backwards").map(s => s.timing.delay))
      .toEqual([0, 30, 60, 90, 120, 150, 180, 180, 180]);
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

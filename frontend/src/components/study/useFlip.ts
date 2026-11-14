"use client";
/**
 * Animates a change in which keyed items (`data-flip="<key>"`) a container
 * shows, so it reads as one layout rearranging: items that stay slide to their
 * new place, new ones fade in, gone ones fade out, and the container's height
 * follows. An item whose key carries its content (a label, a count) is
 * crossfaded in place when that content changes: the old one goes as the new
 * one comes. Such an item needs the same string as its React `key`, so the
 * old element is taken out whole instead of being rewritten into the new one
 * (there would be nothing left to fade out). The rule is ./flipPlan.ts; this
 * measures and plays it, on the hub's switch clock (./hubMotion.ts).
 *
 * A new item also rises 10px and a gone one shrinks a little, unless it is
 * marked `data-flip-how="fade"` (text and small marks, which must not move).
 * What goes fades out in the first part of the switch and what comes fades in
 * in the second, so the two are never read on top of each other; slides and
 * the height run the whole length.
 *
 * It only animates when `trigger` changes, and never under reduced motion.
 * Everything runs through the Web Animations API, which leaves no inline
 * style behind: cancelling (a second change mid-flight, or unmount) puts
 * every item straight at its resting place.
 *
 * Each item's box is read with offsetLeft/offsetTop, in its offset parent's
 * space, so a tracked item that holds tracked items must be positioned (and
 * so must the container), with no other positioned element in between.
 * Offsets ignore transforms: a measurement taken mid-animation is still the
 * resting layout. The container's rows must not stretch with its height
 * (`align-content: start` on a grid), or tweening the height would move them.
 */
import React from "react";
import { flipPlan, type FlipItem } from "./flipPlan";
import { HUB_EASE, HUB_IN, HUB_IN_LATE, HUB_OUT, HUB_WHOLE, reducedMotion, type HubPhase } from "./hubMotion";

type Seen = FlipItem & { el: HTMLElement; fade: boolean };
type Layout = { root: HTMLElement; trigger: string; height: number; items: Map<string, Seen> };
type Live = { anims: Animation[]; ghosts: HTMLElement[] };

const keyOf = (el: Element | null | undefined) => el?.getAttribute("data-flip") ?? null;

function measure(root: HTMLElement, trigger: string): Layout {
  const items = new Map<string, Seen>();
  for (const el of root.querySelectorAll<HTMLElement>("[data-flip]")) {
    items.set(keyOf(el)!, {
      el,
      box: { x: el.offsetLeft, y: el.offsetTop, w: el.offsetWidth, h: el.offsetHeight },
      parent: keyOf(el.parentElement?.closest("[data-flip]")),
      fade: el.getAttribute("data-flip-how") === "fade",
    });
  }
  return { root, trigger, height: root.offsetHeight, items };
}

/** A copy of an item that is gone, back where it was, out of reach of pointer, focus and tests. */
function ghostOf(was: Seen, host: HTMLElement): HTMLElement {
  const ghost = was.el.cloneNode(true) as HTMLElement;
  for (const el of [ghost, ...ghost.querySelectorAll("[data-flip], [data-testid]")]) {
    el.removeAttribute("data-flip");
    el.removeAttribute("data-testid");
  }
  ghost.setAttribute("inert", "");
  ghost.setAttribute("aria-hidden", "true");
  const { x, y, w, h } = was.box;
  // `animation: none` stops a copied entrance class from replaying on the copy.
  Object.assign(ghost.style, { position: "absolute", left: `${x}px`, top: `${y}px`, width: `${w}px`, height: `${h}px`, margin: "0", animation: "none", pointerEvents: "none" });
  host.appendChild(ghost);
  return ghost;
}

function play(prev: Layout, now: Layout, live: Live) {
  const run = (el: HTMLElement, frames: Keyframe[], phase: HubPhase, fill: FillMode = "none") => {
    const anim = el.animate(frames, { ...phase, easing: HUB_EASE, fill });
    live.anims.push(anim);
    return anim;
  };
  const plan = flipPlan(prev.items, now.items);
  for (const m of plan.move) {
    run(now.items.get(m.key)!.el, [{ transform: `translate(${m.dx}px, ${m.dy}px)` }, { transform: "none" }], HUB_WHOLE);
  }
  // One keyframe each: the other end is wherever the item rests (or rested).
  // Filled backwards, so a new item stays hidden until its part begins.
  for (const key of plan.enter) {
    const item = now.items.get(key)!;
    // An entrance of the item's own (a roadmap column's, in CSS) would run
    // over this one and past its end: this one takes its place.
    for (const own of item.el.getAnimations?.() ?? []) own.cancel();
    if (item.fade) run(item.el, [{ opacity: 0, offset: 0 }], HUB_IN, "backwards");
    // The hub's studyPaneEnter.
    else run(item.el, [{ opacity: 0, transform: "translateY(10px)", offset: 0 }], HUB_IN_LATE, "backwards");
  }
  for (const key of plan.leave) {
    const was = prev.items.get(key)!;
    // Still on the page: React rewrote this element into its successor (no
    // `key`), so what it used to show is gone and there is nothing to copy.
    if (was.el.isConnected) continue;
    const ghost = ghostOf(was, was.parent ? now.items.get(was.parent)!.el : now.root);
    live.ghosts.push(ghost);
    const gone = was.fade ? { opacity: 0, offset: 1 } : { opacity: 0, transform: "scale(0.94)", offset: 1 };
    // Filled forwards: the copy stays hidden for the instant before it is removed.
    run(ghost, [gone], HUB_OUT, "forwards").onfinish = () => ghost.remove();
  }
  if (Math.abs(prev.height - now.height) >= 1) {
    run(now.root, [{ height: `${prev.height}px` }, { height: `${now.height}px` }], HUB_WHOLE);
  }
}

export function useFlip(root: React.RefObject<HTMLElement | null>, trigger: string) {
  const last = React.useRef<Layout | null>(null);
  const live = React.useRef<Live>({ anims: [], ghosts: [] });
  const settle = React.useCallback(() => {
    for (const anim of live.current.anims) anim.cancel();
    for (const ghost of live.current.ghosts) ghost.remove();
    live.current = { anims: [], ghosts: [] };
  }, []);

  // After every commit, so the layout on record is the one on screen when the
  // next change comes (a column folded open since, an outline that landed).
  React.useLayoutEffect(() => {
    const el = root.current;
    if (!el) return;
    const prev = last.current;
    // A container that was replaced (re-keyed) starts over: it has its own entrance.
    const changed = prev !== null && prev.root === el && prev.trigger !== trigger;
    // Before measuring: a height still animating would be read as the new height.
    if (changed) settle();
    const now = measure(el, trigger);
    last.current = now;
    if (!prev || !changed || typeof el.animate !== "function" || reducedMotion()) return;
    // The new layout is already in place; a browser that refuses a keyframe
    // must cost the motion, not the page.
    try { play(prev, now, live.current); } catch { settle(); }
  });

  // The layout also moves without a commit here: on a resize, and when a
  // child re-renders by itself (the figure counting changes its own width).
  // Take it again then, or the next change would start from where the items
  // no longer are. Watched from the parent, which outlives a re-keyed container.
  React.useEffect(() => {
    const parent = root.current?.parentElement;
    if (!parent) return;
    const again = () => {
      const el = root.current;
      if (el && last.current) last.current = measure(el, last.current.trigger);
    };
    const resized = typeof ResizeObserver === "function" ? new ResizeObserver(again) : null;
    resized?.observe(parent);
    const mutated = new MutationObserver(again);
    mutated.observe(parent, { childList: true, characterData: true, subtree: true });
    return () => {
      resized?.disconnect();
      mutated.disconnect();
    };
  }, [root]);

  React.useEffect(() => settle, [settle]);
}

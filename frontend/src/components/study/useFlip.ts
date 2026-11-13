"use client";
/**
 * Animates a change in which keyed items (`data-flip="<key>"`) a container
 * shows, so it reads as one layout rearranging: items that stay slide to their
 * new place, new ones fade and rise in, gone ones fade and shrink out, and the
 * container's height follows. The rule is ./flipPlan.ts; this measures and
 * plays it.
 *
 * It only animates when `trigger` changes, and never under reduced motion.
 * Everything runs through the Web Animations API, which leaves no inline
 * style behind: cancelling (a second change mid-flight, or unmount) puts
 * every item straight at its resting place.
 *
 * Each item's box is read with offsetLeft/offsetTop, in its offset parent's
 * space, so a tracked item that holds tracked items must be positioned (and
 * so must the container). Offsets ignore transforms: a measurement taken
 * mid-animation is still the resting layout.
 */
import React from "react";
import { flipPlan, type FlipItem } from "./flipPlan";

type Seen = FlipItem & { el: HTMLElement };
type Layout = { trigger: string; height: number; items: Map<string, Seen> };
type Live = { anims: Animation[]; ghosts: HTMLElement[] };

const keyOf = (el: Element | null | undefined) => el?.getAttribute("data-flip") ?? null;

function measure(root: HTMLElement, trigger: string): Layout {
  const items = new Map<string, Seen>();
  for (const el of root.querySelectorAll<HTMLElement>("[data-flip]")) {
    const box = { x: el.offsetLeft, y: el.offsetTop, w: el.offsetWidth, h: el.offsetHeight };
    items.set(keyOf(el)!, { el, box, parent: keyOf(el.parentElement?.closest("[data-flip]")) });
  }
  return { trigger, height: root.offsetHeight, items };
}

const canAnimate = (root: HTMLElement) =>
  typeof root.animate === "function" && !window.matchMedia("(prefers-reduced-motion: reduce)").matches;

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

function play(root: HTMLElement, prev: Layout, now: Layout, live: Live) {
  const css = getComputedStyle(root);
  const easing = css.getPropertyValue("--ease").trim() || "ease-out";
  const ms = (token: string, fallback: number) => parseFloat(css.getPropertyValue(token)) || fallback;
  const slow = ms("--dur-slow", 420);
  const quick = ms("--dur", 220);
  const run = (el: HTMLElement, frames: Keyframe[], timing: KeyframeAnimationOptions) => {
    const anim = el.animate(frames, { easing, ...timing });
    live.anims.push(anim);
    return anim;
  };
  const plan = flipPlan(prev.items, now.items);
  for (const m of plan.move) {
    run(now.items.get(m.key)!.el, [{ transform: `translate(${m.dx}px, ${m.dy}px)` }, { transform: "none" }], { duration: slow });
  }
  // From hidden and 10px low (the hub's studyPaneEnter) to wherever the item rests.
  plan.enter.forEach((key, i) => {
    run(now.items.get(key)!.el, [{ opacity: 0, transform: "translateY(10px)", offset: 0 }], { duration: quick, delay: Math.min(i, 6) * 30, fill: "backwards" });
  });
  for (const key of plan.leave) {
    const was = prev.items.get(key)!;
    const ghost = ghostOf(was, was.parent ? now.items.get(was.parent)!.el : root);
    live.ghosts.push(ghost);
    run(ghost, [{ opacity: 0, transform: "scale(0.94)", offset: 1 }], { duration: quick, fill: "forwards" }).onfinish = () => ghost.remove();
  }
  if (Math.abs(prev.height - now.height) >= 1) {
    run(root, [{ height: `${prev.height}px` }, { height: `${now.height}px` }], { duration: slow });
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
    const changed = prev !== null && prev.trigger !== trigger;
    // Before measuring: a height still animating would be read as the new height.
    if (changed) settle();
    const now = measure(el, trigger);
    last.current = now;
    if (!prev || !changed || !canAnimate(el)) return;
    // The new layout is already in place; a browser that refuses a keyframe
    // must cost the motion, not the page.
    try { play(el, prev, now, live.current); } catch { settle(); }
  });

  // A resize moves everything without a commit: take the layout again, or the
  // next change would slide the items in from where they no longer are.
  React.useEffect(() => {
    const el = root.current;
    if (!el?.parentElement || typeof ResizeObserver !== "function") return;
    const observer = new ResizeObserver(() => {
      if (last.current) last.current = measure(el, last.current.trigger);
    });
    observer.observe(el.parentElement);
    return () => observer.disconnect();
  }, [root]);

  React.useEffect(() => settle, [settle]);
}

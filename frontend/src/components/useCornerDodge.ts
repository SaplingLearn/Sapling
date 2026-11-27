"use client";
/**
 * Keeps the sidebar layout's corner Report button (ShellCornerActions) off the
 * page's own controls.
 *
 * The button is pinned to the content column's bottom-right corner so it sits
 * in the same spot on every page — which is also where pages dock their own
 * controls: the tutor composer's Send, a card's action scrolled down to the
 * bottom edge (Study's "Make flashcards"). Covering one of those makes it
 * unclickable. So whenever the page settles (it loads or changes, the window
 * resizes, the student stops scrolling or typing), the button checks what
 * lies under its resting spot; when a control is there, it rises just above
 * the highest one, and it drops back once the spot is clear.
 *
 * Every page gets this without declaring anything: the check is a hit test
 * (`document.elementsFromPoint`) over the button's box, so it sees exactly
 * what the student would click. It never runs while the page is busy (it
 * waits for SETTLE_MS of quiet), so a scroll does not make the button jump
 * under the cursor.
 */
import { useEffect, type RefObject } from "react";

/** What counts as a control the button must not cover. */
const CONTROL = [
  "a[href]", "button", 'input:not([type="hidden"])', "select", "textarea", "summary",
  '[contenteditable="true"]', '[role="button"]', '[role="link"]', '[role="checkbox"]',
  '[role="radio"]', '[role="switch"]', '[role="tab"]', '[role="menuitem"]', '[role="option"]',
  '[role="slider"]', '[role="textbox"]', '[role="combobox"]',
].join(", ");

/** Clearance between the risen button and the control below it, px. */
export const DODGE_GAP = 8;
/** The furthest the button rises, px: past this it would wander into the page. */
export const DODGE_MAX = 240;
/** Room kept between the risen button and the top of its column, px. */
const EDGE = 64;
/** Quiet time before a re-check, ms. */
export const SETTLE_MS = 120;
/** A rise can uncover the next control up; re-checked at most this many times. */
const PASSES = 4;
/** Hit-test inset from the box's edges, px (a control merely touching it is not under it). */
const INSET = 2;

export interface Box { left: number; top: number; right: number; bottom: number }

function samplePoints(box: Box): [number, number][] {
  const l = box.left + INSET, r = box.right - INSET, t = box.top + INSET, b = box.bottom - INSET;
  return [[l, t], [r, t], [l, b], [r, b], [(l + r) / 2, (t + b) / 2]];
}

/** The page's controls under `box`, other than `own` (the button itself). */
export function controlsUnder(box: Box, own: Element): Element[] {
  const found = new Set<Element>();
  for (const [x, y] of samplePoints(box)) {
    for (const hit of document.elementsFromPoint(x, y)) {
      const control = own.contains(hit) ? null : hit.closest(CONTROL);
      if (control && !own.contains(control)) found.add(control);
    }
  }
  return [...found];
}

/** How far up from `resting` the button must rise to sit clear of every
 *  control under it, and under each spot it rises to, capped at `max`. */
export function liftFor(resting: Box, own: Element, max: number): number {
  let lift = 0;
  for (let pass = 0; pass < PASSES; pass++) {
    const box = { ...resting, top: resting.top - lift, bottom: resting.bottom - lift };
    const controls = controlsUnder(box, own);
    if (controls.length === 0) return lift;
    const needed = Math.max(...controls.map((c) => resting.bottom - c.getBoundingClientRect().top + DODGE_GAP));
    if (needed <= lift) return lift;
    lift = Math.min(Math.ceil(needed), max);
    if (lift === max) return lift;
  }
  return lift;
}

/** Where the button should sit now, as a rise from `resting`: back at rest
 *  once that spot is clear; where it already is while that spot is still
 *  clear (so a page full of controls does not make it hop at every pause);
 *  else the lowest clear spot above (`liftFor`). */
export function nextLift(resting: Box, own: Element, max: number, current: number): number {
  if (controlsUnder(resting, own).length === 0) return 0;
  const here = { ...resting, top: resting.top - current, bottom: resting.bottom - current };
  if (current > 0 && current <= max && controlsUnder(here, own).length === 0) return current;
  return liftFor(resting, own, max);
}

/** Dodge the page's controls (see the module header). `key` re-checks on a
 *  change the DOM alone may not show (a new route). */
export function useCornerDodge(ref: RefObject<HTMLElement | null>, key?: string): void {
  useEffect(() => {
    const el = ref.current;
    if (!el || typeof document.elementsFromPoint !== "function") return;
    let lift = 0;
    let timer: number | undefined;
    const measure = () => {
      const rect = el.getBoundingClientRect();
      const resting = { left: rect.left, right: rect.right, top: rect.top + lift, bottom: rect.bottom + lift };
      const columnTop = (el.offsetParent ?? document.body).getBoundingClientRect().top;
      const max = Math.max(0, Math.min(DODGE_MAX, resting.top - columnTop - EDGE));
      const next = nextLift(resting, el, max, lift);
      if (next === lift) return;
      lift = next;
      el.style.transform = lift ? `translateY(${-lift}px)` : "";
    };
    const settle = () => {
      window.clearTimeout(timer);
      timer = window.setTimeout(measure, SETTLE_MS);
    };
    settle();
    const mutations = new MutationObserver(settle);
    mutations.observe(document.body, { childList: true, subtree: true });
    const sizes = typeof ResizeObserver === "function" ? new ResizeObserver(settle) : null;
    if (el.offsetParent) sizes?.observe(el.offsetParent);
    window.addEventListener("resize", settle);
    document.addEventListener("scroll", settle, true);
    document.addEventListener("input", settle, true);
    return () => {
      window.clearTimeout(timer);
      mutations.disconnect();
      sizes?.disconnect();
      window.removeEventListener("resize", settle);
      document.removeEventListener("scroll", settle, true);
      document.removeEventListener("input", settle, true);
      el.style.transform = "";
    };
  }, [ref, key]);
}

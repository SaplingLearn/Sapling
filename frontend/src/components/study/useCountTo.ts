"use client";
/**
 * A whole number that counts to its new value instead of jumping to it, on the
 * hub's switch clock (./hubMotion.ts). A new value mid-count starts from the
 * number then on screen, so it always ends on the last value given. Under
 * reduced motion it is simply the value.
 */
import React from "react";
import { countAt, reducedMotion } from "./hubMotion";

export function useCountTo(value: number): number {
  const [shown, setShown] = React.useState(value);
  /** What is on screen: where the next count starts from. */
  const onScreen = React.useRef(value);

  // A layout effect, so the count starts in the frame the value changed in
  // (with the rest of the switch) and a reduced-motion jump paints once.
  React.useLayoutEffect(() => {
    const from = onScreen.current;
    const show = (n: number) => {
      onScreen.current = n;
      setShown(n);
    };
    if (from === value) return;
    if (reducedMotion()) {
      show(value);
      return;
    }
    const start = performance.now();
    let frame = 0;
    const tick = (now: number) => {
      const n = countAt(from, value, now - start);
      show(n);
      if (n !== value) frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [value]);

  return shown;
}

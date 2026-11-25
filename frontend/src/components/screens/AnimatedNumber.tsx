"use client";
/**
 * A number that tweens from its previous value to a new one (#866 motion).
 *
 * The first paint shows the real figure (no count-up on load: motion marks a
 * change); only a later change plays a short tween that ends on the exact new
 * value. Reduced motion, and framer's test-mode skip, show the new value at
 * once, so tests and screen-reader users never meet a mid-tween number.
 *
 *   <AnimatedNumber value={n} format={v => v.toLocaleString()} />
 */
import { useEffect, useRef, useState } from "react";
import { animate, MotionGlobalConfig, useReducedMotion } from "framer-motion";
import { MOTION } from "@/lib/designTokens";
import "@/lib/motion";

export interface AnimatedNumberProps {
  value: number;
  /** How a value (final or mid-tween) is written. Defaults to a rounded locale string. */
  format?: (v: number) => string;
  className?: string;
  "data-testid"?: string;
}

const defaultFormat = (v: number) => Math.round(v).toLocaleString();

export function AnimatedNumber({ value, format = defaultFormat, className, ...rest }: AnimatedNumberProps) {
  const reduced = Boolean(useReducedMotion()) || MotionGlobalConfig.skipAnimations === true;
  // The figure mid-tween; null at rest, when the real value shows.
  const [display, setDisplay] = useState<number | null>(null);
  const [prev, setPrev] = useState(value);
  // Where the tween starts: the value on screen when the change lands.
  const shown = useRef(value);

  // On a change, hold the old figure for the frame before the tween starts
  // (React's adjust-state-while-rendering pattern), so the new value never
  // flashes first.
  if (value !== prev) {
    setPrev(value);
    if (!reduced) setDisplay(display ?? prev);
  }

  useEffect(() => {
    const from = shown.current;
    if (reduced || from === value || !Number.isFinite(from) || !Number.isFinite(value)) {
      shown.current = value;
      return;
    }
    const controls = animate(from, value, {
      duration: MOTION.duration.slow,
      ease: MOTION.ease.out,
      onUpdate: v => { shown.current = v; setDisplay(v); },
      onComplete: () => { shown.current = value; setDisplay(null); },
    });
    return () => controls.stop();
  }, [value, reduced]);

  return (
    <span className={className} data-testid={rest["data-testid"]}>
      {format(reduced ? value : (display ?? value))}
    </span>
  );
}

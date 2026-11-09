"use client";

import React from "react";
import { IS_TEST_MODE } from "@/lib/testMode";
import { usePrefersReducedMotion } from "@/lib/usePrefersReducedMotion";

/**
 * The original Home greeting animation, carried over from the pre-v3
 * Dashboard (main@929658f:app/dashboard/page.tsx):
 *  - types one character every 55ms;
 *  - a thin forest-green "|" cursor (weight 200) blinks every 530ms;
 *  - 300ms after the last character the cursor disappears (no perpetual
 *    blink) and `onDone` fires, so the parent can fade the quote in.
 *
 * Reduced motion and test mode skip the typing: the full text renders at
 * once and `onDone` fires on the next tick. The host heading should carry
 * the full text as its accessible name (the typed span is aria-hidden), so
 * screen readers never hear a half-typed greeting.
 */
export function Typewriter({
  text,
  speed = 55,
  onDone,
}: {
  text: string;
  speed?: number;
  onDone?: () => void;
}) {
  const reducedMotion = usePrefersReducedMotion();
  const instant = IS_TEST_MODE || reducedMotion;
  const [shown, setShown] = React.useState(instant ? text : "");
  const [done, setDone] = React.useState(instant);
  const [cursorOn, setCursorOn] = React.useState(true);

  // Keep onDone in a ref so the typing only restarts when the text or speed
  // changes, not on every parent render.
  const onDoneRef = React.useRef(onDone);
  React.useEffect(() => { onDoneRef.current = onDone; }, [onDone]);

  React.useEffect(() => {
    if (instant) {
      setShown(text);
      setDone(true);
      const t = setTimeout(() => onDoneRef.current?.(), 0);
      return () => clearTimeout(t);
    }
    setShown("");
    setDone(false);
    setCursorOn(true);
    let i = 0;
    let settleTimer: ReturnType<typeof setTimeout> | null = null;
    const iv = setInterval(() => {
      i += 1;
      setShown(text.slice(0, i));
      if (i >= text.length) {
        clearInterval(iv);
        settleTimer = setTimeout(() => {
          setDone(true);
          onDoneRef.current?.();
        }, 300);
      }
    }, speed);
    return () => {
      clearInterval(iv);
      if (settleTimer) clearTimeout(settleTimer);
    };
  }, [text, speed, instant]);

  React.useEffect(() => {
    if (done) { setCursorOn(false); return; }
    const blink = setInterval(() => setCursorOn((v) => !v), 530);
    return () => clearInterval(blink);
  }, [done]);

  return (
    <span aria-hidden data-testid="home-greeting-typed">
      {shown}
      <span
        style={{
          opacity: done ? 0 : cursorOn ? 1 : 0,
          marginLeft: 1,
          color: "#445D22",
          fontWeight: 200,
          transition: "opacity 0.1s",
        }}
      >
        |
      </span>
    </span>
  );
}

"use client";
/**
 * The Home greeting (main's Dashboard hero, brought back as the redesigned
 * Home page heading): "Good morning/afternoon/evening, {first name}" —
 * "Welcome back" when there is no name — typed out once, then a short quote
 * that fades in under it.
 *
 * Hydration: the time-of-day prefix and the random quote are CLIENT-ONLY
 * (state set in an effect), so the server's timezone/RNG never disagrees with
 * the client's. Reduced motion: the text appears whole, with no cursor and no
 * fade. Screen readers get the whole heading once (the `h1`'s accessible
 * name), never the letter-by-letter typing.
 */
import React from "react";

import { IS_TEST_MODE, now } from "@/lib/testMode";
import { usePrefersReducedMotion } from "@/lib/usePrefersReducedMotion";

export const QUOTES = [
  "Learning is the only thing the mind never exhausts, never fears, and never regrets. — da Vinci",
  "The roots of education are bitter, but the fruit is sweet. — Aristotle",
  "Live as if you were to die tomorrow. Learn as if you were to live forever. — Gandhi",
  "An investment in knowledge pays the best interest. — Franklin",
  "The beautiful thing about learning is that no one can take it away from you. — B.B. King",
  "Tell me and I forget. Teach me and I remember. Involve me and I learn. — Franklin",
];

export function getGreetingPrefix(d: Date) {
  const h = d.getHours();
  if (h < 12) return "Good morning";
  if (h < 17) return "Good afternoon";
  return "Good evening";
}

// Pre-revamp typing animation (main@929658f:app/dashboard/page.tsx:257-284):
//  - Types one char every 55ms.
//  - Thin forest-green vertical bar '|' cursor, weight 200, blinks 530ms.
//  - When the text finishes typing, wait 300ms then hide the cursor
//    entirely (no perpetual blinking).
//  - Exposes an onDone callback so the parent can fade the quote in once
//    the greeting settles.
//  - `instant` (reduced motion): the whole text at once, no cursor.
export function Typewriter({
  text,
  speed = 55,
  onDone,
  instant = false,
}: {
  text: string;
  speed?: number;
  onDone?: () => void;
  instant?: boolean;
}) {
  const [shown, setShown] = React.useState(instant ? text : "");
  const [done, setDone] = React.useState(instant);
  const [cursorOn, setCursorOn] = React.useState(!instant);

  // Keep onDone in a ref so the typing effect only restarts when text
  // or speed changes — not on every parent re-render.
  const onDoneRef = React.useRef(onDone);
  React.useEffect(() => { onDoneRef.current = onDone; }, [onDone]);

  React.useEffect(() => {
    if (instant) {
      setShown(text);
      setDone(true);
      setCursorOn(false);
      onDoneRef.current?.();
      return;
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
    <span>
      {shown}
      <span
        aria-hidden
        style={{
          opacity: done ? 0 : cursorOn ? 1 : 0,
          marginLeft: 1,
          color: "var(--accent)",
          fontWeight: 200,
          transition: "opacity 0.1s",
        }}
      >
        |
      </span>
    </span>
  );
}

/** The Home page's h1 + quote, in the redesign type (classes from the caller). */
export function HomeGreeting({
  userName,
  titleClassName,
  quoteClassName,
}: {
  userName: string | null | undefined;
  titleClassName?: string;
  quoteClassName?: string;
}) {
  const reduced = usePrefersReducedMotion();
  const firstName = userName ? userName.trim().split(" ")[0] : "";
  // Client-only: the server's clock/RNG would drift from the client's.
  const [prefix, setPrefix] = React.useState<string | null>(null);
  const [quote, setQuote] = React.useState<string | null>(null);
  const [typed, setTyped] = React.useState(false);
  React.useEffect(() => {
    setPrefix(getGreetingPrefix(new Date(now())));
    // Test mode freezes the quote to index 0 so the copy is byte-stable.
    setQuote(IS_TEST_MODE ? QUOTES[0] : QUOTES[Math.floor(Math.random() * QUOTES.length)]);
  }, []);
  const text = firstName && prefix ? `${prefix}, ${firstName}` : "Welcome back";
  const quoteShown = typed || reduced;
  return (
    <>
      <h1 className={titleClassName} aria-label={text} data-testid="dashboard-greeting">
        <span aria-hidden="true">
          {/* keyed by text: a late name/prefix restarts the typing cleanly */}
          <Typewriter key={text} text={text} instant={reduced} onDone={() => setTyped(true)} />
        </span>
      </h1>
      {quote && (
        <p
          className={quoteClassName}
          aria-hidden={!quoteShown}
          data-testid="dashboard-quote"
          style={{
            opacity: quoteShown ? 1 : 0,
            transform: quoteShown || reduced ? "none" : "translateY(-4px)",
            transition: reduced ? "none" : "opacity 0.55s ease 0.15s, transform 0.55s ease 0.15s",
          }}
        >
          “{quote}”
        </p>
      )}
    </>
  );
}

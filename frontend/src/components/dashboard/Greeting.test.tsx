// @vitest-environment jsdom
/**
 * The Home greeting: main's "Good morning/afternoon/evening, {first name}"
 * (fallback "Welcome back") as the page h1, typed once, with the quote fading
 * in after it. The h1's accessible name is the whole greeting (never the
 * letter-by-letter typing); reduced motion shows everything at once.
 */
import React from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, render, screen } from "@testing-library/react";

const motion = vi.hoisted(() => ({ reduced: false }));
vi.mock("@/lib/usePrefersReducedMotion", () => ({ usePrefersReducedMotion: () => motion.reduced }));

import { HomeGreeting, getGreetingPrefix } from "./Greeting";

afterEach(() => {
  cleanup();
  vi.useRealTimers();
  motion.reduced = false;
});

describe("HomeGreeting", () => {
  it("greets by first name by time of day, as the page heading", () => {
    motion.reduced = true;
    render(<HomeGreeting userName="Ada Lovelace" />);
    const h1 = screen.getByRole("heading", { level: 1 });
    expect(h1).toHaveAccessibleName(`${getGreetingPrefix(new Date())}, Ada`);
  });

  it("falls back to 'Welcome back' without a name", () => {
    motion.reduced = true;
    render(<HomeGreeting userName={null} />);
    expect(screen.getByRole("heading", { level: 1 })).toHaveAccessibleName("Welcome back");
  });

  it("reduced motion: the whole greeting and the quote at once, no fade", () => {
    motion.reduced = true;
    render(<HomeGreeting userName="Ada" />);
    expect(screen.getByTestId("dashboard-greeting")).toHaveTextContent(/, Ada/);
    const quote = screen.getByTestId("dashboard-quote");
    expect(quote).toHaveStyle({ opacity: "1", transition: "none" });
    expect(quote).not.toHaveAttribute("aria-hidden", "true");
  });

  it("types the greeting, then fades the quote in", () => {
    vi.useFakeTimers();
    render(<HomeGreeting userName="Ada" />);
    const quote = screen.getByTestId("dashboard-quote");
    expect(quote).toHaveStyle({ opacity: "0" });
    expect(quote).toHaveAttribute("aria-hidden", "true");
    act(() => {
      vi.advanceTimersByTime(3_000);
    });
    expect(screen.getByTestId("dashboard-greeting")).toHaveTextContent(/, Ada/);
    expect(quote).toHaveStyle({ opacity: "1" });
  });

  it.each([
    [8, "Good morning"],
    [13, "Good afternoon"],
    [20, "Good evening"],
  ])("%i:00 → %s", (h, prefix) => {
    const d = new Date(2026, 2, 11, h);
    expect(getGreetingPrefix(d)).toBe(prefix);
  });
});

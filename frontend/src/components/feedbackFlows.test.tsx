// @vitest-environment jsdom
/**
 * The two feedback prompts ShellFrame mounts side by side (#762): the passive
 * "What's clicking?" pulse (FeedbackFlow, PULSE_DELAY_MS after load) and the
 * navigate-away-from-/learn "How was that session?" (SessionFeedbackGlobal).
 * Both are full-screen modals with their own scroll lock; nothing stopped them
 * opening on top of each other. And the last-session context the session
 * prompt reads was never cleared, so a later prompt could be attributed to a
 * session from long before.
 */

import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, cleanup, act, fireEvent } from "@testing-library/react";

const nav = vi.hoisted(() => ({ pathname: "/learn", search: "" }));
vi.mock("next/navigation", () => ({
  usePathname: () => nav.pathname,
  useSearchParams: () => new URLSearchParams(nav.search),
}));
vi.mock("@/context/UserContext", () => ({
  useUser: () => ({ userId: "u1", isAuthenticated: true }),
}));
vi.mock("@/lib/api", () => ({ submitFeedback: vi.fn(async () => ({})) }));

import { FeedbackFlow, FIRST_SEEN_KEY, PULSE_COOLDOWN_MS, PULSE_DELAY_MS, PULSE_GRACE_MS } from "./FeedbackFlow";
import { SessionFeedbackGlobal } from "./SessionFeedbackGlobal";
import { ToastProvider } from "./ToastProvider";
import { __resetScrollLocksForTests } from "@/lib/useScrollLock";
import { __resetFeedbackSlotForTests } from "@/lib/feedbackSlot";

const GLOBAL_TITLE = "What's clicking?";
const SESSION_TITLE = "How was that session?";

function Shell() {
  return (
    <ToastProvider>
      <FeedbackFlow />
      <SessionFeedbackGlobal />
    </ToastProvider>
  );
}

function navigate(view: ReturnType<typeof render>, pathname: string) {
  nav.pathname = pathname;
  view.rerender(<Shell />);
}

beforeEach(() => {
  vi.useFakeTimers();
  nav.pathname = "/learn";
  nav.search = "";
  localStorage.clear();
  // A settled student: past the new-student grace, so the pulse may ask.
  localStorage.setItem(FIRST_SEEN_KEY, String(Date.now() - 30 * 24 * 60 * 60 * 1000));
  sessionStorage.clear();
  __resetFeedbackSlotForTests();
});

afterEach(() => {
  cleanup();
  vi.useRealTimers();
  __resetScrollLocksForTests();
});

describe("only one feedback prompt at a time", () => {
  it("leaving /learn while the passive prompt is open does not stack the session prompt on it", () => {
    const view = render(<Shell />);
    act(() => { vi.advanceTimersByTime(PULSE_DELAY_MS); });
    expect(screen.getByText(GLOBAL_TITLE)).toBeInTheDocument();

    navigate(view, "/dashboard");
    expect(screen.queryByText(SESSION_TITLE)).toBeNull();
    // Skipped, not spent: no session cooldown was recorded for a prompt that
    // never showed.
    expect(localStorage.getItem("sapling_last_session_feedback")).toBeNull();
  });

  it("the passive prompt's timer does not fire on top of an open session prompt", () => {
    const view = render(<Shell />);
    navigate(view, "/dashboard");
    expect(screen.getByText(SESSION_TITLE)).toBeInTheDocument();

    act(() => { vi.advanceTimersByTime(PULSE_DELAY_MS); });
    expect(screen.queryByText(GLOBAL_TITLE)).toBeNull();
  });

  it("once a prompt closes, the other may open", () => {
    const view = render(<Shell />);
    act(() => { vi.advanceTimersByTime(PULSE_DELAY_MS); });
    fireEvent.click(screen.getByRole("button", { name: "Not now" }));
    expect(screen.queryByText(GLOBAL_TITLE)).toBeNull();

    navigate(view, "/dashboard");
    expect(screen.getByText(SESSION_TITLE)).toBeInTheDocument();
  });
});

describe("last-session context", () => {
  it("is consumed when the session prompt reads it, so it can't label a later prompt", () => {
    sessionStorage.setItem("sapling_last_session_context", JSON.stringify({ sessionId: "s1", topic: "Recursion" }));
    const view = render(<Shell />);
    navigate(view, "/dashboard");
    expect(screen.getByText("Recursion")).toBeInTheDocument();
    expect(sessionStorage.getItem("sapling_last_session_context")).toBeNull();
  });
});

describe("how often the pulse asks", () => {
  it("never asks a new student in their first days", () => {
    localStorage.removeItem(FIRST_SEEN_KEY);
    render(<Shell />);
    act(() => { vi.advanceTimersByTime(PULSE_DELAY_MS); });
    expect(screen.queryByText(GLOBAL_TITLE)).toBeNull();
    // ...and starts the clock for when it may.
    expect(Number(localStorage.getItem(FIRST_SEEN_KEY))).toBeGreaterThan(0);
    expect(PULSE_GRACE_MS).toBeGreaterThan(0);
  });

  it("waits out the cooldown after it last asked", () => {
    localStorage.setItem("sapling_last_feedback", String(Date.now() - PULSE_COOLDOWN_MS + 60_000));
    render(<Shell />);
    act(() => { vi.advanceTimersByTime(PULSE_DELAY_MS); });
    expect(screen.queryByText(GLOBAL_TITLE)).toBeNull();
  });

  it("never opens over a quiz, and doesn't spend its chance there", () => {
    nav.pathname = "/quiz";
    render(<Shell />);
    act(() => { vi.advanceTimersByTime(PULSE_DELAY_MS); });
    expect(screen.queryByText(GLOBAL_TITLE)).toBeNull();
    expect(localStorage.getItem("sapling_last_feedback")).toBeNull();
  });
});

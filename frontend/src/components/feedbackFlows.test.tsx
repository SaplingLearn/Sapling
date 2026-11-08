// @vitest-environment jsdom
/**
 * The shell's two passive feedback prompts and their pacing
 * (lib/feedbackPacing.ts): the "What's clicking?" pulse (FeedbackFlow, due 45s
 * after load) and "How was that session?" (SessionFeedbackGlobal, on leaving
 * /learn after a wrap-up). A live walkthrough had the pulse land mid check-in,
 * right after the first diagnostic answer, and the session prompt follow when
 * the student went on to /study. #762: both are full-screen modals that once
 * stacked on each other, and the last-session context once outlived its session.
 *
 * `Learning` stands in for LoopLearn's half of the contract, which
 * LoopLearn.test.tsx pins: it holds prompts while its session is open and, at
 * the wrap-up, releases them and remembers the ended session.
 */

import React, { useEffect } from "react";
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

import { FeedbackFlow } from "./FeedbackFlow";
import { SessionFeedbackGlobal } from "./SessionFeedbackGlobal";
import { ToastProvider } from "./ToastProvider";
import { __resetScrollLocksForTests } from "@/lib/useScrollLock";
import {
  __resetFeedbackPacingForTests,
  ANY_PROMPT_GAP_MS,
  mayPrompt,
  noteLearningSession,
  PULSE_COOLDOWN_MS,
  recordPrompt,
  rememberEndedSession,
  SESSION_PROMPT_COOLDOWN_MS,
  useFeedbackHold,
} from "@/lib/feedbackPacing";

const PULSE = "What's clicking?";
const SESSION = "How was that session?";
const PULSE_DELAY = 45_000;
const ENDED_KEY = "sapling_last_session_context";

type Phase = "probe" | "check" | "close";
interface ShellProps {
  /** LoopLearn on /learn: the session on screen and its phase. */
  learning?: { session: string; phase: Phase };
  /** Another surface's activity in progress (a review item, a retention check). */
  activity?: boolean;
}

function Learning({ session, phase }: { session: string; phase: Phase }) {
  useFeedbackHold(phase !== "close");
  useEffect(() => {
    noteLearningSession(session);
    if (phase === "close") rememberEndedSession({ sessionId: session, topic: "Recursion" });
  }, [session, phase]);
  return null;
}

function Activity() {
  useFeedbackHold(true);
  return null;
}

function Shell({ learning, activity }: ShellProps) {
  return (
    <ToastProvider>
      {learning && <Learning {...learning} />}
      {activity && <Activity />}
      <FeedbackFlow />
      <SessionFeedbackGlobal />
    </ToastProvider>
  );
}

function navigate(view: ReturnType<typeof render>, pathname: string, props: ShellProps = {}, search = "") {
  nav.pathname = pathname;
  nav.search = search;
  view.rerender(<Shell {...props} />);
}

const advance = (ms: number) => act(() => { vi.advanceTimersByTime(ms); });
const promptedSessions = (): string[] => JSON.parse(localStorage.getItem("sapling_feedback_sessions") ?? "[]");

/** /learn: session s1's check-in starts, runs `ms`, then wraps up. */
function sessionThatWrapsUpAfter(ms: number) {
  const view = render(<Shell learning={{ session: "s1", phase: "probe" }} />);
  advance(ms);
  view.rerender(<Shell learning={{ session: "s1", phase: "close" }} />);
  return view;
}

beforeEach(() => {
  vi.useFakeTimers();
  nav.pathname = "/learn";
  nav.search = "";
  localStorage.clear();
  sessionStorage.clear();
  __resetFeedbackPacingForTests();
});

afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.restoreAllMocks();
  __resetScrollLocksForTests();
});

describe("never mid-learning", () => {
  it.each<Phase>(["probe", "check"])("no pulse during the %s, however long it runs — deferred, not spent", (phase) => {
    render(<Shell learning={{ session: "s1", phase }} />);
    advance(PULSE_DELAY);
    advance(20 * 60_000);
    expect(screen.queryByText(PULSE)).toBeNull();
    expect(localStorage.getItem("sapling_last_feedback")).toBeNull();
  });

  it("a pulse that came due during the check-in opens after the wrap-up", () => {
    const view = render(<Shell learning={{ session: "s1", phase: "probe" }} />);
    advance(PULSE_DELAY); // the first diagnostic answer, in the walkthrough
    expect(screen.queryByText(PULSE)).toBeNull();
    view.rerender(<Shell learning={{ session: "s1", phase: "check" }} />);
    advance(5 * 60_000);
    expect(screen.queryByText(PULSE)).toBeNull();

    view.rerender(<Shell learning={{ session: "s1", phase: "close" }} />);
    expect(screen.getByText(PULSE)).toBeInTheDocument();
    expect(promptedSessions()).toEqual(["s1"]);
  });

  it("a deferred pulse opens at the next break when the student leaves mid-session", () => {
    const view = render(<Shell learning={{ session: "s1", phase: "check" }} />);
    advance(PULSE_DELAY);
    navigate(view, "/dashboard");
    expect(screen.getByText(PULSE)).toBeInTheDocument();
    expect(screen.queryByText(SESSION)).toBeNull(); // nothing wrapped up: nothing to ask about
    expect(promptedSessions()).toEqual(["s1"]);
  });

  it("no pulse over a review item or retention check on another page; it opens once that ends", () => {
    const view = render(<Shell />, {});
    navigate(view, "/study", { activity: true });
    advance(PULSE_DELAY);
    expect(screen.queryByText(PULSE)).toBeNull();
    navigate(view, "/study", { activity: false });
    expect(screen.getByText(PULSE)).toBeInTheDocument();
  });

  it("the end-of-session prompt waits out an activity already in progress where the student lands", () => {
    const view = sessionThatWrapsUpAfter(10_000);
    navigate(view, "/study", { activity: true });
    expect(screen.queryByText(SESSION)).toBeNull();
    navigate(view, "/study", { activity: false });
    expect(screen.getByText(SESSION)).toBeInTheDocument();
  });
});

describe("at most one feedback prompt per learning session", () => {
  it("a pulse shown in the session skips that session's end-of-session prompt", () => {
    const view = sessionThatWrapsUpAfter(PULSE_DELAY); // the pulse waited for the wrap-up
    expect(screen.getByText(PULSE)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Not now" }));

    navigate(view, "/study");
    expect(screen.queryByText(SESSION)).toBeNull();
    expect(sessionStorage.getItem(ENDED_KEY)).toBeNull(); // consumed: it can't come back later
    expect(localStorage.getItem("sapling_last_session_feedback")).toBeNull();
  });

  it("the end-of-session prompt skips a pulse that comes due later in that session", () => {
    const view = sessionThatWrapsUpAfter(10_000);
    navigate(view, "/study");
    expect(screen.getByText(SESSION)).toBeInTheDocument();
    expect(screen.getByText("Recursion")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Skip" }));

    advance(PULSE_DELAY);
    expect(screen.queryByText(PULSE)).toBeNull();
    expect(promptedSessions()).toEqual(["s1"]);
  });

  it("a session that had a prompt allows no other, past the same-day gap; another session may", () => {
    const t0 = Date.now();
    recordPrompt("session", "s1", t0);
    const nextDay = t0 + ANY_PROMPT_GAP_MS + 1;
    expect(mayPrompt("global", "s1", nextDay)).toBe(false);
    expect(mayPrompt("global", "s2", nextDay)).toBe(true);
    expect(mayPrompt("global", null, nextDay)).toBe(true);
  });
});

describe("a dismissal counts as shown", () => {
  it("the pulse is recorded the moment it opens, so Not now spends it", () => {
    const view = render(<Shell />);
    navigate(view, "/dashboard");
    advance(PULSE_DELAY);
    expect(screen.getByText(PULSE)).toBeInTheDocument();
    expect(localStorage.getItem("sapling_last_feedback")).not.toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Not now" }));

    // A reload restarts the 45s timer; the dismissal still holds the cooldown.
    cleanup();
    __resetFeedbackPacingForTests();
    render(<Shell />);
    advance(PULSE_DELAY * 2);
    expect(screen.queryByText(PULSE)).toBeNull();
  });

  it("Skip on the session prompt spends it: a second session's wrap-up the same day asks nothing", () => {
    const view = sessionThatWrapsUpAfter(10_000);
    navigate(view, "/study");
    fireEvent.click(screen.getByRole("button", { name: "Skip" }));
    expect(localStorage.getItem("sapling_last_session_feedback")).not.toBeNull();

    navigate(view, "/learn", { learning: { session: "s2", phase: "probe" } });
    navigate(view, "/learn", { learning: { session: "s2", phase: "close" } });
    navigate(view, "/dashboard");
    expect(screen.queryByText(SESSION)).toBeNull();
  });
});

describe("cross-session cooldowns", () => {
  it("each kind keeps its cooldown (pulse 3 days, session prompt 2 days), and any two prompts are a day apart", () => {
    const t0 = Date.now();
    recordPrompt("global", null, t0);
    expect(mayPrompt("global", null, t0 + PULSE_COOLDOWN_MS)).toBe(false);
    expect(mayPrompt("global", null, t0 + PULSE_COOLDOWN_MS + 1)).toBe(true);
    expect(mayPrompt("session", null, t0 + ANY_PROMPT_GAP_MS)).toBe(false);
    expect(mayPrompt("session", null, t0 + ANY_PROMPT_GAP_MS + 1)).toBe(true);

    localStorage.clear();
    recordPrompt("session", null, t0);
    expect(mayPrompt("session", null, t0 + SESSION_PROMPT_COOLDOWN_MS)).toBe(false);
    expect(mayPrompt("session", null, t0 + SESSION_PROMPT_COOLDOWN_MS + 1)).toBe(true);
    expect(mayPrompt("global", null, t0 + ANY_PROMPT_GAP_MS)).toBe(false);
    expect(mayPrompt("global", null, t0 + ANY_PROMPT_GAP_MS + 1)).toBe(true);
  });

  it("storage that cannot be read asks nothing rather than asking on every load", () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => { throw new Error("blocked"); });
    expect(mayPrompt("global", null)).toBe(false);
    expect(mayPrompt("session", "s1")).toBe(false);
  });
});

describe("only one feedback prompt on screen at a time (#762)", () => {
  // ?testFeedback= forces a prompt past the pacing, so only the slot decides.
  it("leaving /learn while the pulse is open does not stack the session prompt on it", () => {
    nav.search = "testFeedback=session";
    const view = render(<Shell />);
    advance(PULSE_DELAY);
    expect(screen.getByText(PULSE)).toBeInTheDocument();

    navigate(view, "/dashboard");
    expect(screen.queryByText(SESSION)).toBeNull();
    // Skipped, not spent: nothing was recorded for a prompt that never showed.
    expect(localStorage.getItem("sapling_last_session_feedback")).toBeNull();
  });

  it("the pulse does not open on top of an open session prompt", () => {
    nav.search = "testFeedback=session";
    const view = render(<Shell />);
    navigate(view, "/dashboard", {}, "testFeedback=global");
    expect(screen.getByText(SESSION)).toBeInTheDocument();

    advance(PULSE_DELAY);
    expect(screen.queryByText(PULSE)).toBeNull();
  });

  it("closing a prompt gives the slot back", () => {
    nav.search = "testFeedback=session";
    const view = render(<Shell />);
    advance(PULSE_DELAY);
    fireEvent.click(screen.getByRole("button", { name: "Not now" }));
    expect(screen.queryByText(PULSE)).toBeNull();

    navigate(view, "/dashboard");
    expect(screen.getByText(SESSION)).toBeInTheDocument();
  });
});

describe("the end-of-session prompt's trigger", () => {
  it("leaving /learn without a wrap-up asks nothing", () => {
    const view = render(<Shell learning={{ session: "s1", phase: "check" }} />);
    navigate(view, "/dashboard");
    expect(screen.queryByText(SESSION)).toBeNull();
  });

  it("the ended-session context is consumed when the prompt reads it, so it can't label a later prompt", () => {
    sessionStorage.setItem(ENDED_KEY, JSON.stringify({ sessionId: "s1", topic: "Recursion" }));
    const view = render(<Shell />);
    navigate(view, "/dashboard");
    expect(screen.getByText("Recursion")).toBeInTheDocument();
    expect(sessionStorage.getItem(ENDED_KEY)).toBeNull();
  });

  it("?testFeedback=session on /learn still forces the prompt on the way out (Figma recipes)", () => {
    recordPrompt("session", null); // inside every cooldown
    nav.search = "testFeedback=session";
    const view = render(<Shell />);
    navigate(view, "/dashboard"); // the nav link drops the query string
    expect(screen.getByText(SESSION)).toBeInTheDocument();
  });
});

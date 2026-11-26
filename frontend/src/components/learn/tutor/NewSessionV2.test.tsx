// @vitest-environment jsdom
/**
 * New session, rebuilt (Tutor redesign phase 4, `new_session_v2`) against its
 * design board, `../__fixtures__/new-session.design.html`, kept verbatim: the
 * question, the radio cards and the wrap-up line come from it (words and
 * structure, not pixels). The board's "Just ask a question" and "Prepare for
 * Midterm 2" have nothing behind them yet and are not offered.
 */
import fs from "node:fs";
import path from "node:path";
import React from "react";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const flags: Record<string, string> = {};
vi.mock("@/context/FlagsContext", () => ({ useFlag: (k: string) => flags[k] ?? "off" }));
vi.mock("next/link", () => ({
  default: React.forwardRef<HTMLAnchorElement, React.AnchorHTMLAttributes<HTMLAnchorElement>>(function LinkStub(props, ref) {
    return <a ref={ref} {...props} />;
  }),
}));

import { NEW_SESSION_COPY, NewSessionV2, intentsFor } from "./NewSessionV2";
import { TutorHome } from "./TutorPages";

afterEach(() => {
  cleanup();
  for (const k of Object.keys(flags)) delete flags[k];
});

const DESIGN = fs.readFileSync(path.join(__dirname, "../__fixtures__/new-session.design.html"), "utf8").replace(/&#39;|&rsquo;|’/g, "'");
const FULL = {
  courseName: "CS 112", continueTitle: "Hash tables and 2 more", startWith: { id: "ht", name: "Hash tables" },
  dueCount: 7, dueHref: "/study?due=1", busy: false, starting: false, closesCurrent: "Hash tables and 2 more",
};

function renderNew(over: Partial<typeof FULL> = {}) {
  const on = { onContinue: vi.fn(), onStart: vi.fn(), onStartWith: vi.fn(), onGoal: vi.fn() };
  render(<NewSessionV2 {...FULL} {...over} {...on} />);
  return on;
}

describe("the choices", () => {
  it("only the sessions the Tutor can start, continue first and review last", () => {
    expect(intentsFor(FULL).map((i) => [i.id, i.title, i.line])).toEqual([
      ["continue", "Continue Hash tables and 2 more", "Pick up where you stopped."],
      ["concept", "Learn Hash tables", "Starts with a short check-in on it."],
      ["course", "Work through CS 112", "Starts with a short check-in, then a plan."],
      ["goal", "Work toward a goal", "Say what you want to learn and pick its concepts."],
      ["review", "Review", "7 reviews due."],
    ]);
    // nothing open, nothing suggested, nothing due (or Study hidden): two choices
    expect(intentsFor({ ...FULL, continueTitle: null, startWith: null, dueCount: 0 }).map((i) => i.id)).toEqual(["course", "goal"]);
    expect(intentsFor({ ...FULL, dueHref: null }).map((i) => i.id)).not.toContain("review");
  });
});

describe("parity with the design board", () => {
  it.each([NEW_SESSION_COPY.title, NEW_SESSION_COPY.legend, "Start learning",
    NEW_SESSION_COPY.wrapsUp("Hash tables and 2 more")])("the board says %j", (text) => {
    expect(DESIGN).toContain(text);
  });

  it("the question takes focus, one radio per choice, one start button named for the pick", () => {
    renderNew();
    expect(screen.getByRole("heading", { name: NEW_SESSION_COPY.title })).toHaveFocus();
    const group = screen.getByRole("group", { name: NEW_SESSION_COPY.legend });
    expect(within(group).getAllByRole("radio")).toHaveLength(5);
    expect(screen.getByRole("radio", { name: /Work through CS 112/ })).toBeChecked(); // the old home's one CTA
    const start = screen.getByTestId("loop-start-guided");
    expect(start.textContent).toBe("New session");
    fireEvent.click(screen.getByRole("radio", { name: /Learn Hash tables/ }));
    expect(start.textContent).toBe("Start learning");
    expect(screen.getAllByRole("button").filter((b) => b.className.includes("btn--primary"))).toHaveLength(1);
  });

  it("each pick starts its own session", () => {
    const on = renderNew();
    const start = () => fireEvent.click(screen.getByTestId("loop-start-guided"));
    start();
    expect(on.onStart).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByRole("radio", { name: /Learn Hash tables/ }));
    start();
    expect(on.onStartWith).toHaveBeenCalledWith({ id: "ht", name: "Hash tables" });
    fireEvent.click(screen.getByRole("radio", { name: /Work toward a goal/ }));
    start();
    expect(on.onGoal).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByRole("radio", { name: /Continue Hash tables/ }));
    start();
    expect(on.onContinue).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByRole("radio", { name: /^Review/ }));
    const review = screen.getByTestId("loop-start-guided");
    expect(review.tagName).toBe("A");
    expect(review.getAttribute("href")).toBe("/study?due=1");
    expect(review.textContent).toBe("Review"); // the glossary's word, not the board's retired "Start review"
  });

  it("the wrap-up line shows only for a choice that starts a new session", () => {
    renderNew();
    expect(screen.getByTestId("tutor-new-wraps-up").textContent).toBe("This wraps up your open session, Hash tables and 2 more.");
    fireEvent.click(screen.getByRole("radio", { name: /Continue Hash tables/ }));
    expect(screen.queryByTestId("tutor-new-wraps-up")).toBeNull();
  });

  it("while a start is in flight every choice is locked and the button says so", () => {
    renderNew({ busy: true, starting: true });
    expect(screen.getByTestId("loop-start-guided").textContent).toBe("Starting…");
    expect((screen.getByTestId("loop-start-guided") as HTMLButtonElement).disabled).toBe(true);
    for (const r of screen.getAllByRole("radio")) expect(r).toBeDisabled(); // through the fieldset
  });
});

describe("TutorHome", () => {
  const props = {
    courseName: "CS 112", continueRow: null, dueCount: 0, dueHref: null, startWith: null, busy: false, starting: false,
    closesCurrent: null, onContinue: () => {}, onStart: () => {}, onStartWith: () => {}, onGoal: () => {},
  };

  it("new_session_v2 off: the home as before", () => {
    render(<TutorHome {...props} />);
    expect(screen.getByRole("heading", { name: "What do you want to learn today?" })).toBeTruthy();
    expect(screen.queryByTestId("tutor-new-session-v2")).toBeNull();
  });

  it("new_session_v2 on: the rebuilt one, keeping the home's testid", () => {
    flags.new_session_v2 = "on";
    render(<TutorHome {...props} />);
    expect(screen.getByTestId("tutor-home")).toBeTruthy();
    expect(screen.getByTestId("tutor-new-session-v2")).toBeTruthy();
  });
});

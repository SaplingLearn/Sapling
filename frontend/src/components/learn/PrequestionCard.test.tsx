// @vitest-environment jsdom
/**
 * The segment prequestion card (spec §13 A138): a region named by its heading,
 * an ungraded guess — a radio group of the served options (useRadioGroup) or a
 * text box — "No idea" always available, the guess payload the stream route
 * takes, the resumed "answered" state, and the focus a new question takes
 * (spec §13 A135).
 */
import React from "react";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { LoopPrequestion } from "@/lib/api";
import { PREQUESTION_HEADING, PrequestionCard, renderGuess } from "./PrequestionCard";

afterEach(cleanup);

const mc: LoopPrequestion = {
  question_hash: "pq-mc",
  format: "mc_reason",
  difficulty: 1,
  prompt: "Which option names the sentinel?",
  options: [
    { letter: "A", text: "the alpha sentinel phrase" },
    { letter: "B", text: "the kilo sentinel phrase" },
    { letter: "C", text: "the zulu sentinel phrase" },
  ],
  text: "Take a guess first — this one isn't scored.\n\nWhich option names the sentinel?",
};
const free: LoopPrequestion = {
  question_hash: "pq-free", format: "free", difficulty: 2, prompt: "What stops a recursion?", options: null,
  text: "Take a guess first — this one isn't scored.\n\nWhat stops a recursion?",
};

function renderCard(pq: LoopPrequestion, over: { busy?: boolean } = {}) {
  const onGuess = vi.fn();
  const onExplain = vi.fn();
  const view = render(<PrequestionCard prequestion={pq} busy={over.busy ?? false} onGuess={onGuess} onExplain={onExplain} />);
  return { ...view, onGuess, onExplain };
}

describe("PrequestionCard (spec §13 A138)", () => {
  it("is a region named by its heading, says it is not scored, and carries the pose's attributes", () => {
    renderCard(mc);
    const region = screen.getByRole("region", { name: PREQUESTION_HEADING });
    expect(region).toBe(screen.getByTestId("loop-prequestion"));
    expect(region).toHaveAttribute("data-question-hash", "pq-mc");
    expect(region).toHaveAttribute("data-format", "mc_reason");
    expect(region).toHaveAttribute("data-difficulty", "1");
    expect(region).toHaveAttribute("data-answered", "false");
    expect(region.textContent).toContain("isn't scored");
    expect(screen.getByTestId("loop-prequestion-prompt").textContent).toBe("Which option names the sentinel?");
  });

  it("multiple choice is a radio group named by the question: one tab stop, the arrow keys move and choose", () => {
    const { onGuess } = renderCard(mc);
    const group = screen.getByRole("radiogroup", { name: "Which option names the sentinel?" });
    expect(group).toBe(screen.getByTestId("loop-prequestion-options"));
    const [a, b, c] = within(group).getAllByRole("radio");
    expect(a).toHaveAccessibleName("A. the alpha sentinel phrase");
    expect([a, b, c].map((r) => r.tabIndex)).toEqual([0, -1, -1]);
    expect(a).toHaveFocus(); // a new question takes focus: the group's tab stop
    expect(screen.getByTestId("loop-prequestion-submit")).toBeDisabled(); // nothing chosen yet
    fireEvent.keyDown(a, { key: "ArrowDown" });
    expect(b).toHaveFocus();
    expect(b).toHaveAttribute("aria-checked", "true");
    fireEvent.keyDown(b, { key: "End" });
    expect(c).toHaveAttribute("aria-checked", "true");
    fireEvent.keyDown(c, { key: "Home" });
    expect(a).toHaveAttribute("aria-checked", "true");
    fireEvent.change(screen.getByRole("textbox", { name: "Why you think so (optional)" }), { target: { value: "  it sounds right  " } });
    fireEvent.click(screen.getByTestId("loop-prequestion-submit"));
    expect(onGuess).toHaveBeenCalledExactlyOnceWith({ option: "A", reason: "it sounds right", no_idea: false });
  });

  it("a multiple-choice guess with no reason sends the option alone", () => {
    const { onGuess } = renderCard(mc);
    fireEvent.click(screen.getByTestId("loop-prequestion-option-C"));
    fireEvent.click(screen.getByTestId("loop-prequestion-submit"));
    expect(onGuess).toHaveBeenCalledExactlyOnceWith({ option: "C", no_idea: false });
  });

  it("a free item takes a typed guess, described by the question; Ctrl+Enter submits it", () => {
    const { onGuess } = renderCard(free);
    const box = screen.getByRole("textbox", { name: "Your guess" });
    expect(box).toHaveFocus();
    expect(box).toHaveAccessibleDescription("What stops a recursion?");
    expect(screen.getByTestId("loop-prequestion-submit")).toBeDisabled();
    fireEvent.change(box, { target: { value: "  a base case " } });
    fireEvent.keyDown(box, { key: "Enter", ctrlKey: true });
    expect(onGuess).toHaveBeenCalledExactlyOnceWith({ answer: "a base case", no_idea: false });
  });

  it("No idea is always there and sends no guess", () => {
    const { onGuess } = renderCard(free);
    fireEvent.click(screen.getByTestId("loop-prequestion-no-idea"));
    expect(onGuess).toHaveBeenCalledExactlyOnceWith({ no_idea: true });
  });

  it("while it is sent nothing can be sent twice", () => {
    const { onGuess } = renderCard(mc, { busy: true });
    expect(screen.getByTestId("loop-prequestion-submit")).toBeDisabled();
    expect(screen.getByTestId("loop-prequestion-no-idea")).toBeDisabled();
    fireEvent.click(screen.getByTestId("loop-prequestion-no-idea"));
    expect(onGuess).not.toHaveBeenCalled();
  });

  it("a guess already saved offers the owed explanation instead of asking again", () => {
    const { onExplain, onGuess } = renderCard({ ...free, answered: true });
    expect(screen.getByTestId("loop-prequestion")).toHaveAttribute("data-answered", "true");
    expect(screen.queryByTestId("loop-prequestion-input")).toBeNull();
    expect(screen.queryByTestId("loop-prequestion-no-idea")).toBeNull();
    expect(screen.getByText("Your guess is saved.")).toBeTruthy();
    const explain = screen.getByTestId("loop-prequestion-explain");
    expect(explain).toHaveFocus();
    fireEvent.click(explain);
    expect(onExplain).toHaveBeenCalledTimes(1);
    expect(onGuess).not.toHaveBeenCalled();
  });

  it("does not take focus while a modal dialog owns it", () => {
    const modal = document.createElement("div");
    modal.setAttribute("aria-modal", "true");
    document.body.appendChild(modal);
    try {
      renderCard(free);
      expect(screen.getByRole("textbox", { name: "Your guess" })).not.toHaveFocus();
    } finally {
      modal.remove();
    }
  });

  it("renders the guess row the log shows (the server saves the same words)", () => {
    expect(renderGuess({ no_idea: true })).toBe("No idea.");
    expect(renderGuess({ option: "B", no_idea: false })).toBe("My guess: B");
    expect(renderGuess({ option: "B", reason: "it repeats", no_idea: false })).toBe("My guess: B — it repeats");
    expect(renderGuess({ answer: "a base case", no_idea: false })).toBe("My guess: a base case");
  });
});

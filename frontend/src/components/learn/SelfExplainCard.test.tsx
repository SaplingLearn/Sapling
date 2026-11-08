// @vitest-environment jsdom
/**
 * The self-explanation card (spec §13 A139): a region named by its heading,
 * the "why" prompt describing the reply box, Send (only with text) and Skip,
 * and the ref LoopLearn moves focus to after feedback.
 */
import React from "react";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { LoopSelfExplain } from "@/lib/api";
import { SELF_EXPLAIN_HEADING, SelfExplainCard } from "./SelfExplainCard";

afterEach(cleanup);

const prompt: LoopSelfExplain = {
  prompt_id: "se-1",
  juncture: "worked_example",
  prompt: "Why does each step of that worked example follow from the one before it?",
};

function renderCard(over: { busy?: boolean; nested?: boolean; inputRef?: React.Ref<HTMLTextAreaElement> } = {}) {
  const onSend = vi.fn();
  const onSkip = vi.fn();
  const view = render(
    <SelfExplainCard prompt={prompt} busy={over.busy ?? false} onSend={onSend} onSkip={onSkip} nested={over.nested} inputRef={over.inputRef} />,
  );
  return { ...view, onSend, onSkip };
}

describe("SelfExplainCard (spec §13 A139)", () => {
  it("is a region named by its heading, says it is not scored, and names its juncture and prompt", () => {
    renderCard();
    const region = screen.getByRole("region", { name: SELF_EXPLAIN_HEADING });
    expect(region).toBe(screen.getByTestId("loop-self-explain"));
    expect(region).toHaveAttribute("data-juncture", "worked_example");
    expect(region).toHaveAttribute("data-prompt-id", "se-1");
    expect(region.textContent).toContain("Not scored");
    expect(screen.getByTestId("loop-self-explain-prompt").textContent).toBe(prompt.prompt);
    expect(screen.getByRole("heading", { name: SELF_EXPLAIN_HEADING }).tagName).toBe("H2");
  });

  it("the reply box is described by the prompt; Send waits for text and sends it trimmed", () => {
    const { onSend } = renderCard();
    const box = screen.getByRole("textbox", { name: "Your explanation" });
    expect(box).toHaveAccessibleDescription(prompt.prompt);
    const send = screen.getByTestId("loop-self-explain-send");
    expect(send).toBeDisabled();
    fireEvent.change(box, { target: { value: "   " } });
    expect(send).toBeDisabled();
    fireEvent.change(box, { target: { value: "  Each step applies the same rule.  " } });
    fireEvent.click(send);
    expect(onSend).toHaveBeenCalledExactlyOnceWith("Each step applies the same rule.");
  });

  it("Ctrl+Enter sends; Skip sends nothing but the skip", () => {
    const { onSend, onSkip } = renderCard();
    const box = screen.getByRole("textbox", { name: "Your explanation" });
    fireEvent.change(box, { target: { value: "Because the rule repeats." } });
    fireEvent.keyDown(box, { key: "Enter", metaKey: true });
    expect(onSend).toHaveBeenCalledExactlyOnceWith("Because the rule repeats.");
    fireEvent.click(screen.getByTestId("loop-self-explain-skip"));
    expect(onSkip).toHaveBeenCalledTimes(1);
  });

  it("while it is saved nothing can be sent twice", () => {
    const { onSend, onSkip } = renderCard({ busy: true });
    expect(screen.getByTestId("loop-self-explain-send")).toBeDisabled();
    expect(screen.getByTestId("loop-self-explain-skip")).toBeDisabled();
    fireEvent.click(screen.getByTestId("loop-self-explain-skip"));
    expect(onSend).not.toHaveBeenCalled();
    expect(onSkip).not.toHaveBeenCalled();
  });

  it("nested under a hint it is a sub-section, and it never takes focus on its own", () => {
    renderCard({ nested: true });
    expect(screen.getByRole("heading", { name: SELF_EXPLAIN_HEADING }).tagName).toBe("H3");
    expect(screen.getByRole("textbox", { name: "Your explanation" })).not.toHaveFocus();
  });

  it("hands its reply box to the caller's ref (LoopLearn's focus target after feedback)", () => {
    const ref = React.createRef<HTMLTextAreaElement>();
    renderCard({ inputRef: ref });
    expect(ref.current).toBe(screen.getByTestId("loop-self-explain-input"));
  });
});

// @vitest-environment jsdom
import React from "react";
import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, cleanup, fireEvent } from "@testing-library/react";
import type { HighlightInteraction } from "@/lib/quiz/types";
import { encodeHighlightAnswer } from "@/lib/quiz/highlightInteraction";
import { HighlightAnswer } from "./HighlightAnswer";

const POEM: HighlightInteraction = {
  kind: "highlight",
  note: "Select the claim.",
  passages: [
    { id: "l0", label: "Line zero" },
    { id: "l4", label: "Line four" },
    { id: "l5", label: "Line five" },
  ],
};

afterEach(cleanup);

function mount(over: Partial<React.ComponentProps<typeof HighlightAnswer>> = {}) {
  const onChange = over.onChange ?? vi.fn();
  render(
    <HighlightAnswer
      interaction={POEM}
      value=""
      disabled={false}
      onChange={onChange}
      {...over}
    />,
  );
  return { onChange };
}

describe("HighlightAnswer", () => {
  it("lists every passage", () => {
    mount();
    expect(screen.getByTestId("quiz-highlight")).toHaveAttribute("data-complete", "false");
    expect(screen.getByTestId("quiz-highlight-note")).toHaveTextContent(/Select the claim/);
    expect(screen.getByTestId("quiz-highlight-row-l4")).toBeInTheDocument();
  });

  it("toggles a passage into answerText", () => {
    const { onChange } = mount();
    fireEvent.click(screen.getByTestId("quiz-highlight-row-l5"));
    expect(onChange).toHaveBeenCalledWith("l5");
  });

  it("tones rows from the expected encode once a verdict is shown", () => {
    mount({
      value: encodeHighlightAnswer(["l0"]),
      expected: encodeHighlightAnswer(["l4", "l5"]),
      verdict: "incorrect",
    });
    expect(screen.getByTestId("quiz-highlight-row-l0").className).toMatch(/--wrong/);
    expect(screen.getByTestId("quiz-highlight-row-l4").className).toMatch(/--right/);
  });
});

// @vitest-environment jsdom
/**
 * W7.2 Compare: two sides + relation chips under SessionTop patterns —
 * encode into short_answer text, verdict option tones.
 */

import React from "react";
import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, cleanup, fireEvent } from "@testing-library/react";
import type { CompareInteraction } from "@/lib/quiz/types";
import { CompareAnswer } from "./CompareAnswer";

const MITOSIS: CompareInteraction = {
  kind: "compare",
  left: { id: "mitosis", label: "Mitosis" },
  right: { id: "meiosis", label: "Meiosis" },
  options: [
    { id: "left_only", label: "Only the left" },
    { id: "right_only", label: "Only the right" },
    { id: "both", label: "Both" },
    { id: "neither", label: "Neither" },
  ],
};

afterEach(cleanup);

function mount(over: Partial<React.ComponentProps<typeof CompareAnswer>> = {}) {
  const onChange = over.onChange ?? vi.fn();
  render(
    <CompareAnswer
      interaction={MITOSIS}
      value=""
      disabled={false}
      onChange={onChange}
      {...over}
    />,
  );
  return { onChange };
}

describe("CompareAnswer", () => {
  it("shows both sides and every relation option", () => {
    mount();
    expect(screen.getByTestId("quiz-compare")).toHaveAttribute("data-complete", "false");
    expect(screen.getByTestId("quiz-compare-side-mitosis")).toHaveAttribute("data-side", "mitosis");
    expect(screen.getByTestId("quiz-compare-side-meiosis")).toHaveAttribute("data-side", "meiosis");
    for (const id of ["left_only", "right_only", "both", "neither"]) {
      expect(screen.getByTestId(`quiz-compare-option-${id}`)).toBeInTheDocument();
    }
  });

  it("selects a relation and encodes answerText", () => {
    const { onChange } = mount();
    fireEvent.click(screen.getByTestId("quiz-compare-option-both"));
    expect(onChange).toHaveBeenCalledWith("both");
  });

  it("clears the choice when the same option is clicked again", () => {
    const { onChange } = mount({ value: "both" });
    expect(screen.getByTestId("quiz-compare")).toHaveAttribute("data-complete", "true");
    fireEvent.click(screen.getByTestId("quiz-compare-option-both"));
    expect(onChange).toHaveBeenCalledWith("");
  });

  it("tones options from the expected encode once a verdict is shown", () => {
    mount({ value: "left_only", expected: "both", verdict: "incorrect" });
    expect(screen.getByTestId("quiz-compare-option-left_only").className).toMatch(/--wrong/);
    expect(screen.getByTestId("quiz-compare-option-both").className).toMatch(/--right/);
  });
});

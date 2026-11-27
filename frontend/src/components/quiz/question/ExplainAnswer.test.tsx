// @vitest-environment jsdom
/**
 * W7.2 Explain: tall prose + optional rubric under SessionTop patterns.
 */

import React from "react";
import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, cleanup, fireEvent } from "@testing-library/react";
import type { ExplainInteraction } from "@/lib/quiz/types";
import { ExplainAnswer } from "./ExplainAnswer";

const ORBIT: ExplainInteraction = {
  kind: "explain",
  placeholder: "Type your explanation",
  rubric: [
    "The station and astronauts are in continuous free fall",
    "Their sideways speed keeps them in orbit",
  ],
};

afterEach(cleanup);

function mount(over: Partial<React.ComponentProps<typeof ExplainAnswer>> = {}) {
  const onChange = over.onChange ?? vi.fn();
  render(
    <ExplainAnswer
      interaction={ORBIT}
      value=""
      disabled={false}
      onChange={onChange}
      {...over}
    />,
  );
  return { onChange };
}

describe("ExplainAnswer", () => {
  it("shows the prose field and stays incomplete while empty", () => {
    mount();
    expect(screen.getByTestId("quiz-explain")).toHaveAttribute("data-complete", "false");
    expect(screen.getByTestId("quiz-explain-input")).toHaveAttribute(
      "placeholder",
      "Type your explanation",
    );
    expect(screen.queryByTestId("quiz-explain-rubric")).not.toBeInTheDocument();
  });

  it("writes answerText as the student types", () => {
    const { onChange } = mount();
    fireEvent.change(screen.getByTestId("quiz-explain-input"), {
      target: { value: "They fall together around Earth." },
    });
    expect(onChange).toHaveBeenCalledWith("They fall together around Earth.");
  });

  it("shows rubric rows once a verdict is present", () => {
    mount({
      value: "They fall together around Earth.",
      verdict: "correct",
    });
    expect(screen.getByTestId("quiz-explain")).toHaveAttribute("data-complete", "true");
    expect(screen.getByTestId("quiz-explain-rubric")).toBeInTheDocument();
    expect(screen.getByTestId("quiz-explain-rubric-0").className).toMatch(/--right/);
  });
});

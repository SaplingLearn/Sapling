// @vitest-environment jsdom
import React from "react";
import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, cleanup, fireEvent } from "@testing-library/react";
import type { CalculateInteraction } from "@/lib/quiz/types";
import { CalculateAnswer } from "./CalculateAnswer";

const CAR: CalculateInteraction = {
  kind: "calculate",
  placeholder: "Your answer",
  unitLabel: "Units",
};

afterEach(cleanup);

function mount(over: Partial<React.ComponentProps<typeof CalculateAnswer>> = {}) {
  const onChange = over.onChange ?? vi.fn();
  render(
    <CalculateAnswer
      interaction={CAR}
      value=""
      disabled={false}
      onChange={onChange}
      {...over}
    />,
  );
  return { onChange };
}

describe("CalculateAnswer", () => {
  it("shows value and unit fields", () => {
    mount();
    expect(screen.getByTestId("quiz-calculate")).toHaveAttribute("data-complete", "false");
    expect(screen.getByTestId("quiz-calculate-value")).toBeInTheDocument();
    expect(screen.getByTestId("quiz-calculate-unit")).toBeInTheDocument();
  });

  it("encodes value|unit as the student types", () => {
    const { onChange } = mount({ value: "12|" });
    fireEvent.change(screen.getByTestId("quiz-calculate-unit"), {
      target: { value: "m/s" },
    });
    expect(onChange).toHaveBeenCalledWith("12|m/s");
  });

  it("marks complete when both sides are filled", () => {
    mount({ value: "12|m/s" });
    expect(screen.getByTestId("quiz-calculate")).toHaveAttribute("data-complete", "true");
  });
});

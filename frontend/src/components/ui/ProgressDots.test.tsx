// @vitest-environment jsdom
import { describe, it, expect, afterEach } from "vitest";
import { render, screen, cleanup } from "@testing-library/react";
import React from "react";
import { ProgressDots } from "./ProgressDots";

afterEach(cleanup);

const kinds = (container: HTMLElement) =>
  Array.from(container.querySelectorAll(".progress-dots__dot")).map((d) =>
    d.className.replace("progress-dots__dot progress-dots__dot--", ""),
  );

describe("ProgressDots", () => {
  it("is one labelled image, not a list of anonymous dots", () => {
    render(<ProgressDots total={5} current={2} answered={2} ariaLabel="Question 3 of 5" />);
    const el = screen.getByRole("img", { name: "Question 3 of 5" });
    expect(el).toHaveClass("progress-dots", "progress-dots--column");
  });

  it("marks answered, current and upcoming", () => {
    const { container } = render(
      <ProgressDots total={5} current={2} answered={2} ariaLabel="Question 3 of 5" />,
    );
    expect(kinds(container)).toEqual(["done", "done", "current", "todo", "todo"]);
  });

  it("shows 'you are here' over 'you answered this' when revisiting", () => {
    const { container } = render(
      <ProgressDots total={4} current={1} answered={4} ariaLabel="Question 2 of 4" />,
    );
    expect(kinds(container)).toEqual(["done", "current", "done", "done"]);
  });

  it("renders one dot per item at any count, and nothing at zero", () => {
    const { container, rerender } = render(
      <ProgressDots total={3} current={0} answered={0} ariaLabel="Question 1 of 3" />,
    );
    expect(kinds(container)).toHaveLength(3);
    rerender(<ProgressDots total={0} current={0} answered={0} ariaLabel="No questions" />);
    expect(kinds(container)).toHaveLength(0);
  });

  it("takes the row orientation Onboarding's step indicator wants", () => {
    render(
      <ProgressDots
        total={3}
        current={1}
        answered={1}
        orientation="row"
        ariaLabel="Step 2 of 3"
        testid="onboarding-progress"
      />,
    );
    const el = screen.getByTestId("onboarding-progress");
    expect(el).toHaveClass("progress-dots--row");
    expect(el).not.toHaveClass("progress-dots--column");
  });
});

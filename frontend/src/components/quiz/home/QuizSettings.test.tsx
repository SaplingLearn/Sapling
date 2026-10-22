// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { QuizConfig } from "@/lib/quiz/types";
import { QuizSettings } from "./QuizSettings";

const CONFIG: QuizConfig = {
  num_questions: { min: 5, max: 5, options: [5] },
  difficulties: ["medium"],
  question_types: ["multiple_choice", "mixed"],
};

describe("QuizSettings — the Mixed format note", () => {
  afterEach(cleanup);

  it("is visible text, not the question screen's visually hidden hint", () => {
    render(
      <QuizSettings
        config={CONFIG}
        value={{ count: 5, difficulty: "medium", feedback: "at-end", questionFormat: "mixed" }}
        onChange={vi.fn()}
      />,
    );
    const note = screen.getByTestId("quiz-format-mixed-note");
    expect(note).toHaveTextContent("A variety suited to your course");
    expect(note).not.toHaveClass("quiz-question__hint");
  });

  it("is absent for a single format", () => {
    render(
      <QuizSettings
        config={CONFIG}
        value={{ count: 5, difficulty: "medium", feedback: "at-end", questionFormat: "multiple_choice" }}
        onChange={vi.fn()}
      />,
    );
    expect(screen.queryByTestId("quiz-format-mixed-note")).toBeNull();
  });
});

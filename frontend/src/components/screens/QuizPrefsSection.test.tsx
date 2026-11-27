// @vitest-environment jsdom
/**
 * W7.9: Settings Preferences → Quiz reads/writes lib/quiz/prefs.ts; hidden
 * under hide_quiz. No user_settings columns.
 */
import React from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";

const flagState = vi.hoisted(() => ({ hideQuiz: false }));
vi.mock("@/context/FlagsContext", () => ({
  useFlag: (key: string) => (key === "hide_quiz" && flagState.hideQuiz ? "on" : "off"),
}));

vi.mock("@/lib/quiz/useQuizConfig", () => ({
  useQuizConfig: () => ({
    config: {
      num_questions: { min: 3, max: 10, options: [3, 5, 10] },
      difficulties: ["easy", "medium", "hard", "adaptive"],
      question_types: ["multiple_choice", "short_answer", "mixed"],
    },
    error: null,
  }),
  resetQuizConfigCache: () => {},
}));

/** Stub CustomSelect as a native <select> so the prefs write path is exerciseable. */
vi.mock("@/components/CustomSelect", () => ({
  CustomSelect: ({
    value,
    onChange,
    options,
    testId,
    ariaLabel,
  }: {
    value: string;
    onChange: (v: string) => void;
    options: { value: string; label: React.ReactNode }[];
    testId?: string;
    ariaLabel: string;
  }) => (
    <select
      data-testid={testId}
      aria-label={ariaLabel}
      value={value}
      onChange={e => onChange(e.target.value)}
    >
      {options.map(o => (
        <option key={o.value} value={o.value}>{o.label}</option>
      ))}
    </select>
  ),
}));

import { PREFS_KEY } from "@/lib/quiz/session";
import { loadPrefs } from "@/lib/quiz/prefs";

import { QuizPrefsSection } from "./QuizPrefsSection";

beforeEach(() => {
  window.localStorage.clear();
  flagState.hideQuiz = false;
});

afterEach(() => {
  cleanup();
  flagState.hideQuiz = false;
});

describe("QuizPrefsSection (W7.9)", () => {
  it("renders Length / Difficulty / Answers / Format and persists to prefs", () => {
    render(<QuizPrefsSection />);
    expect(screen.getByTestId("settings-quiz-prefs")).toBeTruthy();
    expect(screen.getByTestId("settings-quiz-length")).toBeTruthy();
    expect(screen.getByTestId("settings-quiz-difficulty")).toBeTruthy();
    expect(screen.getByTestId("settings-quiz-answers")).toBeTruthy();
    expect(screen.getByTestId("settings-quiz-format")).toBeTruthy();
    expect(screen.queryByText(/Definitive|Conceptual/i)).toBeNull();

    fireEvent.change(screen.getByTestId("settings-quiz-difficulty"), { target: { value: "hard" } });
    expect(loadPrefs()).toMatchObject({ difficulty: "hard", feedback: "at-end" });
    expect(JSON.parse(window.localStorage.getItem(PREFS_KEY)!)).toMatchObject({
      difficulty: "hard",
    });
  });

  it("is absent while hide_quiz is on", () => {
    flagState.hideQuiz = true;
    render(<QuizPrefsSection />);
    expect(screen.queryByTestId("settings-quiz-prefs")).toBeNull();
  });
});

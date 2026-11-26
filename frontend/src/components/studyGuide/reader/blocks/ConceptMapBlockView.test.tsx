// @vitest-environment jsdom
/**
 * W7.9: concept-map "Quiz this concept" is a Quiz deep link (`topic` + `start=1`),
 * not a tutor Ask prompt; hidden under `hide_quiz`.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";

const flagState = vi.hoisted(() => ({ hideQuiz: false }));
vi.mock("@/context/FlagsContext", () => ({
  useFlag: (key: string) => (key === "hide_quiz" && flagState.hideQuiz ? "on" : "off"),
  useFlagMap: () => ({
    flags: flagState.hideQuiz ? { hide_quiz: "on" } : {},
    ready: true,
    fresh: true,
  }),
}));

import type { ConceptMapBlock, GuideDetail } from "@/lib/studyGuide/types";

import { ReaderProvider, type Reader } from "../ReaderContext";
import { fixtureGuide } from "../readerFixture";
import { ConceptMapBlockView, guideConceptQuizHref } from "./ConceptMapBlockView";

const BLOCK: ConceptMapBlock = {
  type: "concept_map",
  id: "cm1",
  title: "Build-up",
  nodes: [
    { concept: "Loops", step: "1" },
    { concept: "Recursion", step: "2" },
  ],
};

function view(guide: GuideDetail = fixtureGuide()) {
  const reader: Reader = {
    userId: "u1",
    guide,
    mode: "read",
    generating: false,
    rewriting: null,
    update: () => {},
    regenerateBlock: () => {},
    askTutor: async () => {},
    tutorBusy: false,
  };
  return (
    <ReaderProvider value={reader}>
      <ConceptMapBlockView block={BLOCK} />
    </ReaderProvider>
  );
}

afterEach(() => {
  cleanup();
  flagState.hideQuiz = false;
});

describe("guideConceptQuizHref", () => {
  it("deep-links the concept name with start=1 and returns to the guide", () => {
    expect(guideConceptQuizHref("guide-9", "Recursion")).toBe(
      "/quiz?topic=Recursion&from=link&return=%2Fstudy%2Fguide%2Fguide-9&start=1",
    );
  });
});

describe("ConceptMapBlockView Quiz this concept (W7.9)", () => {
  it("offers Quiz this concept as a start=1 link, not a tutor prompt", () => {
    const guide = fixtureGuide({ id: "g-abc" });
    render(view(guide));
    fireEvent.click(screen.getByTestId("guide-concept-cm1-1"));
    const quiz = screen.getByTestId("guide-concept-quiz-cm1");
    expect(quiz).toHaveAttribute("href", guideConceptQuizHref("g-abc", "Recursion"));
    expect(quiz).toHaveTextContent("Quiz this concept");
    expect(screen.queryByText("Quiz me on this")).toBeNull();
    expect(screen.getByTestId("guide-concept-prompt-cm1-0")).toHaveTextContent("Explain it a simpler way");
    expect(screen.getByTestId("guide-concept-prompt-cm1-1")).toHaveTextContent("Give me another example");
  });

  it("hides the Quiz link under hide_quiz", () => {
    flagState.hideQuiz = true;
    render(view());
    fireEvent.click(screen.getByTestId("guide-concept-cm1-0"));
    expect(screen.queryByTestId("guide-concept-quiz-cm1")).toBeNull();
    expect(screen.getByTestId("guide-concept-prompt-cm1-0")).toBeTruthy();
  });
});

// @vitest-environment jsdom
/**
 * The check block shows the answer the guide holds for it, and nothing it
 * remembers by itself: a question rewritten under the same id is unanswered.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";

vi.mock("@/lib/studyGuide/api", () => ({ answerCheck: vi.fn() }));

import { ToastProvider } from "@/components/ToastProvider";
import type { CheckBlock, GuideDetail } from "@/lib/studyGuide/types";

import { ReaderProvider, type Reader } from "../ReaderContext";
import { fixtureGuide } from "../readerFixture";
import { CheckBlockView } from "./CheckBlockView";

const BLOCK: CheckBlock = {
  type: "check",
  id: "s1-i8",
  question: "How many times does the body run?",
  options: [
    { id: "a", text: "3" },
    { id: "b", text: "4" },
  ],
  correct_id: "b",
  explain_correct: "0, 2, 4 and 6 pass the test.",
  explain_incorrect: null,
  concept: "Loops",
};

function view(guide: GuideDetail, block: CheckBlock) {
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
    <ToastProvider>
      <ReaderProvider value={reader}>
        <CheckBlockView block={block} />
      </ReaderProvider>
    </ToastProvider>
  );
}

afterEach(cleanup);

describe("the check block", () => {
  it("marks the picked option as checked when it is the correct one", () => {
    render(view(fixtureGuide({ answers: { "s1-i8": { option_id: "b", correct: true } } }), BLOCK));
    const picked = screen.getByTestId("guide-check-option-s1-i8-b");
    expect(picked).toHaveAttribute("aria-checked", "true");
    expect(picked).toHaveAccessibleName(/correct answer/);
    expect(screen.getByTestId("guide-check-option-s1-i8-a")).toHaveAttribute("aria-checked", "false");
  });

  it("forgets the answer when the question under its id is replaced", () => {
    const answered = fixtureGuide({ answers: { "s1-i8": { option_id: "b", correct: true } } });
    const { rerender } = render(view(answered, BLOCK));
    expect(screen.getByTestId("guide-check-result-s1-i8")).toHaveTextContent("Correct. 0, 2, 4 and 6 pass the test.");

    // The guide was rewritten: same id, a new question, no answer on record.
    const rewritten: CheckBlock = { ...BLOCK, question: "What does range(3) yield?", correct_id: null, explain_correct: null };
    rerender(view(fixtureGuide({ answers: {} }), rewritten));

    expect(screen.getByText("What does range(3) yield?")).toBeInTheDocument();
    expect(screen.queryByTestId("guide-check-result-s1-i8")).not.toBeInTheDocument();
    expect(screen.getByTestId("guide-check-option-s1-i8-b")).toHaveAttribute("aria-checked", "false");
    expect(screen.getByTestId("guide-check-option-s1-i8-b")).not.toHaveAccessibleName(/correct answer/);
  });
});

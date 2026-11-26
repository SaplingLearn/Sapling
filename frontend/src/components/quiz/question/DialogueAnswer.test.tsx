// @vitest-environment jsdom
/**
 * W7.2 Dialogue: partner thread + Send under SessionTop patterns —
 * encode into short_answer text, Check at minReplies.
 */

import React from "react";
import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, cleanup, fireEvent } from "@testing-library/react";
import type { DialogueInteraction } from "@/lib/quiz/types";
import { encodeDialogueAnswer } from "@/lib/quiz/dialogueInteraction";
import { DialogueAnswer } from "./DialogueAnswer";

const FALL: DialogueInteraction = {
  kind: "dialogue",
  role: "Confused Classmate",
  open: "Heavier objects fall faster, right?",
  follow: "But the bowling ball is pulled harder.",
  placeholder: "Reply to your classmate",
  minReplies: 2,
  maxReplies: 4,
};

afterEach(cleanup);

function mount(over: Partial<React.ComponentProps<typeof DialogueAnswer>> = {}) {
  const onChange = over.onChange ?? vi.fn();
  render(
    <DialogueAnswer
      interaction={FALL}
      value=""
      disabled={false}
      onChange={onChange}
      {...over}
    />,
  );
  return { onChange };
}

describe("DialogueAnswer", () => {
  it("shows the opening partner line and composer", () => {
    mount();
    expect(screen.getByTestId("quiz-dialogue")).toHaveAttribute("data-complete", "false");
    expect(screen.getByTestId("quiz-dialogue-role")).toHaveTextContent("Confused Classmate");
    expect(screen.getByTestId("quiz-dialogue-open")).toHaveTextContent(/Heavier objects/);
    expect(screen.queryByTestId("quiz-dialogue-follow")).not.toBeInTheDocument();
    expect(screen.getByTestId("quiz-dialogue-input")).toBeInTheDocument();
  });

  it("sends a reply, reveals the follow-up, and encodes answerText", () => {
    const { onChange } = mount();
    fireEvent.change(screen.getByTestId("quiz-dialogue-input"), {
      target: { value: "Same acceleration without air resistance." },
    });
    fireEvent.click(screen.getByTestId("quiz-dialogue-send"));
    expect(onChange).toHaveBeenCalledWith(
      encodeDialogueAnswer(["Same acceleration without air resistance."]),
    );
  });

  it("marks complete once minReplies are present", () => {
    mount({
      value: encodeDialogueAnswer(["First reply", "Second reply"]),
    });
    expect(screen.getByTestId("quiz-dialogue")).toHaveAttribute("data-complete", "true");
    expect(screen.getByTestId("quiz-dialogue-follow")).toBeInTheDocument();
    expect(screen.getByTestId("quiz-dialogue-reply-0")).toHaveTextContent("First reply");
    expect(screen.getByTestId("quiz-dialogue-reply-1")).toHaveTextContent("Second reply");
  });
});

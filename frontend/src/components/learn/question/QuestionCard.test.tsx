// @vitest-environment jsdom
import React from "react";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AnswerField, NOT_GRADED, QuestionActions, QuestionCard } from "./QuestionCard";

afterEach(cleanup);

function Card({ graded, nested, onSubmit = vi.fn() }: { graded: boolean; nested?: boolean; onSubmit?: () => void }) {
  return (
    <QuestionCard graded={graded} nested={nested} meta={graded ? "Question 1" : NOT_GRADED} prompt="What is a base case?" testId="card"
      head={{ testId: "head", "data-question-hash": "qh" }}>
      <AnswerField label="Your answer" name="answer" testId="answer" start value="" onChange={() => {}} onSubmit={onSubmit} />
      <QuestionActions
        submit={{ label: "Submit answer", busyLabel: "Checking…", busy: false, disabled: false, onClick: onSubmit, testId: "submit" }}
        optOut={{ label: "I don't know", onClick: () => {}, testId: "idk" }}
      />
    </QuestionCard>
  );
}

describe("QuestionCard", () => {
  it("is a region named by its one meta line, with the question and a head the tests can find", () => {
    render(<Card graded />);
    const region = screen.getByRole("region", { name: "Question 1" });
    expect(region.getAttribute("data-graded")).toBe("true");
    expect(screen.getByRole("heading", { name: "Question 1" }).tagName).toBe("H2");
    expect(screen.getByTestId("head").getAttribute("data-question-hash")).toBe("qh");
    expect(screen.getByTestId("head").textContent).toContain("What is a base case?");
  });

  it("every field is named by its visible label and described by the question", () => {
    render(<Card graded />);
    const box = screen.getByRole("textbox", { name: "Your answer" });
    expect(box).toHaveAccessibleDescription("What is a base case?");
    expect(box.hasAttribute("data-answer-start")).toBe(true);
    expect(screen.getByText("Your answer").tagName).toBe("LABEL");
  });

  it("⌘/Ctrl+Enter submits", () => {
    const onSubmit = vi.fn();
    render(<Card graded onSubmit={onSubmit} />);
    fireEvent.keyDown(screen.getByRole("textbox", { name: "Your answer" }), { key: "Enter", metaKey: true });
    fireEvent.keyDown(screen.getByRole("textbox", { name: "Your answer" }), { key: "Enter", ctrlKey: true });
    fireEvent.keyDown(screen.getByRole("textbox", { name: "Your answer" }), { key: "Enter" });
    expect(onSubmit).toHaveBeenCalledTimes(2);
  });

  it("not graded is the card's shape and its meta line; nested it is an h3 sub-section", () => {
    render(<Card graded={false} nested />);
    const region = screen.getByRole("region", { name: NOT_GRADED });
    expect(region.getAttribute("data-graded")).toBe("false");
    expect(region.className).not.toContain("card");
    expect(screen.getByRole("heading", { name: NOT_GRADED }).tagName).toBe("H3");
  });

  it("the busy label replaces the verb only while busy", () => {
    const { rerender } = render(
      <QuestionCard graded meta="Q" prompt="p">
        <QuestionActions submit={{ label: "Save guess", busyLabel: "Saving…", busy: false, disabled: false, onClick: () => {}, testId: "s" }} />
      </QuestionCard>,
    );
    expect(screen.getByTestId("s").textContent).toBe("Save guess");
    rerender(
      <QuestionCard graded meta="Q" prompt="p">
        <QuestionActions submit={{ label: "Save guess", busyLabel: "Saving…", busy: true, disabled: true, onClick: () => {}, testId: "s" }} />
      </QuestionCard>,
    );
    expect(screen.getByTestId("s").textContent).toBe("Saving…");
  });
});

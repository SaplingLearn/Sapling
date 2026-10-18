// @vitest-environment jsdom
import { describe, it, expect, afterEach } from "vitest";
import { render, screen, cleanup, fireEvent } from "@testing-library/react";
import React from "react";
import { __resetScrollLocksForTests } from "@/lib/useScrollLock";
import { QuizPrimitivesGallery } from "./QuizPrimitivesGallery";

afterEach(() => {
  cleanup();
  __resetScrollLocksForTests();
});

/**
 * A smoke test for the harness itself. Its job is to keep the gallery from
 * quietly rotting the next time a primitive's props change — a screenshot
 * target nobody can mount is worse than none.
 */
describe("QuizPrimitivesGallery", () => {
  it("mounts every primitive, with the course accent bound on the root", () => {
    const { container } = render(<QuizPrimitivesGallery />);
    const root = container.querySelector<HTMLElement>(".quiz-gallery")!;
    expect(root.style.getPropertyValue("--quiz-accent")).toBe("#7b4b99");

    expect(container.querySelectorAll(".btn").length).toBeGreaterThan(6);
    expect(container.querySelectorAll(".seg").length).toBe(4);
    expect(container.querySelectorAll(".answer-option").length).toBeGreaterThan(6);
    expect(container.querySelectorAll(".progress-dots").length).toBe(5);
    expect(container.querySelectorAll(".inline-banner").length).toBe(2);
    expect(container.querySelectorAll(".empty-state").length).toBe(2);
    expect(container.querySelectorAll(".concept-node").length).toBeGreaterThan(9);
    expect(container.querySelectorAll(".concept-neighbourhood").length).toBe(5);
  });

  it("shows all five AnswerOption states side by side", () => {
    const { container } = render(<QuizPrimitivesGallery />);
    for (const state of ["default", "selected", "correct", "chosen-wrong", "muted"]) {
      expect(container.querySelector(`.answer-option--${state}`)).not.toBeNull();
    }
  });

  it("opens the sheet, which portals out of the gallery", () => {
    render(<QuizPrimitivesGallery />);
    expect(screen.queryByTestId("gallery-sheet")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Ask about this" }));
    expect(screen.getByTestId("gallery-sheet")).toBeInTheDocument();
  });
});

// @vitest-environment jsdom
/**
 * W7.2 Sequence (kit 7.2): click-to-slot under SessionTop patterns — tray,
 * ordered slots, encode into short_answer text, verdict card tones.
 */

import React from "react";
import { describe, it, expect, vi, afterEach } from "vitest";
import { fireEvent, render, screen, cleanup } from "@testing-library/react";
import { encodeSequenceAnswer } from "@/lib/quiz/sequenceInteraction";
import type { SequenceInteraction } from "@/lib/quiz/types";
import { SequenceAnswer } from "./SequenceAnswer";

afterEach(cleanup);

const MITOSIS: SequenceInteraction = {
  kind: "sequence",
  steps: [
    { id: "prophase", label: "Prophase" },
    { id: "metaphase", label: "Metaphase" },
    { id: "anaphase", label: "Anaphase" },
  ],
};

function mount(over: Partial<React.ComponentProps<typeof SequenceAnswer>> = {}) {
  const onChange = vi.fn();
  render(
    <SequenceAnswer
      interaction={MITOSIS}
      value=""
      disabled={false}
      onChange={onChange}
      {...over}
    />,
  );
  return { onChange };
}

describe("SequenceAnswer", () => {
  it("renders tray + numbered slots", () => {
    mount();
    expect(screen.getByTestId("quiz-sequence")).toHaveAttribute("data-complete", "false");
    expect(screen.getByTestId("quiz-sequence-tray")).toBeInTheDocument();
    expect(screen.getByTestId("quiz-sequence-slots")).toBeInTheDocument();
    for (const id of ["prophase", "metaphase", "anaphase"]) {
      expect(screen.getByTestId(`quiz-sequence-item-${id}`)).toBeInTheDocument();
    }
    expect(screen.getByTestId("quiz-sequence-slot-0")).toHaveAttribute("data-slot", "0");
  });

  it("selects a tray card then places it in a slot", () => {
    const { onChange } = mount();
    fireEvent.click(screen.getByTestId("quiz-sequence-item-prophase"));
    expect(screen.getByTestId("quiz-sequence-item-prophase")).toHaveAttribute("aria-pressed", "true");
    fireEvent.click(screen.getByRole("button", { name: "Place in position 1" }));
    expect(onChange).toHaveBeenCalledWith("prophase;;");
  });

  it("marks complete when every slot is filled", () => {
    const value = encodeSequenceAnswer(MITOSIS, {
      prophase: 0,
      metaphase: 1,
      anaphase: 2,
    });
    mount({ value });
    expect(screen.getByTestId("quiz-sequence")).toHaveAttribute("data-complete", "true");
    expect(screen.getByTestId("quiz-sequence-tray-empty")).toHaveTextContent("Every step is placed.");
  });

  it("tones placed cards against expected on incorrect verdict", () => {
    const value = encodeSequenceAnswer(MITOSIS, {
      prophase: 1,
      metaphase: 0,
      anaphase: 2,
    });
    const expected = encodeSequenceAnswer(MITOSIS, {
      prophase: 0,
      metaphase: 1,
      anaphase: 2,
    });
    mount({ value, expected, verdict: "incorrect" });
    expect(screen.getByTestId("quiz-sequence-item-prophase").className).toMatch(/--wrong/);
    expect(screen.getByTestId("quiz-sequence-item-anaphase").className).toMatch(/--right/);
  });
});

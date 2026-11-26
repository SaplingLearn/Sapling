// @vitest-environment jsdom
/**
 * W7.2 Build (kit construct): click-to-slot under SessionTop patterns — tray,
 * slots, encode into short_answer text, verdict card tones.
 */

import React from "react";
import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, cleanup, fireEvent } from "@testing-library/react";
import type { BuildInteraction } from "@/lib/quiz/types";
import { encodeBuildAnswer } from "@/lib/quiz/buildInteraction";
import { BuildAnswer } from "./BuildAnswer";

const NUCLEOTIDE: BuildInteraction = {
  kind: "build",
  slots: [
    { id: "head", label: "Head" },
    { id: "sugar", label: "Sugar" },
    { id: "base", label: "Base" },
  ],
  parts: [
    { id: "phosphate", label: "Phosphate" },
    { id: "deoxyribose", label: "Deoxyribose" },
    { id: "adenine", label: "Adenine" },
    { id: "amino", label: "Amino acid" },
  ],
};

afterEach(cleanup);

function mount(over: Partial<React.ComponentProps<typeof BuildAnswer>> = {}) {
  const onChange = over.onChange ?? vi.fn();
  render(
    <BuildAnswer
      interaction={NUCLEOTIDE}
      value=""
      disabled={false}
      onChange={onChange}
      {...over}
    />,
  );
  return { onChange };
}

describe("BuildAnswer", () => {
  it("lists every part in the tray and three slots", () => {
    mount();
    expect(screen.getByTestId("quiz-build")).toHaveAttribute("data-complete", "false");
    expect(screen.getByTestId("quiz-build-tray")).toBeInTheDocument();
    expect(screen.getByTestId("quiz-build-slots")).toBeInTheDocument();
    for (const id of ["phosphate", "deoxyribose", "adenine", "amino"]) {
      expect(screen.getByTestId(`quiz-build-item-${id}`)).toBeInTheDocument();
    }
    expect(screen.getByTestId("quiz-build-slot-head")).toHaveAttribute("data-slot", "head");
    expect(screen.getByTestId("quiz-build-slot-base")).toHaveAttribute("data-slot", "base");
  });

  it("places a selected part onto a slot and encodes answerText", () => {
    const { onChange } = mount();
    fireEvent.click(screen.getByTestId("quiz-build-item-phosphate"));
    expect(screen.getByTestId("quiz-build-item-phosphate")).toHaveAttribute("aria-pressed", "true");
    fireEvent.click(screen.getByRole("button", { name: "Place on Head" }));
    expect(onChange).toHaveBeenCalledWith("head=phosphate;sugar=;base=");
  });

  it("returns a placed part to the tray on click", () => {
    const value = encodeBuildAnswer(NUCLEOTIDE, {
      phosphate: 0,
      deoxyribose: null,
      adenine: null,
      amino: null,
    });
    const { onChange } = mount({ value });
    fireEvent.click(screen.getByTestId("quiz-build-item-phosphate"));
    expect(onChange).toHaveBeenCalledWith("head=;sugar=;base=");
  });

  it("marks complete when every slot is filled (extras may remain)", () => {
    const value = encodeBuildAnswer(NUCLEOTIDE, {
      phosphate: 0,
      deoxyribose: 1,
      adenine: 2,
      amino: null,
    });
    mount({ value });
    expect(screen.getByTestId("quiz-build")).toHaveAttribute("data-complete", "true");
    expect(screen.getByTestId("quiz-build-item-amino")).toBeInTheDocument();
  });

  it("tones cards from the expected encode once a verdict is shown", () => {
    const value = encodeBuildAnswer(NUCLEOTIDE, {
      phosphate: 1,
      deoxyribose: 0,
      adenine: 2,
      amino: null,
    });
    const expected = encodeBuildAnswer(NUCLEOTIDE, {
      phosphate: 0,
      deoxyribose: 1,
      adenine: 2,
      amino: null,
    });
    mount({ value, expected, verdict: "incorrect" });
    expect(screen.getByTestId("quiz-build-item-phosphate").className).toMatch(/--wrong/);
    expect(screen.getByTestId("quiz-build-item-deoxyribose").className).toMatch(/--wrong/);
    expect(screen.getByTestId("quiz-build-item-adenine").className).toMatch(/--right/);
    expect(screen.queryByTestId("quiz-build-tray")).not.toBeInTheDocument();
  });
});

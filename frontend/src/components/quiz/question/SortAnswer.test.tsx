// @vitest-environment jsdom
/**
 * W7.2 Sort (kit 7.1): click-to-bucket under SessionTop patterns — tray,
 * buckets, encode into short_answer text, verdict card tones.
 */

import React from "react";
import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, cleanup, fireEvent } from "@testing-library/react";
import type { SortInteraction } from "@/lib/quiz/types";
import { encodeSortAnswer } from "@/lib/quiz/sortInteraction";
import { SortAnswer } from "./SortAnswer";

const CELL: SortInteraction = {
  kind: "sort",
  buckets: ["Prokaryote", "Eukaryote"],
  items: [
    { id: "e-coli", label: "E. coli" },
    { id: "yeast", label: "Yeast" },
    { id: "strep", label: "Streptococcus" },
  ],
};

afterEach(cleanup);

function mount(over: Partial<React.ComponentProps<typeof SortAnswer>> = {}) {
  const onChange = over.onChange ?? vi.fn();
  render(
    <SortAnswer
      interaction={CELL}
      value=""
      disabled={false}
      onChange={onChange}
      {...over}
    />,
  );
  return { onChange };
}

describe("SortAnswer", () => {
  it("lists every item in the tray and two buckets", () => {
    mount();
    expect(screen.getByTestId("quiz-sort")).toHaveAttribute("data-complete", "false");
    expect(screen.getByTestId("quiz-sort-tray")).toBeInTheDocument();
    expect(screen.getByTestId("quiz-sort-buckets")).toBeInTheDocument();
    for (const id of ["e-coli", "yeast", "strep"]) {
      expect(screen.getByTestId(`quiz-sort-item-${id}`)).toBeInTheDocument();
    }
    expect(screen.getByTestId("quiz-sort-bucket-0")).toHaveAttribute("data-bucket", "Prokaryote");
    expect(screen.getByTestId("quiz-sort-bucket-1")).toHaveAttribute("data-bucket", "Eukaryote");
  });

  it("places a selected item into a bucket and encodes answerText", () => {
    const { onChange } = mount();
    fireEvent.click(screen.getByTestId("quiz-sort-item-e-coli"));
    expect(screen.getByTestId("quiz-sort-item-e-coli")).toHaveAttribute("aria-pressed", "true");
    fireEvent.click(screen.getByRole("button", { name: "Place in Prokaryote" }));
    expect(onChange).toHaveBeenCalledWith("Prokaryote=e-coli;Eukaryote=");
  });

  it("returns a placed item to the tray on click", () => {
    const value = encodeSortAnswer(CELL, { "e-coli": 0, yeast: null, strep: null });
    const { onChange } = mount({ value });
    fireEvent.click(screen.getByTestId("quiz-sort-item-e-coli"));
    expect(onChange).toHaveBeenCalledWith("Prokaryote=;Eukaryote=");
  });

  it("marks complete only when every item is placed", () => {
    const value = encodeSortAnswer(CELL, { "e-coli": 0, yeast: 1, strep: 0 });
    mount({ value });
    expect(screen.getByTestId("quiz-sort")).toHaveAttribute("data-complete", "true");
    expect(screen.getByTestId("quiz-sort-tray-empty")).toHaveTextContent("Every item is sorted.");
  });

  it("tones cards from the expected encode once a verdict is shown", () => {
    const value = encodeSortAnswer(CELL, { "e-coli": 0, yeast: 0, strep: 1 });
    const expected = encodeSortAnswer(CELL, { "e-coli": 0, yeast: 1, strep: 0 });
    mount({ value, expected, verdict: "incorrect" });
    expect(screen.getByTestId("quiz-sort-item-e-coli").className).toMatch(/--right/);
    expect(screen.getByTestId("quiz-sort-item-yeast").className).toMatch(/--wrong/);
    expect(screen.queryByTestId("quiz-sort-tray")).not.toBeInTheDocument();
  });
});

// @vitest-environment jsdom
/**
 * W7.2 Label (kit 7.4): click-to-spot under SessionTop patterns — tray,
 * spots, encode into short_answer text, verdict card tones.
 */

import React from "react";
import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, cleanup, fireEvent } from "@testing-library/react";
import type { LabelInteraction } from "@/lib/quiz/types";
import { encodeLabelAnswer } from "@/lib/quiz/labelInteraction";
import { LabelAnswer } from "./LabelAnswer";

const HEART: LabelInteraction = {
  kind: "label",
  spots: [
    { id: "1", label: "1" },
    { id: "2", label: "2" },
    { id: "3", label: "3" },
    { id: "4", label: "4" },
  ],
  labels: [
    { id: "aorta", label: "Aorta" },
    { id: "pa", label: "Pulmonary artery" },
    { id: "ra", label: "Right atrium" },
    { id: "lv", label: "Left ventricle" },
  ],
};

afterEach(cleanup);

function mount(over: Partial<React.ComponentProps<typeof LabelAnswer>> = {}) {
  const onChange = over.onChange ?? vi.fn();
  render(
    <LabelAnswer
      interaction={HEART}
      value=""
      disabled={false}
      onChange={onChange}
      {...over}
    />,
  );
  return { onChange };
}

describe("LabelAnswer", () => {
  it("lists every label in the tray and four spots", () => {
    mount();
    expect(screen.getByTestId("quiz-label")).toHaveAttribute("data-complete", "false");
    expect(screen.getByTestId("quiz-label-tray")).toBeInTheDocument();
    expect(screen.getByTestId("quiz-label-spots")).toBeInTheDocument();
    for (const id of ["aorta", "pa", "ra", "lv"]) {
      expect(screen.getByTestId(`quiz-label-item-${id}`)).toBeInTheDocument();
    }
    expect(screen.getByTestId("quiz-label-spot-1")).toHaveAttribute("data-spot", "1");
    expect(screen.getByTestId("quiz-label-spot-4")).toHaveAttribute("data-spot", "4");
  });

  it("places a selected label onto a spot and encodes answerText", () => {
    const { onChange } = mount();
    fireEvent.click(screen.getByTestId("quiz-label-item-aorta"));
    expect(screen.getByTestId("quiz-label-item-aorta")).toHaveAttribute("aria-pressed", "true");
    fireEvent.click(screen.getByRole("button", { name: "Place on 1" }));
    expect(onChange).toHaveBeenCalledWith("1=aorta;2=;3=;4=");
  });

  it("returns a placed label to the tray on click", () => {
    const value = encodeLabelAnswer(HEART, { aorta: 0, pa: null, ra: null, lv: null });
    const { onChange } = mount({ value });
    fireEvent.click(screen.getByTestId("quiz-label-item-aorta"));
    expect(onChange).toHaveBeenCalledWith("1=;2=;3=;4=");
  });

  it("marks complete only when every label is placed", () => {
    const value = encodeLabelAnswer(HEART, { aorta: 0, pa: 1, ra: 2, lv: 3 });
    mount({ value });
    expect(screen.getByTestId("quiz-label")).toHaveAttribute("data-complete", "true");
    expect(screen.getByTestId("quiz-label-tray-empty")).toHaveTextContent("Every label is placed.");
  });

  it("tones cards from the expected encode once a verdict is shown", () => {
    const value = encodeLabelAnswer(HEART, { aorta: 1, pa: 0, ra: 2, lv: 3 });
    const expected = encodeLabelAnswer(HEART, { aorta: 0, pa: 1, ra: 2, lv: 3 });
    mount({ value, expected, verdict: "incorrect" });
    expect(screen.getByTestId("quiz-label-item-aorta").className).toMatch(/--wrong/);
    expect(screen.getByTestId("quiz-label-item-pa").className).toMatch(/--wrong/);
    expect(screen.getByTestId("quiz-label-item-ra").className).toMatch(/--right/);
    expect(screen.queryByTestId("quiz-label-tray")).not.toBeInTheDocument();
  });
});

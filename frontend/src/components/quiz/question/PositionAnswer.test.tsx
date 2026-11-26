// @vitest-environment jsdom
import React from "react";
import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, cleanup, fireEvent } from "@testing-library/react";
import type { PositionInteraction } from "@/lib/quiz/types";
import { PositionAnswer } from "./PositionAnswer";

const PH: PositionInteraction = {
  kind: "position",
  axisLabel: "pH scale",
  markers: [
    { id: "lemon", label: "Lemon juice" },
    { id: "water", label: "Pure water" },
  ],
  stops: [
    { id: "2", label: "2" },
    { id: "7", label: "7" },
  ],
};

afterEach(cleanup);

describe("PositionAnswer", () => {
  it("places a marker on a stop", () => {
    const onChange = vi.fn();
    render(
      <PositionAnswer interaction={PH} value="" disabled={false} onChange={onChange} />,
    );
    expect(screen.getByTestId("quiz-position")).toHaveAttribute("data-complete", "false");
    fireEvent.click(screen.getByTestId("quiz-position-item-lemon"));
    fireEvent.click(screen.getByTestId("quiz-position-stop-2").querySelector("button")!);
    expect(onChange).toHaveBeenCalledWith("lemon=2;water=");
  });
});

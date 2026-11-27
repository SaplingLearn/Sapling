// @vitest-environment jsdom
import React from "react";
import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, cleanup, fireEvent } from "@testing-library/react";
import type { RankInteraction } from "@/lib/quiz/types";
import { RankAnswer } from "./RankAnswer";

const DX: RankInteraction = {
  kind: "rank",
  hint: "Most likely at the top.",
  items: [
    { id: "mi", label: "MI" },
    { id: "gerd", label: "GERD" },
  ],
};

afterEach(cleanup);

describe("RankAnswer", () => {
  it("ranks an item and accepts a why", () => {
    const onChange = vi.fn();
    render(
      <RankAnswer interaction={DX} value="" disabled={false} onChange={onChange} />,
    );
    expect(screen.getByTestId("quiz-rank")).toHaveAttribute("data-complete", "false");
    fireEvent.click(screen.getByTestId("quiz-rank-item-mi"));
    fireEvent.click(screen.getByTestId("quiz-rank-slot-0").querySelector("button")!);
    expect(onChange).toHaveBeenCalledWith("mi;");
    fireEvent.change(screen.getByTestId("quiz-rank-why"), {
      target: { value: "Radiating pain." },
    });
    expect(onChange).toHaveBeenCalled();
  });
});

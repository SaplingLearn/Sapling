// @vitest-environment jsdom
import React from "react";
import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, cleanup, fireEvent } from "@testing-library/react";
import type { ConnectInteraction } from "@/lib/quiz/types";
import { ConnectAnswer } from "./ConnectAnswer";

const DRUGS: ConnectInteraction = {
  kind: "connect",
  note: "Match each drug.",
  left: [
    { id: "aspirin", label: "Aspirin" },
    { id: "penicillin", label: "Penicillin" },
  ],
  right: [
    { id: "cox", label: "Inhibits COX enzymes" },
    { id: "wall", label: "Inhibits cell wall" },
  ],
};

afterEach(cleanup);

const MAP: ConnectInteraction = {
  kind: "connect",
  mode: "map",
  left: [],
  right: [],
  nodes: [
    { id: "deriv", label: "Derivative" },
    { id: "limit", label: "Limit" },
    { id: "slope", label: "Slope" },
  ],
};

describe("ConnectAnswer", () => {
  it("pairs left to right", () => {
    const onChange = vi.fn();
    render(
      <ConnectAnswer interaction={DRUGS} value="" disabled={false} onChange={onChange} />,
    );
    expect(screen.getByTestId("quiz-connect")).toHaveAttribute("data-mode", "match");
    expect(screen.getByTestId("quiz-connect")).toHaveAttribute("data-complete", "false");
    fireEvent.click(screen.getByTestId("quiz-connect-left-aspirin"));
    fireEvent.click(screen.getByTestId("quiz-connect-right-cox"));
    expect(onChange).toHaveBeenCalledWith("aspirin=cox;penicillin=");
  });

  it("links concept-map nodes", () => {
    const onChange = vi.fn();
    render(
      <ConnectAnswer interaction={MAP} value="" disabled={false} onChange={onChange} />,
    );
    expect(screen.getByTestId("quiz-connect")).toHaveAttribute("data-mode", "map");
    fireEvent.click(screen.getByTestId("quiz-connect-node-deriv"));
    fireEvent.click(screen.getByTestId("quiz-connect-node-limit"));
    expect(onChange).toHaveBeenCalledWith("deriv=limit");
  });
});

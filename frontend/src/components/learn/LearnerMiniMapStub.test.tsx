// @vitest-environment jsdom
/**
 * W3.5a: learner mini-map is client state only — connect / remove / clear,
 * never a network call.
 */
import React from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import {
  LearnerMiniMapStub,
  takeMiniMapConcepts,
} from "./LearnerMiniMapStub";

const THREE = [
  { id: "n1", label: "Derivatives" },
  { id: "n2", label: "Integrals" },
  { id: "n3", label: "Limits" },
];

afterEach(() => cleanup());

describe("LearnerMiniMapStub", () => {
  it("hides with fewer than two concepts", () => {
    const { container } = render(
      <LearnerMiniMapStub concepts={[{ id: "n1", label: "Only one" }]} />,
    );
    expect(container).toBeEmptyDOMElement();
  });

  it("caps chips at three", () => {
    expect(takeMiniMapConcepts([...THREE, { id: "n4", label: "Extra" }])).toHaveLength(3);
  });

  it("connects two chips into a local edge and can remove it", async () => {
    const user = userEvent.setup();
    const fetchSpy = vi.spyOn(globalThis, "fetch");
    render(<LearnerMiniMapStub concepts={THREE} />);

    expect(screen.getByTestId("loop-close-minimap")).toBeInTheDocument();
    await user.click(screen.getByTestId("loop-close-minimap-chip-n1"));
    await user.click(screen.getByTestId("loop-close-minimap-chip-n2"));

    const edge = screen.getByTestId("loop-close-minimap-edge-n1|n2");
    expect(edge).toHaveTextContent("Derivatives");
    expect(edge).toHaveTextContent("Integrals");
    expect(fetchSpy).not.toHaveBeenCalled();

    await user.click(screen.getByTestId("loop-close-minimap-remove-n1|n2"));
    expect(screen.queryByTestId("loop-close-minimap-edge-n1|n2")).not.toBeInTheDocument();
    expect(fetchSpy).not.toHaveBeenCalled();
    fetchSpy.mockRestore();
  });

  it("clear drops every local edge", async () => {
    const user = userEvent.setup();
    render(<LearnerMiniMapStub concepts={THREE} />);
    await user.click(screen.getByTestId("loop-close-minimap-chip-n1"));
    await user.click(screen.getByTestId("loop-close-minimap-chip-n3"));
    expect(screen.getByTestId("loop-close-minimap-edge-n1|n3")).toBeInTheDocument();
    await user.click(screen.getByTestId("loop-close-minimap-clear"));
    expect(screen.queryByTestId("loop-close-minimap-edge-n1|n3")).not.toBeInTheDocument();
    expect(screen.getByTestId("loop-close-minimap-edges")).toHaveTextContent("No links yet");
  });
});

// @vitest-environment jsdom
/**
 * `initialZoom`: the zoom a graph opens and resets at, centred on the window.
 * Quiz home's live neighbourhood uses it so a small fragment fills its frame;
 * every other caller keeps the default, the identity view.
 */

import { afterEach, describe, expect, it } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import React from "react";
import type { GraphEdge, GraphNode } from "@/lib/data";
import { KnowledgeGraph2D } from "./KnowledgeGraph2D";

afterEach(cleanup);

const NODES: GraphNode[] = [
  { id: "a", name: "Limits", subject: "Math", color: "#7a874f", mastery_tier: "learning", mastery_score: 0.4, course_id: "c1" },
  { id: "b", name: "Derivatives", subject: "Math", color: "#7a874f", mastery_tier: "struggling", mastery_score: 0.2, course_id: "c1" },
];
const EDGES: GraphEdge[] = [{ source: "a", target: "b", strength: 0.6 }];

/** The pan/zoom group's transform — the only `<g>` carrying a scale. */
const viewTransform = (container: HTMLElement) =>
  Array.from(container.querySelectorAll("g"))
    .map(g => g.getAttribute("transform") ?? "")
    .find(t => t.includes("scale("));

describe("KnowledgeGraph2D — initialZoom", () => {
  it("defaults to the identity view", () => {
    const { container } = render(<KnowledgeGraph2D nodes={NODES} edges={EDGES} width={400} height={300} />);
    expect(viewTransform(container)).toBe("translate(0, 0) scale(1)");
  });

  it("opens zoomed and centred on the window", () => {
    const { container } = render(
      <KnowledgeGraph2D nodes={NODES} edges={EDGES} width={400} height={300} initialZoom={2} />,
    );
    // Centred: the window's midpoint (200, 150) stays where it was.
    expect(viewTransform(container)).toBe("translate(-200, -150) scale(2)");
  });

  it("resets to the opening zoom, not to 1", () => {
    const { container } = render(
      <KnowledgeGraph2D nodes={NODES} edges={EDGES} width={400} height={300} initialZoom={2} />,
    );
    fireEvent.click(screen.getByTestId("graph-zoom-out"));
    expect(viewTransform(container)).not.toBe("translate(-200, -150) scale(2)");
    fireEvent.click(screen.getByTestId("graph-zoom-reset"));
    expect(viewTransform(container)).toBe("translate(-200, -150) scale(2)");
  });

  it("re-centres when the window is measured to a new size", () => {
    const view = render(
      <KnowledgeGraph2D nodes={NODES} edges={EDGES} width={400} height={300} initialZoom={2} />,
    );
    view.rerender(<KnowledgeGraph2D nodes={NODES} edges={EDGES} width={600} height={340} initialZoom={2} />);
    expect(viewTransform(view.container)).toBe("translate(-300, -170) scale(2)");
  });
});

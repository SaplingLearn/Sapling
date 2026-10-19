// @vitest-environment jsdom
/**
 * The `sapling` appearance (Dashboard redesign, prompt 07):
 *  - every concept is filled with its SERVER tier's source-palette colour
 *    (A3B06D / FCC98A / EF908F / DECDC1) and hubs with brown 6C462F, so the
 *    four-state legend beside the map describes the marks truthfully;
 *  - `selectedId` draws a visible ring and the node's name;
 *  - `interactive={false}` (the phone preview) takes no gestures: no zoom
 *    controls, page touch scrolling over the SVG, and a tap selects nothing;
 *  - the FA26 appearance /tree uses is unchanged.
 */
import React from "react";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import type { GraphNode } from "@/lib/data";

vi.stubEnv("NEXT_PUBLIC_TEST_MODE", "1");
let KnowledgeGraph2D: (typeof import("./KnowledgeGraph2D"))["KnowledgeGraph2D"];
beforeAll(async () => {
  ({ KnowledgeGraph2D } = await import("./KnowledgeGraph2D"));
});
afterEach(cleanup);

const NODES: GraphNode[] = [
  { id: "root", name: "CS101 - Intro", subject: "CS", color: "#7a874f", is_subject_root: true, mastery_tier: "mastered", mastery_score: 0, course_id: "c1" },
  { id: "m", name: "Loops", subject: "CS", color: "#7a874f", mastery_tier: "mastered", mastery_score: 0.97, course_id: "c1" },
  { id: "l", name: "Recursion and its many uses", subject: "CS", color: "#7a874f", mastery_tier: "learning", mastery_score: 0.4, course_id: "c1" },
  { id: "s", name: "Pointers", subject: "CS", color: "#7a874f", mastery_tier: "struggling", mastery_score: 0.2, course_id: "c1" },
  { id: "u", name: "Graphs", subject: "CS", color: "#7a874f", mastery_tier: "unexplored", mastery_score: 0, course_id: "c1" },
];
const EDGES = [{ source: "root", target: "m", strength: 0.7 }];

const circleFill = (id: string) =>
  document.querySelector(`[data-testid="graph-node"][data-node-id="${id}"] [data-testid="graph-node-circle"]`)?.getAttribute("fill");

describe("KnowledgeGraph2D sapling appearance", () => {
  it("paints by server tier in the source palette, hubs brown", () => {
    render(<KnowledgeGraph2D appearance="sapling" nodes={NODES} edges={EDGES} width={600} height={400} />);
    expect(circleFill("root")).toBe("#6C462F");
    expect(circleFill("m")).toBe("#A3B06D");
    expect(circleFill("l")).toBe("#FCC98A");
    expect(circleFill("s")).toBe("#EF908F");
    expect(circleFill("u")).toBe("#DECDC1");
  });

  it("FA26 (/tree) keeps its own values", () => {
    render(<KnowledgeGraph2D appearance="fa26" nodes={NODES} edges={EDGES} width={600} height={400} />);
    expect(circleFill("m")).toBe("#a1b06d");
    expect(circleFill("root")).toBe("#7c614e");
  });

  it("marks the selected node with a ring and its (longer) name", () => {
    render(<KnowledgeGraph2D appearance="sapling" nodes={NODES} edges={EDGES} width={600} height={400} selectedId="l" />);
    const g = document.querySelector('[data-testid="graph-node"][data-node-id="l"]')!;
    expect(g.getAttribute("data-selected")).toBe("true");
    expect(g.querySelector('[data-testid="graph-node-selected-ring"]')).not.toBeNull();
    expect(g.querySelector(":scope > text")?.textContent).toBe("Recursion and its many uses");
    expect(document.querySelectorAll('[data-testid="graph-node-selected-ring"]')).toHaveLength(1);
  });

  it("interactive: named 44px zoom controls and node activation", () => {
    const onNodeClick = vi.fn();
    render(<KnowledgeGraph2D appearance="sapling" nodes={NODES} edges={EDGES} width={600} height={400} onNodeClick={onNodeClick} />);
    expect(screen.getByRole("button", { name: "Zoom in" })).toHaveStyle({ minWidth: "44px", minHeight: "44px" });
    expect(screen.getByRole("button", { name: "Reset view" })).toBeInTheDocument();
    fireEvent.click(document.querySelector('[data-testid="graph-node"][data-node-id="s"]')!);
    expect(onNodeClick).toHaveBeenCalledWith(expect.objectContaining({ id: "s" }));
  });

  it("static preview: no controls, page touch scrolling, taps select nothing", () => {
    const onNodeClick = vi.fn();
    render(
      <KnowledgeGraph2D appearance="sapling" nodes={NODES} edges={EDGES} width={320} height={260} interactive={false} onNodeClick={onNodeClick} />,
    );
    expect(screen.queryByTestId("graph-zoom-in")).toBeNull();
    expect(screen.getByRole("img", { name: "Knowledge graph" })).toHaveStyle({ touchAction: "pan-y" });
    fireEvent.click(document.querySelector('[data-testid="graph-node"][data-node-id="s"]')!);
    expect(onNodeClick).not.toHaveBeenCalled();
  });
});

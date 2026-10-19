// @vitest-environment jsdom
import React from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import type { GraphNode } from "@/lib/data";
import { PEN_NATIVE_GRAPH_REFERENCE } from "@/lib/graph/penNativeGraphSource";
import { PenKnowledgeGraph2D } from "./PenKnowledgeGraph2D";
import { PenGraphReference } from "./PenGraphReference";

afterEach(cleanup);
const node = (id: string, course: string, root = false): GraphNode => ({ id, course_id: course, name: root ? course : "Shared concept", subject: course, color: "#000000", is_subject_root: root, mastery_tier: "learning", mastery_score: 0.3 });
const nodes = [node("course-a", "CS 101", true), node("concept-a", "CS 101"), node("course-b", "CS 102", true), node("concept-b", "CS 102")];
const edges = [{ source: "course-a", target: "concept-a", strength: 0.8 }, { source: "concept-a", target: "concept-b", strength: 0.4 }];
const positions = () => Object.fromEntries(screen.getAllByTestId("graph-node").map(mark => [mark.getAttribute("data-node-id"), mark.getAttribute("transform")]));

describe("authored Pen graph", () => {
  it("renders every real ID and relationship as an authored path, including same-name concepts", () => {
    render(<PenKnowledgeGraph2D nodes={nodes} edges={edges} />);
    expect(screen.getByRole("img", { name: "Knowledge graph" })).toHaveAttribute("data-renderer", "pen");
    expect(screen.getAllByTestId("graph-node")).toHaveLength(nodes.length);
    expect(screen.getAllByTestId("graph-node-item")).toHaveLength(nodes.length);
    const branches = screen.getAllByTestId("graph-edge");
    expect(branches).toHaveLength(edges.length);
    expect(branches[0].tagName).toBe("path");
    expect(branches.map(branch => [branch.getAttribute("data-source"), branch.getAttribute("data-target")])).toEqual(expect.arrayContaining(edges.map(edge => [edge.source, edge.target])));
    for (const mark of screen.getAllByTestId("graph-node-circle")) {
      expect(mark.tagName).toBe("path");
      expect(mark).toHaveAttribute("opacity", "1");
    }
  });

  it("keeps the authored branch width at seven graph units under long-edge projection", () => {
    render(<PenKnowledgeGraph2D nodes={nodes} edges={edges} width={893} height={601} />);
    const branch = screen.getAllByTestId("graph-edge").find(value => value.getAttribute("data-source") === "concept-a")!;
    const matrix = branch.parentElement!.getAttribute("transform")!.match(/matrix\(([^)]+)\)/)![1].split(" ").map(Number);
    const projection = Math.hypot(matrix[0], matrix[1]);
    expect(projection).toBeGreaterThan(1.5); // A real long cross-course relationship.
    expect(Number(branch.getAttribute("stroke-width")) * projection).toBeCloseTo(7, 4);
    expect(branch).not.toHaveAttribute("vector-effect"); // Responsive zoom still scales the source width.
  });

  it("keeps geometry stable when API order or knowledge estimates refresh", () => {
    const view = render(<PenKnowledgeGraph2D nodes={nodes} edges={edges} />);
    const original = positions();
    view.rerender(<PenKnowledgeGraph2D nodes={[...nodes].reverse().map(value => ({ ...value, mastery_score: 0.98, mastery_tier: "mastered" }))} edges={[...edges].reverse()} />);
    expect(positions()).toEqual(original);
    expect(screen.getAllByTestId("graph-node-circle").filter(mark => mark.getAttribute("fill") === "#A3B06D")).toHaveLength(2);
  });

  it("activates the exact real ID by Enter, Space and the textual list", () => {
    const select = vi.fn();
    render(<PenKnowledgeGraph2D nodes={nodes} edges={edges} onNodeClick={select} />);
    const marks = screen.getAllByTestId("graph-node");
    fireEvent.keyDown(marks.find(mark => mark.getAttribute("data-node-id") === "concept-b")!, { key: "Enter" });
    fireEvent.keyDown(marks.find(mark => mark.getAttribute("data-node-id") === "concept-a")!, { key: " " });
    fireEvent.click(screen.getAllByTestId("graph-node-activate")[2]);
    expect(select.mock.calls.map(([value]) => value.id)).toEqual(["concept-b", "concept-a", "course-b"]);
  });

  it("zooms, fits and resets without selecting or changing graph input", () => {
    const select = vi.fn();
    const untouched = JSON.stringify({ nodes, edges });
    render(<PenKnowledgeGraph2D nodes={nodes} edges={edges} onNodeClick={select} />);
    const original = screen.getByTestId("graph-transform").getAttribute("transform");
    fireEvent.click(screen.getByRole("button", { name: "Zoom in" }));
    expect(screen.getByTestId("graph-transform").getAttribute("transform")).not.toBe(original);
    fireEvent.click(screen.getByRole("button", { name: "Fit graph" }));
    expect(screen.getByTestId("graph-transform")).toHaveAttribute("transform", original);
    fireEvent.click(screen.getByRole("button", { name: "Zoom out" }));
    fireEvent.click(screen.getByRole("button", { name: "Reset view" }));
    expect(screen.getByTestId("graph-transform")).toHaveAttribute("transform", original);
    expect(select).not.toHaveBeenCalled();
    expect(JSON.stringify({ nodes, edges })).toBe(untouched);
  });

  it("consumes wheel gestures only during exploration, keeping phone page scrolling intact", () => {
    const view = render(<PenKnowledgeGraph2D nodes={nodes} edges={edges} />);
    const svg = screen.getByRole("img", { name: "Knowledge graph" });
    const original = screen.getByTestId("graph-transform").getAttribute("transform");
    const exploreWheel = new WheelEvent("wheel", { deltaY: -100, clientX: 100, clientY: 100, bubbles: true, cancelable: true });
    fireEvent(svg, exploreWheel);
    expect(exploreWheel.defaultPrevented).toBe(true);
    expect(screen.getByTestId("graph-transform").getAttribute("transform")).not.toBe(original);
    view.rerender(<PenKnowledgeGraph2D nodes={nodes} edges={edges} interactive={false} />);
    const phoneWheel = new WheelEvent("wheel", { deltaY: 100, bubbles: true, cancelable: true });
    fireEvent(svg, phoneWheel);
    expect(phoneWheel.defaultPrevented).toBe(false);
  });

  it("captures a node gesture on that node and releases the same holder", () => {
    render(<PenKnowledgeGraph2D nodes={nodes} edges={edges} />);
    const mark = screen.getAllByTestId("graph-node")[1];
    const svg = screen.getByRole("img", { name: "Knowledge graph" });
    const nodeCapture = vi.fn(), nodeRelease = vi.fn(), canvasCapture = vi.fn();
    Object.defineProperty(mark, "setPointerCapture", { value: nodeCapture });
    Object.defineProperty(mark, "releasePointerCapture", { value: nodeRelease });
    Object.defineProperty(svg, "setPointerCapture", { value: canvasCapture });
    fireEvent.pointerDown(mark, { pointerId: 4, button: 0, clientX: 100, clientY: 100 });
    fireEvent.pointerUp(svg, { pointerId: 4, clientX: 100, clientY: 100 });
    expect(nodeCapture).toHaveBeenCalledWith(4);
    expect(nodeRelease).toHaveBeenCalledWith(4);
    expect(canvasCapture).not.toHaveBeenCalled();
  });

  it("bounds node dragging and updates its actual relationship without activating it", () => {
    const select = vi.fn();
    render(<PenKnowledgeGraph2D nodes={nodes} edges={edges} onNodeClick={select} width={893} height={601} />);
    const mark = screen.getAllByTestId("graph-node").find(value => value.getAttribute("data-node-id") === "concept-a")!;
    const original = mark.getAttribute("transform");
    const branch = screen.getAllByTestId("graph-edge").find(value => value.getAttribute("data-target") === "concept-a")!;
    const originalBranch = branch.parentElement!.getAttribute("transform");
    const svg = screen.getByRole("img", { name: "Knowledge graph" });
    fireEvent.pointerDown(mark, { pointerId: 1, button: 0, clientX: 200, clientY: 200 });
    fireEvent.pointerMove(svg, { pointerId: 1, clientX: 240, clientY: 240 });
    fireEvent.pointerUp(svg, { pointerId: 1, clientX: 240, clientY: 240 });
    fireEvent.click(mark);
    expect(mark.getAttribute("transform")).not.toBe(original);
    expect(branch.parentElement!.getAttribute("transform")).not.toBe(originalBranch);
    expect(select).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Reset view" }));
    expect(mark).toHaveAttribute("transform", original);
  });

  it("preserves comparison evidence and uses instance-local gradient IDs", () => {
    render(<><PenKnowledgeGraph2D nodes={nodes} edges={edges} comparison={[{ name: "Shared concept", mastery_score: 0.7 }]} comparisonLabel="Study partner" /><PenKnowledgeGraph2D nodes={nodes} edges={edges} /></>);
    expect(screen.getAllByTestId("graph-comparison-ring")).toHaveLength(2);
    for (const ring of screen.getAllByTestId("graph-comparison-ring")) expect(ring.querySelector("title")).toHaveTextContent("Study partner: 70% mastery on Shared concept");
    const ids = Array.from(document.querySelectorAll("linearGradient")).map(value => value.id);
    expect(new Set(ids).size).toBe(ids.length);
  });

  it("the phone overview keeps page gestures and takes no pointer, keyboard or wheel actions", () => {
    const select = vi.fn();
    render(<PenKnowledgeGraph2D nodes={nodes} edges={edges} width={320} height={260} interactive={false} onNodeClick={select} />);
    const svg = screen.getByRole("img", { name: "Knowledge graph" });
    const original = screen.getByTestId("graph-transform").getAttribute("transform");
    expect(svg).toHaveStyle({ touchAction: "pan-y" });
    expect(screen.queryByTestId("graph-zoom-in")).not.toBeInTheDocument();
    expect(screen.queryByTestId("graph-node-activate")).not.toBeInTheDocument();
    fireEvent.click(screen.getAllByTestId("graph-node")[1]);
    fireEvent.keyDown(screen.getAllByTestId("graph-node")[1], { key: "Enter" });
    fireEvent.wheel(svg, { deltaY: -100 });
    expect(select).not.toHaveBeenCalled();
    expect(screen.getByTestId("graph-transform")).toHaveAttribute("transform", original);
  });
});

describe("exact Pen reference fixture", () => {
  it("retains all ordered paths, source paints, 21 gradients and filtered source group", () => {
    render(<PenGraphReference />);
    const svg = screen.getByTestId("pen-graph-reference");
    const paths = svg.querySelectorAll("path");
    expect(paths).toHaveLength(74);
    expect(svg.querySelectorAll("linearGradient")).toHaveLength(21);
    expect(svg).toHaveAttribute("viewBox", "0 0 893 601");
    PEN_NATIVE_GRAPH_REFERENCE.paths.forEach((source, index) => {
      expect(paths[index]).toHaveAttribute("d", source.d);
      expect(paths[index]).toHaveAttribute("data-source-node", source.sourceId);
      expect(paths[index]).toHaveAttribute("transform", source.transform);
    });
    const gradients = svg.querySelectorAll("linearGradient");
    PEN_NATIVE_GRAPH_REFERENCE.gradients.forEach((source, index) => {
      expect(gradients[index]).toHaveAttribute("gradientTransform", source.transform);
      expect(gradients[index]).toHaveAttribute("x1", String(source.x1));
      expect(gradients[index]).toHaveAttribute("y1", String(source.y1));
      expect(gradients[index]).toHaveAttribute("x2", String(source.x2));
      expect(gradients[index]).toHaveAttribute("y2", String(source.y2));
      source.stops.forEach((stop, stopIndex) => {
        expect(gradients[index].children[stopIndex]).toHaveAttribute("stop-opacity", String(stop.opacity));
        expect(gradients[index].children[stopIndex]).toHaveAttribute("stop-color", stop.color);
      });
    });
    expect(svg.querySelectorAll("g[filter] > path")).toHaveLength(1);
    expect(svg.querySelectorAll("image,text")).toHaveLength(0);
  });
});

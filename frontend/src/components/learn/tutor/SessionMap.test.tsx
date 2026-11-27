// @vitest-environment jsdom
/**
 * The session panel's map (PR #866 U4): drawn in mastery colours whatever the
 * Tree's toggle is set to (its key, under it, is the mastery key), framed so
 * every concept and caption is inside the panel, and with nothing drawn over
 * its nodes — no colour toggle (KnowledgeGraph draws none for a fixed mode),
 * no zoom stack. It renders once the panel's width is measured. It draws the
 * course's concepts only: the course root (flat course size, hub brown, no
 * entry in the key) is left out with its links, and with no concept there is
 * no map at all.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, render, screen } from "@testing-library/react";
import React from "react";
import type { GraphEdge, GraphNode } from "@/lib/data";

const seen = vi.hoisted(() => ({ props: [] as Record<string, unknown>[] }));
vi.mock("../../graph/KnowledgeGraph", () => ({
  KnowledgeGraph: (props: Record<string, unknown>) => {
    seen.props.push(props);
    return <div data-testid="kg" />;
  },
}));

import { SessionMap, sessionMapGraph } from "./SessionMap";

const node = (id: string, root = false): GraphNode =>
  ({
    id,
    name: id,
    subject: "Intro CS",
    course_id: "c1",
    mastery_score: 0,
    mastery_tier: root ? "subject_root" : "unexplored",
    is_subject_root: root,
  }) as unknown as GraphNode;
const edge = (source: string, target: string): GraphEdge => ({ source, target, strength: 0.7 }) as unknown as GraphEdge;

const ROOT = node("root-c1", true);
const CONCEPTS = [node("a"), node("b")];
const NODES = [ROOT, ...CONCEPTS];
const EDGES = [edge("root-c1", "a"), edge("root-c1", "b"), edge("a", "b")];

let observed: ((width: number) => void) | null = null;

beforeEach(() => {
  seen.props = [];
  observed = null;
  vi.stubGlobal(
    "ResizeObserver",
    class {
      constructor(private cb: (entries: { contentRect: { width: number } }[]) => void) {}
      observe() {
        observed = (width) => this.cb([{ contentRect: { width } }]);
      }
      disconnect() {}
    },
  );
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("SessionMap", () => {
  it("waits for the panel's width, then draws a fitted mastery map with no controls over it", () => {
    render(<SessionMap nodes={CONCEPTS} edges={[]} highlightId="n1" />);
    expect(screen.queryByTestId("kg")).toBeNull();
    act(() => observed!(264));
    expect(screen.getByTestId("kg")).toBeTruthy();
    expect(seen.props.at(-1)).toMatchObject({
      width: 264,
      height: 240,
      highlightId: "n1",
      colorMode: "mastery",
      fit: true,
      zoomControls: false,
      wheelZoom: "pinch",
    });
  });

  it("forwards practicedNodeIds as practicedIds (W3.2 covered outline)", () => {
    const practiced = new Set(["a", "b"]);
    render(<SessionMap nodes={CONCEPTS} edges={[]} highlightId="a" practicedNodeIds={practiced} />);
    act(() => observed!(264));
    expect(seen.props.at(-1)).toMatchObject({
      highlightId: "a",
      practicedIds: practiced,
    });
  });

  it("leaves out the course root and every link that touches it", () => {
    render(<SessionMap nodes={NODES} edges={EDGES} />);
    act(() => observed!(264));
    const drawn = seen.props.at(-1) as { nodes: GraphNode[]; edges: GraphEdge[] };
    expect(drawn.nodes.map((n) => n.id)).toEqual(["a", "b"]);
    expect(drawn.nodes.some((n) => n.is_subject_root)).toBe(false);
    expect(drawn.edges).toEqual([edge("a", "b")]);
  });

  it("renders no map when the course has no concept (its root alone, or nothing)", () => {
    for (const nodes of [[ROOT], []]) {
      const { container, unmount } = render(<SessionMap nodes={nodes} edges={[]} />);
      expect(container).toBeEmptyDOMElement();
      expect(screen.queryByTestId("tutor-session-map")).toBeNull();
      unmount();
    }
    expect(observed).toBeNull();
    expect(seen.props).toEqual([]);
  });
});

describe("sessionMapGraph", () => {
  it("keeps the concepts and the links between them", () => {
    const g = sessionMapGraph(NODES, EDGES);
    expect(g.nodes).toEqual(CONCEPTS);
    expect(g.edges).toEqual([edge("a", "b")]);
  });

  it("has no concepts when the course has only its root", () => {
    expect(sessionMapGraph([ROOT], [edge("root-c1", "root-c1")])).toEqual({ nodes: [], edges: [] });
  });
});

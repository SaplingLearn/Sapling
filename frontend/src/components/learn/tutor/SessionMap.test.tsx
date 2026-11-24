// @vitest-environment jsdom
/**
 * The session panel's map (PR #866 U4): drawn in mastery colours whatever the
 * Tree's toggle is set to (its key, under it, is the mastery key), framed so
 * every concept and caption is inside the panel, and with nothing drawn over
 * its nodes — no colour toggle (KnowledgeGraph draws none for a fixed mode),
 * no zoom stack. It renders once the panel's width is measured.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, render, screen } from "@testing-library/react";
import React from "react";

const seen = vi.hoisted(() => ({ props: [] as Record<string, unknown>[] }));
vi.mock("../../graph/KnowledgeGraph", () => ({
  KnowledgeGraph: (props: Record<string, unknown>) => {
    seen.props.push(props);
    return <div data-testid="kg" />;
  },
}));

import { SessionMap } from "./SessionMap";

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
    render(<SessionMap nodes={[]} edges={[]} highlightId="n1" />);
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
    render(<SessionMap nodes={[]} edges={[]} highlightId="a" practicedNodeIds={practiced} />);
    act(() => observed!(264));
    expect(seen.props.at(-1)).toMatchObject({
      highlightId: "a",
      practicedIds: practiced,
    });
  });
});

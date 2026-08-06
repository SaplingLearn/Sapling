// @vitest-environment jsdom
/**
 * NEXT_PUBLIC_TEST_MODE determinism for KnowledgeGraph3D (#383).
 *
 * Test mode must force `cooldownTicks={0}` even when the OS reports no
 * reduced-motion preference — the same ready-made seam the
 * prefers-reduced-motion path uses, so the WebGL layout renders its
 * deterministic initial arrangement without a physics warm-up.
 *
 * Mocks mirror KnowledgeGraph3D.test.tsx (props-capturing stub for
 * react-force-graph-3d, passthrough next/dynamic). The component is
 * imported lazily in beforeAll so the file-scope env stub is visible
 * when `@/lib/testMode` first evaluates.
 */

import { describe, it, expect, vi, beforeAll, beforeEach, afterEach } from "vitest";
import { render, cleanup, fireEvent } from "@testing-library/react";
import React from "react";
import type { GraphNode } from "@/lib/data";

vi.stubEnv("NEXT_PUBLIC_TEST_MODE", "1");

// eslint-disable-next-line @typescript-eslint/no-explicit-any
let lastProps: Record<string, any> | null = null;
let zoomToFitSpy = vi.fn();

vi.mock("react-force-graph-3d", () => ({
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  default: React.forwardRef((props: any, ref: React.Ref<unknown>) => {
    lastProps = props;
    React.useImperativeHandle(ref, () => ({ zoomToFit: zoomToFitSpy }));
    return null;
  }),
}));

vi.mock("next/dynamic", () => ({
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  default: (loader: any) => {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    let Resolved: any = () => null;
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    Promise.resolve(loader()).then((mod: any) => {
      Resolved = mod?.default ?? mod;
    });
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const Wrapper = (props: any) => {
      const C = Resolved;
      return C ? C(props) : null;
    };
    return Wrapper;
  },
}));

let KnowledgeGraph3D: (typeof import("./KnowledgeGraph3D"))["KnowledgeGraph3D"];

beforeAll(async () => {
  ({ KnowledgeGraph3D } = await import("./KnowledgeGraph3D"));
});

function installNoPreferenceMatchMedia() {
  Object.defineProperty(window, "matchMedia", {
    writable: true,
    configurable: true,
    value: vi.fn().mockImplementation((query: string) => ({
      matches: false, // OS reports NO reduced-motion preference
      media: query,
      onchange: null,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      addListener: vi.fn(),
      removeListener: vi.fn(),
      dispatchEvent: vi.fn(),
    })),
  });
}

const NODE: GraphNode = {
  id: "n1",
  name: "Node 1",
  subject: "Math",
  color: "#88aa55",
  mastery_tier: "learning",
  mastery_score: 0.5,
  course_id: "c1",
};

beforeEach(() => {
  lastProps = null;
  zoomToFitSpy = vi.fn();
  installNoPreferenceMatchMedia();
});

afterEach(() => {
  cleanup();
});

describe("KnowledgeGraph3D — test-mode determinism", () => {
  it("forces cooldownTicks to 0 and warmupTicks to 200 even without a reduced-motion preference", () => {
    render(<KnowledgeGraph3D nodes={[NODE]} edges={[]} />);
    expect(lastProps).not.toBeNull();
    expect(lastProps!.cooldownTicks).toBe(0);
    // warmupTicks mirrors KnowledgeGraph2D's sim.tick(200) precedent: run
    // the simulation to a real settled layout synchronously instead of
    // skipping it outright under test mode.
    expect(lastProps!.warmupTicks).toBe(200);
  });

  it("recenter button fires an instant (0ms) fit under test mode (IS_TEST_MODE gating)", () => {
    // IS_TEST_MODE is stubbed true file-wide here even though the OS
    // reports no reduced-motion preference — the button's zoomToFit
    // gating (`reducedMotion || IS_TEST_MODE ? 0 : 400`) must still zero
    // the duration via the IS_TEST_MODE half of that condition.
    const { getByTestId } = render(<KnowledgeGraph3D nodes={[NODE]} edges={[]} />);
    fireEvent.click(getByTestId("graph-zoom-reset"));
    expect(zoomToFitSpy).toHaveBeenCalledWith(0, 60);
  });
});

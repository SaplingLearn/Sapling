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

// Exactly the props these tests read — spelled out so the capture needs no
// `any` (and therefore no eslint suppression). No index signature: forwardRef
// runs its props type through `PropsWithoutRef`, and `Omit` collapses an
// index-signature type down to just the index signature, losing every key.
type CapturedProps = {
  cooldownTicks: number;
  warmupTicks: number;
};
let lastProps: CapturedProps | null = null;
let zoomToFitSpy = vi.fn();

vi.mock("react-force-graph-3d", () => ({
  // A NAMED function inside forwardRef so the component has a display name,
  // and props are recorded in an EFFECT rather than in the render body:
  // reassigning a module-scope variable during render is a render-phase side
  // effect (react-hooks/globals) that tears under a discarded concurrent
  // render. Testing Library's render/rerender/act all flush passive effects
  // before returning, so tests still observe the props synchronously.
  default: React.forwardRef(function ForceGraph3DMock(
    props: CapturedProps,
    ref: React.Ref<unknown>,
  ) {
    React.useImperativeHandle(ref, () => ({ zoomToFit: zoomToFitSpy }));
    React.useEffect(() => {
      lastProps = props;
    });
    return null;
  }),
}));

// Shared passthrough (#538) — it renders the resolved component via
// createElement instead of calling it, so the stub's hooks land in their own
// fiber, and it accepts this component's loader, which resolves to a bare
// function component rather than a module namespace.
//
// `await import` rather than a static import because vitest hoists vi.mock
// factories above every import in the file — a static binding would still be
// uninitialised when the factory runs.
vi.mock("next/dynamic", async () =>
  (await import("@/test-utils/mockNextDynamic")).mockNextDynamicModule(),
);

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

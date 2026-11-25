// @vitest-environment jsdom
/**
 * W2.5: the probe's Next is held (disabled, with the dwell notice) while a
 * confident miss's feedback dwell runs, and free otherwise — with the question
 * still on screen and after it is gone.
 */
import React from "react";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { LoopProbeItem } from "@/lib/api";
import { HYPERCORRECTION_DWELL_COPY } from "@/lib/hypercorrectionDwell";
import { ProbePanel } from "./ProbePanel";
import { type Draft } from "./loopShared";

afterEach(cleanup);

const draft: Draft = { answer: "", option: "", reason: "", reasoning: "", confidence: null };
const item = {
  done: false, check_item_id: "i1", question_hash: "qh", node_id: "n1", format: "free", difficulty: 1,
  prompt: "What is a base case?", options: null,
} as LoopProbeItem;

function panel(nextHeld: boolean, shown: LoopProbeItem | null, onNext = vi.fn()) {
  render(
    <ProbePanel
      item={shown} count={1} draft={draft} setDraft={vi.fn()} reference="It stops the recursion." note={null}
      busy={false} nextHeld={nextHeld} loadFailed={false} greeting={null}
      onSubmit={vi.fn()} onIdk={vi.fn()} onNext={onNext} onRetry={vi.fn()}
    />,
  );
  return onNext;
}

describe("ProbePanel — the hypercorrection hold (W2.5)", () => {
  it.each([["with the question", item], ["without it", null]] as const)("holds Next %s", (_name, shown) => {
    const onNext = panel(true, shown);
    expect(screen.getByTestId("loop-probe-next")).toBeDisabled();
    expect(screen.getByRole("status")).toHaveTextContent(HYPERCORRECTION_DWELL_COPY);
    expect(screen.getByTestId("loop-probe-reference")).toHaveTextContent("It stops the recursion.");
    fireEvent.click(screen.getByTestId("loop-probe-next"));
    expect(onNext).not.toHaveBeenCalled();
  });

  it.each([["with the question", item], ["without it", null]] as const)("leaves Next free when nothing holds it, %s", (_name, shown) => {
    const onNext = panel(false, shown);
    expect(screen.queryByTestId("loop-feedback-dwell")).toBeNull();
    fireEvent.click(screen.getByTestId("loop-probe-next"));
    expect(onNext).toHaveBeenCalledTimes(1);
  });
});

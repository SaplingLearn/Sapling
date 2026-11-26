// @vitest-environment jsdom
/**
 * The hint ladder (Tutor redesign phase 4, `hint_ladder`) against its design:
 * `../__fixtures__/question-states.design.html` is the Claude Design board the
 * rebuild was made from (states 1–3), kept verbatim. The copy the card says is
 * pulled from it, so a later edit that drifts from the design fails here.
 * jsdom has no layout engine: this checks words, labels and states, not pixels.
 */
import fs from "node:fs";
import path from "node:path";
import React, { useState } from "react";
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { LoopCheckItem } from "@/lib/api";
import { CheckCard } from "../CheckCard";
import { type Draft } from "../loopShared";
import { HINT_LADDER_COPY, clock, nextHintLabel, stepLabels, type HintLadderView, type HintStep } from "./HintLadder";

vi.mock("../../Icon", () => ({ Icon: () => null }));

afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

const DESIGN = fs.readFileSync(path.join(__dirname, "../__fixtures__/question-states.design.html"), "utf8")
  .replace(/&#39;|&rsquo;|’/g, "'");

const item: LoopCheckItem = { question_hash: "qh", format: "free", difficulty: 2, prompt: "Why does linear probing create clusters?", options: null };
const step = (rung: number, reply = `hint at ${rung}`): HintStep => ({ rung, reply });

function renderCard(ladder: HintLadderView | null, hint: { denied: string } | { reply: string } | null = null, onHint = vi.fn()) {
  function Harness() {
    const [draft, setDraft] = useState<Draft>({ answer: "", option: "", reason: "", confidence: null });
    return (
      <CheckCard item={item} draft={draft} setDraft={setDraft} busy={false} hint={hint} hintBusy={false} hintRetry={false}
        onSubmit={vi.fn()} onIdk={vi.fn()} onHint={onHint} ladder={ladder} />
    );
  }
  return render(<Harness />);
}

describe("the ladder's rules", () => {
  it("names the next step: Hint, Hint 2, then the worked steps", () => {
    expect(nextHintLabel([])).toBe("Hint");
    expect(nextHintLabel([step(1)])).toBe("Hint 2");
    expect(nextHintLabel([step(1), step(2), step(3)])).toBe("Show worked steps");
    // A12/A122: an item that opens on its worked example jumps straight to H4
    expect(stepLabels([step(4)])).toEqual(["Worked steps."]);
    expect(stepLabels([step(1), step(2), step(4)])).toEqual(["Hint 1.", "Hint 2.", "Worked steps."]);
  });

  it("counts down in minutes and seconds", () => {
    expect(clock(32)).toBe("0:32");
    expect(clock(65)).toBe("1:05");
    expect(clock(-3)).toBe("0:00");
  });
});

describe("parity with the design board", () => {
  it.each([
    HINT_LADDER_COPY.locked, HINT_LADDER_COPY.hintCost, HINT_LADDER_COPY.stepsCost, HINT_LADDER_COPY.stepsWarning,
    "Hint 2", `Hint in ${clock(32)}`,
  ])("the board says %j", (text) => {
    expect(DESIGN).toContain(text);
  });

  it("state 1: a locked hint says why, and counts down on its button, still focusable", () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-11-26T10:00:00Z"));
    renderCard({ steps: [], waitUntil: Date.now() + 32_000 }, { denied: "no_genuine_attempt" });
    const button = screen.getByTestId("loop-hint-button");
    expect(button.textContent).toBe(`Hint in ${clock(32)}`);
    expect(button.getAttribute("aria-disabled")).toBe("true");
    expect(screen.getByTestId("loop-hint-denied").textContent).toBe(HINT_LADDER_COPY.locked);
    act(() => { vi.advanceTimersByTime(33_000); });
    expect(button.textContent).toBe("Hint");
    expect(button.getAttribute("aria-disabled")).toBe("false");
  });

  it("state 2: the hint taken stays stacked, the costs show, the next step is Hint 2", () => {
    renderCard({ steps: [step(1, "Where does the next key go?")], waitUntil: null });
    expect(screen.getByTestId("loop-hint-ladder").textContent).toBe("Hint 1. Where does the next key go?");
    expect(screen.getByTestId("loop-hint-cost").textContent).toContain(HINT_LADDER_COPY.hintCost);
    expect(screen.getByTestId("loop-hint-cost").textContent).toContain(HINT_LADDER_COPY.stepsCost);
    expect(screen.getByTestId("loop-hint-button").textContent).toBe("Hint 2");
  });

  it("state 3: before the worked steps, the card says what they cost", () => {
    const onHint = vi.fn();
    renderCard({ steps: [step(1), step(2), step(3)], waitUntil: null }, null, onHint);
    expect(screen.getByTestId("loop-hint-button").textContent).toBe("Show worked steps");
    expect(screen.getByTestId("loop-hint-cost").textContent).toContain(HINT_LADDER_COPY.stepsWarning);
    fireEvent.click(screen.getByTestId("loop-hint-button"));
    expect(onHint).toHaveBeenCalledTimes(1);
  });

  it("off (no ladder): the one Hint button and the latest hint, as before", () => {
    renderCard(null, { reply: "latest hint" });
    expect(screen.getByTestId("loop-hint-button").textContent).toBe("Hint");
    expect(screen.getByTestId("loop-hint-reply").textContent).toContain("latest hint");
    expect(screen.queryByTestId("loop-hint-ladder")).toBeNull();
    expect(screen.queryByTestId("loop-hint-cost")).toBeNull();
  });
});

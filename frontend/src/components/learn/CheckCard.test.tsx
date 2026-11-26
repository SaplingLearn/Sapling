// @vitest-environment jsdom
/**
 * The check card's chrome. W4.4's "Key verified" line was removed in the
 * Tutor redesign's subtract pass (trust chrome that changed no decision);
 * W4.1a's honest withheld-figure line stays.
 */
import React, { useState } from "react";
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { LoopCheckItem } from "@/lib/api";
import { CheckCard } from "./CheckCard";
import { type Draft } from "./loopShared";

vi.mock("../Icon", () => ({ Icon: () => null }));

afterEach(cleanup);

const emptyDraft: Draft = {
  answer: "",
  option: "",
  reason: "",
  reasoning: "",
  confidence: null,
};

const baseItem: LoopCheckItem = {
  question_hash: "qh-k",
  format: "free",
  difficulty: 2,
  prompt: "Why does the base case stop?",
  options: null,
};

function renderCard(item: LoopCheckItem) {
  function Harness() {
    const [draft, setDraft] = useState<Draft>(emptyDraft);
    return (
      <CheckCard
        item={item}
        draft={draft}
        setDraft={setDraft}
        busy={false}
        hint={null}
        hintBusy={false}
        hintRetry={false}
        onSubmit={vi.fn()}
        onIdk={vi.fn()}
        onHint={vi.fn()}
      />
    );
  }
  return render(<Harness />);
}

describe("CheckCard chrome", () => {
  it("shows no Key verified line, even when the pose carries key_verified", () => {
    renderCard({ ...baseItem, key_verified: true });
    expect(screen.queryByTestId("loop-key-verified")).toBeNull();
    expect(screen.queryByText(/Key verified/)).toBeNull();
  });

  it("W4.1a: shows withheld figure slot when pose.figure.status is withheld", () => {
    renderCard({ ...baseItem, figure: { status: "withheld" } });
    const slot = screen.getByTestId("loop-figure-withheld");
    expect(slot).toHaveTextContent(/no figure attached yet/i);
  });

  it("W4.1a: omits figure chrome without pose.figure", () => {
    renderCard(baseItem);
    expect(screen.queryByTestId("loop-figure-withheld")).toBeNull();
  });

  it("omits chrome without key_verified (never invents trust)", () => {
    renderCard(baseItem);
    expect(screen.queryByTestId("loop-key-verified")).toBeNull();
  });
});

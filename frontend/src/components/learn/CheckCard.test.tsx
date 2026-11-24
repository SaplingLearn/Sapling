// @vitest-environment jsdom
/**
 * W4.4: calm "Key verified" chrome on the check card only when the pose
 * carries `key_verified` (server: check_items.canonical_verified). Never
 * invents trust chrome without that signal.
 */
import React, { useState } from "react";
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { LoopCheckItem } from "@/lib/api";
import { KEY_VERIFIED_HINT, KEY_VERIFIED_LABEL } from "@/lib/loopTrustChrome";
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

describe("CheckCard W4.4 key-verified chrome", () => {
  it("shows Key verified when the pose carries key_verified", () => {
    renderCard({ ...baseItem, key_verified: true });
    const chrome = screen.getByTestId("loop-key-verified");
    expect(chrome.textContent).toBe(KEY_VERIFIED_LABEL);
    expect(chrome).toHaveAttribute("role", "status");
    expect(chrome).toHaveAttribute("title", KEY_VERIFIED_HINT);
    expect(chrome.getAttribute("aria-label")).toContain(KEY_VERIFIED_HINT);
  });

  it("omits chrome without key_verified (never invents trust)", () => {
    renderCard(baseItem);
    expect(screen.queryByTestId("loop-key-verified")).toBeNull();
  });
});

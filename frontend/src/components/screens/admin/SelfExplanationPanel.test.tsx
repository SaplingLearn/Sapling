// @vitest-environment jsdom
/**
 * The learning-loop self-explanation section (spec §13 A139): what it shows
 * from the admin KPI's `self_explanation` field — prompts shown, the reply
 * rate and length, the next item after a reply against after none, per
 * juncture — that every rate carries its n, that nothing renders for a backend
 * before A139, that a failed read says so, and that "nothing behind it" reads
 * "—", never a zero.
 */

import React from "react";
import { afterEach, describe, expect, it } from "vitest";
import { cleanup, render, screen, within } from "@testing-library/react";

import { JUNCTURE_LABEL, SelfExplanationPanel } from "./SelfExplanationPanel";
import type { LoopSelfExplainNext, LoopSelfExplanation } from "@/lib/types";

afterEach(cleanup);

const next = (n: number, unassisted: number, none = 0): LoopSelfExplainNext => ({
  n, unassisted, rate: n ? unassisted / n : null, none,
});

const report: LoopSelfExplanation = {
  shown: 8,
  replied: 5,
  skipped: 2,
  open: 1,
  reply_rate: 5 / 8,
  reply_chars: { median: 42, n: 5 },
  next_item: { replied: next(4, 3, 1), not_replied: next(2, 0, 1) },
  by_juncture: [
    { juncture: "worked_example", shown: 5, replied: 4, reply_rate: 0.8, next_item: { replied: next(3, 2), not_replied: next(1, 0) } },
    { juncture: "first_correct", shown: 3, replied: 1, reply_rate: 1 / 3, next_item: { replied: next(0, 0, 1), not_replied: next(0, 0) } },
  ],
  truncated: false,
};

describe("SelfExplanationPanel (spec §13 A139)", () => {
  it("renders nothing for a backend before A139, and says so when the reads failed", () => {
    const { container } = render(<SelfExplanationPanel data={undefined} />);
    expect(container.innerHTML).toBe("");
    cleanup();
    render(<SelfExplanationPanel data={null} />);
    expect(screen.getByTestId("admin-loop-self-explain-unavailable").textContent).toContain("could not be read");
  });

  it("says when no prompt was shown, instead of a table of zeros", () => {
    render(
      <SelfExplanationPanel
        data={{
          ...report, shown: 0, replied: 0, skipped: 0, open: 0, reply_rate: null,
          reply_chars: { median: null, n: 0 },
          next_item: { replied: next(0, 0), not_replied: next(0, 0) }, by_juncture: [],
        }}
      />,
    );
    expect(screen.getByTestId("admin-loop-self-explain-empty")).toBeTruthy();
    expect(screen.queryByTestId("admin-loop-self-explain-reply-rate")).toBeNull();
  });

  it("shows prompts shown, the reply rate and length, each with its n", () => {
    render(<SelfExplanationPanel data={report} />);
    const shown = screen.getByTestId("admin-loop-self-explain-shown");
    expect(shown.textContent).toContain("8");
    expect(shown.textContent).toContain("5 replied · 2 skipped · 1 unanswered");
    const rate = screen.getByTestId("admin-loop-self-explain-reply-rate");
    expect(rate.textContent).toContain("62.5%");
    expect(rate.textContent).toContain("n = 8");
    const chars = screen.getByTestId("admin-loop-self-explain-reply-chars");
    expect(chars.textContent).toContain("42 chars");
    expect(chars.textContent).toContain("n = 5");
  });

  it("compares the next item after a reply with after none", () => {
    render(<SelfExplanationPanel data={report} />);
    const after = screen.getByTestId("admin-loop-self-explain-next-replied");
    expect(after.textContent).toContain("3 of 4 (75%)");
    expect(after.textContent).toContain("n = 4");
    expect(after.textContent).toContain("1 with no next item yet");
    const without = screen.getByTestId("admin-loop-self-explain-next-not-replied");
    expect(without.textContent).toContain("0 of 2 (0%)");
  });

  it("splits by juncture, labelled in words; a rate with nothing behind it reads —", () => {
    render(<SelfExplanationPanel data={report} />);
    const worked = screen.getByTestId("admin-loop-self-explain-juncture-worked_example");
    expect(within(worked).getByText(JUNCTURE_LABEL.worked_example)).toBeTruthy();
    expect(within(worked).getByText("80% (4 of 5)")).toBeTruthy();
    expect(within(worked).getByText("2 of 3 (66.7%)")).toBeTruthy();
    const first = screen.getByTestId("admin-loop-self-explain-juncture-first_correct");
    expect(within(first).getByText(JUNCTURE_LABEL.first_correct)).toBeTruthy();
    expect(within(first).getAllByText("—")).toHaveLength(2); // no next item measured either way
  });

  it("labels the next-item figures a description, not an effect", () => {
    render(<SelfExplanationPanel data={report} />);
    expect(screen.getByTestId("admin-loop-self-explain").textContent).toContain("not a measured effect");
    expect(screen.getByTestId("admin-loop-self-explain").textContent).toContain("never graded");
  });
});

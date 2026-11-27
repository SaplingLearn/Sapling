// @vitest-environment jsdom
/**
 * The rebuilt wrap-up (Tutor redesign phase 4, `wrapup_v2`) against its design
 * board, `../__fixtures__/wrapup.design.html`, kept verbatim: the words the
 * rebuild says are pulled from it, so a drift from the design fails here
 * (words and structure, not pixels: jsdom has no layout).
 */
import fs from "node:fs";
import path from "node:path";
import React from "react";
import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("@/context/UserContext", () => ({ useUser: () => ({ userId: "u1", userReady: true }) }));
vi.mock("@/context/FlagsContext", () => ({ useFlag: () => "off" }));
vi.mock("next/link", () => ({
  default: React.forwardRef<HTMLAnchorElement, React.AnchorHTMLAttributes<HTMLAnchorElement>>(function LinkStub(props, ref) {
    return <a ref={ref} {...props} />;
  }),
}));
vi.mock("../WrapUpRating", () => ({ WrapUpRating: () => <div data-testid="rating-stub" /> }));

import type { LoopCloseConcept, LoopCloseResponse } from "@/lib/api";
import { WRAPUP_COPY, WrapUpV2, conceptRow, wrapHeadline, wrapRows } from "./WrapUpV2";

afterEach(cleanup);

const DESIGN = fs.readFileSync(path.join(__dirname, "../__fixtures__/wrapup.design.html"), "utf8").replace(/&#39;|&rsquo;|’/g, "'");
const names = new Map([["ht", "Hash tables"], ["st", "Stacks"], ["cr", "Collision resolution"], ["q", "Queues"]]);
const c = (node_id: string, p_before: number, p_after: number, baseline?: LoopCloseConcept["baseline"]): LoopCloseConcept =>
  ({ node_id, p_before, p_after, ...(baseline ? { baseline } : {}) });
const BOARD = [c("ht", 0.25, 0.45), c("st", 0.5, 0.6), c("cr", 0.2, 0.2, "teaching")];
const close = (concepts: LoopCloseConcept[]): LoopCloseResponse => ({
  close: { summary: "You reviewed stacks and learned how a hash table places keys.", self_eval: "", if_then: "Redo the two collision questions.", concepts, misconceptions: [], model_written: true },
  model_written: true, close_phase: "teach",
});
const ALL = { study: true, tutor: true, quiz: true, tree: true };

function renderWrap(concepts: LoopCloseConcept[], dueCount: number | null, onNew = vi.fn()) {
  return render(
    <WrapUpV2 close={close(concepts)} names={names} courseId="c1" onNew={onNew} visibility={ALL} rating={null}
      planned={["ht", "st", "cr", "q"]} dueCount={dueCount} headingRef={() => {}} />,
  );
}

describe("what the wrap-up says", () => {
  it("each concept in the ladder's words, a first measurement never a drop", () => {
    expect(conceptRow(c("ht", 0.25, 0.45), "Hash tables").change).toBe("Getting started to Developing");
    expect(conceptRow(c("st", 0.5, 0.6), "Stacks").change).toBe("Developing, a little higher");
    expect(conceptRow(c("cr", 0.2, 0.2, "teaching"), "Collision resolution").change).toBe("Measured for the first time: Getting started");
    expect(conceptRow(c("x", 0.5, 0.5), "X").change).toBe("Developing, no change");
  });

  it("the plan's concepts the session did not reach close the list", () => {
    const rows = wrapRows(BOARD, ["ht", "q"], names);
    expect(rows.map((r) => [r.name, r.change])).toEqual([
      ["Hash tables", "Getting started to Developing"],
      ["Stacks", "Developing, a little higher"],
      ["Collision resolution", "Measured for the first time: Getting started"],
      ["Queues", "Not reached today"],
    ]);
  });

  it("the headline comes from the data", () => {
    expect(wrapHeadline(BOARD, names)).toEqual({ text: "Hash tables moved up to Developing", leadId: "ht" });
    expect(wrapHeadline([c("cr", 0.2, 0.2, "check_in"), c("st", 0.5, 0.5, "teaching")], names).text).toBe("2 concepts measured for the first time");
    expect(wrapHeadline([c("st", 0.5, 0.6)], names).text).toBe("Stacks is a little stronger");
    expect(wrapHeadline([], names).text).toBe("Nothing measured yet");
  });
});

describe("parity with the design board", () => {
  it.each([
    "Hash tables moved up to Developing", "Getting started to Developing", "Developing, a little higher",
    "Measured for the first time: Getting started", WRAPUP_COPY.notReached, WRAPUP_COPY.nextTime,
  ])("the board says %j", (text) => {
    expect(DESIGN).toContain(text);
  });

  it("the board's order: headline, what changed, summary, Next time, the next step", () => {
    renderWrap(BOARD, 7);
    const root = screen.getByTestId("loop-wrapup-v2");
    const order = ["loop-close-headline", "loop-close-concept-ht", "loop-close-summary", "loop-close-if-then", "loop-close-done"]
      .map((id) => within(root).getByTestId(id));
    for (let i = 1; i < order.length; i += 1) {
      expect(order[i - 1].compareDocumentPosition(order[i]) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    }
    expect(screen.getByTestId("loop-close-concept-q").getAttribute("data-reached")).toBe("false");
  });

  it("one primary next step: Review when reviews are due, New session beside it, the rest under More practice", () => {
    renderWrap(BOARD, 7);
    const done = screen.getByTestId("loop-close-done");
    const primary = within(done).getByRole("link", { name: "7 reviews due" });
    expect(primary.className).toContain("btn--primary");
    expect(within(done).getByTestId("loop-close-new-session").className).not.toContain("btn--primary");
    const more = screen.getByRole("heading", { name: "More practice" }).parentElement!;
    expect(within(more).queryByText("Review")).toBeNull();
    expect(within(more).getByTestId("loop-close-tree-link")).toBeTruthy();
    expect(screen.queryByText(/Check retention after time away/)).toBeNull(); // cut
  });

  it("nothing due: New session is the one primary step", () => {
    renderWrap(BOARD, 0);
    expect(screen.getByTestId("loop-close-new-session").className).toContain("btn--primary");
    expect(screen.queryByTestId("loop-close-study-link")).toBeNull();
  });
});

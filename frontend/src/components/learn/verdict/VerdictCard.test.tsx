// @vitest-environment jsdom
/**
 * The rebuilt verdict (Tutor redesign phase 4, `verdict_v2`) against its
 * design: `../__fixtures__/question-states.design.html`, states 4–6, kept
 * verbatim. The words the card and Continue say are pulled from the board, so
 * a later edit that drifts from the design fails here (words and states, not
 * pixels: jsdom has no layout).
 */
import fs from "node:fs";
import path from "node:path";
import React from "react";
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import type { LoopLearnerState } from "@/lib/api";
import { clock } from "../question/HintLadder";
import { VERDICT_V2_COPY, VerdictCard, VerdictSlot, creditLine, nextStepLabel, skillChangeLine, verdictTitle } from "./VerdictCard";

afterEach(cleanup);

const DESIGN = fs.readFileSync(path.join(__dirname, "../__fixtures__/question-states.design.html"), "utf8")
  .replace(/&#39;|&rsquo;|’/g, "'");
const ls = (p_known: number, measured?: false): LoopLearnerState =>
  ({ node_id: "n1", p_known, band: p_known < 0.3 ? "novice" : p_known < 0.8 ? "develop" : "profic", ...(measured === false ? { measured } : {}) });

describe("what the verdict says", () => {
  it("titles: Correct, Correct, half credit (a hint), part credit (anything else), Not quite", () => {
    expect(verdictTitle("correct", "full")).toBe("Correct");
    expect(verdictTitle("correct", "partial", ["hint"])).toBe("Correct, half credit");
    expect(verdictTitle("correct", "partial", ["recheck"])).toBe("Correct, part credit");
    expect(verdictTitle("correct", "none")).toBe("Correct");
    expect(verdictTitle("not_yet")).toBe("Not quite");
    expect(verdictTitle("idk")).toBe("Not quite");
  });

  it("one credit line, only when credit was reduced, never blaming the student", () => {
    expect(creditLine("full", [], "Loops")).toBeNull();
    expect(creditLine("partial", ["hint"], "Hash tables")).toBe("You used a hint, so this counts half toward Hash tables. Try the next one on your own.");
    expect(creditLine("partial", ["hint", "recheck"], "Loops")).toBe(
      "This counts partly toward Loops, because you used a hint and this idea was already checked earlier this session.",
    );
    expect(creditLine("none", [], "Loops")).toBe(`${VERDICT_V2_COPY.noCredit} ${VERDICT_V2_COPY.tryOnOwn}`);
    expect(creditLine("none", [], "Loops")).not.toMatch(/help was shown/);
  });

  it("the skill change, shown once: a new level, a move within one, or the first measurement", () => {
    expect(skillChangeLine("Hash tables", ls(0.25), ls(0.4))).toBe("Hash tables: Getting started → Developing");
    expect(skillChangeLine("Hash tables", ls(0.4), ls(0.5))).toBe("Hash tables: Developing, a little higher");
    expect(skillChangeLine("Hash tables", ls(0.5), ls(0.45))).toBe("Hash tables: Developing, a little lower");
    expect(skillChangeLine("Hash tables", undefined, ls(0.4))).toBe("Hash tables: Developing");
    expect(skillChangeLine("Hash tables", ls(0.35, false), ls(0.4))).toBe("Hash tables: Developing"); // a prior is no "before"
    expect(skillChangeLine("Hash tables", ls(0.4), ls(0.4))).toBeNull(); // nothing moved
    expect(skillChangeLine("Hash tables", ls(0.4), ls(0.4, false))).toBeNull(); // no measurement
  });

  it("Continue names the plan's next concept, else just Continue", () => {
    expect(nextStepLabel("Collision resolution")).toBe("Next: Collision resolution");
    expect(nextStepLabel(undefined)).toBe("Continue");
    expect(nextStepLabel(null)).toBe("Continue");
  });
});

describe("parity with the design board (states 4–6)", () => {
  it.each([
    VERDICT_V2_COPY.correct, VERDICT_V2_COPY.halfCredit, VERDICT_V2_COPY.notQuite, VERDICT_V2_COPY.sure,
    creditLine("partial", ["hint"], "Hash tables")!, nextStepLabel("Collision resolution"),
    "Getting started", "Developing", "a little higher", `in ${clock(6)}`,
  ])("the board says %j", (text) => {
    expect(DESIGN).toContain(text);
  });

  it("state 5: half credit, its one line, and the skill change", () => {
    render(<VerdictCard verdict="correct" credit="partial" reasons={["hint"]} concept="Hash tables" before={ls(0.2)} after={ls(0.25)} held={false} />);
    const card = screen.getByTestId("loop-verdict");
    expect(card.getAttribute("data-credit")).toBe("partial");
    expect(card.querySelector("p")?.textContent).toBe("Correct, half credit");
    expect(screen.getByTestId("loop-verdict-credit").textContent).toContain("counts half toward Hash tables");
    expect(screen.getByTestId("loop-verdict-skill").textContent).toBe("Hash tables: Getting started, a little higher");
  });

  it("state 6: Not quite after a confident answer says why the next step waits", () => {
    render(<VerdictCard verdict="not_yet" concept="Hash tables" held />);
    expect(screen.getByTestId("loop-verdict").getAttribute("data-verdict")).toBe("not_yet");
    expect(screen.getByTestId("loop-verdict-sure").textContent).toBe(VERDICT_V2_COPY.sure);
    expect(screen.queryByTestId("loop-verdict-credit")).toBeNull();
  });

  it("off: the slot is the banner as before", () => {
    render(<VerdictSlot v2={false} verdict={{ verdict: "correct", nodeId: "n1", credit: "full" }} next={undefined}
      concept="Loops" before={{}} after={{}} held={false} />);
    expect(screen.getByTestId("loop-verdict").textContent).toContain("That answer counts toward this concept.");
    expect(screen.queryByTestId("loop-verdict-skill")).toBeNull();
  });
});

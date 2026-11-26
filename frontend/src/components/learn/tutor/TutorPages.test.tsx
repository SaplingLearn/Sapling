// @vitest-environment jsdom
/**
 * The Tutor home (T1): its CTA says "Starting…" only while a start is in
 * flight — a home that is only waiting on its lists (or a pending grade) is
 * disabled, never described as starting (#866 Z59).
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import React from "react";

vi.mock("next/link", () => ({
  default: ({ children, href, ...rest }: { children: React.ReactNode; href: string }) => <a href={href} {...rest}>{children}</a>,
}));

import { MASTERY_PALETTE, tierFor } from "@/lib/graph/nodeStyle";
import { Meter, TutorHome, masteryTone, meterTier } from "./TutorPages";

afterEach(cleanup);

function home(busy: boolean, starting: boolean) {
  const noop = () => {};
  return render(
    <TutorHome courseName="Intro CS" continueRow={null} dueCount={null} dueHref={null} startWith={{ id: "n1", name: "Recursion" }}
      busy={busy} starting={starting} closesCurrent={null}
      onContinue={noop} onStart={noop} onStartWith={noop} onGoal={noop} />,
  );
}

describe("TutorHome's CTA", () => {
  it("is disabled but keeps its label while the home only waits on its lists", () => {
    home(true, false);
    const cta = screen.getByTestId("loop-start-guided") as HTMLButtonElement;
    expect(cta.disabled).toBe(true);
    expect(cta.textContent).toContain("New session");
    expect(cta.textContent).not.toContain("Starting");
  });

  it("says Starting… while a start is in flight", () => {
    home(true, true);
    expect(screen.getByTestId("loop-start-guided").textContent).toContain("Starting…");
  });
});

describe("#866 K21 — a skill meter colours mastery as the map does", () => {
  it.each([
    [0.97, "mastered"], [0.95, "mastered"], [0.88, "learning"], [0.8, "learning"], [0.44, "learning"],
    [0.3, "learning"], [0.29, "struggling"], [0.1, "struggling"], [0.05, "unexplored"], [null, "unexplored"],
  ] as const)("score %s is the map's %s tier, in the map key's colour", (score, tier) => {
    expect(meterTier(score)).toBe(tier);
    expect(masteryTone(score)).toBe(MASTERY_PALETTE[tier]);
    expect(meterTier(score)).toBe(score == null ? "unexplored" : tierFor(score));
  });

  it("the meter names its tier", () => {
    render(<Meter label="Recursion" score={0.8} testId="m" />);
    expect(screen.getByTestId("m").getAttribute("data-tier")).toBe("learning");
    expect(screen.getByRole("meter", { name: "Recursion skill" }).getAttribute("aria-valuetext")).toBe("80%, Learning");
  });
});

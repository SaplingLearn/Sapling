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

import { TutorHome } from "./TutorPages";

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
    expect(cta.textContent).toContain("Start a guided session");
    expect(cta.textContent).not.toContain("Starting");
  });

  it("says Starting… while a start is in flight", () => {
    home(true, true);
    expect(screen.getByTestId("loop-start-guided").textContent).toContain("Starting…");
  });
});

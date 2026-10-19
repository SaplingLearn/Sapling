// @vitest-environment jsdom
/**
 * The shell's top-right utility cluster: its Settings link draws the same
 * Lucide gear as the sidebar's Settings row (#727's hand-drawn gear polygon
 * rendered as a lumpy blob).
 */
import React from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render } from "@testing-library/react";

vi.mock("next/navigation", () => ({ usePathname: () => "/dashboard", useSearchParams: () => new URLSearchParams() }));
vi.mock("./fa26/Navigation", () => ({ Navigation: () => null }));
vi.mock("./ReportIssueFlow", () => ({ ReportIssueFlow: () => null }));
vi.mock("./FeedbackFlow", () => ({ FeedbackFlow: () => null }));
vi.mock("./SessionFeedbackGlobal", () => ({ SessionFeedbackGlobal: () => null }));
vi.mock("./AchievementUnlockWatcher", () => ({ AchievementUnlockWatcher: () => null }));
vi.mock("./NavFeatureGate", () => ({ NavFeatureGate: ({ children }: { children: React.ReactNode }) => <>{children}</> }));

import { ShellFrame } from "./ShellFrame";
import { Settings } from "lucide-react";

afterEach(cleanup);

describe("ShellFrame utility cluster", () => {
  it("draws the Settings link with the shared Lucide gear", () => {
    const { container } = render(<ShellFrame><p>page</p></ShellFrame>);
    const link = container.querySelector('a[aria-label="Settings"][href="/settings"]');
    expect(link).toBeTruthy();
    const gear = link!.querySelector("svg");
    expect(gear).toHaveClass("lucide-settings", "fa26-gear");
    expect(gear).toHaveAttribute("aria-hidden", "true");
    expect(gear).toHaveAttribute("stroke-width", "2.25"); // weight-matched to the solid bell
    // same geometry as the sidebar's Settings row (lucide-react's Settings)
    const { container: ref } = render(<Settings />);
    expect(Array.from(gear!.children).map((n) => n.outerHTML.replace(/ (key|class)="[^"]*"/g, "")))
      .toEqual(Array.from(ref.querySelector("svg")!.children).map((n) => n.outerHTML.replace(/ (key|class)="[^"]*"/g, "")));
    // no trace of the old polygon
    expect(link!.innerHTML).not.toContain("m9 1 1 3h4");
  });
});

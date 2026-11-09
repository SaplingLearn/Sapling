// @vitest-environment jsdom
import React from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { ShellActions } from "./ShellActions";

vi.mock("next/navigation", () => ({ usePathname: () => "/settings/connections" }));
vi.mock("./ReportIssueFlow", () => ({
  ReportIssueFlow: ({ onClose }: { onClose: () => void }) => (
    <div role="dialog" aria-label="Report an issue"><button onClick={onClose}>Close</button></div>
  ),
}));

afterEach(cleanup);

describe("ShellActions", () => {
  it("links to settings and marks nested settings routes active", () => {
    render(<ShellActions />);
    expect(screen.getByRole("link", { name: "Settings" }).getAttribute("href")).toBe("/settings");
    expect(screen.getByRole("link", { name: "Settings" }).getAttribute("aria-current")).toBe("page");
  });

  it("opens the report outside the header stacking context and closes it", () => {
    const { container } = render(<ShellActions />);
    fireEvent.click(screen.getByRole("button", { name: "Report an issue" }));
    const dialog = screen.getByRole("dialog", { name: "Report an issue" });
    expect(document.body.contains(dialog)).toBe(true);
    expect(container.contains(dialog)).toBe(false);
    fireEvent.click(screen.getByRole("button", { name: "Close" }));
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("keeps both icon controls named for keyboard and screen reader users", () => {
    render(<ShellActions />);
    expect(screen.getByRole("link", { name: "Settings" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Report an issue" })).toBeTruthy();
    expect(screen.queryByText("Settings")).toBeNull();
    expect(screen.queryByText("Report")).toBeNull();
  });

  it("reveals the Settings label on hover without adding it to the button", async () => {
    render(<ShellActions />);
    const settings = screen.getByRole("link", { name: "Settings" });
    fireEvent.mouseEnter(settings.parentElement!);
    expect((await screen.findByRole("tooltip")).textContent).toBe("Settings");
    expect(settings.textContent?.trim()).toBe("");
    fireEvent.mouseLeave(settings.parentElement!);
    expect(screen.queryByRole("tooltip")).toBeNull();
  });

  it("reveals Report on keyboard focus and dismisses it with Escape", () => {
    render(<ShellActions />);
    const report = screen.getByRole("button", { name: "Report an issue" });
    fireEvent.focus(report);
    expect(screen.getByRole("tooltip").textContent).toBe("Report");
    fireEvent.keyDown(report, { key: "Escape" });
    expect(screen.queryByRole("tooltip")).toBeNull();
  });
});

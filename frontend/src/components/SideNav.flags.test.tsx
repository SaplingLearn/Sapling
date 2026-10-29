// @vitest-environment jsdom
/**
 * SideNav × hide_* feature flags (#620): a hidden destination renders no row,
 * a section emptied by flags drops its header, and flagged rows wait for the
 * flags to load. (TopNav renders the same `useVisibleNavSections` list.)
 */
import React from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, render, screen } from "@testing-library/react";

vi.mock("next/navigation", () => ({ usePathname: () => "/dashboard" }));
vi.mock("@/context/UserContext", () => ({
  useUser: () => ({ userName: "Andres", avatarUrl: null, isAdmin: false, isAuthenticated: true }),
}));
vi.mock("next/link", () => ({
  default: ({ href, children, ...rest }: React.ComponentPropsWithoutRef<"a">) => (
    <a href={href} {...rest}>{children}</a>
  ),
}));
vi.mock("./Avatar", () => ({ Avatar: () => null }));
vi.mock("./Icon", () => ({ Icon: () => null }));
let flagState: { flags: Record<string, string>; ready: boolean } = { flags: {}, ready: true };
vi.mock("@/context/FlagsContext", () => ({ useFlagMap: () => flagState }));

import { SideNav } from "./SideNav";

function renderRail() {
  act(() => { render(<SideNav />); });
}

describe("SideNav hide_* flags", () => {
  beforeEach(() => { flagState = { flags: {}, ready: true }; });
  afterEach(() => cleanup());

  it("shows every destination when no flag is on", () => {
    renderRail();
    for (const r of ["dashboard", "learn", "quiz", "course-planner"]) {
      expect(screen.getByTestId(`nav-link-${r}`)).toBeTruthy();
    }
  });

  it("drops a hidden destination and keeps the rest", () => {
    flagState = { flags: { hide_quiz: "on", hide_tree: "off" }, ready: true };
    renderRail();
    expect(screen.queryByTestId("nav-link-quiz")).toBeNull();
    expect(screen.getByTestId("nav-link-tree")).toBeTruthy();
  });

  it("drops a section's header when all its destinations are hidden", () => {
    flagState = { flags: { hide_social: "on", hide_achievements: "on" }, ready: true };
    renderRail();
    expect(screen.queryByText("Community")).toBeNull();
    expect(screen.getByText("Organize")).toBeTruthy();
  });

  it("holds flagged destinations back until flags load; Settings stays", () => {
    flagState = { flags: {}, ready: false };
    renderRail();
    expect(screen.getByTestId("nav-link-dashboard")).toBeTruthy();
    expect(screen.getByTestId("nav-link-settings")).toBeTruthy();
    expect(screen.queryByTestId("nav-link-quiz")).toBeNull();
    expect(screen.queryByTestId("nav-link-learn")).toBeNull();
  });
});

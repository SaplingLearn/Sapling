// @vitest-environment jsdom
/**
 * Spec §13 A126: the "retention check due" mark on the Study nav entry — the
 * side rail (wide and narrow) and the top nav (its Learn group, the Study row,
 * the mobile menu) — shown only while the shell's one read says a check is due.
 */
import React from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";

const nav = vi.hoisted(() => ({ due: false, mobile: false }));
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
vi.mock("./ShellActions", () => ({ ShellActions: () => null }));
vi.mock("@/lib/useIsMobile", () => ({ useIsMobile: () => nav.mobile }));
vi.mock("@/context/FlagsContext", () => ({ useFlagMap: () => ({ flags: {}, ready: true }) }));
vi.mock("@/context/RetentionDueContext", () => ({
  useRetentionDue: () => ({ due: nav.due, courseIds: nav.due ? ["c1"] : [], refresh: () => {} }),
}));

import { SideNav } from "./SideNav";
import { TopNav } from "./TopNav";

describe("the retention-due mark", () => {
  beforeEach(() => { nav.due = false; nav.mobile = false; });
  afterEach(() => cleanup());

  it("marks the side rail's Study entry only while a check is due", () => {
    act(() => { render(<SideNav />); });
    expect(screen.queryByTestId("nav-retention-due")).toBeNull();
    cleanup();
    nav.due = true;
    act(() => { render(<SideNav />); });
    const study = screen.getByTestId("nav-link-study");
    expect(study.querySelector('[data-testid="nav-retention-due"]')).toBeTruthy();
    expect(study.getAttribute("aria-label")).toBe("Study, retention check due");
    expect(screen.getAllByTestId("nav-retention-due")).toHaveLength(1); // Study alone
    expect(screen.getByTestId("nav-link-dashboard").getAttribute("aria-label")).toBeNull();
  });

  it("marks the top nav's Learn group and its Study row", () => {
    nav.due = true;
    act(() => { render(<TopNav />); });
    expect(screen.getAllByTestId("topnav-group-retention-due")).toHaveLength(1);
    fireEvent.click(screen.getByRole("button", { name: /Learn/ }));
    expect(screen.getByTestId("topnav-retention-due")).toBeTruthy();
  });

  it("marks the closed mobile menu, then the Study row inside it", () => {
    nav.due = true;
    nav.mobile = true;
    act(() => { render(<TopNav />); });
    const menu = screen.getByRole("button", { name: "Navigation menu, retention check due" });
    expect(screen.getByTestId("topnav-menu-retention-due")).toBeTruthy();
    fireEvent.click(menu);
    expect(screen.getByTestId("topnav-mobile-retention-due")).toBeTruthy();
    expect(screen.queryByTestId("topnav-menu-retention-due")).toBeNull();
  });

  it("shows nothing in the top nav while nothing is due", () => {
    act(() => { render(<TopNav />); });
    expect(screen.queryByTestId("topnav-group-retention-due")).toBeNull();
    expect(screen.getByRole("button", { name: /Learn/ })).toBeTruthy();
  });
});

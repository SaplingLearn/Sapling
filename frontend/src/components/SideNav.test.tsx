// @vitest-environment jsdom
/**
 * Component tests for SideNav — the authenticated app-shell rail.
 *
 * These lock the structural + accessibility invariants the rail's spacing
 * pass is allowed to move within, not the exact pixel values:
 *   1. Every destination renders, grouped under its 4 section labels
 *   2. Nav rows never drop below the 36px interactive floor — in BOTH the
 *      expanded and collapsed states (the whole point of the density pass)
 *   3. The single foot rule sits ABOVE Settings, and the profile block
 *      carries no rule of its own
 *   4. Active is marked (weight + brand color), inactive is not
 *   5. Collapsed swaps section labels for separator rules and keeps the
 *      expand/collapse affordances and their aria-labels
 *
 * Module mocks mirror TopNav.test.tsx: next/navigation, next/link, useUser,
 * and the presentational Avatar/Icon are stubbed so the tests can drive route
 * + collapse state without standing up real context or the SVG sprite.
 */

import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, cleanup, act } from "@testing-library/react";

vi.mock("next/navigation", () => ({
  usePathname: vi.fn(() => "/dashboard"),
}));

const mockUser = {
  userName: "Andres",
  avatarUrl: null as string | null,
  isAdmin: false,
  isAuthenticated: true,
};

vi.mock("@/context/UserContext", () => ({
  useUser: () => mockUser,
}));

vi.mock("next/link", () => ({
  default: ({ href, children, ...rest }: React.ComponentPropsWithoutRef<"a">) => (
    <a href={href} {...rest}>
      {children}
    </a>
  ),
}));

vi.mock("./Avatar", () => ({
  Avatar: ({ name }: { name: string }) => <span data-testid="avatar">{name}</span>,
}));
vi.mock("./Icon", () => ({
  Icon: ({ name }: { name: string }) => <span data-testid={`icon-${name}`} />,
}));

import { SideNav, SIDE_NAV_EXPANDED, SIDE_NAV_COLLAPSED } from "./SideNav";
import { usePathname } from "next/navigation";

const mockedUsePathname = vi.mocked(usePathname);

const COLLAPSE_KEY = "sapling_sidenav_collapsed";

/** The rail reads its collapse pref from localStorage in an effect, so the
 *  pref has to be in place BEFORE render for the collapsed-state tests. */
function renderRail(collapsed = false) {
  window.localStorage.setItem(COLLAPSE_KEY, collapsed ? "1" : "0");
  act(() => {
    render(<SideNav />);
  });
  return document.querySelector("[data-app-sidenav]") as HTMLElement;
}

/** Every nav row is an <a> inside the rail. The logo is the one <a> that is
 *  not a nav row (it keeps its aria-label in both states, so filter on that
 *  rather than on text — the wordmark is dropped when collapsed). */
function navRows(rail: HTMLElement): HTMLElement[] {
  return Array.from(rail.querySelectorAll("a")).filter(
    (a) => a.getAttribute("aria-label") !== "Sapling — home",
  ) as HTMLElement[];
}

beforeEach(() => {
  mockedUsePathname.mockReturnValue("/dashboard");
  mockUser.isAdmin = false;
  mockUser.isAuthenticated = true;
  window.localStorage.clear();
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("SideNav — structure", () => {
  it("exposes the two shell widths ShellFrame lays out against", () => {
    expect(SIDE_NAV_EXPANDED).toBe(232);
    expect(SIDE_NAV_COLLAPSED).toBe(64);
  });

  it("keeps the data-app-sidenav hook the pre-hydration mobile guard keys on", () => {
    const rail = renderRail();
    expect(rail).toBeTruthy();
    expect(rail.getAttribute("aria-label")).toBe("Primary");
    expect(rail.getAttribute("role")).toBe("navigation");
  });

  it("renders the 4 section labels and every destination", () => {
    renderRail();
    for (const label of ["Learn", "Organize", "Community", "Tools"]) {
      expect(screen.getByText(label)).toBeTruthy();
    }
    for (const item of ["Dashboard", "Tutor", "Quiz", "Tree", "Study", "Library", "Calendar", "Social", "Achievements", "Grades", "Notetaker", "Course Planner", "Settings"]) {
      expect(screen.getByText(item)).toBeTruthy();
    }
    // Admin is gated on the flag.
    expect(screen.queryByText("Admin")).toBeNull();
  });
});

describe("SideNav — interactive row height floor", () => {
  // 44px is the WCAG comfort target; 36px is the floor this dense desktop
  // rail is allowed to sit at. A future tightening pass must not cross it.
  const MIN_HIT_TARGET = 36;

  it("keeps every expanded nav row at or above the 36px floor", () => {
    const rail = renderRail(false);
    const rows = navRows(rail);
    expect(rows.length).toBeGreaterThan(0);
    for (const row of rows) {
      const min = parseFloat(row.style.minHeight || "0");
      expect(min).toBeGreaterThanOrEqual(MIN_HIT_TARGET);
    }
  });

  it("keeps every collapsed nav row at or above the 36px floor", () => {
    const rail = renderRail(true);
    for (const row of navRows(rail)) {
      const min = parseFloat(row.style.minHeight || "0");
      expect(min).toBeGreaterThanOrEqual(MIN_HIT_TARGET);
    }
  });
});

describe("SideNav — the foot rule", () => {
  it("puts the rule immediately above Settings, not on the profile block", () => {
    const rail = renderRail();
    const settings = screen.getByText("Settings").closest("a")!;
    const rule = settings.previousElementSibling as HTMLElement;
    expect(rule).toBeTruthy();
    expect(rule.getAttribute("aria-hidden")).toBe("true");
    expect(rule.style.height).toBe("1px");

    // The profile block (the one holding the avatar) owns no rule of its own.
    const profile = screen.getByTestId("avatar").closest("div[style]")!;
    let node: HTMLElement | null = profile as HTMLElement;
    while (node && node !== rail) {
      expect(node.style.borderTop).toBe("");
      node = node.parentElement;
    }
  });

  it("keeps Admin below the same single rule when the user is an admin", () => {
    mockUser.isAdmin = true;
    renderRail();
    const settings = screen.getByText("Settings").closest("a")!;
    const admin = screen.getByText("Admin").closest("a")!;
    // Admin follows Settings directly — no second rule between them.
    expect(settings.nextElementSibling).toBe(admin);
    // And the rule is above the pair, not inside it.
    expect((settings.previousElementSibling as HTMLElement).style.height).toBe("1px");
  });
});

describe("SideNav — active vs inactive", () => {
  it("marks only the current route", () => {
    mockedUsePathname.mockReturnValue("/quiz");
    renderRail();
    const quiz = screen.getByText("Quiz").closest("a")!;
    const tree = screen.getByText("Tree").closest("a")!;

    // The selected row is a plain fill in the green scale; an unselected one
    // has no background at all. Asserting the TOKEN rather than a computed
    // colour keeps this honest if the scale is retuned.
    expect(quiz.getAttribute("style") || "").toMatch(/font-weight:\s*600/);
    expect(quiz.getAttribute("style") || "").toMatch(/--sap-100/);
    expect(tree.getAttribute("style") || "").toMatch(/font-weight:\s*400/);
    expect(tree.getAttribute("style") || "").not.toMatch(/--sap-100/);
  });

  it("treats / and /dashboard/... as the Dashboard route", () => {
    mockedUsePathname.mockReturnValue("/");
    renderRail();
    const dashboard = screen.getByText("Dashboard").closest("a")!;
    expect(dashboard.getAttribute("style") || "").toMatch(/font-weight:\s*600/);
  });
});

describe("SideNav — collapsed state", () => {
  it("drops the section labels for separator rules and keeps the expand affordance", () => {
    const rail = renderRail(true);

    // Labels are gone in the narrow rail...
    expect(screen.queryByText("Learn")).toBeNull();
    expect(screen.queryByText("Tools")).toBeNull();
    // ...replaced by hairlines: 3 group boundaries + the foot rule.
    const rules = Array.from(rail.querySelectorAll<HTMLElement>("[aria-hidden]")).filter(
      (el) => el.style.height === "1px",
    );
    expect(rules).toHaveLength(4);

    expect(screen.getByRole("button", { name: "Expand sidebar" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Collapse sidebar" })).toBeNull();
    // Each row still carries its label as an accessible name.
    expect(screen.getByRole("link", { name: "Settings" })).toBeTruthy();
  });

  it("shows the collapse affordance when expanded", () => {
    renderRail(false);
    expect(screen.getByRole("button", { name: "Collapse sidebar" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Expand sidebar" })).toBeNull();
  });
});

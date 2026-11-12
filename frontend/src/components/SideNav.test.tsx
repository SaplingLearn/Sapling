// @vitest-environment jsdom
/**
 * Component tests for SideNav — the authenticated app-shell rail.
 *
 * These lock the structural + accessibility invariants the rail's spacing
 * pass is allowed to move within, not the exact pixel values:
 *   1. Every destination renders, grouped under its 4 section labels
 *   2. Nav rows never drop below the 36px interactive floor — in BOTH the
 *      expanded and collapsed states (the whole point of the density pass)
 *   3. The single foot rule sits ABOVE the account controls, and the profile block
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
import { render, screen, cleanup, act, within } from "@testing-library/react";

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
// Destination rows only: the logo and the account block (the Settings button
// in the footer) are links too, but neither is a nav row.
const isNavRow = (a: Element) =>
  a.getAttribute("aria-label") !== "Sapling — home" &&
  a.getAttribute("data-testid") !== "nav-link-settings";

function navRows(rail: HTMLElement): HTMLElement[] {
  return Array.from(rail.querySelectorAll("a")).filter(isNavRow) as HTMLElement[];
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
    expect(SIDE_NAV_EXPANDED).toBe(200);
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
    for (const item of ["Dashboard", "Tutor", "Tree", "Study", "Library", "Calendar", "Social", "Achievements", "Grades", "Notetaker", "Course Planner"]) {
      expect(screen.getByText(item)).toBeTruthy();
    }
    expect(screen.queryByRole("link", { name: "Quiz" })).toBeNull();
    // Admin is gated on the flag.
    expect(screen.queryByText("Admin")).toBeNull();
  });
});

describe("SideNav — interactive row height floor", () => {
  // 44px is the WCAG comfort target; 36px is the floor this dense desktop
  // rail is allowed to sit at. A future tightening pass must not cross it.
  const MIN_HIT_TARGET = 36;

  /**
   * The smallest height a row can ever resolve to.
   *
   * The rail's rows are sized `clamp(36px, 4.3vh, 38px)` so they hold their
   * pitch on a tall window and give it up on a short one. jsdom does no
   * viewport maths, so the style is read back as that literal string, and a
   * bare `parseFloat` on it is NaN — which fails this check for the wrong
   * reason while a genuine regression below the floor would fail it for the
   * right one, indistinguishably.
   *
   * A clamp's first argument IS its floor, so that is what gets asserted.
   * This deliberately reads the smallest possible value rather than the one a
   * particular viewport would produce: the invariant is that no window, however
   * short, can push a row under 36px.
   */
  function smallestHeight(minHeight: string): number {
    const clamped = minHeight.match(/^\s*clamp\(\s*([\d.]+)px/);
    return parseFloat(clamped ? clamped[1] : minHeight || "0");
  }

  it("keeps every expanded nav row at or above the 36px floor", () => {
    const rail = renderRail(false);
    const rows = navRows(rail);
    expect(rows.length).toBeGreaterThan(0);
    for (const row of rows) {
      const min = smallestHeight(row.style.minHeight);
      // Guards the helper itself: an unparseable value must fail loudly here
      // rather than slip through as a NaN comparison below.
      expect(Number.isFinite(min)).toBe(true);
      expect(min).toBeGreaterThanOrEqual(MIN_HIT_TARGET);
    }
  });

  it("keeps every collapsed nav row at or above the 36px floor", () => {
    const rail = renderRail(true);
    for (const row of navRows(rail)) {
      const min = smallestHeight(row.style.minHeight);
      expect(Number.isFinite(min)).toBe(true);
      expect(min).toBeGreaterThanOrEqual(MIN_HIT_TARGET);
    }
  });
});

describe("SideNav — the logo", () => {
  const symbolOf = (rail: HTMLElement) =>
    rail.querySelector<HTMLElement>("[data-sidenav-symbol]")!;

  it("shows the wordmark wide and the Sapling symbol narrow, both as a live home link", () => {
    let rail = renderRail(false);
    let home = screen.getByRole("link", { name: "Sapling — home" });
    expect(home.getAttribute("href")).toBe("/dashboard");
    expect(symbolOf(rail).style.opacity).toBe("0");
    cleanup();
    rail = renderRail(true);
    home = screen.getByRole("link", { name: "Sapling — home" });
    expect(symbolOf(rail).style.opacity).toBe("1");
    expect(home.contains(symbolOf(rail))).toBe(true);
    // Reachable in the narrow rail too: it is the only logo left on screen.
    expect(home.getAttribute("tabindex")).toBeNull();
    expect(home.style.pointerEvents).toBe("");
  });
});

describe("SideNav — the account footer", () => {
  const footerOf = (rail: HTMLElement) =>
    rail.querySelector<HTMLElement>("[data-sidenav-footer]")!;

  it("makes the whole account block the Settings button", () => {
    const rail = renderRail();
    const settings = screen.getByRole("link", { name: "Settings" });
    expect(settings.getAttribute("href")).toBe("/settings");
    expect(footerOf(rail).contains(settings)).toBe(true);
    // The avatar is inside the link, not beside it.
    expect(settings.contains(screen.getByTestId("avatar"))).toBe(true);
  });

  it("opens the account footer with one full-width rule", () => {
    const rail = renderRail();
    const footer = footerOf(rail);
    expect(footer.style.borderTop).toBe("1px solid var(--border)");

    // The profile block (the one holding the avatar) owns no rule of its own.
    let node: HTMLElement | null = screen.getByTestId("avatar").closest("div[style]");
    while (node && node !== footer) {
      expect(node.style.borderTop).toBe("");
      node = node.parentElement;
    }
    expect(node).toBe(footer);
  });

  it("keeps Admin below the same single rule when the user is an admin", () => {
    mockUser.isAdmin = true;
    const rail = renderRail();
    const admin = screen.getByText("Admin").closest("a")!;
    // Collapse opens the footer; Admin follows it, under the same rule.
    expect(footerOf(rail).firstElementChild?.nextElementSibling).toBe(admin);
    expect(admin.parentElement).toBe(footerOf(rail));
  });

  it("puts the collapse toggle just under the footer rule in both widths", () => {
    let rail = renderRail(false);
    const collapse = screen.getByRole("button", { name: "Collapse sidebar" });
    expect(footerOf(rail).firstElementChild).toBe(collapse);
    // Wide rail: a labelled row. Narrow rail: the chevron alone (the label
    // stays mounted so it can fade, but is invisible and aria-hidden).
    const collapseLabel = within(collapse).getByText("Collapse");
    expect(collapseLabel.style.opacity).toBe("1");
    cleanup();
    rail = renderRail(true);
    const expand = screen.getByRole("button", { name: "Expand sidebar" });
    expect(footerOf(rail).firstElementChild).toBe(expand);
    expect(within(expand).getByText("Collapse").style.opacity).toBe("0");
  });

  it("pins the footer and scrolls only the destinations, scrollbar hidden", () => {
    const rail = renderRail();
    expect(rail.style.overflow).toBe("hidden");
    const scroller = rail.querySelector<HTMLElement>("[data-sidenav-scroll]")!;
    expect(scroller.style.overflowY).toBe("auto");
    expect(scroller.getAttribute("style") || "").toMatch(/scrollbar-width:\s*none/);
    expect(scroller.contains(screen.getByText("Tutor"))).toBe(true);
    expect(scroller.contains(footerOf(rail))).toBe(false);
  });
});

describe("SideNav — active vs inactive", () => {
  it("marks Study active while a quiz is open", () => {
    mockedUsePathname.mockReturnValue("/quiz");
    renderRail();
    const study = screen.getByText("Study").closest("a")!;
    const tree = screen.getByText("Tree").closest("a")!;

    // The selected row is a plain neutral fill in the ink scale; an unselected one
    // has no background at all. Asserting the TOKEN rather than a computed
    // colour keeps this honest if the scale is retuned.
    expect(study.getAttribute("style") || "").toMatch(/font-weight:\s*600/);
    expect(study.getAttribute("style") || "").toMatch(/--bg-soft/);
    expect(tree.getAttribute("style") || "").toMatch(/font-weight:\s*400/);
    expect(tree.getAttribute("style") || "").not.toMatch(/--bg-soft/);
  });

  it.each(["/flashcards", "/flashcards/deck-1", "/study/guide"])(
    "marks Study active on %s, a Study page",
    (path) => {
      mockedUsePathname.mockReturnValue(path);
      renderRail();
      const study = screen.getByText("Study").closest("a")!;
      expect(study.getAttribute("style") || "").toMatch(/font-weight:\s*600/);
      expect(study.getAttribute("style") || "").toMatch(/--bg-soft/);
    },
  );

  it("treats / and /dashboard/... as the Dashboard route", () => {
    mockedUsePathname.mockReturnValue("/");
    renderRail();
    const dashboard = screen.getByText("Dashboard").closest("a")!;
    expect(dashboard.getAttribute("style") || "").toMatch(/font-weight:\s*600/);
  });
});

describe("SideNav — collapsed state", () => {
  it("centres rows by padding, never justify-content, so the move can tween", () => {
    const rows = () =>
      Array.from(document.querySelectorAll<HTMLElement>("[data-app-sidenav] a[href^='/']"))
        .filter(isNavRow);
    renderRail(false);
    for (const r of rows()) {
      expect(r.style.justifyContent).toBe("");
      expect(r.style.marginLeft).toBe("0px");
      expect(r.style.paddingLeft).toBe("12px");
      expect(r.style.transition).toMatch(/padding/);
    }
    cleanup();
    renderRail(true);
    // 64px rail − 2×6px padding = 52px; a 15px icon centred → 18.5px.
    for (const r of rows()) {
      expect(r.style.justifyContent).toBe("");
      expect(r.style.marginLeft).toBe("0px");
      expect(r.style.paddingLeft).toBe("18.5px");
    }
  });

  it("drops the section labels for separator rules and keeps the expand affordance", () => {
    const rail = renderRail(true);

    // Labels stay mounted so the collapse can fade them, but in the narrow
    // rail they are invisible and hidden from assistive tech...
    for (const label of ["Learn", "Tools"]) {
      const el = screen.getByText(label);
      expect(el.style.opacity).toBe("0");
      expect(el.closest("[aria-hidden='true']")).toBeTruthy();
    }
    // ...and a hairline shows at each of the 3 group boundaries instead; the
    // footer keeps its own border-top rule in the narrow state too.
    const rules = Array.from(rail.querySelectorAll<HTMLElement>("[data-sidenav-group-rule]"));
    expect(rules).toHaveLength(3);
    for (const r of rules) expect(r.style.opacity).toBe("1");
    expect(rail.querySelector<HTMLElement>("[data-sidenav-footer]")!.style.borderTop).toBe(
      "1px solid var(--border)",
    );

    expect(screen.getByRole("button", { name: "Expand sidebar" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Collapse sidebar" })).toBeNull();
    // Each row still carries its label as an accessible name.
    expect(screen.getByRole("link", { name: "Dashboard" })).toBeTruthy();
  });

  it("shows the collapse affordance when expanded", () => {
    renderRail(false);
    expect(screen.getByRole("button", { name: "Collapse sidebar" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Expand sidebar" })).toBeNull();
  });
});

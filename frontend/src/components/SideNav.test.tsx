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

describe("SideNav — the account footer", () => {
  const footerOf = (rail: HTMLElement) =>
    rail.querySelector<HTMLElement>("[data-sidenav-footer]")!;

  it("opens the footer with one full-width rule directly above Settings", () => {
    const rail = renderRail();
    const footer = footerOf(rail);
    expect(footer.style.borderTop).toBe("1px solid var(--border)");
    // Settings is the footer's first row: nothing sits between it and the rule.
    expect(footer.firstElementChild).toBe(screen.getByText("Settings").closest("a"));

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
    const settings = screen.getByText("Settings").closest("a")!;
    const admin = screen.getByText("Admin").closest("a")!;
    // Admin follows Settings directly — no second rule between them.
    expect(settings.nextElementSibling).toBe(admin);
    expect(admin.parentElement).toBe(footerOf(rail));
  });

  it("puts the collapse toggle directly above the footer rule in both widths", () => {
    let rail = renderRail(false);
    const collapse = screen.getByRole("button", { name: "Collapse sidebar" });
    expect(footerOf(rail).previousElementSibling).toBe(collapse);
    // Wide rail: a labelled row. Narrow rail: the chevron alone (the label
    // stays mounted so it can fade, but is invisible and aria-hidden).
    const collapseLabel = within(collapse).getByText("Collapse");
    expect(collapseLabel.style.opacity).toBe("1");
    cleanup();
    rail = renderRail(true);
    const expand = screen.getByRole("button", { name: "Expand sidebar" });
    expect(footerOf(rail).previousElementSibling).toBe(expand);
    expect(within(expand).getByText("Collapse").style.opacity).toBe("0");
  });

  it("pins the footer and scrolls only the destinations, scrollbar hidden", () => {
    const rail = renderRail();
    expect(rail.style.overflow).toBe("hidden");
    const scroller = rail.querySelector<HTMLElement>("[data-sidenav-scroll]")!;
    expect(scroller.style.overflowY).toBe("auto");
    expect(scroller.getAttribute("style") || "").toMatch(/scrollbar-width:\s*none/);
    expect(scroller.contains(screen.getByText("Quiz"))).toBe(true);
    expect(scroller.contains(footerOf(rail))).toBe(false);
  });
});

describe("SideNav — active vs inactive", () => {
  it("marks only the current route", () => {
    mockedUsePathname.mockReturnValue("/quiz");
    renderRail();
    const quiz = screen.getByText("Quiz").closest("a")!;
    const tree = screen.getByText("Tree").closest("a")!;

    // The selected row is a plain neutral fill in the ink scale; an unselected one
    // has no background at all. Asserting the TOKEN rather than a computed
    // colour keeps this honest if the scale is retuned.
    expect(quiz.getAttribute("style") || "").toMatch(/font-weight:\s*600/);
    expect(quiz.getAttribute("style") || "").toMatch(/--bg-soft/);
    expect(tree.getAttribute("style") || "").toMatch(/font-weight:\s*400/);
    expect(tree.getAttribute("style") || "").not.toMatch(/--bg-soft/);
  });

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
        .filter((a) => a.getAttribute("aria-label") !== "Sapling — home");
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
    expect(screen.getByRole("link", { name: "Settings" })).toBeTruthy();
  });

  it("shows the collapse affordance when expanded", () => {
    renderRail(false);
    expect(screen.getByRole("button", { name: "Collapse sidebar" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Expand sidebar" })).toBeNull();
  });
});

describe("SideNav — /font-lab override", () => {
  const FONT_LAB_KEY = "sapling_font_lab_selection_v1";

  // jsdom's CSSStyleDeclaration normalizes the quoting on a font-family
  // string (single quotes in, double quotes out) — the assertions below
  // match that normalized form, not the literal source string.
  it("is a no-op for everyone who has never opened /font-lab", () => {
    const rail = renderRail();
    const logo = screen.getByText("Sapling");
    expect(logo.style.fontFamily).toBe('"Spectral", Georgia, serif');
    const group = rail.querySelector<HTMLElement>(".label-micro")!;
    expect(group.style.fontFamily).toBe("");
    expect(rail.style.fontFamily).toBe("");
  });

  it("applies a stored pick to the real rail once /font-lab has written one", () => {
    window.localStorage.setItem(
      FONT_LAB_KEY,
      JSON.stringify({ heading: "Besley", body: "DM Sans", label: "Fragment Mono", subtitle: "DM Sans" }),
    );
    const rail = renderRail();
    const logo = screen.getByText("Sapling");
    expect(logo.style.fontFamily).toBe('"Besley", serif');
    expect(logo.style.fontWeight).toBe("700"); // Besley's own previewWeight, not a hardcoded 700.
    const group = rail.querySelector<HTMLElement>(".label-micro")!;
    expect(group.style.fontFamily).toBe('"Fragment Mono", monospace');
    // body and subtitle both matched the shipped default, so neither role
    // is treated as "overridden" and the rail keeps inheriting its normal stack.
    expect(rail.style.fontFamily).toBe("");
  });

  // A candidate is picked for its whole look, not just its family name — a
  // bold label face rendered exactly as thin as the shipped default until
  // `fontWeight` was threaded through the override too (same bug hid
  // subtitle's italic candidates behind `fontStyle`).
  it("carries a candidate's own weight and italic, not just its family", () => {
    window.localStorage.setItem(
      FONT_LAB_KEY,
      JSON.stringify({ heading: "Spectral", body: "DM Sans", label: "Anonymous Pro", subtitle: "Piazzolla" }),
    );
    const rail = renderRail();
    const group = rail.querySelector<HTMLElement>(".label-micro")!;
    expect(group.style.fontFamily).toBe('"Anonymous Pro", monospace');
    expect(group.style.fontWeight).toBe("700"); // Anonymous Pro's previewWeight — was silently dropped to normal.
    const subtitle = screen.getByText("Account");
    expect(subtitle.style.fontFamily).toBe('"Piazzolla", serif');
    expect(subtitle.style.fontStyle).toBe("italic"); // Piazzolla's italic flag — was silently dropped to upright.
  });

  it("ignores an unparsable value instead of throwing", () => {
    window.localStorage.setItem(FONT_LAB_KEY, "{not json");
    const rail = renderRail();
    expect(screen.getByText("Sapling").style.fontFamily).toBe('"Spectral", Georgia, serif');
    expect(rail).toBeTruthy();
  });
});

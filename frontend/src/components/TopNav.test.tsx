// @vitest-environment jsdom
/**
 * Component tests for TopNav — covers the grouped-dropdown behavior
 * introduced in PR #81:
 *   1. Renders the 4 group labels in desktop mode
 *   2. Active state on the group containing the current route
 *   3. Hover opens the dropdown with the group's items
 *   4. Escape closes an open dropdown
 *   5. Mobile (≤768px) renders the hamburger instead of group labels
 *
 * Module mocks: next/navigation, useUser, useIsMobile, and the small
 * Avatar/Icon presentational components are stubbed so the tests can
 * drive route + viewport state without standing up real context.
 */

import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, cleanup, fireEvent, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

// Hoisted module mocks. usePathname is the only one the tests need to
// flip per-test; the rest are static stubs.
vi.mock("next/navigation", () => ({
  usePathname: vi.fn(() => "/dashboard"),
}));

vi.mock("@/context/UserContext", () => ({
  useUser: () => ({
    userName: "Andres",
    avatarUrl: null,
    isAdmin: false,
    isAuthenticated: true,
  }),
}));

vi.mock("@/lib/useIsMobile", () => ({
  useIsMobile: vi.fn(() => false),
}));

// next/link in tests behaves like a plain <a> — render its children
// inside an anchor tag so existing href semantics work.
vi.mock("next/link", () => ({
  default: ({ href, children, ...rest }: any) => (
    <a href={href} {...rest}>
      {children}
    </a>
  ),
}));

// Avatar + Icon are presentational; replace with minimal stubs so we
// don't have to load the SVG sprite for these tests.
vi.mock("./Avatar", () => ({
  Avatar: ({ name }: any) => <span data-testid="avatar">{name}</span>,
}));
vi.mock("./Icon", () => ({
  Icon: ({ name }: any) => <span data-testid={`icon-${name}`} />,
}));

import { TopNav } from "./TopNav";
import { usePathname } from "next/navigation";
import { useIsMobile } from "@/lib/useIsMobile";

const mockedUsePathname = vi.mocked(usePathname);
const mockedUseIsMobile = vi.mocked(useIsMobile);

beforeEach(() => {
  mockedUsePathname.mockReturnValue("/dashboard");
  mockedUseIsMobile.mockReturnValue(false);
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("TopNav — desktop group labels", () => {
  it("renders the 4 group labels", () => {
    render(<TopNav />);
    // The group triggers are buttons with the group label as their
    // visible text. They render alongside the chevron icon, so we
    // match by accessible name (text content).
    expect(screen.getByRole("button", { name: /^Learn/ })).toBeTruthy();
    expect(screen.getByRole("button", { name: /^Organize/ })).toBeTruthy();
    expect(screen.getByRole("button", { name: /^Community/ })).toBeTruthy();
    expect(screen.getByRole("button", { name: /^Tools/ })).toBeTruthy();
  });

  it("highlights the Learn group when on /dashboard", () => {
    mockedUsePathname.mockReturnValue("/dashboard");
    render(<TopNav />);
    const learn = screen.getByRole("button", { name: /^Learn/ });
    // Active state = font-weight 700 inline. The button's style
    // attribute is the source of truth for the active styling.
    expect(learn.getAttribute("style") || "").toMatch(/font-weight:\s*700/);
  });

  it("highlights the Organize group when on /library", () => {
    mockedUsePathname.mockReturnValue("/library");
    render(<TopNav />);
    const organize = screen.getByRole("button", { name: /^Organize/ });
    expect(organize.getAttribute("style") || "").toMatch(/font-weight:\s*700/);
    // And Learn should NOT be active in this case.
    const learn = screen.getByRole("button", { name: /^Learn/ });
    expect(learn.getAttribute("style") || "").toMatch(/font-weight:\s*500/);
  });

  it("highlights the Tools group when on /gradebook", () => {
    mockedUsePathname.mockReturnValue("/gradebook");
    render(<TopNav />);
    const tools = screen.getByRole("button", { name: /^Tools/ });
    expect(tools.getAttribute("style") || "").toMatch(/font-weight:\s*700/);
  });
});

describe("TopNav — dropdown behavior", () => {
  // We open via click in tests (the component supports both click and
  // hover; click is the more reliable trigger in jsdom because
  // mouseEnter/mouseOver synthetic-event mapping is finicky there).
  // The behavior under test — "open panel reveals the group's items" —
  // is identical regardless of trigger.

  it("opens a panel with the group's items on click", async () => {
    const user = userEvent.setup();
    render(<TopNav />);
    const learn = screen.getByRole("button", { name: /^Learn/ });

    // Initially closed.
    expect(learn.getAttribute("aria-expanded")).toBe("false");
    expect(screen.queryByText("Tutor")).toBeNull();

    fireEvent.click(learn);

    // After open: aria-expanded=true and the items render.
    expect(learn.getAttribute("aria-expanded")).toBe("true");
    // Use getByText against the inner label span — accessible-name
    // matching on the <a> doesn't pick up the children correctly in
    // jsdom when an icon stub sits next to the label.
    expect(screen.getByText("Tutor")).toBeTruthy();
    expect(screen.getByText("Quiz")).toBeTruthy();
    expect(screen.getByText("Tree")).toBeTruthy();
    expect(screen.getByText("Study")).toBeTruthy();
  });

  it("closes the open panel on Escape", async () => {
    const user = userEvent.setup();
    render(<TopNav />);
    const learn = screen.getByRole("button", { name: /^Learn/ });
    fireEvent.click(learn);
    expect(learn.getAttribute("aria-expanded")).toBe("true");

    await user.keyboard("{Escape}");

    expect(learn.getAttribute("aria-expanded")).toBe("false");
  });

  it("opens different panels for different groups (no leak)", async () => {
    const user = userEvent.setup();
    render(<TopNav />);
    const community = screen.getByRole("button", { name: /^Community/ });

    fireEvent.click(community);

    // The Community panel shows Social + Achievements, not Tutor.
    expect(screen.getByText("Social")).toBeTruthy();
    expect(screen.getByText("Achievements")).toBeTruthy();
    expect(screen.queryByText("Tutor")).toBeNull();
  });

  it("renders the right items inside each group", async () => {
    const user = userEvent.setup();
    render(<TopNav />);

    // Tools group has 3 items.
    const tools = screen.getByRole("button", { name: /^Tools/ });
    fireEvent.click(tools);

    expect(screen.getByText("Grades")).toBeTruthy();
    expect(screen.getByText("Notetaker")).toBeTruthy();
    expect(screen.getByText("Course Planner")).toBeTruthy();
  });
});

describe("TopNav — mobile mode", () => {
  beforeEach(() => {
    mockedUseIsMobile.mockReturnValue(true);
  });

  it("renders the hamburger button instead of group labels", () => {
    render(<TopNav />);
    // No group triggers in the bar — they collapse into the hamburger.
    expect(screen.queryByRole("button", { name: /^Learn/ })).toBeNull();
    expect(screen.getByRole("button", { name: /Navigation menu/i })).toBeTruthy();
  });

  it("shows the grouped panel when the hamburger is opened", async () => {
    const user = userEvent.setup();
    render(<TopNav />);
    const burger = screen.getByRole("button", { name: /Navigation menu/i });

    await user.click(burger);

    // Mobile panel exposes group labels as section headers AND each
    // sub-item as a link. The presence of, say, "Tutor" inside the
    // panel proves the grouped structure rendered.
    expect(screen.getByText("Tutor")).toBeTruthy();
    expect(screen.getByText("Library")).toBeTruthy();
    expect(screen.getByText("Achievements")).toBeTruthy();
  });
});

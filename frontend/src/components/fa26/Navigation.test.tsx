// @vitest-environment jsdom
import React from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { Navigation, StudyNavigation } from "./Navigation";

const state = vi.hoisted(() => ({ pathname: "/learn", search: "", isAdmin: false }));
vi.mock("next/navigation", () => ({
  usePathname: () => state.pathname,
  useSearchParams: () => new URLSearchParams(state.search),
}));
vi.mock("@/context/UserContext", () => ({ useUser: () => ({ userName: "Sam Student", isAdmin: state.isAdmin }) }));
const flagState = vi.hoisted(() => ({ flags: {} as Record<string, string>, ready: true }));
vi.mock("@/context/FlagsContext", () => ({ useFlagMap: () => flagState }));
afterEach(() => {
  cleanup();
  state.pathname = "/learn";
  state.search = "";
  state.isAdmin = false;
  flagState.flags = {};
  flagState.ready = true;
});

describe("approved Pen sidebar", () => {
  it("renders the approved six destinations in order with the authored wordmark and icons", () => {
    render(<Navigation />);
    const primary = within(screen.getByRole("navigation", { name: "Primary" }));
    expect(primary.getAllByRole("link").map(link => [link.getAttribute("aria-label"), link.getAttribute("href")])).toEqual([
      ["Today", "/dashboard"], ["Learn", "/learn"], ["Knowledge", "/tree"],
      ["Library", "/library"], ["Tutor", "/learn?view=tutor"], ["Calendar", "/calendar"],
    ]);
    const wordmark = screen.getByRole("link", { name: "Sapling home" }).querySelector("img");
    expect(wordmark).toHaveAttribute("src", "/design/sapling/sapling-wordmark-approved.svg");
    expect(wordmark).toHaveAttribute("width", "150");
    expect(screen.getByText("Your workspace")).toBeTruthy();
    for (const [name, icon] of [["Today", "today"], ["Learn", "learn"], ["Library", "library"], ["Tutor", "tutor"], ["Calendar", "calendar"]]) {
      expect(primary.getByRole("link", { name }).querySelector(".sapling-icon")).toHaveAttribute("data-icon", icon);
    }
    expect(screen.getByRole("link", { name: "Knowledge" }).querySelector("svg")).toHaveClass("lucide-git-branch");
    expect(screen.getByRole("link", { name: "Settings" })).toHaveAttribute("href", "/settings");
  });

  it.each([
    ["", "Learn", "Tutor"],
    ["view=tutor", "Tutor", "Learn"],
    ["view=studio&resume=123", "Learn", "Tutor"],
  ])("uses the current /learn view as the sole selected destination (%s)", (search, selected, other) => {
    state.search = search;
    render(<Navigation />);
    expect(screen.getByRole("link", { name: selected })).toHaveAttribute("aria-current", "page");
    expect(screen.getByRole("link", { name: other })).not.toHaveAttribute("aria-current");
    expect(screen.getAllByRole("link").filter(link => link.getAttribute("aria-current") === "page")).toHaveLength(1);
  });

  it("does not treat a different path prefix as Learn", () => {
    state.pathname = "/learning";
    render(<Navigation />);
    expect(screen.getByRole("link", { name: "Learn" })).not.toHaveAttribute("aria-current");
    expect(screen.getByRole("link", { name: "Tutor" })).not.toHaveAttribute("aria-current");
  });

  it("keeps the current course and session when switching Learn and Tutor views", () => {
    state.search = "course=course-two&resume=session-two&view=tutor";
    render(<Navigation />);
    expect(screen.getByRole("link", { name: "Learn" })).toHaveAttribute("href", "/learn?course=course-two&resume=session-two");
    expect(screen.getByRole("link", { name: "Tutor" })).toHaveAttribute("href", "/learn?course=course-two&resume=session-two&view=tutor");
  });

  it("keeps all existing secondary tools reachable, moves focus inside, and restores it on Escape", () => {
    render(<Navigation />);
    const trigger = screen.getByRole("button", { name: "Account and more tools" });
    fireEvent.click(trigger);
    const tools = within(screen.getByRole("region", { name: "More tools" }));
    expect(tools.getByRole("link", { name: "Quiz" })).toHaveFocus();
    expect(tools.getAllByRole("link").map(link => [link.textContent, link.getAttribute("href")])).toEqual([
      ["Quiz", "/quiz"], ["Study guides", "/study?mode=guide"], ["Flashcards", "/study?mode=cards"],
      ["Notes", "/notetaker"], ["Grades", "/gradebook"], ["Course planner", "/course-planner"],
      ["Achievements", "/achievements"], ["Community", "/social"],
    ]);
    expect(screen.queryByRole("link", { name: "Admin" })).toBeNull();
    fireEvent.keyDown(document, { key: "Escape" });
    expect(trigger).toHaveFocus();
    expect(trigger).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByRole("region", { name: "More tools" })).toBeNull();
  });

  it("closes more tools on outside interaction and after choosing a destination", () => {
    render(<Navigation />);
    const trigger = screen.getByRole("button", { name: "Account and more tools" });
    fireEvent.click(trigger);
    fireEvent.pointerDown(document.body);
    expect(trigger).toHaveAttribute("aria-expanded", "false");
    fireEvent.click(trigger);
    fireEvent.click(screen.getByRole("link", { name: "Grades" }));
    expect(trigger).toHaveAttribute("aria-expanded", "false");
  });

  it("shows the admin destination only for admins", () => {
    state.isAdmin = true;
    render(<Navigation />);
    fireEvent.click(screen.getByRole("button", { name: "Account and more tools" }));
    expect(screen.getByRole("link", { name: "Admin" })).toHaveAttribute("href", "/admin");
  });

  it("applies hide_tutor to both Learn and the query-string Tutor destination", () => {
    flagState.flags = { hide_tutor: "on", hide_tree: "off" };
    render(<Navigation />);
    expect(screen.queryByTestId("nav-link-learn")).toBeNull();
    expect(screen.queryByTestId("nav-link-tutor")).toBeNull();
    expect(screen.getByTestId("nav-link-tree")).toHaveAttribute("href", "/tree");
  });

  it("applies feature flags to the account menu, including query-string study destinations", () => {
    flagState.flags = { hide_quiz: "on", hide_study: "on", hide_grades: "on", hide_notetaker: "on" };
    render(<Navigation />);
    fireEvent.click(screen.getByRole("button", { name: "Account and more tools" }));
    for (const id of ["quiz", "study", "flashcards", "gradebook", "notetaker"]) {
      expect(screen.queryByTestId(`nav-link-${id}`)).toBeNull();
    }
    expect(screen.getByTestId("nav-link-settings")).toBeTruthy();
    expect(screen.getByTestId("nav-link-course-planner")).toBeTruthy();
  });

  it("holds flagged destinations back until flags load while keeping Today and Settings", () => {
    flagState.ready = false;
    render(<Navigation />);
    expect(screen.getByTestId("nav-link-dashboard")).toBeTruthy();
    expect(screen.getByTestId("nav-link-settings")).toBeTruthy();
    for (const id of ["library", "learn", "tutor", "tree", "calendar"]) expect(screen.queryByTestId(`nav-link-${id}`)).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Account and more tools" }));
    expect(screen.queryByTestId("nav-link-study")).toBeNull();
    expect(screen.queryByTestId("nav-link-quiz")).toBeNull();
  });
});

describe("study navigation", () => {
  it("switches the study mode without discarding the mounted screen", () => {
    const select = vi.fn();
    render(<StudyNavigation active="guide" onSelect={select} />);
    expect(screen.getByRole("button", { name: "Study Guides" })).toHaveAttribute("aria-pressed", "true");
    fireEvent.click(screen.getByRole("button", { name: "Flashcards" }));
    expect(select).toHaveBeenCalledWith("cards");
    expect(screen.getByRole("link", { name: "Quiz" })).toHaveAttribute("href", "/quiz");
  });
});

// @vitest-environment jsdom
import React from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { Navigation, StudyNavigation } from "./Navigation";

const state = vi.hoisted(() => ({ pathname: "/study", isAdmin: false }));
vi.mock("next/navigation", () => ({ usePathname: () => state.pathname }));
vi.mock("@/context/UserContext", () => ({ useUser: () => ({ userName: "Sam Student", isAdmin: state.isAdmin }) }));
afterEach(() => { cleanup(); state.isAdmin = false; });

describe("FA26 navigation", () => {
  it("keeps Study selected for both flashcards and guides", () => {
    render(<Navigation />);
    expect(screen.getByRole("link", { name: "Study" })).toHaveAttribute("aria-current", "page");
    expect(screen.getByRole("link", { name: "Clov" })).toHaveAttribute("href", "/learn");
  });

  it("keeps secondary tools reachable and returns focus on Escape", () => {
    render(<Navigation />);
    const trigger = screen.getByRole("button", { name: "Account and more tools" });
    fireEvent.click(trigger);
    expect(screen.getByRole("link", { name: "Grades" })).toHaveAttribute("href", "/gradebook");
    expect(screen.queryByRole("link", { name: "Admin" })).toBeNull();
    fireEvent.keyDown(document, { key: "Escape" });
    expect(trigger).toHaveFocus();
    expect(trigger).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByRole("link", { name: "Grades" })).toBeNull();
  });

  it("shows the admin destination only for admins", () => {
    state.isAdmin = true;
    render(<Navigation />);
    fireEvent.click(screen.getByRole("button", { name: "Account and more tools" }));
    expect(screen.getByRole("link", { name: "Admin" })).toHaveAttribute("href", "/admin");
  });

  it("switches the study mode without discarding the mounted screen", () => {
    const select = vi.fn();
    render(<StudyNavigation active="guide" onSelect={select} />);
    expect(screen.getByRole("button", { name: "Study Guides" })).toHaveAttribute("aria-pressed", "true");
    fireEvent.click(screen.getByRole("button", { name: "Flashcards" }));
    expect(select).toHaveBeenCalledWith("cards");
    expect(screen.getByRole("link", { name: "Quiz" })).toHaveAttribute("href", "/quiz");
  });
});

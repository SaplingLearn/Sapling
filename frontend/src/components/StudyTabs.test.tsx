// @vitest-environment jsdom
import React from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { StudyTabs } from "./StudyTabs";

const flagState = vi.hoisted(() => ({ flags: {} as Record<string, string>, ready: true }));
vi.mock("@/context/FlagsContext", () => ({ useFlagMap: () => flagState }));
afterEach(cleanup);
beforeEach(() => { flagState.flags = {}; flagState.ready = true; });

describe("Study tools", () => {
  it("points each tool at its own page, never the retired ?mode= panes", () => {
    render(<StudyTabs mode="guide" />);
    expect(screen.getByRole("link", { name: "Quiz" }).getAttribute("href")).toBe("/quiz");
    expect(screen.getByRole("link", { name: "Study Guide" }).getAttribute("href"))
      .toBe("/library?type=study_guide");
    expect(screen.getByRole("link", { name: "Flashcards" }).getAttribute("href")).toBe("/flashcards");
  });

  it("navigates rather than switching a pane in place", () => {
    render(<StudyTabs mode="guide" />);
    const flashcards = screen.getByRole("link", { name: "Flashcards" });
    // No preventDefault handler left: a plain click is the navigation.
    expect(fireEvent.click(flashcards)).toBe(true);
  });

  it("marks Quiz selected on the quiz page", () => {
    render(<StudyTabs mode="quiz" />);
    expect(screen.getByRole("link", { name: "Quiz" }).getAttribute("aria-current")).toBe("page");
    expect(screen.getByRole("link", { name: "Study Guide" }).getAttribute("aria-current")).toBeNull();
  });

  it("preserves the quiz feature flag", () => {
    flagState.flags = { hide_quiz: "on" };
    render(<StudyTabs mode="guide" />);
    expect(screen.queryByRole("link", { name: "Quiz" })).toBeNull();
    expect(screen.getByRole("link", { name: "Flashcards" })).toBeTruthy();
  });

  it("waits for flags before offering Quiz", () => {
    flagState.ready = false;
    render(<StudyTabs mode="guide" />);
    expect(screen.queryByRole("link", { name: "Quiz" })).toBeNull();
  });
});

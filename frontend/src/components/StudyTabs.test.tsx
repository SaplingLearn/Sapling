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
  it("offers Quiz alongside the study guide and flashcards", () => {
    render(<StudyTabs mode="guide" />);
    expect(screen.getByRole("link", { name: "Quiz" }).getAttribute("href")).toBe("/quiz");
    expect(screen.getByRole("link", { name: "Study Guide" }).getAttribute("href")).toBe("/study?mode=guide");
    expect(screen.getByRole("link", { name: "Flashcards" }).getAttribute("href")).toBe("/study?mode=cards");
  });

  it("switches existing study modes without leaving the page", () => {
    const change = vi.fn();
    render(<StudyTabs mode="guide" onChange={change} />);
    fireEvent.click(screen.getByRole("link", { name: "Flashcards" }));
    expect(change).toHaveBeenCalledWith("cards");
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

// @vitest-environment jsdom
import React from "react";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("next/link", () => ({
  default: React.forwardRef<HTMLAnchorElement, React.AnchorHTMLAttributes<HTMLAnchorElement>>(function LinkStub(props, ref) {
    return <a ref={ref} {...props} />;
  }),
}));

import { QuickReviews, type QuickReview } from "./QuickReviews";
import type { Concept } from "./studyModel";

afterEach(cleanup);

const concept = (id: string, name: string): Concept => ({
  id, name, st: "review", m: 40, lastStudied: null, pre: [], post: [], step: 0, group: "", gap: "", weekDelta: 0,
} as unknown as Concept);
const reviews: QuickReview[] = [{ t: concept("a", "Loops"), ago: 9 }, { t: concept("b", "Recursion"), ago: 2 }];

function renderRow(onNavigate = vi.fn(), quizHref: string | null = "/quiz?scope=due") {
  render(<QuickReviews reviews={reviews} courseLabel="CS101" reviewHref="/flashcards?course=c1" quizHref={quizHref} onNavigate={onNavigate} fsrsDue />);
  return screen.getByRole("button", { name: /2 reviews due/ });
}

describe("QuickReviews", () => {
  it("is a disclosure: a click opens the list, the row again closes it; hover does nothing", () => {
    const row = renderRow();
    fireEvent.mouseEnter(row.parentElement!);
    expect(screen.queryByRole("region", { name: "Due reviews" })).toBeNull();
    fireEvent.click(row);
    const list = screen.getByRole("region", { name: "Due reviews" });
    expect(row.getAttribute("aria-expanded")).toBe("true");
    expect(row.getAttribute("aria-controls")).toBe(list.id);
    expect(within(list).getByText("Loops")).toBeTruthy();
    fireEvent.click(row);
    expect(screen.queryByRole("region", { name: "Due reviews" })).toBeNull();
  });

  it("Escape closes it and hands focus back to the row; a click outside closes it", () => {
    const row = renderRow();
    fireEvent.click(row);
    const review = screen.getByRole("link", { name: "Review" });
    review.focus();
    fireEvent.keyDown(review, { key: "Escape" });
    expect(screen.queryByRole("region", { name: "Due reviews" })).toBeNull();
    expect(row).toHaveFocus();
    fireEvent.click(row);
    fireEvent.pointerDown(document.body);
    expect(screen.queryByRole("region", { name: "Due reviews" })).toBeNull();
  });

  it("its actions are real links; a plain click leaves through the hub and closes the list", () => {
    const onNavigate = vi.fn();
    const row = renderRow(onNavigate);
    fireEvent.click(row);
    const review = screen.getByRole("link", { name: "Review" });
    expect(review.getAttribute("href")).toBe("/flashcards?course=c1");
    expect(screen.getByRole("link", { name: "Practice what's due" }).getAttribute("href")).toBe("/quiz?scope=due");
    expect(fireEvent.click(review, { metaKey: true })).toBe(true); // a new tab is the browser's
    expect(onNavigate).not.toHaveBeenCalled();
    fireEvent.click(review);
    expect(onNavigate).toHaveBeenCalledWith("/flashcards?course=c1");
    expect(screen.queryByRole("region", { name: "Due reviews" })).toBeNull();
  });

  it("no quiz href: Review alone", () => {
    fireEvent.click(renderRow(vi.fn(), null));
    expect(screen.queryByTestId("due-reviews-quiz")).toBeNull();
    expect(screen.getByTestId("due-reviews-flashcards").textContent).toBe("Review");
  });
});

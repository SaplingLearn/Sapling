// @vitest-environment jsdom
/**
 * One card of the Study Guides home: every field of the card, top to bottom,
 * and the states a guide can be in.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, within } from "@testing-library/react";

vi.mock("next/navigation", () => ({ useRouter: () => ({}) }));
vi.mock("@/context/UserContext", () => ({ useUser: () => ({ userId: "u1", userReady: true }) }));
vi.mock("@/lib/api", () => ({ getCourses: vi.fn() }));
vi.mock("@/lib/studyGuide/api", () => ({
  listGuides: vi.fn(),
  getGuideOptions: vi.fn(),
  planGuide: vi.fn(),
  createGuide: vi.fn(),
}));

import type { GuideCard as Guide } from "@/lib/studyGuide/types";

import { GuideCard } from "./GuideCard";
import { NOW, guide } from "./testKit";

afterEach(cleanup);

const renderCard = (over: Partial<Guide> = {}) => {
  render(<ul><GuideCard guide={guide(over)} now={NOW} /></ul>);
  return screen.getByTestId("guides-card-g1");
};
const figure = (key: string) => {
  const cell = screen.getByTestId(`guides-card-${key}-g1`);
  return `${cell.querySelector("dd")?.textContent} ${cell.querySelector("dt")?.textContent}`;
};

describe("GuideCard", () => {
  it("is one link to the guide's reader", () => {
    const card = renderCard();
    expect(card.tagName).toBe("A");
    expect(card).toHaveAttribute("href", "/study/guide/g1");
    expect(within(card).getByText("Loops and recursion")).toBeTruthy();
  });

  it("dates the guide, and says nothing more when nothing is new or saved", () => {
    const card = renderCard();
    expect(within(card).getByText("Nov 10")).toBeTruthy();
    expect(screen.queryByTestId("guides-card-new-g1")).toBeNull();
    expect(screen.queryByTestId("guides-card-saved-g1")).toBeNull();
    expect(screen.queryByTestId("guides-card-status-g1")).toBeNull();
  });

  it("says how many lectures the class has added since, and that it is saved", () => {
    renderCard({ new_materials: 2, saved_at: "2026-11-11T09:00:00Z" });
    expect(screen.getByTestId("guides-card-new-g1")).toHaveTextContent("2 new lectures");
    expect(screen.getByTestId("guides-card-saved-g1")).toHaveTextContent("Saved");
  });

  it("draws the mastery bar and names the section with the most room", () => {
    const card = renderCard();
    const bar = within(card).getByRole("img");
    expect(bar.getAttribute("aria-label")).toContain("Recursion 50%, Struggling");
    expect(bar.children).toHaveLength(3);
    expect(screen.getByTestId("guides-card-room-g1")).toHaveTextContent("Most room: Recursion, Struggling");
  });

  it("shows the four numbers: sections, blocks, practice and minutes", () => {
    renderCard();
    expect(figure("sections")).toBe("3 Sections");
    expect(figure("blocks")).toBe("7 Blocks");
    expect(figure("practice")).toBe("2 Practice");
    expect(figure("minutes")).toBe("14 Minutes");
  });

  it("labels the guide's scope, goal and depth, with the class beside them", () => {
    const card = renderCard({ goal: "review", depth: "deep", scope_label: "Whole course" });
    const chips = [...card.querySelectorAll(".chip")].map(chip => chip.textContent);
    expect(chips).toEqual(["Whole course", "Review", "Deep review"]);
    expect(within(card).getByText("Intro to CS")).toBeTruthy();
  });

  it("a guide still being written says so, dated by its row, and still opens", () => {
    const card = renderCard({
      status: "generating", generated_at: null, created_at: "2026-11-12T11:00:00Z",
      bars: [], counts: { sections: 0, blocks: 0, practice: 0, minutes: 0 },
    });
    expect(card).toHaveAttribute("href", "/study/guide/g1");
    expect(card).toHaveAttribute("data-status", "generating");
    expect(screen.getByTestId("guides-card-status-g1")).toHaveTextContent("Writing…");
    expect(within(card).getByText("Today")).toBeTruthy();
    // No sections yet: no bar and no "most room".
    expect(within(card).queryByRole("img")).toBeNull();
    expect(screen.queryByTestId("guides-card-room-g1")).toBeNull();
  });

  it("a guide that failed says so and still opens", () => {
    const card = renderCard({ status: "failed" });
    expect(card).toHaveAttribute("href", "/study/guide/g1");
    expect(screen.getByTestId("guides-card-status-g1")).toHaveTextContent("Could not finish");
  });
});

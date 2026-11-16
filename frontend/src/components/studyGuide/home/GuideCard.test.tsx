// @vitest-environment jsdom
/**
 * One card of the Study Guides home: every row of the card, top to bottom,
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

const BLUE = "rgb(40, 104, 176)";

const renderCard = (over: Partial<Guide> = {}) => {
  render(<ul><GuideCard guide={guide(over)} now={NOW} color={BLUE} /></ul>);
  return screen.getByTestId("guides-card-g1");
};
const figure = (key: string) => {
  const cell = screen.getByTestId(`guides-card-${key}-g1`);
  return `${cell.querySelector("dd")?.textContent} ${cell.querySelector("dt")?.textContent}`;
};
/** The card's direct rows, as the text each one holds (an icon's markup has spaces in it). */
const rows = (card: HTMLElement) => [...card.children].map(row => row.textContent?.replace(/\s+/g, " ").trim());

describe("GuideCard", () => {
  it("is one link to the guide's reader, with the title as its heading", () => {
    const card = renderCard();
    expect(card.tagName).toBe("A");
    expect(card).toHaveAttribute("href", "/study/guide/g1");
    const title = within(card).getByRole("heading", { level: 2, name: "Loops and recursion" });
    // The title is cut at two lines: the whole of it is the tooltip.
    expect(title).toHaveAttribute("title", "Loops and recursion");
  });

  it("has its rows in the design's order: title, date, bar, numbers, labels", () => {
    const card = renderCard();
    expect(rows(card)).toEqual([
      "Loops and recursion",
      "Nov 10 Not saved",
      "Most room: RecursionStruggling",
      "Sections3Blocks7Practice2Minutes14",
      "Midterm 2Exam prepCS101, Intro to CS",
    ]);
  });

  it("dates the guide and says it is not saved, with nothing after the date", () => {
    const card = renderCard();
    expect(within(card).getByText("Nov 10")).toBeTruthy();
    expect(screen.getByTestId("guides-card-unsaved-g1")).toHaveTextContent(/^Not saved$/);
    expect(screen.queryByTestId("guides-card-saved-g1")).toBeNull();
    expect(screen.queryByTestId("guides-card-new-g1")).toBeNull();
    expect(screen.queryByTestId("guides-card-status-g1")).toBeNull();
  });

  it("says a saved guide is in the Library, in place of Not saved", () => {
    renderCard({ saved_at: "2026-11-11T09:00:00Z" });
    const saved = screen.getByTestId("guides-card-saved-g1");
    expect(saved).toHaveTextContent("In Library");
    // Read out as saved too.
    expect(saved).toHaveTextContent("Saved");
    expect(screen.queryByTestId("guides-card-unsaved-g1")).toBeNull();
  });

  it("counts the lectures the class has added since, after the date", () => {
    const card = renderCard({ new_materials: 2 });
    expect(screen.getByTestId("guides-card-new-g1")).toHaveTextContent(/^2 new lectures$/);
    expect(card.children[1]).toHaveTextContent("Nov 10 · 2 new lectures");
  });

  it("counts one new lecture in the singular", () => {
    renderCard({ new_materials: 1 });
    expect(screen.getByTestId("guides-card-new-g1")).toHaveTextContent(/^1 new lecture$/);
  });

  it("draws the mastery bar and names the section with the most room and its tier", () => {
    const card = renderCard();
    const bar = within(card).getByRole("img");
    expect(bar.getAttribute("aria-label")).toContain("Recursion 50%, Struggling");
    expect(bar.children).toHaveLength(3);
    const room = screen.getByTestId("guides-card-room-g1");
    expect(room).toHaveTextContent("Most room: Recursion");
    expect(within(room).getByText("Recursion").tagName).toBe("STRONG");
    expect(within(room).getByText("Struggling")).toBeTruthy();
  });

  it("shows the four numbers over their labels: sections, blocks, practice and minutes", () => {
    renderCard();
    expect(figure("sections")).toBe("3 Sections");
    expect(figure("blocks")).toBe("7 Blocks");
    expect(figure("practice")).toBe("2 Practice");
    expect(figure("minutes")).toBe("14 Minutes");
  });

  it("labels a count of one in the singular", () => {
    renderCard({ counts: { sections: 1, blocks: 1, practice: 1, minutes: 1 } });
    expect(figure("sections")).toBe("1 Section");
    expect(figure("blocks")).toBe("1 Block");
    expect(figure("minutes")).toBe("1 Minute");
  });

  describe("the two labels", () => {
    const labels = (over: Partial<Guide>) => {
      const foot = renderCard(over).lastElementChild as HTMLElement;
      return [...(foot.firstElementChild as HTMLElement).children].map(pill => pill.textContent);
    };

    it("are what the guide is for and its goal, at the standard depth", () => {
      expect(labels({ scope_label: "Homework 7", goal: "review", depth: "standard" })).toEqual(["Homework 7", "Review"]);
    });

    it("name a cram sheet in place of the goal", () => {
      expect(labels({ goal: "exam_prep", depth: "cram" })).toEqual(["Midterm 2", "Cram sheet"]);
    });

    it("name a deep review in place of the goal", () => {
      expect(labels({ goal: "practice", depth: "deep" })).toEqual(["Midterm 2", "Deep review"]);
    });
  });

  it("names the class by its code, with a dot in the class's colour", () => {
    const card = renderCard();
    const code = within(card).getByText("CS101");
    const dot = code.previousElementSibling as HTMLElement;
    expect(dot).toHaveAttribute("aria-hidden", "true");
    expect(dot.style.background).toBe(BLUE);
    // The full name is the tooltip, and is read out after the code.
    expect(code.parentElement).toHaveAttribute("title", "Intro to CS");
    expect(code.parentElement).toHaveTextContent("CS101, Intro to CS");
  });

  it("does not say the name twice for a class with no code", () => {
    const card = renderCard({ course_code: "Intro to CS" });
    expect(within(card).getAllByText(/Intro to CS/)).toHaveLength(1);
  });

  it("a guide still being written says so after the date, keeps its rows, and still opens", () => {
    const card = renderCard({
      status: "generating", generated_at: null, created_at: "2026-11-12T11:00:00Z",
      bars: [], counts: { sections: 0, blocks: 0, practice: 0, minutes: 0 },
    });
    expect(card).toHaveAttribute("href", "/study/guide/g1");
    expect(card).toHaveAttribute("data-status", "generating");
    expect(screen.getByTestId("guides-card-status-g1")).toHaveTextContent(/^Not finished$/);
    expect(card.children[1]).toHaveTextContent("Today · Not finished Not saved");
    // No sections yet: no bar and no "most room", but the same five rows.
    expect(within(card).queryByRole("img")).toBeNull();
    expect(screen.queryByTestId("guides-card-room-g1")).toBeNull();
    expect(card.children).toHaveLength(5);
    expect(figure("sections")).toBe("0 Sections");
  });

  it("a guide that failed says so in place of the new lectures, and still opens", () => {
    const card = renderCard({ status: "failed", new_materials: 3 });
    expect(card).toHaveAttribute("href", "/study/guide/g1");
    expect(screen.getByTestId("guides-card-status-g1")).toHaveTextContent(/^Could not finish$/);
    expect(screen.queryByTestId("guides-card-new-g1")).toBeNull();
  });
});

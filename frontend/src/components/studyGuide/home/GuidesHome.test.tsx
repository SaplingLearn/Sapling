// @vitest-environment jsdom
/**
 * The Study Guides home: the toolbar (search, sort), the states that stand in
 * for the grid, and the links that open the New study guide dialog.
 *
 * A card's own content is pinned in GuideCard.test.tsx and the dialog in
 * NewGuideModal.test.tsx; the pure rules are in guidesModel.test.ts.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

const push = vi.hoisted(() => vi.fn());
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push }),
  useSearchParams: () => new URLSearchParams(window.location.search),
}));
vi.mock("@/context/UserContext", () => ({ useUser: () => ({ userId: "u1", userReady: true }) }));
vi.mock("@/components/DocumentUploadModal", () => ({ DocumentUploadModal: () => null }));
vi.mock("@/lib/api", () => ({ getCourses: vi.fn() }));
vi.mock("@/lib/studyGuide/api", () => ({
  listGuides: vi.fn(),
  getGuideOptions: vi.fn(),
  planGuide: vi.fn(),
  createGuide: vi.fn(),
}));

import { arriveAt, deferred, guide, mocks, renderHome, resetMocks } from "./testKit";

const THREE = [
  guide({ id: "a", title: "Loops and recursion", generated_at: "2026-11-10T12:00:00Z" }),
  guide({ id: "b", title: "Limits", course_id: "c2", course_name: "Calculus", scope_label: "Whole course", generated_at: "2026-11-11T12:00:00Z" }),
  guide({ id: "c", title: "Arrays", scope_label: "Lab 5", generated_at: "2026-11-09T12:00:00Z" }),
];

/** The ids of the cards on screen, in order. */
const cardIds = () =>
  within(screen.getByTestId("guides-grid")).getAllByRole("link").map(card => card.getAttribute("data-testid")?.replace("guides-card-", ""));

async function home(guides = THREE) {
  mocks.list.mockResolvedValue({ guides });
  renderHome();
  await screen.findByTestId("guides-grid");
  return userEvent.setup();
}

beforeEach(() => {
  resetMocks();
  push.mockReset();
});
afterEach(cleanup);

describe("the page", () => {
  it("is titled Study Guides, with the way back to the hub and the AI chip", async () => {
    await home();
    expect(screen.getByRole("heading", { level: 1, name: "Study Guides" })).toBeTruthy();
    expect(screen.getByTestId("back-link")).toHaveAttribute("href", "/study");
    expect(screen.getByRole("button", { name: "Review AI guidelines" })).toBeTruthy();
  });

  it("goes back to the hub on the course it was opened for", async () => {
    arriveAt("course=c2");
    await home();
    expect(screen.getByTestId("back-link")).toHaveAttribute("href", "/study?course=c2");
  });

  it("lists every guide, newest first, each a link to its reader", async () => {
    await home();
    expect(mocks.list).toHaveBeenCalledWith("u1");
    expect(cardIds()).toEqual(["b", "a", "c"]);
    expect(screen.getByTestId("guides-card-b")).toHaveAttribute("href", "/study/guide/b");
  });
});

describe("search", () => {
  it("filters by title, class name and scope label", async () => {
    const user = await home();
    const search = screen.getByTestId("guides-search");
    await user.type(search, "recurs");
    expect(cardIds()).toEqual(["a"]);
    await user.clear(search);
    await user.type(search, "calculus");
    expect(cardIds()).toEqual(["b"]);
    await user.clear(search);
    await user.type(search, "lab 5");
    expect(cardIds()).toEqual(["c"]);
  });

  it("says so when no guide matches, and Escape brings the grid back", async () => {
    const user = await home();
    await user.type(screen.getByTestId("guides-search"), "chemistry");
    expect(screen.getByTestId("guides-no-match")).toHaveTextContent("No guide matches “chemistry”.");
    expect(screen.queryByTestId("guides-grid")).toBeNull();
    expect(screen.queryByTestId("guides-empty")).toBeNull();
    await user.keyboard("{Escape}");
    expect(cardIds()).toEqual(["b", "a", "c"]);
  });
});

describe("sort", () => {
  it("shows only the current choice on its button", async () => {
    const user = await home();
    const sort = screen.getByTestId("guides-sort");
    expect(sort).toHaveTextContent(/^Most recent$/);
    expect(screen.queryByRole("menu")).toBeNull();
    await user.click(sort);
    const items = within(screen.getByRole("menu")).getAllByRole("menuitemradio");
    expect(items.map(item => item.textContent?.trim())).toEqual(["Most recent", "Oldest", "Class"]);
    expect(items.map(item => item.getAttribute("aria-checked"))).toEqual(["true", "false", "false"]);
  });

  it("reorders the grid and closes the menu on a pick", async () => {
    const user = await home();
    await user.click(screen.getByTestId("guides-sort"));
    await user.click(screen.getByTestId("guides-sort-oldest"));
    expect(screen.queryByRole("menu")).toBeNull();
    expect(screen.getByTestId("guides-sort")).toHaveTextContent(/^Oldest$/);
    expect(cardIds()).toEqual(["c", "a", "b"]);

    await user.click(screen.getByTestId("guides-sort"));
    await user.click(screen.getByTestId("guides-sort-class"));
    expect(screen.getByTestId("guides-sort")).toHaveTextContent(/^Class$/);
    // Calculus before Intro to CS; newest first inside Intro to CS.
    expect(cardIds()).toEqual(["b", "a", "c"]);

    await user.click(screen.getByTestId("guides-sort"));
    await user.click(screen.getByTestId("guides-sort-recent"));
    expect(cardIds()).toEqual(["b", "a", "c"]);
  });

  it("closes on Escape, with focus back on the button", async () => {
    const user = await home();
    await user.click(screen.getByTestId("guides-sort"));
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("menu")).toBeNull();
    expect(screen.getByTestId("guides-sort")).toHaveFocus();
  });
});

describe("states", () => {
  it("shows skeleton cards while the list loads", async () => {
    const pending = deferred<{ guides: never[] }>();
    mocks.list.mockReturnValue(pending.promise);
    renderHome();
    expect(screen.getByTestId("guides-loading")).toHaveAttribute("aria-busy", "true");
    expect(screen.queryByTestId("guides-grid")).toBeNull();
    expect(screen.queryByTestId("guides-empty")).toBeNull();
    pending.resolve({ guides: [] });
    await screen.findByTestId("guides-empty");
    expect(screen.queryByTestId("guides-loading")).toBeNull();
  });

  it("invites the first guide when there is none, with the same New button", async () => {
    mocks.list.mockResolvedValue({ guides: [] });
    renderHome();
    const empty = await screen.findByTestId("guides-empty");
    expect(within(empty).getByRole("heading", { name: "No study guides yet" })).toBeTruthy();
    expect(screen.queryByTestId("guide-new-dialog")).toBeNull();
    await userEvent.setup().click(screen.getByTestId("guides-empty-new"));
    expect(await screen.findByTestId("guide-new-dialog")).toBeTruthy();
  });

  it("a failed load is an error with Retry, not an empty home", async () => {
    mocks.list.mockRejectedValueOnce(new Error("500"));
    renderHome();
    expect(await screen.findByTestId("guides-load-error")).toHaveAttribute("role", "alert");
    expect(screen.queryByTestId("guides-empty")).toBeNull();

    mocks.list.mockResolvedValue({ guides: THREE });
    await userEvent.setup().click(screen.getByTestId("guides-load-retry"));
    await screen.findByTestId("guides-grid");
    expect(screen.queryByTestId("guides-load-error")).toBeNull();
    expect(mocks.list).toHaveBeenCalledTimes(2);
  });
});

describe("opening the New study guide dialog", () => {
  it("opens from the toolbar, and Cancel closes it", async () => {
    const user = await home();
    expect(screen.queryByTestId("guide-new-dialog")).toBeNull();
    await user.click(screen.getByTestId("guides-new"));
    expect(await screen.findByRole("dialog", { name: "New study guide" })).toBeTruthy();
    await user.click(screen.getByTestId("guide-new-cancel"));
    expect(screen.queryByTestId("guide-new-dialog")).toBeNull();
  });

  it("?new=1 opens it on arrival and leaves the URL", async () => {
    arriveAt("new=1");
    await home();
    expect(await screen.findByTestId("guide-new-dialog")).toBeTruthy();
    expect(window.location.search).toBe("");
    // No class named: the first of the term's courses.
    await waitFor(() => expect(screen.getByTestId("guide-new-class")).toHaveTextContent("CS101"));
  });

  it("?new=1&course= opens it with that class chosen, and keeps the course in the URL", async () => {
    arriveAt("new=1&course=c2");
    await home();
    await screen.findByTestId("guide-new-dialog");
    await waitFor(() => expect(screen.getByTestId("guide-new-class")).toHaveTextContent("MA225"));
    expect(mocks.options).toHaveBeenCalledWith("u1", "c2", null);
    expect(window.location.search).toBe("?course=c2");
  });

  it("Generate guide creates the guide and goes to its reader", async () => {
    arriveAt("new=1&course=c1");
    const user = await home();
    await screen.findByTestId("guide-new-material-d1");
    await user.click(screen.getByTestId("guide-new-generate"));
    await waitFor(() => expect(push).toHaveBeenCalledWith("/study/guide/g-new"));
    expect(mocks.create).toHaveBeenCalledWith("u1", expect.objectContaining({ course_id: "c1", material_ids: ["d1", "d2", "d3"] }));
  });

  it("a plain arrival opens nothing", async () => {
    arriveAt("course=c2");
    await home();
    expect(screen.queryByTestId("guide-new-dialog")).toBeNull();
    expect(mocks.options).not.toHaveBeenCalled();
  });
});

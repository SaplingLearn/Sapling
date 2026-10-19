// @vitest-environment jsdom
import React from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Navigation, PhoneRail, StudyNavigation } from "./Navigation";
import { MORE_STORAGE_KEY, Sidebar, __resetMoreStateForTests } from "./Sidebar";
import { __resetMediaStoresForTests } from "@/lib/useIsMobile";
import { __resetReducedMotionStoreForTests } from "@/lib/usePrefersReducedMotion";

const state = vi.hoisted(() => ({ pathname: "/study", search: "", isAdmin: false }));
vi.mock("next/navigation", () => ({
  usePathname: () => state.pathname,
  useSearchParams: () => new URLSearchParams(state.search),
}));
vi.mock("@/context/UserContext", () => ({ useUser: () => ({ userName: "Sam Student", isAdmin: state.isAdmin }) }));
const flagState = vi.hoisted(() => ({ flags: {} as Record<string, string>, ready: true }));
vi.mock("@/context/FlagsContext", () => ({ useFlagMap: () => flagState }));
afterEach(() => {
  cleanup();
  state.isAdmin = false; state.search = "";
  flagState.flags = {}; flagState.ready = true;
  window.localStorage.clear();
  __resetMoreStateForTests();
});

describe("FA26 phone rail", () => {
  it("keeps Study selected for both flashcards and guides", () => {
    render(<PhoneRail />);
    expect(screen.getByRole("link", { name: "Study" })).toHaveAttribute("aria-current", "page");
    expect(screen.getByRole("link", { name: "Clov" })).toHaveAttribute("href", "/learn");
  });

  it("keeps secondary tools reachable and returns focus on Escape", () => {
    render(<PhoneRail />);
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
    render(<PhoneRail />);
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

  it("drops destinations hidden by their hide_ flag, in the rail and the account menu (#620)", () => {
    flagState.flags = { hide_quiz: "on", hide_grades: "on", hide_tree: "off" };
    render(<PhoneRail />);
    expect(screen.queryByTestId("nav-link-quiz")).toBeNull();
    expect(screen.getByTestId("nav-link-tree")).toHaveAttribute("href", "/tree");
    expect(screen.getByTestId("nav-link-learn")).toHaveAttribute("href", "/learn");
    fireEvent.click(screen.getByRole("button", { name: "Account and more tools" }));
    expect(screen.queryByTestId("nav-link-gradebook")).toBeNull();
    expect(screen.getByTestId("nav-link-settings")).toBeTruthy();
  });

  it("holds flagged destinations back until flags load; Dashboard stays", () => {
    flagState.ready = false;
    render(<PhoneRail />);
    expect(screen.getByTestId("nav-link-dashboard")).toBeTruthy();
    expect(screen.queryByTestId("nav-link-library")).toBeNull();
    expect(screen.queryByTestId("nav-link-learn")).toBeNull();
  });

  it("draws Library, Calendar and Clov with the approved botanical exports", () => {
    render(<PhoneRail />);
    const iconIn = (name: string) => screen.getByRole("link", { name }).querySelector(".sapling-icon");
    expect(iconIn("Library")).toHaveAttribute("data-icon", "library");
    expect(iconIn("Calendar")).toHaveAttribute("data-icon", "calendar");
    expect(iconIn("Clov")).toHaveAttribute("data-icon", "clov");
    expect(iconIn("Dashboard")).toHaveAttribute("data-icon", "today");
    expect(iconIn("Library")).toHaveAttribute("aria-hidden", "true");
  });
});

/* ── The Pen sidebar (desktop) ─────────────────────────────────────────── */

const PRIMARY_ORDER = ["dashboard", "learn", "tree", "library", "tutor-view", "calendar"];
/** jsdom has no layout: give every sidebar row a Pen-like box (rows 46px tall
 *  on a 55px pitch, the first at 66px into the content box). */
function stubRowGeometry() {
  return vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockImplementation(function (this: HTMLElement) {
    const key = this.dataset.navKey;
    const index = key ? PRIMARY_ORDER.indexOf(key) : -1;
    const top = key ? 69 + 66 + (index < 0 ? 7 : index) * 55 : 69;
    return { top, bottom: top + 46, left: 16, right: 200, width: 184, height: 46, x: 16, y: top, toJSON: () => ({}) } as DOMRect;
  });
}
/** Swap the matchMedia stub: `phone` = below 768px, `reduced` = reduced motion. */
function setMedia({ phone = false, reduced = true }: { phone?: boolean; reduced?: boolean }) {
  window.matchMedia = ((query: string) => ({
    matches: query.includes("prefers-reduced-motion") ? reduced : query.includes("max-width: 767px") ? phone : false,
    media: query, onchange: null,
    addEventListener() {}, removeEventListener() {}, addListener() {}, removeListener() {},
    dispatchEvent: () => false,
  })) as unknown as typeof window.matchMedia;
  __resetMediaStoresForTests();
  __resetReducedMotionStoreForTests();
}
const pill = () => screen.getByTestId("nav-pill");
const current = () => Array.from(document.querySelectorAll('[aria-current="page"]'));

describe("Pen sidebar", () => {
  afterEach(() => { vi.restoreAllMocks(); setMedia({}); state.pathname = "/study"; });

  it("shows the six Pen destinations in order, with their hrefs", () => {
    state.pathname = "/dashboard";
    flagState.flags = { tutor_view: "on" };
    render(<Sidebar />);
    const nav = screen.getByRole("navigation", { name: "Primary" });
    const six = within(nav).getAllByRole("list")[0];
    expect(within(six).getAllByRole("link").map(a => [a.textContent, a.getAttribute("href")])).toEqual([
      ["Today", "/dashboard"], ["Learn", "/learn"], ["Knowledge", "/tree"],
      ["Library", "/library"], ["Tutor", "/learn?view=tutor"], ["Calendar", "/calendar"],
    ]);
    expect(screen.getByTestId("nav-link-tutor-view")).toHaveAttribute("href", "/learn?view=tutor");
    expect(screen.getByTestId("nav-link-tree")).toHaveTextContent("Knowledge");
    expect(screen.getByTestId("nav-link-settings")).toHaveAttribute("href", "/settings");
    expect(screen.getByText("Your workspace")).toBeTruthy();
    expect(screen.getByTestId("nav-account")).toHaveTextContent("Sam Student");
    expect(screen.getByTestId("nav-account")).toHaveTextContent("Personal workspace");
    expect(screen.getByRole("link", { name: "Sapling home" })).toHaveAttribute("href", "/dashboard");
  });

  it("draws the approved Pen exports for five rows and Lucide's branch for Knowledge", () => {
    flagState.flags = { tutor_view: "on" };
    render(<Sidebar />);
    const icon = (id: string) => screen.getByTestId(id).querySelector(".sapling-icon");
    expect(icon("nav-link-dashboard")).toHaveAttribute("data-icon", "today");
    expect(icon("nav-link-learn")).toHaveAttribute("data-icon", "learn");
    expect(icon("nav-link-library")).toHaveAttribute("data-icon", "library");
    expect(icon("nav-link-tutor-view")).toHaveAttribute("data-icon", "tutor");
    expect(icon("nav-link-calendar")).toHaveAttribute("data-icon", "calendar");
    expect(screen.getByTestId("nav-link-tree").querySelector("svg.lucide-git-branch")).toBeTruthy();
  });

  it("marks Learn or Tutor current by ?view=, exactly one row at a time", () => {
    state.pathname = "/learn";
    flagState.flags = { tutor_view: "on" };
    const { rerender } = render(<Sidebar />);
    expect(screen.getByTestId("nav-link-learn")).toHaveAttribute("aria-current", "page");
    expect(current()).toHaveLength(1);
    state.search = "view=tutor";
    rerender(<Sidebar />);
    expect(screen.getByTestId("nav-link-tutor-view")).toHaveAttribute("aria-current", "page");
    expect(screen.getByTestId("nav-link-learn")).not.toHaveAttribute("aria-current");
    expect(current()).toHaveLength(1);
  });

  it("hides Tutor while tutor_view is off; Learn then owns /learn, even with ?view=tutor", () => {
    state.pathname = "/learn";
    state.search = "view=tutor";
    render(<Sidebar />);
    expect(screen.queryByTestId("nav-link-tutor-view")).toBeNull();
    expect(screen.getByTestId("nav-link-learn")).toHaveAttribute("aria-current", "page");
  });

  it("keeps the active course, session and deep-link context when switching Learn/Tutor", () => {
    state.pathname = "/learn";
    state.search = "course=course-two&resume=session-two&mode=socratic&view=tutor";
    flagState.flags = { tutor_view: "on" };
    const { rerender } = render(<Sidebar />);
    expect(screen.getByTestId("nav-link-learn")).toHaveAttribute("href", "/learn?course=course-two&resume=session-two&mode=socratic");
    expect(screen.getByTestId("nav-link-tutor-view")).toHaveAttribute("href", "/learn?course=course-two&resume=session-two&mode=socratic&view=tutor");
    state.search = "course=course-three";
    rerender(<Sidebar />);
    expect(screen.getByTestId("nav-link-learn")).toHaveAttribute("href", "/learn?course=course-three");
    expect(screen.getByTestId("nav-link-tutor-view")).toHaveAttribute("href", "/learn?course=course-three&view=tutor");
    expect(screen.getByTestId("nav-link-library")).toHaveAttribute("href", "/library");
  });

  it("drops destinations hidden by their hide_ flag, in the six and in More (#620)", () => {
    state.pathname = "/dashboard";
    flagState.flags = { tutor_view: "on", hide_tutor: "on", hide_tree: "on", hide_quiz: "on", hide_grades: "off" };
    render(<Sidebar />);
    for (const id of ["nav-link-learn", "nav-link-tutor-view", "nav-link-tree", "nav-link-quiz"]) {
      expect(screen.queryByTestId(id), id).toBeNull();
    }
    expect(screen.getByTestId("nav-link-library")).toBeTruthy();
    expect(screen.getByTestId("nav-link-gradebook")).toHaveAttribute("href", "/gradebook");
  });

  it("keeps every other destination in More, and drops More when flags empty it", () => {
    render(<Sidebar />);
    const region = screen.getByTestId("nav-more-region");
    expect(within(region).getAllByRole("link", { hidden: true }).map(a => a.getAttribute("href"))).toEqual([
      "/quiz", "/study", "/social", "/achievements", "/gradebook", "/notetaker", "/course-planner",
    ]);
    cleanup();
    flagState.flags = Object.fromEntries(
      ["quiz", "study", "social", "achievements", "grades", "notetaker", "course_planner"].map(f => [`hide_${f}`, "on"]));
    render(<Sidebar />);
    expect(screen.queryByTestId("nav-more")).toBeNull();
  });

  it("puts Admin in More for admins only", () => {
    state.isAdmin = true;
    render(<Sidebar />);
    expect(screen.getByTestId("nav-link-admin")).toHaveAttribute("href", "/admin");
  });

  it("holds flagged destinations back until flags load; Today and Settings stay", () => {
    flagState.ready = false;
    render(<Sidebar />);
    expect(screen.getByTestId("nav-link-dashboard")).toBeTruthy();
    expect(screen.getByTestId("nav-link-settings")).toBeTruthy();
    expect(screen.queryByTestId("nav-link-learn")).toBeNull();
    expect(screen.queryByTestId("nav-more")).toBeNull();
  });

  it("More is a collapsed disclosure that remembers its state", async () => {
    state.pathname = "/dashboard";
    render(<Sidebar />);
    const button = screen.getByTestId("nav-more");
    const region = screen.getByTestId("nav-more-region");
    expect(button).toHaveAttribute("aria-expanded", "false");
    expect(button).toHaveAttribute("aria-controls", region.id);
    expect(region).toHaveAttribute("inert");
    fireEvent.click(button);
    expect(button).toHaveAttribute("aria-expanded", "true");
    expect(region).not.toHaveAttribute("inert");
    expect(region).toHaveAttribute("data-open");
    expect(window.localStorage.getItem(MORE_STORAGE_KEY)).toBe("1");
    // a fresh page load reads the remembered state back
    cleanup();
    __resetMoreStateForTests();
    render(<Sidebar />);
    await waitFor(() => expect(screen.getByTestId("nav-more")).toHaveAttribute("aria-expanded", "true"));
  });

  it("More works from the keyboard: Enter toggles, Escape collapses and returns focus", async () => {
    state.pathname = "/dashboard";
    const user = userEvent.setup();
    render(<Sidebar />);
    const button = screen.getByTestId("nav-more");
    button.focus();
    await user.keyboard("{Enter}");
    expect(button).toHaveAttribute("aria-expanded", "true");
    await user.tab();
    expect(screen.getByTestId("nav-link-quiz")).toHaveFocus();
    await user.keyboard("{Escape}");
    expect(button).toHaveAttribute("aria-expanded", "false");
    expect(button).toHaveFocus();
    expect(window.localStorage.getItem(MORE_STORAGE_KEY)).toBe("0");
    await user.keyboard(" ");
    expect(button).toHaveAttribute("aria-expanded", "true");
  });

  it("survives blocked storage", () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => { throw new Error("blocked"); });
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => { throw new Error("blocked"); });
    state.pathname = "/dashboard";
    render(<Sidebar />);
    fireEvent.click(screen.getByTestId("nav-more"));
    expect(screen.getByTestId("nav-more")).toHaveAttribute("aria-expanded", "true");
  });

  it("opens More, with that row current, when the route lives there", () => {
    state.pathname = "/quiz/abc";
    render(<Sidebar />);
    expect(screen.getByTestId("nav-more")).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByTestId("nav-link-quiz")).toHaveAttribute("aria-current", "page");
    expect(current()).toHaveLength(1);
    // the student may still close it on that route
    fireEvent.click(screen.getByTestId("nav-more"));
    expect(screen.getByTestId("nav-more")).toHaveAttribute("aria-expanded", "false");
  });

  it("marks Settings current on /settings", () => {
    state.pathname = "/settings";
    render(<Sidebar />);
    expect(screen.getByTestId("nav-link-settings")).toHaveAttribute("aria-current", "page");
    expect(current()).toHaveLength(1);
  });

  it("places ONE pill under the current row, and slides it on a route change", async () => {
    setMedia({ reduced: false });
    stubRowGeometry();
    state.pathname = "/dashboard";
    flagState.flags = { tutor_view: "on" };
    const { rerender } = render(<Sidebar />);
    expect(document.querySelectorAll('[data-testid="nav-pill"]')).toHaveLength(1);
    expect(pill()).toHaveAttribute("data-shown");
    expect(pill()).toHaveAttribute("data-jump"); // first placement: no slide
    expect(getComputedStyle(pill()).transform).toBe("translateY(66px)");
    const sidebar = screen.getByTestId("app-sidebar");
    await waitFor(() => expect(sidebar).toHaveAttribute("data-animated"));
    state.pathname = "/library";
    rerender(<Sidebar />);
    expect(getComputedStyle(pill()).transform).toBe("translateY(231px)");
    expect(pill()).not.toHaveAttribute("data-jump"); // a real move: it tweens
    expect(sidebar).toHaveAttribute("data-animated");
    expect(screen.getByTestId("nav-link-library")).toHaveAttribute("aria-current", "page");
  });

  it("under reduced motion never arms the transitions, and lands the pill on the new row", async () => {
    setMedia({ reduced: true });
    stubRowGeometry();
    state.pathname = "/dashboard";
    flagState.flags = { tutor_view: "on" };
    const { rerender } = render(<Sidebar />);
    await act(() => new Promise(r => setTimeout(r, 50)));
    state.pathname = "/learn";
    state.search = "view=tutor";
    rerender(<Sidebar />);
    expect(screen.getByTestId("app-sidebar")).not.toHaveAttribute("data-animated");
    expect(getComputedStyle(pill()).transform).toBe("translateY(286px)");
    expect(screen.getByTestId("nav-link-tutor-view")).toHaveAttribute("aria-current", "page");
    expect(current()).toHaveLength(1);
  });

  it("hides the pill while its row sits in a collapsed More, and the active row keeps its own fill", () => {
    stubRowGeometry();
    state.pathname = "/quiz";
    render(<Sidebar />);
    expect(pill()).toHaveAttribute("data-shown");
    fireEvent.click(screen.getByTestId("nav-more"));
    expect(pill()).not.toHaveAttribute("data-shown");
  });
});

describe("shell navigation switch", () => {
  afterEach(() => setMedia({}));

  it("desktop: the sidebar carries the testids, the rail none", () => {
    setMedia({ phone: false });
    state.pathname = "/dashboard";
    render(<Navigation />);
    expect(screen.getAllByTestId("nav-link-dashboard")).toHaveLength(1);
    expect(screen.getByTestId("app-sidebar")).toContainElement(screen.getByTestId("nav-link-dashboard"));
  });

  it("phone: the rail carries the testids, the sidebar none", () => {
    setMedia({ phone: true });
    state.pathname = "/dashboard";
    render(<Navigation />);
    expect(screen.queryByTestId("app-sidebar")).toBeNull();
    expect(screen.getAllByTestId("nav-link-dashboard")).toHaveLength(1);
    expect(screen.getByRole("button", { name: "Account and more tools" })).toBeTruthy();
  });
});

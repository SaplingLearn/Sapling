// @vitest-environment jsdom
/**
 * The Claude Design onboarding, signed in only (sign in first, 2026-11-12):
 * the per-account draft (#757) and its expiry, screen gating, the birthday
 * rules, the school and course dead ends, the shared legal text, the profile
 * save (versions, under_18, the name) and every way it can fail, the Connect
 * step's hand-offs, and the accessibility of each screen change. Reduced
 * motion is on unless a test turns it off, so the intro/outro choreography is
 * skipped.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, cleanup, waitFor, fireEvent, screen, act, within } from "@testing-library/react";

const replace = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ replace }) }));

const signOut = vi.fn(async () => {});
const refreshProfile = vi.fn(async () => {});
const markOnboarded = vi.fn();
let user = { userId: "user_a", userName: "Ada Lovelace" };
let authed = true;
vi.mock("@/context/UserContext", () => ({
  useUser: () => ({ ...user, userReady: true, isAuthenticated: authed, signOut, refreshProfile, markOnboarded }),
}));

const toast = { success: vi.fn(), error: vi.fn(), info: vi.fn() };
vi.mock("@/components/ToastProvider", () => ({ useToast: () => toast }));

let seedRoute: string | null = null;
vi.mock("@/lib/localSeed", () => ({ onboardingRedirect: async () => seedRoute }));

const COURSES = [
  { id: "c1", course_code: "CAS CS 111", course_name: "Introduction to Computer Science 1" },
  { id: "c2", course_code: "CAS MA 123", course_name: "Calculus I" },
];
const submitOnboardingProfile = vi.fn();
const updateSettings = vi.fn(async () => ({}));
// Driveable so the #802 latest-query-wins case can hold one reply open; it
// answers with the catalog above by default.
type SearchReply = { courses: { id: string; course_code: string; course_name: string }[] };
const allCourses = async (): Promise<SearchReply> => ({ courses: COURSES });
const onboardingCoursesSearch = vi.fn<(q: string) => Promise<SearchReply>>(allCourses);
vi.mock("@/lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api")>()),
  submitOnboardingProfile: (...a: unknown[]) => submitOnboardingProfile(...a),
  updateSettings: (...a: unknown[]) => updateSettings(...(a as [])),
  onboardingCoursesSearch: (q: string) => onboardingCoursesSearch(q),
}));

// The student's feature flags (#620), read by the Connect step itself.
const fetchFlags = vi.fn<() => Promise<Record<string, string>>>(async () => ({}));
vi.mock("@/lib/flags", () => ({ fetchFlags: () => fetchFlags() }));

import { Onboarding } from "./Onboarding";
import { onboardingDraftKey, GUEST_DRAFT_KEY, DRAFT_TTL_MS } from "@/lib/onboardingDraft";
import { SAPLING_WORDMARK_SRC } from "@/components/SaplingWordmark";
import { PRIVACY, TERMS } from "@/lib/legal/documents";
import { PRIVACY_VERSION, TERMS_VERSION } from "@/lib/legal/versions";
import { AGE_GATE_MS } from "@/components/onboarding/age";
import { ApiError } from "@/lib/api";

const CONNECT = 8; // index of the last screen
const AT_CONNECT = {
  name: "Ada", dobM: "4", dobD: "12", dobY: "2000", school: "bu", year: "junior",
  courses: [COURSES[0]], coursesLater: false, termsEnd: true, termsOk: true, privEnd: true, privOk: true,
  conn: {}, screen: CONNECT, done: [0, 1, 2, 3, 4],
};

/** Stores a draft the way the flow does: stamped for its 7-day expiry. */
function seedDraft(userId: string, draft: object, savedAt = Date.now()) {
  localStorage.setItem(onboardingDraftKey(userId), JSON.stringify({ ...draft, savedAt }));
}
function storedDraft(userId = "user_a") {
  const raw = localStorage.getItem(onboardingDraftKey(userId));
  return raw ? JSON.parse(raw) : null;
}

function reducedMotion(on: boolean) {
  window.matchMedia = ((query: string) => ({
    matches: on && query.includes("reduce"), media: query, onchange: null,
    addEventListener: () => {}, removeEventListener: () => {},
    addListener: () => {}, removeListener: () => {}, dispatchEvent: () => false,
  })) as unknown as typeof window.matchMedia;
}

// jsdom has no 2D canvas; the graph already tolerates a null context.
HTMLCanvasElement.prototype.getContext = (() => null) as typeof HTMLCanvasElement.prototype.getContext;

const continueBtn = () => screen.getByTestId("onboarding-continue") as HTMLButtonElement;
const heading = () => screen.getByRole("heading", { level: 1 });

/** The birthday fields are CustomSelects: open one, click its option. */
function pickDob(field: string, value: string) {
  fireEvent.click(screen.getByTestId(`onboarding-dob-${field}`));
  fireEvent.click(screen.getByTestId(`onboarding-dob-${field}-${value}`));
}
function dayOptions(): string[] {
  fireEvent.click(screen.getByTestId("onboarding-dob-day"));
  const days = screen.getAllByTestId(/^onboarding-dob-day-\d+$/).map(el => el.getAttribute("data-testid")!.split("-").pop()!);
  fireEvent.click(screen.getByTestId("onboarding-dob-day"));
  return days;
}

function resetAll() {
  vi.clearAllMocks();
  localStorage.clear();
  user = { userId: "user_a", userName: "Ada Lovelace" };
  authed = true;
  seedRoute = null;
  reducedMotion(true);
  onboardingCoursesSearch.mockImplementation(allCourses);
  fetchFlags.mockImplementation(async () => ({}));
}

describe("Onboarding: the draft", () => {
  beforeEach(resetAll);
  afterEach(cleanup);

  it("never shows another account's draft, and drops the legacy key", async () => {
    seedDraft("user_b", { ...AT_CONNECT, name: "Bob" });
    localStorage.setItem("sapling_onboarding_draft", JSON.stringify({ ...AT_CONNECT, name: "Legacy" }));
    render(<Onboarding />);
    // Fresh account → the name screen, prefilled from Google, not user_b's draft.
    const name = (await screen.findByTestId("onboarding-name")) as HTMLInputElement;
    expect(name.value).toBe("Ada");
    expect(localStorage.getItem("sapling_onboarding_draft")).toBeNull();
    expect(storedDraft("user_b").name).toBe("Bob");
  });

  it("never reads a signed-out visitor's guest draft", async () => {
    localStorage.setItem(GUEST_DRAFT_KEY, JSON.stringify({ ...AT_CONNECT, name: "Sam", savedAt: Date.now() }));
    render(<Onboarding />);
    expect(((await screen.findByTestId("onboarding-name")) as HTMLInputElement).value).toBe("Ada");
    expect(continueBtn().textContent).toBe("Next");
  });

  it("restores the draft under the account's own key, stamped for its expiry", async () => {
    seedDraft("user_a", AT_CONNECT);
    render(<Onboarding />);
    await waitFor(() => expect(continueBtn().textContent).toBe("Finish"));
    const stored = storedDraft();
    expect(stored.screen).toBe(CONNECT);
    expect(Math.abs(stored.savedAt - Date.now())).toBeLessThan(5_000);
  });

  it("drops a draft older than seven days, and one with no date", async () => {
    seedDraft("user_a", AT_CONNECT, Date.now() - DRAFT_TTL_MS - 1000);
    const view = render(<Onboarding />);
    expect(await screen.findByTestId("onboarding-name")).toBeTruthy();
    view.unmount();
    localStorage.setItem(onboardingDraftKey("user_a"), JSON.stringify(AT_CONNECT));
    render(<Onboarding />);
    expect(await screen.findByTestId("onboarding-name")).toBeTruthy();
  });

  it("resumes a draft six days old", async () => {
    seedDraft("user_a", AT_CONNECT, Date.now() - 6 * 24 * 60 * 60 * 1000);
    render(<Onboarding />);
    await waitFor(() => expect(continueBtn().textContent).toBe("Finish"));
  });

  it("ignores a draft from the previous onboarding shape", async () => {
    seedDraft("user_a", { first_name: "Ada", step: 5, course_ids: ["c1"] });
    render(<Onboarding />);
    expect(await screen.findByTestId("onboarding-name")).toBeTruthy();
  });
});

describe("Onboarding: signed in only", () => {
  beforeEach(resetAll);
  afterEach(cleanup);

  it("sends a signed-out visitor to sign in", async () => {
    user = { userId: "", userName: "" };
    authed = false;
    render(<Onboarding />);
    await waitFor(() => expect(replace).toHaveBeenCalledWith("/?signin=1"));
  });

  it("keeps the local-seed hold redirect (#715)", async () => {
    seedRoute = "/setting-up";
    render(<Onboarding />);
    await waitFor(() => expect(replace).toHaveBeenCalledWith("/setting-up"));
  });

  it("has a visible Sign out on every screen that signs out and leaves", async () => {
    seedDraft("user_a", { ...AT_CONNECT, screen: 3, done: [0, 1] });
    render(<Onboarding />);
    await screen.findByText("What are you taking this term?");
    fireEvent.click(screen.getByTestId("onboarding-sign-out"));
    await waitFor(() => expect(replace).toHaveBeenCalledWith("/"));
    expect(signOut).toHaveBeenCalled();
    expect(storedDraft()).toBeNull();
  });

  it("draws its own graph, and every mark is the shared wordmark", async () => {
    render(<Onboarding />);
    await screen.findByTestId("onboarding-name");
    expect(document.querySelector("canvas.ob-canvas")).not.toBeNull();
    const marks = [...document.querySelectorAll<HTMLImageElement>(".ob-logo img")];
    expect(marks.length).toBeGreaterThan(0);
    for (const m of marks) expect(m.getAttribute("src")).toBe(SAPLING_WORDMARK_SRC);
  });
});

describe("Onboarding: screens", () => {
  beforeEach(resetAll);
  afterEach(() => {
    cleanup();
    vi.useRealTimers();
  });

  it("gates each screen: name, birthday (13+), school, year + course", async () => {
    render(<Onboarding />);
    const name = await screen.findByTestId("onboarding-name");
    fireEvent.change(name, { target: { value: "  " } });
    expect(continueBtn().disabled).toBe(true);
    fireEvent.change(name, { target: { value: "Ada" } });
    fireEvent.click(continueBtn());

    const thisYear = new Date().getFullYear();
    pickDob("month", "1");
    pickDob("day", "1");
    pickDob("year", String(thisYear - 16));
    expect(screen.getByTestId("onboarding-minor-note").textContent).toMatch(
      /under 18, your profile starts private and sharing with your class starts\s+off/,
    );
    expect(screen.queryByText(/study-room invites/)).toBeNull();
    fireEvent.click(continueBtn());

    expect(continueBtn().disabled).toBe(true);
    fireEvent.click(screen.getByTestId("onboarding-school-bu"));
    fireEvent.click(continueBtn());

    expect(continueBtn().disabled).toBe(true);
    fireEvent.click(screen.getByTestId("onboarding-year-junior"));
    fireEvent.click(await screen.findByTestId("onboarding-course-result-c1"));
    expect(screen.getByTestId("onboarding-course-remove-c1").textContent).toContain("CAS CS 111");
    expect(continueBtn().disabled).toBe(false);
    fireEvent.click(continueBtn());
    expect(screen.getByText("Your notes become a map.")).toBeTruthy();
  });

  it("the name field's label and placeholder agree", async () => {
    render(<Onboarding />);
    const name = await screen.findByTestId("onboarding-name");
    expect(name.getAttribute("aria-label")).toBe("Your first name");
    expect(name.getAttribute("placeholder")).toBe("Your first name");
  });

  it("offers only the days the chosen month and year have", async () => {
    seedDraft("user_a", { ...AT_CONNECT, dobM: "", dobD: "", dobY: "", screen: 1, done: [] });
    render(<Onboarding />);
    await screen.findByText("When's your birthday?");
    expect(dayOptions()).toHaveLength(31);
    pickDob("month", "2");
    expect(dayOptions()).toHaveLength(29); // no year yet: a leap year
    pickDob("year", "2001");
    expect(dayOptions()).toHaveLength(28);
    pickDob("month", "1");
    pickDob("day", "31");
    pickDob("month", "4");
    // April has no 31st: the day is cleared rather than kept invalid.
    expect(screen.getByTestId("onboarding-dob-day").textContent).toContain("Day");
    expect(dayOptions()).toHaveLength(30);
  });

  it("the year list goes back 100 years", async () => {
    seedDraft("user_a", { ...AT_CONNECT, dobM: "", dobD: "", dobY: "", screen: 1, done: [] });
    render(<Onboarding />);
    await screen.findByText("When's your birthday?");
    const thisYear = new Date().getFullYear();
    fireEvent.click(screen.getByTestId("onboarding-dob-year"));
    expect(screen.getByTestId(`onboarding-dob-year-${thisYear - 100}`)).toBeTruthy();
    expect(screen.queryByTestId(`onboarding-dob-year-${thisYear - 101}`)).toBeNull();
  });

  it("an under-13 answer says what is true, keeps nothing, and holds for a day in this browser", async () => {
    seedDraft("user_a", { ...AT_CONNECT, dobM: "", dobD: "", dobY: "", screen: 1, done: [0] });
    const view = render(<Onboarding />);
    await screen.findByText("When's your birthday?");
    pickDob("month", "1");
    pickDob("day", "1");
    pickDob("year", String(new Date().getFullYear() - 10));

    const panel = screen.getByTestId("onboarding-blocked");
    expect(panel.textContent).toContain("13 and up");
    expect(panel.textContent).toContain("Signing in with Google created a Sapling account");
    expect(panel.textContent).toContain("haven't kept your birthday");
    expect(panel.textContent).not.toContain("haven't saved anything");
    expect(document.activeElement).toBe(screen.getByTestId("onboarding-blocked-title"));
    // No straight retry: the date fields and the old "I made a mistake" are gone.
    expect(screen.queryByTestId("onboarding-dob-year")).toBeNull();
    expect(screen.queryByTestId("onboarding-dob-fix")).toBeNull();
    expect(continueBtn().disabled).toBe(true);
    // Nothing they entered is kept: not the birthday, not the name.
    await waitFor(() => expect(storedDraft().dobY).toBe(""));
    expect(storedDraft().name).toBe("");

    // A reload (or another account) in this browser is still blocked...
    view.unmount();
    render(<Onboarding />);
    await screen.findByTestId("onboarding-blocked");
    cleanup();
    // ...until the day is up.
    const until = Number(localStorage.getItem("sapling_age_gate_until"));
    expect(until - Date.now()).toBeGreaterThan(AGE_GATE_MS - 60_000);
    localStorage.setItem("sapling_age_gate_until", String(Date.now() - 1));
    render(<Onboarding />);
    await screen.findByText("When's your birthday?");
    expect(screen.queryByTestId("onboarding-blocked")).toBeNull();
    expect(screen.getByTestId("onboarding-dob-year")).toBeTruthy();
  });

  it("the under-13 panel signs out", async () => {
    localStorage.setItem("sapling_age_gate_until", String(Date.now() + 1000 * 60));
    seedDraft("user_a", { ...AT_CONNECT, screen: 1, done: [] });
    render(<Onboarding />);
    fireEvent.click(await screen.findByTestId("onboarding-blocked-sign-out"));
    await waitFor(() => expect(signOut).toHaveBeenCalled());
  });

  it("a school that isn't listed gets an honest answer, the beta list and a way out", async () => {
    seedDraft("user_a", { ...AT_CONNECT, school: "", screen: 2, done: [0] });
    render(<Onboarding />);
    await screen.findByText("Where do you study?");
    const toggle = screen.getByTestId("onboarding-school-missing");
    expect(toggle.getAttribute("aria-expanded")).toBe("false");
    fireEvent.click(toggle);
    expect(toggle.getAttribute("aria-expanded")).toBe("true");
    const panel = screen.getByTestId("onboarding-school-missing-panel");
    expect(panel.textContent).toContain("open to Boston University students for now");
    expect(screen.getByTestId("onboarding-beta-link").getAttribute("href")).toBe("/#newsletter");
    fireEvent.click(screen.getByTestId("onboarding-school-sign-out"));
    await waitFor(() => expect(signOut).toHaveBeenCalled());
  });

  it("the coming-soon schools carry no opacity on their text", async () => {
    seedDraft("user_a", { ...AT_CONNECT, screen: 2, done: [0] });
    render(<Onboarding />);
    await screen.findByText("Where do you study?");
    // The rule lives in onboarding.css; the tiles carry no inline opacity either.
    for (const tile of document.querySelectorAll<HTMLElement>(".ob-school--soon")) {
      expect(tile.style.opacity).toBe("");
      expect(tile.getAttribute("aria-disabled")).toBeNull();
    }
  });

  it("a failed course search says so and retries, never 'no matches'", async () => {
    onboardingCoursesSearch.mockRejectedValueOnce(new Error("Failed to fetch"));
    seedDraft("user_a", { ...AT_CONNECT, courses: [], screen: 3, done: [0, 1] });
    render(<Onboarding />);
    const error = await screen.findByTestId("onboarding-course-search-error");
    expect(error.textContent).toContain("couldn't search the course list");
    expect(screen.queryByTestId("onboarding-course-search-empty")).toBeNull();
    expect(screen.getByTestId("onboarding-course-search-status").textContent).toContain("didn't work");
    fireEvent.click(screen.getByTestId("onboarding-course-search-retry"));
    expect(await screen.findByTestId("onboarding-course-result-c1")).toBeTruthy();
    expect(screen.queryByTestId("onboarding-course-search-error")).toBeNull();
  });

  it("an empty search says no courses match", async () => {
    onboardingCoursesSearch.mockResolvedValue({ courses: [] });
    seedDraft("user_a", { ...AT_CONNECT, courses: [], screen: 3, done: [0, 1] });
    render(<Onboarding />);
    expect((await screen.findByTestId("onboarding-course-search-empty")).textContent).toContain("No courses match");
  });

  it("Enter in the course search adds the top result instead of moving on", async () => {
    seedDraft("user_a", { ...AT_CONNECT, courses: [], screen: 3, done: [0, 1] });
    render(<Onboarding />);
    const input = await screen.findByTestId("onboarding-course-search");
    await screen.findByTestId("onboarding-course-result-c1");
    fireEvent.keyDown(input, { key: "Enter" });
    expect(screen.getByTestId("onboarding-course-remove-c1")).toBeTruthy();
    expect(screen.getByText("What are you taking this term?")).toBeTruthy();
    // Again: the top result is already added, so nothing changes.
    fireEvent.keyDown(input, { key: "Enter" });
    expect(screen.getByTestId("onboarding-course-remove-c1")).toBeTruthy();
    expect(screen.getByText("What are you taking this term?")).toBeTruthy();
  });

  it("'My courses aren't listed' moves on with no courses, and saves none", async () => {
    seedDraft("user_a", { ...AT_CONNECT, courses: [COURSES[1]], screen: 3, done: [0, 1] });
    submitOnboardingProfile.mockResolvedValue({ ok: true, courses_linked: 0 });
    render(<Onboarding />);
    await screen.findByText("What are you taking this term?");
    const later = screen.getByTestId("onboarding-courses-later");
    fireEvent.click(later);
    expect(later.getAttribute("aria-pressed")).toBe("true");
    expect(screen.queryByTestId("onboarding-course-remove-c2")).toBeNull();
    expect(screen.getByTestId("onboarding-courses-later-note")).toBeTruthy();
    expect(continueBtn().disabled).toBe(false);
    // Picking a course again undoes it.
    fireEvent.click(await screen.findByTestId("onboarding-course-result-c1"));
    expect(later.getAttribute("aria-pressed")).toBe("false");
    fireEvent.click(later);
    // On to the end and finish.
    for (let i = 0; i < 5; i++) fireEvent.click(continueBtn());
    expect(continueBtn().textContent).toBe("Finish");
    fireEvent.click(continueBtn());
    await waitFor(() => expect(submitOnboardingProfile).toHaveBeenCalled());
    expect(submitOnboardingProfile.mock.calls[0][0].course_ids).toEqual([]);
  });

  it("legal screens show the published document, and need the end reached and the box ticked", async () => {
    const scrollHeight = Object.getOwnPropertyDescriptor(HTMLElement.prototype, "scrollHeight");
    const clientHeight = Object.getOwnPropertyDescriptor(HTMLElement.prototype, "clientHeight");
    Object.defineProperty(HTMLElement.prototype, "scrollHeight", { configurable: true, get() { return this.classList.contains("ob-doc-body") ? 1000 : 0; } });
    Object.defineProperty(HTMLElement.prototype, "clientHeight", { configurable: true, get() { return this.classList.contains("ob-doc-body") ? 200 : 0; } });
    try {
      seedDraft("user_a", { ...AT_CONNECT, screen: 6, termsEnd: false, termsOk: false, privEnd: false, privOk: false, done: [0, 1, 2, 3] });
      render(<Onboarding />);
      await screen.findByRole("heading", { level: 1, name: "Terms of Service" });
      const body = screen.getByTestId("onboarding-legal-body");
      expect(within(body).getByText(TERMS.sections[4].body!)).toBeTruthy();
      expect(screen.getByTestId("onboarding-legal-updated").textContent).toBe("Last updated: October 22, 2026");

      const agree = screen.getByTestId("onboarding-agree") as HTMLButtonElement;
      const hint = screen.getByTestId("onboarding-agree-hint");
      expect(hint.textContent).toBe("Scroll to the end to accept.");
      expect(agree.getAttribute("aria-describedby")).toBe(hint.id);
      expect(agree.getAttribute("title")).toBeNull();
      expect(agree.disabled).toBe(true);
      expect(continueBtn().disabled).toBe(true);

      body.scrollTop = 800;
      fireEvent.scroll(body);
      await waitFor(() => expect(agree.disabled).toBe(false));
      expect(screen.queryByTestId("onboarding-agree-hint")).toBeNull();
      expect(agree.getAttribute("aria-describedby")).toBeNull();
      fireEvent.click(agree);
      expect(continueBtn().disabled).toBe(false);

      fireEvent.click(continueBtn());
      await screen.findByRole("heading", { level: 1, name: "Privacy Policy" });
      expect(screen.getByTestId("onboarding-legal-updated").textContent).toBe("Last updated: November 3, 2026");
      expect(within(screen.getByTestId("onboarding-legal-body")).getByText(PRIVACY.sections[5].bodyAfter!)).toBeTruthy();
    } finally {
      if (scrollHeight) Object.defineProperty(HTMLElement.prototype, "scrollHeight", scrollHeight);
      if (clientHeight) Object.defineProperty(HTMLElement.prototype, "clientHeight", clientHeight);
    }
  });

  it("Escape goes back a screen, and so does the visible Back button", async () => {
    seedDraft("user_a", { ...AT_CONNECT, screen: 3, done: [0, 1] });
    render(<Onboarding />);
    await screen.findByText("What are you taking this term?");
    fireEvent.keyDown(window, { key: "Escape" });
    expect(await screen.findByText("Where do you study?")).toBeTruthy();
    const back = screen.getByTestId("onboarding-back");
    expect(back.tagName).toBe("BUTTON");
    // Reachable from the keyboard (the old one was tabIndex -1 and hidden on phones).
    expect(back.getAttribute("tabindex")).toBeNull();
    fireEvent.click(back);
    expect(await screen.findByText("When's your birthday?")).toBeTruthy();
  });

  it("has no Back on the first screen", async () => {
    render(<Onboarding />);
    await screen.findByTestId("onboarding-name");
    expect(screen.queryByTestId("onboarding-back")).toBeNull();
  });
});

describe("Onboarding: accessibility", () => {
  beforeEach(resetAll);
  afterEach(() => {
    cleanup();
    vi.useRealTimers();
  });

  it("moves focus to each new screen's heading", async () => {
    render(<Onboarding />);
    await screen.findByTestId("onboarding-name");
    await waitFor(() => expect(document.activeElement).toBe(heading()));
    expect(heading().textContent).toBe("First, what should I call you?");
    fireEvent.click(continueBtn());
    await waitFor(() => expect(document.activeElement?.textContent).toBe("When's your birthday?"));
    expect(document.activeElement?.tagName).toBe("H1");
  });

  it("exposes 'Step n of 6' on the progress strip", async () => {
    seedDraft("user_a", { ...AT_CONNECT, screen: 3, done: [0, 1] });
    render(<Onboarding />);
    await screen.findByText("What are you taking this term?");
    expect(screen.getByTestId("onboarding-step").textContent).toBe("Step 3 of 6: Your courses");
  });

  it("keeps the screens inert while they are hidden for the intro", async () => {
    reducedMotion(false);
    vi.useFakeTimers();
    render(<Onboarding />);
    const content = document.querySelector(".ob-content")!;
    expect(content.getAttribute("aria-hidden")).toBe("true");
    expect(content.hasAttribute("inert")).toBe(true);
    expect(continueBtn().disabled).toBe(true);
    // The form arrives a fade after the zoom starts (INTRO_DONE = 3200).
    await act(async () => { vi.advanceTimersByTime(2600); });
    expect(content.hasAttribute("inert")).toBe(true);
    await act(async () => { vi.advanceTimersByTime(700); });
    expect(content.hasAttribute("inert")).toBe(false);
    expect(content.getAttribute("aria-hidden")).toBe("false");
    expect(continueBtn().disabled).toBe(false);
  });

  it("the consent sheet holds focus, closes on Esc without going back, and returns focus", async () => {
    seedDraft("user_a", AT_CONNECT);
    render(<Onboarding />);
    const connect = await screen.findByTestId("onboarding-connect-gradescope");
    connect.focus();
    fireEvent.click(connect);
    const sheet = screen.getByTestId("onboarding-consent");
    expect(sheet.getAttribute("role")).toBe("dialog");
    const go = screen.getByTestId("onboarding-consent-continue");
    const cancel = screen.getByTestId("onboarding-consent-cancel");
    await waitFor(() => expect(document.activeElement).toBe(go));
    // Tab from the last control wraps to the first.
    cancel.focus();
    fireEvent.keyDown(cancel, { key: "Tab" });
    expect(document.activeElement).toBe(go);
    // The screens behind it are inert while it is open.
    expect(document.querySelector(".ob-content")!.hasAttribute("inert")).toBe(true);
    fireEvent.keyDown(go, { key: "Escape" });
    expect(screen.queryByTestId("onboarding-consent")).toBeNull();
    expect(heading().textContent).toBe("Connect your accounts");
    await waitFor(() => expect(document.activeElement).toBe(screen.getByTestId("onboarding-connect-gradescope")));
  });

  it("mounts the outro's live region empty and fills it when the outro starts", async () => {
    seedDraft("user_a", AT_CONNECT);
    submitOnboardingProfile.mockReturnValue(new Promise(() => {}));
    render(<Onboarding />);
    await screen.findByText("Finish");
    const outro = document.querySelector(".ob-moment--outro")!;
    expect(outro.getAttribute("aria-live")).toBe("polite");
    expect(outro.textContent).toBe("");
    fireEvent.click(continueBtn());
    expect(outro.textContent).toContain("Welcome to");
    expect(outro.querySelector("img")?.getAttribute("alt")).toBe("Sapling");
  });
});

describe("Onboarding: Finish", () => {
  beforeEach(resetAll);
  afterEach(() => {
    cleanup();
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it("saves the profile with the legal versions and under_18, refreshes the name, and goes to the dashboard", async () => {
    seedDraft("user_a", AT_CONNECT);
    submitOnboardingProfile.mockResolvedValueOnce({ ok: true, courses_linked: 1 });
    render(<Onboarding />);
    fireEvent.click(await screen.findByText("Finish"));
    await waitFor(() => expect(replace).toHaveBeenCalledWith("/dashboard"));
    expect(submitOnboardingProfile).toHaveBeenCalledWith(
      {
        user_id: "user_a", first_name: "Ada", last_name: "Lovelace", year: "junior", course_ids: ["c1"],
        under_18: false, accepted_terms_version: TERMS_VERSION, accepted_privacy_version: PRIVACY_VERSION,
      },
      { signal: expect.any(AbortSignal) },
    );
    expect(TERMS_VERSION).toBe("2026-10-22");
    expect(PRIVACY_VERSION).toBe("2026-11-03");
    expect(updateSettings).not.toHaveBeenCalled();
    expect(refreshProfile).toHaveBeenCalled();
    // Marked onboarded before leaving, so the shell doesn't send them back.
    expect(markOnboarded).toHaveBeenCalled();
    expect(markOnboarded.mock.invocationCallOrder[0]).toBeLessThan(replace.mock.invocationCallOrder[0]);
    expect(storedDraft()).toBeNull();
  });

  it("a whole name typed into the field is not saved with the last name twice", async () => {
    seedDraft("user_a", { ...AT_CONNECT, name: "Ada Lovelace" });
    submitOnboardingProfile.mockResolvedValueOnce({ ok: true });
    render(<Onboarding />);
    fireEvent.click(await screen.findByText("Finish"));
    await waitFor(() => expect(submitOnboardingProfile).toHaveBeenCalled());
    expect(submitOnboardingProfile.mock.calls[0][0]).toMatchObject({ first_name: "Ada", last_name: "Lovelace" });
  });

  it("an under-18 account sends under_18 with the save, and nothing else", async () => {
    const dobY = String(new Date().getFullYear() - 16);
    seedDraft("user_a", { ...AT_CONNECT, dobM: "1", dobD: "1", dobY });
    submitOnboardingProfile.mockResolvedValueOnce({ ok: true });
    render(<Onboarding />);
    fireEvent.click(await screen.findByText("Finish"));
    await waitFor(() => expect(replace).toHaveBeenCalledWith("/dashboard"));
    expect(submitOnboardingProfile.mock.calls[0][0].under_18).toBe(true);
    expect(updateSettings).not.toHaveBeenCalled();
  });

  it("shows 'Setting up…' while the white hand-off waits on the save", async () => {
    seedDraft("user_a", AT_CONNECT);
    let resolve: (v: unknown) => void = () => {};
    submitOnboardingProfile.mockReturnValueOnce(new Promise(r => { resolve = r; }));
    render(<Onboarding />);
    await screen.findByText("Finish");
    const status = screen.getByTestId("onboarding-setting-up");
    expect(status.getAttribute("role")).toBe("status");
    expect(status.textContent).toBe("");
    fireEvent.click(continueBtn());
    expect(status.textContent).toBe("Setting up…");
    expect(replace).not.toHaveBeenCalled();
    await act(async () => { resolve({ ok: true }); });
    await waitFor(() => expect(replace).toHaveBeenCalledWith("/dashboard"));
  });

  it("with motion, the outro plays before the hand-off and the status shows once it is white", async () => {
    reducedMotion(false);
    seedDraft("user_a", AT_CONNECT);
    let resolve: (v: unknown) => void = () => {};
    submitOnboardingProfile.mockReturnValueOnce(new Promise(r => { resolve = r; }));
    vi.useFakeTimers();
    render(<Onboarding />);
    await act(async () => {});
    fireEvent.click(continueBtn());
    const status = screen.getByTestId("onboarding-setting-up");
    await act(async () => { vi.advanceTimersByTime(3000); });
    expect(status.textContent).toBe("");
    await act(async () => { vi.advanceTimersByTime(1500); });
    expect(status.textContent).toBe("Setting up…");
    expect(replace).not.toHaveBeenCalled();
    await act(async () => { resolve({ ok: true }); });
    expect(replace).toHaveBeenCalledWith("/dashboard");
  });

  it("an already-onboarded account (409) goes to the dashboard and says so", async () => {
    seedDraft("user_a", AT_CONNECT);
    submitOnboardingProfile.mockRejectedValueOnce(new ApiError('{"detail":"Onboarding is already complete."}', 409));
    render(<Onboarding />);
    fireEvent.click(await screen.findByText("Finish"));
    await waitFor(() => expect(replace).toHaveBeenCalledWith("/dashboard"));
    expect(toast.info).toHaveBeenCalledWith("Your account was already set up.");
    expect(toast.error).not.toHaveBeenCalled();
    expect(markOnboarded).toHaveBeenCalled();
    expect(storedDraft()).toBeNull();
  });

  it("an account that isn't approved (403 not_approved) goes to /pending", async () => {
    seedDraft("user_a", AT_CONNECT);
    submitOnboardingProfile.mockRejectedValueOnce(new ApiError(
      '{"detail":{"code":"not_approved"}}', 403, { body: { detail: { code: "not_approved" } } },
    ));
    render(<Onboarding />);
    fireEvent.click(await screen.findByText("Finish"));
    await waitFor(() => expect(replace).toHaveBeenCalledWith("/pending"));
    expect(markOnboarded).not.toHaveBeenCalled();
    expect(toast.error).not.toHaveBeenCalled();
  });

  it("courses that no longer exist (422 no_known_courses) go back to the courses screen with a message", async () => {
    seedDraft("user_a", AT_CONNECT);
    submitOnboardingProfile.mockRejectedValueOnce(new ApiError("", 422, {
      body: { detail: { code: "no_known_courses", message: "None of those courses exist." } },
    }));
    render(<Onboarding />);
    fireEvent.click(await screen.findByText("Finish"));
    await screen.findByText("What are you taking this term?");
    const notice = screen.getByTestId("onboarding-notice");
    expect(notice.textContent).toContain("None of the courses you picked are in the catalog any more");
    expect(heading().getAttribute("aria-describedby")).toBe(notice.id);
    await waitFor(() => expect(document.activeElement).toBe(heading()));
    expect(screen.queryByTestId("onboarding-course-remove-c1")).toBeNull();
    expect(replace).not.toHaveBeenCalled();
    expect(toast.error).not.toHaveBeenCalled();
  });

  it("an outdated Terms or Privacy Policy (422 legal_outdated) goes back to the Terms with a message", async () => {
    seedDraft("user_a", AT_CONNECT);
    submitOnboardingProfile.mockRejectedValueOnce(new ApiError("", 422, {
      body: { detail: { code: "legal_outdated", message: "Please accept the current terms." } },
    }));
    render(<Onboarding />);
    fireEvent.click(await screen.findByText("Finish"));
    await screen.findByRole("heading", { level: 1, name: "Terms of Service" });
    expect(screen.getByTestId("onboarding-notice").textContent).toContain("changed after this page opened");
    expect(screen.getByTestId("onboarding-legal-reload")).toBeTruthy();
    const stored = storedDraft();
    expect([stored.termsOk, stored.privOk]).toEqual([false, false]);
    expect(replace).not.toHaveBeenCalled();
  });

  it("any other failure keeps the draft, says so in words (never raw JSON), and returns to the form", async () => {
    seedDraft("user_a", AT_CONNECT);
    submitOnboardingProfile.mockRejectedValueOnce(new ApiError('{"detail":{"oops":true}}', 500, { body: { detail: { oops: true } } }));
    render(<Onboarding />);
    fireEvent.click(await screen.findByText("Finish"));
    await waitFor(() => expect(toast.error).toHaveBeenCalled());
    const message = toast.error.mock.calls[0][0] as string;
    expect(message).not.toMatch(/[{}]/);
    expect(message).toBe("Something went wrong on our end. Try again in a moment.");
    expect(replace).not.toHaveBeenCalled();
    expect(storedDraft()).not.toBeNull();
    await waitFor(() => expect(continueBtn().disabled).toBe(false));
    expect(screen.getByTestId("onboarding-setting-up").textContent).toBe("");
  });
});

describe("Onboarding: Connect", () => {
  beforeEach(resetAll);
  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it("explains Gradescope truthfully and says what will happen, then lands on the gradebook", async () => {
    seedDraft("user_a", AT_CONNECT);
    submitOnboardingProfile.mockResolvedValueOnce({ ok: true });
    render(<Onboarding />);
    fireEvent.click(await screen.findByTestId("onboarding-connect-gradescope"));
    const sheet = screen.getByTestId("onboarding-consent");
    expect(sheet.textContent).toContain("sign in to Gradescope");
    expect(sheet.textContent).toContain("Assignment names and due dates");
    expect(sheet.textContent).toContain("Scores are encrypted");
    fireEvent.click(screen.getByTestId("onboarding-consent-continue"));
    const chosen = screen.getByTestId("onboarding-connect-gradescope");
    expect(chosen.textContent).toBe("Will connect after setup");
    expect(screen.queryByText(/Connected ✓/)).toBeNull();
    fireEvent.click(continueBtn());
    await waitFor(() => expect(replace).toHaveBeenCalledWith("/gradebook"));
  });

  it("a chosen account can be un-chosen", async () => {
    seedDraft("user_a", { ...AT_CONNECT, conn: { gradescope: true } });
    render(<Onboarding />);
    const chosen = await screen.findByTestId("onboarding-connect-gradescope");
    expect(chosen.textContent).toBe("Will connect after setup");
    fireEvent.click(chosen);
    expect(screen.getByTestId("onboarding-connect-gradescope").textContent).toBe("Connect");
  });

  it("Google Calendar is a full page load to its consent flow, back to the gradebook when Gradescope was chosen too", async () => {
    const assign = vi.fn();
    vi.stubGlobal("location", { ...window.location, assign, reload: vi.fn() });
    seedDraft("user_a", { ...AT_CONNECT, conn: { gradescope: true } });
    submitOnboardingProfile.mockResolvedValueOnce({ ok: true });
    render(<Onboarding />);
    fireEvent.click(await screen.findByTestId("onboarding-connect-gcal"));
    expect(screen.getByTestId("onboarding-consent").textContent).toContain("Google will ask for your permission");
    fireEvent.click(screen.getByTestId("onboarding-consent-continue"));
    fireEvent.click(continueBtn());
    await waitFor(() => expect(assign).toHaveBeenCalledWith("/api/calendar/auth-url?user_id=user_a&next=%2Fgradebook"));
    expect(replace).not.toHaveBeenCalled();
  });

  it("Google Calendar alone goes to its consent flow with no next", async () => {
    const assign = vi.fn();
    vi.stubGlobal("location", { ...window.location, assign, reload: vi.fn() });
    seedDraft("user_a", { ...AT_CONNECT, conn: { gcal: true } });
    submitOnboardingProfile.mockResolvedValueOnce({ ok: true });
    render(<Onboarding />);
    fireEvent.click(await screen.findByText("Finish"));
    await waitFor(() => expect(assign).toHaveBeenCalledWith("/api/calendar/auth-url?user_id=user_a"));
  });

  it("Skip for now clears the choices and goes to the dashboard", async () => {
    const assign = vi.fn();
    vi.stubGlobal("location", { ...window.location, assign, reload: vi.fn() });
    seedDraft("user_a", { ...AT_CONNECT, conn: { gcal: true, gradescope: true } });
    submitOnboardingProfile.mockResolvedValueOnce({ ok: true });
    render(<Onboarding />);
    fireEvent.click(await screen.findByTestId("onboarding-skip"));
    await waitFor(() => expect(replace).toHaveBeenCalledWith("/dashboard"));
    expect(assign).not.toHaveBeenCalled();
  });

  it("leaves out Google Calendar while hide_calendar is on (its API answers 404)", async () => {
    fetchFlags.mockResolvedValue({ hide_calendar: "on" });
    seedDraft("user_a", AT_CONNECT);
    render(<Onboarding />);
    await screen.findByTestId("onboarding-connect-gradescope");
    await waitFor(() => expect(fetchFlags).toHaveBeenCalled());
    expect(screen.queryByTestId("onboarding-connect-gcal")).toBeNull();
  });

  it("drops a Calendar choice made before hide_calendar went on: Finish goes to the dashboard", async () => {
    const assign = vi.fn();
    vi.stubGlobal("location", { ...window.location, assign, reload: vi.fn() });
    fetchFlags.mockResolvedValue({ hide_calendar: "on" });
    seedDraft("user_a", { ...AT_CONNECT, conn: { gcal: true } });
    submitOnboardingProfile.mockResolvedValueOnce({ ok: true });
    render(<Onboarding />);
    await waitFor(() => expect(fetchFlags).toHaveBeenCalled());
    await act(async () => {});
    fireEvent.click(await screen.findByText("Finish"));
    await waitFor(() => expect(replace).toHaveBeenCalledWith("/dashboard"));
    expect(assign).not.toHaveBeenCalled();
  });

  it("with flags unreadable it uses this browser's last copy, and with none leaves the flagged options out", async () => {
    fetchFlags.mockRejectedValue(new Error("down"));
    seedDraft("user_a", AT_CONNECT);
    const view = render(<Onboarding />);
    await screen.findByTestId("onboarding-connect-canvas");
    await waitFor(() => expect(fetchFlags).toHaveBeenCalled());
    await act(async () => {});
    expect(screen.queryByTestId("onboarding-connect-gcal")).toBeNull();
    expect(screen.queryByTestId("onboarding-connect-gradescope")).toBeNull();
    view.unmount();
    localStorage.setItem("sapling.flags.v1:user_a", JSON.stringify({ hide_grades: "on" }));
    render(<Onboarding />);
    expect(await screen.findByTestId("onboarding-connect-gcal")).toBeTruthy();
    expect(screen.queryByTestId("onboarding-connect-gradescope")).toBeNull();
  });

  it("accounts Sapling can't connect yet say 'Coming soon' and record nothing", async () => {
    seedDraft("user_a", AT_CONNECT);
    render(<Onboarding />);
    for (const key of ["blackboard", "canvas", "classroom"]) {
      const tag = await screen.findByTestId(`onboarding-connect-${key}`);
      expect(tag.tagName).not.toBe("BUTTON");
      expect(tag.textContent).toBe("Coming soon");
    }
    expect(screen.queryByText("Notify me")).toBeNull();
  });
});

describe("onboarding course search: latest query wins (#802/#769)", () => {
  beforeEach(resetAll);
  afterEach(cleanup);

  it("a slow reply for 'fe' can't replace the results for 'fe 223'", async () => {
    const pending: Record<string, (v: SearchReply) => void> = {};
    onboardingCoursesSearch.mockImplementation((q: string) =>
      q === "fe 223"
        ? Promise.resolve({ courses: [{ id: "c-fe223", course_code: "QST FE 223", course_name: "Introduction to Corporate Finance" }] })
        : q === "fe"
          ? new Promise<SearchReply>(res => { pending.fe = res; })
          : Promise.resolve({ courses: [] }),
    );
    seedDraft("user_a", { ...AT_CONNECT, courses: [], screen: 3, done: [0, 1] });
    render(<Onboarding />);
    const input = await screen.findByTestId("onboarding-course-search");

    fireEvent.change(input, { target: { value: "fe" } });
    await waitFor(() => expect(pending.fe).toBeDefined(), { timeout: 2000 });
    fireEvent.change(input, { target: { value: "fe 223" } });
    expect(await screen.findByText("QST FE 223", undefined, { timeout: 2000 })).toBeTruthy();

    await act(async () => {
      pending.fe({ courses: [{ id: "c-fe101", course_code: "QST FE 101", course_name: "Free Enterprise" }] });
    });
    expect(screen.queryByText("QST FE 101")).toBeNull();
    expect(screen.getByText("QST FE 223")).toBeTruthy();
  });
});

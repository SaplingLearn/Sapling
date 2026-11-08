// @vitest-environment jsdom
/**
 * The Claude Design onboarding: per-account draft (#757), screen gating, the
 * 409 "already onboarded" hand-off, failure recovery, and where Finish lands.
 * Reduced motion is on throughout, so the intro/outro choreography is skipped.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, cleanup, waitFor, fireEvent, screen, act } from "@testing-library/react";

const replace = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ replace }) }));

const signOut = vi.fn(async () => {});
let user = { userId: "user_a", userName: "Ada Lovelace" };
let authed = true;
vi.mock("@/context/UserContext", () => ({
  useUser: () => ({ ...user, userReady: true, isAuthenticated: authed, signOut }),
}));

// The real modal runs a Google popup; this stand-in signs in on click.
vi.mock("@/components/marketing/SignInModal", () => ({
  default: ({ open, onClose, onSignedIn }: { open: boolean; onClose: () => void; onSignedIn?: () => void }) =>
    open ? (
      <button data-testid="signin-modal" onClick={() => { onSignedIn?.(); onClose(); }}>Sign in</button>
    ) : null,
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
vi.mock("@/lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api")>()),
  submitOnboardingProfile: (...a: unknown[]) => submitOnboardingProfile(...a),
  updateSettings: (...a: unknown[]) => updateSettings(...(a as [])),
  onboardingCoursesSearch: async () => ({ courses: COURSES }),
}));

import { Onboarding, onboardingDraftKey, ageOn, GUEST_OWNER } from "./Onboarding";
import { ApiError } from "@/lib/api";

const CONNECT = 8; // index of the last screen
const AT_CONNECT = {
  name: "Ada", dobM: "4", dobD: "12", dobY: "2000", school: "bu", year: "junior",
  courses: [COURSES[0]], termsEnd: true, termsOk: true, privEnd: true, privOk: true,
  conn: {}, screen: CONNECT, done: [0, 1, 2, 3, 4],
};

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

describe("Onboarding", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    localStorage.clear();
    user = { userId: "user_a", userName: "Ada Lovelace" };
    authed = true;
    seedRoute = null;
    reducedMotion(true);
  });
  afterEach(cleanup);

  it("never shows another account's draft, and drops the legacy key", async () => {
    localStorage.setItem(onboardingDraftKey("user_b"), JSON.stringify({ ...AT_CONNECT, name: "Bob" }));
    localStorage.setItem("sapling_onboarding_draft", JSON.stringify({ ...AT_CONNECT, name: "Legacy" }));
    render(<Onboarding />);
    // Fresh account → the name screen, prefilled from Google, not user_b's draft.
    const name = (await screen.findByTestId("onboarding-name")) as HTMLInputElement;
    expect(name.value).toBe("Ada");
    expect(localStorage.getItem("sapling_onboarding_draft")).toBeNull();
    expect(JSON.parse(localStorage.getItem(onboardingDraftKey("user_b"))!).name).toBe("Bob");
  });

  it("restores the draft under the account's own key", async () => {
    localStorage.setItem(onboardingDraftKey("user_a"), JSON.stringify(AT_CONNECT));
    render(<Onboarding />);
    await waitFor(() => expect(continueBtn().textContent).toBe("Finish"));
    expect(JSON.parse(localStorage.getItem(onboardingDraftKey("user_a"))!).screen).toBe(CONNECT);
  });

  it("ignores a draft from the previous onboarding shape", async () => {
    localStorage.setItem(onboardingDraftKey("user_a"), JSON.stringify({ first_name: "Ada", step: 5, course_ids: ["c1"] }));
    render(<Onboarding />);
    expect(await screen.findByTestId("onboarding-name")).toBeTruthy();
  });

  it("gates each screen: name, birthday (13+), school, year + course", async () => {
    render(<Onboarding />);
    const name = await screen.findByTestId("onboarding-name");
    fireEvent.change(name, { target: { value: "  " } });
    expect(continueBtn().disabled).toBe(true);
    fireEvent.change(name, { target: { value: "Ada" } });
    fireEvent.click(continueBtn());

    // Birthday: under 13 blocks, 13+ continues.
    const thisYear = new Date().getFullYear();
    fireEvent.change(screen.getByTestId("onboarding-dob-month"), { target: { value: "1" } });
    fireEvent.change(screen.getByTestId("onboarding-dob-day"), { target: { value: "1" } });
    fireEvent.change(screen.getByTestId("onboarding-dob-year"), { target: { value: String(thisYear - 10) } });
    expect(screen.getByRole("alert").textContent).toContain("13 and up");
    expect(continueBtn().disabled).toBe(true);
    fireEvent.click(screen.getByTestId("onboarding-dob-fix"));
    fireEvent.change(screen.getByTestId("onboarding-dob-year"), { target: { value: String(thisYear - 16) } });
    expect(screen.getByText(/under 18/)).toBeTruthy();
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

  it("legal screens need the box ticked, and the box needs the end reached", async () => {
    localStorage.setItem(onboardingDraftKey("user_a"), JSON.stringify({
      ...AT_CONNECT, screen: 6, termsEnd: false, termsOk: false, privEnd: false, privOk: false, done: [0, 1, 2, 3],
    }));
    render(<Onboarding />);
    await screen.findByText("Terms of Service");
    expect(continueBtn().disabled).toBe(true);
    // jsdom lays nothing out, so the panel has no overflow: the end counts as reached.
    await waitFor(() => expect((screen.getByTestId("onboarding-agree") as HTMLButtonElement).disabled).toBe(false));
    fireEvent.click(screen.getByTestId("onboarding-agree"));
    expect(continueBtn().disabled).toBe(false);
  });

  it("finishing saves the profile without majors or a learning style and goes to the dashboard", async () => {
    localStorage.setItem(onboardingDraftKey("user_a"), JSON.stringify(AT_CONNECT));
    submitOnboardingProfile.mockResolvedValueOnce({ user_id: "user_a", courses_linked: ["c1"] });
    render(<Onboarding />);
    fireEvent.click(await screen.findByText("Finish"));
    await waitFor(() => expect(replace).toHaveBeenCalledWith("/dashboard"));
    expect(submitOnboardingProfile).toHaveBeenCalledWith({
      user_id: "user_a", first_name: "Ada", last_name: "Lovelace", year: "junior", course_ids: ["c1"],
    });
    expect(updateSettings).not.toHaveBeenCalled();
    expect(localStorage.getItem(onboardingDraftKey("user_a"))).toBeNull();
  });

  it("an under-18 account starts with sharing off", async () => {
    const dobY = String(new Date().getFullYear() - 16);
    localStorage.setItem(onboardingDraftKey("user_a"), JSON.stringify({ ...AT_CONNECT, dobM: "1", dobD: "1", dobY }));
    submitOnboardingProfile.mockResolvedValueOnce({ user_id: "user_a", courses_linked: ["c1"] });
    render(<Onboarding />);
    fireEvent.click(await screen.findByText("Finish"));
    await waitFor(() => expect(replace).toHaveBeenCalledWith("/dashboard"));
    expect(updateSettings).toHaveBeenCalledWith("user_a", { profile_visibility: "private", share_class_context: false });
  });

  it("choosing Gradescope lands on the gradebook", async () => {
    localStorage.setItem(onboardingDraftKey("user_a"), JSON.stringify(AT_CONNECT));
    submitOnboardingProfile.mockResolvedValueOnce({ user_id: "user_a", courses_linked: ["c1"] });
    render(<Onboarding />);
    fireEvent.click(await screen.findByTestId("onboarding-connect-gradescope"));
    fireEvent.click(screen.getByTestId("onboarding-consent-continue"));
    expect(screen.getByTestId("onboarding-connect-gradescope").textContent).toBe("Connected ✓");
    fireEvent.click(continueBtn());
    await waitFor(() => expect(replace).toHaveBeenCalledWith("/gradebook"));
  });

  it("an already-onboarded account (409) goes to the dashboard and drops its draft", async () => {
    localStorage.setItem(onboardingDraftKey("user_a"), JSON.stringify(AT_CONNECT));
    submitOnboardingProfile.mockRejectedValueOnce(new ApiError("Onboarding is already complete.", 409));
    render(<Onboarding />);
    fireEvent.click(await screen.findByText("Finish"));
    await waitFor(() => expect(replace).toHaveBeenCalledWith("/dashboard"));
    expect(toast.error).not.toHaveBeenCalled();
    expect(localStorage.getItem(onboardingDraftKey("user_a"))).toBeNull();
  });

  it("any other failure keeps the draft, says so, and returns to the form", async () => {
    localStorage.setItem(onboardingDraftKey("user_a"), JSON.stringify(AT_CONNECT));
    submitOnboardingProfile.mockRejectedValueOnce(new ApiError("boom", 500));
    render(<Onboarding />);
    fireEvent.click(await screen.findByText("Finish"));
    await waitFor(() => expect(toast.error).toHaveBeenCalled());
    expect(replace).not.toHaveBeenCalled();
    expect(localStorage.getItem(onboardingDraftKey("user_a"))).not.toBeNull();
    await waitFor(() => expect(continueBtn().disabled).toBe(false));
  });

  it("plays the intro before showing the form when motion is allowed", async () => {
    reducedMotion(false);
    vi.useFakeTimers();
    try {
      render(<Onboarding />);
      expect(continueBtn().disabled).toBe(true);
      await act(async () => { vi.advanceTimersByTime(2600); });
      expect(continueBtn().disabled).toBe(false);
    } finally {
      vi.useRealTimers();
    }
  });

  it("Escape goes back a screen", async () => {
    localStorage.setItem(onboardingDraftKey("user_a"), JSON.stringify({ ...AT_CONNECT, screen: 2, done: [0] }));
    render(<Onboarding />);
    await screen.findByText("Where do you study?");
    fireEvent.keyDown(window, { key: "Escape" });
    expect(await screen.findByText("When's your birthday?")).toBeTruthy();
  });
});

describe("ageOn", () => {
  it("counts a birthday later this year as not yet reached", () => {
    const today = new Date(2026, 10, 7);
    expect(ageOn(today, "11", "8", "2013")).toBe(12);
    expect(ageOn(today, "11", "7", "2013")).toBe(13);
    expect(ageOn(today, "", "7", "2013")).toBeNull();
  });
});

describe("Onboarding over the landing (Get Started)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    localStorage.clear();
    seedRoute = null;
    reducedMotion(true);
  });
  afterEach(cleanup);

  it("a signed-out visitor goes through as a guest: no redirect, no prefilled name", async () => {
    user = { userId: "", userName: "" };
    authed = false;
    render(<Onboarding takeover />);
    const name = (await screen.findByTestId("onboarding-name")) as HTMLInputElement;
    expect(name.value).toBe("");
    expect(replace).not.toHaveBeenCalled();
    fireEvent.change(name, { target: { value: "Sam" } });
    await waitFor(() => expect(JSON.parse(localStorage.getItem(onboardingDraftKey(GUEST_OWNER))!).name).toBe("Sam"));
  });

  it("a guest's Finish signs in first, then saves their answers under the account", async () => {
    user = { userId: "", userName: "" };
    authed = false;
    localStorage.setItem(onboardingDraftKey(GUEST_OWNER), JSON.stringify({ ...AT_CONNECT, name: "Sam" }));
    submitOnboardingProfile.mockResolvedValueOnce({ user_id: "user_new", courses_linked: ["c1"] });
    const view = render(<Onboarding takeover />);
    fireEvent.click(await screen.findByText("Finish"));
    expect(submitOnboardingProfile).not.toHaveBeenCalled();
    // Signing in: the modal reports success, and the account becomes current.
    fireEvent.click(screen.getByTestId("signin-modal"));
    user = { userId: "user_new", userName: "Sam Rivera" };
    authed = true;
    view.rerender(<Onboarding takeover />);
    await waitFor(() => expect(replace).toHaveBeenCalledWith("/dashboard"));
    expect(submitOnboardingProfile).toHaveBeenCalledWith(expect.objectContaining({
      user_id: "user_new", first_name: "Sam", last_name: "Rivera", course_ids: ["c1"],
    }));
    expect(localStorage.getItem(onboardingDraftKey(GUEST_OWNER))).toBeNull();
  });

  it("closing sign-in without signing in saves nothing", async () => {
    user = { userId: "", userName: "" };
    authed = false;
    localStorage.setItem(onboardingDraftKey(GUEST_OWNER), JSON.stringify(AT_CONNECT));
    render(<Onboarding takeover />);
    fireEvent.click(await screen.findByText("Finish"));
    expect(screen.getByTestId("signin-modal")).toBeTruthy();
    expect(submitOnboardingProfile).not.toHaveBeenCalled();
  });

  it("a signed-in account is treated as new: no local-seed redirect away from the flow", async () => {
    user = { userId: "user_a", userName: "Ada Lovelace" };
    authed = true;
    seedRoute = "/setting-up";
    render(<Onboarding takeover />);
    await screen.findByTestId("onboarding-name");
    await new Promise(r => setTimeout(r, 20));
    expect(replace).not.toHaveBeenCalled();
  });

  it("the /onboarding route picks up a guest draft after a same-tab sign-in", async () => {
    localStorage.setItem(onboardingDraftKey(GUEST_OWNER), JSON.stringify({ ...AT_CONNECT, name: "Sam" }));
    user = { userId: "user_new", userName: "Sam Rivera" };
    authed = true;
    render(<Onboarding />);
    await waitFor(() => expect(continueBtn().textContent).toBe("Finish"));
    expect(localStorage.getItem(onboardingDraftKey(GUEST_OWNER))).toBeNull();
    expect(JSON.parse(localStorage.getItem(onboardingDraftKey("user_new"))!).name).toBe("Sam");
  });
});

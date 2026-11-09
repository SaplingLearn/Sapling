// @vitest-environment jsdom
/**
 * #757: the onboarding draft is scoped to the signed-in account, and a replay
 * the server refuses (409, already onboarded) goes to the dashboard instead of
 * surfacing an error.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, cleanup, waitFor, fireEvent, screen, act } from "@testing-library/react";

const replace = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ replace }) }));

let user = { userId: "user_a", userName: "Ada Lovelace" };
vi.mock("@/context/UserContext", () => ({
  useUser: () => ({ ...user, userReady: true, isAuthenticated: true, signOut: vi.fn() }),
}));

const toast = { success: vi.fn(), error: vi.fn(), info: vi.fn() };
vi.mock("@/components/ToastProvider", () => ({ useToast: () => toast }));

vi.mock("@/lib/localSeed", () => ({ onboardingRedirect: async () => null }));

const submitOnboardingProfile = vi.fn();
type SearchReply = { courses: { id: string; course_code: string; course_name: string }[] };
const noCourses = async (): Promise<SearchReply> => ({ courses: [] });
const onboardingCoursesSearch = vi.fn<(q: string) => Promise<SearchReply>>(noCourses);
vi.mock("@/lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api")>()),
  submitOnboardingProfile: (...a: unknown[]) => submitOnboardingProfile(...a),
  onboardingCoursesSearch: (q: string) => onboardingCoursesSearch(q),
}));

import { Onboarding, onboardingDraftKey } from "./Onboarding";
import { ApiError } from "@/lib/api";

const FINAL_DRAFT = {
  first_name: "Ada", last_name: "Lovelace", school: "Boston University", year: "junior",
  majors: ["Math"], minors: [], course_ids: ["c1"], course_cache: [],
  // PKG-14b: the learning-style step is gone, so the final step is index 4
  step: 4,
};

describe("#757 onboarding draft is per account", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    localStorage.clear();
    user = { userId: "user_a", userName: "Ada Lovelace" };
  });
  afterEach(cleanup);

  it("never shows another account's draft", async () => {
    localStorage.setItem(onboardingDraftKey("user_b"), JSON.stringify({ ...FINAL_DRAFT, first_name: "Bob" }));
    localStorage.setItem("sapling_onboarding_draft", JSON.stringify({ ...FINAL_DRAFT, first_name: "Legacy" }));
    render(<Onboarding />);
    // Fresh account → the welcome step, not user_b's (or the legacy) step 5.
    await waitFor(() => expect(screen.getByTestId("onboarding-continue").textContent).toBe("Continue"));
    expect(screen.queryByTestId("onboarding-back")).toBeNull();
    // The legacy unscoped draft is dropped, and user_b's is left alone.
    expect(localStorage.getItem("sapling_onboarding_draft")).toBeNull();
    expect(JSON.parse(localStorage.getItem(onboardingDraftKey("user_b"))!).first_name).toBe("Bob");
  });

  it("saves and restores the draft under the account's own key", async () => {
    localStorage.setItem(onboardingDraftKey("user_a"), JSON.stringify(FINAL_DRAFT));
    render(<Onboarding />);
    await waitFor(() => expect(screen.getByTestId("onboarding-continue").textContent).toBe("Enter Sapling →"));
    expect(JSON.parse(localStorage.getItem(onboardingDraftKey("user_a"))!).step).toBe(4);
  });

  it("an already-onboarded account (409) goes to the dashboard and drops its draft", async () => {
    localStorage.setItem(onboardingDraftKey("user_a"), JSON.stringify(FINAL_DRAFT));
    submitOnboardingProfile.mockRejectedValueOnce(new ApiError("Onboarding is already complete.", 409));
    render(<Onboarding />);
    const button = await screen.findByText("Enter Sapling →");
    fireEvent.click(button);
    await waitFor(() => expect(replace).toHaveBeenCalledWith("/dashboard"));
    expect(toast.error).not.toHaveBeenCalled();
    expect(localStorage.getItem(onboardingDraftKey("user_a"))).toBeNull();
  });

  it("any other failure keeps the draft and says so", async () => {
    localStorage.setItem(onboardingDraftKey("user_a"), JSON.stringify(FINAL_DRAFT));
    submitOnboardingProfile.mockRejectedValueOnce(new ApiError("boom", 500));
    render(<Onboarding />);
    fireEvent.click(await screen.findByText("Enter Sapling →"));
    await waitFor(() => expect(toast.error).toHaveBeenCalled());
    expect(replace).not.toHaveBeenCalledWith("/dashboard");
    expect(localStorage.getItem(onboardingDraftKey("user_a"))).not.toBeNull();
  });
});

describe("onboarding course search: latest query wins (#769)", () => {
  beforeEach(() => {
    localStorage.clear();
    user = { userId: "user_a", userName: "Ada Lovelace" };
  });
  afterEach(() => {
    cleanup();
    onboardingCoursesSearch.mockImplementation(noCourses);
  });

  it("a slow reply for 'fe' can't replace the results for 'fe 223'", async () => {
    const pending: Record<string, (v: SearchReply) => void> = {};
    onboardingCoursesSearch.mockImplementation((q: string) =>
      q === "fe 223"
        ? Promise.resolve({ courses: [{ id: "c-fe223", course_code: "QST FE 223", course_name: "Introduction to Corporate Finance" }] })
        : q === "fe"
          ? new Promise<SearchReply>(res => { pending.fe = res; })
          : Promise.resolve({ courses: [] }),
    );
    localStorage.setItem(onboardingDraftKey("user_a"), JSON.stringify({ ...FINAL_DRAFT, course_ids: [], step: 4 }));
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

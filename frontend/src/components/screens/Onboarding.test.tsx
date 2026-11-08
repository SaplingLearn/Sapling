// @vitest-environment jsdom
/**
 * #757: the onboarding draft is scoped to the signed-in account, and a replay
 * the server refuses (409, already onboarded) goes to the dashboard instead of
 * surfacing an error.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, cleanup, waitFor, fireEvent, screen } from "@testing-library/react";

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
vi.mock("@/lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api")>()),
  submitOnboardingProfile: (...a: unknown[]) => submitOnboardingProfile(...a),
  onboardingCoursesSearch: async () => ({ courses: [] }),
}));

import { Onboarding, onboardingDraftKey } from "./Onboarding";
import { ApiError } from "@/lib/api";

const FINAL_DRAFT = {
  first_name: "Ada", last_name: "Lovelace", school: "Boston University", year: "junior",
  majors: ["Math"], minors: [], course_ids: ["c1"], course_cache: [],
  learning_style: "visual", step: 5,
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
    expect(JSON.parse(localStorage.getItem(onboardingDraftKey("user_a"))!).step).toBe(5);
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

// @vitest-environment jsdom
/**
 * Profile-form prefill (finding F8): the Settings profile form must render the
 * user's CURRENT display name / username / bio / location / website, not empty
 * inputs. Blank inputs risk a save wiping the stored values.
 *
 * The `/settings` payload can come back with those identity fields unset even
 * though `GET /api/profile/{user}` carries them; the component seeds the form
 * from the public profile as a fallback so the inputs reflect what's stored.
 */

import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, cleanup, fireEvent, act, waitFor } from "@testing-library/react";
import type { PostHog } from "posthog-js";
import type { UserProfile, UserSettings } from "@/lib/types";
import { __resetAnalyticsForTests, initAnalytics } from "@/lib/analytics";

vi.mock("@/context/UserContext", () => ({
  useUser: () => ({
    userId: "u1",
    userName: "Rich Active",
    avatarUrl: null,
    userReady: true,
    signOut: vi.fn(),
    refreshProfile: vi.fn(),
    setAvatarUrl: vi.fn(),
  }),
}));

vi.mock("@/lib/useLayoutPref", () => ({ useLayoutPref: () => ["sidebar", vi.fn()] }));
vi.mock("@/lib/useScrollLock", () => ({ useScrollLock: () => {} }));

const toast = vi.hoisted(() => ({
  error: vi.fn(), success: vi.fn(), info: vi.fn(), warn: vi.fn(), show: vi.fn(), dismiss: vi.fn(),
}));
vi.mock("../ToastProvider", () => ({ useToast: () => toast }));

// Stub presentational children so this exercises the profile form only.
vi.mock("../TopBar", () => ({ TopBar: () => null }));
vi.mock("../FullHeightScreen", () => ({ FullHeightScreen: ({ children }: { children: React.ReactNode }) => <div>{children}</div> }));
vi.mock("../Icon", () => ({ Icon: () => null }));
vi.mock("../Avatar", () => ({ Avatar: () => null }));
vi.mock("../CustomSelect", () => ({ CustomSelect: () => null }));
vi.mock("../ProfileView", () => ({ ProfileView: () => null }));
vi.mock("../Skeleton", () => ({ SettingsFormSkeleton: () => null }));
vi.mock("next/link", () => ({ default: ({ children }: { children: React.ReactNode }) => children }));

vi.mock("@/lib/api", () => ({
  fetchSettings: vi.fn(),
  fetchPublicProfile: vi.fn(),
  updateSettings: vi.fn(),
  deleteAccount: vi.fn(),
  updateProfile: vi.fn(),
  checkUsername: vi.fn(),
  uploadAvatar: vi.fn(),
  fetchCosmetics: vi.fn(),
  fetchCosmeticsCatalog: vi.fn(),
  equipCosmetic: vi.fn(),
  exportData: vi.fn(),
}));

import { Settings } from "./Settings";
import { fetchSettings, fetchPublicProfile, updateSettings } from "@/lib/api";

function settings(overrides: Partial<UserSettings> = {}): UserSettings {
  return {
    display_name: null,
    username: null,
    bio: null,
    location: null,
    website: null,
    notification_email: true,
    notification_push: false,
    notification_in_app: true,
    theme: "light",
    font_size: "medium",
    accent_color: "#2b5221",
    profile_visibility: "public",
    activity_status_visible: true,
    ...overrides,
  };
}

function profile(overrides: Partial<UserProfile> = {}): UserProfile {
  return {
    id: "u1",
    name: "Rich Active",
    username: "rich-active",
    bio: "Learning things",
    location: "Boston, MA",
    website: "example.com",
    avatar_url: null,
    created_at: null,
    year: null,
    majors: [],
    minors: [],
    school: null,
    roles: [],
    featured_achievements: [],
    equipped_cosmetics: {},
    stats: {} as UserProfile["stats"],
    ...overrides,
  };
}

beforeEach(() => {
  window.localStorage.clear();
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("Settings profile form prefill (F8)", () => {
  it("seeds the inputs from the public profile when /settings omits the identity fields", async () => {
    // Bug scenario: /settings returns the identity fields unset …
    vi.mocked(fetchSettings).mockResolvedValue(settings());
    // … but the profile carries the stored values.
    vi.mocked(fetchPublicProfile).mockResolvedValue(profile());

    render(<Settings />);

    // Display name / bio / location / website (uncontrolled defaultValue inputs).
    expect(await screen.findByDisplayValue("Rich Active")).toBeInTheDocument();
    expect(screen.getByDisplayValue("Learning things")).toBeInTheDocument();
    expect(screen.getByDisplayValue("Boston, MA")).toBeInTheDocument();
    expect(screen.getByDisplayValue("example.com")).toBeInTheDocument();
    // Username (controlled input, seeded via usernameDraft).
    expect(screen.getByPlaceholderText("your-handle")).toHaveValue("rich-active");
  });

  it("prefers the /settings values when they are already populated", async () => {
    vi.mocked(fetchSettings).mockResolvedValue(
      settings({
        display_name: "Settings Name",
        username: "settings-handle",
        bio: "Settings bio",
      }),
    );
    vi.mocked(fetchPublicProfile).mockResolvedValue(
      profile({ name: "Profile Name", username: "profile-handle", bio: "Profile bio" }),
    );

    render(<Settings />);

    expect(await screen.findByDisplayValue("Settings Name")).toBeInTheDocument();
    expect(screen.getByDisplayValue("Settings bio")).toBeInTheDocument();
    expect(screen.getByPlaceholderText("your-handle")).toHaveValue("settings-handle");
    expect(screen.queryByDisplayValue("Profile Name")).toBeNull();
  });
});

function fakePosthog() {
  let optedOut = false;
  return {
    init: vi.fn(),
    has_opted_out_capturing: () => optedOut,
    opt_out_capturing: vi.fn(() => void (optedOut = true)),
    opt_in_capturing: vi.fn(() => void (optedOut = false)),
  };
}

async function startAnalytics(ph: ReturnType<typeof fakePosthog>) {
  await act(async () => {
    await initAnalytics({ NEXT_PUBLIC_POSTHOG_KEY: "phc_test" }, async () => ph as unknown as PostHog);
  });
}

describe("Settings → Data: product analytics opt-out", () => {
  beforeEach(() => {
    __resetAnalyticsForTests();
    vi.mocked(fetchSettings).mockResolvedValue(settings());
    vi.mocked(fetchPublicProfile).mockResolvedValue(profile());
    vi.mocked(updateSettings).mockReset().mockResolvedValue(settings());
    toast.error.mockClear();
  });
  afterEach(() => {
    __resetAnalyticsForTests();
    vi.restoreAllMocks();
  });

  it("renders a disabled switch when analytics is not running in this build", async () => {
    render(<Settings />);
    fireEvent.click(screen.getByTestId("settings-tab-data"));
    const toggle = await screen.findByTestId("settings-analytics-toggle");
    expect(toggle).toBeDisabled();
    expect(toggle).toHaveAttribute("role", "switch");
    expect(toggle).toHaveAttribute("aria-checked", "false");
    expect(toggle).toHaveAttribute("aria-labelledby", "settings-analytics-label");
    expect(screen.getByTestId("settings-analytics-note")).toHaveTextContent(/isn't running/);
    fireEvent.click(toggle);
    expect(updateSettings).not.toHaveBeenCalled();
  });

  it("opts out and back in through posthog-js, saving each choice to the account", async () => {
    const ph = fakePosthog();
    await startAnalytics(ph);
    render(<Settings />);
    await waitFor(() => expect(fetchSettings).toHaveBeenCalled());
    fireEvent.click(screen.getByTestId("settings-tab-data"));
    const toggle = await screen.findByTestId("settings-analytics-toggle");
    expect(toggle).toBeEnabled();
    expect(toggle).toHaveAttribute("aria-checked", "true");
    expect(screen.getByTestId("settings-analytics-note")).toHaveTextContent(/every browser/);

    fireEvent.click(toggle);
    expect(ph.opt_out_capturing).toHaveBeenCalledTimes(1);
    expect(toggle).toHaveAttribute("aria-checked", "false");
    expect(updateSettings).toHaveBeenLastCalledWith("u1", { analytics_opt_out: true });

    fireEvent.click(toggle);
    expect(ph.opt_in_capturing).toHaveBeenCalledTimes(1);
    expect(toggle).toHaveAttribute("aria-checked", "true");
    expect(updateSettings).toHaveBeenLastCalledWith("u1", { analytics_opt_out: false });
  });

  it("does not apply the account preference itself — the UserProvider owns that", async () => {
    vi.mocked(fetchSettings).mockResolvedValue(settings({ analytics_opt_out: true }));
    const ph = fakePosthog();
    await startAnalytics(ph);
    render(<Settings />);
    await waitFor(() => expect(fetchSettings).toHaveBeenCalled());
    await act(async () => {});
    expect(ph.opt_out_capturing).not.toHaveBeenCalled();
  });

  it("a failed opt-OUT save keeps this browser opted out and says so", async () => {
    vi.mocked(updateSettings).mockRejectedValue(new Error("500"));
    vi.spyOn(console, "error").mockImplementation(() => {});
    const ph = fakePosthog();
    await startAnalytics(ph);
    render(<Settings />);
    fireEvent.click(screen.getByTestId("settings-tab-data"));
    const toggle = await screen.findByTestId("settings-analytics-toggle");
    fireEvent.click(toggle);
    await waitFor(() => expect(toast.error).toHaveBeenCalledWith(expect.stringMatching(/still applies in this browser/)));
    expect(toggle).toHaveAttribute("aria-checked", "false");
    expect(ph.opt_in_capturing).not.toHaveBeenCalled();
  });

  it("a failed opt-IN save reverts to off and says it failed — never 'applies in this browser'", async () => {
    vi.mocked(updateSettings).mockRejectedValue(new Error("500"));
    vi.spyOn(console, "error").mockImplementation(() => {});
    const ph = fakePosthog();
    ph.opt_out_capturing(); // currently off
    ph.opt_out_capturing.mockClear();
    await startAnalytics(ph);
    render(<Settings />);
    fireEvent.click(screen.getByTestId("settings-tab-data"));
    const toggle = await screen.findByTestId("settings-analytics-toggle");
    expect(toggle).toHaveAttribute("aria-checked", "false");
    fireEvent.click(toggle);
    expect(ph.opt_in_capturing).toHaveBeenCalledTimes(1);
    await waitFor(() => expect(toast.error).toHaveBeenCalledWith(expect.stringMatching(/Couldn't turn product analytics back on/)));
    expect(toast.error).not.toHaveBeenCalledWith(expect.stringMatching(/applies in this browser/));
    expect(ph.opt_out_capturing).toHaveBeenCalledTimes(1);
    expect(toggle).toHaveAttribute("aria-checked", "false");
  });

  it("a backend without the field leaves this browser's own opt-out in force", async () => {
    // settings() carries no analytics_opt_out — the pre-#677 payload.
    const ph = fakePosthog();
    ph.opt_out_capturing(); // opted out locally earlier
    await startAnalytics(ph);
    render(<Settings />);
    await waitFor(() => expect(fetchSettings).toHaveBeenCalled());
    fireEvent.click(screen.getByTestId("settings-tab-data"));
    const toggle = await screen.findByTestId("settings-analytics-toggle");
    expect(toggle).toHaveAttribute("aria-checked", "false");
    expect(ph.opt_in_capturing).not.toHaveBeenCalled();
  });

  it("the switch is disabled under Do Not Track / GPC", async () => {
    await startAnalytics(fakePosthog());
    Object.defineProperty(navigator, "globalPrivacyControl", { value: true, configurable: true });
    try {
      render(<Settings />);
      fireEvent.click(screen.getByTestId("settings-tab-data"));
      const toggle = await screen.findByTestId("settings-analytics-toggle");
      expect(toggle).toBeDisabled();
      expect(toggle).toHaveAttribute("aria-checked", "false");
      expect(screen.getByTestId("settings-analytics-note")).toHaveTextContent(/Do Not Track/);
    } finally {
      delete (navigator as { globalPrivacyControl?: boolean }).globalPrivacyControl;
    }
  });
});

describe("Settings → Notifications toggles (shared Toggle)", () => {
  beforeEach(() => {
    vi.mocked(fetchSettings).mockResolvedValue(settings({ notification_push: false }));
    vi.mocked(fetchPublicProfile).mockResolvedValue(profile());
    vi.mocked(updateSettings).mockReset().mockResolvedValue(settings());
  });

  it("render as labelled switches and still PATCH their own field", async () => {
    render(<Settings />);
    await waitFor(() => expect(fetchSettings).toHaveBeenCalled());
    fireEvent.click(screen.getByTestId("settings-tab-notifications"));
    const push = await screen.findByTestId("settings-toggle-notification_push");
    expect(push).toHaveAttribute("role", "switch");
    expect(push).toHaveAttribute("aria-checked", "false");
    expect(screen.getByRole("switch", { name: "Push" })).toBe(push);
    fireEvent.click(push);
    expect(push).toHaveAttribute("aria-checked", "true");
    expect(updateSettings).toHaveBeenCalledWith("u1", { notification_push: true });
  });
});

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
import { __resetAnalyticsForTests, setProductAnalyticsFlag } from "@/lib/analytics";
import { __resetAccountSettingsForTests } from "@/lib/accountSettings";

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

/**
 * Reset analytics for a build that does (or does not) send pageviews, with
 * posthog-js stubbed out and the admin flag as given. The account answer
 * comes from Settings' OWN read (fetchSettings, through lib/accountSettings).
 */
function analyticsBuild({ configured = true, flag = true, load }: { configured?: boolean; flag?: boolean; load?: () => Promise<PostHog> } = {}) {
  __resetAnalyticsForTests({
    env: configured ? { NEXT_PUBLIC_POSTHOG_KEY: "phc_test" } : {},
    load:
      load ??
      (async () =>
        ({
          init: (_k: string, c: { loaded?: () => void }) => c.loaded?.(),
          identify: vi.fn(),
          get_distinct_id: () => "anon",
          get_property: () => undefined,
          reset: vi.fn(),
        }) as unknown as PostHog),
  });
  __resetAccountSettingsForTests();
  if (flag) setProductAnalyticsFlag(true);
}

/** The account's `analytics_opt_out`, as GET /settings answers it (undefined = field missing). */
function accountSays(optOut: boolean | undefined) {
  vi.mocked(fetchSettings).mockResolvedValue(settings(optOut === undefined ? {} : { analytics_opt_out: optOut }));
}

/** A PATCH the test resolves or rejects by hand. */
function deferredPatch() {
  let resolve!: () => void;
  let reject!: (e: Error) => void;
  const promise = new Promise<UserSettings>((res, rej) => {
    resolve = () => res(settings());
    reject = rej;
  });
  return { promise, resolve, reject };
}

describe("Settings → Data: product analytics opt-out", () => {
  beforeEach(() => {
    analyticsBuild();
    accountSays(false);
    vi.mocked(fetchPublicProfile).mockResolvedValue(profile());
    vi.mocked(updateSettings).mockReset().mockResolvedValue(settings());
    toast.error.mockClear();
  });
  afterEach(() => {
    __resetAnalyticsForTests();
    __resetAccountSettingsForTests();
    delete (navigator as { globalPrivacyControl?: boolean }).globalPrivacyControl;
    window.history.replaceState({}, "", "/");
    vi.restoreAllMocks();
  });

  async function openDataTab() {
    render(<Settings />);
    await waitFor(() => expect(fetchSettings).toHaveBeenCalled());
    fireEvent.click(screen.getByTestId("settings-tab-data"));
    return screen.findByTestId("settings-analytics-toggle");
  }
  const note = () => screen.getByTestId("settings-analytics-note");

  it("describes everything PostHog receives, tied to the account ID — not just pageviews", async () => {
    await openDataTab();
    const card = screen.getByTestId("settings-analytics");
    for (const claim of [/app pages you view/, /actions you take/, /AI model, token counts and cost/, /error reports/, /Sapling account ID/, /stops all of this/]) {
      expect(card).toHaveTextContent(claim);
    }
    expect(card).not.toHaveTextContent(/pseudonymous/i);
  });

  it("works in a build that sends no pageviews: the account governs the backend mirror too", async () => {
    analyticsBuild({ configured: false });
    const toggle = await openDataTab();
    await waitFor(() => expect(toggle).toBeEnabled());
    expect(toggle).toHaveAttribute("role", "switch");
    expect(toggle).toHaveAttribute("aria-labelledby", "settings-analytics-label");
    expect(toggle).toHaveAttribute("aria-checked", "true");
    expect(note()).toHaveTextContent(/On — saved to your account/);
    expect(note()).not.toHaveTextContent(/nothing is being collected/i);
    fireEvent.click(toggle);
    expect(updateSettings).toHaveBeenLastCalledWith("u1", { analytics_opt_out: true });
    await waitFor(() => expect(note()).toHaveTextContent(/Off — saved to your account/));
  });

  it("works while the admin product_analytics flag is off (#620/#677)", async () => {
    analyticsBuild({ flag: false });
    accountSays(true);
    const toggle = await openDataTab();
    await waitFor(() => expect(toggle).toBeEnabled());
    expect(toggle).toHaveAttribute("aria-checked", "false");
    fireEvent.click(toggle);
    expect(updateSettings).toHaveBeenLastCalledWith("u1", { analytics_opt_out: false });
    await waitFor(() => expect(toggle).toHaveAttribute("aria-checked", "true"));
  });

  it("is disabled only until the account answer has arrived", async () => {
    let answer!: (s: UserSettings) => void;
    vi.mocked(fetchSettings).mockReturnValue(new Promise<UserSettings>((r) => (answer = r)));
    const toggle = await openDataTab();
    expect(toggle).toBeDisabled();
    expect(note()).toHaveTextContent(/Loading your saved setting/);
    await act(async () => answer(settings({ analytics_opt_out: false })));
    expect(toggle).toBeEnabled();
    expect(toggle).toHaveAttribute("aria-checked", "true");
  });

  it("a failed read: disabled with a Try again that unsticks it", async () => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    vi.mocked(fetchSettings).mockRejectedValueOnce(new Error("500"));
    const toggle = await openDataTab();
    await waitFor(() => expect(note()).toHaveTextContent(/couldn't load your saved setting/));
    expect(toggle).toBeDisabled();
    fireEvent.click(screen.getByTestId("settings-analytics-reload"));
    await waitFor(() => expect(toggle).toBeEnabled());
    expect(toggle).toHaveAttribute("aria-checked", "true");
    expect(screen.queryByTestId("settings-analytics-reload")).toBeNull();
  });

  it("a missing field: usable, shown off, and switching it on saves an explicit answer", async () => {
    accountSays(undefined);
    const toggle = await openDataTab();
    await waitFor(() => expect(toggle).toBeEnabled());
    expect(toggle).toHaveAttribute("aria-checked", "false");
    expect(note()).toHaveTextContent(/No choice is saved to your account yet/);
    fireEvent.click(toggle);
    expect(updateSettings).toHaveBeenLastCalledWith("u1", { analytics_opt_out: false });
    await waitFor(() => expect(toggle).toHaveAttribute("aria-checked", "true"));
  });

  it("under Do Not Track / GPC: usable, and says this browser sends no page views", async () => {
    Object.defineProperty(navigator, "globalPrivacyControl", { value: true, configurable: true });
    const toggle = await openDataTab();
    await waitFor(() => expect(toggle).toBeEnabled());
    expect(toggle).toHaveAttribute("aria-checked", "true");
    expect(note()).toHaveTextContent(/Do Not Track or Global Privacy Control/);
    expect(note()).toHaveTextContent(/this browser sends no page views/);
    fireEvent.click(toggle);
    expect(updateSettings).toHaveBeenLastCalledWith("u1", { analytics_opt_out: true });
  });

  it("shows the account's opt-out", async () => {
    accountSays(true);
    const toggle = await openDataTab();
    await waitFor(() => expect(toggle).toBeEnabled());
    expect(toggle).toHaveAttribute("aria-checked", "false");
    expect(note()).toHaveTextContent(/Off — saved to your account/);
  });

  it("opt-OUT flips at once, then saves to the account", async () => {
    const toggle = await openDataTab();
    await waitFor(() => expect(toggle).toHaveAttribute("aria-checked", "true"));
    const patch = deferredPatch();
    vi.mocked(updateSettings).mockReturnValueOnce(patch.promise);
    fireEvent.click(toggle);
    expect(toggle).toHaveAttribute("aria-checked", "false"); // before the save resolved
    expect(updateSettings).toHaveBeenLastCalledWith("u1", { analytics_opt_out: true });
    await act(async () => patch.resolve());
    await waitFor(() => expect(toggle).toBeEnabled());
  });

  it("opt-IN saves to the account FIRST and only then flips on", async () => {
    accountSays(true);
    const toggle = await openDataTab();
    await waitFor(() => expect(toggle).toBeEnabled());
    const patch = deferredPatch();
    vi.mocked(updateSettings).mockReturnValueOnce(patch.promise);
    fireEvent.click(toggle);
    expect(updateSettings).toHaveBeenLastCalledWith("u1", { analytics_opt_out: false });
    expect(toggle).toHaveAttribute("aria-checked", "false");
    await act(async () => patch.resolve());
    await waitFor(() => expect(toggle).toHaveAttribute("aria-checked", "true"));
  });

  it("rapid toggles never overlap: disabled while a save is in flight", async () => {
    const toggle = await openDataTab();
    await waitFor(() => expect(toggle).toBeEnabled());
    const patch = deferredPatch();
    vi.mocked(updateSettings).mockReturnValueOnce(patch.promise);
    fireEvent.click(toggle);
    expect(toggle).toBeDisabled();
    fireEvent.click(toggle);
    fireEvent.click(toggle);
    expect(updateSettings).toHaveBeenCalledTimes(1);
    await act(async () => patch.resolve());
    await waitFor(() => expect(toggle).toBeEnabled());
    expect(toggle).toHaveAttribute("aria-checked", "false");
  });

  it("a failed opt-OUT save: off in this browser for this visit only, never 'saved', with a retry that saves it", async () => {
    vi.mocked(updateSettings).mockRejectedValueOnce(new Error("500"));
    const toggle = await openDataTab();
    await waitFor(() => expect(toggle).toBeEnabled());
    fireEvent.click(toggle);
    await waitFor(() =>
      expect(toast.error).toHaveBeenCalledWith(expect.stringMatching(/off in this browser for this visit only/)),
    );
    expect(toggle).toHaveAttribute("aria-checked", "false");
    expect(note()).toHaveTextContent(/Off in this browser for this visit only/);
    expect(note()).toHaveTextContent(/our servers may still share usage data/);
    expect(note()).not.toHaveTextContent(/saved to your account,/);
    fireEvent.click(screen.getByTestId("settings-analytics-retry"));
    await waitFor(() => expect(note()).toHaveTextContent(/Off — saved to your account/));
    expect(updateSettings).toHaveBeenLastCalledWith("u1", { analytics_opt_out: true });
    expect(screen.queryByTestId("settings-analytics-retry")).toBeNull();
  });

  it("says so when page views could not start in this browser", async () => {
    vi.spyOn(console, "warn").mockImplementation(() => {});
    window.history.replaceState({}, "", "/settings");
    analyticsBuild({
      load: async () => {
        throw new Error("chunk blocked");
      },
    });
    const toggle = await openDataTab();
    await waitFor(() => expect(note()).toHaveTextContent(/Page views couldn't start in this browser/));
    expect(toggle).toHaveAttribute("aria-checked", "true");
    expect(toggle).toBeEnabled();
  });

  it("a failed opt-IN save changes nothing and says it failed", async () => {
    vi.mocked(updateSettings).mockRejectedValue(new Error("500"));
    accountSays(true);
    const toggle = await openDataTab();
    await waitFor(() => expect(toggle).toBeEnabled());
    fireEvent.click(toggle);
    await waitFor(() =>
      expect(toast.error).toHaveBeenCalledWith(expect.stringMatching(/Couldn't turn product analytics back on/)),
    );
    expect(toggle).toHaveAttribute("aria-checked", "false");
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

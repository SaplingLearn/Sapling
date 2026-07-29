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
import { render, screen, cleanup } from "@testing-library/react";
import type { UserProfile, UserSettings } from "@/lib/types";

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

vi.mock("../ToastProvider", () => ({
  useToast: () => ({
    error: vi.fn(), success: vi.fn(), info: vi.fn(), warn: vi.fn(), show: vi.fn(), dismiss: vi.fn(),
  }),
}));

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
import { fetchSettings, fetchPublicProfile } from "@/lib/api";

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

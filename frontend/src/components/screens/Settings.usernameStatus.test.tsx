// @vitest-environment jsdom
/**
 * Characterization of the Settings → Profile username field's status display:
 * the input's border colour and the message line (text + colour) for each
 * verdict the availability check can return.
 */

import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, cleanup, fireEvent, waitFor } from "@testing-library/react";
import type { UserProfile, UserSettings } from "@/lib/types";
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
import { fetchSettings, fetchPublicProfile, checkUsername } from "@/lib/api";

function settings(overrides: Partial<UserSettings> = {}): UserSettings {
  return {
    display_name: null,
    username: "orig",
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

function profile(): UserProfile {
  return {
    id: "u1", name: "Rich Active", username: "orig", bio: null, location: null, website: null,
    avatar_url: null, created_at: null, year: null, majors: [], minors: [], school: null, roles: [],
    featured_achievements: [], equipped_cosmetics: {}, stats: {} as UserProfile["stats"],
  };
}

beforeEach(() => {
  window.localStorage.clear();
  __resetAccountSettingsForTests();
  vi.mocked(fetchSettings).mockResolvedValue(settings());
  vi.mocked(fetchPublicProfile).mockResolvedValue(profile());
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

async function typeUsername(value: string) {
  render(<Settings />);
  const input = await screen.findByPlaceholderText("your-handle");
  await waitFor(() => expect(input).toHaveValue("orig"));
  fireEvent.change(input, { target: { value } });
  return input;
}

const style = (el: Element) => el.getAttribute("style") ?? "";

describe("Settings username status display (characterization)", () => {
  it("idle: neutral border and no message", async () => {
    const input = await typeUsername("orig");
    expect(style(input)).toContain("border: 1px solid var(--border)");
    expect(screen.queryByText("Available")).toBeNull();
    expect(checkUsername).not.toHaveBeenCalled();
  });

  it("checking: neutral border, no message line yet", async () => {
    vi.mocked(checkUsername).mockReturnValue(new Promise(() => {}));
    const input = await typeUsername("alice");
    expect(style(input)).toContain("border: 1px solid var(--border)");
    expect(screen.queryByText("Checking…")).toBeNull();
    expect(input.parentElement!.nextElementSibling).toBeNull();
  });

  it("available: neutral border, accent 'Available' message", async () => {
    vi.mocked(checkUsername).mockResolvedValue({ available: true });
    const input = await typeUsername("alice");
    const msg = await screen.findByText("Available");
    expect(style(input)).toContain("border: 1px solid var(--border)");
    expect(style(msg)).toContain("color: var(--accent)");
    expect(checkUsername).toHaveBeenCalledWith("alice", "u1");
  });

  it("taken: error border and error 'Already taken' message", async () => {
    vi.mocked(checkUsername).mockResolvedValue({ available: false, reason: "taken" });
    const input = await typeUsername("bob");
    const msg = await screen.findByText("Already taken");
    expect(style(input)).toContain("border: 1px solid var(--err)");
    expect(style(msg)).toContain("color: var(--err)");
  });

  it("invalid: error border and error rules message", async () => {
    vi.mocked(checkUsername).mockResolvedValue({ available: false, reason: "invalid" });
    const input = await typeUsername("X!");
    const msg = await screen.findByText("3–24 chars, lowercase letters, digits, or _");
    expect(style(input)).toContain("border: 1px solid var(--err)");
    expect(style(msg)).toContain("color: var(--err)");
    expect(checkUsername).toHaveBeenCalledWith("x!", "u1");
  });

  it("a failed check falls back to idle: neutral border, no message", async () => {
    vi.mocked(checkUsername).mockRejectedValue(new Error("500"));
    const input = await typeUsername("carol");
    await waitFor(() => expect(checkUsername).toHaveBeenCalled());
    await waitFor(() => expect(style(input)).toContain("border: 1px solid var(--border)"));
    expect(input.parentElement!.nextElementSibling).toBeNull();
  });
});

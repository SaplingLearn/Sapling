// @vitest-environment jsdom
/**
 * #767: the showcase save on the Achievements screen.
 *
 * What these pin:
 *   - the save request fires once per edit, even under StrictMode (it used to
 *     fire from inside a setState updater, which React may run twice);
 *   - a failed save rolls the showcase back to the last server-confirmed list
 *     and toasts once;
 *   - the window-focus reload does not overwrite an edit still being saved.
 */

import React from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";

vi.mock("@/context/UserContext", () => ({
  useUser: () => ({ userId: "u1", userReady: true }),
}));

const toastSpies = vi.hoisted(() => ({
  success: vi.fn(),
  error: vi.fn(),
  warn: vi.fn(),
  info: vi.fn(),
}));
vi.mock("../ToastProvider", () => ({
  useToast: () => toastSpies,
}));

vi.mock("../Icon", () => ({
  Icon: ({ name }: { name: string }) => <span data-testid={`icon-${name}`} />,
}));
// The grid, hero card and tabs are not under test here.
vi.mock("./achievements/BadgeGrid", () => ({
  BadgeGrid: () => null,
  CAT_META: {},
  CAT_ORDER: [],
}));
vi.mock("./achievements/HeroCard", () => ({ HeroCard: () => null }));

vi.mock("@/lib/api", () => ({
  fetchAchievements: vi.fn(),
  fetchGamificationMe: vi.fn(),
  setFeaturedAchievements: vi.fn(),
}));

import { Achievements } from "./Achievements";
import { fetchAchievements, fetchGamificationMe, setFeaturedAchievements } from "@/lib/api";
import type { Achievement, UserAchievement } from "@/lib/types";

const mockedFetch = vi.mocked(fetchAchievements);
const mockedMe = vi.mocked(fetchGamificationMe);
const mockedSave = vi.mocked(setFeaturedAchievements);

function ach(id: string): Achievement {
  return {
    id, name: id.toUpperCase(), slug: id, description: null, icon: null,
    category: "milestone", rarity: "common", is_secret: false, xp_reward: 0,
    icon_url: null, sort_order: 0, status: "live",
  };
}

function earned(featured: string[]): UserAchievement[] {
  return ["a1", "a2"].map((id) => ({
    achievement: ach(id), earned_at: "2026-01-01T00:00:00Z", is_featured: featured.includes(id),
  }));
}

function showcase(): string[] {
  return screen
    .queryAllByTestId(/^achievements-showcase-remove-/)
    .map((el) => el.getAttribute("data-testid")!.replace("achievements-showcase-remove-", ""));
}

async function renderScreen(strict = false) {
  mockedFetch.mockResolvedValue({ earned: earned(["a1", "a2"]), available: [] });
  mockedMe.mockRejectedValue(new Error("not under test"));
  vi.spyOn(console, "error").mockImplementation(() => {});
  render(strict ? <React.StrictMode><Achievements /></React.StrictMode> : <Achievements />);
  await waitFor(() => expect(showcase()).toEqual(["a1", "a2"]));
}

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
  vi.restoreAllMocks();
  window.localStorage.clear();
});

describe("Achievements showcase save", () => {
  it("sends one save per edit under StrictMode", async () => {
    mockedSave.mockResolvedValue({ updated: true });
    await renderScreen(true);

    fireEvent.click(screen.getByTestId("achievements-showcase-remove-a1"));

    await waitFor(() => expect(showcase()).toEqual(["a2"]));
    expect(mockedSave).toHaveBeenCalledTimes(1);
    expect(mockedSave).toHaveBeenCalledWith("u1", ["a2"]);
  });

  it("sends one save per reorder under StrictMode", async () => {
    mockedSave.mockResolvedValue({ updated: true });
    await renderScreen(true);

    fireEvent.click(screen.getByTestId("achievements-showcase-right-a1"));

    await waitFor(() => expect(showcase()).toEqual(["a2", "a1"]));
    expect(mockedSave).toHaveBeenCalledTimes(1);
    expect(mockedSave).toHaveBeenCalledWith("u1", ["a2", "a1"]);
  });

  it("rolls back a failed save and toasts once", async () => {
    mockedSave.mockRejectedValue(new Error("500"));
    await renderScreen(true);

    fireEvent.click(screen.getByTestId("achievements-showcase-remove-a1"));

    await waitFor(() => expect(toastSpies.error).toHaveBeenCalledTimes(1));
    expect(showcase()).toEqual(["a1", "a2"]);
  });

  it("does not let the focus reload overwrite an edit still saving", async () => {
    let finishSave: (v: { updated: boolean }) => void = () => {};
    mockedSave.mockImplementation(
      () => new Promise((resolve) => { finishSave = resolve; }),
    );
    await renderScreen();

    fireEvent.click(screen.getByTestId("achievements-showcase-remove-a1"));
    expect(showcase()).toEqual(["a2"]);

    // The server still reports the pre-edit showcase while the save is pending.
    await act(async () => {
      window.dispatchEvent(new Event("focus"));
    });
    await waitFor(() => expect(mockedFetch).toHaveBeenCalledTimes(2));
    expect(showcase()).toEqual(["a2"]);

    await act(async () => finishSave({ updated: true }));
    expect(showcase()).toEqual(["a2"]);
  });

  it("still adopts the server showcase on a focus reload with no edit pending", async () => {
    await renderScreen();
    mockedFetch.mockResolvedValue({ earned: earned(["a2"]), available: [] });

    await act(async () => {
      window.dispatchEvent(new Event("focus"));
    });

    await waitFor(() => expect(showcase()).toEqual(["a2"]));
  });
});

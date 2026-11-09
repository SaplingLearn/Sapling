// @vitest-environment jsdom
/**
 * Component + unit tests for the admin achievement wiki (Task 15 review fixes).
 *
 * What these pin:
 *   - Finding 1 (CRITICAL): re-expanding a card after a successful save shows
 *     the freshly-saved values, not the values from the card's first render —
 *     and a subsequent save of a different field never reverts the earlier
 *     save (the stale-closure silent-data-loss bug).
 *   - Finding 2: the achievement<->cosmetic linker (list/link/unlink) is back
 *     on the expanded card.
 *   - Finding 3: the icon drop zone can't be double-fired while an upload is
 *     in flight, and a failed/rejected upload leaves the picker usable again.
 *   - Finding 4: `readIcon`'s validation branches (dimensions, size, content
 *     type, SVG bypass) are unit-tested directly, with `createImageBitmap`
 *     stubbed since jsdom doesn't implement it.
 */

import React from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

const toastSpies = vi.hoisted(() => ({
  success: vi.fn(),
  error: vi.fn(),
  warn: vi.fn(),
}));
vi.mock("@/components/ToastProvider", () => ({
  useToast: () => toastSpies,
}));

const api = vi.hoisted(() => ({
  adminListAchievements: vi.fn(),
  adminUpdateAchievement: vi.fn(),
  adminUploadAchievementIcon: vi.fn(),
  adminListXpRules: vi.fn(),
  adminUpdateXpRule: vi.fn(),
  adminGrantAchievement: vi.fn(),
  adminListTriggers: vi.fn(),
  adminCreateTrigger: vi.fn(),
  adminUpdateTrigger: vi.fn(),
  adminDeleteTrigger: vi.fn(),
  adminListAchievementCosmetics: vi.fn(),
  adminLinkAchievementCosmetic: vi.fn(),
  adminUnlinkAchievementCosmetic: vi.fn(),
  adminListCosmetics: vi.fn(),
  adminFetchUsers: vi.fn(),
}));
vi.mock("@/lib/api", () => api);

import { AchievementWiki, readIcon } from "./AchievementWiki";
import type { Achievement, Cosmetic } from "@/lib/types";

const ACHIEVEMENT: Achievement = {
  id: "a1",
  name: "First Steps",
  slug: "first-steps",
  description: "Take your first step",
  icon: null,
  category: "activity",
  rarity: "common",
  is_secret: false,
  xp_reward: 10,
  icon_url: null,
  sort_order: 1,
  status: "live",
};

const COSMETIC_A: Cosmetic = { id: "cos-1", type: "avatar_frame", name: "Golden Frame", slug: "golden-frame", rarity: "rare" };
const COSMETIC_B: Cosmetic = { id: "cos-2", type: "title", name: "Trailblazer", slug: "trailblazer", rarity: "epic" };

function primeHappyPath(achievements: Achievement[] = [ACHIEVEMENT]) {
  api.adminListAchievements.mockResolvedValue({ achievements });
  api.adminFetchUsers.mockResolvedValue({ users: [] });
  api.adminListXpRules.mockResolvedValue({ rules: [] });
  api.adminListTriggers.mockResolvedValue({ triggers: [] });
  api.adminListAchievementCosmetics.mockResolvedValue({ links: [] });
  api.adminListCosmetics.mockResolvedValue({ cosmetics: [] });
}

async function expandCard(name = "First Steps") {
  const heading = await screen.findByText(name);
  const card = heading.closest(".card") as HTMLElement;
  fireEvent.click(within(card).getByRole("button", { name: "Edit" }));
  return card;
}

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("AchievementWiki — stale closure on re-expand (Finding 1)", () => {
  it("shows freshly-saved values on re-expand, and a later save never reverts the earlier one", async () => {
    primeHappyPath();
    api.adminUpdateAchievement.mockResolvedValue({});
    render(<AchievementWiki />);

    let card = await expandCard();
    const nameInput = () => within(card).getByDisplayValue("First Steps") as HTMLInputElement;
    expect(nameInput()).toBeTruthy();

    // Edit + save the name field.
    fireEvent.change(nameInput(), { target: { value: "Renamed Steps" } });
    fireEvent.click(within(card).getByRole("button", { name: "Save" }));
    await waitFor(() => expect(api.adminUpdateAchievement).toHaveBeenCalledTimes(1));
    expect(api.adminUpdateAchievement).toHaveBeenLastCalledWith("a1", { name: "Renamed Steps" });
    await waitFor(() => expect(toastSpies.success).toHaveBeenCalledWith("Saved"));

    // The card stays expanded after a successful save (per save()'s own
    // logic); close it, then re-expand — this is the exact toggle sequence
    // that hit the stale closure in production.
    card = screen.getByText("Renamed Steps").closest(".card") as HTMLElement;
    fireEvent.click(within(card).getByRole("button", { name: "Close" }));
    fireEvent.click(within(card).getByRole("button", { name: "Edit" }));

    // RED (pre-fix): this would show "First Steps" — the value frozen at
    // the card's first render — instead of the value that was just saved.
    await waitFor(() => expect(within(card).getByDisplayValue("Renamed Steps")).toBeTruthy());

    // Edit a *different* field and save again. A stale closure would diff
    // its frozen "First Steps" against the fresh "Renamed Steps" prop, see
    // a spurious change, and silently PATCH the name back.
    const sortInput = within(card).getAllByRole("spinbutton")[1]; // XP reward, then Sort order
    fireEvent.change(sortInput, { target: { value: "9" } });
    fireEvent.click(within(card).getByRole("button", { name: "Save" }));
    await waitFor(() => expect(api.adminUpdateAchievement).toHaveBeenCalledTimes(2));
    const secondPatch = api.adminUpdateAchievement.mock.calls[1][1];
    expect(secondPatch).toEqual({ sort_order: 9 });
    expect(secondPatch).not.toHaveProperty("name");
  });
});

describe("AchievementWiki — cosmetics linking (Finding 2)", () => {
  it("lists linked cosmetics, unlinks one, and links an available one", async () => {
    primeHappyPath();
    api.adminListAchievementCosmetics.mockResolvedValue({
      links: [{ achievement_id: "a1", cosmetic_id: "cos-1" }],
    });
    api.adminListCosmetics.mockResolvedValue({ cosmetics: [COSMETIC_A, COSMETIC_B] });
    api.adminUnlinkAchievementCosmetic.mockResolvedValue({ unlinked: true });
    api.adminLinkAchievementCosmetic.mockResolvedValue({ linked: true });

    render(<AchievementWiki />);
    const card = await expandCard();

    await waitFor(() => expect(within(card).getByText("Golden Frame")).toBeTruthy());
    expect(within(card).queryByText("Trailblazer")).toBeNull(); // linked-only list; not in the "add" dropdown text yet

    // Unlink the existing cosmetic.
    api.adminListAchievementCosmetics.mockResolvedValueOnce({ links: [] });
    const linkedRow = within(card).getByText("Golden Frame").closest("div") as HTMLElement;
    fireEvent.click(within(linkedRow).getByRole("button", { name: "×" }));
    await waitFor(() => expect(api.adminUnlinkAchievementCosmetic).toHaveBeenCalledWith("a1", "cos-1"));
    await waitFor(() => expect(within(card).queryByText("Golden Frame")).toBeNull());

    // Link a new one via the picker.
    api.adminListAchievementCosmetics.mockResolvedValueOnce({
      links: [{ achievement_id: "a1", cosmetic_id: "cos-2" }],
    });
    const user = userEvent.setup();
    await user.click(within(card).getByRole("button", { name: "Pick a cosmetic to link…" }));
    await user.click(await within(card).findByRole("option", { name: /Trailblazer/ }));
    fireEvent.click(within(card).getByRole("button", { name: "Link" }));
    await waitFor(() => expect(api.adminLinkAchievementCosmetic).toHaveBeenCalledWith("a1", "cos-2"));
    await waitFor(() => expect(within(card).getByText("Trailblazer")).toBeTruthy());
  });
});

describe("AchievementWiki — icon upload gating (Finding 3)", () => {
  function makeFile(name = "icon.png", type = "image/png", bytes = 10) {
    return new File([new Uint8Array(bytes)], name, { type });
  }

  it("does not start a second upload while one is in flight", async () => {
    primeHappyPath();
    let resolveUpload!: (v: { icon_url: string }) => void;
    api.adminUploadAchievementIcon.mockReturnValue(
      new Promise(res => { resolveUpload = res; }),
    );
    vi.stubGlobal("createImageBitmap", vi.fn(async () => ({ width: 512, height: 512, close: () => {} })));

    render(<AchievementWiki />);
    const card = await expandCard();
    const input = card.querySelector('input[type="file"]') as HTMLInputElement;

    fireEvent.change(input, { target: { files: [makeFile()] } });
    await waitFor(() => expect(within(card).getByText("Uploading…")).toBeTruthy());

    // Fire the same change event again while the first upload is still
    // pending — the pre-fix drop zone would let this through.
    fireEvent.change(input, { target: { files: [makeFile()] } });
    await Promise.resolve();

    expect(api.adminUploadAchievementIcon).toHaveBeenCalledTimes(1);

    resolveUpload({ icon_url: "https://example.com/icon.png" });
    await waitFor(() => expect(toastSpies.success).toHaveBeenCalledWith("Icon uploaded"));
    vi.unstubAllGlobals();
  });

  it("gates the drop-zone click while an upload is in flight", async () => {
    primeHappyPath();
    let resolveUpload!: (v: { icon_url: string }) => void;
    api.adminUploadAchievementIcon.mockReturnValue(
      new Promise(res => { resolveUpload = res; }),
    );
    vi.stubGlobal("createImageBitmap", vi.fn(async () => ({ width: 512, height: 512, close: () => {} })));
    const clickSpy = vi.spyOn(HTMLInputElement.prototype, "click").mockImplementation(() => {});

    render(<AchievementWiki />);
    const card = await expandCard();
    const dropZone = screen.getByText(/Drop a 512×512/).closest("div") as HTMLElement;

    fireEvent.click(dropZone);
    expect(clickSpy).toHaveBeenCalledTimes(1);

    const input = card.querySelector('input[type="file"]') as HTMLInputElement;
    fireEvent.change(input, { target: { files: [makeFile()] } });
    await waitFor(() => expect(within(card).getByText("Uploading…")).toBeTruthy());

    fireEvent.click(screen.getByText("Uploading…"));
    expect(clickSpy).toHaveBeenCalledTimes(1); // unchanged — gated while uploading

    resolveUpload({ icon_url: "https://example.com/icon.png" });
    await waitFor(() => expect(toastSpies.success).toHaveBeenCalledWith("Icon uploaded"));
    clickSpy.mockRestore();
    vi.unstubAllGlobals();
  });

  it("resets the file input after a failed upload so a retry still fires", async () => {
    primeHappyPath();
    vi.stubGlobal("createImageBitmap", vi.fn(async () => ({ width: 512, height: 512, close: () => {} })));
    render(<AchievementWiki />);
    const card = await expandCard();
    const input = card.querySelector('input[type="file"]') as HTMLInputElement;

    // Wrong content type — readIcon rejects synchronously inside handleFile.
    fireEvent.change(input, { target: { files: [makeFile("icon.gif", "image/gif")] } });
    await waitFor(() => expect(toastSpies.error).toHaveBeenCalledWith("Icon must be a PNG, WebP or SVG"));
    expect(input.value).toBe("");
    expect(within(card).queryByText("Uploading…")).toBeNull();

    // A subsequent, valid attempt must still go through.
    api.adminUploadAchievementIcon.mockResolvedValue({ icon_url: "https://example.com/icon.png" });
    fireEvent.change(input, { target: { files: [makeFile()] } });
    await waitFor(() => expect(api.adminUploadAchievementIcon).toHaveBeenCalledTimes(1));
    vi.unstubAllGlobals();
  });
});

describe("readIcon (Finding 4)", () => {
  beforeEach(() => {
    vi.stubGlobal("createImageBitmap", vi.fn(async () => ({ width: 512, height: 512, close: () => {} })));
  });
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  function file(bytes: number, type: string, name = "icon.png") {
    return new File([new Uint8Array(bytes)], name, { type });
  }

  it("accepts a well-formed 512×512 PNG", async () => {
    const result = await readIcon(file(1024, "image/png"));
    expect(result.contentType).toBe("image/png");
    expect(result.base64.length).toBeGreaterThan(0);
  });

  it("rejects the wrong dimensions and names the actual size", async () => {
    vi.stubGlobal("createImageBitmap", vi.fn(async () => ({ width: 400, height: 300, close: () => {} })));
    await expect(readIcon(file(1024, "image/png"))).rejects.toThrow(
      "Icon must be exactly 512×512 (this one is 400×300)",
    );
  });

  it("rejects an oversized file and names the actual size in KB", async () => {
    const oversized = file(600 * 1024, "image/png");
    await expect(readIcon(oversized)).rejects.toThrow(
      "Icon must be 512 KB or smaller (this one is 600 KB)",
    );
  });

  it("rejects the wrong content type", async () => {
    await expect(readIcon(file(1024, "image/jpeg"))).rejects.toThrow(
      "Icon must be a PNG, WebP or SVG",
    );
  });

  it("bypasses the dimension check for SVG", async () => {
    const bitmapSpy = vi.fn(async () => ({ width: 1, height: 1, close: () => {} }));
    vi.stubGlobal("createImageBitmap", bitmapSpy);
    const result = await readIcon(file(512, "image/svg+xml", "icon.svg"));
    expect(result.contentType).toBe("image/svg+xml");
    expect(bitmapSpy).not.toHaveBeenCalled();
  });
});

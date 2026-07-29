// @vitest-environment jsdom
/**
 * Tests for SharedContextToggle / useSharedContext (#72).
 *
 * The toggle keeps its localStorage read-path behavior, and additionally
 * write-through persists `share_class_context` to user_settings so the
 * backend can honor the opt-out on the WRITE path. Covered here:
 *   1. Renders as a switch, defaulting to enabled
 *   2. Toggling PATCHes { share_class_context } via updateSettings
 *   3. A failed PATCH is swallowed (console.warn) — the toggle still flips
 *   4. Mount hydrates from the server value when one is present
 *
 * Module mocks: @/lib/api (fetchSettings/updateSettings) and useUser.
 */

import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, cleanup, fireEvent, waitFor } from "@testing-library/react";

const { mockFetchSettings, mockUpdateSettings } = vi.hoisted(() => ({
  mockFetchSettings: vi.fn(),
  mockUpdateSettings: vi.fn(),
}));

vi.mock("@/lib/api", () => ({
  fetchSettings: mockFetchSettings,
  updateSettings: mockUpdateSettings,
}));

vi.mock("@/context/UserContext", () => ({
  useUser: () => ({ userId: "u1", userReady: true }),
}));

import { SharedContextToggle, useSharedContext } from "./SharedContextToggle";

// Drives the hook the same way Learn.tsx does.
function Harness() {
  const [enabled, setEnabled] = useSharedContext();
  return <SharedContextToggle enabled={enabled} onChange={setEnabled} />;
}

beforeEach(() => {
  localStorage.clear();
  mockFetchSettings.mockResolvedValue({});
  mockUpdateSettings.mockResolvedValue({});
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("SharedContextToggle", () => {
  it("renders an enabled switch by default", async () => {
    render(<Harness />);
    const toggle = screen.getByRole("switch");
    expect(toggle).toHaveAttribute("aria-checked", "true");
    expect(toggle).toHaveTextContent("Class intel");
    await waitFor(() => expect(mockFetchSettings).toHaveBeenCalledWith("u1"));
  });

  it("toggling PATCHes share_class_context and updates localStorage", async () => {
    render(<Harness />);
    fireEvent.click(screen.getByRole("switch"));
    expect(screen.getByRole("switch")).toHaveAttribute("aria-checked", "false");
    expect(localStorage.getItem("sapling_shared_ctx")).toBe("false");
    await waitFor(() =>
      expect(mockUpdateSettings).toHaveBeenCalledWith("u1", {
        share_class_context: false,
      }),
    );
  });

  it("swallows a failed PATCH — the toggle still flips", async () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    mockUpdateSettings.mockRejectedValue(new Error("400 not whitelisted"));
    render(<Harness />);
    fireEvent.click(screen.getByRole("switch"));
    // The local flip is immediate even though the PATCH fails…
    expect(screen.getByRole("switch")).toHaveAttribute("aria-checked", "false");
    expect(localStorage.getItem("sapling_shared_ctx")).toBe("false");
    // …and the rejection is caught and warned, never thrown.
    await waitFor(() => expect(warn).toHaveBeenCalled());
    warn.mockRestore();
  });

  it("hydrates from a persisted server opt-out on mount", async () => {
    mockFetchSettings.mockResolvedValue({ share_class_context: false });
    render(<Harness />);
    await waitFor(() =>
      expect(screen.getByRole("switch")).toHaveAttribute("aria-checked", "false"),
    );
    expect(localStorage.getItem("sapling_shared_ctx")).toBe("false");
  });
});

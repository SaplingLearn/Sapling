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
 * Plus tooltip placement (#581): the panel is 240px wide against a ~130px
 * button, so whichever edge it is NOT anchored to overhangs. The anchor has
 * to follow the toggle's position in its container, on both open paths
 * (hover and keyboard focus):
 *   5. Default/`align="right"` anchors right — the active-session TopBar
 *   6. `align="left"` anchors left — the start-session card's left-flush row
 *   7. Focus opens the tooltip with the same anchoring as hover
 *
 * Module mocks: @/lib/api (fetchSettings/updateSettings) and useUser.
 */

import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, cleanup, fireEvent, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

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

describe("SharedContextToggle tooltip placement (#581)", () => {
  // The tooltip is `position: absolute` inside an `inline-block` wrapper, so
  // only one horizontal offset may be set — setting both would stretch the
  // panel across the wrapper instead of anchoring it to one edge.
  function anchorOf(tip: HTMLElement) {
    return { left: tip.style.left, right: tip.style.right };
  }

  it("anchors to the right edge by default — the TopBar mount must not regress", () => {
    render(<SharedContextToggle enabled onChange={() => {}} />);
    fireEvent.mouseOver(screen.getByRole("switch"));
    expect(anchorOf(screen.getByRole("tooltip"))).toEqual({ left: "", right: "0px" });
  });

  it('anchors to the left edge with align="left" — the start-session card mount', () => {
    render(<SharedContextToggle enabled onChange={() => {}} align="left" />);
    fireEvent.mouseOver(screen.getByRole("switch"));
    // Anchored left, the 240px panel opens INTO the card rather than
    // overhanging its left edge under the opaque sidebar.
    expect(anchorOf(screen.getByRole("tooltip"))).toEqual({ left: "0px", right: "" });
  });

  it('is explicit that align="right" and the default are the same placement', () => {
    render(<SharedContextToggle enabled onChange={() => {}} align="right" />);
    fireEvent.mouseOver(screen.getByRole("switch"));
    expect(anchorOf(screen.getByRole("tooltip"))).toEqual({ left: "", right: "0px" });
  });

  it("opens on keyboard focus with the same anchoring as hover", async () => {
    // Keyboard users reach the tooltip through onFocus, never onMouseEnter —
    // the clipped-text bug hit that path identically. Tab to the switch the
    // way a keyboard user does rather than firing a synthetic hover.
    render(<SharedContextToggle enabled onChange={() => {}} align="left" />);
    expect(screen.queryByRole("tooltip")).toBeNull();

    await userEvent.tab();
    expect(screen.getByRole("switch")).toHaveFocus();
    expect(anchorOf(screen.getByRole("tooltip"))).toEqual({ left: "0px", right: "" });

    await userEvent.tab();
    expect(screen.queryByRole("tooltip")).toBeNull();
  });

  it("hides the tooltip again on mouse-out", () => {
    render(<SharedContextToggle enabled onChange={() => {}} />);
    const toggle = screen.getByRole("switch");
    fireEvent.mouseOver(toggle);
    expect(screen.getByRole("tooltip")).toHaveTextContent("Shared course context");
    fireEvent.mouseOut(toggle);
    expect(screen.queryByRole("tooltip")).toBeNull();
  });
});

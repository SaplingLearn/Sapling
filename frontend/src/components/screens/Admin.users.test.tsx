// @vitest-environment jsdom
/**
 * Admin → Users lists the people who have access, and nothing else: unapproved
 * sign-ins no longer create accounts, so there is no "pending" user to show or
 * approve here (that queue is Admin → Allowlist).
 *
 * What these pin:
 *   - no Approve button and no Status column; the summary is a plain count;
 *   - "Remove access" confirms in-page first: Cancel calls nothing, confirm
 *     calls `adminRemoveUserAccess`, toasts, and reloads the list;
 *   - the backend's 409 on your own account surfaces its own sentence;
 *   - Analytics labels `totals.pending` as "Awaiting approval" (waitlist
 *     signups not yet approved).
 */

import React from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";

const userState = vi.hoisted(() => ({ isAdmin: true, userReady: true, userId: "admin-1" }));
vi.mock("@/context/UserContext", () => ({
  useUser: () => userState,
}));

vi.mock("../TopBar", () => ({
  TopBar: ({ title }: { title: string }) => <div>{title}</div>,
}));

const toastSpies = vi.hoisted(() => ({
  success: vi.fn(),
  error: vi.fn(),
  warn: vi.fn(),
}));
vi.mock("../ToastProvider", () => ({
  useToast: () => toastSpies,
}));

vi.mock("@/lib/supabase", () => ({ supabase: {} }));
vi.mock("./admin/AchievementWiki", () => ({ AchievementWiki: () => null }));
vi.mock("./admin/FeatureFlags", () => ({ FeatureFlagsTab: () => null }));

const api = vi.hoisted(() => ({
  adminFetchUsers: vi.fn(),
  adminRemoveUserAccess: vi.fn(),
  adminListRoles: vi.fn(),
  adminAnalyticsOverview: vi.fn(),
}));
vi.mock("@/lib/api", () => api);

import { Admin } from "./Admin";

const ADA = {
  id: "u-ada", name: "Ada Lovelace", email: "ada@bu.edu", is_approved: true,
  last_sign_in_at: null, created_at: "2026-10-01T00:00:00Z", roles: [],
};
const GRACE = {
  id: "u-grace", name: "Grace Hopper", email: "grace@bu.edu", is_approved: true,
  last_sign_in_at: null, created_at: "2026-10-02T00:00:00Z", roles: [],
};

beforeEach(() => {
  api.adminFetchUsers.mockResolvedValue({ users: [ADA, GRACE], total: 2, page: 1, page_size: 50 });
  api.adminListRoles.mockResolvedValue({ roles: [] });
  api.adminRemoveUserAccess.mockResolvedValue({ unapproved: true });
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
  userState.isAdmin = true;
});

const openRemove = async (id: string) => {
  fireEvent.click(await screen.findByTestId(`admin-user-remove-access-${id}`));
  return screen.findByTestId("admin-user-remove-confirm");
};

describe("Admin → Users", () => {
  it("lists users with access: no Approve button, no Status column, a plain count", async () => {
    render(<Admin />);
    expect(await screen.findByText("Ada Lovelace")).toBeTruthy();
    expect(screen.getByText("Grace Hopper")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Approve" })).toBeNull();
    expect(screen.queryByText("Status")).toBeNull();
    expect(screen.queryByText(/approved on this page/)).toBeNull();
    expect(screen.getByTestId("admin-users-summary").textContent).toBe("2 users");
    expect(screen.getAllByRole("button", { name: "Remove access" })).toHaveLength(2);
  });

  it("asks before removing access, and Cancel does nothing", async () => {
    render(<Admin />);
    await openRemove("u-ada");
    expect(screen.getByText("Remove Ada Lovelace's access?")).toBeTruthy();
    expect(screen.getByTestId("admin-user-remove-body").textContent).toMatch(/move to the Allowlist as a\s+signup/);

    fireEvent.click(screen.getByTestId("admin-user-remove-cancel"));
    await waitFor(() => expect(screen.queryByTestId("admin-user-remove-confirm")).toBeNull());
    expect(api.adminRemoveUserAccess).not.toHaveBeenCalled();
    expect(api.adminFetchUsers).toHaveBeenCalledTimes(1);
  });

  it("confirming removes access, toasts, and reloads the list", async () => {
    render(<Admin />);
    fireEvent.click(await openRemove("u-grace"));

    await waitFor(() => expect(api.adminRemoveUserAccess).toHaveBeenCalledWith("u-grace"));
    await waitFor(() => expect(api.adminFetchUsers).toHaveBeenCalledTimes(2));
    expect(toastSpies.success).toHaveBeenCalledWith("Access removed. grace@bu.edu is back on the Allowlist.");
    expect(screen.queryByTestId("admin-user-remove-confirm")).toBeNull();
  });

  it("surfaces the backend's own sentence when you try to remove yourself", async () => {
    api.adminRemoveUserAccess.mockRejectedValue(
      Object.assign(new Error('{"detail":"You cannot remove your own access."}'), {
        status: 409,
        body: { detail: "You cannot remove your own access." },
      }),
    );
    render(<Admin />);
    fireEvent.click(await openRemove("u-ada"));

    await waitFor(() => expect(toastSpies.error).toHaveBeenCalledWith("You cannot remove your own access."));
    expect(toastSpies.success).not.toHaveBeenCalled();
    expect(api.adminFetchUsers).toHaveBeenCalledTimes(1);
  });
});

describe("Admin → Analytics", () => {
  it("labels waitlist signups as Awaiting approval", async () => {
    api.adminAnalyticsOverview.mockResolvedValue({
      totals: { users: 5, approved: 5, pending: 3, admins: 1 },
      signups_by_day: [], approvals_by_day: [], role_counts: [],
    });
    render(<Admin />);
    fireEvent.click(screen.getByTestId("admin-tab-analytics"));
    expect(await screen.findByText("Awaiting approval")).toBeTruthy();
    expect(screen.queryByText("Pending")).toBeNull();
  });
});

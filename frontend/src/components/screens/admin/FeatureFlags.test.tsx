// @vitest-environment jsdom
/**
 * Task 7: the admin "Feature flags" tab (`FeatureFlagsTab` in ./FeatureFlags).
 *
 * What's pinned here:
 *   - the flag list renders a row per flag (`flag-row-{key}`), expanding to
 *     an editor on click;
 *   - a default/rollout change is gated behind the two-click `useConfirm`
 *     pattern used elsewhere in this codebase (real hook, not mocked, so
 *     the confirm mechanics themselves are exercised, per the Social
 *     friends-panel precedent) — the first click arms the Save button, and
 *     only the second click calls `adminUpdateFlag`;
 *   - the per-student "explain" lookup calls `adminExplainFlag` and renders
 *     `"<variant> (<step>: <detail>)"`.
 *
 * Note: the task brief drafted a promise-based `useConfirm(): (opts) =>
 * Promise<boolean>` mock, but the real `frontend/src/lib/useConfirm.ts` is a
 * synchronous arm/trigger hook (see every other `useConfirm` call site in
 * this repo). This file exercises the real hook instead of inventing a
 * second confirm mechanism.
 */
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({
  adminListFlags: vi.fn(),
  adminUpdateFlag: vi.fn(),
  adminUpsertFlagTarget: vi.fn(),
  adminDeleteFlagTarget: vi.fn(),
  adminExplainFlag: vi.fn(),
  adminListRoles: vi.fn(),
  adminFetchUsers: vi.fn(),
}));
vi.mock("@/lib/api", () => api);

const toastSpies = vi.hoisted(() => ({
  show: vi.fn(),
  success: vi.fn(),
  error: vi.fn(),
  info: vi.fn(),
  warn: vi.fn(),
}));
vi.mock("@/components/ToastProvider", () => ({ useToast: () => toastSpies }));

import { FeatureFlagsTab } from "./FeatureFlags";

const FLAG = {
  key: "learning_loop", description: "AI learning loop (#673).", variants: ["off", "on"],
  client_visible: true, default_variant: "off", rollout_percent: 0, rollout_variant: null,
  updated_at: null, updated_by: null, updated_by_name: null, targets: [],
};

describe("FeatureFlagsTab", () => {
  afterEach(cleanup);

  beforeEach(() => {
    Object.values(api).forEach((f) => f.mockReset());
    Object.values(toastSpies).forEach((f) => f.mockReset());
    api.adminListFlags.mockResolvedValue({ flags: [FLAG] });
    api.adminListRoles.mockResolvedValue({ roles: [{ id: "r-admin", name: "Admin" }] });
    api.adminFetchUsers.mockResolvedValue({ users: [], total: 0, page: 1, page_size: 8 });
  });

  it("lists flags", async () => {
    render(<FeatureFlagsTab />);
    expect(await screen.findByTestId("flag-row-learning_loop")).toBeTruthy();
  });

  it("requires a confirming second click before saving a default change", async () => {
    api.adminUpdateFlag.mockResolvedValue({ flag: { ...FLAG, default_variant: "on" } });
    render(<FeatureFlagsTab />);
    fireEvent.click(await screen.findByTestId("flag-row-learning_loop"));
    fireEvent.change(screen.getByTestId("flag-default-learning_loop"), { target: { value: "on" } });

    const save = screen.getByTestId("flag-save-learning_loop");
    fireEvent.click(save);
    expect(api.adminUpdateFlag).not.toHaveBeenCalled();

    fireEvent.click(save);
    await waitFor(() => expect(api.adminUpdateFlag).toHaveBeenCalledWith(
      "learning_loop", { default_variant: "on", rollout_percent: 0, rollout_variant: null }));
  });

  it("does not save without the confirming second click", async () => {
    render(<FeatureFlagsTab />);
    fireEvent.click(await screen.findByTestId("flag-row-learning_loop"));
    fireEvent.change(screen.getByTestId("flag-default-learning_loop"), { target: { value: "on" } });
    fireEvent.click(screen.getByTestId("flag-save-learning_loop"));
    expect(api.adminUpdateFlag).not.toHaveBeenCalled();
  });

  it("explains a student's variant", async () => {
    api.adminExplainFlag.mockResolvedValue({ variant: "on", step: "role", detail: "r-admin" });
    render(<FeatureFlagsTab />);
    fireEvent.click(await screen.findByTestId("flag-row-learning_loop"));
    fireEvent.change(screen.getByTestId("flag-explain-input-learning_loop"), { target: { value: "u1" } });
    fireEvent.keyDown(screen.getByTestId("flag-explain-input-learning_loop"), { key: "Enter" });
    expect((await screen.findByTestId("flag-explain-result-learning_loop")).textContent)
      .toContain("on (role: r-admin)");
    expect(api.adminExplainFlag).toHaveBeenCalledWith("learning_loop", "u1");
  });

  it("adds and removes a rule", async () => {
    const withTarget = {
      ...FLAG,
      targets: [{ target_type: "role" as const, target_id: "r-admin", label: "Admin", variant: "on" }],
    };
    api.adminUpsertFlagTarget.mockResolvedValue({ flag: withTarget });
    api.adminDeleteFlagTarget.mockResolvedValue({ flag: FLAG });

    render(<FeatureFlagsTab />);
    fireEvent.click(await screen.findByTestId("flag-row-learning_loop"));
    fireEvent.change(screen.getByTestId("flag-target-role-learning_loop"), { target: { value: "r-admin" } });
    fireEvent.click(screen.getByTestId("flag-target-add-learning_loop"));
    await waitFor(() => expect(api.adminUpsertFlagTarget).toHaveBeenCalledWith(
      "learning_loop", { target_type: "role", target_id: "r-admin", variant: "on" }));

    expect(await screen.findByTestId("flag-target-row-learning_loop-role-r-admin")).toBeTruthy();

    fireEvent.click(screen.getByTestId("flag-target-remove-learning_loop-role-r-admin"));
    await waitFor(() => expect(api.adminDeleteFlagTarget).toHaveBeenCalledWith("learning_loop", "role", "r-admin"));
  });
});

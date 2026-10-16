// @vitest-environment jsdom
/**
 * The admin "Feature flags" tab (`FeatureFlagsTab` in ./FeatureFlags, #620).
 *
 * What's pinned here:
 *   - flags render grouped like the nav, a row per flag (`flag-row-{key}`),
 *     in Visible/Hidden words — never the raw "on"/"off" of a hide flag;
 *   - the row switch changes the everyone-default only after a confirm
 *     dialog that states the scope (design spec §7);
 *   - clicking a row opens the right-hand panel; default/rollout edits are
 *     staged, the footer states their scope, and only Save calls
 *     `adminUpdateFlag` (Discard drops them);
 *   - overrides add/remove immediately; the student check renders the
 *     explain answer in words.
 */
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
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
  key: "hide_quiz", description: "Hide Quiz from the nav; its pages redirect to /dashboard.", variants: ["off", "on"],
  client_visible: true, default_variant: "off", rollout_percent: 0, rollout_variant: null,
  updated_at: null, updated_by: null, updated_by_name: null, targets: [],
};
const LIBRARY = { ...FLAG, key: "hide_library", description: "Hide Library from the nav." };

const openPanel = async () => {
  fireEvent.click(await screen.findByTestId("flag-row-hide_quiz"));
  return screen.findByTestId("flag-panel-hide_quiz");
};

describe("FeatureFlagsTab", () => {
  afterEach(cleanup);

  beforeEach(() => {
    Object.values(api).forEach((f) => f.mockReset());
    Object.values(toastSpies).forEach((f) => f.mockReset());
    api.adminListFlags.mockResolvedValue({ flags: [LIBRARY, FLAG] });
    api.adminListRoles.mockResolvedValue({ roles: [{ id: "r-admin", name: "Admin" }] });
    api.adminFetchUsers.mockResolvedValue({ users: [], total: 0, page: 1, page_size: 6 });
  });

  it("groups flags like the nav and speaks Visible/Hidden", async () => {
    render(<FeatureFlagsTab />);
    expect(await screen.findByTestId("flag-row-hide_quiz")).toBeTruthy();
    const learn = screen.getByRole("region", { name: "Learn" });
    expect(within(learn).getByTestId("flag-row-hide_quiz")).toBeTruthy();
    expect(within(screen.getByRole("region", { name: "Organize" })).getByTestId("flag-row-hide_library")).toBeTruthy();
    expect(screen.getByTestId("flag-state-hide_quiz").textContent).toBe("Visible");
    expect(screen.getByTestId("flag-toggle-hide_quiz").getAttribute("aria-checked")).toBe("true");
  });

  it("the row switch saves only after the confirm dialog, which states the scope", async () => {
    api.adminUpdateFlag.mockResolvedValue({ flag: { ...FLAG, default_variant: "on" } });
    render(<FeatureFlagsTab />);
    fireEvent.click(await screen.findByTestId("flag-toggle-hide_quiz"));

    expect(api.adminUpdateFlag).not.toHaveBeenCalled();
    expect(screen.queryByTestId("flag-panel-hide_quiz")).toBeNull(); // the switch doesn't open the row
    expect(screen.getByTestId("flag-save-scope-hide_quiz").textContent).toContain("Quiz becomes Hidden for everyone");

    fireEvent.click(screen.getByTestId("flag-confirm-hide_quiz"));
    await waitFor(() => expect(api.adminUpdateFlag).toHaveBeenCalledWith("hide_quiz", { default_variant: "on" }));
    expect((await screen.findByTestId("flag-state-hide_quiz")).textContent).toBe("Hidden");
  });

  it("cancelling the confirm dialog saves nothing", async () => {
    render(<FeatureFlagsTab />);
    fireEvent.click(await screen.findByTestId("flag-toggle-hide_quiz"));
    fireEvent.click(screen.getByTestId("flag-cancel-hide_quiz"));
    expect(screen.queryByTestId("flag-save-scope-hide_quiz")).toBeNull();
    expect(api.adminUpdateFlag).not.toHaveBeenCalled();
  });

  it("flipping the default to what a rollout serves ends that rollout", async () => {
    api.adminListFlags.mockResolvedValue({ flags: [{ ...FLAG, rollout_percent: 25, rollout_variant: "on" }] });
    api.adminUpdateFlag.mockResolvedValue({ flag: { ...FLAG, default_variant: "on" } });
    render(<FeatureFlagsTab />);
    fireEvent.click(await screen.findByTestId("flag-toggle-hide_quiz"));
    expect(screen.getByTestId("flag-save-scope-hide_quiz").textContent).toContain("rollout ends");
    fireEvent.click(screen.getByTestId("flag-confirm-hide_quiz"));
    await waitFor(() => expect(api.adminUpdateFlag).toHaveBeenCalledWith(
      "hide_quiz", { default_variant: "on", rollout_percent: 0, rollout_variant: null }));
  });

  it("panel edits are staged: the footer states the scope and only Save writes", async () => {
    api.adminUpdateFlag.mockResolvedValue({ flag: { ...FLAG, rollout_percent: 25, rollout_variant: "on" } });
    render(<FeatureFlagsTab />);
    await openPanel();

    expect(screen.queryByTestId("flag-save-hide_quiz")).toBeNull(); // nothing to save yet
    fireEvent.click(screen.getByTestId("flag-rollout-preset-hide_quiz-25"));
    expect(screen.getByTestId("flag-save-scope-hide_quiz").textContent).toContain("Hidden for 25% of students");
    expect(api.adminUpdateFlag).not.toHaveBeenCalled();

    fireEvent.click(screen.getByTestId("flag-save-hide_quiz"));
    await waitFor(() => expect(api.adminUpdateFlag).toHaveBeenCalledWith(
      "hide_quiz", { default_variant: "off", rollout_percent: 25, rollout_variant: "on" }));
  });

  it("Discard drops staged edits", async () => {
    render(<FeatureFlagsTab />);
    await openPanel();
    fireEvent.click(screen.getByTestId("flag-default-hide_quiz-on"));
    expect(screen.getByTestId("flag-save-scope-hide_quiz")).toBeTruthy();
    fireEvent.click(screen.getByTestId("flag-discard-hide_quiz"));
    expect(screen.queryByTestId("flag-save-scope-hide_quiz")).toBeNull();
    expect(api.adminUpdateFlag).not.toHaveBeenCalled();
  });

  it("explains a student's variant in words", async () => {
    api.adminExplainFlag.mockResolvedValue({ variant: "on", step: "role", detail: "r-admin" });
    render(<FeatureFlagsTab />);
    await openPanel();
    fireEvent.change(screen.getByTestId("flag-explain-input-hide_quiz"), { target: { value: "u1" } });
    fireEvent.keyDown(screen.getByTestId("flag-explain-input-hide_quiz"), { key: "Enter" });
    expect((await screen.findByTestId("flag-explain-result-hide_quiz")).textContent)
      .toContain("Hidden: from the Admin role override");
    expect(api.adminExplainFlag).toHaveBeenCalledWith("hide_quiz", "u1");
  });

  it("adds and removes an override", async () => {
    const withTarget = {
      ...FLAG,
      targets: [{ target_type: "role" as const, target_id: "r-admin", label: "Admin", variant: "on" }],
    };
    api.adminUpsertFlagTarget.mockResolvedValue({ flag: withTarget });
    api.adminDeleteFlagTarget.mockResolvedValue({ flag: FLAG });

    render(<FeatureFlagsTab />);
    await openPanel();
    fireEvent.change(screen.getByTestId("flag-target-role-hide_quiz"), { target: { value: "r-admin" } });
    fireEvent.click(screen.getByTestId("flag-target-add-hide_quiz"));
    await waitFor(() => expect(api.adminUpsertFlagTarget).toHaveBeenCalledWith(
      "hide_quiz", { target_type: "role", target_id: "r-admin", variant: "on" }));

    expect(await screen.findByTestId("flag-target-row-hide_quiz-role-r-admin")).toBeTruthy();

    fireEvent.click(screen.getByTestId("flag-target-remove-hide_quiz-role-r-admin"));
    await waitFor(() => expect(api.adminDeleteFlagTarget).toHaveBeenCalledWith("hide_quiz", "role", "r-admin"));
  });
});

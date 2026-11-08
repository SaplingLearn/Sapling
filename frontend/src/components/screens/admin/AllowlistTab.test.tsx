// @vitest-environment jsdom
/**
 * The admin "Allowlist" tab (`AllowlistTab` in ./AllowlistTab).
 *
 * What's pinned here:
 *   - "select all" selects only the unapproved rows the current filter +
 *     search show (approved/joined rows have no checkbox);
 *   - bulk approve opens a confirm dialog and only then calls the bulk API
 *     with exactly the selected emails; the dialog copy follows
 *     `/email/status`;
 *   - the status filter chips carry counts and compose with search;
 *   - the Invite column renders `invite_status` as chips with tooltips.
 */
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({
  adminListAllowlist: vi.fn(),
  adminApproveAllowlist: vi.fn(),
  adminApproveAllowlistBulk: vi.fn(),
  adminRevokeAllowlist: vi.fn(),
  adminEmailStatus: vi.fn(),
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

import { AllowlistTab } from "./AllowlistTab";

const row = (email: string, over: Record<string, unknown> = {}) => ({
  id: `id-${email}`, email, created_at: "2026-10-01T00:00:00Z",
  approved_at: null, joined_at: null, joined_user_id: null, invite_status: null,
  ...over,
});

const ROWS = [
  row("alice@bu.edu"),
  row("bob@bu.edu"),
  row("carol@bu.edu", { approved_at: "2026-10-02T00:00:00Z", invite_status: "sent" }),
  row("dave@bu.edu", { approved_at: "2026-10-02T00:00:00Z", joined_at: "2026-10-03T00:00:00Z", invite_status: "failed" }),
  row("erin@bu.edu", { approved_at: "2026-10-02T00:00:00Z", invite_status: "skipped" }),
  row("frank@bu.edu", { approved_at: "2026-10-02T00:00:00Z", invite_status: "suppressed" }),
];

const checked = (id: string) => (screen.getByTestId(id) as HTMLInputElement).checked;

describe("AllowlistTab", () => {
  afterEach(cleanup);

  beforeEach(() => {
    Object.values(api).forEach((f) => f.mockReset());
    Object.values(toastSpies).forEach((f) => f.mockReset());
    api.adminListAllowlist.mockResolvedValue({ emails: ROWS });
    api.adminEmailStatus.mockResolvedValue({ configured: true, from_address: "hi@sapling.test" });
  });

  it("select-all selects only the unapproved rows the filter shows", async () => {
    render(<AllowlistTab />);
    await screen.findByTestId("allowlist-row-alice@bu.edu");
    // Approved / joined rows get no checkbox at all.
    expect(screen.queryByTestId("allowlist-select-carol@bu.edu")).toBeNull();
    expect(screen.queryByTestId("allowlist-select-dave@bu.edu")).toBeNull();

    // Search "ali" narrows the signups to alice.
    fireEvent.change(screen.getByTestId("allowlist-search"), { target: { value: "ali" } });
    fireEvent.click(screen.getByTestId("allowlist-select-all"));
    expect(checked("allowlist-select-alice@bu.edu")).toBe(true);
    expect(screen.getByTestId("allowlist-bulk-approve").textContent).toBe("Approve selected (1)");

    // Clearing the search reveals bob, still unselected.
    fireEvent.change(screen.getByTestId("allowlist-search"), { target: { value: "" } });
    expect(checked("allowlist-select-bob@bu.edu")).toBe(false);
    expect(checked("allowlist-select-all")).toBe(false);

    fireEvent.click(screen.getByTestId("allowlist-select-all"));
    expect(checked("allowlist-select-bob@bu.edu")).toBe(true);
    expect(screen.getByTestId("allowlist-bulk-approve").textContent).toBe("Approve selected (2)");

    // Second click clears the visible selection.
    fireEvent.click(screen.getByTestId("allowlist-select-all"));
    expect(screen.getByTestId("allowlist-bulk-approve").textContent).toBe("Approve selected (0)");
    expect((screen.getByTestId("allowlist-bulk-approve") as HTMLButtonElement).disabled).toBe(true);
  });

  it("bulk approve calls the API with the selected emails only after confirm", async () => {
    api.adminApproveAllowlistBulk.mockResolvedValue({ approved: 2, emails: [] });
    render(<AllowlistTab />);
    await screen.findByTestId("allowlist-row-alice@bu.edu");

    fireEvent.click(screen.getByTestId("allowlist-select-all"));
    fireEvent.click(screen.getByTestId("allowlist-bulk-approve"));

    expect(api.adminApproveAllowlistBulk).not.toHaveBeenCalled();
    expect((await screen.findByTestId("allowlist-bulk-confirm-text")).textContent).toContain("you’re in");
    expect(screen.getByRole("dialog").textContent).toContain("Approve 2 people?");

    fireEvent.click(screen.getByTestId("allowlist-bulk-confirm"));
    await waitFor(() =>
      expect(api.adminApproveAllowlistBulk).toHaveBeenCalledWith(["alice@bu.edu", "bob@bu.edu"]),
    );
    await waitFor(() => expect(toastSpies.success).toHaveBeenCalledWith(expect.stringContaining("Approved 2 of 2")));
    await waitFor(() => expect(screen.queryByTestId("allowlist-bulk-confirm")).toBeNull());
    expect(api.adminListAllowlist).toHaveBeenCalledTimes(2); // reloaded
  });

  it("warns in the confirm dialog and banner when email isn't configured", async () => {
    api.adminEmailStatus.mockResolvedValue({ configured: false, from_address: "" });
    render(<AllowlistTab />);
    expect(await screen.findByTestId("email-not-configured-banner")).toBeTruthy();
    fireEvent.click(screen.getByTestId("allowlist-select-alice@bu.edu"));
    fireEvent.click(screen.getByTestId("allowlist-bulk-approve"));
    const text = await screen.findByTestId("allowlist-bulk-confirm-text");
    expect(text.textContent).toContain("no emails go out until Resend is configured");
  });

  it("filter chips carry counts and compose with search", async () => {
    render(<AllowlistTab />);
    await screen.findByTestId("allowlist-row-alice@bu.edu");
    expect(screen.getByTestId("allowlist-filter-all").textContent).toBe("All (6)");
    expect(screen.getByTestId("allowlist-filter-signup").textContent).toBe("Signups (2)");
    expect(screen.getByTestId("allowlist-filter-approved").textContent).toBe("Approved (3)");
    expect(screen.getByTestId("allowlist-filter-joined").textContent).toBe("Joined (1)");

    fireEvent.click(screen.getByTestId("allowlist-filter-approved"));
    expect(screen.queryByTestId("allowlist-row-alice@bu.edu")).toBeNull();
    expect(screen.queryByTestId("allowlist-row-dave@bu.edu")).toBeNull();
    expect(screen.getByTestId("allowlist-row-carol@bu.edu")).toBeTruthy();
    expect(screen.getByTestId("allowlist-row-erin@bu.edu")).toBeTruthy();

    fireEvent.change(screen.getByTestId("allowlist-search"), { target: { value: "erin" } });
    expect(screen.queryByTestId("allowlist-row-carol@bu.edu")).toBeNull();
    expect(screen.getByTestId("allowlist-row-erin@bu.edu")).toBeTruthy();

    fireEvent.click(screen.getByTestId("allowlist-filter-joined"));
    expect(screen.queryByTestId("allowlist-row-erin@bu.edu")).toBeNull();
    expect(screen.getByText("No addresses match.")).toBeTruthy();
  });

  it("renders invite_status as chips with explanatory tooltips", async () => {
    render(<AllowlistTab />);
    await screen.findByTestId("allowlist-row-alice@bu.edu");

    const sent = screen.getByTestId("allowlist-invite-carol@bu.edu");
    expect(sent.textContent).toBe("sent");
    expect(sent.className).toContain("chip--accent");

    const failed = screen.getByTestId("allowlist-invite-dave@bu.edu");
    expect(failed.className).toContain("chip--warn");

    const skipped = screen.getByTestId("allowlist-invite-erin@bu.edu");
    expect(skipped.className).not.toMatch(/chip--(accent|warn)/);
    expect(skipped.getAttribute("title")).toContain("Resend not configured");

    expect(screen.getByTestId("allowlist-invite-frank@bu.edu").getAttribute("title")).toContain("unsubscribed");

    // No invite yet → em dash, no chip.
    expect(screen.queryByTestId("allowlist-invite-alice@bu.edu")).toBeNull();
  });

  it("single Approve toasts from the returned invite status", async () => {
    api.adminApproveAllowlist.mockResolvedValue({ email: row("bob@bu.edu", { approved_at: "x", invite_status: "sent" }) });
    render(<AllowlistTab />);
    fireEvent.click(await screen.findByTestId("allowlist-toggle-bob@bu.edu"));
    await waitFor(() => expect(api.adminApproveAllowlist).toHaveBeenCalledWith("bob@bu.edu"));
    await waitFor(() => expect(toastSpies.success).toHaveBeenCalledWith(expect.stringContaining("email sent")));
  });
});

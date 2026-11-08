// @vitest-environment jsdom
/**
 * Admin → Users → "Account tools" (`AccountToolsDialog`).
 *
 * What's pinned here:
 *   - `/meta` loads on open and the environment badge names it (PRODUCTION
 *     in the danger style), with the selected major's course codes listed;
 *   - every action stays disabled until the account's email is typed
 *     (case-insensitive); an undecryptable row confirms by user id;
 *   - seed sends the chosen major, wipe calls wipe, and both toast a summed
 *     row count and close;
 *   - copy is a muted note when sync isn't configured, two direction buttons
 *     naming the peer when it is, and disabled + "unreachable" when the peer
 *     is null;
 *   - a failed action toasts the humanized error and keeps the dialog open.
 */
import React from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";

const toastSpies = vi.hoisted(() => ({
  success: vi.fn(),
  error: vi.fn(),
  warn: vi.fn(),
}));
vi.mock("../../ToastProvider", () => ({
  useToast: () => toastSpies,
}));

const api = vi.hoisted(() => ({
  adminAccountsMeta: vi.fn(),
  adminSeedAccount: vi.fn(),
  adminWipeAccount: vi.fn(),
  adminCopyAccount: vi.fn(),
}));
vi.mock("@/lib/api", () => api);

import { AccountToolsDialog } from "./AccountToolsDialog";

const ADA = {
  id: "u-ada", name: "Ada Lovelace", email: "Ada@bu.edu", is_approved: true,
  last_sign_in_at: null, created_at: "2026-10-01T00:00:00Z", roles: [],
};

const META = {
  env: "production",
  majors: [
    {
      key: "cs", label: "Computer Science",
      courses: [
        { code: "CAS CS 111", name: "Intro to CS 1" },
        { code: "CAS CS 112", name: "Intro to CS 2" },
        { code: "CAS CS 131", name: "Combinatoric Structures" },
        { code: "CAS MA 123", name: "Calculus I" },
      ],
    },
    {
      key: "biology", label: "Biology",
      courses: [
        { code: "CAS BI 107", name: "Biology 1" },
        { code: "CAS BI 108", name: "Biology 2" },
        { code: "CAS CH 101", name: "General Chemistry" },
        { code: "CAS MA 115", name: "Statistics" },
      ],
    },
  ],
  sync: { configured: false, peer_env: null },
};

const onClose = vi.fn();

beforeEach(() => {
  api.adminAccountsMeta.mockResolvedValue(META);
  api.adminSeedAccount.mockResolvedValue({
    major: "biology", wiped: { notes: 2 }, created: { notes: 8, flashcards: 24, documents: 8 },
  });
  api.adminWipeAccount.mockResolvedValue({ wiped: { notes: 8, flashcards: 24 } });
  api.adminCopyAccount.mockResolvedValue({ direction: "push", peer_env: "staging", counts: { notes: 3, sessions: 1 } });
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

const open = async (user: typeof ADA | (Omit<typeof ADA, "email"> & { email: string | null }) = ADA) => {
  render(<AccountToolsDialog user={user} onClose={onClose} />);
  return screen.findByTestId("admin-account-env-badge");
};

const confirm = (text = "ada@BU.edu") =>
  fireEvent.change(screen.getByTestId("admin-account-confirm-input"), { target: { value: text } });

const btn = (id: string) => screen.getByTestId(id) as HTMLButtonElement;

describe("AccountToolsDialog", () => {
  it("renders nothing without a user", () => {
    render(<AccountToolsDialog user={null} onClose={onClose} />);
    expect(screen.queryByTestId("admin-account-tools")).toBeNull();
    expect(api.adminAccountsMeta).not.toHaveBeenCalled();
  });

  it("loads meta and shows the environment badge and the selected major's courses", async () => {
    const badge = await open();
    expect(api.adminAccountsMeta).toHaveBeenCalledTimes(1);
    expect(badge.textContent).toBe("PRODUCTION");
    expect(screen.getByTestId("admin-account-env").getAttribute("data-env")).toBe("production");
    expect(screen.getByTestId("admin-account-env").textContent).toMatch(/production database/);

    const courses = screen.getByTestId("admin-account-major-courses");
    expect(courses.textContent).toContain("CAS CS 111");
    expect(courses.querySelectorAll("li")).toHaveLength(4);

    fireEvent.change(screen.getByTestId("admin-account-major"), { target: { value: "biology" } });
    expect(screen.getByTestId("admin-account-major-courses").textContent).toContain("CAS BI 107");
    expect(screen.getByTestId("admin-account-major-courses").textContent).not.toContain("CAS CS 111");
  });

  it("keeps every action disabled until the account's email is typed (case-insensitive)", async () => {
    api.adminAccountsMeta.mockResolvedValue({ ...META, sync: { configured: true, peer_env: "staging" } });
    await open();
    for (const id of ["admin-account-seed", "admin-account-wipe", "admin-account-copy-push", "admin-account-copy-pull"]) {
      expect(btn(id).disabled).toBe(true);
    }
    confirm("ada@bu.ed");
    expect(btn("admin-account-wipe").disabled).toBe(true);

    confirm("  ADA@bu.edu ");
    for (const id of ["admin-account-seed", "admin-account-wipe", "admin-account-copy-push", "admin-account-copy-pull"]) {
      expect(btn(id).disabled).toBe(false);
    }
    expect(api.adminSeedAccount).not.toHaveBeenCalled();
    expect(api.adminWipeAccount).not.toHaveBeenCalled();
  });

  it("confirms an undecryptable account by its user id", async () => {
    await open({ ...ADA, email: null });
    confirm("u-ada");
    expect(btn("admin-account-wipe").disabled).toBe(false);
  });

  it("seeds with the chosen major, toasts a row count, and closes", async () => {
    await open();
    fireEvent.change(screen.getByTestId("admin-account-major"), { target: { value: "biology" } });
    confirm();
    fireEvent.click(btn("admin-account-seed"));

    await waitFor(() => expect(api.adminSeedAccount).toHaveBeenCalledWith("u-ada", "biology"));
    await waitFor(() => expect(onClose).toHaveBeenCalled());
    expect(toastSpies.success).toHaveBeenCalledWith(
      "Seeded Ada Lovelace with Biology: created 40 rows, replaced 2 rows.",
    );
  });

  it("wipes, toasts the removed row count, and closes", async () => {
    await open();
    confirm();
    fireEvent.click(btn("admin-account-wipe"));

    await waitFor(() => expect(api.adminWipeAccount).toHaveBeenCalledWith("u-ada"));
    await waitFor(() => expect(onClose).toHaveBeenCalled());
    expect(toastSpies.success).toHaveBeenCalledWith("Wiped Ada Lovelace's data: removed 32 rows.");
  });

  it("disables every action while one runs", async () => {
    let resolveWipe: (v: unknown) => void = () => {};
    api.adminWipeAccount.mockReturnValue(new Promise((r) => { resolveWipe = r; }));
    await open();
    confirm();
    fireEvent.click(btn("admin-account-wipe"));

    await waitFor(() => expect(btn("admin-account-wipe").textContent).toBe("Wiping…"));
    expect(btn("admin-account-seed").disabled).toBe(true);
    expect(btn("admin-account-close").disabled).toBe(true);
    resolveWipe({ wiped: {} });
    await waitFor(() => expect(onClose).toHaveBeenCalled());
  });

  it("shows a muted note instead of copy buttons when sync isn't configured", async () => {
    await open();
    expect(screen.getByTestId("admin-account-copy-unconfigured")).toBeTruthy();
    expect(screen.queryByTestId("admin-account-copy-push")).toBeNull();
    expect(screen.queryByTestId("admin-account-copy-pull")).toBeNull();
  });

  it("offers push and pull naming the peer when sync is configured", async () => {
    api.adminAccountsMeta.mockResolvedValue({ ...META, env: "staging", sync: { configured: true, peer_env: "production" } });
    await open();
    expect(btn("admin-account-copy-push").textContent).toBe("Copy to production");
    expect(btn("admin-account-copy-pull").textContent).toBe("Copy from production");

    api.adminCopyAccount.mockResolvedValue({ direction: "pull", peer_env: "production", counts: { notes: 3, sessions: 1 } });
    confirm();
    fireEvent.click(btn("admin-account-copy-pull"));
    await waitFor(() => expect(api.adminCopyAccount).toHaveBeenCalledWith("u-ada", "pull"));
    await waitFor(() => expect(toastSpies.success).toHaveBeenCalledWith("Copied Ada Lovelace from production: 4 rows."));
  });

  it("disables copy and says so when the peer is unreachable", async () => {
    api.adminAccountsMeta.mockResolvedValue({ ...META, sync: { configured: true, peer_env: null } });
    await open();
    confirm();
    expect(screen.getByTestId("admin-account-copy-unreachable")).toBeTruthy();
    expect(btn("admin-account-copy-push").disabled).toBe(true);
    expect(btn("admin-account-copy-pull").disabled).toBe(true);
    expect(btn("admin-account-wipe").disabled).toBe(false);
  });

  it("keeps the dialog open and toasts the backend's sentence on error", async () => {
    api.adminWipeAccount.mockRejectedValue(
      Object.assign(new Error('{"detail":"An operation is already running for this account."}'), {
        status: 409,
        body: { detail: "An operation is already running for this account." },
      }),
    );
    await open();
    confirm();
    fireEvent.click(btn("admin-account-wipe"));

    await waitFor(() =>
      expect(toastSpies.error).toHaveBeenCalledWith("An operation is already running for this account."),
    );
    expect(onClose).not.toHaveBeenCalled();
    expect(toastSpies.success).not.toHaveBeenCalled();
    expect(screen.getByTestId("admin-account-tools")).toBeTruthy();
    await waitFor(() => expect(btn("admin-account-wipe").disabled).toBe(false));
  });

  it("shows a retry when meta fails to load", async () => {
    api.adminAccountsMeta.mockRejectedValueOnce(new Error("boom"));
    render(<AccountToolsDialog user={ADA} onClose={onClose} />);
    await screen.findByTestId("admin-account-meta-error");
    expect(btn("admin-account-wipe").disabled).toBe(true);

    fireEvent.click(btn("admin-account-meta-retry"));
    expect((await screen.findByTestId("admin-account-env-badge")).textContent).toBe("PRODUCTION");
  });
});

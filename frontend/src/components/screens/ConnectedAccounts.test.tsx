// @vitest-environment jsdom
/** #770: the Gradescope card reports the connection STATE, not row existence. */
import React from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";

const toast = vi.hoisted(() => ({
  show: vi.fn(), dismiss: vi.fn(), success: vi.fn(), error: vi.fn(), info: vi.fn(), warn: vi.fn(),
}));
vi.mock("@/components/ToastProvider", () => ({ useToast: () => toast }));
vi.mock("@/context/UserContext", () => ({ useUser: () => ({ userId: "u1", userReady: true }) }));
vi.mock("@/lib/api", () => ({ getGradescopeStatus: vi.fn(), deleteGradescopeCredentials: vi.fn() }));
vi.mock("next/link", () => ({
  default: ({ children }: { children?: React.ReactNode }) => <>{children}</>,
}));
vi.mock("@/components/TopBar", () => ({ TopBar: () => null }));
vi.mock("@/components/Gradebook/GradescopeSyncModal", () => ({ GradescopeSyncModal: () => null }));

import { ConnectedAccounts } from "./ConnectedAccounts";
import { getGradescopeStatus } from "@/lib/api";

afterEach(() => { cleanup(); vi.resetAllMocks(); });

describe("ConnectedAccounts Gradescope card", () => {
  it("shows rejected credentials as needing a reconnect, not as connected", async () => {
    vi.mocked(getGradescopeStatus).mockResolvedValue({
      has_credentials: true, auth_mode: "cookies", last_synced_at: null,
      state: "needs_reauth", needs_reauth: true, connected: false, last_sync_error: "auth_failed",
    });
    render(<ConnectedAccounts />);
    expect(await screen.findByText("Sign-in expired · reconnect needed")).toBeInTheDocument();
    expect(screen.queryByText(/Credentials saved/)).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Reconnect" })).toBeInTheDocument();
  });

  it("reports a disconnected account (links may survive) as not connected", async () => {
    vi.mocked(getGradescopeStatus).mockResolvedValue({
      has_credentials: false, auth_mode: null, last_synced_at: null, state: "disconnected",
    });
    render(<ConnectedAccounts />);
    expect(await screen.findByText("Not connected")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Connect" })).toBeInTheDocument();
  });

  it("surfaces the last failed sync attempt on a working connection", async () => {
    vi.mocked(getGradescopeStatus).mockResolvedValue({
      has_credentials: true, auth_mode: "password", last_synced_at: null,
      state: "connected", last_sync_error: "fetch_failed", last_attempt_at: null,
    });
    render(<ConnectedAccounts />);
    expect(await screen.findByText(/Gradescope was unavailable/)).toBeInTheDocument();
  });

  it("does not claim 'not connected' when the status read itself failed", async () => {
    vi.mocked(getGradescopeStatus).mockRejectedValue(new Error("network"));
    render(<ConnectedAccounts />);
    expect(await screen.findByText("Couldn't check status")).toBeInTheDocument();
    expect(screen.queryByText("Not connected")).not.toBeInTheDocument();
  });
});

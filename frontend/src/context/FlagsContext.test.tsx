// @vitest-environment jsdom
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const fetchFlags = vi.fn();
vi.mock("@/lib/flags", () => ({ fetchFlags: () => fetchFlags() }));
const setProductAnalyticsFlag = vi.fn();
vi.mock("@/lib/analytics", () => ({ setProductAnalyticsFlag: (on: boolean) => setProductAnalyticsFlag(on) }));
let pathname = "/dashboard";
vi.mock("next/navigation", () => ({ usePathname: () => pathname }));
let user = { userId: "u1", isAuthenticated: true, userReady: true };
vi.mock("@/context/UserContext", () => ({ useUser: () => user }));

import { FlagsProvider, useFlag } from "./FlagsContext";

function Probe() {
  return <span data-testid="v">{useFlag("learning_loop")}</span>;
}

describe("FlagsProvider/useFlag", () => {
  beforeEach(() => {
    fetchFlags.mockReset(); setProductAnalyticsFlag.mockReset();
    pathname = "/dashboard"; user = { userId: "u1", isAuthenticated: true, userReady: true };
  });
  afterEach(() => {
    cleanup();
  });

  it("is off until loaded, then the fetched variant", async () => {
    let resolve!: (v: Record<string, string>) => void;
    fetchFlags.mockReturnValue(new Promise((r) => { resolve = r; }));
    render(<FlagsProvider><Probe /></FlagsProvider>);
    expect(screen.getByTestId("v").textContent).toBe("off");
    resolve({ learning_loop: "on", product_analytics: "on" });
    await waitFor(() => expect(screen.getByTestId("v").textContent).toBe("on"));
    expect(setProductAnalyticsFlag).toHaveBeenLastCalledWith(true);
  });

  it("fails closed on error and turns analytics off", async () => {
    fetchFlags.mockRejectedValue(new Error("down"));
    render(<FlagsProvider><Probe /></FlagsProvider>);
    await waitFor(() => expect(setProductAnalyticsFlag).toHaveBeenCalledWith(false));
    expect(screen.getByTestId("v").textContent).toBe("off");
  });

  it("does not fetch off the app shell and reads off", () => {
    pathname = "/privacy";
    render(<FlagsProvider><Probe /></FlagsProvider>);
    expect(fetchFlags).not.toHaveBeenCalled();
    expect(screen.getByTestId("v").textContent).toBe("off");
  });

  it("drops the previous user's analytics flag as soon as a switch refetches", async () => {
    fetchFlags.mockResolvedValueOnce({ product_analytics: "on" });
    const { rerender } = render(<FlagsProvider><Probe /></FlagsProvider>);
    await waitFor(() => expect(setProductAnalyticsFlag).toHaveBeenLastCalledWith(true));
    let second!: (v: Record<string, string>) => void;
    fetchFlags.mockReturnValueOnce(new Promise((r) => { second = r; }));
    user = { userId: "u2", isAuthenticated: true, userReady: true };
    rerender(<FlagsProvider><Probe /></FlagsProvider>);
    // u2's flags are still in flight: u1's "on" must not stay in force.
    await waitFor(() => expect(fetchFlags).toHaveBeenCalledTimes(2));
    expect(setProductAnalyticsFlag).toHaveBeenLastCalledWith(false);
    second({ product_analytics: "on" });
    await waitFor(() => expect(setProductAnalyticsFlag).toHaveBeenLastCalledWith(true));
  });

  it("ignores a stale response after a user switch", async () => {
    let first!: (v: Record<string, string>) => void;
    fetchFlags.mockReturnValueOnce(new Promise((r) => { first = r; }))
      .mockResolvedValueOnce({ learning_loop: "off" });
    const { rerender } = render(<FlagsProvider><Probe /></FlagsProvider>);
    user = { userId: "u2", isAuthenticated: true, userReady: true };
    rerender(<FlagsProvider><Probe /></FlagsProvider>);
    first({ learning_loop: "on" });
    await waitFor(() => expect(fetchFlags).toHaveBeenCalledTimes(2));
    expect(screen.getByTestId("v").textContent).toBe("off");
  });
});

// @vitest-environment jsdom
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const fetchFlags = vi.fn();
vi.mock("@/lib/flags", () => ({ fetchFlags: () => fetchFlags() }));
let pathname = "/dashboard";
vi.mock("next/navigation", () => ({ usePathname: () => pathname }));
let user = { userId: "u1", isAuthenticated: true, userReady: true };
vi.mock("@/context/UserContext", () => ({ useUser: () => user }));

import { FlagsProvider, useFlag, useFlagMap } from "./FlagsContext";

function Probe() {
  return <span data-testid="v">{useFlag("hide_quiz")}</span>;
}

function MapProbe() {
  const { flags, ready } = useFlagMap();
  return <span data-testid="m">{ready ? JSON.stringify(flags) : "loading"}</span>;
}

describe("FlagsProvider/useFlag", () => {
  beforeEach(() => {
    fetchFlags.mockReset();
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
    resolve({ hide_quiz: "on" });
    await waitFor(() => expect(screen.getByTestId("v").textContent).toBe("on"));
  });

  it("fails closed on error", async () => {
    fetchFlags.mockRejectedValue(new Error("down"));
    render(<FlagsProvider><Probe /></FlagsProvider>);
    await waitFor(() => expect(fetchFlags).toHaveBeenCalled());
    expect(screen.getByTestId("v").textContent).toBe("off");
  });

  it("does not fetch off the app shell and reads off", () => {
    pathname = "/privacy";
    render(<FlagsProvider><Probe /></FlagsProvider>);
    expect(fetchFlags).not.toHaveBeenCalled();
    expect(screen.getByTestId("v").textContent).toBe("off");
  });

  it("ignores a stale response after a user switch", async () => {
    let first!: (v: Record<string, string>) => void;
    fetchFlags.mockReturnValueOnce(new Promise((r) => { first = r; }))
      .mockResolvedValueOnce({ hide_quiz: "off" });
    const { rerender } = render(<FlagsProvider><Probe /></FlagsProvider>);
    user = { userId: "u2", isAuthenticated: true, userReady: true };
    rerender(<FlagsProvider><Probe /></FlagsProvider>);
    first({ hide_quiz: "on" });
    await waitFor(() => expect(fetchFlags).toHaveBeenCalledTimes(2));
    expect(screen.getByTestId("v").textContent).toBe("off");
  });

  it("useFlagMap is not ready until this user's flags arrive", async () => {
    let resolve!: (v: Record<string, string>) => void;
    fetchFlags.mockReturnValue(new Promise((r) => { resolve = r; }));
    render(<FlagsProvider><MapProbe /></FlagsProvider>);
    expect(screen.getByTestId("m").textContent).toBe("loading");
    resolve({ hide_quiz: "on" });
    await waitFor(() => expect(screen.getByTestId("m").textContent).toBe('{"hide_quiz":"on"}'));
  });

  it("useFlagMap is ready and empty when the fetch fails", async () => {
    fetchFlags.mockRejectedValue(new Error("down"));
    render(<FlagsProvider><MapProbe /></FlagsProvider>);
    await waitFor(() => expect(screen.getByTestId("m").textContent).toBe("{}"));
  });

  it("useFlagMap is not ready while a switched-to user's flags are in flight", async () => {
    fetchFlags.mockResolvedValueOnce({ hide_quiz: "on" });
    const { rerender } = render(<FlagsProvider><MapProbe /></FlagsProvider>);
    await waitFor(() => expect(screen.getByTestId("m").textContent).toBe('{"hide_quiz":"on"}'));
    let second!: (v: Record<string, string>) => void;
    fetchFlags.mockReturnValueOnce(new Promise((r) => { second = r; }));
    user = { userId: "u2", isAuthenticated: true, userReady: true };
    rerender(<FlagsProvider><MapProbe /></FlagsProvider>);
    expect(screen.getByTestId("m").textContent).toBe("loading");
    second({});
    await waitFor(() => expect(screen.getByTestId("m").textContent).toBe("{}"));
  });

  it("useFlagMap is ready at once when signed out, and off the shell", () => {
    user = { userId: "", isAuthenticated: false, userReady: true };
    render(<FlagsProvider><MapProbe /></FlagsProvider>);
    expect(screen.getByTestId("m").textContent).toBe("{}");
    cleanup();
    user = { userId: "u1", isAuthenticated: true, userReady: true };
    pathname = "/privacy";
    render(<FlagsProvider><MapProbe /></FlagsProvider>);
    expect(screen.getByTestId("m").textContent).toBe("{}");
  });
});

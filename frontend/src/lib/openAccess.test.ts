// @vitest-environment jsdom
/**
 * `useOpenAccess`: the public pages' read of `open_access`
 * (docs/design/open-access-gate.md). Fails closed: only a fresh "on" opens it.
 */
import { renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const fetchFlags = vi.hoisted(() => vi.fn());
vi.mock("@/lib/flags", () => ({ fetchFlags }));

import { useOpenAccess } from "./openAccess";

describe("useOpenAccess", () => {
  beforeEach(() => { fetchFlags.mockReset(); });

  it("is true when the flag reads on", async () => {
    fetchFlags.mockResolvedValue({ open_access: "on" });
    const { result } = renderHook(() => useOpenAccess());
    expect(result.current).toBe(false); // closed until the answer is in
    await waitFor(() => expect(result.current).toBe(true));
  });

  it.each([
    ["off", { open_access: "off" }],
    ["missing", {}],
  ])("is false when the flag is %s", async (_label, flags) => {
    fetchFlags.mockResolvedValue(flags);
    const { result } = renderHook(() => useOpenAccess());
    await waitFor(() => expect(fetchFlags).toHaveBeenCalled());
    expect(result.current).toBe(false);
  });

  it("is false when the read fails or the store is degraded", async () => {
    fetchFlags.mockImplementation(() => Promise.reject(new Error("flag store unreadable")));
    const { result } = renderHook(() => useOpenAccess());
    await waitFor(() => expect(fetchFlags).toHaveBeenCalled());
    expect(result.current).toBe(false);
  });
});

// @vitest-environment jsdom
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { renderHook, cleanup } from "@testing-library/react";

const toastApi = vi.hoisted(() => ({ error: vi.fn() }));
vi.mock("@/components/ToastProvider", () => ({
  useToast: () => toastApi,
}));

import { useCalendarConnectError } from "./useCalendarConnectError";

describe("useCalendarConnectError — a calendar connect that failed on its way to another page", () => {
  beforeEach(() => {
    toastApi.error.mockClear();
  });
  afterEach(() => {
    cleanup();
    window.history.replaceState(null, "", "/");
  });

  it("explains the code once and clears it, keeping the rest of the URL", () => {
    window.history.replaceState(null, "", "/gradebook?semester=Fall%202025&calendar_error=access_denied#top");
    renderHook(() => useCalendarConnectError());
    expect(toastApi.error).toHaveBeenCalledTimes(1);
    expect(toastApi.error).toHaveBeenCalledWith(expect.stringContaining("access wasn't allowed"));
    expect(window.location.pathname).toBe("/gradebook");
    expect(window.location.search).toBe("?semester=Fall+2025");
    expect(window.location.hash).toBe("#top");
  });

  it("does nothing without a code", () => {
    window.history.replaceState(null, "", "/gradebook?semester=Fall%202025");
    renderHook(() => useCalendarConnectError());
    expect(toastApi.error).not.toHaveBeenCalled();
    expect(window.location.search).toBe("?semester=Fall%202025");
  });
});

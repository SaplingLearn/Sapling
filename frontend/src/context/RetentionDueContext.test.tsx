// @vitest-environment jsdom
/**
 * Spec §13 A126: the shell's ONE "retention check due" read — behind the
 * `retention_due_badge` flag, once per signed-in student, then only on a slow
 * visible-tab cadence or an explicit refresh; a failed read hides the badge.
 */
import React from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, render, screen, waitFor } from "@testing-library/react";

const user = vi.hoisted(() => ({ state: { userId: "u1", isAuthenticated: true } }));
vi.mock("@/context/UserContext", () => ({ useUser: () => user.state }));
const flags = vi.hoisted(() => ({ value: "on" }));
vi.mock("@/context/FlagsContext", () => ({ useFlag: (key: string) => (key === "retention_due_badge" ? flags.value : "off") }));
const api = vi.hoisted(() => ({ fetchRetentionDue: vi.fn() }));
vi.mock("@/lib/api", () => api);

import {
  RETENTION_DUE_REFRESH_MS,
  RetentionDueProvider,
  retentionHref,
  useRetentionDue,
} from "./RetentionDueContext";

function Probe() {
  const { due, courseIds, refresh } = useRetentionDue();
  return (
    <div>
      <span data-testid="due">{due ? "due" : "none"}</span>
      <span data-testid="courses">{courseIds.join(",")}</span>
      <button onClick={refresh}>refresh</button>
    </div>
  );
}

function renderShell() {
  return render(<RetentionDueProvider><Probe /></RetentionDueProvider>);
}

describe("RetentionDueProvider", () => {
  beforeEach(() => {
    vi.resetAllMocks();
    user.state = { userId: "u1", isAuthenticated: true };
    flags.value = "on";
    Object.defineProperty(document, "visibilityState", { configurable: true, get: () => "visible" });
  });
  afterEach(() => { cleanup(); vi.useRealTimers(); });

  it("reads once for a signed-in student and exposes the due courses", async () => {
    api.fetchRetentionDue.mockResolvedValue({ due: true, course_ids: ["c1", "c2"] });
    renderShell();
    await waitFor(() => expect(screen.getByTestId("due").textContent).toBe("due"));
    expect(screen.getByTestId("courses").textContent).toBe("c1,c2");
    expect(api.fetchRetentionDue).toHaveBeenCalledTimes(1);
    expect(api.fetchRetentionDue).toHaveBeenCalledWith("u1");
  });

  it("fetches nothing while the flag is off or nobody is signed in", async () => {
    flags.value = "off";
    renderShell();
    await act(async () => {});
    cleanup();
    flags.value = "on";
    user.state = { userId: "", isAuthenticated: false };
    renderShell();
    await act(async () => {});
    expect(api.fetchRetentionDue).not.toHaveBeenCalled();
    expect(screen.getByTestId("due").textContent).toBe("none");
  });

  it("hides the badge when the read fails, never claiming a check is due", async () => {
    api.fetchRetentionDue.mockRejectedValue(new Error("503"));
    renderShell();
    await waitFor(() => expect(api.fetchRetentionDue).toHaveBeenCalledTimes(1));
    expect(screen.getByTestId("due").textContent).toBe("none");
  });

  it("asks again on refresh and on the slow cadence of a visible tab only", async () => {
    vi.useFakeTimers({ toFake: ["setInterval", "clearInterval"] });
    api.fetchRetentionDue.mockResolvedValue({ due: true, course_ids: ["c1"] });
    renderShell();
    await act(async () => {});
    expect(api.fetchRetentionDue).toHaveBeenCalledTimes(1);
    api.fetchRetentionDue.mockResolvedValue({ due: false, course_ids: [] });
    await act(async () => { screen.getByText("refresh").click(); });
    expect(api.fetchRetentionDue).toHaveBeenCalledTimes(2);
    expect(screen.getByTestId("due").textContent).toBe("none");
    await act(async () => { vi.advanceTimersByTime(RETENTION_DUE_REFRESH_MS); });
    expect(api.fetchRetentionDue).toHaveBeenCalledTimes(3);
    Object.defineProperty(document, "visibilityState", { configurable: true, get: () => "hidden" });
    await act(async () => { vi.advanceTimersByTime(RETENTION_DUE_REFRESH_MS * 3); });
    expect(api.fetchRetentionDue).toHaveBeenCalledTimes(3); // a background tab never polls
    expect(RETENTION_DUE_REFRESH_MS).toBeGreaterThanOrEqual(300_000); // the server's cache window
  });

  it("is nothing due outside the provider", () => {
    render(<Probe />);
    expect(screen.getByTestId("due").textContent).toBe("none");
  });

  it("deep-links Study to the first due course", () => {
    expect(retentionHref(["c 1", "c2"])).toBe("/study?retention-course=c+1");
    expect(retentionHref([])).toBe("/study");
  });
});

// @vitest-environment jsdom
/** Spec §11.3: Learn() renders LoopLearn for the loop status {active: true}.
 * The status probe is the only input: no settings field carries
 * learning_loop_beta (spec §7, §13 A31), so the UI cannot read the staff/QA
 * toggle at all. Anything else — {active: false}, the gate's 404 (resolved
 * inactive by getLoopStatus), any error — keeps the legacy tree. */
import React from "react";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams(),
  usePathname: () => "/learn",
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), back: vi.fn(), prefetch: vi.fn() }),
}));
// Settings as the API returns them: no learning_loop_beta key (spec §13 A31).
vi.mock("@/context/UserContext", () => ({
  useUser: () => ({ userId: "u1", userReady: true, settings: { theme: "light" } }),
}));
vi.mock("../ToastProvider", () => ({ useToast: () => ({ error: vi.fn(), success: vi.fn(), info: vi.fn() }) }));
vi.mock("../learn/LoopLearn", () => ({ LoopLearn: () => <div data-testid="loop-phase" data-phase="probe" /> }));
const getLoopStatus = vi.hoisted(() => vi.fn());
vi.mock("@/lib/api", async (orig) => ({
  ...(await orig<typeof import("@/lib/api")>()),
  getLoopStatus,
  // the legacy tree's bootstrap reads — inert here
  getSessions: vi.fn().mockResolvedValue({ sessions: [] }),
  getCourses: vi.fn().mockResolvedValue({ courses: [] }),
  getGraph: vi.fn().mockResolvedValue({ nodes: [], edges: [], stats: {} }),
}));

import { ApiError } from "@/lib/api";
import { Learn } from "../screens/Learn";

beforeEach(() => { getLoopStatus.mockReset(); });
afterEach(cleanup);

it("renders LoopLearn for {active: true} with the status probe as the only input", async () => {
  getLoopStatus.mockResolvedValue({ active: true });
  render(<Learn />);
  expect(await screen.findByTestId("loop-phase")).toBeTruthy();
  expect(screen.queryByTestId("tutor-start")).toBeNull();
  expect(getLoopStatus).toHaveBeenCalledWith("u1");
  expect(getLoopStatus).toHaveBeenCalledTimes(1);
});

it("keeps the legacy tree for {active: false} (the gate's 404 resolves to this)", async () => {
  getLoopStatus.mockResolvedValue({ active: false });
  render(<Learn />);
  await waitFor(() => expect(screen.getByTestId("tutor-start")).toBeTruthy());
  expect(screen.queryByTestId("loop-phase")).toBeNull();
});

it("keeps the legacy tree when the probe fails (fails closed, build phase)", async () => {
  getLoopStatus.mockRejectedValue(new ApiError("boom", 503));
  render(<Learn />);
  await waitFor(() => expect(screen.getByTestId("tutor-start")).toBeTruthy());
  expect(screen.queryByTestId("loop-phase")).toBeNull();
});

// @vitest-environment jsdom
/**
 * Component tests for the admin analytics screen (#121 — data layer + raw
 * tables; charts come with #122).
 *
 * What these pin:
 *   - the admin gate (non-admins get the Admin-screen refusal, zero fetches);
 *   - all four panels render live data from the /api/admin/analytics wrappers;
 *   - a failed panel load shows a banner + retry that refetches (the house
 *     "error && !data" pattern), without blanking the other panels;
 *   - the range presets drive every query (new `from` on refetch);
 *   - a truncated aggregation surfaces its badge (never silent partial data).
 */

import React from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";

const userState = vi.hoisted(() => ({ isAdmin: true, userReady: true, userId: "admin-1" }));
vi.mock("@/context/UserContext", () => ({
  useUser: () => userState,
}));

vi.mock("../TopBar", () => ({
  TopBar: ({ title }: { title: string }) => <div>{title}</div>,
}));

vi.mock("../Icon", () => ({
  Icon: ({ name }: { name: string }) => <span data-testid={`icon-${name}`} />,
}));

const api = vi.hoisted(() => ({
  adminUsageSummary: vi.fn(),
  adminUsageByUser: vi.fn(),
  adminLlmCost: vi.fn(),
  adminErrors: vi.fn(),
}));
vi.mock("@/lib/api", () => api);

import { AdminAnalytics } from "./AdminAnalytics";

const RANGE = { from: "2026-06-30T12:00:00.000Z", to: "2026-07-30T12:00:00.000Z" };

const summaryFixture = {
  range: RANGE,
  total_events: 42,
  distinct_active_users: 7,
  by_event_type: [{ event_type: "note.created", count: 20 }],
  truncated: false,
  series: null,
};
const byUserFixture = {
  range: RANGE,
  total_users: 1,
  limit: 50,
  offset: 0,
  users: [{ user_id: "u-alpha", event_count: 5, by_category: { usage: 5 }, llm_cost_usd: 1.23, total_tokens: 456 }],
  truncated: false,
};
const costFixture = {
  range: RANGE,
  group_by: "feature",
  rows: [{ key: "quiz", calls: 3, prompt_tokens: 10, completion_tokens: 5, total_tokens: 15, cost_usd: 0.5 }],
  totals: { calls: 3, prompt_tokens: 10, completion_tokens: 5, total_tokens: 15, cost_usd: 0.5 },
  truncated: true,
  series: null,
};
const errorsFixture = {
  range: RANGE,
  total: 1,
  limit: 50,
  offset: 0,
  errors: [{
    created_at: "2026-07-15T09:00:00+00:00", event_type: "error.5xx", request_id: "r1",
    user_id: "u-alpha", path: "/api/quiz", method: "POST", status_code: 500, duration_ms: 12.3,
  }],
  truncated: false,
  series: null,
};

function primeHappyPath() {
  api.adminUsageSummary.mockResolvedValue(summaryFixture);
  api.adminUsageByUser.mockResolvedValue(byUserFixture);
  api.adminLlmCost.mockResolvedValue(costFixture);
  api.adminErrors.mockResolvedValue(errorsFixture);
}

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
  userState.isAdmin = true;
});

describe("AdminAnalytics", () => {
  it("refuses non-admins without fetching anything", () => {
    userState.isAdmin = false;
    render(<AdminAnalytics />);
    expect(screen.getByText(/don't have admin access/i)).toBeTruthy();
    expect(api.adminUsageSummary).not.toHaveBeenCalled();
    expect(api.adminErrors).not.toHaveBeenCalled();
  });

  it("renders all four panels from the live wrappers", async () => {
    primeHappyPath();
    render(<AdminAnalytics />);
    await waitFor(() => {
      expect(screen.getByText("42")).toBeTruthy(); // total events
      expect(screen.getByText("note.created")).toBeTruthy();
      expect(screen.getByText("u-alpha")).toBeTruthy();
      expect(screen.getByText("quiz")).toBeTruthy();
      expect(screen.getByText("error.5xx")).toBeTruthy();
    });
  });

  it("shows a banner + retry for a failed panel and refetches on retry", async () => {
    primeHappyPath();
    api.adminUsageSummary.mockRejectedValueOnce(new Error("boom"));
    render(<AdminAnalytics />);
    const retry = await screen.findByTestId("admin-analytics-usage-retry");
    // The other panels keep their data — a single failed panel never blanks the page.
    expect(screen.getByText("u-alpha")).toBeTruthy();
    fireEvent.click(retry);
    await waitFor(() => expect(screen.getByText("42")).toBeTruthy());
    expect(api.adminUsageSummary).toHaveBeenCalledTimes(2);
  });

  it("range presets drive every query", async () => {
    primeHappyPath();
    render(<AdminAnalytics />);
    await screen.findByText("42");
    const before = api.adminUsageSummary.mock.calls.length;
    fireEvent.click(screen.getByTestId("admin-analytics-range-7d"));
    await waitFor(() => expect(api.adminUsageSummary.mock.calls.length).toBeGreaterThan(before));
    const lastSummary = api.adminUsageSummary.mock.calls.at(-1)![0];
    const lastErrors = api.adminErrors.mock.calls.at(-1)![0];
    expect(lastSummary.from).toBe(lastErrors.from); // one range drives all panels
    const spanMs = new Date(lastSummary.to).getTime() - new Date(lastSummary.from).getTime();
    expect(spanMs).toBe(7 * 86_400_000);
  });

  it("surfaces the truncation badge when an aggregation was capped", async () => {
    primeHappyPath();
    render(<AdminAnalytics />);
    await screen.findByText("quiz");
    expect(screen.getByText(/truncated/i)).toBeTruthy();
  });
});

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
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";

const userState = vi.hoisted(() => ({ isAdmin: true, userReady: true, userId: "admin-1" }));
vi.mock("@/context/UserContext", () => ({
  useUser: () => userState,
}));

vi.mock("../TopBar", () => ({
  TopBar: ({ title }: { title: string }) => <div>{title}</div>,
}));

// Hoisted toast spies — background-reload failures surface via toast.error
// (the #463 Calendar convention), never via the banner once data exists.
const toastSpies = vi.hoisted(() => ({
  success: vi.fn(),
  error: vi.fn(),
  warn: vi.fn(),
}));
vi.mock("../ToastProvider", () => ({
  useToast: () => toastSpies,
}));

vi.mock("../Icon", () => ({
  Icon: ({ name }: { name: string }) => <span data-testid={`icon-${name}`} />,
}));

const api = vi.hoisted(() => ({
  adminUsageSummary: vi.fn(),
  adminUsageByUser: vi.fn(),
  adminLlmCost: vi.fn(),
  adminErrors: vi.fn(),
  adminLearningLoopKpis: vi.fn(),
}));
vi.mock("@/lib/api", () => api);

// Charts are lazy-loaded via next/dynamic in the screen; the shared
// passthrough renders them synchronously (re-rendering once late
// resolutions land).
vi.mock("next/dynamic", async () =>
  (await import("@/test-utils/mockNextDynamic")).mockNextDynamicModule(),
);

import { AdminAnalytics, LearningLoopPanelBody } from "./AdminAnalytics";

const RANGE = { from: "2026-06-30T12:00:00.000Z", to: "2026-07-30T12:00:00.000Z" };

const summaryFixture = {
  range: RANGE,
  total_events: 42,
  distinct_active_users: 7,
  by_event_type: [{ event_type: "note.created", count: 20 }],
  truncated: false,
  series: [
    { date: "2026-07-10", count: 12 },
    { date: "2026-07-12", count: 30 },
    { date: "2026-07-15", count: 4 }, // rate denominator for the errors-panel day
  ],
};
const byUserFixture = {
  range: RANGE,
  total_users: 2,
  limit: 50,
  offset: 0,
  users: [
    { user_id: "u-alpha", event_count: 5, by_category: { usage: 5 }, llm_cost_usd: 1.23, total_tokens: 456 },
    { user_id: "u-beta", event_count: 9, by_category: { usage: 9 }, llm_cost_usd: 0.5, total_tokens: 100 },
  ],
  truncated: false,
};
const costFixture = {
  range: RANGE,
  group_by: "feature",
  rows: [{ key: "quiz", calls: 3, prompt_tokens: 10, completion_tokens: 5, total_tokens: 15, cost_usd: 0.5 }],
  totals: { calls: 3, prompt_tokens: 10, completion_tokens: 5, total_tokens: 15, cost_usd: 0.5 },
  truncated: true,
  series: [{ date: "2026-07-10", calls: 3, total_tokens: 15, cost_usd: 0.5 }],
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
  series: [{ date: "2026-07-15", count: 1 }],
};

const emptyCalibration = {
  n: 0, brier: null, mean_predicted: null, observed_rate: null, ece: null,
  bins: [0, 1, 2, 3, 4].map(i => ({ lo: i / 5, hi: (i + 1) / 5, n: 0, mean_predicted: null, observed: null })),
};
const emptyGain = {
  n: 0, pre_correct_rate: null, post_correct_rate: null, paired_difference: null,
  improved: 0, same: 0, worse: 0,
};
const learningGain = {
  delayed_min_days: 7,
  windows: [
    {
      window_days: 7, posttests: 6, excluded_retired: 0,
      n: 5, pre_correct_rate: 0.4, post_correct_rate: 0.8, paired_difference: 0.4,
      improved: 2, same: 3, worse: 0,
      delayed: { n: 2, pre_correct_rate: 0.5, post_correct_rate: 1, paired_difference: 0.5, improved: 1, same: 1, worse: 0 },
    },
    { window_days: 28, posttests: 0, excluded_retired: 0, ...emptyGain, delayed: emptyGain },
  ],
};
const loopFixture = {
  range: RANGE,
  steps_total: 40, banded_steps: 20, in_band: 15, in_band_share: 0.75,
  unassisted_next_session: { sessions: 10, successes: 6, rate: 0.6, quiz_ask_excluded: 1 },
  caught_leaks: 1, served_reveals: 0, unscanned_turns: 0,
  ceiling_compliance: { steps: 40, compliant: 39, rate: 0.975 },
  earnest_revise: { graded_steps: 0, earnest_blocked: 0, unmeasured_steps: 0, rate: null, gate: "inconclusive" as const },
  gates: { zero_leaks: true, ceiling_compliance_ok: true, earnest_revise_ok: null },
  calibration: {
    all: {
      n: 4, brier: 0.21, mean_predicted: 0.82, observed_rate: 0.5, ece: 0.32,
      bins: [
        ...emptyCalibration.bins.slice(0, 4),
        { lo: 0.8, hi: 1, n: 4, mean_predicted: 0.82, observed: 0.5 },
      ],
    },
    posttest: emptyCalibration,
  },
  learning_gain: learningGain,
  truncated: false,
};

function primeHappyPath() {
  api.adminUsageSummary.mockResolvedValue(summaryFixture);
  api.adminUsageByUser.mockResolvedValue(byUserFixture);
  api.adminLlmCost.mockResolvedValue(costFixture);
  api.adminErrors.mockResolvedValue(errorsFixture);
  api.adminLearningLoopKpis.mockResolvedValue(loopFixture);
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
      expect(screen.getByText("42")).toBeTruthy(); // total events stat
      // Chart labels + table fallbacks both carry these — multiple matches are expected.
      expect(screen.getAllByText("note.created").length).toBeGreaterThanOrEqual(1);
      expect(screen.getByText("u-alpha")).toBeTruthy();
      expect(screen.getAllByText("quiz").length).toBeGreaterThanOrEqual(1);
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
    await screen.findAllByText("quiz");
    expect(screen.getByText(/truncated/i)).toBeTruthy();
  });

  it("toasts a failed background reload and keeps the loaded view (no banner)", async () => {
    primeHappyPath();
    render(<AdminAnalytics />);
    await screen.findByText("42");
    api.adminUsageSummary.mockRejectedValueOnce(new Error("reload boom"));
    fireEvent.click(screen.getByTestId("admin-analytics-range-7d"));
    await waitFor(() => expect(toastSpies.error).toHaveBeenCalled());
    // Stale-but-loaded data stays visible; the initial-load banner never appears.
    expect(screen.getByText("42")).toBeTruthy();
    expect(screen.queryByTestId("admin-analytics-usage-retry")).toBeNull();
  });

  it("ignores a stale response that resolves after a newer request", async () => {
    primeHappyPath();
    let resolveStale!: (v: typeof summaryFixture) => void;
    // First (30d) summary request hangs; the later (7d) one resolves first.
    api.adminUsageSummary
      .mockReturnValueOnce(new Promise((r) => { resolveStale = r; }))
      .mockResolvedValueOnce({ ...summaryFixture, total_events: 99 });
    render(<AdminAnalytics />);
    await screen.findByText("u-alpha"); // other panels loaded
    fireEvent.click(screen.getByTestId("admin-analytics-range-7d"));
    await screen.findByText("99");
    resolveStale(summaryFixture); // the out-of-order 30d response lands late
    await waitFor(() => expect(screen.queryByText("42")).toBeNull());
    expect(screen.getByText("99")).toBeTruthy();
  });

  it("clamps an inverted custom range instead of sending from > to", async () => {
    primeHappyPath();
    render(<AdminAnalytics />);
    await screen.findByText("42");
    // Move `from` past the current `to` — the `to` edge must be dragged along.
    fireEvent.change(screen.getByTestId("admin-analytics-range-from"), {
      target: { value: "2099-09-01" },
    });
    await waitFor(() => {
      const last = api.adminUsageSummary.mock.calls.at(-1)![0];
      expect(last.from).toBe("2099-09-01T00:00:00.000Z");
      expect(last.to >= last.from).toBe(true);
    });
  });

  it("requests day bucketing for the trend panels (#122)", async () => {
    primeHappyPath();
    render(<AdminAnalytics />);
    await screen.findByText("42");
    expect(api.adminUsageSummary.mock.calls.at(-1)![0].bucket).toBe("day");
    expect(api.adminLlmCost.mock.calls.at(-1)![0].bucket).toBe("day");
    expect(api.adminErrors.mock.calls.at(-1)![0].bucket).toBe("day");
    expect(api.adminUsageByUser.mock.calls.at(-1)![0].bucket).toBeUndefined();
  });

  it("renders the trend charts and the event-type bars from the series (#122)", async () => {
    primeHappyPath();
    render(<AdminAnalytics />);
    await screen.findByText("42");
    expect(await screen.findByRole("img", { name: "Events per day" })).toBeTruthy();
    expect(screen.getByRole("img", { name: "Cost per day" })).toBeTruthy();
    expect(screen.getByRole("img", { name: "Tokens per day" })).toBeTruthy();
    expect(screen.getByRole("img", { name: "Errors per day" })).toBeTruthy();
    // Labeled as a RATE — errors ÷ events joined across panels.
    expect(screen.getByRole("img", { name: "Error rate per day" })).toBeTruthy();
    expect(screen.getByRole("img", { name: "Top event types" })).toBeTruthy();
  });

  it("keeps table fallbacks behind every chart, day series included (#122 a11y)", async () => {
    primeHappyPath();
    render(<AdminAnalytics />);
    await screen.findByText("42");
    // The #121 category tables survive, and each day-series chart cluster now
    // has a "View data" table twin (the hover tooltip has no keyboard path).
    // Summaries carry per-chart labels so screen-reader users can tell the
    // five disclosures apart.
    expect(screen.getAllByText(/^View data: /).length).toBeGreaterThanOrEqual(5);
    for (const label of [
      "View data: events per day",
      "View data: event types",
      "View data: cost per day",
      "View data: cost breakdown",
      "View data: errors per day",
    ]) {
      expect(screen.getByText(label)).toBeTruthy();
    }
    const panel = (name: string) =>
      within(screen.getByRole("heading", { name }).closest("section") as HTMLElement);
    // Usage day table: the plotted 2026-07-10 value plus an explicit
    // zero-filled gap day (2026-07-11 is absent from the sparse series).
    const usageRow = panel("Usage").getByText("2026-07-10").closest("tr")!;
    expect(within(usageRow).getByText("12")).toBeTruthy();
    const gapRow = panel("Usage").getByText("2026-07-11").closest("tr")!;
    expect(within(gapRow).getByText("0")).toBeTruthy();
    // Cost day table mirrors CostDayPoint: calls, tokens, and formatted cost.
    const costRow = panel("LLM cost").getByText("2026-07-10").closest("tr")!;
    expect(within(costRow).getByText("3")).toBeTruthy();
    expect(within(costRow).getByText("15")).toBeTruthy();
    expect(within(costRow).getByText("$0.50")).toBeTruthy();
    // Errors day table: the absolute count and the cross-panel rate
    // (1 error ÷ 4 events on 2026-07-15).
    const errRow = panel("Errors").getByText("2026-07-15").closest("tr")!;
    expect(within(errRow).getByText("1")).toBeTruthy();
    expect(within(errRow).getByText("25%")).toBeTruthy();
  });

  it("withholds the error rate when the summary payload belongs to a different range", async () => {
    // The hooks keep their last payload during a range-change reload, so the
    // errors panel can briefly see a summary from the OLD range. The rate
    // must show its waiting state, not an all-0% line fabricated from
    // zero-filled stale days (#491 review).
    primeHappyPath();
    api.adminUsageSummary.mockResolvedValue({
      ...summaryFixture,
      range: { from: "2026-05-01T00:00:00.000Z", to: "2026-05-31T00:00:00.000Z" },
    });
    render(<AdminAnalytics />);
    await screen.findByText("error.5xx");
    expect(screen.getByText(/appears once the usage events-per-day series loads/i)).toBeTruthy();
    expect(screen.queryByRole("img", { name: "Error rate per day" })).toBeNull();
    // The errors day table shows the absolute count but no fabricated 0% rate.
    const errPanel = within(
      screen.getByRole("heading", { name: "Errors" }).closest("section") as HTMLElement,
    );
    for (const cell of errPanel.getAllByText("2026-07-15")) {
      const row = cell.closest("tr");
      if (row) expect(within(row).queryByText("0%")).toBeNull();
    }
  });

  it("sorts the users table by a clicked column (#122)", async () => {
    primeHappyPath();
    render(<AdminAnalytics />);
    await screen.findByText("u-alpha");
    const order = () => {
      const cells = screen.getAllByText(/^u-(alpha|beta)$/).map((el) => el.textContent);
      return cells;
    };
    expect(order()).toEqual(["u-alpha", "u-beta"]); // server order (cost desc)
    fireEvent.click(screen.getByTestId("admin-analytics-users-sort-events"));
    await waitFor(() => expect(order()).toEqual(["u-beta", "u-alpha"])); // events desc
  });
});


describe("Learning loop panel (spec §10, §13 A110)", () => {
  it("loads over the same range and shows the gates as pass / inconclusive", async () => {
    primeHappyPath();
    render(<AdminAnalytics />);
    const panel = await screen.findByTestId("admin-loop-gate-leaks");
    expect(panel.getAttribute("data-state")).toBe("pass");
    expect(screen.getByTestId("admin-loop-gate-ceiling").getAttribute("data-state")).toBe("pass");
    // No graded step carries the signal: inconclusive, never a silent pass.
    expect(screen.getByTestId("admin-loop-gate-earnest").getAttribute("data-state")).toBe("inconclusive");
    expect(api.adminLearningLoopKpis).toHaveBeenCalledWith(
      expect.objectContaining({ from: expect.any(String), to: expect.any(String) }),
    );
  });

  it("shows calibration bins, and an empty report as no observations rather than zeros", () => {
    render(<LearningLoopPanelBody d={loopFixture} />);
    const all = screen.getByTestId("admin-loop-calibration-all");
    expect(within(all).getByText("0.8–1.0")).toBeTruthy();
    expect(within(all).getAllByText("50%").length).toBeGreaterThan(0); // observed in the top bin
    const post = screen.getByTestId("admin-loop-calibration-posttest");
    expect(within(post).getByText("No independent observations in this range.")).toBeTruthy();
  });

  it("marks a failing gate", () => {
    render(<LearningLoopPanelBody d={{ ...loopFixture, gates: { ...loopFixture.gates, zero_leaks: false } }} />);
    expect(screen.getByTestId("admin-loop-gate-leaks").getAttribute("data-state")).toBe("fail");
  });

  it("shows the pre/post gain per fixed window, with the delayed stratum under each (spec §13 A112)", () => {
    render(<LearningLoopPanelBody d={loopFixture} />);
    const week = screen.getByTestId("admin-loop-gain-7");
    expect(within(week).getByText("7 days")).toBeTruthy();
    expect(within(week).getByText("6")).toBeTruthy(); // post-tests, paired or not
    expect(within(week).getByText("5")).toBeTruthy(); // pairs
    expect(within(week).getByText("40%")).toBeTruthy(); // pre-test correct
    expect(within(week).getByText("80%")).toBeTruthy(); // post-test correct
    expect(within(week).getByText("+40.0 pp")).toBeTruthy(); // paired change
    expect(within(week).getByText("2 / 3 / 0")).toBeTruthy();
    const delayed = screen.getByTestId("admin-loop-gain-7-delayed");
    expect(within(delayed).getByText("↳ no practice in the 7 days before")).toBeTruthy();
    expect(within(delayed).getByText("+50.0 pp")).toBeTruthy();
    expect(within(delayed).getByText("100%")).toBeTruthy();
  });

  it("shows an empty window as dashes rather than zero rates", () => {
    render(<LearningLoopPanelBody d={loopFixture} />);
    const month = screen.getByTestId("admin-loop-gain-28");
    expect(within(month).getAllByText("—").length).toBe(3); // pre, post, paired change
    expect(within(month).queryByText("0%")).toBeNull();
    expect(within(month).getByText("0 / 0 / 0")).toBeTruthy();
  });

  it("says so when no unaided post-test was answered in the range", () => {
    const none = {
      ...loopFixture,
      learning_gain: {
        delayed_min_days: 7,
        windows: [7, 28].map(window_days => ({
          window_days, posttests: 0, excluded_retired: 0, ...emptyGain, delayed: emptyGain,
        })),
      },
    };
    render(<LearningLoopPanelBody d={none} />);
    expect(screen.getByTestId("admin-loop-gain").textContent).toContain("No unaided post-test outcomes in this range.");
    expect(screen.queryByTestId("admin-loop-gain-7")).toBeNull();
  });

  it("shows per window how many outcomes a retired item left out (spec §13 A112 × A113)", () => {
    const withRetired = {
      ...loopFixture,
      learning_gain: {
        ...learningGain,
        windows: [{ ...learningGain.windows[0], excluded_retired: 2 }, learningGain.windows[1]],
      },
    };
    render(<LearningLoopPanelBody d={withRetired} />);
    expect(screen.getByText("Excluded: item retired")).toBeTruthy();
    expect(screen.getByTestId("admin-loop-gain-7-excluded").textContent).toBe("2");
    expect(screen.getByTestId("admin-loop-gain-28-excluded").textContent).toBe("0");
    // the delayed stratum is a subset of the window's pairs: no count of its own
    expect(screen.queryByTestId("admin-loop-gain-7-delayed-excluded")).toBeNull();
    expect(within(screen.getByTestId("admin-loop-gain-7-delayed")).getAllByText("—").length).toBe(2);
  });

  it("keeps the table when every outcome in range was left out for a retired item", () => {
    const allRetired = {
      ...loopFixture,
      learning_gain: {
        delayed_min_days: 7,
        windows: [
          { window_days: 7, posttests: 0, excluded_retired: 3, ...emptyGain, delayed: emptyGain },
          { window_days: 28, posttests: 0, excluded_retired: 0, ...emptyGain, delayed: emptyGain },
        ],
      },
    };
    render(<LearningLoopPanelBody d={allRetired} />);
    expect(screen.getByTestId("admin-loop-gain").textContent).not.toContain("No unaided post-test outcomes");
    expect(screen.getByTestId("admin-loop-gain-7-excluded").textContent).toBe("3");
  });
});

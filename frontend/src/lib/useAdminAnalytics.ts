"use client";

/**
 * Data hooks for the admin analytics dashboard (#121), over the
 * /api/admin/analytics rollup API (#120).
 *
 * House data-fetching pattern (no SWR/React Query in this repo): a stable
 * useCallback fetcher + a useEffect that re-runs when it changes, exposing
 * { data, loading, error, reload }. Errors are humanized once here so every
 * panel renders the same message shape. The default range clock is the REAL
 * clock (see presetRange's docstring for why it skips testMode's now()).
 */

import React from "react";
import {
  adminErrors,
  adminLlmCost,
  adminUsageByUser,
  adminUsageSummary,
} from "./api";
import { humanizeError } from "./errorMessage";
import type {
  AnalyticsBucket,
  ErrorsPageData,
  LlmCostData,
  LlmCostGroupBy,
  UsageByUserData,
  UsageSummaryData,
} from "./types";

export interface AnalyticsRangeValue {
  from: string;
  to: string;
}

/** Last-`days` window ending at `nowMs`, as the ISO strings the analytics
 * endpoints take. Defaults to the REAL clock even under
 * NEXT_PUBLIC_TEST_MODE — a #426-family skip-list entry: these are QUERY
 * BOUNDS over rows the backend stamps with its real clock, and the frozen
 * testMode instant pointed the e2e dashboard at an empty March window
 * (admin-analytics.spec.ts). Deterministic tests pass nowMs explicitly. */
export function presetRange(days: number, nowMs: number = Date.now()): AnalyticsRangeValue {
  return {
    from: new Date(nowMs - days * 86_400_000).toISOString(),
    to: new Date(nowMs).toISOString(),
  };
}

export interface AnalyticsQuery<T> {
  data: T | null;
  loading: boolean;
  error: string | null;
  reload: () => void;
}

function useAnalyticsQuery<T>(
  fetcher: () => Promise<T>,
  onBackgroundError?: (message: string) => void,
): AnalyticsQuery<T> {
  const [data, setData] = React.useState<T | null>(null);
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState<string | null>(null);
  // Monotonic sequence: only the newest in-flight request may commit state,
  // so an out-of-order response (7d resolving after 30d) can't overwrite
  // newer data (PR #478 review).
  const seqRef = React.useRef(0);
  const hasDataRef = React.useRef(false);
  // Read through a ref so an unstable callback can't retrigger the effect.
  const bgErrorRef = React.useRef(onBackgroundError);
  bgErrorRef.current = onBackgroundError;

  const load = React.useCallback(async () => {
    const seq = ++seqRef.current;
    setLoading(true);
    try {
      const result = await fetcher();
      if (seq !== seqRef.current) return;
      hasDataRef.current = true;
      setData(result);
      setError(null);
    } catch (err) {
      if (seq !== seqRef.current) return;
      const message = humanizeError(err, "Couldn't load analytics.");
      setError(message);
      // #463 convention: initial failure renders the banner (no data yet);
      // a failed BACKGROUND reload keeps the loaded view and toasts instead.
      if (hasDataRef.current) bgErrorRef.current?.(message);
    } finally {
      if (seq === seqRef.current) setLoading(false);
    }
  }, [fetcher]);

  React.useEffect(() => {
    load();
  }, [load]);

  return { data, loading, error, reload: load };
}

export interface AnalyticsHookOptions {
  bucket?: AnalyticsBucket;
  limit?: number;
  offset?: number;
  groupBy?: LlmCostGroupBy;
  /** Called instead of the banner when a reload fails AFTER data has loaded. */
  onBackgroundError?: (message: string) => void;
}

export function useUsageSummary(
  range: AnalyticsRangeValue,
  opts?: AnalyticsHookOptions,
): AnalyticsQuery<UsageSummaryData> {
  const { from, to } = range;
  const { bucket, onBackgroundError } = opts ?? {};
  const fetcher = React.useCallback(
    () => adminUsageSummary({ from, to, bucket }),
    [from, to, bucket],
  );
  return useAnalyticsQuery(fetcher, onBackgroundError);
}

export function useUsageByUser(
  range: AnalyticsRangeValue,
  opts?: AnalyticsHookOptions,
): AnalyticsQuery<UsageByUserData> {
  const { from, to } = range;
  const { limit, offset, onBackgroundError } = opts ?? {};
  const fetcher = React.useCallback(
    () => adminUsageByUser({ from, to, limit, offset }),
    [from, to, limit, offset],
  );
  return useAnalyticsQuery(fetcher, onBackgroundError);
}

export function useLlmCost(
  range: AnalyticsRangeValue,
  opts?: AnalyticsHookOptions,
): AnalyticsQuery<LlmCostData> {
  const { from, to } = range;
  const { groupBy, bucket, onBackgroundError } = opts ?? {};
  const fetcher = React.useCallback(
    () => adminLlmCost({ from, to, group_by: groupBy, bucket }),
    [from, to, groupBy, bucket],
  );
  return useAnalyticsQuery(fetcher, onBackgroundError);
}

export function useErrorsFeed(
  range: AnalyticsRangeValue,
  opts?: AnalyticsHookOptions,
): AnalyticsQuery<ErrorsPageData> {
  const { from, to } = range;
  const { limit, offset, bucket, onBackgroundError } = opts ?? {};
  const fetcher = React.useCallback(
    () => adminErrors({ from, to, limit, offset, bucket }),
    [from, to, limit, offset, bucket],
  );
  return useAnalyticsQuery(fetcher, onBackgroundError);
}

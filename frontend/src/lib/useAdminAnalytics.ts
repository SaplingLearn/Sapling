"use client";

/**
 * Data hooks for the admin analytics dashboard (#121), over the
 * /api/admin/analytics rollup API (#120).
 *
 * House data-fetching pattern (no SWR/React Query in this repo): a stable
 * useCallback fetcher + a useEffect that re-runs when it changes, exposing
 * { data, loading, error, reload }. Errors are humanized once here so every
 * panel renders the same message shape. The default range clock routes
 * through lib/testMode's now() so the E2E stack sees a frozen window.
 */

import React from "react";
import {
  adminErrors,
  adminLlmCost,
  adminUsageByUser,
  adminUsageSummary,
} from "./api";
import { humanizeError } from "./errorMessage";
import { now } from "./testMode";
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

/** Last-`days` window ending at `nowMs` (defaults to the testMode-aware
 * clock), as the ISO strings the analytics endpoints take. */
export function presetRange(days: number, nowMs: number = now()): AnalyticsRangeValue {
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

function useAnalyticsQuery<T>(fetcher: () => Promise<T>): AnalyticsQuery<T> {
  const [data, setData] = React.useState<T | null>(null);
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState<string | null>(null);

  const load = React.useCallback(async () => {
    setLoading(true);
    try {
      setData(await fetcher());
      setError(null);
    } catch (err) {
      setError(humanizeError(err, "Couldn't load analytics."));
    } finally {
      setLoading(false);
    }
  }, [fetcher]);

  React.useEffect(() => {
    load();
  }, [load]);

  return { data, loading, error, reload: load };
}

export function useUsageSummary(
  range: AnalyticsRangeValue,
  bucket?: AnalyticsBucket,
): AnalyticsQuery<UsageSummaryData> {
  const { from, to } = range;
  const fetcher = React.useCallback(
    () => adminUsageSummary({ from, to, bucket }),
    [from, to, bucket],
  );
  return useAnalyticsQuery(fetcher);
}

export function useUsageByUser(
  range: AnalyticsRangeValue,
  limit?: number,
  offset?: number,
): AnalyticsQuery<UsageByUserData> {
  const { from, to } = range;
  const fetcher = React.useCallback(
    () => adminUsageByUser({ from, to, limit, offset }),
    [from, to, limit, offset],
  );
  return useAnalyticsQuery(fetcher);
}

export function useLlmCost(
  range: AnalyticsRangeValue,
  groupBy?: LlmCostGroupBy,
  bucket?: AnalyticsBucket,
): AnalyticsQuery<LlmCostData> {
  const { from, to } = range;
  const fetcher = React.useCallback(
    () => adminLlmCost({ from, to, group_by: groupBy, bucket }),
    [from, to, groupBy, bucket],
  );
  return useAnalyticsQuery(fetcher);
}

export function useErrorsFeed(
  range: AnalyticsRangeValue,
  limit?: number,
  offset?: number,
  bucket?: AnalyticsBucket,
): AnalyticsQuery<ErrorsPageData> {
  const { from, to } = range;
  const fetcher = React.useCallback(
    () => adminErrors({ from, to, limit, offset, bucket }),
    [from, to, limit, offset, bucket],
  );
  return useAnalyticsQuery(fetcher);
}

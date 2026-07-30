"use client";

/**
 * Admin analytics screen (#121): typed data layer + raw tables over
 * /api/admin/analytics (usage summary, per-user rollup, LLM cost, errors).
 * One date range drives every panel; each panel owns its loading/error/empty
 * state so a single failed query never blanks the page. Charts and visual
 * polish are #122 — this screen deliberately renders plain numbers/tables.
 */

import React from "react";
import { TopBar } from "../TopBar";
import { useToast } from "../ToastProvider";
import { useUser } from "@/context/UserContext";
import {
  presetRange,
  useErrorsFeed,
  useLlmCost,
  useUsageByUser,
  useUsageSummary,
  type AnalyticsQuery,
  type AnalyticsRangeValue,
} from "@/lib/useAdminAnalytics";
import type { LlmCostGroupBy } from "@/lib/types";

const PRESETS = [
  { days: 7, label: "7d" },
  { days: 30, label: "30d" },
  { days: 90, label: "90d" },
] as const;

const GROUPS: LlmCostGroupBy[] = ["feature", "user", "model"];

const th: React.CSSProperties = {
  textAlign: "left", fontSize: 11, textTransform: "uppercase", letterSpacing: "0.08em",
  color: "var(--text-muted)", padding: "4px 8px",
};
const td: React.CSSProperties = {
  fontSize: 13, padding: "6px 8px", borderTop: "1px solid var(--border)",
};
const tdNum: React.CSSProperties = { ...td, textAlign: "right", fontVariantNumeric: "tabular-nums" };

function TruncatedBadge() {
  // Copy stays meaning-neutral: on the aggregation panels `truncated` means
  // the visible aggregates are partial; on the errors panel it refers to the
  // (bucket=day) series scan only — the feed and total stay exact.
  return (
    <span className="chip chip--err" title="The range was too large for a full scan — some of this panel's data is partial.">
      Truncated — partial data
    </span>
  );
}

function Stat({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div>
      <div className="label-micro">{label}</div>
      <div style={{ fontSize: 24, fontWeight: 600 }}>{value}</div>
    </div>
  );
}

function Panel<T>({ title, query, testid, children }: {
  title: string;
  query: AnalyticsQuery<T>;
  testid: string;
  children: (data: T) => React.ReactNode;
}) {
  return (
    <section className="card" style={{ padding: "var(--pad-lg)" }}>
      <h2 className="h-serif" style={{ fontSize: 18, marginBottom: 12 }}>{title}</h2>
      {query.error && !query.data ? (
        <div role="alert" style={{ display: "flex", alignItems: "center", gap: 12, color: "var(--text-muted)", fontSize: 13 }}>
          <span>{query.error}</span>
          <button data-testid={`${testid}-retry`} className="btn btn--sm" onClick={query.reload}>
            Try again
          </button>
        </div>
      ) : !query.data ? (
        <div style={{ color: "var(--text-muted)", fontSize: 13 }}>Loading…</div>
      ) : (
        children(query.data)
      )}
    </section>
  );
}

export function AdminAnalytics() {
  // The gate lives OUTSIDE the hook-owning body: hooks fire their fetches on
  // mount, and a non-admin visit must not fire four requests that 403 (each
  // minting an auth.permission_denied audit event on the backend).
  const { isAdmin } = useUser();
  if (!isAdmin) {
    return (
      <div>
        <TopBar breadcrumb="Admin" title="Analytics" subtitle="Staff only" />
        <div style={{ padding: 60, textAlign: "center", color: "var(--text-muted)" }}>
          You don&apos;t have admin access.
        </div>
      </div>
    );
  }
  return <AnalyticsBody />;
}

function AnalyticsBody() {
  const [range, setRange] = React.useState<AnalyticsRangeValue>(() => presetRange(30));
  const [groupBy, setGroupBy] = React.useState<LlmCostGroupBy>("feature");
  const toast = useToast();
  // Failed BACKGROUND reloads keep the loaded view and toast (#463 convention).
  const onBackgroundError = React.useCallback(
    (message: string) => toast.error(message),
    [toast],
  );

  const summary = useUsageSummary(range, { onBackgroundError });
  const byUser = useUsageByUser(range, { onBackgroundError });
  const cost = useLlmCost(range, { groupBy, onBackgroundError });
  const errs = useErrorsFeed(range, { onBackgroundError });

  const setCustom = (edge: "from" | "to", day: string) => {
    if (!day) return;
    setRange((r) => {
      const next = {
        ...r,
        [edge]: edge === "from" ? `${day}T00:00:00.000Z` : `${day}T23:59:59.999Z`,
      };
      // Keep the window valid (the backend 422s from > to): moving one edge
      // past the other drags the other edge to the same day.
      if (next.from > next.to) {
        if (edge === "from") next.to = `${day}T23:59:59.999Z`;
        else next.from = `${day}T00:00:00.000Z`;
      }
      return next;
    });
  };

  return (
    <div>
      <TopBar
        breadcrumb="Admin"
        title="Analytics"
        subtitle="Usage, LLM cost, and errors"
        actions={<span className="chip chip--err">Staff only</span>}
      />
      <div style={{
        padding: "12px 32px", borderBottom: "1px solid var(--border)",
        display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap",
      }}>
        <span className="label-micro">Range</span>
        {PRESETS.map((p) => (
          <button
            key={p.days}
            data-testid={`admin-analytics-range-${p.label}`}
            className="btn btn--sm"
            onClick={() => setRange(presetRange(p.days))}
          >
            {p.label}
          </button>
        ))}
        <input
          data-testid="admin-analytics-range-from"
          type="date"
          aria-label="Range start"
          value={range.from.slice(0, 10)}
          max={range.to.slice(0, 10)}
          onChange={(e) => setCustom("from", e.target.value)}
          style={{ fontSize: 13 }}
        />
        <span style={{ color: "var(--text-muted)", fontSize: 13 }}>→</span>
        <input
          data-testid="admin-analytics-range-to"
          type="date"
          aria-label="Range end"
          value={range.to.slice(0, 10)}
          min={range.from.slice(0, 10)}
          onChange={(e) => setCustom("to", e.target.value)}
          style={{ fontSize: 13 }}
        />
      </div>

      <div style={{ padding: "24px 32px", display: "grid", gap: 16 }}>
        <Panel title="Usage" query={summary} testid="admin-analytics-usage">
          {(d) => (
            <>
              {d.truncated && <TruncatedBadge />}
              <div style={{ display: "flex", gap: 32, margin: "8px 0 16px" }}>
                <Stat label="Total events" value={d.total_events} />
                <Stat label="Active users" value={d.distinct_active_users} />
              </div>
              {d.by_event_type.length === 0 ? (
                <div style={{ color: "var(--text-muted)", fontSize: 13 }}>No events in this range.</div>
              ) : (
                <table style={{ borderCollapse: "collapse", minWidth: 360 }}>
                  <thead>
                    <tr><th style={th}>Event type</th><th style={{ ...th, textAlign: "right" }}>Count</th></tr>
                  </thead>
                  <tbody>
                    {d.by_event_type.map((row) => (
                      <tr key={row.event_type}>
                        <td style={td}>{row.event_type}</td>
                        <td style={tdNum}>{row.count}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </>
          )}
        </Panel>

        <Panel title="Top users" query={byUser} testid="admin-analytics-users">
          {(d) => (
            <>
              {d.truncated && <TruncatedBadge />}
              {d.users.length === 0 ? (
                <div style={{ color: "var(--text-muted)", fontSize: 13 }}>No user activity in this range.</div>
              ) : (
                <table style={{ borderCollapse: "collapse", minWidth: 520 }}>
                  <thead>
                    <tr>
                      <th style={th}>User</th>
                      <th style={{ ...th, textAlign: "right" }}>Events</th>
                      <th style={{ ...th, textAlign: "right" }}>LLM cost</th>
                      <th style={{ ...th, textAlign: "right" }}>Tokens</th>
                    </tr>
                  </thead>
                  <tbody>
                    {d.users.map((u) => (
                      <tr key={u.user_id}>
                        <td style={{ ...td, fontFamily: "var(--font-mono, monospace)", fontSize: 12 }}>{u.user_id}</td>
                        <td style={tdNum}>{u.event_count}</td>
                        <td style={tdNum}>${u.llm_cost_usd.toFixed(4)}</td>
                        <td style={tdNum}>{u.total_tokens}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </>
          )}
        </Panel>

        <Panel title="LLM cost" query={cost} testid="admin-analytics-cost">
          {(d) => (
            <>
              <div style={{ display: "flex", gap: 6, alignItems: "center", marginBottom: 12 }}>
                <span className="label-micro">Group by</span>
                {GROUPS.map((g) => (
                  <button
                    key={g}
                    data-testid={`admin-analytics-cost-group-${g}`}
                    className="btn btn--sm"
                    style={g === groupBy ? { fontWeight: 600, borderColor: "var(--accent)" } : undefined}
                    onClick={() => setGroupBy(g)}
                  >
                    {g}
                  </button>
                ))}
                {d.truncated && <TruncatedBadge />}
              </div>
              {d.rows.length === 0 ? (
                <div style={{ color: "var(--text-muted)", fontSize: 13 }}>No LLM calls in this range.</div>
              ) : (
                <table style={{ borderCollapse: "collapse", minWidth: 560 }}>
                  <thead>
                    <tr>
                      <th style={th}>{d.group_by}</th>
                      <th style={{ ...th, textAlign: "right" }}>Calls</th>
                      <th style={{ ...th, textAlign: "right" }}>Prompt</th>
                      <th style={{ ...th, textAlign: "right" }}>Completion</th>
                      <th style={{ ...th, textAlign: "right" }}>Tokens</th>
                      <th style={{ ...th, textAlign: "right" }}>Cost</th>
                    </tr>
                  </thead>
                  <tbody>
                    {d.rows.map((row) => (
                      <tr key={row.key}>
                        <td style={td}>{row.key || "(none)"}</td>
                        <td style={tdNum}>{row.calls}</td>
                        <td style={tdNum}>{row.prompt_tokens}</td>
                        <td style={tdNum}>{row.completion_tokens}</td>
                        <td style={tdNum}>{row.total_tokens}</td>
                        <td style={tdNum}>${row.cost_usd.toFixed(4)}</td>
                      </tr>
                    ))}
                    <tr>
                      <td style={{ ...td, fontWeight: 600 }}>Total</td>
                      <td style={{ ...tdNum, fontWeight: 600 }}>{d.totals.calls}</td>
                      <td style={{ ...tdNum, fontWeight: 600 }}>{d.totals.prompt_tokens}</td>
                      <td style={{ ...tdNum, fontWeight: 600 }}>{d.totals.completion_tokens}</td>
                      <td style={{ ...tdNum, fontWeight: 600 }}>{d.totals.total_tokens}</td>
                      <td style={{ ...tdNum, fontWeight: 600 }}>${d.totals.cost_usd.toFixed(4)}</td>
                    </tr>
                  </tbody>
                </table>
              )}
            </>
          )}
        </Panel>

        <Panel title="Errors" query={errs} testid="admin-analytics-errors">
          {(d) => (
            <>
              {d.truncated && <TruncatedBadge />}
              {d.errors.length === 0 ? (
                <div style={{ color: "var(--text-muted)", fontSize: 13 }}>No errors in this range. 🎉</div>
              ) : (
                <table style={{ borderCollapse: "collapse", minWidth: 640 }}>
                  <thead>
                    <tr>
                      <th style={th}>Time</th>
                      <th style={th}>Type</th>
                      <th style={th}>Method</th>
                      <th style={th}>Path</th>
                      <th style={{ ...th, textAlign: "right" }}>Status</th>
                      <th style={{ ...th, textAlign: "right" }}>Duration</th>
                    </tr>
                  </thead>
                  <tbody>
                    {d.errors.map((e, i) => (
                      <tr key={e.request_id ?? `${e.created_at}-${i}`}>
                        <td style={{ ...td, whiteSpace: "nowrap" }}>{e.created_at ?? "—"}</td>
                        <td style={td}>{e.event_type}</td>
                        <td style={td}>{e.method ?? "—"}</td>
                        <td style={{ ...td, fontFamily: "var(--font-mono, monospace)", fontSize: 12 }}>{e.path ?? "—"}</td>
                        <td style={tdNum}>{e.status_code ?? "—"}</td>
                        <td style={tdNum}>{e.duration_ms != null ? `${e.duration_ms.toFixed(1)}ms` : "—"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </>
          )}
        </Panel>
      </div>
    </div>
  );
}

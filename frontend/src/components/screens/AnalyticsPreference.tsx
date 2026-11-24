"use client";
import React from "react";
import Link from "next/link";
import {
  getAnalyticsState,
  getServerAnalyticsState,
  subscribeAnalytics,
  type AnalyticsState,
} from "@/lib/analytics";
import { Toggle } from "./SettingsToggle";

/** The status line under the analytics switch, per state — what is actually true. */
const ANALYTICS_NOTES: Record<AnalyticsState, string> = {
  unknown: "Loading your saved setting…",
  unreadable: "We couldn't load your saved setting, so we can't show it yet.",
  unset:
    "No choice is saved to your account yet, so this browser sends no page views. Switch it on to share usage data.",
  on: "On — saved to your account, so it applies wherever you sign in. Nothing about it is stored in your browser.",
  on_browser_blocked:
    "On — saved to your account. Your browser's Do Not Track or Global Privacy Control signal is on, so this browser sends no page views and we share no actions from its requests, but some background processing on your documents can still be shared; switch this off to opt out of everything, wherever you sign in.",
  on_not_running:
    "On — saved to your account. Page views couldn't start in this browser (a blocker may have stopped them).",
  off: "Off — saved to your account, so none of this is shared, wherever you sign in.",
  off_unsaved:
    "Off in this browser for this visit only — we couldn't save it to your account, so our servers may still share usage data, and it will be back on next visit.",
};

/**
 * Product-analytics opt-out (PostHog). It follows the signed-in student's
 * ACCOUNT (`analytics_opt_out`), which governs both this browser's pageviews
 * and the backend's own PostHog mirror (#677) — so the switch is usable as
 * soon as the account has answered, whether or not this build sends
 * pageviews, the admin `product_analytics` flag is on, or DNT/GPC is set
 * (src/lib/analytics.ts). It is disabled only until that answer arrives (with
 * a "Try again" after a failed read) and while a save is in flight. After a
 * failed opt-out save it shows "off in this browser for this visit only"
 * with a retry, never "saved".
 */
export function AnalyticsPreference({
  onChange,
  onRetry,
  onReload,
  saving,
}: {
  onChange: (enabled: boolean) => void;
  onRetry: () => void;
  onReload: () => void;
  saving: boolean;
}) {
  const state = React.useSyncExternalStore(
    subscribeAnalytics,
    getAnalyticsState,
    getServerAnalyticsState,
  );
  const on = state === "on" || state === "on_browser_blocked" || state === "on_not_running";
  const loaded = state !== "unknown" && state !== "unreadable";

  return (
    <div className="card" data-testid="settings-analytics" style={{ padding: "var(--pad-lg)", marginTop: 16 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 20 }}>
        <div>
          <div style={{ fontWeight: 600, marginBottom: 4 }} id="settings-analytics-label">
            Product analytics
          </div>
          <div style={{ fontSize: 12, color: "var(--text-dim)" }}>
            Share how you use Sapling with PostHog, our analytics provider, so we can see what to
            improve: the app pages you view (with basic browser and device details, but not your IP
            address), actions you take (like starting a quiz, messaging the
            tutor or uploading a document), the AI model, token counts and cost behind each AI
            response, and error reports from our servers. It&apos;s tied to your Sapling account ID —
            never your name or email, and never what you type or the text of your notes, documents,
            messages or AI replies. Turning it off stops all of this within about a minute.{" "}
            {/* Underlined: a link inside running text must not rely on colour alone (WCAG 1.4.1). */}
            <Link href="/privacy" style={{ color: "var(--accent)", textDecoration: "underline" }}>Privacy Policy</Link>
          </div>
          <div style={{ fontSize: 11, color: "var(--text-muted)", marginTop: 6 }} data-testid="settings-analytics-note">
            {ANALYTICS_NOTES[state]}
            {state === "unreadable" && (
              <>
                {" "}
                <button
                  type="button"
                  className="btn btn--sm"
                  data-testid="settings-analytics-reload"
                  onClick={onReload}
                  style={{ marginLeft: 4 }}
                >
                  Try again
                </button>
              </>
            )}
            {state === "off_unsaved" && (
              <>
                {" "}
                <button
                  type="button"
                  className="btn btn--sm"
                  data-testid="settings-analytics-retry"
                  disabled={saving}
                  onClick={onRetry}
                  style={{ marginLeft: 4 }}
                >
                  Retry saving
                </button>
              </>
            )}
          </div>
        </div>
        <Toggle
          on={on}
          onChange={onChange}
          disabled={!loaded || saving}
          ariaLabelledBy="settings-analytics-label"
          testId="settings-analytics-toggle"
        />
      </div>
    </div>
  );
}

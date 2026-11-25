"use client";
import React from "react";
import Link from "next/link";
import { motion, type Variants } from "framer-motion";
import {
  getAnalyticsState,
  getServerAnalyticsState,
  subscribeAnalytics,
  type AnalyticsState,
} from "@/lib/analytics";
import { useMotionPresets, type MotionPreset } from "@/lib/motion";
import { Toggle } from "./SettingsToggle";
import styles from "./AnalyticsPreference.module.css";

/** A lib/motion preset as variants: spreading its target objects straight
 *  onto a motion element fails framer 11's prop types (TS2590), variants do not. */
function presetVariants(p: MotionPreset) {
  const variants: Variants = { initial: p.initial, animate: p.animate, exit: p.exit };
  return { variants, initial: "initial", animate: "animate", exit: "exit", transition: p.transition } as const;
}

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
  const m = useMotionPresets();

  return (
    <div className={`card ${styles.card}`} data-testid="settings-analytics">
      <div className={styles.row}>
        <div>
          <div className={styles.title} id="settings-analytics-label">
            Product analytics
          </div>
          <div className={styles.body}>
            Share how you use Sapling with PostHog, our analytics provider, so we can see what to
            improve: the app pages you view (with basic browser and device details, but not your IP
            address), actions you take (like starting a quiz, messaging the
            tutor or uploading a document), the AI model, token counts and cost behind each AI
            response, and error reports from our servers. It&apos;s tied to your Sapling account ID —
            never your name or email, and never what you type or the text of your notes, documents,
            messages or AI replies. Turning it off stops all of this within about a minute.{" "}
            {/* Underlined: a link inside running text must not rely on colour alone (WCAG 1.4.1). */}
            <Link href="/privacy" className={styles.link}>Privacy Policy</Link>
          </div>
          {/* Re-keyed per state: a new status line fades in, so the change is seen. */}
          <motion.div
            key={state}
            {...presetVariants(m.fade)}
            className={styles.note}
            data-testid="settings-analytics-note"
          >
            {ANALYTICS_NOTES[state]}
            {state === "unreadable" && (
              <>
                {" "}
                <button
                  type="button"
                  data-testid="settings-analytics-reload"
                  onClick={onReload}
                  className={`btn btn--sm ${styles.noteAction}`}
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
                  data-testid="settings-analytics-retry"
                  disabled={saving}
                  onClick={onRetry}
                  className={`btn btn--sm ${styles.noteAction}`}
                >
                  Retry saving
                </button>
              </>
            )}
          </motion.div>
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
